"""
Purchase Return Repository — CRUD for purchase_returns and purchase_return_items.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, update_one


async def get_purchase_return(
    organization_id: uuid.UUID, *, return_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "purchase_returns",
        filters={"id": str(return_id), "organization_id": str(organization_id)},
    )


async def list_purchase_returns(
    organization_id: uuid.UUID, *, limit: int = 500
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "purchase_returns",
        filters={"organization_id": str(organization_id)},
        order="created_at.desc",
        limit=limit,
    )


async def get_purchase_return_items(
    organization_id: uuid.UUID, *, return_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "purchase_return_items",
        filters={"return_id": str(return_id), "organization_id": str(organization_id)},
        order="line_number.asc",
    )


async def create_purchase_return(
    *,
    organization_id: uuid.UUID,
    supplier_id: uuid.UUID,
    items: List[Dict[str, Any]],
    bill_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
    return_date: Optional[str] = None,
    currency_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a purchase return with line items."""
    subtotal = sum(float(it.get("line_total", 0)) for it in items)
    tax_total = sum(float(it.get("tax_amount", 0)) for it in items)
    total = subtotal + tax_total

    purchase_return = await insert_one(
        "purchase_returns",
        data={
            "organization_id": str(organization_id),
            "supplier_id": str(supplier_id),
            "bill_id": str(bill_id) if bill_id else None,
            "status": "DRAFT",
            "return_date": return_date or date.today().isoformat(),
            "currency_code": currency_code or "PKR",
            "subtotal": subtotal,
            "tax_total": tax_total,
            "total": total,
            "reason": reason,
        },
    )

    for idx, item in enumerate(items, start=1):
        await insert_one(
            "purchase_return_items",
            data={
                "organization_id": str(organization_id),
                "return_id": purchase_return["id"],
                "line_number": idx,
                "description": item.get("description", ""),
                "bill_item_id": item.get("bill_item_id"),
                "product_id": item.get("product_id"),
                "quantity": float(item.get("quantity", 1)),
                "unit_price": float(item.get("unit_price", 0)),
                "tax_amount": float(item.get("tax_amount", 0)),
                "line_total": float(item.get("line_total", 0)),
            },
        )

    purchase_return["items"] = items
    purchase_return["total"] = total
    return purchase_return


async def link_journal_to_purchase_return(
    *, return_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Source-tie the posted journal back to the purchase return row."""
    return await update_one(
        "purchase_returns",
        row_id=return_id,
        data={"journal_entry_id": str(journal_entry_id)},
    )


async def mark_open(*, return_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    """Transition DRAFT → OPEN once the reversal journal is posted.

    bill_status has no ISSUED value — OPEN is the posted state (mirrors
    purchase bills), so payables/aging views reflect the reversal.
    """
    return await update_one(
        "purchase_returns",
        row_id=return_id,
        data={"status": "OPEN"},
    )


async def set_status(
    *, return_id: uuid.UUID, status: str
) -> Optional[Dict[str, Any]]:
    """Status-only transition (DRAFT → OPEN/VOIDED, OPEN → VOIDED)."""
    return await update_one(
        "purchase_returns",
        row_id=return_id,
        data={"status": status},
    )
