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
from datetime import datetime, timezone
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


async def list_assets(
    organization_id: uuid.UUID, *, limit: int = 200
) -> List[Dict[str, Any]]:
    """The register listing (newest purchase first) for the Fixed Assets page.

    Returns EVERY status — the caller derives the status counts and the
    register summary from the full list and filters rows for display, so one
    database round-trip serves the whole page (mirrors the catalogue rule).
    """
    return await fetch_many(
        "fixed_assets",
        filters={"organization_id": str(organization_id)},
        select=(
            "id,asset_code,name,description,purchase_date,purchase_cost,"
            "salvage_value,useful_life_years,depreciation_method,"
            "accumulated_depreciation,book_value,status,gl_asset_account_id"
        ),
        order="purchase_date.desc",
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


async def list_asset_categories(
    organization_id: uuid.UUID, *, limit: int = 200
) -> List[Dict[str, Any]]:
    """The organisation's asset categories (default life / method / GL accounts).

    A category is pure CONFIGURATION: it never posts anything, it only prefills
    the acquisition form (and the AI's defaults) with the organisation's own
    policy — so registering an asset never has to invent a life or a method.
    """
    return await fetch_many(
        "asset_categories",
        filters={"organization_id": str(organization_id)},
        order="name.asc",
        limit=limit,
    )


async def get_asset_category(
    organization_id: uuid.UUID, *, category_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "asset_categories",
        filters={
            "id": str(category_id),
            "organization_id": str(organization_id),
        },
    )


async def create_asset_category(
    *,
    organization_id: uuid.UUID,
    name: str,
    description: Optional[str] = None,
    default_useful_life_years: Optional[int] = None,
    default_depreciation_method: str = "STRAIGHT_LINE",
    default_asset_account_id: Optional[uuid.UUID] = None,
    default_depreciation_expense_account_id: Optional[uuid.UUID] = None,
    default_accumulated_depreciation_account_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    return await insert_one(
        "asset_categories",
        data={
            "organization_id": str(organization_id),
            "name": name,
            "description": description,
            "default_useful_life_years": default_useful_life_years,
            "default_depreciation_method": default_depreciation_method,
            "default_asset_account_id": (
                str(default_asset_account_id) if default_asset_account_id else None
            ),
            "default_depreciation_expense_account_id": (
                str(default_depreciation_expense_account_id)
                if default_depreciation_expense_account_id else None
            ),
            "default_accumulated_depreciation_account_id": (
                str(default_accumulated_depreciation_account_id)
                if default_accumulated_depreciation_account_id else None
            ),
        },
    )


async def update_asset_category(
    row_id: uuid.UUID, *, fields: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Update mutable category columns by primary key (ownership pre-checked)."""
    payload = {
        key: (str(value) if isinstance(value, uuid.UUID) else value)
        for key, value in fields.items()
    }
    return await update_one("asset_categories", row_id=row_id, data=payload)


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


async def get_schedule_row_for_date(
    *,
    organization_id: uuid.UUID,
    asset_id: uuid.UUID,
    depreciation_date: str,
) -> Optional[Dict[str, Any]]:
    """The schedule row for ONE ``(asset, date)`` — the lookup behind the
    table's ``unique (asset_id, depreciation_date)``.

    Registration seeds a 0-value row on the PURCHASE date, so this is how a
    first charge dated the same day finds the row it must update instead of
    colliding with it (production 2026-10-03: a same-day charge posted its
    journal and then died on the unique key, returning 500).
    """
    return await fetch_one(
        "asset_depreciation_schedules",
        filters={
            "organization_id": str(organization_id),
            "asset_id": str(asset_id),
            "depreciation_date": depreciation_date,
        },
    )


async def get_depreciation_trail(
    organization_id: uuid.UUID, *, asset_id: uuid.UUID
) -> Dict[str, Any]:
    """The posted CHARGE trail for one asset.

    ``last_charged_date`` — the most recent date a NON-ZERO charge was posted
    (``None`` when nothing has been charged yet); that date — or the purchase
    date — is where the next charge's period STARTS (IAS 16: acquisition →
    charge date on the first run, the latest charge → charge date afterwards).

    ``charged_total`` — the sum of the charges in the trail, so the service can
    notice a charge that was posted but never reached the schedule: production
    2026-10-03 posted 54,333.33 and moved the asset's accumulated depreciation
    while the schedule write died on the unique key — the trail is incomplete
    and the next charge would silently overlap it.
    """
    rows = await fetch_many(
        "asset_depreciation_schedules",
        filters={
            "organization_id": str(organization_id),
            "asset_id": str(asset_id),
        },
        select="depreciation_date, depreciation_amount",
        order="depreciation_date.desc",
        limit=200,
    )
    last_charged: Optional[str] = None
    charged_total = 0.0
    for row in rows:
        amount = float(row.get("depreciation_amount") or 0)
        charged_total += amount
        if amount > 0 and last_charged is None:
            last_charged = str(row.get("depreciation_date"))
    return {
        "last_charged_date": last_charged,
        "charged_total": round(charged_total, 2),
        "rows": len(rows),
    }


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
    """Write the posted schedule row for the charge.

    Insert, except when ``unique (asset_id, depreciation_date)`` already has a
    row for that day — the registration seed row (0 charged so far, purchase
    date).  That row is UPDATED in place, so a first charge dated the purchase
    date still lands instead of raising after the journal was posted.  A row
    that already carries a real charge is rejected BEFORE posting by the
    service, so an update here can never silently swallow an earlier charge.
    """
    data: Dict[str, Any] = {
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
    }
    try:
        return await insert_one("asset_depreciation_schedules", data=data)
    except Exception:
        existing = await get_schedule_row_for_date(
            organization_id=organization_id,
            asset_id=asset_id,
            depreciation_date=depreciation_date,
        )
        if not existing:
            raise
        updates = {
            key: value
            for key, value in data.items()
            if key not in ("organization_id", "asset_id", "depreciation_date")
        }
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        return await update_one(
            "asset_depreciation_schedules",
            row_id=uuid.UUID(str(existing["id"])),
            data=updates,
        ) or existing


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

