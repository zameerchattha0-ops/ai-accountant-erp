"""
Organization Repository — Supabase data access for organizations and membership.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one


async def get_organization(
    *, organization_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "organizations", filters={"id": str(organization_id)}
    )


async def get_user_membership(
    *, user_id: uuid.UUID
) -> List[Dict[str, Any]]:
    """Return all active organisation memberships for a user."""
    return await fetch_many(
        "organization_members",
        filters={"user_id": str(user_id), "status": "ACTIVE"},
    )


async def get_user_organization(
    *, user_id: uuid.UUID, organization_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Check if a user belongs to a specific organisation."""
    return await fetch_one(
        "organization_members",
        filters={
            "user_id": str(user_id),
            "organization_id": str(organization_id),
            "status": "ACTIVE",
        },
    )


async def get_financial_years(
    organization_id: uuid.UUID,
    *,
    is_current: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if is_current is not None:
        filters["is_current"] = is_current
    return await fetch_many("financial_years", filters=filters, order="start_date.desc")


async def get_current_financial_year(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "financial_years",
        filters={"organization_id": str(organization_id), "is_current": True},
    )


async def get_accounting_periods(
    organization_id: uuid.UUID,
    *,
    financial_year_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if financial_year_id:
        filters["financial_year_id"] = str(financial_year_id)
    if status:
        filters["status"] = status
    return await fetch_many(
        "accounting_periods", filters=filters, order="start_date.asc"
    )


async def get_open_accounting_period(
    organization_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """Return the first open accounting period for the current financial year."""
    fy = await get_current_financial_year(organization_id)
    if not fy:
        return None
    periods = await get_accounting_periods(
        organization_id, financial_year_id=uuid.UUID(fy["id"]), status="OPEN"
    )
    return periods[0] if periods else None


async def get_bank_accounts(
    organization_id: uuid.UUID,
    *,
    is_active: bool = True,
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "bank_accounts",
        filters={"organization_id": str(organization_id), "is_active": is_active},
        order="bank_name.asc",
    )
