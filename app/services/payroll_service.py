"""
Payroll Service — salary runs and salary payments (Employees, Phase 2).

The pair an accountant actually books:

    run_payroll          Dr 6010 Salaries           Cr 2130 Accrued Salaries
                         (payment_method=PAID credits bank/cash instead)
    pay_employee_salary  Dr 2130 Accrued Salaries   Cr bank/cash
                         (falls back to Dr 6010 when the organisation has no
                          accrued-salaries ledger — disclosed in the result)

Design contract (LLM-first, deterministic execution):

* every amount is COMPUTED from the employee's records — the basic salary
  plus the MONTHLY allowance components in force on the payroll date, net of
  the MONTHLY deductions — never taken from the model's sentence;
* ONE-TIME / ANNUAL components are NOT part of a recurring run (a second run
  would pay them again); they are REPORTED back, never silently dropped;
* the journal is posted through ``accounting_service`` (prepare → validate →
  post) — the same verified lifecycle the asset and expense paths use;
* every rejection message is written for the MODEL to act on: it names what
  to ask the user instead of silently defaulting.
"""

from __future__ import annotations

import re
import uuid
from datetime import date as _date
from typing import Any, Dict, List, Optional

import structlog

from app.database import fetch_many
from app.repositories import employee_repository as repo
# The deterministic GL primitives are SHARED with the fixed-asset lifecycle —
# reused, never duplicated, so account resolution can never drift apart.
from app.services import accounting_service
from app.services import employee_service
from app.services.fixed_asset_service import (
    _post_journal,
    _resolve_gl_account,
    _resolve_settlement_account,
)

log = structlog.get_logger(__name__)


class PayrollInputError(ValueError):
    """A correctable input problem — the message is written for the model."""


#: hard ceiling on one run — beyond this the request must be split (the
#: journal, the reviewer and the confirmation card all stay reviewable).
_MAX_EMPLOYEES_PER_RUN = 200

#: employees in these states are never paid by a run.
_TERMINAL_STATUSES = frozenset({"RESIGNED", "TERMINATED"})

#: payment_method synonyms — PAID moves money now, ACCRUED books the liability.
_SETTLEMENT_SYNONYMS = {
    "PAID": "PAID", "PAY": "PAID", "PAYMENT": "PAID", "CASH": "PAID",
    "BANK": "PAID", "PAID_NOW": "PAID", "PAY_NOW": "PAID", "IMMEDIATE": "PAID",
    "IMMEDIATELY": "PAID", "TRANSFER": "PAID", "TRANSFERRED": "PAID",
    "ALREADY_PAID": "PAID", "DISBURSED": "PAID", "PAID_OUT": "PAID",
    "ACCRUED": "ACCRUED", "ACCRUE": "ACCRUED", "ACCRUAL": "ACCRUED",
    "UNPAID": "ACCRUED", "NOT_PAID": "ACCRUED", "OWED": "ACCRUED",
    "ON_ACCOUNT": "ACCRUED", "PAYABLE": "ACCRUED", "PENDING": "ACCRUED",
}

#: deterministic salary-account keywords (a UNIQUE EXPENSE-name match wins).
_SALARY_ACCOUNT_KEYWORDS = ("salar", "wage", "payroll")
#: the accrued-liability side of an accrue-then-pay cycle.
_ACCRUED_ACCOUNT_KEYWORDS = (
    "accrued salar", "salaries payable", "salary payable", "salary accrual",
    "accrued payroll", "wages payable", "accrued wages",
)


def _clean_date(value: Any, *, label: str, default_today: bool = False) -> str:
    """Mechanical date resolution (server-side truth); never guessed."""
    from app.date_parser import parse_transaction_date

    text = str(value or "").strip()
    if not text:
        if default_today:
            return _date.today().isoformat()
        raise PayrollInputError(
            f"{label} is required — ask the user for it (YYYY-MM-DD or DD/MM/YYYY)."
        )
    parsed = parse_transaction_date(text)
    if not parsed.ok:
        raise PayrollInputError(
            f"{label} '{text}' is not a parseable date — {parsed.error} "
            "Ask the user again."
        )
    return str(parsed.iso_date)


def _clean_settlement(value: Any) -> str:
    """Map the model's wording onto PAID / ACCRUED — the two real treatments."""
    text = re.sub(r"[\s\-]+", "_", str(value or "").strip().upper())
    if not text:
        return "ACCRUED"
    settlement = _SETTLEMENT_SYNONYMS.get(text)
    if not settlement:
        raise PayrollInputError(
            f"payment_method '{value}' is not recognised — use ACCRUED (the "
            "salary is owed, credit Accrued Salaries) or PAID (money leaves "
            "the bank/cash now). Decide from the user's sentence, then pass "
            "the value."
        )
    return settlement


