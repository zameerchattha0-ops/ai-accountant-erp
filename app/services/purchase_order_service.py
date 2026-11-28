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


async def _load_chain_context(organization_id: uuid.UUID) -> Dict[str, Any]:
    """Load org procurement documents and linked bills once (fail-open for mocked tests)."""
    all_orders: List[Dict[str, Any]] = []
    all_bills: List[Dict[str, Any]] = []
    suppliers_map: Dict[str, Dict[str, Any]] = {}
    try:
        all_orders = await fetch_many(
            "purchase_orders",
            filters={"organization_id": str(organization_id)},
            order="created_at.asc",
            limit=500,
        )
    except Exception:
        all_orders = []
    try:
        all_bills = await fetch_many(
            "purchase_bills",
            filters={"organization_id": str(organization_id)},
            select=(
                "id,bill_number,supplier_id,status,bill_date,total,subtotal,tax_total,"
                "currency_code,notes,supplier_invoice_ref,source_order_id,source_rfq_id,"
                "source_po_id,source_grn_id,created_at,updated_at"
            ),
            order="created_at.desc",
            limit=500,
        )
    except Exception:
        all_bills = []
    try:
        sup_rows = await fetch_many(
            "suppliers",
            filters={"organization_id": str(organization_id)},
            select="id,name,email,phone",
            limit=200,
        )
        suppliers_map = {str(s["id"]): s for s in sup_rows}
    except Exception:
        suppliers_map = {}

    orders_by_id = {str(o["id"]): o for o in all_orders if o.get("id")}
    bills_by_id = {str(b["id"]): b for b in all_bills if b.get("id")}
    bills_by_order_id: Dict[str, Dict[str, Any]] = {}
    for b in all_bills:
        for fk in ("source_order_id", "source_grn_id"):
            if b.get(fk):
                bills_by_order_id[str(b[fk])] = b
    return {
        "orders": all_orders,
        "orders_by_id": orders_by_id,
        "bills": all_bills,
        "bills_by_id": bills_by_id,
        "bills_by_order_id": bills_by_order_id,
        "suppliers_map": suppliers_map,
    }


