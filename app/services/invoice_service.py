"""
Invoice Service — business logic for sales invoice operations.

Coordinates: customer resolution → invoice creation → accounting engine → journal.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import invoice_repository as inv_repo
from app.repositories import invoice_item_repository as item_repo
from app.services import customer_service, accounting_service
from app.services.item_validation import validate_document_items

log = structlog.get_logger(__name__)


async def create_invoice(
    *,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    invoice_date: Optional[str] = None,
    due_date: Optional[str] = None,
    currency_code: str = "PKR",
    subtotal: float = 0.0,
    tax_total: float = 0.0,
    discount_total: float = 0.0,
    total: float = 0.0,
    payment_terms_days: Optional[int] = None,
    project_id: Optional[uuid.UUID] = None,
    quotation_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
    terms: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create a sales invoice and optionally generate journal entry.

    PARITY LAW: when *items* is provided, every line is validated and its
    ``line_total`` computed HERE (never trusted from the caller) and the
    lines are persisted through ``invoice_item_repository.add_invoice_items``
    — the SAME repository the manual path must use.  The header totals are
    then recomputed from the lines so the invoice header can never disagree
    with its own line items.
    """
    # Verify customer exists
    customer = await customer_service.get(organization_id, customer_id=customer_id)
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    # PARITY: validate + normalise line items BEFORE any write so an
    # invalid line never leaves a header-only partial state behind.
    normalized_items: List[Dict[str, Any]] = []
    if items is not None:
        normalized_items, item_totals = validate_document_items(items)
        subtotal = item_totals["subtotal"]
        discount_total = item_totals["discount_total"]
        tax_total = item_totals["tax_total"]
        total = item_totals["total"]

    # Verify the source quotation exists (cross-module dependency — the
    # quotation must belong to the same organization AND the same customer
    # so the receivable cannot be attached to the wrong party).
    if quotation_id:
        from app.repositories import quotation_repository as quote_repo
        quotation = await quote_repo.get_quotation(
            organization_id, quotation_id=quotation_id
        )
        if not quotation:
            raise ValueError(
                f"Quotation {quotation_id} not found for this organization"
            )
        if str(quotation.get("customer_id")) != str(customer_id):
            raise ValueError(
                "Quotation belongs to a different customer — refusing to "
                "convert it into an invoice for another party"
            )

    inv_date = invoice_date or date.today().isoformat()
    if not due_date and payment_terms_days:
        due_date = (
            date.fromisoformat(inv_date) + timedelta(days=payment_terms_days)
        ).isoformat()

    if total == 0:
        total = subtotal + tax_total - discount_total

    invoice = await inv_repo.create_invoice(
        organization_id=organization_id,
        customer_id=customer_id,
        invoice_date=inv_date,
        due_date=due_date,
        currency_code=currency_code,
        subtotal=subtotal,
        tax_total=tax_total,
        discount_total=discount_total,
        total=total,
        payment_terms_days=payment_terms_days,
        project_id=project_id,
        quotation_id=quotation_id,
        notes=notes,
        terms=terms,
        created_by=created_by,
    )

    # PARITY: persist the line items through the repository — the AI tool
    # path and any future backend-API path land in the exact same rows the
    # manual form produces (identical shape, identical validation).
    if normalized_items:
        saved_items = await item_repo.add_invoice_items(
            organization_id, invoice_id=uuid.UUID(str(invoice["id"])),
            items=normalized_items,
        )
        invoice["items"] = saved_items
        invoice["item_count"] = len(saved_items)

    log.info(
        "invoice.created",
        invoice_id=invoice["id"],
        customer_id=str(customer_id),
        total=total,
        item_count=invoice.get("item_count", 0),
    )

    return invoice


async def get_invoice(
    organization_id: uuid.UUID, *, invoice_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await inv_repo.get_invoice(organization_id, invoice_id=invoice_id)
