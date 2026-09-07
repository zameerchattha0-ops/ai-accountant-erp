"""
Fixed Asset Repository — Supabase data access for the fixed-asset lifecycle.

The database contract is authoritative:
* ``public.fixed_assets`` — asset_code auto-assigned by the
  ``trg_fixed_assets_number`` trigger; UNIQUE per organization;
  ``status`` is the ``asset_status`` enum
  (ACTIVE, FULLY_DEPRECIATED, DISPOSED, SOLD, WRITTEN_OFF);
  per-asset GL account columns (gl_asset_account_id,
  gl_depreciation_expense_account_id, gl_accumulated_depreciation_account_id).
* ``public.asset_transactions`` — lifecycle audit trail with an optional
  journal_entry_id source link.
* ``public.asset_depreciation_schedules`` — posted depreciation history.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, search_ilike, update_one


async def search_assets(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    """Search registered assets by name or code ([] = no match — valid
    information: the asset is not registered, never a database failure)."""
    return await search_ilike(
        "fixed_assets",
        column="name",
        value=query,
        organization_id=organization_id,
        select=(
            "id,asset_code,name,purchase_date,purchase_cost,salvage_value,"
            "useful_life_years,depreciation_method,accumulated_depreciation,"
            "book_value,status,gl_asset_account_id"
        ),
        limit=limit,
    )


async def get_asset(
    organization_id: uuid.UUID, *, asset_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "fixed_assets",
        filters={
            "id": str(asset_id),
            "organization_id": str(organization_id),
        },
    )


async def create_asset(
    *,
    organization_id: uuid.UUID,
    name: str,
    purchase_date: str,
    purchase_cost: float,
    salvage_value: float = 0.0,
    useful_life_years: Optional[int] = None,
    depreciation_method: str = "STRAIGHT_LINE",
    depreciation_rate_percent: Optional[float] = None,
    category_id: Optional[uuid.UUID] = None,
    supplier_id: Optional[uuid.UUID] = None,
    gl_asset_account_id: Optional[uuid.UUID] = None,
    gl_depreciation_expense_account_id: Optional[uuid.UUID] = None,
    gl_accumulated_depreciation_account_id: Optional[uuid.UUID] = None,
    description: Optional[str] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Register an asset. ``asset_code`` is assigned by the DB trigger and
    MUST NOT be supplied here (the trigger contract is authoritative)."""
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "name": name,
        "description": description,
        "purchase_date": purchase_date,
        "purchase_cost": purchase_cost,
        "salvage_value": salvage_value,
        "useful_life_years": useful_life_years,
        "depreciation_method": depreciation_method,
        "depreciation_rate_percent": depreciation_rate_percent,
        "accumulated_depreciation": 0,
        "status": "ACTIVE",
        "category_id": str(category_id) if category_id else None,
        "supplier_id": str(supplier_id) if supplier_id else None,
        "gl_asset_account_id": str(gl_asset_account_id) if gl_asset_account_id else None,
        "gl_depreciation_expense_account_id": (
            str(gl_depreciation_expense_account_id)
            if gl_depreciation_expense_account_id else None
        ),
        "gl_accumulated_depreciation_account_id": (
            str(gl_accumulated_depreciation_account_id)
            if gl_accumulated_depreciation_account_id else None
        ),
        "created_by": str(created_by) if created_by else None,
    }
    return await insert_one("fixed_assets", data=data)


async def update_asset_by_id(
    row_id: uuid.UUID, *, fields: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Update mutable asset columns by primary key.  The service layer has
    already verified organization ownership of the fetched row."""
    payload = {
        k: (str(v) if isinstance(v, uuid.UUID) else v)
        for k, v in fields.items()
    }
    return await update_one("fixed_assets", row_id=row_id, data=payload)


async def record_asset_transaction(
    *,
    organization_id: uuid.UUID,
    asset_id: uuid.UUID,
    transaction_type: str,
    transaction_date: str,
    amount: float,
    journal_entry_id: Optional[uuid.UUID] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append the lifecycle audit trail row (source-tied to its journal)."""
    return await insert_one("asset_transactions", data={
        "organization_id": str(organization_id),
        "asset_id": str(asset_id),
        "transaction_type": transaction_type,
        "transaction_date": transaction_date,
        "amount": amount,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
        "details": details or {},
    })


async def record_depreciation_schedule(
    *,
    organization_id: uuid.UUID,
    asset_id: uuid.UUID,
    depreciation_date: str,
    opening_book_value: float,
    depreciation_amount: float,
    closing_book_value: float,
    journal_entry_id: Optional[uuid.UUID] = None,
    accounting_period_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Insert a posted depreciation schedule row."""
    return await insert_one("asset_depreciation_schedules", data={
        "organization_id": str(organization_id),
        "asset_id": str(asset_id),
        "accounting_period_id": (
            str(accounting_period_id) if accounting_period_id else None
        ),
        "depreciation_date": depreciation_date,
        "opening_book_value": opening_book_value,
        "depreciation_amount": depreciation_amount,
        "closing_book_value": closing_book_value,
        "is_posted": True,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
    })


async def get_asset_transactions(
    organization_id: uuid.UUID,
    *,
    asset_id: uuid.UUID,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "asset_transactions",
        filters={
            "asset_id": str(asset_id),
            "organization_id": str(organization_id),
        },
        order="transaction_date.desc",
        limit=limit,
    )

