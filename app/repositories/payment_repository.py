"""
Payment Repository — Supabase data access for payments and receipts.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, update_one


# ---- Receipts (customer payments INBOUND) --------------------------------

async def create_receipt(
    *,
    organization_id: uuid.UUID,
    receipt_date: str,
    customer_id: uuid.UUID,
    amount: float,
    payment_method: str = "BANK_TRANSFER",
    currency_code: str = "PKR",
    bank_account_id: Optional[uuid.UUID] = None,
    cash_account_id: Optional[uuid.UUID] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    journal_entry_id: Optional[uuid.UUID] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "receipt_date": receipt_date,
        "customer_id": str(customer_id),
        "amount": amount,
        "payment_method": payment_method,
        "currency_code": currency_code,
        "bank_account_id": str(bank_account_id) if bank_account_id else None,
        "cash_account_id": str(cash_account_id) if cash_account_id else None,
        "reference": reference,
        "notes": notes,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
        # DB contract (migration 013): receipts.status is payment_status
        # enum {PENDING, COMPLETED, CANCELLED, REVERSED} — "DRAFT" is NOT
        # a valid value and makes every receipt insert fail.  A receipt is
        # PENDING until its journal is posted (link_journal_to_receipt
        # then transitions it to COMPLETED).
        "status": "PENDING",
        "created_by": str(created_by) if created_by else None,
    }
    return await insert_one("receipts", data=data)


async def get_receipt(
    organization_id: uuid.UUID, *, receipt_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "receipts",
        filters={
            "id": str(receipt_id),
            "organization_id": str(organization_id),
        },
    )


async def list_receipts(
    organization_id: uuid.UUID,
    *,
    customer_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if customer_id:
        filters["customer_id"] = str(customer_id)
    return await fetch_many(
        "receipts", filters=filters, order="receipt_date.desc", limit=limit
    )


async def link_journal_to_receipt(
    *, receipt_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "receipts",
        row_id=receipt_id,
        data={"journal_entry_id": str(journal_entry_id), "status": "COMPLETED"},
    )


async def update_receipt_status(
    *, receipt_id: uuid.UUID, status: str
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "receipts", row_id=receipt_id, data={"status": status},
    )


# ---- Receipt Allocations ---------------------------------------------------

async def create_receipt_allocation(
    *,
    organization_id: uuid.UUID,
    receipt_id: uuid.UUID,
    invoice_id: Optional[uuid.UUID] = None,
    credit_note_id: Optional[uuid.UUID] = None,
    amount_allocated: float,
) -> Dict[str, Any]:
    """Allocate a receipt against an invoice or credit note."""
    return await insert_one(
        "receipt_allocations",
        data={
            "organization_id": str(organization_id),
            "receipt_id": str(receipt_id),
            "invoice_id": str(invoice_id) if invoice_id else None,
            "credit_note_id": str(credit_note_id) if credit_note_id else None,
            "amount_allocated": amount_allocated,
        },
    )


async def list_receipt_allocations(
    organization_id: uuid.UUID, *, receipt_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "receipt_allocations",
        filters={
            "organization_id": str(organization_id),
            "receipt_id": str(receipt_id),
        },
    )


# ---- Payments (supplier payments OUTFLOW) --------------------------------

async def create_payment(
    *,
    organization_id: uuid.UUID,
    payment_date: str,
    supplier_id: uuid.UUID,
    amount: float,
    # DB enum payment_direction = {INFLOW, OUTFLOW} — database is
    # authoritative (migration 034); never write INBOUND/OUTBOUND here.
    direction: str = "OUTFLOW",
    payment_method: str = "BANK_TRANSFER",
    currency_code: str = "PKR",
    bank_account_id: Optional[uuid.UUID] = None,
    cash_account_id: Optional[uuid.UUID] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    journal_entry_id: Optional[uuid.UUID] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "payment_date": payment_date,
        "supplier_id": str(supplier_id),
        "amount": amount,
        "direction": direction,
        "payment_method": payment_method,
        "currency_code": currency_code,
        "bank_account_id": str(bank_account_id) if bank_account_id else None,
        "cash_account_id": str(cash_account_id) if cash_account_id else None,
        "reference": reference,
        "notes": notes,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
        # DB contract (migration 013): payments.status is payment_status
        # enum {PENDING, COMPLETED, CANCELLED, REVERSED} — "DRAFT" is NOT
        # a valid value.  PENDING until the journal posts.
        "status": "PENDING",
        "created_by": str(created_by) if created_by else None,
    }
    return await insert_one("payments", data=data)


async def get_payment(
    organization_id: uuid.UUID, *, payment_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "payments",
        filters={
            "id": str(payment_id),
            "organization_id": str(organization_id),
        },
    )


async def list_payments(
    organization_id: uuid.UUID,
    *,
    supplier_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if supplier_id:
        filters["supplier_id"] = str(supplier_id)
    return await fetch_many(
        "payments", filters=filters, order="payment_date.desc", limit=limit
    )


async def link_journal_to_payment(
    *, payment_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "payments",
        row_id=payment_id,
        data={"journal_entry_id": str(journal_entry_id), "status": "COMPLETED"},
    )


async def update_payment_status(
    *, payment_id: uuid.UUID, status: str
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "payments", row_id=payment_id, data={"status": status},
    )


# ---- Payment Allocations ---------------------------------------------------

async def create_payment_allocation(
    *,
    organization_id: uuid.UUID,
    payment_id: uuid.UUID,
    bill_id: Optional[uuid.UUID] = None,
    expense_id: Optional[uuid.UUID] = None,
    amount_allocated: float,
) -> Dict[str, Any]:
    """Allocate a payment against a bill or expense."""
    return await insert_one(
        "payment_allocations",
        data={
            "organization_id": str(organization_id),
            "payment_id": str(payment_id),
            "bill_id": str(bill_id) if bill_id else None,
            "expense_id": str(expense_id) if expense_id else None,
            "amount_allocated": amount_allocated,
        },
    )


async def list_payment_allocations(
    organization_id: uuid.UUID, *, payment_id: uuid.UUID
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "payment_allocations",
        filters={
            "organization_id": str(organization_id),
            "payment_id": str(payment_id),
        },
    )
