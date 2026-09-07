"""
Quotation Repository — CRUD for quotations and quotation_items.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, search_ilike, update_one


async def search_quotations(
    organization_id: uuid.UUID, *, query: str = "", limit: int = 25
) -> List[Dict[str, Any]]:
    if query:
        return await search_ilike(
            "quotations", column="quotation_number", value=query,
            organization_id=organization_id, limit=limit,
        )
    return await fetch_many(
        "quotations",
        filters={"organization_id": str(organization_id)},
        order="quotation_date.desc",
        limit=limit,
    )


async def get_quotation(
    organization_id: uuid.UUID, *, quotation_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "quotations",
        filters={"id": str(quotation_id), "organization_id": str(organization_id)},
    )


async def get_quotation_items(
    organization_id: uuid.UUID, *, quotation_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "quotation_items",
        filters={"quotation_id": str(quotation_id), "organization_id": str(organization_id)},
        order="line_number.asc",
    )


async def create_quotation(
    *,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    items: List[Dict[str, Any]],
    quotation_date: Optional[str] = None,
    valid_until: Optional[str] = None,
    currency_code: Optional[str] = None,
    project_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
    terms: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a quotation with line items. Returns the quotation dict."""
    subtotal = sum(float(it.get("line_total", 0)) for it in items)
    discount_total = sum(float(it.get("discount_amount", 0)) for it in items)
    tax_total = sum(float(it.get("tax_amount", 0)) for it in items)
    total = subtotal - discount_total + tax_total

    quotation = await insert_one(
        "quotations",
        data={
            "organization_id": str(organization_id),
            "customer_id": str(customer_id),
            "revision": 1,
            "status": "DRAFT",
            "quotation_date": quotation_date or date.today().isoformat(),
            "valid_until": valid_until,
            "currency_code": currency_code or "PKR",
            "subtotal": subtotal,
            "discount_total": discount_total,
            "tax_total": tax_total,
            "total": total,
            "notes": notes,
            "terms": terms,
            "project_id": str(project_id) if project_id else None,
        },
    )

    # Insert line items
    for idx, item in enumerate(items, start=1):
        await insert_one(
            "quotation_items",
            data={
                "organization_id": str(organization_id),
                "quotation_id": quotation["id"],
                "line_number": idx,
                "description": item.get("description", ""),
                "product_id": item.get("product_id"),
                "service_id": item.get("service_id"),
                "project_id": item.get("project_id"),
                "quantity": float(item.get("quantity", 1)),
                "unit_price": float(item.get("unit_price", 0)),
                "discount_amount": float(item.get("discount_amount", 0)),
                "tax_rate_id": item.get("tax_rate_id"),
                "tax_amount": float(item.get("tax_amount", 0)),
                "line_total": float(item.get("line_total", 0)),
                "notes": item.get("notes"),
            },
        )

    quotation["items"] = items
    quotation["total"] = total
    return quotation


async def mark_converted(
    organization_id: uuid.UUID, *, quotation_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Transition an accepted/issued quotation to CONVERTED.

    Only quotations that have NOT already been converted may transition —
    the UPDATE itself is guarded (status <> 'CONVERTED') so a concurrent
    double conversion cannot both succeed.
    """
    # Guarded read first for a clean error message on the common path.
    quotation = await get_quotation(
        organization_id, quotation_id=quotation_id
    )
    if not quotation:
        return None
    if quotation.get("status") == "CONVERTED":
        return quotation
    return await update_one(
        "quotations",
        row_id=quotation_id,
        data={"status": "CONVERTED"},
    )
