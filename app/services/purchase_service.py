"""
Purchase Service — business logic for purchase bill operations.

Coordinates: supplier resolution → bill creation → accounting engine → journal.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import purchase_repository as repo
from app.database import call_rpc, fetch_many
from app.services import supplier_service
from app.services.item_validation import validate_document_items

log = structlog.get_logger(__name__)


async def create_purchase_bill(
    *,
    organization_id: uuid.UUID,
    supplier_id: uuid.UUID,
    bill_date: Optional[str] = None,
    due_date: Optional[str] = None,
    currency_code: str = "PKR",
    subtotal: float = 0.0,
    tax_total: float = 0.0,
    discount_total: float = 0.0,
    total: float = 0.0,
    payment_terms_days: Optional[int] = None,
    supplier_invoice_ref: Optional[str] = None,
    notes: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create a purchase bill after verifying the supplier exists.

    PARITY LAW: accepts the SAME ``items`` contract as the invoice service —
    identical validation, identical line_total computation, persisted via
    ``purchase_repository.add_purchase_bill_items``.
    """
    supplier = await supplier_service.get(organization_id, supplier_id=supplier_id)
    if not supplier:
        raise ValueError(f"Supplier {supplier_id} not found")

    # PARITY: validate + normalise lines BEFORE any write (no header-only
    # partial state when a line is invalid).
    normalized_items: List[Dict[str, Any]] = []
    if items is not None:
        normalized_items, item_totals = validate_document_items(items)
        subtotal = item_totals["subtotal"]
        discount_total = item_totals["discount_total"]
        tax_total = item_totals["tax_total"]
        total = item_totals["total"]

    b_date = bill_date or date.today().isoformat()
    if not due_date and payment_terms_days:
        due_date = (
            date.fromisoformat(b_date) + timedelta(days=payment_terms_days)
        ).isoformat()

    if total == 0:
        total = subtotal + tax_total - discount_total

    # ATOMIC POSTING (migration 077): the bill, its line items and (optionally)
    # a journal go into ONE database transaction, so a failure can never leave
    # a document without its lines — the partial state the previous two-write
    # sequence allowed. All arithmetic and validation above is unchanged; the
    # bill is created without a journal here (journal attachment on posting /
    # settlement is unchanged behaviour).
    header = {
        "supplier_id": str(supplier_id),
        "bill_date": b_date,
        "due_date": due_date,
        "currency_code": currency_code,
        "subtotal": subtotal,
        "discount_total": discount_total,
        "tax_total": tax_total,
        "total": total,
        "payment_terms_days": payment_terms_days,
        "supplier_invoice_ref": supplier_invoice_ref,
        "notes": notes,
        "created_by": str(created_by) if created_by else None,
    }
    items_payload = [
        {
            k: (str(v) if isinstance(v, uuid.UUID) else v)
            for k, v in item.items()
        }
        for item in normalized_items
    ]
    outcome = await call_rpc(
        "create_purchase_bill_atomic",
        params={
            "p_organization_id": str(organization_id),
            "p_header": header,
            "p_items": items_payload,
            "p_journal": None,
        },
    ) or {}
    bill = outcome.get("bill") or {}
    if outcome.get("items"):
        bill["items"] = outcome["items"]
        bill["item_count"] = outcome.get("item_count", 0)

    log.info(
        "purchase.bill_created",
        bill_id=bill["id"],
        supplier_id=str(supplier_id),
        total=total,
        item_count=bill.get("item_count", 0),
    )

    return bill


async def get_purchase_bill(
    organization_id: uuid.UUID, *, bill_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Fetch a purchase bill with its line items attached.

    Returns None when the bill does not exist (callers surface a not-found
    rather than an empty object).
    """
    bill = await repo.get_purchase_bill(organization_id, bill_id=bill_id)
    if not bill:
        return None
    items = await fetch_many(
        "purchase_bill_items",
        filters={
            "organization_id": str(organization_id),
            "bill_id": str(bill_id),
        },
        order="line_number.asc",
        limit=200,
    )
    bill["items"] = items
    bill["item_count"] = len(items)
    return bill


async def mark_bill_paid(
    organization_id: uuid.UUID, *, bill_id: uuid.UUID, amount: float
) -> None:
    """Mark a bill settled at creation (CASH purchases).

    A cash purchase credits Cash/Bank directly in its journal, so the bill
    must NOT stay open — an open bill would let a later "pay the supplier"
    settlement credit cash a SECOND time (double payment).  Same arithmetic
    as payment_service._update_bill_paid, but public and owned by the bill
    aggregate.
    """
    from app.database import update_one

    bill = await repo.get_purchase_bill(organization_id, bill_id=bill_id)
    if not bill:
        return
    new_paid = float(bill.get("amount_paid", 0)) + amount
    total = float(bill.get("total", 0))
    if new_paid >= total:
        status = "PAID"
    elif new_paid > 0:
        status = "PARTIALLY_PAID"
    else:
        status = bill.get("status", "OPEN")
    await update_one(
        "purchase_bills",
        row_id=bill_id,
        data={"amount_paid": new_paid, "status": status},
        organization_id=organization_id,
    )

    return await repo.get_purchase_bill(organization_id, bill_id=bill_id)
