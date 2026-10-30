"""
ERP AI Agent — Deterministic Accounting Engine
==================================================
Provides authoritative accounting logic.  **Never** depends on Gemini
to calculate debit/credit or verify balance.

Responsibilities:
* Resolve accounts
* Construct journal lines from transaction data
* Validate balance (total_debit == total_credit)
* Link source documents
* Link customer/supplier/project dimensions
* Respect accounting periods
* Handle reversals

Mandatory invariant:  TOTAL DEBIT == TOTAL CREDIT
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import structlog

from app.services import accounting_service
from app.services import party_ledger_service
from app.repositories import account_repository as a_repo

log = structlog.get_logger(__name__)


# ===================================================================
# High-level transaction builders
# ===================================================================


async def record_credit_purchase(
    *,
    organization_id: uuid.UUID,
    supplier_id: uuid.UUID,
    asset_account_id: uuid.UUID,
    payable_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record a credit purchase journal.

    Debit:  Asset / Expense account
    Credit: Accounts Payable (supplier)
    """
    lines = [
        {
            "account_id": str(asset_account_id),
            "description": description,
            "debit": amount,
            "credit": 0,
            "supplier_id": str(supplier_id),
            "project_id": str(project_id) if project_id else None,
        },
        {
            "account_id": str(payable_account_id),
            "description": f"Payable — {description}",
            "debit": 0,
            "credit": amount,
            "supplier_id": str(supplier_id),
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="purchase_bill",
        source_id=source_id,
    )


async def record_cash_purchase(
    *,
    organization_id: uuid.UUID,
    asset_account_id: uuid.UUID,
    cash_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record a cash purchase journal.

    Debit:  Asset / Expense account
    Credit: Cash / Bank account
    """
    lines = [
        {
            "account_id": str(asset_account_id),
            "description": description,
            "debit": amount,
            "credit": 0,
        },
        {
            "account_id": str(cash_account_id),
            "description": f"Cash payment — {description}",
            "debit": 0,
            "credit": amount,
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="purchase",
        source_id=source_id,
    )


async def record_cogs(
    *,
    organization_id: uuid.UUID,
    cogs_account_id: uuid.UUID,
    inventory_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Perpetual-inventory COST RECOGNITION entry — triggered BY THE SALE.

    Debit:  Cost of Sales (EXPENSE — hits the P&L only now, not at purchase)
    Credit: Inventory (ASSET — the stock that left the business)

    The engine never invents *amount*: the caller passes the cost derived
    from the stock ledger (quantity x weighted-average unit cost).
    """
    lines = [
        {
            "account_id": str(cogs_account_id),
            "description": f"Cost of sales — {description}",
            "debit": amount,
            "credit": 0,
        },
        {
            "account_id": str(inventory_account_id),
            "description": f"Inventory relieved — {description}",
            "debit": 0,
            "credit": amount,
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=f"Cost of sales — {description}",
        lines=lines,
        source_type="cogs",
        source_id=source_id,
    )


async def record_credit_sale(
    *,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    receivable_account_id: uuid.UUID,
    revenue_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record a credit sale journal.

    Debit:  Accounts Receivable (customer)
    Credit: Revenue account
    """
    lines = [
        {
            "account_id": str(receivable_account_id),
            "description": f"Receivable — {description}",
            "debit": amount,
            "credit": 0,
            "customer_id": str(customer_id),
        },
        {
            "account_id": str(revenue_account_id),
            "description": description,
            "debit": 0,
            "credit": amount,
            "customer_id": str(customer_id),
            "project_id": str(project_id) if project_id else None,
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="invoice",
        source_id=source_id,
    )


async def record_cash_sale(
    *,
    organization_id: uuid.UUID,
    cash_account_id: uuid.UUID,
    revenue_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
    customer_id: Optional[uuid.UUID] = None,
    items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Record a cash sale journal.

    Debit:  Cash / Bank account
    Credit: Revenue account

    ``items`` is carried so the caller can trigger cost recognition for
    stock-tracked lines — see ``prepare_cogs_for_items``.  It never changes
    the journal itself: the entry stays exactly the two lines above, because
    the sale of goods is a single revenue event.
    """
    lines = [
        {
            "account_id": str(cash_account_id),
            "description": f"Cash received — {description}",
            "debit": amount,
            "credit": 0,
            "customer_id": str(customer_id) if customer_id else None,
        },
        {
            "account_id": str(revenue_account_id),
            "description": description,
            "debit": 0,
            "credit": amount,
            "customer_id": str(customer_id) if customer_id else None,
        },
    ]
    prepared = await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="cash_sale",
        source_id=source_id,
    )
    if items:
        prepared["items"] = items
    return prepared


async def record_credit_note(
    *,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    receivable_account_id: uuid.UUID,
    revenue_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record a credit note journal (customer return / allowance).

    Debit:  Revenue account — the sale is reversed (contra to the invoice)
    Credit: Accounts Receivable (customer) — the receivable shrinks
    """
    lines = [
        {
            "account_id": str(revenue_account_id),
            "description": f"Sales reversal — {description}",
            "debit": amount,
            "credit": 0,
            "customer_id": str(customer_id),
            "project_id": str(project_id) if project_id else None,
        },
        {
            "account_id": str(receivable_account_id),
            "description": f"Receivable reduced — {description}",
            "debit": 0,
            "credit": amount,
            "customer_id": str(customer_id),
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="credit_note",
        source_id=source_id,
    )


async def record_purchase_return(
    *,
    organization_id: uuid.UUID,
    supplier_id: uuid.UUID,
    expense_account_id: uuid.UUID,
    payable_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record a purchase return (debit note) journal.

    Debit:  Accounts Payable (supplier) — the payable shrinks
    Credit: Expense/Asset account — the purchase is reversed
    """
    lines = [
        {
            "account_id": str(payable_account_id),
            "description": f"Payable reduced — {description}",
            "debit": amount,
            "credit": 0,
            "supplier_id": str(supplier_id),
        },
        {
            "account_id": str(expense_account_id),
            "description": f"Purchase reversal — {description}",
            "debit": 0,
            "credit": amount,
            "supplier_id": str(supplier_id),
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="purchase_return",
        source_id=source_id,
    )


async def record_expense(
    *,
    organization_id: uuid.UUID,
    expense_account_id: uuid.UUID,
    payment_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
    supplier_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record an expense journal.

    Debit:  Expense account
    Credit: Cash/Bank/Payable account
    """
    lines = [
        {
            "account_id": str(expense_account_id),
            "description": description,
            "debit": amount,
            "credit": 0,
            "supplier_id": str(supplier_id) if supplier_id else None,
        },
        {
            "account_id": str(payment_account_id),
            "description": f"Payment — {description}",
            "debit": 0,
            "credit": amount,
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="expense",
        source_id=source_id,
    )


async def record_customer_receipt(
    *,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    receivable_account_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record customer payment receipt.

    Debit:  Bank / Cash account
    Credit: Accounts Receivable
    """
    lines = [
        {
            "account_id": str(bank_account_id),
            "description": f"Receipt — {description}",
            "debit": amount,
            "credit": 0,
            "customer_id": str(customer_id),
        },
        {
            "account_id": str(receivable_account_id),
            "description": f"Receivable settled — {description}",
            "debit": 0,
            "credit": amount,
            "customer_id": str(customer_id),
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="receipt",
        source_id=source_id,
    )


async def record_supplier_payment(
    *,
    organization_id: uuid.UUID,
    supplier_id: uuid.UUID,
    payable_account_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record supplier payment.

    Debit:  Accounts Payable
    Credit: Bank / Cash account
    """
    lines = [
        {
            "account_id": str(payable_account_id),
            "description": f"Payable settled — {description}",
            "debit": amount,
            "credit": 0,
            "supplier_id": str(supplier_id),
        },
        {
            "account_id": str(bank_account_id),
            "description": f"Payment — {description}",
            "debit": 0,
            "credit": amount,
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="payment",
        source_id=source_id,
    )


async def record_bank_transfer(
    *,
    organization_id: uuid.UUID,
    source_bank_account_id: uuid.UUID,
    destination_bank_account_id: uuid.UUID,
    amount: float,
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record an internal bank-to-bank transfer journal.

    Debit:  Destination bank GL account
    Credit: Source bank GL account
    """
    lines = [
        {
            "account_id": str(destination_bank_account_id),
            "description": f"Transfer in — {description}",
            "debit": amount,
            "credit": 0,
        },
        {
            "account_id": str(source_bank_account_id),
            "description": f"Transfer out — {description}",
            "debit": 0,
            "credit": amount,
        },
    ]
    return await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=lines,
        source_type="bank_transfer",
        source_id=source_id,
    )


async def record_compound_journal(
    *,
    organization_id: uuid.UUID,
    transaction_date: str,
    description: str,
    lines: List[Dict[str, Any]],
    entry_type: str = "MANUAL",
    currency_code: str = "PKR",
    user_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Record and post an arbitrary compound multi-line journal entry directly into the GL.

    Validates:
    - At least 2 lines.
    - Double-entry balance invariant: sum(debit) == sum(credit) > 0.
    - Each line must resolve to a valid, active, non-grouping GL account.
    - Line amounts must be non-negative and mutually exclusive (debit > 0 xor credit > 0).
    """
    if not lines or not isinstance(lines, list) or len(lines) < 2:
        raise ValueError("A compound journal entry requires at least 2 lines.")

    group_ids = await _grouping_account_ids(organization_id)
    validated_lines: List[Dict[str, Any]] = []

    for idx, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise ValueError(f"Line #{idx} must be an object with account and debit/credit details.")

        try:
            debit = round(float(line.get("debit", 0) or 0), 2)
            credit = round(float(line.get("credit", 0) or 0), 2)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Line #{idx} contains invalid numeric amount: {exc}")

        if debit < 0 or credit < 0:
            raise ValueError(f"Line #{idx} amounts cannot be negative: debit={debit}, credit={credit}")
        if debit > 0 and credit > 0:
            raise ValueError(f"Line #{idx} cannot have both debit ({debit}) and credit ({credit})")
        if debit == 0 and credit == 0:
            raise ValueError(f"Line #{idx} must have either debit > 0 or credit > 0")

        acc: Optional[Dict[str, Any]] = None
        raw_acc_id = line.get("account_id")
        code = str(line.get("account_code") or line.get("code") or "").strip()
        name = str(line.get("account_name") or line.get("name") or "").strip()

        if raw_acc_id:
            try:
                acc_uuid = uuid.UUID(str(raw_acc_id))
                acc = await a_repo.get_account(organization_id, account_id=acc_uuid)
            except Exception:
                acc = None

        if not acc and code:
            acc = await a_repo.get_account_by_code(organization_id, code=code)

        if not acc and name:
            acc = await accounting_service.resolve_account(organization_id, account_name=name)

        if not acc:
            identifier = raw_acc_id or code or name or f"line #{idx}"
            raise ValueError(f"Account '{identifier}' could not be resolved in chart of accounts.")

        if acc.get("is_active") is False:
            raise ValueError(f"Account '{acc.get('name')}' ({acc.get('code')}) is inactive and cannot be posted to.")

        if acc.get("id") in group_ids:
            raise ValueError(f"Account '{acc.get('name')}' ({acc.get('code')}) is a grouping heading, not a postable account.")

        line_desc = str(line.get("description") or description).strip()
        cust_id = line.get("customer_id") or line.get("party_id")
        supp_id = line.get("supplier_id")
        proj_id = line.get("project_id")

        validated_lines.append({
            "account_id": str(acc["id"]),
            "description": line_desc,
            "debit": debit,
            "credit": credit,
            "customer_id": str(cust_id) if cust_id else None,
            "supplier_id": str(supp_id) if supp_id else None,
            "project_id": str(proj_id) if proj_id else None,
        })

    total_debit = round(sum(l["debit"] for l in validated_lines), 2)
    total_credit = round(sum(l["credit"] for l in validated_lines), 2)

    if abs(total_debit - total_credit) > 0.01:
        raise ValueError(
            f"Compound journal is unbalanced: total debit ({total_debit}) != total credit ({total_credit}). Double-entry balance invariant violated."
        )
    if total_debit <= 0:
        raise ValueError("Total journal entry amount must be strictly greater than 0.")

    prepared = await accounting_service.prepare_journal(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        lines=validated_lines,
        source_type=entry_type or "MANUAL",
        currency_code=currency_code or "PKR",
    )
    entry_row = prepared.get("entry") or prepared.get("journal_entry") or {}
    entry_id = uuid.UUID(str(entry_row["id"]))
    await accounting_service.validate_journal(entry_id=entry_id)
    posted = await accounting_service.post_journal(entry_id=entry_id)

    return {
        "success": True,
        "journal_entry_id": str(entry_id),
        "entry_number": entry_row.get("journal_number") or posted.get("entry_number") or entry_row.get("entry_number"),
        "transaction_date": transaction_date,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "lines_count": len(validated_lines),
        "status": "POSTED",
        "description": description,
    }


# ===================================================================
# Verification
# ===================================================================


async def verify_journal(
    organization_id: uuid.UUID, *, entry_id: uuid.UUID
) -> Dict[str, Any]:
    """Verify a journal entry is balanced and exists."""
    entry = await accounting_service.get_entry(organization_id, entry_id=entry_id)
    if not entry:
        return {"verified": False, "reason": "Journal entry not found"}

    lines = await accounting_service.get_lines(entry_id=entry_id)
    total_debit = sum(float(l.get("debit", 0)) for l in lines)
    total_credit = sum(float(l.get("credit", 0)) for l in lines)

    balanced = abs(total_debit - total_credit) < 0.01
    return {
        "verified": balanced,
        "journal_number": entry.get("journal_number"),
        "status": entry.get("status"),
        "total_debit": total_debit,
        "total_credit": total_credit,
        "line_count": len(lines),
    }


# ===================================================================
# Auto-journal — atomic document + journal creation (C3 + C4)
# ===================================================================


async def _grouping_account_ids(organization_id: uuid.UUID) -> set:
    """Parent (grouping) account ids for an organization.

    Used so a hierarchy heading can never be resolved as a posting default.
    A lookup failure degrades to "no grouping accounts", which keeps the
    previous behaviour rather than blocking the posting.
    """
    try:
        return await a_repo.get_grouping_account_ids(organization_id)
    except Exception as exc:  # noqa: BLE001 — never block a posting on this
        log.warning("accounting_engine.grouping_lookup_failed", error=str(exc)[:200])
        return set()


async def _resolve_default_account(
    organization_id: uuid.UUID,
    account_type: str,
    *,
    fallback_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve a default account of the given type — deterministically.

    EXPENSE accounts are special: an arbitrary "first expense account"
    default can post to an unrelated category (e.g. Salaries).  For
    EXPENSE the default MUST be a genuinely GENERIC account (general /
    other / miscellaneous / sundry / operating in its name); when none
    exists we return None so the caller surfaces an honest warning instead
    of silently posting to a wrong expense category.  Other types (cash,
    payable, revenue) keep the first-of-type convention — conventional
    control accounts, low mis-classification risk.

    GROUPING accounts are never postable: since the chart of accounts is
    hierarchical, a parent (e.g. "Property, Plant & Equipment") is a
    heading, not an account that can carry a posting.  Any account that is
    the parent of another active account is skipped, so introducing
    hierarchy can never hijack a default.
    """
    accounts = await a_repo.get_chart_of_accounts(
        organization_id, account_type=account_type, limit=100,
    )
    if accounts:
        group_ids = await _grouping_account_ids(organization_id)
        accounts = [a for a in accounts if a.get("id") not in group_ids]

    if account_type == "EXPENSE":
        generic_terms = ("general", "other", "miscellaneous", "sundry", "operating")
        for acc in accounts:
            name = (acc.get("name") or "").lower()
            if "accumulated" in name or "depreciation" in name:
                continue
            if any(t in name for t in generic_terms):
                return acc
        log.warning(
            "accounting_engine.no_generic_expense_default",
            hint="post with an explicit account hint instead",
        )
        return None
    if accounts:
        return accounts[0]
    if fallback_type:
        fallback = await a_repo.get_chart_of_accounts(
            organization_id, account_type=fallback_type, limit=5,
        )
        if fallback:
            group_ids = await _grouping_account_ids(organization_id)
            for acc in fallback:
                if acc.get("id") not in group_ids:
                    return acc
    return None


# ---------------------------------------------------------------------------
# Perpetual-inventory account resolution (migration 091)
#
# The purchase side of an INVENTORY-natured transaction must debit the
# INVENTORY valuation account (an ASSET) — NEVER an expense account — and the
# sale side must credit it against a COST OF SALES expense account.  Both
# resolvers are read-only and honest: no match -> None -> the caller surfaces
# a warning instead of silently posting to a wrong ledger (the same contract
# as _resolve_default_account for EXPENSE).
# ---------------------------------------------------------------------------
_INVENTORY_LEDGER_RE = re.compile(
    r"\b(?:inventor\w*|merchandise|stocks?|goods\s+on\s+hand)\b",
    re.IGNORECASE,
)
_COGS_LEDGER_RE = re.compile(
    r"cost\s+of\s+(?:sales|goods)|\bcogs\b",
    re.IGNORECASE,
)


async def resolve_inventory_account(
    organization_id: uuid.UUID,
    *,
    hint_account: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """The ASSET ledger that carries stock valuation.

    Order: the validated hint (when it IS an inventory-named asset), then a
    chart search for the standard ledger words.  Grouping accounts are
    skipped — a heading ("Inventory" over "Finished Goods" children) must
    never carry the posting.
    """
    if hint_account and hint_account.get("account_type") == "ASSET":
        if _INVENTORY_LEDGER_RE.search(str(hint_account.get("name") or "")):
            return hint_account
    group_ids = await _grouping_account_ids(organization_id)
    for term in ("Inventory", "Merchandise", "Stock"):
        try:
            rows = await a_repo.search_accounts(
                organization_id, query=term, limit=10
            )
        except Exception as exc:  # noqa: BLE001 — never block on a lookup
            log.warning(
                "accounting_engine.inventory_lookup_failed",
                term=term, error=str(exc)[:200],
            )
            continue
        for row in rows or ():
            if row.get("account_type") != "ASSET":
                continue
            if row.get("id") in group_ids:
                continue
            if row.get("is_active") is False:
                continue
            if _INVENTORY_LEDGER_RE.search(str(row.get("name") or "")):
                return row
    return None


async def resolve_cogs_account(
    organization_id: uuid.UUID,
    *,
    hint_account: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """The EXPENSE ledger that carries Cost of Sales (credited on a sale)."""
    if hint_account and hint_account.get("account_type") == "EXPENSE":
        if _COGS_LEDGER_RE.search(str(hint_account.get("name") or "")):
            return hint_account
    group_ids = await _grouping_account_ids(organization_id)
    for term in ("Cost of Sales", "Cost of Goods", "COGS"):
        try:
            rows = await a_repo.search_accounts(
                organization_id, query=term, limit=10
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "accounting_engine.cogs_lookup_failed",
                term=term, error=str(exc)[:200],
            )
            continue
        for row in rows or ():
            if row.get("account_type") != "EXPENSE":
                continue
            if row.get("id") in group_ids:
                continue
            if row.get("is_active") is False:
                continue
            name = str(row.get("name") or "")
            if _COGS_LEDGER_RE.search(name) or "purchase" in name.lower():
                return row
    return None


async def ensure_inventory_account(
    organization_id: uuid.UUID,
    *,
    hint_account: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """The Inventory ASSET ledger — creating it when the chart lacks one.

    Same execution-time self-heal contract as ``ensure_cogs_account``: an
    INVENTORY purchase may not be refused because the chart was seeded
    without the optional Inventory ledger.  Top-level (parent never
    invented); the hint path is unchanged.  None only when both resolve and
    create fail — the caller's warning then still fires.
    """
    row = await resolve_inventory_account(organization_id, hint_account=hint_account)
    if row is not None:
        return row
    try:
        code = await a_repo.next_available_code(organization_id, "1200")
        created = await a_repo.create_account(
            organization_id=organization_id,
            code=code,
            name="Inventory",
            account_type="ASSET",
            normal_balance="DEBIT",
            parent_account_id=None,
            description=(
                "Inventory valuation — created on demand by the perpetual-"
                "inventory engine when a stock purchase needed it."
            ),
        )
    except Exception as exc:  # noqa: BLE001 — honest warning, never a crash
        log.warning(
            "accounting_engine.inventory_account_create_failed",
            error=str(exc)[:200],
        )
        return None
    log.info(
        "accounting_engine.inventory_account_created",
        code=str(created.get("code")),
        name=str(created.get("name")),
    )
    return created


async def ensure_cogs_account(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """Resolve the Cost-of-Sales ledger, CREATING it when the chart lacks one.

    A first-ever inventory sale on a chart that never approved the optional
    Cost-of-Sales bundle (migration 067 seeds it only when approved) would
    otherwise fail cost recognition with "ask the user to create it" — the
    missing-head must be a PREREQUISITE the engine creates itself, exactly
    like ``revenue_ledger_service``'s parent creation and
    ``inventory_service.ensure_inventory_category``.

    Postable by construction: a fresh TOP-LEVEL "Cost of Sales" account has
    no children, so it is not a grouping heading (a heading must never carry
    a posting).  Returns None only when the chart write failed — the caller
    keeps its honest warning (never a fake ledger).
    """
    account = await resolve_cogs_account(organization_id)
    if account is not None:
        return account
    try:
        code = await a_repo.next_available_code(organization_id, "6010")
        created = await a_repo.create_account(
            organization_id=organization_id,
            code=code,
            name="Cost of Sales",
            account_type="EXPENSE",
            normal_balance="DEBIT",
            parent_account_id=None,
            description=(
                "Direct cost of inventory/services sold — created "
                "automatically when the first sale recognised cost."
            ),
        )
    except Exception as exc:  # noqa: BLE001 — chart write failed → honest None
        log.warning(
            "accounting_engine.cogs_account_create_failed",
            error=str(exc)[:200],
        )
        return None
    log.info(
        "accounting_engine.cogs_account_created",
        code=created.get("code"),
        account_id=str(created.get("id")),
    )
    return created


async def _resolve_cash_account(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """The ledger a CASH purchase credits — by NAME, never "first asset".

    "First ASSET" is usually Cash in simple charts but becomes Accounts
    Receivable the moment one exists, which would credit a customer's
    obligation for a supplier payment — exactly the silent mis-posting this
    resolver exists to prevent.  No cash-named ledger -> None -> warning.
    """
    for name in ("Cash", "Cash Account", "Petty Cash", "Bank"):
        row = await _resolve_named_postable_account(organization_id, name)
        if row is not None:
            return row
    try:
        rows = await a_repo.search_accounts(
            organization_id, query="cash", limit=10
        )
    except Exception:  # noqa: BLE001
        return None
    group_ids = await _grouping_account_ids(organization_id)
    for row in rows or ():
        if row.get("account_type") != "ASSET":
            continue
        if row.get("id") in group_ids:
            continue
        if row.get("is_active") is False:
            continue
        return row
    return None


async def ensure_cash_account(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """The Cash/Bank ASSET ledger a cash purchase credits — CREATING it when
    the chart lacks one (2026-10-20).

    Same execution-time self-heal contract as ``ensure_inventory_account`` /
    ``ensure_cogs_account``: a CASH purchase must not be refused (or silently
    credit a wrong asset like Accounts Receivable) merely because the chart
    was seeded without a Cash ledger.  Order:
      1. the existing Cash/Cash Account/Petty Cash/Bank ledger (by NAME);
      2. a fuzzy "cash"-named ASSET (never a grouping heading);
      3. CREATE a top-level "Cash" ASSET ledger and return it, flagged
         ``cash_account_created`` so the caller discloses the write.
    Returns None only when resolve AND create both fail — the caller's
    honest warning then still fires (never a fabricated ledger).
    """
    row = await _resolve_cash_account(organization_id)
    if row is not None:
        return row
    try:
        code = await a_repo.next_available_code(organization_id, "1110")
        created = await a_repo.create_account(
            organization_id=organization_id,
            code=code,
            name="Cash",
            account_type="ASSET",
            normal_balance="DEBIT",
            parent_account_id=None,
            description=(
                "Cash on hand — created on demand when a cash purchase needed "
                "a cash ledger and the chart had none."
            ),
        )
    except Exception as exc:  # noqa: BLE001 — honest warning, never a crash
        log.warning(
            "accounting_engine.cash_account_create_failed",
            error=str(exc)[:200],
        )
        return None
    created["cash_account_created"] = True
    log.info(
        "accounting_engine.cash_account_created",
        code=str(created.get("code")),
        name=str(created.get("name")),
    )
    return created


async def _resolve_named_postable_account(
    organization_id: uuid.UUID, name: str, expected_type: str = "ASSET"
) -> Optional[Dict[str, Any]]:
    """Exact-name lookup that refuses grouping (heading) accounts and verifies account type."""
    from app.services import accounting_service

    row = await accounting_service.resolve_account(
        organization_id,
        account_name=name,
        account_type=expected_type,
        exact_only=True,
        required_type=expected_type,
    )
    if not row or row.get("is_active") is False:
        return None
    if expected_type and row.get("account_type") != expected_type:
        log.warning(
            "authority_split.intercepted",
            reason="fuzzy_type_mismatch",
            expected_type=expected_type,
            actual_type=row.get("account_type"),
            account_name=name,
        )
        return None
    if row.get("name", "").strip().lower() != name.strip().lower():
        return None
    group_ids = await _grouping_account_ids(organization_id)
    if row.get("id") in group_ids:
        return None
    return row



async def prepare_cogs_for_items(
    organization_id: uuid.UUID,
    *,
    items: Optional[List[Dict[str, Any]]],
    transaction_date: str,
    description: str,
    source_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Cost-recognition journal for the stock-tracked lines of a SALE.

    Perpetual inventory: the Cost-of-Sales entry is triggered by the sale,
    never by the purchase.  For every line that references a stock-tracked
    product this helper

      1. reads the weighted-average cost from the stock ledger (fallback:
         the product's catalogue ``cost_price``),
      2. refuses lines whose stock/cost cannot be valued (honest per-line
         warning — an issue valued at zero would fabricate profit),
      3. prepares ``Dr Cost of Sales / Cr Inventory`` when at least one
         line could be valued.

    Returns a dict that is MERGED into the caller's result:
      * success -> ``cogs_entry`` (prepared, not posted), ``cost_of_sales``
        (total), ``cogs_lines`` (per product: quantity + unit_cost — the
        caller issues stock with EXACTLY these costs after posting);
      * nothing to recognise -> ``{}`` (service sales / no stock lines);
      * any failure -> ``cogs_warning`` (the revenue entry still stands).
    """
    from app.repositories import product_repository as prod_repo
    from app.services import inventory_service

    tracked: List[Dict[str, Any]] = []
    for raw in items or ():
        if not isinstance(raw, dict):
            continue
        pid = raw.get("product_id")
        if not pid:
            continue
        try:
            product = await prod_repo.get_product(
                organization_id, product_id=uuid.UUID(str(pid))
            )
        except Exception as exc:  # noqa: BLE001 — per-line, never fatal
            log.warning(
                "accounting_engine.cogs_product_lookup_failed",
                product_id=str(pid), error=str(exc)[:200],
            )
            continue
        if not product or not product.get("is_stock_tracked"):
            continue
        try:
            qty = float(raw.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        tracked.append({"product": product, "quantity": qty, "raw": raw})

    if not tracked:
        return {}  # nothing here is stock — a service sale has no COGS

    positions = await inventory_service.positions_for_products(
        organization_id,
        product_ids=[t["product"]["id"] for t in tracked],
    )

    cogs_lines: List[Dict[str, Any]] = []
    total = 0.0
    skipped: List[str] = []
    for t in tracked:
        product = t["product"]
        qty = t["quantity"]
        position = positions.get(str(product.get("id"))) or {}
        cost = position.get("average_cost")
        try:
            cost = float(cost) if cost is not None else 0.0
        except (TypeError, ValueError):
            cost = 0.0
        if cost <= 0:
            # Ledger unreadable or empty: fall back to the CATALOGUE cost.
            fallback = product.get("cost_price")
            try:
                cost = float(fallback) if fallback is not None else 0.0
            except (TypeError, ValueError):
                cost = 0.0
        if cost <= 0:
            skipped.append(str(product.get("name") or "unnamed product"))
            continue
        cogs_lines.append({
            "product_id": str(product["id"]),
            "quantity": qty,
            "unit_cost": round(cost, 4),
        })
        total += qty * cost

    if not cogs_lines:
        return {
            "cogs_warning": (
                "No Cost-of-Sales entry was recorded: the cost of "
                f"{', '.join(skipped)} could not be determined from the "
                "stock ledger or the product catalogue."
            ),
        }

    # ensure: a chart with no Cost of Sales head CREATES it here (missing
    # prerequisite → engine-created), so the first inventory sale never fails.
    cogs_account = await ensure_cogs_account(organization_id)
    inventory_account = await ensure_inventory_account(organization_id)
    if not cogs_account or not inventory_account:
        missing = []
        if not cogs_account:
            missing.append("Cost of Sales (EXPENSE)")
        if not inventory_account:
            missing.append("Inventory (ASSET)")
        return {
            "cogs_warning": (
                "No Cost-of-Sales entry was recorded: the chart has no "
                f"{'/'.join(missing)} account. Ask the user to create it, "
                "then re-record the cost recognition."
            ),
            "cogs_lines": cogs_lines,
        }

    total = round(total, 2)
    prepared = await record_cogs(
        organization_id=organization_id,
        cogs_account_id=uuid.UUID(str(cogs_account["id"])),
        inventory_account_id=uuid.UUID(str(inventory_account["id"])),
        amount=total,
        transaction_date=transaction_date,
        description=description,
        source_id=source_id,
    )
    result: Dict[str, Any] = {
        "cogs_entry": prepared,
        "cost_of_sales": total,
        "cogs_lines": cogs_lines,
    }
    if skipped:
        result["cogs_warning"] = (
            "Some lines were NOT cost-recognised (no cost could be "
            f"determined): {', '.join(skipped)}."
        )
    return result


async def auto_journal(
    *,
    organization_id: uuid.UUID,
    document_type: str,
    document: Dict[str, Any],
    amount: float,
    transaction_date: str,
    description: str,
    customer_id: Optional[uuid.UUID] = None,
    supplier_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
    account_hint_id: Optional[uuid.UUID] = None,
    transaction_nature: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> Dict[str, Any]:
    """Automatically create a journal entry for a document.

    Resolves default accounts from the chart of accounts and calls
    the appropriate accounting-engine builder.  On success the return
    dict includes ``journal_entry``; on failure it includes
    ``journal_warning`` but the document itself is still returned
    (C4: document creation is not rolled back).
    """
    source_id = uuid.UUID(document["id"]) if document.get("id") else None

    # --- Account hint validation (classification → engine hand-off) -------
    # The hint comes from the deterministic classifier (or the model) and is
    # VALIDATED here: it must exist, belong to this organisation, be active,
    # and be of an acceptable type for the debit side.  An invalid hint is
    # ignored (falls back to the engine default) — it can never bypass the
    # engine's authority.
    hint_account: Optional[Dict[str, Any]] = None
    if account_hint_id:
        try:
            hint_account = await a_repo.get_account(
                organization_id, account_id=account_hint_id
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("accounting_engine.hint_lookup_failed", error=str(exc))
        if not hint_account:
            log.warning(
                "accounting_engine.hint_rejected",
                reason="account not found in this organisation",
                account_hint_id=str(account_hint_id),
            )
            hint_account = None
        elif not hint_account.get("is_active", True):
            log.warning(
                "accounting_engine.hint_rejected",
                reason="account is inactive",
                account_hint_id=str(account_hint_id),
            )
            hint_account = None

    try:
        if document_type == "invoice":
            # PARTY SEGREGATION: post to the CUSTOMER'S OWN receivable ledger
            # when it exists - a child of the AR control account, created when
            # the customer is added (app/services/party_ledger_service.py) - so
            # the chart itself shows what each party owes.  The control account
            # stays the fallback for parties that have no ledger yet.
            #
            # The resolution is READ-ONLY: a posting never grows the chart, and
            # a party link pointing at a deactivated/foreign account is ignored.
            receivable = None
            if customer_id:
                receivable = await party_ledger_service.resolve_customer_receivable_account(
                    organization_id, customer_id
                )
            if not receivable:
                # Resolve the RECEIVABLE account precisely — the first ASSET
                # account is usually Cash (1000), which would debit Cash for a
                # CREDIT sale - it must never debit 1000 Cash instead of
                # 1100 Accounts Receivable.
                receivable = await accounting_service.resolve_account(
                    organization_id, account_name="Accounts Receivable"
                )
            if not receivable:
                receivable = await _resolve_default_account(
                    organization_id, "ASSET", fallback_type="CURRENT_ASSET",
                )
            revenue = await _resolve_default_account(
                organization_id, "REVENUE", fallback_type="INCOME",
            )
            if not receivable or not revenue:
                return {"journal_warning": "Cannot resolve Receivable or Revenue accounts"}
            entry = await record_credit_sale(
                organization_id=organization_id,
                customer_id=customer_id or uuid.UUID(int=0),
                receivable_account_id=uuid.UUID(receivable["id"]),
                revenue_account_id=uuid.UUID(revenue["id"]),
                amount=amount,
                transaction_date=transaction_date,
                description=description,
                source_id=source_id,
                project_id=project_id,
            )
            result: Dict[str, Any] = {"journal_entry": entry}
            # PERPETUAL INVENTORY: the SALE triggers cost recognition —
            # Dr Cost of Sales / Cr Inventory for the stock-tracked lines
            # (never at purchase time).  Prepared here, posted by the tool
            # layer alongside the revenue entry; any failure is a warning,
            # never a reason to drop the revenue entry (C4).
            cogs = await prepare_cogs_for_items(
                organization_id,
                items=document.get("items") or [],
                transaction_date=transaction_date,
                description=description,
                source_id=source_id,
            )
            result.update(cogs)
            return result

        elif document_type == "purchase_bill":
            # PERPETUAL INVENTORY (migration 091): an INVENTORY-natured
            # purchase debits the INVENTORY VALUATION account (an ASSET) —
            # never an expense account — so the P&L is untouched at purchase
            # time; Cost of Sales is recognised later, triggered by the sale
            # (prepare_cogs_for_items).  The hint wins when it IS the
            # inventory ledger; otherwise the chart search resolves it — and
            # ensure_inventory_account CREATES the ledger when the chart has
            # none (missing prerequisite → engine-created, never "ask the
            # user" for a standard statement head).
            is_inventory = str(transaction_nature or "").upper() == "INVENTORY"
            if is_inventory or (
                hint_account
                and hint_account.get("account_type") == "ASSET"
                and _INVENTORY_LEDGER_RE.search(str(hint_account.get("name") or ""))
            ):
                inventory = await ensure_inventory_account(
                    organization_id, hint_account=hint_account
                )
                if not inventory:
                    return {
                        "journal_warning": (
                            "Cannot resolve the Inventory valuation account "
                            "(no postable ASSET ledger named Inventory/Stock "
                            "exists). The purchase was NOT journalised — ask "
                            "the user to create the Inventory account first."
                        )
                    }
                debit_account: Optional[Dict[str, Any]] = inventory
            else:
                # A validated hint (from the classifier/user) may route the debit
                # to a fixed-asset account instead of the generic expense default.
                debit_account = hint_account if (
                    hint_account and hint_account.get("account_type") in ("EXPENSE", "ASSET")
                ) else await _resolve_default_account(
                    organization_id, "EXPENSE",
                )
            if not debit_account:
                return {"journal_warning": "Cannot resolve the debit account"}

            # SETTLEMENT SIDE: a CASH purchase credits Bank/Cash directly
            # (the bill is settled at creation — the tool marks it PAID so a
            # later supplier payment can never double-credit cash); a credit
            # purchase credits the party payable (existing behaviour).
            if str(payment_method or "").upper() == "CASH":
                cash_account = await _resolve_cash_account(organization_id)
                if not cash_account:
                    return {
                        "journal_warning": (
                            "Cannot resolve the Cash/Bank account for this "
                            "cash purchase. Ask the user which asset ledger "
                            "holds cash, then re-record it."
                        )
                    }
                entry = await record_cash_purchase(
                    organization_id=organization_id,
                    asset_account_id=uuid.UUID(debit_account["id"]),
                    cash_account_id=uuid.UUID(cash_account["id"]),
                    amount=amount,
                    transaction_date=transaction_date,
                    description=description,
                    source_id=source_id,
                )
                return {
                    "journal_entry": entry,
                    "settlement": "CASH",
                    "cash_account_id": str(cash_account["id"]),
                }

            # PARTY SEGREGATION (payable side): the SUPPLIER'S OWN payable
            # ledger when it exists; the AP control account otherwise.
            payable = None
            if supplier_id:
                payable = await party_ledger_service.resolve_supplier_payable_account(
                    organization_id, supplier_id
                )
            if not payable:
                # Resolve the PAYABLE control account by NAME, not as a generic
                # liability default: once parties hang under 2010 it becomes a
                # HEADING, and the default resolver deliberately refuses to
                # return a heading (a heading must never carry a posting).
                payable = await accounting_service.resolve_account(
                    organization_id, account_name="Accounts Payable"
                )
            if not payable:
                payable = await _resolve_default_account(
                    organization_id, "LIABILITY", fallback_type="CURRENT_LIABILITY",
                )
            if not debit_account or not payable:
                return {"journal_warning": "Cannot resolve debit or Payable accounts"}
            entry = await record_credit_purchase(
                organization_id=organization_id,
                supplier_id=supplier_id or uuid.UUID(int=0),
                asset_account_id=uuid.UUID(debit_account["id"]),
                payable_account_id=uuid.UUID(payable["id"]),
                amount=amount,
                transaction_date=transaction_date,
                description=description,
                source_id=source_id,
                project_id=project_id,
            )
            return {"journal_entry": entry}

        elif document_type == "expense":
            expense_acct = hint_account if (
                hint_account and hint_account.get("account_type") in ("EXPENSE", "ASSET")
            ) else await _resolve_default_account(
                organization_id, "EXPENSE",
            )
            cash_acct = await _resolve_default_account(
                organization_id, "ASSET", fallback_type="CURRENT_ASSET",
            )
            if not expense_acct or not cash_acct:
                return {"journal_warning": "Cannot resolve Expense or Cash accounts"}
            entry = await record_expense(
                organization_id=organization_id,
                expense_account_id=uuid.UUID(expense_acct["id"]),
                payment_account_id=uuid.UUID(cash_acct["id"]),
                amount=amount,
                transaction_date=transaction_date,
                description=description,
                source_id=source_id,
                supplier_id=supplier_id,
            )
            return {"journal_entry": entry}

        elif document_type == "credit_note":
            # Customer return / allowance — the invoice posting with the
            # sides REVERSED: revenue is reversed and the receivable
            # shrinks.  Same party-segregation resolution as the invoice
            # block (the customer's own ledger; control-account fallback).
            receivable = None
            if customer_id:
                receivable = await party_ledger_service.resolve_customer_receivable_account(
                    organization_id, customer_id
                )
            if not receivable:
                receivable = await accounting_service.resolve_account(
                    organization_id, account_name="Accounts Receivable"
                )
            if not receivable:
                receivable = await _resolve_default_account(
                    organization_id, "ASSET", fallback_type="CURRENT_ASSET",
                )
            revenue = await _resolve_default_account(
                organization_id, "REVENUE", fallback_type="INCOME",
            )
            if not receivable or not revenue:
                return {"journal_warning": "Cannot resolve Receivable or Revenue accounts"}
            entry = await record_credit_note(
                organization_id=organization_id,
                customer_id=customer_id or uuid.UUID(int=0),
                receivable_account_id=uuid.UUID(receivable["id"]),
                revenue_account_id=uuid.UUID(revenue["id"]),
                amount=amount,
                transaction_date=transaction_date,
                description=description,
                source_id=source_id,
                project_id=project_id,
            )
            return {"journal_entry": entry}

        elif document_type == "purchase_return":
            # Debit note — the bill posting with the sides REVERSED: the
            # payable shrinks and the expense/purchase is reversed.  A
            # validated classifier hint routes the credit back to the
            # exact asset/expense account the bill debited.
            expense = hint_account if (
                hint_account and hint_account.get("account_type") in ("EXPENSE", "ASSET")
            ) else await _resolve_default_account(
                organization_id, "EXPENSE",
            )
            payable = None
            if supplier_id:
                payable = await party_ledger_service.resolve_supplier_payable_account(
                    organization_id, supplier_id
                )
            if not payable:
                payable = await accounting_service.resolve_account(
                    organization_id, account_name="Accounts Payable"
                )
            if not payable:
                payable = await _resolve_default_account(
                    organization_id, "LIABILITY", fallback_type="CURRENT_LIABILITY",
                )
            if not expense or not payable:
                return {"journal_warning": "Cannot resolve Expense or Payable accounts"}
            entry = await record_purchase_return(
                organization_id=organization_id,
                supplier_id=supplier_id or uuid.UUID(int=0),
                expense_account_id=uuid.UUID(expense["id"]),
                payable_account_id=uuid.UUID(payable["id"]),
                amount=amount,
                transaction_date=transaction_date,
                description=description,
                source_id=source_id,
            )
            return {"journal_entry": entry}

        else:
            return {"journal_warning": f"Auto-journal not supported for {document_type}"}

    except Exception as exc:
        log.warning(
            "accounting_engine.auto_journal_failed",
            document_type=document_type,
            error=str(exc),
        )
        return {"journal_warning": f"Journal creation failed: {exc}"}
