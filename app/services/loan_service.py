"""Loans & Financing service — the SCHEDULE is the source of truth.

Architectural rule (spec): never maintain a separate manually computed
account for every installment.  Principal outstanding, current/non-current
portions, interest accrued/paid, next due date and remaining tenure are
all DERIVED from ``loans`` + ``loan_installments``; the COA only receives
the postings.  Every journal this module creates carries the loan's unique
descriptive narration in its description AND is source-tied to the loan
row, so an owner can trace any entry back to its loan.

Borrowing (BORROWED):  Dr Bank / Cr dedicated Loan ledger (liability)
  installments: Dr Loan ledger (principal) + Dr Interest Expense / Cr Bank
Lending (GIVEN):      Dr Loan receivable ledger / Cr Bank
  receipts:     Dr Bank / Cr Loan ledger (principal) + Cr Interest Income

Only the INTEREST component is ever an expense/income — principal
repayment is never an expense (the classic ERP bug this module prevents).
"""

from __future__ import annotations

import calendar
import math
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import structlog

from app.database import fetch_many, fetch_one, insert_one, update_one
from app.repositories import account_repository as a_repo
from app.services import accounting_service

log = structlog.get_logger(__name__)

FREQUENCY_INTERVAL_MONTHS = {
    "MONTHLY": 1,
    "QUARTERLY": 3,
    "SEMI_ANNUAL": 6,
    "ANNUALLY": 12,
}


def _interval_months(frequency: str, custom_interval_months: Optional[int]) -> int:
    key = str(frequency or "MONTHLY").upper()
    if key == "CUSTOM":
        months = int(custom_interval_months or 0)
        if months <= 0:
            raise ValueError("CUSTOM frequency requires custom_interval_months > 0.")
        return months
    return FREQUENCY_INTERVAL_MONTHS.get(key, 1)


def _months_add(base: date, months: int) -> date:
    """Calendar month addition, clamping the day (31 Jan + 1mo = 28/29 Feb)."""
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def build_schedule(
    *,
    principal: float,
    annual_rate: float,
    tenure_months: int,
    frequency: str,
    custom_interval_months: Optional[int],
    first_payment_date: date,
    interest_method: str = "REDUCING",
    grace_months: int = 0,
    balloon_amount: float = 0.0,
) -> List[Dict[str, Any]]:
    """The amortization schedule (pure — no I/O, unit-testable).

    REDUCING: the periodic rate applies to each period's OPENING principal;
    the final installment is rounding-adjusted so the loan closes at
    exactly 0.  Grace periods are interest-only installments at the front.
    FLAT: total interest = P x rate x years, split evenly across periods.
    A balloon amount is extra principal due with the FINAL installment.
    """
    p = round(float(principal), 2)
    if p <= 0:
        raise ValueError("principal must be positive.")
    interval = _interval_months(frequency, custom_interval_months)
    n = int(math.ceil(tenure_months / interval))
    if n <= 0:
        raise ValueError("tenure produces zero installments.")
    periodic_rate = (float(annual_rate) / 100.0) * (interval / 12.0)
    balloon = min(round(float(balloon_amount or 0.0), 2), p)
    grace_n = min(int(math.ceil(int(grace_months or 0) / interval)), max(n - 1, 0))
    amortizing_n = n - grace_n
    method = str(interest_method or "REDUCING").upper()

    rows: List[Dict[str, Any]] = []
    if method == "FLAT":
        total_interest = p * (float(annual_rate) / 100.0) * (tenure_months / 12.0)
        per_interest = round(total_interest / n, 2)
        per_principal = round(p / n, 2)
        opening = p
        for i in range(1, n + 1):
            principal_component = round(opening, 2) if i == n else per_principal
            interest = per_interest if i > grace_n else round(opening * periodic_rate, 2)
            closing = round(opening - principal_component, 2)
            rows.append(_row(i, first_payment_date, interval, opening,
                             principal_component, interest, closing))
            opening = closing
        return rows

    # REDUCING
    net = round(p - balloon, 2)
    if amortizing_n > 0 and periodic_rate > 0:
        factor = (1 + periodic_rate) ** amortizing_n
        emi = round(net * periodic_rate * factor / (factor - 1), 2)
    else:
        emi = round(net / amortizing_n, 2) if amortizing_n else 0.0

    opening = p
    for i in range(1, n + 1):
        interest = round(opening * periodic_rate, 2)
        if i <= grace_n:
            principal_component = 0.0               # interest-only grace
        elif i == n:
            principal_component = round(opening, 2)  # closes the loan exactly
        else:
            principal_component = max(round(emi - interest, 2), 0.0)
        closing = round(opening - principal_component, 2)
        rows.append(_row(i, first_payment_date, interval, opening,
                         principal_component, interest, closing))
        opening = closing
    return rows


