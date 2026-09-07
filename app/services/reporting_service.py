"""
Reporting Service — business logic for financial report generation.

All reports derive from authoritative database views.
The AI must NEVER estimate or compute financial figures.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import report_repository as repo

log = structlog.get_logger(__name__)


async def get_general_ledger(
    organization_id: uuid.UUID,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    account_id: Optional[uuid.UUID] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    return await repo.get_general_ledger(
        organization_id,
        from_date=from_date,
        to_date=to_date,
        account_id=account_id,
        limit=limit,
    )


async def get_trial_balance(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    return await repo.get_trial_balance(organization_id, limit=limit)


async def get_balance_sheet(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    return await repo.get_balance_sheet(organization_id, limit=limit)


async def get_income_statement(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    return await repo.get_income_statement(organization_id, limit=limit)


async def get_customer_aging(
    organization_id: uuid.UUID,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await repo.get_customer_aging(organization_id, limit=limit)


async def get_supplier_aging(
    organization_id: uuid.UUID,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await repo.get_supplier_aging(organization_id, limit=limit)


async def get_recent_transactions(
    organization_id: uuid.UUID,
    *,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    return await repo.get_recent_transactions(organization_id, limit=limit)


async def get_cash_flow(
    organization_id: uuid.UUID,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Return cash flow statement data classified by activity type."""
    return await repo.get_cash_flow(organization_id, limit=limit)


async def generate_report(
    organization_id: uuid.UUID,
    *,
    report_type: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    account_id: Optional[uuid.UUID] = None,
    customer_id: Optional[uuid.UUID] = None,
    supplier_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """Dispatch to the appropriate report based on report_type."""
    report_type_lower = report_type.lower().replace(" ", "_").replace("-", "_")

    if report_type_lower in ("general_ledger", "gl"):
        data = await get_general_ledger(
            organization_id,
            from_date=from_date,
            to_date=to_date,
            account_id=account_id,
            limit=limit,
        )
    elif report_type_lower in ("trial_balance", "tb"):
        data = await get_trial_balance(organization_id, limit=limit)
    elif report_type_lower in ("balance_sheet", "bs"):
        data = await get_balance_sheet(organization_id, limit=limit)
    elif report_type_lower in ("income_statement", "profit_loss", "pl", "p&l"):
        data = await get_income_statement(organization_id, limit=limit)
    elif report_type_lower in ("customer_aging",):
        data = await get_customer_aging(organization_id, limit=limit)
    elif report_type_lower in ("supplier_aging",):
        data = await get_supplier_aging(organization_id, limit=limit)
    elif report_type_lower in ("recent_transactions",):
        data = await get_recent_transactions(organization_id, limit=limit)
    elif report_type_lower in ("cash_flow", "cashflow"):
        data = await get_cash_flow(organization_id, limit=limit)
    else:
        return {"report_type": report_type, "error": f"Unknown report type: {report_type}", "data": []}

    return {"report_type": report_type, "data": data, "record_count": len(data)}
