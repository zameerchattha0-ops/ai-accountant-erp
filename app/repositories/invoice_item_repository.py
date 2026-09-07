"""
Invoice Items Repository — CRUD for multi-line invoice items.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from app.database import fetch_many, insert_one


async def get_invoice_items(
    organization_id: uuid.UUID, *, invoice_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "invoice_items",
        filters={"invoice_id": str(invoice_id), "organization_id": str(organization_id)},
        order="line_number.asc",
    )


async def add_invoice_items(
    organization_id: uuid.UUID,
    *,
    invoice_id: uuid.UUID,
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert multiple line items for an invoice."""
    created = []
    for idx, item in enumerate(items, start=1):
        row = await insert_one(
            "invoice_items",
            data={
                "organization_id": str(organization_id),
                "invoice_id": str(invoice_id),
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
                "revenue_account_id": item.get("revenue_account_id"),
            },
        )
        created.append(row)
    return created