def _row(no: int, first: date, interval: int, opening: float,
         principal: float, interest: float, closing: float) -> Dict[str, Any]:
    return {
        "installment_no": no,
        "due_date": _months_add(first, (no - 1) * interval).isoformat(),
        "opening_principal": round(opening, 2),
        "principal_component": round(principal, 2),
        "interest_component": round(interest, 2),
        "total_due": round(principal + interest, 2),
        "closing_principal": round(max(closing, 0.0), 2),
    }


# ---------------------------------------------------------------------------
# Account resolution — headings are ensured; each loan gets its OWN
# dedicated ledger (named with the narration) so owners can trace it.
# ---------------------------------------------------------------------------

async def _find_account(
    organization_id: uuid.UUID, name: str, account_type: str
) -> Optional[Dict[str, Any]]:
    try:
        rows = await a_repo.search_accounts(organization_id, query=name, limit=25)
    except Exception:  # noqa: BLE001 — search is best-effort
        return None
    for row in rows or ():
        if (str(row.get("name") or "").strip().lower() == name.strip().lower()
                and row.get("account_type") == account_type
                and row.get("is_active") is not False):
            return row
    return None


async def _ensure_heading(
    organization_id: uuid.UUID, name: str, account_type: str,
    normal_balance: str, code_base: str,
    parent: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    existing = await _find_account(organization_id, name, account_type)
    if existing is not None:
        return existing
    try:
        code = await a_repo.next_available_code(organization_id, code_base)
        created = await a_repo.create_account(
            organization_id=organization_id, code=code, name=name,
            account_type=account_type, normal_balance=normal_balance,
            parent_account_id=(uuid.UUID(str(parent["id"])) if parent else None),
            description="Loan subsystem heading (auto-created).",
        )
        log.info("loan.heading_created", name=name, code=created.get("code"))
        return created
    except Exception as exc:  # noqa: BLE001
        log.warning("loan.heading_create_failed", name=name, error=str(exc)[:200])
        return None


async def _ensure_loan_ledger(
    organization_id: uuid.UUID, narration: str, account_type: str,
    normal_balance: str, heading: Dict[str, Any], code_base: str,
) -> Optional[Dict[str, Any]]:
    """The per-loan CHILD ledger, named with the unique narration."""
    existing = await _find_account(organization_id, narration, account_type)
    if existing is not None:
        return existing
    try:
        code = await a_repo.next_available_code(organization_id, code_base)
        return await a_repo.create_account(
            organization_id=organization_id, code=code, name=narration,
            account_type=account_type, normal_balance=normal_balance,
            parent_account_id=uuid.UUID(str(heading["id"])),
            description=f"Dedicated loan ledger for '{narration}'.",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("loan.ledger_create_failed", narration=narration,
                    error=str(exc)[:200])
        return None


async def _resolve_cash_account(organization_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    for name in ("Bank", "Bank Account", "Cash", "Cash Account"):
        row = await _find_account(organization_id, name, "ASSET")
        if row is not None and not str(row.get("name") or "").lower().startswith("bank reconcil"):
            return row
    return None


# ---------------------------------------------------------------------------
# Loan lifecycle
# ---------------------------------------------------------------------------

async def create_loan(
    organization_id: uuid.UUID,
    *,
    direction: str,
    narration: str,
    counterparty: str,
    principal: float,
    loan_date: str,
    first_payment_date: str,
    tenure_months: int,
    frequency: str,
    interest_rate: float = 0.0,
    interest_method: str = "REDUCING",
    custom_interval_months: Optional[int] = None,
    grace_months: int = 0,
    balloon_amount: float = 0.0,
    fees_charges: float = 0.0,
    purpose: Optional[str] = None,
    currency_code: str = "PKR",
    cash_account_id: Optional[uuid.UUID] = None,
    party_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create a loan + its schedule + its initial journal (auto-posted).

    BORROWED: Dr Bank / Cr dedicated loan ledger.  GIVEN: Dr loan
    receivable ledger / Cr Bank.  The journal description IS the
    narration, and source_type/source_id tie it to the loan row.
    Fails (ValueError) on a duplicate narration — the identity must stay
    unique per organisation.
    """
    dirn = str(direction or "").strip().upper()
    if dirn not in ("BORROWED", "GIVEN"):
        raise ValueError("direction must be BORROWED or GIVEN.")
    name = str(narration or "").strip()
    if not name:
        raise ValueError("narration is required (e.g. 'Loan - HBL - Vehicle Financing - 2026').")
    if not str(counterparty or "").strip():
        raise ValueError("counterparty (lender/borrower) is required.")

    dup = await fetch_one(
        "loans",
        filters={"organization_id": str(organization_id), "narration": name},
    )
    if dup:
        raise ValueError(
            f"A loan named '{name}' already exists — narrations must be unique "
            "so owners can identify each facility."
        )

    # ---- GL wiring: headings ensured, per-loan ledger created ------------
    cash = (await a_repo.get_account(organization_id, account_id=cash_account_id)
            if cash_account_id else None) or await _resolve_cash_account(organization_id)
    if not cash:
        raise ValueError("Cannot resolve a Bank/Cash account for the loan proceeds.")

    is_borrowed = dirn == "BORROWED"
    if is_borrowed:
        heading = await _ensure_heading(
            organization_id, "Long-Term Loans", "LIABILITY", "CREDIT", "2300",
            parent=await _ensure_heading(
                organization_id, "Non-Current Liabilities", "LIABILITY",
                "CREDIT", "2910"))
        interest_heading = await _ensure_heading(
            organization_id, "Finance Costs", "EXPENSE", "DEBIT", "6700")
        interest_leaf = await _ensure_heading(
            organization_id, "Interest Expense", "EXPENSE", "DEBIT", "6720",
            parent=interest_heading) if interest_heading else None
        ledger_type, ledger_balance, code_base = "LIABILITY", "CREDIT", "2310"
    else:
        heading = await _ensure_heading(
            organization_id, "Loans Receivable", "ASSET", "DEBIT", "1350",
            parent=await _ensure_heading(
                organization_id, "Non-Current Assets", "ASSET", "DEBIT", "1910"))
        interest_heading = await _ensure_heading(
            organization_id, "Other Income", "REVENUE", "CREDIT", "4900")
        interest_leaf = await _ensure_heading(
            organization_id, "Interest Income", "REVENUE", "CREDIT", "4910",
            parent=interest_heading) if interest_heading else None
        ledger_type, ledger_balance, code_base = "ASSET", "DEBIT", "1360"
    if not heading:
        raise ValueError("Cannot resolve/create the loan heading account.")
    ledger = await _ensure_loan_ledger(
        organization_id, name, ledger_type, ledger_balance, heading, code_base)
    if not ledger:
        raise ValueError("Cannot create the dedicated loan ledger.")


    # ---- Schedule (source of truth) --------------------------------------
    first_pay = date.fromisoformat(str(first_payment_date))
    schedule = build_schedule(
        principal=principal, annual_rate=interest_rate,
        tenure_months=int(tenure_months), frequency=frequency,
        custom_interval_months=custom_interval_months,
        first_payment_date=first_pay, interest_method=interest_method,
        grace_months=grace_months, balloon_amount=balloon_amount,
    )

    loan = await insert_one("loans", data={
        "organization_id": str(organization_id),
        "direction": dirn,
        "narration": name,
        "counterparty": str(counterparty).strip(),
        "purpose": purpose,
        "principal": round(float(principal), 2),
        "currency_code": str(currency_code or "PKR").upper()[:3],
        "loan_date": str(loan_date),
        "interest_rate": round(float(interest_rate), 5),
        "interest_method": str(interest_method or "REDUCING").upper(),
        "tenure_months": int(tenure_months),
        "frequency": str(frequency or "MONTHLY").upper(),
        "custom_interval_months": custom_interval_months,
        "first_payment_date": str(first_payment_date),
        "maturity_date": schedule[-1]["due_date"] if schedule else None,
        "grace_months": int(grace_months or 0),
        "balloon_amount": round(float(balloon_amount or 0), 2),
        "fees_charges": round(float(fees_charges or 0), 2),
        "cash_account_id": str(cash["id"]),
        "loan_account_id": str(ledger["id"]),
        "interest_account_id": str(interest_leaf["id"]) if interest_leaf else None,
        "party_id": str(party_id) if party_id else None,
        "status": "ACTIVE",
    })
    loan_id = uuid.UUID(str(loan["id"]))

    for row in schedule:
        await insert_one("loan_installments", data={
            "organization_id": str(organization_id),
            "loan_id": str(loan_id),
            "installment_no": row["installment_no"],
            "due_date": row["due_date"],
            "opening_principal": row["opening_principal"],
            "principal_component": row["principal_component"],
            "interest_component": row["interest_component"],
            "total_due": row["total_due"],
            "closing_principal": row["closing_principal"],
            "status": "SCHEDULED",
        })

    # ---- Initial journal: proceeds disbursed / advanced ------------------
    amount = round(float(principal), 2)
    if is_borrowed:
        lines = [
            {"account_id": str(cash["id"]), "description": name,
             "debit": amount, "credit": 0},
            {"account_id": str(ledger["id"]), "description": name,
             "debit": 0, "credit": amount},
        ]
    else:
        lines = [
            {"account_id": str(ledger["id"]), "description": name,
             "debit": amount, "credit": 0},
            {"account_id": str(cash["id"]), "description": name,
             "debit": 0, "credit": amount},
        ]
    prepared = await accounting_service.prepare_journal(
        organization_id=organization_id, transaction_date=str(loan_date),
        description=name, lines=lines,
        source_type="loan", source_id=loan_id, currency_code=loan["currency_code"],
    )
    entry = (prepared or {}).get("entry") or {}
    journal = {"entry_id": None, "posted": False}
    if entry.get("id"):
        try:
            entry_id = uuid.UUID(str(entry["id"]))
            await accounting_service.validate_journal(entry_id=entry_id)
            await accounting_service.post_journal(entry_id=entry_id)
            await update_one("loans", filters={"id": str(loan_id)},
                             data={"initial_entry_id": str(entry_id)})
            journal = {"entry_id": str(entry_id), "posted": True}
        except Exception as exc:  # noqa: BLE001 — honest warning, never fake
            log.warning("loan.initial_journal_failed", loan_id=str(loan_id),
                        error=str(exc)[:200])
            journal = {"entry_id": entry.get("id"), "posted": False,
                       "warning": str(exc)[:300]}

    log.info("loan.created", loan_id=str(loan_id), direction=dirn,
             narration=name, principal=amount, installments=len(schedule))
    return {
        "loan": {**loan, "maturity_date": schedule[-1]["due_date"] if schedule else None},
        "schedule": schedule,
        "journal": journal,
        "loan_ledger": ledger,
        "cash_account": cash,
        "interest_account": interest_leaf,
    }



async def record_installment_payment(
    organization_id: uuid.UUID,
    *,
    loan_id: uuid.UUID,
    installment_no: int,
    amount_paid: Optional[float] = None,
    paid_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Settle one installment — PRINCIPAL vs INTEREST segregated from the
    schedule (never guessed).  The cash side follows the direction:

      BORROWED: Dr Loan ledger (principal) + Dr Interest Expense / Cr Bank
      GIVEN:    Dr Bank / Cr Loan ledger (principal) + Cr Interest Income

    ``amount_paid`` defaults to the installment's total_due.  A short pay
    marks the row PARTIAL (remaining stays due); a full pay marks PAID and
    flips the loan to COMPLETED when nothing remains.  Only the interest
    component ever reaches the P&L.
    """
    loan_rows = await fetch_many(
        "loans", filters={"organization_id": str(organization_id),
                          "id": str(loan_id)}, limit=1)
    if not loan_rows:
        raise ValueError("Loan not found in this organization.")
    loan = loan_rows[0]

    inst_rows = await fetch_many(
        "loan_installments",
        filters={"loan_id": str(loan_id), "installment_no": int(installment_no)},
        limit=1,
    )
    if not inst_rows:
        raise ValueError(f"Installment #{installment_no} does not exist for this loan.")
    inst = inst_rows[0]
    if str(inst.get("status")) in ("PAID", "WAIVED"):
        raise ValueError(
            f"Installment #{installment_no} is already {inst.get('status')}.")

    remaining = round(float(inst["total_due"]) - float(inst.get("paid_amount") or 0), 2)
    pay = round(float(amount_paid) if amount_paid is not None else remaining, 2)
    if pay <= 0:
        raise ValueError("amount_paid must be positive.")
    pay = min(pay, remaining)

    # Segregation ratio: principal first is NOT assumed — split by the
    # schedule's own proportions so a partial payment never distorts the
    # principal/interest boundary.
    principal_due = round(float(inst["principal_component"]), 2)
    interest_due = round(float(inst["interest_component"]), 2)
    if pay >= remaining:
        principal_part, interest_part = principal_due, interest_due
    else:
        share = pay / remaining if remaining else 0.0
        interest_part = round(min(interest_due * share, pay), 2)
        principal_part = round(pay - interest_part, 2)

    paid_total = round(float(inst.get("paid_amount") or 0) + pay, 2)
    is_borrowed = str(loan.get("direction")) == "BORROWED"
    entry_id: Optional[uuid.UUID] = None

    if is_borrowed:
        lines = [
            {"account_id": str(loan["loan_account_id"]),
             "description": str(loan["narration"]), "debit": principal_part, "credit": 0},
        ]
        if interest_part > 0 and loan.get("interest_account_id"):
            lines.append({"account_id": str(loan["interest_account_id"]),
                          "description": str(loan["narration"]),
                          "debit": interest_part, "credit": 0})
        lines.append({"account_id": str(loan["cash_account_id"]),
                      "description": str(loan["narration"]),
                      "debit": 0, "credit": pay})
    else:
        lines = [
            {"account_id": str(loan["cash_account_id"]),
             "description": str(loan["narration"]), "debit": pay, "credit": 0},
            {"account_id": str(loan["loan_account_id"]),
             "description": str(loan["narration"]), "debit": 0, "credit": principal_part},
        ]
        if interest_part > 0 and loan.get("interest_account_id"):
            lines.append({"account_id": str(loan["interest_account_id"]),
                          "description": str(loan["narration"]),
                          "debit": 0, "credit": interest_part})

    prepared = await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=str(paid_date or date.today().isoformat()),
        description=f"{loan['narration']} — installment #{installment_no}",
        lines=lines, source_type="loan_installment",
        source_id=uuid.UUID(str(inst["id"])),
        currency_code=str(loan.get("currency_code") or "PKR"),
    )
    entry = (prepared or {}).get("entry") or {}
    if entry.get("id"):
        entry_id = uuid.UUID(str(entry["id"]))
        await accounting_service.validate_journal(entry_id=entry_id)
        await accounting_service.post_journal(entry_id=entry_id)


    new_status = "PAID" if paid_total >= remaining - 0.005 else "PARTIAL"
    prior_principal_paid = float(inst.get("principal_paid") or 0)
    prior_interest_paid = float(inst.get("interest_paid") or 0)
    await update_one("loan_installments", filters={"id": str(inst["id"])}, data={
        "status": new_status,
        "paid_amount": paid_total,
        "principal_paid": round(prior_principal_paid + principal_part, 2),
        "interest_paid": round(prior_interest_paid + interest_part, 2),
        "paid_date": str(paid_date or date.today().isoformat()),
        "journal_entry_id": str(entry_id) if entry_id else None,
    })

    # Settle the sweep's PENDING event (if any): the proposed journal this
    # installment carried is now actually posted.
    try:
        await update_one(
            "loan_payment_events",
            filters={"installment_id": str(inst["id"]), "status": "PENDING"},
            data={"status": "COMPLETED",
                  "resolved_at": date.today().isoformat()},
        )
    except Exception as exc:  # noqa: BLE001 — event bookkeeping is secondary
        log.warning("loan.event_settle_failed", installment_id=str(inst["id"]),
                    error=str(exc)[:200])

    # Loan completion: every installment settled.
    unpaid = await fetch_many(
        "loan_installments",
        filters={"loan_id": str(loan_id)}, limit=500,
    )
    outstanding = [r for r in unpaid or ()
                   if str(r.get("status")) not in ("PAID", "WAIVED")]
    if not outstanding:
        await update_one("loans", filters={"id": str(loan_id)},
                         data={"status": "COMPLETED"})

    log.info("loan.installment_paid", loan_id=str(loan_id),
             installment_no=installment_no, principal=principal_part,
             interest=interest_part, cash=pay, status=new_status)
    return {
        "installment_no": installment_no,
        "principal_component": principal_part,
        "interest_component": interest_part,
        "cash_amount": pay,
        "status": new_status,
        "journal_entry_id": str(entry_id) if entry_id else None,
        "loan_status": "COMPLETED" if not outstanding else str(loan.get("status")),
    }


# ---------------------------------------------------------------------------
# Queries — everything derived, nothing manually maintained
# ---------------------------------------------------------------------------

async def due_installments(
    organization_id: uuid.UUID, *, as_of: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """Installments due on/before *as_of* (default today) — the agent's
    scheduled-event sweep reads this to propose due-entry journals."""
    rows = await fetch_many(
        "v_loan_installment_schedule",
        filters={"organization_id": str(organization_id)}, limit=500,
    )
    cutoff = str(as_of or date.today().isoformat())
    return [r for r in rows or ()
            if str(r.get("live_status")) in ("DUE", "OVERDUE", "DUE_SOON")
            and str(r.get("due_date")) <= cutoff
            or str(r.get("live_status")) == "OVERDUE"]


async def get_schedule(
    organization_id: uuid.UUID, *, loan_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "v_loan_installment_schedule",
        filters={"organization_id": str(organization_id), "loan_id": str(loan_id)},
        order="installment_no.asc", limit=500,
    )


async def get_loan(
    organization_id: uuid.UUID, *, loan_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    rows = await fetch_many(
        "v_loans", filters={"organization_id": str(organization_id),
                            "id": str(loan_id)}, limit=1)
    return rows[0] if rows else None


async def list_loans(
    organization_id: uuid.UUID, *, direction: Optional[str] = None,
    status: Optional[str] = None, limit: int = 100,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if direction:
        filters["direction"] = str(direction).upper()
    if status:
        filters["status"] = str(status).upper()
    return await fetch_many("v_loans", filters=filters,
                            order="created_at.desc", limit=limit)



# ---------------------------------------------------------------------------
# Scheduled-event engine (the worker's cron): DUE does NOT mean PAID
# ---------------------------------------------------------------------------

async def run_due_installment_sweep(
    *, as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Daily sweep across ALL orgs (service context — called by the worker).

    For every ACTIVE loan: installments whose due date has arrived move
    stored status SCHEDULED -> DUE (or OVERDUE when already past due), and a
    PENDING ``loan_payment_events`` row records the proposed segregated
    journal.  NOTHING is posted — a due date alone never moves cash; the
    owner settles via record_loan_repayment (page button / chat), which
    posts the journal and marks the event COMPLETED.  Idempotent: the
    per-installment unique index means re-running never duplicates events.
    """
    today = str(as_of or date.today().isoformat())
    orgs = await fetch_many(
        "loans", filters={"status": "ACTIVE"}, limit=500)
    org_ids = {str(o.get("organization_id")) for o in orgs or ()}

    marked_due = marked_overdue = events_created = 0
    for org_text in sorted(org_ids):
        org = uuid.UUID(org_text)
        rows = await fetch_many(
            "v_loan_installment_schedule",
            filters={"organization_id": org_text}, limit=1000)
        for row in rows or ():
            if str(row.get("live_status")) not in ("DUE", "OVERDUE"):
                continue
            stored = str(row.get("status") or "SCHEDULED")
            if stored in ("PAID", "WAIVED", "PARTIAL"):
                continue
            inst_id = uuid.UUID(str(row["id"]))
            target = "OVERDUE" if str(row.get("due_date")) < today else "DUE"
            if stored != target:
                await update_one(
                    "loan_installments", filters={"id": str(inst_id)},
                    data={"status": target})
                if target == "OVERDUE":
                    marked_overdue += 1
                else:
                    marked_due += 1
            existing = await fetch_many(
                "loan_payment_events",
                filters={"installment_id": str(inst_id)}, limit=1)
            if existing:
                continue  # history (or already pending) — never duplicate
            await insert_one("loan_payment_events", data={
                "organization_id": org_text,
                "loan_id": str(row["loan_id"]),
                "installment_id": str(inst_id),
                "event_type": "INSTALLMENT_DUE",
                "status": "PENDING",
                "proposed": {
                    "narration": row.get("narration"),
                    "direction": row.get("direction"),
                    "installment_no": row.get("installment_no"),
                    "due_date": row.get("due_date"),
                    "principal": float(row.get("principal_component") or 0),
                    "interest": float(row.get("interest_component") or 0),
                    "total": float(row.get("total_due") or 0),
                },
            })
            events_created += 1

    log.info("loan.due_sweep", as_of=today, marked_due=marked_due,
             marked_overdue=marked_overdue, events_created=events_created)
    return {"as_of": today, "marked_due": marked_due,
            "marked_overdue": marked_overdue, "events_created": events_created}



# ---------------------------------------------------------------------------
# Restructure / write-off — controlled lifecycle changes
# ---------------------------------------------------------------------------

async def _remaining_principal(
    organization_id: uuid.UUID, loan_id: uuid.UUID
) -> Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """REAL outstanding (principal - persisted principal_paid) plus the
    installment splits into (kept, rebuildable).  Kept = anything cash has
    touched (PAID / PARTIAL / WAIVED); rebuildable = pure schedule rows."""
    rows = await fetch_many(
        "loan_installments",
        filters={"organization_id": str(organization_id), "loan_id": str(loan_id)},
        order="installment_no.asc", limit=500,
    )
    rows = rows or []
    principal_paid = round(sum(float(r.get("principal_paid") or 0) for r in rows), 2)
    loan_rows = await fetch_many(
        "loans", filters={"organization_id": str(organization_id),
                          "id": str(loan_id)}, limit=1)
    if not loan_rows:
        raise ValueError("Loan not found in this organization.")
    outstanding = round(float(loan_rows[0]["principal"]) - principal_paid, 2)
    kept = [r for r in rows if str(r.get("status")) in ("PAID", "PARTIAL", "WAIVED")
            or float(r.get("paid_amount") or 0) > 0]
    rebuildable = [r for r in rows if r not in kept]
    return outstanding, kept, rebuildable


async def restructure_loan(
    organization_id: uuid.UUID,
    *,
    loan_id: uuid.UUID,
    first_payment_date: str,
    tenure_months: int,
    frequency: str,
    interest_rate: float,
    interest_method: str = "REDUCING",
    custom_interval_months: Optional[int] = None,
    grace_months: int = 0,
    balloon_amount: float = 0.0,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Rebuild the UNPAID future schedule under new terms.

    Cash already moved (PAID / PARTIAL installments) is never touched; the
    REAL outstanding principal is re-amortized from ``first_payment_date``
    under the new terms, numbering continues after the kept rows, and no
    journal is posted — a restructure changes future terms, not the ledger
    balance.  Old and new terms are recorded in ``loan_restructurings``.
    """
    outstanding, kept, rebuildable = await _remaining_principal(
        organization_id, loan_id)
    if outstanding <= 0:
        raise ValueError("Loan has no outstanding principal to restructure.")

    loan_rows = await fetch_many(
        "loans", filters={"organization_id": str(organization_id),
                          "id": str(loan_id)}, limit=1)
    loan = loan_rows[0]

    old_terms = {
        "tenure_months": loan.get("tenure_months"),
        "frequency": loan.get("frequency"),
        "interest_rate": float(loan.get("interest_rate") or 0),
        "interest_method": loan.get("interest_method"),
        "first_payment_date": loan.get("first_payment_date"),
        "maturity_date": loan.get("maturity_date"),
        "grace_months": loan.get("grace_months"),
        "balloon_amount": float(loan.get("balloon_amount") or 0),
    }
    new_terms = {
        "tenure_months": int(tenure_months),
        "frequency": str(frequency or "MONTHLY").upper(),
        "interest_rate": round(float(interest_rate), 5),
        "interest_method": str(interest_method or "REDUCING").upper(),
        "first_payment_date": str(first_payment_date),
        "grace_months": int(grace_months or 0),
        "balloon_amount": round(float(balloon_amount or 0), 2),
    }

    for row in rebuildable:
        await update_one(
            "loan_installments", filters={"id": str(row["id"])},
            data={"status": "WAIVED"})

    schedule = build_schedule(
        principal=outstanding, annual_rate=interest_rate,
        tenure_months=int(tenure_months), frequency=frequency,
        custom_interval_months=custom_interval_months,
        first_payment_date=date.fromisoformat(str(first_payment_date)),
        interest_method=interest_method, grace_months=grace_months,
        balloon_amount=balloon_amount,
    )
    next_no = max((int(r.get("installment_no") or 0) for r in kept), default=0)
    created: List[Dict[str, Any]] = []
    for row in schedule:
        next_no += 1
        await insert_one("loan_installments", data={
            "organization_id": str(organization_id),
            "loan_id": str(loan_id),
            "installment_no": next_no,
            "due_date": row["due_date"],
            "opening_principal": row["opening_principal"],
            "principal_component": row["principal_component"],
            "interest_component": row["interest_component"],
            "total_due": row["total_due"],
            "closing_principal": row["closing_principal"],
            "status": "SCHEDULED",
        })
        created.append({**row, "installment_no": next_no})

    await insert_one("loan_restructurings", data={
        "organization_id": str(organization_id),
        "loan_id": str(loan_id),
        "outstanding_principal": outstanding,
        "old_terms": old_terms,
        "new_terms": new_terms,
        "reason": reason,
    })
    await update_one("loans", filters={"id": str(loan_id)}, data={
        "tenure_months": int(tenure_months),
        "frequency": str(frequency or "MONTHLY").upper(),
        "interest_rate": round(float(interest_rate), 5),
        "interest_method": str(interest_method or "REDUCING").upper(),
        "first_payment_date": str(first_payment_date),
        "maturity_date": schedule[-1]["due_date"] if schedule else None,
        "grace_months": int(grace_months or 0),
        "balloon_amount": round(float(balloon_amount or 0), 2),
        "status": "ACTIVE",
    })
    log.info("loan.restructured", loan_id=str(loan_id),
             outstanding=outstanding, new_installments=len(created))
    return {"loan_id": str(loan_id), "outstanding": outstanding,
            "waived": len(rebuildable), "kept": len(kept),
            "new_schedule": created}


async def write_off_loan(
    organization_id: uuid.UUID,
    *,
    loan_id: uuid.UUID,
    write_off_date: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Write off the REAL remaining principal with a segregated journal.

    BORROWED (lender forgives): Dr Loan ledger / Cr 'Loan Forgiveness Gain'
        (REVENUE under Other Income — a forgiveness is income, never a
        negative expense).
    GIVEN (recoverability gone): Dr 'Loan Impairment Loss' (EXPENSE under
        Other Expenses) / Cr Loan receivable ledger.
    Unpaid installments are WAIVED (the schedule stays as history), status
    flips to WRITTEN_OFF, and every line carries the loan narration.
    """
    outstanding, kept, rebuildable = await _remaining_principal(
        organization_id, loan_id)
    if outstanding <= 0:
        raise ValueError("Loan has no outstanding principal to write off.")

    loan_rows = await fetch_many(
        "loans", filters={"organization_id": str(organization_id),
                          "id": str(loan_id)}, limit=1)
    loan = loan_rows[0]
    is_borrowed = str(loan.get("direction")) == "BORROWED"
    narration = str(loan.get("narration"))

    if is_borrowed:
        gain = await _ensure_heading(
            organization_id, "Loan Forgiveness Gain", "REVENUE", "CREDIT",
            "4920", parent=await _ensure_heading(
                organization_id, "Other Income", "REVENUE", "CREDIT", "4900"))
        if not gain:
            raise ValueError("Cannot resolve/create the Loan Forgiveness Gain account.")
        lines = [
            {"account_id": str(loan["loan_account_id"]),
             "description": narration, "debit": outstanding, "credit": 0},
            {"account_id": str(gain["id"]),
             "description": narration, "debit": 0, "credit": outstanding},
        ]
    else:
        loss = await _ensure_heading(
            organization_id, "Loan Impairment Loss", "EXPENSE", "DEBIT",
            "6850", parent=await _ensure_heading(
                organization_id, "Other Expenses", "EXPENSE", "DEBIT", "6800"))
        if not loss:
            raise ValueError("Cannot resolve/create the Loan Impairment Loss account.")
        lines = [
            {"account_id": str(loss["id"]),
             "description": narration, "debit": outstanding, "credit": 0},
            {"account_id": str(loan["loan_account_id"]),
             "description": narration, "debit": 0, "credit": outstanding},
        ]

    for row in rebuildable:
        await update_one(
            "loan_installments", filters={"id": str(row["id"])},
            data={"status": "WAIVED"})

    prepared = await accounting_service.prepare_journal(
        organization_id=organization_id, transaction_date=str(write_off_date),
        description=f"{narration} — write-off",
        lines=lines, source_type="loan_writeoff",
        source_id=uuid.UUID(str(loan_id)),
        currency_code=str(loan.get("currency_code") or "PKR"),
    )
    entry = (prepared or {}).get("entry") or {}
    journal: Dict[str, Any] = {"entry_id": None, "posted": False}
    if entry.get("id"):
        entry_id = uuid.UUID(str(entry["id"]))
        await accounting_service.validate_journal(entry_id=entry_id)
        await accounting_service.post_journal(entry_id=entry_id)
        journal = {"entry_id": str(entry_id), "posted": True}

    await update_one("loans", filters={"id": str(loan_id)}, data={
        "status": "WRITTEN_OFF",
        "updated_at": date.today().isoformat(),
    })
    log.info("loan.written_off", loan_id=str(loan_id), direction=loan.get("direction"),
             amount=outstanding, reason=reason)
    return {"loan_id": str(loan_id), "amount_written_off": outstanding,
            "direction": loan.get("direction"), "journal": journal,
            "status": "WRITTEN_OFF", "reason": reason}

