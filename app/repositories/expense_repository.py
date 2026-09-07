"""
Expense Repository — Supabase data access for expense records.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, update_one


async def get_expense(
    organization_id: uuid.UUID, *, expense_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "expenses",
        filters={
            "id": str(expense_id),
            "organization_id": str(organization_id),
        },
    )


async def list_expenses(
    organization_id: uuid.UUID,
    *,
    supplier_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if supplier_id:
        filters["supplier_id"] = str(supplier_id)
    return await fetch_many(
        "expenses", filters=filters, order="expense_date.desc", limit=limit
    )


async def create_expense(
    *,
    organization_id: uuid.UUID,
    expense_date: str,
    payee_name: str,
    description: str,
    subtotal: float,
    currency_code: str = "PKR",
    tax_total: float = 0.0,
    total: Optional[float] = None,
    supplier_id: Optional[uuid.UUID] = None,
    category_id: Optional[uuid.UUID] = None,
    payment_mode: str = "CASH",
    journal_entry_id: Optional[uuid.UUID] = None,
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    computed_total = total if total is not None else subtotal + tax_total
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "expense_date": expense_date,
        "payee_name": payee_name,
        "description": description,
        "subtotal": subtotal,
        "tax_total": tax_total,
        "total": computed_total,
        "currency_code": currency_code,
        "supplier_id": str(supplier_id) if supplier_id else None,
        "category_id": str(category_id) if category_id else None,
        "payment_mode": payment_mode,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
        "status": "DRAFT",
        "created_by": str(created_by) if created_by else None,
    }
    return await insert_one("expenses", data=data)


async def link_journal_to_expense(
    *, expense_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await update_one(
        "expenses",
        row_id=expense_id,
        data={"journal_entry_id": str(journal_entry_id)},
    )
