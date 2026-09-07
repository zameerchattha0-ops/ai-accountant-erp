"""
Report Repository — Data access for financial reporting views.

All reports derive from authoritative database views/tables.
The AI must NEVER compute or estimate financial figures.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import fetch_many


async def get_general_ledger(
    organization_id: uuid.UUID,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    account_id: Optional[uuid.UUID] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Query v_general_ledger for posted journal lines."""
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if account_id:
        filters["account_id"] = str(account_id)
    # Note: date filtering would need GTE/LTE which our simple helper
    # doesn't support — for production, add a proper filter.
    return await fetch_many(
        "v_general_ledger",
        filters=filters,
        order="transaction_date.desc",
        limit=limit,
    )


async def get_trial_balance(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Query v_trial_balance for account-level debit/credit summary."""
    return await fetch_many(
        "v_trial_balance",
        filters={"organization_id": str(organization_id)},
        order="account_code.asc",
        limit=limit,
    )


async def get_balance_sheet(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Query v_balance_sheet for asset, liability, equity summary."""
    return await fetch_many(
        "v_balance_sheet",
        filters={"organization_id": str(organization_id)},
        limit=limit,
    )


async def get_income_statement(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Query v_income_statement for revenue and expense summary."""
    return await fetch_many(
        "v_income_statement",
        filters={"organization_id": str(organization_id)},
        limit=limit,
    )


async def get_customer_aging(
    organization_id: uuid.UUID,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "v_customer_aging",
        filters={"organization_id": str(organization_id)},
        limit=limit,
    )


async def get_supplier_aging(
    organization_id: uuid.UUID,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "v_supplier_aging",
        filters={"organization_id": str(organization_id)},
        limit=limit,
    )


async def get_recent_transactions(
    organization_id: uuid.UUID,
    *,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "v_recent_transactions",
        filters={"organization_id": str(organization_id)},
        limit=limit,
    )


async def get_cash_flow(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Query v_cash_flow for classified operating/investing/financing activities."""
    return await fetch_many(
        "v_cash_flow",
        filters={"organization_id": str(organization_id)},
        order="transaction_date.desc",
        limit=limit,
    )


async def get_account_summary(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "v_account_summary",
        filters={"organization_id": str(organization_id)},
        order="account_code.asc",
        limit=limit,
    )
