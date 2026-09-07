"""
Bank Repository — Supabase data access for bank accounts and transactions.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, update_one, search_ilike


# ---- Bank Accounts --------------------------------------------------------

async def create_bank_account(
    *,
    organization_id: uuid.UUID,
    account_name: str,
    bank_name: str,
    gl_account_id: uuid.UUID,
    account_number_masked: Optional[str] = None,
    iban: Optional[str] = None,
    branch_code: Optional[str] = None,
    currency_code: str = "PKR",
    is_default: bool = False,
    is_active: bool = True,
) -> Dict[str, Any]:
    """Insert a new bank account linked to its GL account."""
    return await insert_one(
        "bank_accounts",
        data={
            "organization_id": str(organization_id),
            "account_name": account_name,
            "bank_name": bank_name,
            "gl_account_id": str(gl_account_id),
            "account_number_masked": account_number_masked,
            "iban": iban,
            "branch_code": branch_code,
            "currency_code": currency_code,
            "current_balance": 0,
            "is_default": is_default,
            "is_active": is_active,
        },
    )


async def get_bank_account(
    organization_id: uuid.UUID, *, bank_account_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "bank_accounts",
        filters={
            "id": str(bank_account_id),
            "organization_id": str(organization_id),
        },
    )


async def list_bank_accounts(
    organization_id: uuid.UUID,
    *,
    is_active: Optional[bool] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if is_active is not None:
        filters["is_active"] = is_active
    return await fetch_many(
        "bank_accounts",
        filters=filters,
        order="bank_name.asc",
        limit=limit,
    )


async def update_bank_account(
    *,
    bank_account_id: uuid.UUID,
    data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return await update_one("bank_accounts", row_id=bank_account_id, data=data)


async def set_default_bank_account(
    organization_id: uuid.UUID, *, bank_account_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Set is_default = true. The DB trigger unsets other defaults."""
    return await update_one(
        "bank_accounts",
        row_id=bank_account_id,
        data={"is_default": True},
    )


async def get_default_bank_account(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "bank_accounts",
        filters={
            "organization_id": str(organization_id),
            "is_default": True,
            "is_active": True,
        },
    )


# ---- Cash Accounts (Work Stream R4.1 — cash ledger is SEPARATE from the
# bank ledger: a CASH receipt/payment must debit/credit the CASH GL, never
# the bank GL) ---------------------------------------------------------------

async def list_cash_accounts(
    organization_id: uuid.UUID,
    *,
    is_active: Optional[bool] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if is_active is not None:
        filters["is_active"] = is_active
    return await fetch_many(
        "cash_accounts",
        filters=filters,
        order="name.asc",
        limit=limit,
    )


async def get_cash_account(
    organization_id: uuid.UUID, *, cash_account_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "cash_accounts",
        filters={
            "id": str(cash_account_id),
            "organization_id": str(organization_id),
        },
    )


async def get_default_cash_account(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """The org's cash drawer: the first active cash_accounts row (the table
    has no is_default column — one drawer per org is the convention)."""
    rows = await list_cash_accounts(organization_id, is_active=True, limit=1)
    return rows[0] if rows else None


async def search_bank_accounts(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    """Fuzzy search bank accounts by name or bank_name."""
    by_name = await search_ilike(
        "bank_accounts",
        column="account_name",
        value=query,
        organization_id=organization_id,
        limit=limit,
    )
    by_bank = await search_ilike(
        "bank_accounts",
        column="bank_name",
        value=query,
        organization_id=organization_id,
        limit=limit,
    )
    seen = set()
    merged: List[Dict[str, Any]] = []
    for row in by_name + by_bank:
        if row["id"] not in seen:
            seen.add(row["id"])
            merged.append(row)
    return merged[:limit]


# ---- Bank Transactions ----------------------------------------------------

async def create_bank_transaction(
    *,
    organization_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    transaction_date: str,
    direction: str,
    amount: float,
    description: Optional[str] = None,
    reference: Optional[str] = None,
    counterparty: Optional[str] = None,
    journal_entry_id: Optional[uuid.UUID] = None,
    is_transfer: bool = False,
) -> Dict[str, Any]:
    """Insert a bank transaction (deposit/withdrawal/transfer)."""
    return await insert_one(
        "bank_transactions",
        data={
            "organization_id": str(organization_id),
            "bank_account_id": str(bank_account_id),
            "transaction_date": transaction_date,
            "direction": direction,
            "amount": amount,
            "description": description,
            "reference": reference,
            "counterparty": counterparty,
            "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
            "status": "UNRECONCILED",
            "is_transfer": is_transfer,
        },
    )


async def list_bank_transactions(
    organization_id: uuid.UUID,
    *,
    bank_account_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if bank_account_id:
        filters["bank_account_id"] = str(bank_account_id)
    return await fetch_many(
        "bank_transactions",
        filters=filters,
        order="transaction_date.desc",
        limit=limit,
    )


async def link_journal_to_bank_transaction(
    *, transaction_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "bank_transactions",
        row_id=transaction_id,
        data={"journal_entry_id": str(journal_entry_id)},
    )
