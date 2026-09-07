"""
Invoice Repository — Supabase data access for sales invoices.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, update_one


async def get_invoice(
    organization_id: uuid.UUID, *, invoice_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "invoices",
        filters={
            "id": str(invoice_id),
            "organization_id": str(organization_id),
        },
    )


async def get_invoice_by_number(
    organization_id: uuid.UUID, *, invoice_number: str
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "invoices",
        filters={
            "invoice_number": invoice_number,
            "organization_id": str(organization_id),
        },
    )


async def list_invoices(
    organization_id: uuid.UUID,
    *,
    customer_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if customer_id:
        filters["customer_id"] = str(customer_id)
    if status:
        filters["status"] = status
    return await fetch_many(
        "invoices", filters=filters, order="invoice_date.desc", limit=limit
    )


async def create_invoice(
    *,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    invoice_date: str,
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
    journal_entry_id: Optional[uuid.UUID] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "customer_id": str(customer_id),
        "invoice_date": invoice_date,
        "due_date": due_date,
        "currency_code": currency_code,
        "subtotal": subtotal,
        "tax_total": tax_total,
        "discount_total": discount_total,
        "total": total,
        "amount_paid": 0.0,
        # payment_terms_days is NOT NULL (DB default 30) — omit when not
        # provided so the database default applies; an explicit None would
        # violate the constraint.
        **({"payment_terms_days": payment_terms_days}
           if payment_terms_days is not None else {}),
        "project_id": str(project_id) if project_id else None,
        # Source linkage back to the originating quotation (Phase 4:
        # quotation → invoice conversion traceability).  The FK
        # invoices.quotation_id exists in the DB contract.
        "quotation_id": str(quotation_id) if quotation_id else None,
        "notes": notes,
        "terms": terms,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
        "status": "DRAFT",
        "created_by": str(created_by) if created_by else None,
    }
    return await insert_one("invoices", data=data)


async def link_journal_to_invoice(
    *, invoice_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "invoices",
        row_id=invoice_id,
        data={"journal_entry_id": str(journal_entry_id)},
    )
async def link_journal_to_invoice(
    *, invoice_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "invoices",
        row_id=invoice_id,
        data={"journal_entry_id": str(journal_entry_id)},
    )


async def mark_issued(
    *, invoice_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Transition DRAFT → ISSUED and stamp sent_at.

    A recorded invoice is a real receivable event: once its journal is
    posted the invoice must leave DRAFT so receivables/aging views
    (which filter on ISSUED/PARTIALLY_PAID/OVERDUE) reflect it.
    """
    return await update_one(
        "invoices",
        row_id=invoice_id,
        data={
            "status": "ISSUED",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        },
    )
