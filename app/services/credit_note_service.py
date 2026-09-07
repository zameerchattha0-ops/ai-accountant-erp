"""
Credit Note Service — business logic for credit note creation.
Credit notes reduce a customer's receivable balance.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import credit_note_repository as repo
from app.repositories import customer_repository as customer_repo

log = structlog.get_logger(__name__)


async def create_credit_note(
    organization_id: uuid.UUID,
    *,
    customer_id: Optional[str] = None,
    customer_name: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    invoice_id: Optional[str] = None,
    reason: Optional[str] = None,
    **kw,
) -> Dict[str, Any]:
    """Create a credit note with validation."""
    if not items:
        raise ValueError("Credit note requires at least one line item.")
    if not reason:
        raise ValueError("Credit note requires a reason.")

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
        raise ValueError(f"Customer not found: {customer_name or customer_id}")

    credit_note = await repo.create_credit_note(
        organization_id=organization_id,
        customer_id=uuid.UUID(resolved_customer["id"]),
        items=items,
        invoice_id=uuid.UUID(invoice_id) if invoice_id else None,
        reason=reason,
        **kw,
    )
    log.info("credit_note.created", credit_note_id=credit_note["id"], total=credit_note["total"])
    return credit_note
