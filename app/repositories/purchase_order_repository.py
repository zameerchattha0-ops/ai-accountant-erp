"""
Purchase Order Repository — CRUD for purchase_orders and purchase_order_items.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.database import call_rpc, fetch_many, fetch_one, insert_one, search_ilike, update_one


def stage_doc_type_and_prefix(status: str) -> Tuple[str, str]:
    """Return (document_sequences.doc_type, number prefix) per procurement stage."""
    st = str(status or "RFQ").upper()
    if st == "RFQ":
        return "PURCHASE_RFQ", "RFQ"
    if st == "RECEIVED":
        return "GOODS_RECEIPT_NOTE", "GRN"
    return "PURCHASE_ORDER", "PO"


async def generate_po_number(
    organization_id: uuid.UUID,
    prefix: str = "PO",
    *,
    doc_type: Optional[str] = None,
) -> str:
    """Generate sequential stage-specific procurement number (RFQ-/PO-/GRN-)."""
    resolved_prefix = str(prefix or "PO").upper()
    resolved_doc_type = doc_type or {
        "RFQ": "PURCHASE_RFQ",
        "GRN": "GOODS_RECEIPT_NOTE",
    }.get(resolved_prefix, "PURCHASE_ORDER")
    try:
        result = await call_rpc(
            "next_document_number",
            params={
                "p_org": str(organization_id),
                "p_doc_type": resolved_doc_type,
                "p_prefix": resolved_prefix,
            },
        )
        if isinstance(result, list) and result:
            return str(result[0])
        if isinstance(result, str) and result.strip():
            return result.strip()
    except Exception:
        pass
    return f"{resolved_prefix}-{uuid.uuid4().hex[:6].upper()}"


async def search_purchase_orders(
    organization_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    query: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    status_upper = status.upper() if status else "ALL"
    if status and status_upper != "ALL":
        filters["status"] = status_upper

    if query:
        rows = await search_ilike(
            "purchase_orders",
            column="po_number",
            value=query,
            organization_id=organization_id,
            limit=limit,
        )
        if status and status_upper != "ALL":
            return [r for r in rows if str(r.get("status") or "").upper() == status_upper]
        return rows
    return await fetch_many(
        "purchase_orders",
        filters=filters,
        order="created_at.desc",
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
    parent_order_id: Optional[uuid.UUID] = None,
    source_rfq_id: Optional[uuid.UUID] = None,
    source_po_id: Optional[uuid.UUID] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create a Purchase Order, RFQ, or Goods Receipt Note with lineage metadata."""
    status_upper = str(status or "RFQ").upper()
    doc_type, prefix = stage_doc_type_and_prefix(status_upper)
    po_number = await generate_po_number(organization_id, prefix=prefix, doc_type=doc_type)

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

    payload: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "po_number": po_number,
        "supplier_id": str(supplier_id) if supplier_id else None,
        "status": status_upper,
        "order_date": order_date or date.today().isoformat(),
        "expected_delivery_date": expected_delivery_date,
        "currency_code": currency_code or "PKR",
        "subtotal": round(subtotal, 2),
        "tax_total": round(tax_total, 2),
        "total": round(total, 2),
        "notes": notes,
        "terms": terms,
        "created_by": str(created_by) if created_by else None,
    }
    if parent_order_id:
        payload["parent_order_id"] = str(parent_order_id)
    if source_rfq_id:
        payload["source_rfq_id"] = str(source_rfq_id)
    if source_po_id:
        payload["source_po_id"] = str(source_po_id)

    order = await insert_one("purchase_orders", data=payload)

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


async def mark_purchase_order_promoted(
    organization_id: uuid.UUID,
    *,
    order_id: uuid.UUID,
    promoted_to_order_id: Optional[uuid.UUID] = None,
    promoted_to_bill_id: Optional[uuid.UUID] = None,
    promoted_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Mark a preserved RFQ/PO/GRN stage document as promoted to its downstream stage."""
    data: Dict[str, Any] = {
        "promoted_at": promoted_at or datetime.now(timezone.utc).isoformat(),
    }
    if promoted_to_order_id:
        data["promoted_to_order_id"] = str(promoted_to_order_id)
    if promoted_to_bill_id:
        data["promoted_to_bill_id"] = str(promoted_to_bill_id)
    return await update_one(
        "purchase_orders",
        row_id=order_id,
        data=data,
        organization_id=organization_id,
    )


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
        row_id=order_id,
        data={"status": status_upper},
        organization_id=organization_id,
    )

