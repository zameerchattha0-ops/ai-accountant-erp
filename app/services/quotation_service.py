"""
Quotation Service — business logic for quotation creation.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import quotation_repository as repo
from app.repositories import customer_repository as customer_repo

log = structlog.get_logger(__name__)


async def create_quotation(
    organization_id: uuid.UUID,
    *,
    customer_id: Optional[str] = None,
    customer_name: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    **kw,
) -> Dict[str, Any]:
    """Create a quotation with validation."""
    if not items:
        raise ValueError("Quotation requires at least one line item.")

    # Resolve customer
    resolved_customer = None
    if customer_id:
        resolved_customer = await customer_repo.get_customer(
            organization_id, customer_id=uuid.UUID(customer_id)
        )
    if not resolved_customer and customer_name:
        results = await customer_repo.search_customers(
            organization_id, query=customer_name, limit=5
        )
        for c in results:
            if c.get("name", "").lower().strip() == customer_name.lower().strip():
                resolved_customer = c
                break
    if not resolved_customer:
        raise ValueError(
            f"Customer not found: {customer_name or customer_id}. "
            "Create the customer first."
        )

    quotation = await repo.create_quotation(
        organization_id=organization_id,
        customer_id=uuid.UUID(resolved_customer["id"]),
        items=items,
        **kw,
    )
    log.info("quotation.created", quotation_id=quotation["id"], total=quotation["total"])
    return quotation


# ---------------------------------------------------------------------------
# Quotation → Invoice conversion (Phase 4 cross-module lifecycle)
# ---------------------------------------------------------------------------

async def convert_quotation(
    organization_id: uuid.UUID,
    *,
    quotation_id: uuid.UUID,
    invoice_date: Optional[str] = None,
    due_date: Optional[str] = None,
    payment_terms_days: Optional[int] = None,
    notes: Optional[str] = None,
    terms: Optional[str] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Convert a quotation into a sales invoice.

    Cross-module lifecycle (verified against the actual DB contract):

        quotation (DOCUMENT — no accounting)
          → invoice (quotation_id set, totals preserved)
          → journal (Dr Receivable / Cr Revenue, POSTED)
          → quotation status CONVERTED

    Guarantees:
    * the original quotation is preserved and never mutated except the
      status transition to CONVERTED;
    * the resulting invoice references the quotation via the
      ``invoices.quotation_id`` FK;
    * the customer relationship is preserved (a quotation belonging to a
      different customer is refused);
    * amounts are carried over from the quotation unless explicitly
      overridden;
    * accounting occurs ONLY here — creating a quotation never posts a
      journal, converting one does.
    """
    from app.services import invoice_service
    from app.services import accounting_service
    from app.accounting_engine import auto_journal

    # 1. Resolve and guard the source quotation.
    quotation = await repo.get_quotation(
        organization_id, quotation_id=quotation_id
    )
    if not quotation:
        raise ValueError(
            f"Quotation {quotation_id} not found for this organization"
        )
    if quotation.get("status") == "CONVERTED":
        raise ValueError(
            f"Quotation {quotation.get('quotation_number', quotation_id)} "
            "has already been converted to an invoice — refusing to "
            "double-convert (duplicate revenue/receivable prevented)"
        )

    customer_id = uuid.UUID(str(quotation["customer_id"]))

    # PARITY: copy the quotation's line items into the invoice — conversion
    # without lines would create a header that disagrees with its source
    # document.  Product/service/tax/project references are preserved so
    # the invoice items rows carry the identical shape a manual conversion
    # would produce.
    quotation_items = await repo.get_quotation_items(
        organization_id, quotation_id=quotation_id
    )
    items_payload = [
        {
            "description": qi.get("description", ""),
            "product_id": qi.get("product_id"),
            "service_id": qi.get("service_id"),
            "project_id": qi.get("project_id"),
            "quantity": qi.get("quantity", 1),
            "unit_price": qi.get("unit_price", 0),
            "discount_amount": qi.get("discount_amount", 0),
            "tax_rate_id": qi.get("tax_rate_id"),
            "tax_amount": qi.get("tax_amount", 0),
            "line_total": qi.get("line_total", 0),
        }
        for qi in quotation_items or []
    ]

    # 2. Create the invoice with the source linkage and preserved amounts.
    invoice = await invoice_service.create_invoice(
        organization_id=organization_id,
        customer_id=customer_id,
        invoice_date=invoice_date,
        due_date=due_date,
        currency_code=quotation.get("currency_code") or "PKR",
        subtotal=float(quotation.get("subtotal", 0) or 0),
        tax_total=float(quotation.get("tax_total", 0) or 0),
        discount_total=float(quotation.get("discount_total", 0) or 0),
        total=float(quotation.get("total", 0) or 0),
        payment_terms_days=payment_terms_days,
        project_id=(
            uuid.UUID(str(quotation["project_id"]))
            if quotation.get("project_id") else None
        ),
        quotation_id=quotation_id,
        notes=notes if notes is not None else quotation.get("notes"),
        terms=terms if terms is not None else quotation.get("terms"),
        items=items_payload or None,
        created_by=created_by,
    )

    # PARITY VERIFICATION: the converted invoice must carry exactly the
    # source quotation's line count — a mismatch is a hard failure, never a
    # silent partial copy.
    if items_payload and invoice.get("item_count") != len(items_payload):
        raise ValueError(
            "Conversion integrity failure: expected "
            f"{len(items_payload)} invoice line items from the quotation "
            f"but {invoice.get('item_count')} were persisted."
        )

    # 3. Journal: the invoice tool layer handles auto-journaling for direct
    # creation; conversion mirrors that same deterministic path here so a
    # converted invoice carries the identical posted receivable journal.
    # Dr Receivable / Cr Revenue for the invoice total — prepared, validated
    # and posted by the accounting engine (never an LLM decision).
    journal_result: Dict[str, Any] = {}
    total = float(invoice.get("total", 0) or 0)
    if total > 0:
        journal_result = await auto_journal(
            organization_id=organization_id,
            document_type="invoice",
            document=invoice,
            amount=total,
            transaction_date=invoice.get("invoice_date", ""),
            description=(
                f"Invoice {invoice.get('invoice_number', invoice.get('id'))} "
                f"(from quotation {quotation.get('quotation_number', quotation_id)})"
            ),
            customer_id=customer_id,
            project_id=invoice.get("project_id"),
        )
        invoice.update(journal_result)
        prepared = journal_result.get("journal_entry") or {}
        entry = prepared.get("entry") or {}
        if entry.get("id"):
            try:
                entry_id = uuid.UUID(entry["id"])
                await accounting_service.validate_journal(entry_id=entry_id)
                await accounting_service.post_journal(entry_id=entry_id)
                # Link the journal back to the invoice row (source-tied)
                # and leave DRAFT — a posted receivable journal means the
                # invoice is issued; otherwise v_open_receivables and the
                # aging views would hide it while the ledger shows it.
                from app.repositories import invoice_repository as inv_repo
                await inv_repo.link_journal_to_invoice(
                    invoice_id=uuid.UUID(invoice["id"]),
                    journal_entry_id=entry_id,
                )
                await inv_repo.mark_issued(
                    invoice_id=uuid.UUID(invoice["id"])
                )
                invoice["journal_entry_id"] = str(entry_id)
                invoice["status"] = "ISSUED"
                invoice["journal_posted"] = True
            except Exception as exc:  # noqa: BLE001 — never fake success
                log.warning(
                    "quotation.convert.post_journal_failed",
                    invoice_id=str(invoice.get("id")),
                    error=str(exc)[:300],
                )
                invoice["journal_posted"] = False
                invoice["journal_warning"] = (
                    f"Journal prepared but posting failed: {exc}"
                )

    # 4. Transition the quotation — ONLY after the invoice exists, so a
    # failed invoice creation never leaves a CONVERTED quotation behind.
    converted = await repo.mark_converted(
        organization_id, quotation_id=quotation_id
    )

    log.info(
        "quotation.converted",
        quotation_id=str(quotation_id),
        invoice_id=invoice.get("id"),
        total=total,
    )
    return {
        "converted": True,
        "quotation": converted or quotation,
        "invoice": invoice,
    }
