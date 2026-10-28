"""
Purchase Order Service — business logic & lifecycle management for RFQs and POs.
Pipeline:
  RFQ / Draft Quotation -> ORDERED (Vendor Confirmed PO / In Transit)
  -> RECEIVED (GRN / Warehouse Stock Receipt)
  -> BILLED (Purchase Bill Generated)
  -> CANCELLED
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import structlog

from app.database import fetch_many, fetch_one
from app.repositories import purchase_order_repository as po_repo
from app.services import supplier_service

log = structlog.get_logger(__name__)


async def list_orders(
    organization_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    query: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    orders = await po_repo.search_purchase_orders(
        organization_id, status=status, query=query, limit=limit
    )
    if not orders:
        return []

    # Enrich with supplier details
    supplier_ids = list({o["supplier_id"] for o in orders if o.get("supplier_id")})
    suppliers_map: Dict[str, Any] = {}
    if supplier_ids:
        sup_rows = await fetch_many(
            "suppliers",
            filters={"organization_id": str(organization_id)},
            select="id,name,email,phone",
            limit=200,
        )
        suppliers_map = {str(s["id"]): s for s in sup_rows}

    for o in orders:
        s_id = str(o.get("supplier_id") or "")
        sup = suppliers_map.get(s_id, {})
        o["supplier_name"] = sup.get("name") or "—"
        o["supplier_email"] = sup.get("email") or ""
        o["supplier_phone"] = sup.get("phone") or ""

    return orders


async def get_order_with_items(
    organization_id: uuid.UUID, *, order_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    order = await po_repo.get_purchase_order(organization_id, order_id=order_id)
    if not order:
        return None
    items = await po_repo.get_purchase_order_items(organization_id, order_id=order_id)
    order["items"] = items

    if order.get("supplier_id"):
        sup = await supplier_service.get(organization_id, supplier_id=uuid.UUID(str(order["supplier_id"])))
        order["supplier"] = sup
        order["supplier_name"] = (sup or {}).get("name") or "—"
    else:
        order["supplier"] = None
        order["supplier_name"] = "—"

    return order


async def create_order(
    organization_id: uuid.UUID,
    *,
    supplier_id: Optional[uuid.UUID] = None,
    items: List[Dict[str, Any]],
    status: str = "RFQ",
    order_date: Optional[str] = None,
    expected_delivery_date: Optional[str] = None,
    notes: Optional[str] = None,
    terms: Optional[str] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    if supplier_id:
        sup = await supplier_service.get(organization_id, supplier_id=supplier_id)
        if not sup:
            raise ValueError(f"Supplier {supplier_id} not found")

    if not items:
        raise ValueError("Purchase order must contain at least one line item.")

    return await po_repo.create_purchase_order(
        organization_id=organization_id,
        supplier_id=supplier_id,
        items=items,
        status=status,
        order_date=order_date,
        expected_delivery_date=expected_delivery_date,
        notes=notes,
        terms=terms,
        created_by=created_by,
    )


async def transition_order_status(
    organization_id: uuid.UUID,
    *,
    order_id: uuid.UUID,
    new_status: str,
    auto_receive_stock: bool = True,
    auto_create_bill: bool = False,
) -> Dict[str, Any]:
    """Transition PO/RFQ status along the lifecycle:
    - RFQ -> ORDERED (Vendor confirms PO)
    - ORDERED -> RECEIVED (GRN - receives physical stock in warehouse)
    - RECEIVED -> BILLED (Converts to Purchase Bill)
    - Any -> CANCELLED
    """
    order = await get_order_with_items(organization_id, order_id=order_id)
    if not order:
        raise ValueError(f"Purchase order {order_id} not found")

    current_status = str(order.get("status") or "").upper()
    target_status = str(new_status or "").upper()

    if current_status == target_status:
        return order

    # Terminal lock guard
    if current_status in ("CANCELLED", "BILLED"):
        raise ValueError(f"Purchase order is in locked status '{current_status}' and cannot be transitioned.")

    # Execute transition
    updated = await po_repo.update_purchase_order_status(
        organization_id, order_id=order_id, new_status=target_status
    )

    # Side-effect A: When receiving stock, record receipt in perpetual inventory
    if target_status == "RECEIVED" and auto_receive_stock:
        from app.services import inventory_service
        items = order.get("items") or []
        for it in items:
            pid = it.get("product_id")
            if pid:
                p_uuid = uuid.UUID(str(pid))
                qty = float(it.get("quantity") or 0.0)
                unit_cost = float(it.get("unit_price") or 0.0)
                if qty > 0:
                    try:
                        await inventory_service.receive_stock(
                            organization_id,
                            product_id=p_uuid,
                            quantity=qty,
                            unit_cost=unit_cost,
                            source_type="purchase_order",
                            source_id=order_id,
                            description=f"Received against {order.get('po_number')} - {it.get('description')}",
                        )
                    except Exception as err:
                        log.warning("po.receive_stock_error", order_id=str(order_id), error=str(err))

    # Side-effect B: When billed, create purchase bill
    created_bill = None
    if target_status == "BILLED" and auto_create_bill and order.get("supplier_id"):
        from app.services import purchase_service
        try:
            bill_items = [
                {
                    "description": it.get("description") or "Item",
                    "product_id": it.get("product_id"),
                    "quantity": float(it.get("quantity") or 1.0),
                    "unit_price": float(it.get("unit_price") or 0.0),
                    "tax_amount": float(it.get("tax_amount") or 0.0),
                }
                for it in (order.get("items") or [])
            ]
            created_bill = await purchase_service.create_purchase_bill(
                organization_id=organization_id,
                supplier_id=uuid.UUID(str(order["supplier_id"])),
                bill_date=date.today().isoformat(),
                supplier_invoice_ref=order.get("po_number"),
                notes=f"Generated from Purchase Order {order.get('po_number')}",
                items=bill_items,
            )
        except Exception as b_err:
            log.warning("po.create_bill_error", order_id=str(order_id), error=str(b_err))

    result = await get_order_with_items(organization_id, order_id=order_id)
    if created_bill and result:
        result["created_bill"] = created_bill
    return result or updated