def _clean_amount(value: Any, *, label: str) -> float:
    """Numeric validation for an explicitly stated amount ("1,25,000" ok)."""
    if value is None or value == "":
        raise PayrollInputError(f"{label} is missing — ask the user for the amount.")
    if isinstance(value, str):
        stripped = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
        try:
            value = float(stripped)
        except (TypeError, ValueError):
            raise PayrollInputError(
                f"{label} '{value}' is not a number — ask the user for the amount."
            ) from None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PayrollInputError(f"{label} is not a number — ask the user for the amount.")
    if number <= 0:
        raise PayrollInputError(f"{label} must be greater than zero.")
    return round(number, 2)


def _period_label(transaction_date: str) -> str:
    """'2026-09-30' → 'September 2026' (the month a run covers)."""
    try:
        stamp = _date.fromisoformat(transaction_date)
    except (TypeError, ValueError):
        return transaction_date
    return stamp.strftime("%B %Y")



def _eligibility_reason(employee: Dict[str, Any], as_of: str) -> Optional[str]:
    """Why a roster member is NOT paid by a run of *as_of* — else ``None``."""
    status = str(employee.get("status") or "ACTIVE").upper()
    if status in _TERMINAL_STATUSES:
        return f"status is {status}"
    if employee.get("is_active") is False:
        return "the record is inactive"
    joined = str(employee.get("date_of_joining") or "")
    if joined and joined > as_of:
        return f"joins on {joined} (after the payroll date)"
    return None


def _in_force(component: Dict[str, Any], as_of: str) -> bool:
    """Is the component effective on *as_of*? (inclusive window)."""
    start = str(component.get("effective_from") or "")
    end = component.get("effective_to")
    if start and start > as_of:
        return False
    if end and str(end) < as_of:
        return False
    return True


def _compute_pay(
    employee: Dict[str, Any],
    components: List[Dict[str, Any]],
    as_of: str,
) -> Dict[str, Any]:
    """Deterministic per-employee entitlement for *as_of*.

    gross = basic salary + MONTHLY allowance components in force
    net   = gross − MONTHLY deductions in force

    ONE-TIME / ANNUAL components are collected into ``deferred`` and returned
    to the caller for disclosure — a recurring run must never pay them twice.
    """
    basic = round(float(employee.get("basic_salary") or 0), 2)
    allowances_total = 0.0
    deductions_total = 0.0
    applied: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    for component in components or []:
        if not _in_force(component, as_of):
            continue
        amount = round(float(component.get("amount") or 0), 2)
        kind = str(component.get("component_kind") or "ALLOWANCE").upper()
        frequency = str(component.get("frequency") or "MONTHLY").upper()
        row = {
            "description": component.get("description"),
            "component_kind": kind,
            "frequency": frequency,
            "amount": amount,
        }
        if frequency != "MONTHLY":
            row["reason"] = (
                f"{frequency} component — a recurring run does not pay it "
                "(record it separately or set it up as MONTHLY)"
            )
            deferred.append(row)
            continue
        if kind == "DEDUCTION":
            deductions_total = round(deductions_total + amount, 2)
        else:
            allowances_total = round(allowances_total + amount, 2)
        applied.append(row)

    gross = round(basic + allowances_total, 2)
    net = round(gross - deductions_total, 2)
    return {
        "employee_id": str(employee.get("id")),
        "employee_code": employee.get("employee_code"),
        "full_name": employee.get("full_name"),
        "basic_salary": basic,
        "allowances_total": allowances_total,
        "deductions_total": deductions_total,
        "gross_pay": gross,
        "net_pay": net,
        "components": applied,
        "deferred": deferred,
        "status": str(employee.get("status") or "ACTIVE").upper(),
    }


def _clean_uuid(value: Any, *, label: str) -> Optional[uuid.UUID]:
    """Optional account-id argument — a malformed id is a QUESTION, not a guess."""
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise PayrollInputError(
            f"{label} '{value}' is not a valid account id — pass the account's "
            "uuid, or omit it."
        ) from None


