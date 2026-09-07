"""
Credit Note Repository — CRUD for credit_notes and credit_note_items.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one


async def get_credit_note(
    organization_id: uuid.UUID, *, credit_note_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "credit_notes",
        filters={"id": str(credit_note_id), "organization_id": str(organization_id)},
    )


async def get_credit_note_items(
    organization_id: uuid.UUID, *, credit_note_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "credit_note_items",
        filters={"credit_note_id": str(credit_note_id), "organization_id": str(organization_id)},
        order="line_number.asc",
    )


async def create_credit_note(
    *,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    items: List[Dict[str, Any]],
    invoice_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
    credit_note_date: Optional[str] = None,
    currency_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a credit note with line items."""
    subtotal = sum(float(it.get("line_total", 0)) for it in items)
    discount_total = sum(float(it.get("discount_amount", 0)) for it in items)
    tax_total = sum(float(it.get("tax_amount", 0)) for it in items)
    total = subtotal - discount_total + tax_total

    credit_note = await insert_one(
        "credit_notes",
        data={
            "organization_id": str(organization_id),
            "customer_id": str(customer_id),
            "invoice_id": str(invoice_id) if invoice_id else None,
            "status": "DRAFT",
            "credit_note_date": credit_note_date or date.today().isoformat(),
            "currency_code": currency_code or "PKR",
            "subtotal": subtotal,
            "discount_total": discount_total,
            "tax_total": tax_total,
            "total": total,
            "reason": reason,
        },
    )

    for idx, item in enumerate(items, start=1):
        await insert_one(
            "credit_note_items",
            data={
                "organization_id": str(organization_id),
                "credit_note_id": credit_note["id"],
                "line_number": idx,
                "description": item.get("description", ""),
                "invoice_item_id": item.get("invoice_item_id"),
                "product_id": item.get("product_id"),
                "service_id": item.get("service_id"),
                "quantity": float(item.get("quantity", 1)),
                "unit_price": float(item.get("unit_price", 0)),
                "discount_amount": float(item.get("discount_amount", 0)),
                "tax_rate_id": item.get("tax_rate_id"),
                "tax_amount": float(item.get("tax_amount", 0)),
                "line_total": float(item.get("line_total", 0)),
            },
        )

    credit_note["items"] = items
    credit_note["total"] = total
    return credit_note
