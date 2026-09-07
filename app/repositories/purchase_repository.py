"""
Purchase Repository — Supabase data access for purchase bills.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, update_one


async def get_purchase_bill(
    organization_id: uuid.UUID, *, bill_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "purchase_bills",
        filters={
            "id": str(bill_id),
            "organization_id": str(organization_id),
        },
    )


async def list_purchase_bills(
    organization_id: uuid.UUID,
    *,
    supplier_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if supplier_id:
        filters["supplier_id"] = str(supplier_id)
    if status:
        filters["status"] = status
    return await fetch_many(
        "purchase_bills", filters=filters, order="bill_date.desc", limit=limit
    )


async def create_purchase_bill(
    *,
    organization_id: uuid.UUID,
    supplier_id: uuid.UUID,
    bill_date: str,
    due_date: Optional[str] = None,
    currency_code: str = "PKR",
    subtotal: float = 0.0,
    tax_total: float = 0.0,
    discount_total: float = 0.0,
    total: float = 0.0,
    payment_terms_days: Optional[int] = None,
    supplier_invoice_ref: Optional[str] = None,
    notes: Optional[str] = None,
    journal_entry_id: Optional[uuid.UUID] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "supplier_id": str(supplier_id),
        "bill_date": bill_date,
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
        "supplier_invoice_ref": supplier_invoice_ref,
        "notes": notes,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
        "status": "DRAFT",
        "created_by": str(created_by) if created_by else None,
    }
    return await insert_one("purchase_bills", data=data)


async def link_journal_to_bill(
    *, bill_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "purchase_bills",
        row_id=bill_id,
        data={"journal_entry_id": str(journal_entry_id)},
    )


async def add_purchase_bill_items(
    organization_id: uuid.UUID,
    *,
    bill_id: uuid.UUID,
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert multiple line items for a purchase bill.

    PARITY with ``invoice_item_repository.add_invoice_items`` — the same
    normalized line shape (from ``item_validation.validate_document_items``)
    mapped onto the ``purchase_bill_items`` columns (DB contract, migration
    010): expense_account_id / fixed_asset_id replace the revenue side.
    """
    created = []
    for idx, item in enumerate(items, start=1):
        row = await insert_one(
            "purchase_bill_items",
            data={
                "organization_id": str(organization_id),
                "bill_id": str(bill_id),
                "line_number": idx,
                "description": item.get("description", ""),
                "product_id": item.get("product_id"),
                "expense_account_id": item.get("expense_account_id"),
                "project_id": item.get("project_id"),
                "fixed_asset_id": item.get("fixed_asset_id"),
                "quantity": float(item.get("quantity", 1)),
                "unit_price": float(item.get("unit_price", 0)),
                "discount_amount": float(item.get("discount_amount", 0)),
                "tax_rate_id": item.get("tax_rate_id"),
                "tax_amount": float(item.get("tax_amount", 0)),
                "line_total": float(item.get("line_total", 0)),
            },
        )
        created.append(row)
    return created