async def _resolve_salary_expense_account(
    organization_id: uuid.UUID, *, explicit_id: Any
) -> Dict[str, Any]:
    try:
        account = await _resolve_gl_account(
            organization_id,
            account_type="EXPENSE",
            keywords=_SALARY_ACCOUNT_KEYWORDS,
            explicit_id=_clean_uuid(explicit_id, label="salary_expense_account_id"),
        )
    except ValueError as exc:
        raise PayrollInputError(str(exc)) from None
    if not account:
        raise PayrollInputError(
            "No single salaries/wages EXPENSE account could be determined in "
            "the chart of accounts. Ask the user which expense account "
            "salaries post to and pass it as salary_expense_account_id — or "
            "add a 'Salaries' expense account."
        )
    return account


async def _resolve_accrued_account(
    organization_id: uuid.UUID, *, explicit_id: Any
) -> Optional[Dict[str, Any]]:
    try:
        return await _resolve_gl_account(
            organization_id,
            account_type="LIABILITY",
            keywords=_ACCRUED_ACCOUNT_KEYWORDS,
            explicit_id=_clean_uuid(
                explicit_id, label="accrued_salaries_account_id"
            ),
        )
    except ValueError as exc:
        raise PayrollInputError(str(exc)) from None


async def _resolve_bank_account(
    organization_id: uuid.UUID, *, explicit_id: Any
) -> Dict[str, Any]:
    try:
        account = await _resolve_settlement_account(
            organization_id,
            payment_account_id=_clean_uuid(explicit_id, label="payment_account_id"),
        )
    except ValueError as exc:
        raise PayrollInputError(str(exc)) from None
    if not account:
        raise PayrollInputError(
            "No bank/cash account could be determined for the payment — add a "
            "bank account (or pass payment_account_id) first."
        )
    return account


async def _assert_not_already_posted(
    organization_id: uuid.UUID,
    *,
    source_type: str,
    transaction_date: str,
    source_id: Optional[uuid.UUID],
    label: str,
) -> None:
    """A POSTED journal for the same event/date refuses a silent double-post."""
    filters: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "source_type": source_type,
        "transaction_date": transaction_date,
    }
    if source_id:
        filters["source_id"] = str(source_id)
    rows = await fetch_many(
        "journal_entries",
        filters=filters,
        select="id,journal_number,status,description",
        order="created_at.desc",
        limit=5,
    )
    posted = [
        row for row in rows or []
        if str(row.get("status") or "").upper() == "POSTED"
    ]
    if posted:
        reference = posted[0].get("journal_number") or posted[0].get("id")
        raise PayrollInputError(
            f"{label} is ALREADY posted for {transaction_date} (journal "
            f"{reference}). Do not post it twice — tell the user it is already "
            "recorded; if the user confirms this is an ADDITIONAL payment "
            "(advance / arrears / correction), post it with a different date."
        )


async def _post_or_report(**kwargs) -> Dict[str, Any]:
    """prepare → validate → post, with an honest failure payload.

    Losing the journal must never lose the computation: the caller returns the
    breakdown AND ``posted: False`` + the error, so the agent reports the real
    state instead of a silent success.
    """
    try:
        journal = await _post_journal(**kwargs)
    except Exception as exc:  # noqa: BLE001 — reported to the user verbatim
        log.warning("payroll.journal_failed", error=str(exc))
        return {
            "posted": False,
            "entry": None,
            "lines": kwargs.get("lines"),
            "error": str(exc),
        }
    return {
        "posted": True,
        "entry": journal.get("entry"),
        "lines": kwargs.get("lines"),
        "error": None,
    }