def _build_chain_nodes(
    *,
    current_id: str,
    orders_by_id: Dict[str, Dict[str, Any]],
    bills_by_id: Dict[str, Dict[str, Any]],
    bills_by_order_id: Dict[str, Dict[str, Any]],
    start_order: Optional[Dict[str, Any]] = None,
    start_bill: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build chronological traceability chain [RFQ -> ORDERED -> RECEIVED -> BILLED]."""
    rfq_node: Optional[Dict[str, Any]] = None
    po_node: Optional[Dict[str, Any]] = None
    grn_node: Optional[Dict[str, Any]] = None
    bill_node: Optional[Dict[str, Any]] = start_bill

    if start_bill:
        for fk_col, slot in (("source_rfq_id", "rfq"), ("source_po_id", "po"), ("source_grn_id", "grn")):
            ref = start_bill.get(fk_col)
            if ref and str(ref) in orders_by_id:
                if slot == "rfq":
                    rfq_node = orders_by_id[str(ref)]
                elif slot == "po":
                    po_node = orders_by_id[str(ref)]
                else:
                    grn_node = orders_by_id[str(ref)]
        if not (rfq_node or po_node or grn_node) and start_bill.get("source_order_id"):
            src = orders_by_id.get(str(start_bill["source_order_id"]))
            if src:
                start_order = src

    if start_order:
        st = str(start_order.get("status") or "").upper()
        if st == "RFQ":
            rfq_node = start_order
        elif st == "ORDERED":
            po_node = start_order
        elif st == "RECEIVED":
            grn_node = start_order

        # Walk backward
        if not rfq_node and start_order.get("source_rfq_id"):
            rfq_node = orders_by_id.get(str(start_order["source_rfq_id"]))
        if not po_node and start_order.get("source_po_id"):
            po_node = orders_by_id.get(str(start_order["source_po_id"]))
        if start_order.get("parent_order_id"):
            parent = orders_by_id.get(str(start_order["parent_order_id"]))
            if parent:
                pst = str(parent.get("status") or "").upper()
                if pst == "RFQ" and not rfq_node:
                    rfq_node = parent
                elif pst == "ORDERED" and not po_node:
                    po_node = parent
                if parent.get("parent_order_id") and not rfq_node:
                    gp = orders_by_id.get(str(parent["parent_order_id"]))
                    if gp and str(gp.get("status") or "").upper() == "RFQ":
                        rfq_node = gp

        # Walk forward along promoted_to_order_id / promoted_to_bill_id
        cursor = start_order
        for _ in range(4):
            nxt_id = cursor.get("promoted_to_order_id")
            if not nxt_id or str(nxt_id) not in orders_by_id:
                break
            nxt = orders_by_id[str(nxt_id)]
            nst = str(nxt.get("status") or "").upper()
            if nst == "ORDERED" and not po_node:
                po_node = nxt
            elif nst == "RECEIVED" and not grn_node:
                grn_node = nxt
            cursor = nxt

        # Check bill on start_order or downstream cursor
        for node in (grn_node, po_node, rfq_node, start_order):
            if node and not bill_node:
                b_id = node.get("promoted_to_bill_id")
                if b_id and str(b_id) in bills_by_id:
                    bill_node = bills_by_id[str(b_id)]
                elif str(node.get("id")) in bills_by_order_id:
                    bill_node = bills_by_order_id[str(node["id"])]

    nodes: List[Dict[str, Any]] = []
    seen_ids = set()
    for stage_name, item, rec_type in (
        ("RFQ", rfq_node, "ORDER"),
        ("ORDERED", po_node, "ORDER"),
        ("RECEIVED", grn_node, "ORDER"),
        ("BILLED", bill_node, "BILL"),
    ):
        if not item or not item.get("id"):
            continue
        item_id = str(item["id"])
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        doc_num = item.get("bill_number") if rec_type == "BILL" else item.get("po_number")
        nodes.append({
            "id": item_id,
            "doc_number": doc_num or stage_name,
            "stage": stage_name,
            "status": str(item.get("status") or stage_name),
            "record_type": rec_type,
            "order_date": item.get("bill_date") if rec_type == "BILL" else item.get("order_date"),
            "total": float(item.get("total") or 0.0),
            "is_current": item_id == str(current_id),
        })
    return nodes


def _enrich_order_row(
    o: Dict[str, Any],
    *,
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    orders_by_id = ctx["orders_by_id"]
    bills_by_id = ctx["bills_by_id"]
    bills_by_order_id = ctx["bills_by_order_id"]
    suppliers_map = ctx["suppliers_map"]

    enriched = dict(o)
    oid = str(enriched.get("id") or "")
    s_id = str(enriched.get("supplier_id") or "")
    sup = suppliers_map.get(s_id, {})
    enriched["record_type"] = "ORDER"
    enriched["supplier_name"] = sup.get("name") or enriched.get("supplier_name") or "—"
    enriched["supplier_email"] = sup.get("email") or ""
    enriched["supplier_phone"] = sup.get("phone") or ""

    if oid and oid not in orders_by_id:
        orders_by_id[oid] = enriched

    parent = orders_by_id.get(str(enriched.get("parent_order_id") or ""))
    src_rfq = orders_by_id.get(str(enriched.get("source_rfq_id") or ""))
    src_po = orders_by_id.get(str(enriched.get("source_po_id") or ""))
    nxt_ord = orders_by_id.get(str(enriched.get("promoted_to_order_id") or ""))
    nxt_bill = (
        bills_by_id.get(str(enriched.get("promoted_to_bill_id") or ""))
        or bills_by_order_id.get(oid)
    )

    enriched["parent_po_number"] = parent.get("po_number") if parent else None
    enriched["source_rfq_number"] = src_rfq.get("po_number") if src_rfq else None
    enriched["source_po_number"] = src_po.get("po_number") if src_po else None
    enriched["promoted_to_po_number"] = nxt_ord.get("po_number") if nxt_ord else None
    enriched["promoted_to_status"] = nxt_ord.get("status") if nxt_ord else None
    if nxt_bill:
        enriched["promoted_to_bill_id"] = enriched.get("promoted_to_bill_id") or nxt_bill.get("id")
        enriched["promoted_to_bill_number"] = nxt_bill.get("bill_number")
        enriched["promoted_to_bill_status"] = nxt_bill.get("status")
    else:
        enriched["promoted_to_bill_number"] = None
        enriched["promoted_to_bill_status"] = None

    enriched["is_promoted"] = bool(enriched.get("promoted_to_order_id") or enriched.get("promoted_to_bill_id"))
    enriched["chain"] = _build_chain_nodes(
        current_id=oid,
        orders_by_id=orders_by_id,
        bills_by_id=bills_by_id,
        bills_by_order_id=bills_by_order_id,
        start_order=enriched,
    )
    return enriched


async def list_orders(
    organization_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    query: str = "",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    ctx = await _load_chain_context(organization_id)
    raw_orders = await po_repo.search_purchase_orders(
        organization_id, status=None, query=query, limit=limit
    )

    enriched_orders = [_enrich_order_row(o, ctx=ctx) for o in raw_orders]

    # Project Purchase Bills derived from procurement chain into the BILLED stage view
    billed_projections: List[Dict[str, Any]] = []
    suppliers_map = ctx["suppliers_map"]
    orders_by_id = ctx["orders_by_id"]
    bills_by_id = ctx["bills_by_id"]
    bills_by_order_id = ctx["bills_by_order_id"]

    for b in ctx["bills"]:
        has_link = any(b.get(k) for k in ("source_order_id", "source_grn_id", "source_po_id", "source_rfq_id"))
        if not has_link:
            continue
        bid = str(b["id"])
        s_id = str(b.get("supplier_id") or "")
        sup = suppliers_map.get(s_id, {})
        grn = orders_by_id.get(str(b.get("source_grn_id") or ""))
        po = orders_by_id.get(str(b.get("source_po_id") or ""))
        rfq = orders_by_id.get(str(b.get("source_rfq_id") or ""))
        src_ord = orders_by_id.get(str(b.get("source_order_id") or ""))
        chain = _build_chain_nodes(
            current_id=bid,
            orders_by_id=orders_by_id,
            bills_by_id=bills_by_id,
            bills_by_order_id=bills_by_order_id,
            start_bill=b,
        )
        proj = {
            "id": bid,
            "organization_id": str(organization_id),
            "po_number": b.get("bill_number") or "PUR",
            "record_type": "BILL",
            "bill_id": bid,
            "bill_status": b.get("status") or "DRAFT",
            "supplier_id": b.get("supplier_id"),
            "supplier_name": sup.get("name") or "—",
            "supplier_email": sup.get("email") or "",
            "supplier_phone": sup.get("phone") or "",
            "status": "BILLED",
            "order_date": b.get("bill_date"),
            "expected_delivery_date": None,
            "currency_code": b.get("currency_code") or "PKR",
            "subtotal": float(b.get("subtotal") or 0.0),
            "tax_total": float(b.get("tax_total") or 0.0),
            "total": float(b.get("total") or 0.0),
            "notes": b.get("notes"),
            "terms": None,
            "source_order_id": b.get("source_order_id"),
            "source_grn_id": b.get("source_grn_id"),
            "source_po_id": b.get("source_po_id"),
            "source_rfq_id": b.get("source_rfq_id"),
            "source_grn_number": (grn or (src_ord if src_ord and str(src_ord.get("status")).upper() == "RECEIVED" else None) or {}).get("po_number"),
            "source_po_number": (po or {}).get("po_number"),
            "source_rfq_number": (rfq or {}).get("po_number"),
            "is_promoted": False,
            "chain": chain,
            "created_at": b.get("created_at") or b.get("bill_date") or "",
            "updated_at": b.get("updated_at") or b.get("bill_date") or "",
        }
        if query:
            q_low = query.lower()
            haystack = " ".join(
                str(x or "") for x in (
                    proj["po_number"], proj["supplier_name"],
                    proj.get("source_grn_number"), proj.get("source_po_number"), proj.get("source_rfq_number"),
                )
            ).lower()
            if q_low not in haystack:
                continue
        billed_projections.append(proj)

    combined = billed_projections + enriched_orders
    combined.sort(key=lambda r: str(r.get("created_at") or r.get("order_date") or ""), reverse=True)

    status_upper = str(status or "ALL").upper()
    if status_upper != "ALL":
        combined = [r for r in combined if str(r.get("status") or "").upper() == status_upper]

    return combined[:limit]


async def get_order_with_items(
    organization_id: uuid.UUID, *, order_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    ctx = await _load_chain_context(organization_id)
    order = await po_repo.get_purchase_order(organization_id, order_id=order_id)
    if not order:
        bill = ctx["bills_by_id"].get(str(order_id))
        if not bill:
            bill = await fetch_one(
                "purchase_bills",
                filters={"id": str(order_id), "organization_id": str(organization_id)},
            )
        if not bill:
            return None
        bill_items = await fetch_many(
            "purchase_bill_items",
            filters={"bill_id": str(order_id), "organization_id": str(organization_id)},
            order="line_number.asc",
        )
        sup = None
        if bill.get("supplier_id"):
            sup = await supplier_service.get(organization_id, supplier_id=uuid.UUID(str(bill["supplier_id"])))
        chain = _build_chain_nodes(
            current_id=str(order_id),
            orders_by_id=ctx["orders_by_id"],
            bills_by_id=ctx["bills_by_id"],
            bills_by_order_id=ctx["bills_by_order_id"],
            start_bill=bill,
        )
        return {
            **bill,
            "po_number": bill.get("bill_number") or "PUR",
            "record_type": "BILL",
            "bill_id": str(order_id),
            "bill_status": bill.get("status"),
            "status": "BILLED",
            "order_date": bill.get("bill_date"),
            "items": bill_items,
            "supplier": sup,
            "supplier_name": (sup or {}).get("name") or "—",
            "chain": chain,
        }

    items = await po_repo.get_purchase_order_items(organization_id, order_id=order_id)
    enriched = _enrich_order_row(order, ctx=ctx)
    enriched["items"] = items

    if enriched.get("supplier_id"):
        sup = await supplier_service.get(organization_id, supplier_id=uuid.UUID(str(enriched["supplier_id"])))
        enriched["supplier"] = sup
        enriched["supplier_name"] = (sup or {}).get("name") or "—"
    else:
        enriched["supplier"] = None
        enriched["supplier_name"] = "—"

    return enriched


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
    parent_order_id: Optional[uuid.UUID] = None,
    source_rfq_id: Optional[uuid.UUID] = None,
    source_po_id: Optional[uuid.UUID] = None,
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
        parent_order_id=parent_order_id,
        source_rfq_id=source_rfq_id,
        source_po_id=source_po_id,
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
    """Advance procurement along an immutable linked stage chain:
    - RFQ -> ORDERED: preserves RFQ row & creates new PO-0000xx row linked back to RFQ
    - ORDERED -> RECEIVED: preserves PO row & creates new GRN-0000xx row linked back to PO/RFQ
    - RECEIVED -> BILLED: preserves GRN row & creates Purchase Bill (PUR-0000xx) linked back to GRN/PO/RFQ
    - * -> CANCELLED: marks un-promoted stage row CANCELLED in place
    """
    order = await get_order_with_items(organization_id, order_id=order_id)
    if not order:
        raise ValueError(f"Purchase order {order_id} not found")

    current_status = str(order.get("status") or "").upper()
    target_status = str(new_status or "").upper()

    if current_status == target_status:
        return order

    if current_status in ("CANCELLED", "BILLED"):
        raise ValueError(f"Purchase order is in locked status '{current_status}' and cannot be transitioned.")

    if order.get("promoted_to_order_id") or order.get("promoted_to_bill_id"):
        if target_status != "CANCELLED":
            nxt_ref = order.get("promoted_to_po_number") or order.get("promoted_to_bill_number") or "next stage"
            raise ValueError(f"Document {order.get('po_number')} was already promoted to {nxt_ref}.")

    if target_status == "CANCELLED":
        updated = await po_repo.update_purchase_order_status(
            organization_id, order_id=order_id, new_status="CANCELLED"
        )
        return await get_order_with_items(organization_id, order_id=order_id) or updated

    order_items = [
        {
            "product_id": it.get("product_id"),
            "description": it.get("description") or "Item",
            "quantity": float(it.get("quantity") or 1.0),
            "unit_price": float(it.get("unit_price") or 0.0),
            "tax_rate_id": it.get("tax_rate_id"),
            "tax_amount": float(it.get("tax_amount") or 0.0),
        }
        for it in (order.get("items") or [])
    ]

    source_rfq_uuid: Optional[uuid.UUID] = (
        order_id
        if current_status == "RFQ"
        else (uuid.UUID(str(order["source_rfq_id"])) if order.get("source_rfq_id") else None)
    )
    source_po_uuid: Optional[uuid.UUID] = (
        order_id
        if current_status == "ORDERED"
        else (uuid.UUID(str(order["source_po_id"])) if order.get("source_po_id") else None)
    )
    supp_uuid = uuid.UUID(str(order["supplier_id"])) if order.get("supplier_id") else None

    if target_status in ("ORDERED", "RECEIVED"):
        promoted = await po_repo.create_purchase_order(
            organization_id=organization_id,
            supplier_id=supp_uuid,
            items=order_items or [{"description": order.get("po_number") or "Procurement item", "quantity": 1.0, "unit_price": float(order.get("total") or 0.0)}],
            status=target_status,
            order_date=date.today().isoformat(),
            expected_delivery_date=order.get("expected_delivery_date"),
            currency_code=order.get("currency_code") or "PKR",
            notes=order.get("notes"),
            terms=order.get("terms"),
            parent_order_id=order_id,
            source_rfq_id=source_rfq_uuid,
            source_po_id=source_po_uuid,
        )
        promoted_id = uuid.UUID(str(promoted["id"]))
        await po_repo.mark_purchase_order_promoted(
            organization_id,
            order_id=order_id,
            promoted_to_order_id=promoted_id,
        )

        if target_status == "RECEIVED" and auto_receive_stock:
            from app.services import inventory_service
            for it in (promoted.get("items") or order.get("items") or []):
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
                                source_id=promoted_id,
                                description=f"Received on {promoted.get('po_number')} (PO {order.get('po_number')}) - {it.get('description')}",
                            )
                        except Exception as err:
                            log.warning("po.receive_stock_error", order_id=str(promoted_id), error=str(err))

        enriched_promoted = await get_order_with_items(organization_id, order_id=promoted_id) or promoted
        enriched_promoted["promoted_from"] = {
            "id": str(order_id),
            "po_number": order.get("po_number"),
            "status": current_status,
        }
        return enriched_promoted

    # Stage 4: BILLED
    created_bill = None
    if auto_create_bill:
        if not supp_uuid:
            raise ValueError("A supplier is required before converting to a Purchase Bill.")
        from app.services import purchase_service
        source_grn_uuid = order_id if current_status == "RECEIVED" else None
        chain_refs = [
            ref for ref in (
                order.get("po_number"),
                order.get("source_po_number"),
                order.get("source_rfq_number"),
            ) if ref
        ]
        bill_notes = f"Generated from {' <- '.join(chain_refs)}" if chain_refs else f"Generated from {order.get('po_number')}"
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
            supplier_id=supp_uuid,
            bill_date=date.today().isoformat(),
            supplier_invoice_ref=order.get("po_number"),
            notes=bill_notes,
            items=bill_items,
            source_order_id=order_id,
            source_rfq_id=source_rfq_uuid,
            source_po_id=source_po_uuid,
            source_grn_id=source_grn_uuid,
        )
        bill_id = uuid.UUID(str(created_bill["id"]))
        await po_repo.mark_purchase_order_promoted(
            organization_id,
            order_id=order_id,
            promoted_to_bill_id=bill_id,
        )
        result = await get_order_with_items(organization_id, order_id=bill_id) or await get_order_with_items(organization_id, order_id=order_id) or {}
        if created_bill:
            result["created_bill"] = created_bill
        return result

    updated = await po_repo.update_purchase_order_status(
        organization_id, order_id=order_id, new_status=target_status
    )
    return await get_order_with_items(organization_id, order_id=order_id) or updated

