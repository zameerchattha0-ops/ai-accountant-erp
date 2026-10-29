"""
Purchase Order Repository — CRUD for purchase_orders and purchase_order_items.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from app.database import call_rpc, fetch_many, fetch_one, insert_one, search_ilike, update_one


async def generate_po_number(organization_id: uuid.UUID, prefix: str = "PO") -> str:
    """Generate sequential PO/RFQ document number safely."""
    try:
        result = await call_rpc(
            "next_document_number",
            params={
                "p_org": str(organization_id),
                "p_doc_type": "PURCHASE_ORDER",
                "p_prefix": prefix,
            },
        )
        if isinstance(result, list) and result:
            return str(result[0])
        if isinstance(result, str) and result.strip():
            return result.strip()
    except Exception:
        pass
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


async def search_purchase_orders(
    organization_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    query: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if status and status.upper() != "ALL":
        filters["status"] = status.upper()

    if query:
        return await search_ilike(
            "purchase_orders",
            column="po_number",
            value=query,
            organization_id=organization_id,
            limit=limit,
        )
    return await fetch_many(
        "purchase_orders",
        filters=filters,
        order="order_date.desc",
        limit=limit,
    )


async def get_purchase_order(
    organization_id: uuid.UUID, *, order_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "purchase_orders",
        filters={"id": str(order_id), "organization_id": str(organization_id)},
    )


async def get_purchase_order_items(
    organization_id: uuid.UUID, *, order_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "purchase_order_items",
        filters={"purchase_order_id": str(order_id), "organization_id": str(organization_id)},
        order="line_number.asc",
    )


async def create_purchase_order(
    *,
    organization_id: uuid.UUID,
    supplier_id: Optional[uuid.UUID] = None,
    items: List[Dict[str, Any]],
    status: str = "RFQ",
    order_date: Optional[str] = None,
    expected_delivery_date: Optional[str] = None,
    currency_code: Optional[str] = "PKR",
    notes: Optional[str] = None,
    terms: Optional[str] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create a Purchase Order or RFQ with multi-line items."""
    prefix = "RFQ" if status.upper() == "RFQ" else "PO"
    po_number = await generate_po_number(organization_id, prefix=prefix)

    subtotal = 0.0
    tax_total = 0.0

    calculated_items: List[Dict[str, Any]] = []
    for idx, it in enumerate(items, start=1):
        qty = float(it.get("quantity") or 1.0)
        price = float(it.get("unit_price") or 0.0)
        tax = float(it.get("tax_amount") or 0.0)
        line_tot = (qty * price) + tax
        subtotal += (qty * price)
        tax_total += tax

        calculated_items.append({
            "line_number": idx,
            "product_id": str(it.get("product_id")) if it.get("product_id") else None,
            "description": it.get("description") or f"Item {idx}",
            "quantity": qty,
            "unit_price": price,
            "tax_rate_id": str(it.get("tax_rate_id")) if it.get("tax_rate_id") else None,
            "tax_amount": tax,
            "line_total": line_tot,
        })

    total = subtotal + tax_total

    order = await insert_one(
        "purchase_orders",
        data={
            "organization_id": str(organization_id),
            "po_number": po_number,
            "supplier_id": str(supplier_id) if supplier_id else None,
            "status": status.upper(),
            "order_date": order_date or date.today().isoformat(),
            "expected_delivery_date": expected_delivery_date,
            "currency_code": currency_code or "PKR",
            "subtotal": round(subtotal, 2),
            "tax_total": round(tax_total, 2),
            "total": round(total, 2),
            "notes": notes,
            "terms": terms,
            "created_by": str(created_by) if created_by else None,
        },
    )

    inserted_items = []
    for item_data in calculated_items:
        inserted_item = await insert_one(
            "purchase_order_items",
            data={
                "organization_id": str(organization_id),
                "purchase_order_id": str(order["id"]),
                **item_data,
            },
        )
        inserted_items.append(inserted_item)

    order["items"] = inserted_items
    return order


async def update_purchase_order_status(
    organization_id: uuid.UUID,
    *,
    order_id: uuid.UUID,
    new_status: str,
) -> Optional[Dict[str, Any]]:
    valid_statuses = {"RFQ", "ORDERED", "RECEIVED", "BILLED", "CANCELLED"}
    status_upper = new_status.upper()
    if status_upper not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of {valid_statuses}")

    return await update_one(
        "purchase_orders",
        data={"status": status_upper},
        filters={"id": str(order_id), "organization_id": str(organization_id)},
    )