def _account_ref(account: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The three fields the model needs to talk about an account."""
    if not account:
        return None
    return {
        "id": str(account.get("id")),
        "code": account.get("code"),
        "name": account.get("name"),
    }


async def run_payroll(
    organization_id: uuid.UUID,
    *,
    transaction_date: Any = None,
    payment_method: Any = "ACCRUED",
    department: Any = None,
    payment_account_id: Any = None,
    salary_expense_account_id: Any = None,
    accrued_salaries_account_id: Any = None,
    description: Any = None,
    **_: Any,
) -> Dict[str, Any]:
    """PAY every eligible employee for the period in ONE journal entry.

    Amounts are computed from the records (basic + MONTHLY allowances in
    force − MONTHLY deductions); the model never supplies the figure.
    ``payment_method=ACCRUED`` (default) credits the accrued-salaries
    liability; ``payment_method=PAID`` credits the bank/cash account.
    """
    pay_date = _clean_date(
        transaction_date, label="transaction_date", default_today=True
    )
    settlement = _clean_settlement(payment_method)
    period = _period_label(pay_date)

    roster = await repo.list_employees(
        organization_id, limit=_MAX_EMPLOYEES_PER_RUN + 1
    )
    if len(roster) > _MAX_EMPLOYEES_PER_RUN:
        raise PayrollInputError(
            f"This organisation has more than {_MAX_EMPLOYEES_PER_RUN} "
            "employees — one payroll run is capped there. Ask the user to run "
            "it per department (pass department='…') or in batches."
        )

    department_filter = str(department or "").strip().lower()
    eligible: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for employee in roster or []:
        skip_reason = _eligibility_reason(employee, pay_date)
        if (
            not skip_reason
            and department_filter
            and str(employee.get("department") or "").strip().lower()
            != department_filter
        ):
            skip_reason = f"department is {employee.get('department')}"
        if skip_reason:
            skipped.append({
                "employee_code": employee.get("employee_code"),
                "full_name": employee.get("full_name"),
                "reason": skip_reason,
            })
            continue
        eligible.append(employee)

    if not eligible:
        raise PayrollInputError(
            "No pay-eligible employee found"
            + (f" for department '{department}'" if department_filter else "")
            + f" on {pay_date}. Tell the user, and check the employees' status "
            "and joining dates (create the employees first if missing)."
        )

    components = await repo.list_allowances_for_organization(organization_id)
    by_employee: Dict[str, List[Dict[str, Any]]] = {}
    for component in components or []:
        by_employee.setdefault(str(component.get("employee_id")), []).append(component)

    pays: List[Dict[str, Any]] = []
    for employee in eligible:
        pay = _compute_pay(
            employee, by_employee.get(str(employee.get("id")), []), pay_date
        )
        if pay["net_pay"] <= 0:
            raise PayrollInputError(
                f"{pay['full_name']} ({pay['employee_code']}) nets "
                f"{pay['net_pay']} — the recorded deductions consume the whole "
                "salary. Ask the user how to treat it before running payroll."
            )
        pays.append(pay)

    net_total = round(sum(row["net_pay"] for row in pays), 2)
    gross_total = round(sum(row["gross_pay"] for row in pays), 2)
    deductions_total = round(sum(row["deductions_total"] for row in pays), 2)
    deferred = [
        {"employee_code": row["employee_code"], **component}
        for row in pays
        for component in row["deferred"]
    ]

    await _assert_not_already_posted(
        organization_id,
        source_type="payroll_run",
        transaction_date=pay_date,
        source_id=None,
        label=f"Payroll for {period}",
    )

    expense_account = await _resolve_salary_expense_account(
        organization_id, explicit_id=salary_expense_account_id
    )
    if settlement == "PAID":
        credit_account = await _resolve_bank_account(
            organization_id, explicit_id=payment_account_id
        )
        credit_label = "Salaries paid"
    else:
        credit_account = await _resolve_accrued_account(
            organization_id, explicit_id=accrued_salaries_account_id
        )
        if not credit_account:
            raise PayrollInputError(
                "No 'Accrued Salaries' liability account exists in the chart "
                "of accounts. Ask the user whether to add one (e.g. 2130 "
                "Accrued Salaries) — or run it as payment_method=PAID if the "
                "salaries are actually being paid now."
            )
        credit_label = "Salaries payable"

    entry_description = (
        str(description or "").strip()[:200]
        or f"Salaries — {period} ({len(pays)} employees)"
    )
    lines = [
        {
            "account_id": str(expense_account["id"]),
            "description": f"Salaries — {period}",
            "debit": net_total,
            "credit": 0,
        },
        {
            "account_id": str(credit_account["id"]),
            "description": f"{credit_label} — {period}",
            "debit": 0,
            "credit": net_total,
        },
    ]
    posting = await _post_or_report(
        organization_id=organization_id,
        transaction_date=pay_date,
        description=entry_description,
        lines=lines,
        source_type="payroll_run",
        source_id=None,
    )

    log.info(
        "payroll.run",
        organization=str(organization_id),
        employees=len(pays),
        net_total=net_total,
        settlement=settlement,
        posted=posting["posted"],
    )
    return {
        "period": period,
        "transaction_date": pay_date,
        "payment_method": settlement,
        "employee_count": len(pays),
        "employees": pays,
        "gross_total": gross_total,
        "deductions_total": deductions_total,
        "net_total": net_total,
        "skipped_employees": skipped,
        "deferred_components": deferred,
        "journal_posted": posting["posted"],
        "journal_entry": posting["entry"],
        "journal_lines": posting["lines"],
        "journal_error": posting["error"],
        "expense_account": _account_ref(expense_account),
        "credit_account": _account_ref(credit_account),
    }


async def pay_employee_salary(
    organization_id: uuid.UUID,
    *,
    employee: Any,
    amount: Any = None,
    transaction_date: Any = None,
    payment_account_id: Any = None,
    accrued_salaries_account_id: Any = None,
    salary_expense_account_id: Any = None,
    description: Any = None,
    **_: Any,
) -> Dict[str, Any]:
    """PAY ONE employee — the settlement half of the accrue-then-pay pair.

    Debits the accrued-salaries liability (falling back to the salary expense
    account when the organisation has no accrual ledger) and credits
    bank/cash.  The amount is the employee's computed entitlement unless the
    user stated one explicitly — then that figure is the net pay.
    """
    if employee is None or str(employee).strip() == "":
        raise PayrollInputError(
            "Which employee is this salary for? Provide the employee code "
            "(EMP-…), the full name, or the id."
        )
    try:
        target = await employee_service.resolve(organization_id, employee)
    except employee_service.EmployeeInputError as exc:
        raise PayrollInputError(str(exc)) from None

    pay_date = _clean_date(
        transaction_date, label="transaction_date", default_today=True
    )
    period = _period_label(pay_date)
    employee_id = uuid.UUID(str(target["id"]))
    employee_label = (
        f"{target.get('full_name')} ({target.get('employee_code')})".strip()
    )

    components = await repo.list_allowances(
        organization_id, employee_id=employee_id
    )
    pay = _compute_pay(target, components, pay_date)
    overridden = amount is not None and str(amount).strip() != ""
    if overridden:
        # The user stated the figure — it wins over the computed entitlement.
        pay["net_pay"] = _clean_amount(amount, label="amount")
    elif pay["net_pay"] <= 0:
        raise PayrollInputError(
            f"{employee_label} nets {pay['net_pay']} — the deductions recorded "
            "for this employee consume the whole salary. Ask the user how to "
            "treat it (or pass the amount they want paid)."
        )
    net = pay["net_pay"]

    await _assert_not_already_posted(
        organization_id,
        source_type="salary_payment",
        transaction_date=pay_date,
        source_id=employee_id,
        label=f"The salary payment for {employee_label}",
    )

    debit_account = await _resolve_accrued_account(
        organization_id, explicit_id=accrued_salaries_account_id
    )
    debit_label = "Accrued salaries"
    if not debit_account:
        # No accrual ledger in this chart → the payment itself carries the
        # salary expense (disclosed through ``debit_account``).
        debit_account = await _resolve_salary_expense_account(
            organization_id, explicit_id=salary_expense_account_id
        )
        debit_label = "Salaries"
    credit_account = await _resolve_bank_account(
        organization_id, explicit_id=payment_account_id
    )

    entry_description = (
        str(description or "").strip()[:200]
        or f"Salary — {employee_label} ({period})"
    )
    lines = [
        {
            "account_id": str(debit_account["id"]),
            "description": f"{debit_label} — {employee_label}",
            "debit": net,
            "credit": 0,
        },
        {
            "account_id": str(credit_account["id"]),
            "description": f"Salary paid — {employee_label}",
            "debit": 0,
            "credit": net,
        },
    ]
    posting = await _post_or_report(
        organization_id=organization_id,
        transaction_date=pay_date,
        description=entry_description,
        lines=lines,
        source_type="salary_payment",
        source_id=employee_id,
    )

    log.info(
        "payroll.employee_paid",
        organization=str(organization_id),
        employee=str(employee_id),
        amount=net,
        posted=posting["posted"],
    )
    return {
        "employee": {
            "id": str(target.get("id")),
            "employee_code": target.get("employee_code"),
            "full_name": target.get("full_name"),
        },
        "period": period,
        "transaction_date": pay_date,
        "amount": net,
        "amount_source": "USER_STATED" if overridden else "EMPLOYEE_RECORDS",
        "basic_salary": pay["basic_salary"],
        "allowances_total": pay["allowances_total"],
        "deductions_total": pay["deductions_total"],
        "gross_pay": pay["gross_pay"],
        "components": pay["components"],
        "deferred_components": pay["deferred"],
        "journal_posted": posting["posted"],
        "journal_entry": posting["entry"],
        "journal_lines": posting["lines"],
        "journal_error": posting["error"],
        "debit_account": _account_ref(debit_account),
        "credit_account": _account_ref(credit_account),
    }
