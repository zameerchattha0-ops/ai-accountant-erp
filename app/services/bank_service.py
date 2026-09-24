"""
Bank Service — business logic for bank account management.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import bank_repository as repo
from app.repositories import account_repository as acct_repo
from app.database import fetch_one, insert_one

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_bank_category_id() -> Optional[str]:
    """Resolve the BANK account_category id."""
    row = await fetch_one("account_categories", filters={"code": "BANK"})
    return row["id"] if row else None


async def _next_bank_account_code(organization_id: uuid.UUID) -> str:
    """Generate the next available bank account code (1010, 1011, …)."""
    accounts = await acct_repo.get_chart_of_accounts(
        organization_id, account_type="ASSET", limit=500,
    )
    used_codes = {a["code"] for a in accounts}
    base = 1010
    while str(base) in used_codes:
        base += 1
    return str(base)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def create_bank_account(
    *,
    organization_id: uuid.UUID,
    account_name: str,
    bank_name: str,
    account_number_masked: Optional[str] = None,
    iban: Optional[str] = None,
    branch_code: Optional[str] = None,
    currency_code: str = "PKR",
    is_default: bool = False,
) -> Dict[str, Any]:
    """Create a bank account and its corresponding GL account.

    The GL account is created under the BANK category (ASSET type, DEBIT
    normal balance).  The bank_accounts row then references the GL account
    via ``gl_account_id``.
    """
    # 1. Resolve BANK category
    category_id = await _get_bank_category_id()

    # 2. Generate next code
    code = await _next_bank_account_code(organization_id)

    # 3. Create GL account
    gl_data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "code": code,
        "name": account_name,
        "account_type": "ASSET",
        "normal_balance": "DEBIT",
        "is_control_account": False,
        "is_active": True,
        "is_system": False,
        "description": f"Bank ledger for {bank_name} — {account_name}",
    }
    if category_id:
        gl_data["account_category_id"] = category_id

    gl_account = await insert_one("accounts", data=gl_data)
    gl_account_id = uuid.UUID(gl_account["id"])

    # 4. Create bank_accounts row
    bank_account = await repo.create_bank_account(
        organization_id=organization_id,
        account_name=account_name,
        bank_name=bank_name,
        gl_account_id=gl_account_id,
        account_number_masked=account_number_masked,
        iban=iban,
        branch_code=branch_code,
        currency_code=currency_code,
        is_default=is_default,
    )

    log.info(
        "bank.account_created",
        bank_account_id=bank_account["id"],
        gl_account_id=str(gl_account_id),
        code=code,
    )
    return bank_account


async def get_bank_account(
    organization_id: uuid.UUID, *, bank_account_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_bank_account(organization_id, bank_account_id=bank_account_id)


async def list_bank_accounts(
    organization_id: uuid.UUID, *, is_active: Optional[bool] = None
) -> List[Dict[str, Any]]:
    return await repo.list_bank_accounts(organization_id, is_active=is_active)


async def update_bank_account(
    *,
    bank_account_id: uuid.UUID,
    account_name: Optional[str] = None,
    bank_name: Optional[str] = None,
    account_number_masked: Optional[str] = None,
    iban: Optional[str] = None,
    branch_code: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    data: Dict[str, Any] = {}
    if account_name is not None:
        data["account_name"] = account_name
    if bank_name is not None:
        data["bank_name"] = bank_name
    if account_number_masked is not None:
        data["account_number_masked"] = account_number_masked
    if iban is not None:
        data["iban"] = iban
    if branch_code is not None:
        data["branch_code"] = branch_code
    if is_active is not None:
        data["is_active"] = is_active
    if not data:
        return None
    return await repo.update_bank_account(bank_account_id=bank_account_id, data=data)


async def set_default(
    organization_id: uuid.UUID, *, bank_account_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.set_default_bank_account(
        organization_id, bank_account_id=bank_account_id
    )


async def resolve_bank_account(
    organization_id: uuid.UUID, *, name: str
) -> Optional[Dict[str, Any]]:
    """Fuzzy-resolve a bank account from a user-supplied name.

    Used by the AI agent to map natural language like "HBL Operations"
    to the correct bank_accounts row.  Returns None if ambiguous or
    not found.
    """
    # Exact match first
    results = await repo.search_bank_accounts(organization_id, query=name, limit=10)
    if not results:
        return None

    # Exact name match
    name_lower = name.lower().strip()
    exact = [
        r for r in results
        if r.get("account_name", "").lower() == name_lower
        or r.get("bank_name", "").lower() == name_lower
    ]
    if len(exact) == 1:
        return exact[0]

    # Partial match — if only one result, return it
    if len(results) == 1:
        return results[0]

    # Ambiguous — return None so the agent can ask for clarification
    return None

# ---------------------------------------------------------------------------
# Cash drawers (cash_accounts) — the CASH ledger's configuration rows
# ---------------------------------------------------------------------------


def pick_cash_gl_account(accounts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Choose the org's CASH GL account from its chart (pure, testable).

    Preference: exact ``Cash in Hand`` → exact ``Cash`` → any active row
    whose name contains ``cash``.  Returns None when the chart has no cash
    GL account — a missing GL is a configuration state the user resolves
    (never invented here).
    """
    active = [a for a in (accounts or []) if a.get("is_active", True)]
    named = [(a, (a.get("name") or "").strip().lower()) for a in active]
    for wanted in ("cash in hand", "cash"):
        for row, name in named:
            if name == wanted:
                return row
    for row, name in named:
        if "cash" in name:
            return row
    return None


async def find_cash_gl_account(organization_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    """The chart-of-accounts cash GL row (drives the configuration question)."""
    assets = await acct_repo.get_chart_of_accounts(
        organization_id, account_type="ASSET", limit=500,
    )
    return pick_cash_gl_account(assets)


async def ensure_default_cash_account(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """Return the default cash drawer, creating it ONLY on user sanction.

    Callers must have an explicit YES to the cash-configuration question
    (P5 pattern: configuration is never invented on the agent's own
    initiative — same rule as bank accounts).  The drawer links to the
    org's EXISTING cash GL account; no cash GL → None (chart creation
    stays its own guided flow).  Idempotent: an existing active drawer
    (the first active row is the default) is returned untouched.
    """
    existing = await repo.get_default_cash_account(organization_id)
    if existing:
        return existing
    cash_gl = await find_cash_gl_account(organization_id)
    if not cash_gl:
        return None
    drawer = await insert_one(
        "cash_accounts",
        data={
            "organization_id": str(organization_id),
            "name": str(cash_gl.get("name") or "Cash"),
            "gl_account_id": str(cash_gl["id"]),
            "is_active": True,
        },
    )
    log.info(
        "cash.drawer_created",
        organization_id=str(organization_id),
        cash_account_id=drawer.get("id"),
        gl_account_id=str(cash_gl["id"]),
    )
    return drawer

