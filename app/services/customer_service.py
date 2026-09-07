"""
Customer Service — business logic for customer operations.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import customer_repository as repo

log = structlog.get_logger(__name__)


async def search(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await repo.search_customers(organization_id, query=query, limit=limit)


async def get(
    organization_id: uuid.UUID, *, customer_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_customer(organization_id, customer_id=customer_id)


async def create(
    organization_id: uuid.UUID,
    *,
    name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    legal_name: Optional[str] = None,
    tax_number: Optional[str] = None,
    currency_code: str = "PKR",
    payment_terms_days: int = 30,
    credit_limit: Optional[float] = None,
    receivable_account_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a customer after verifying it doesn't already exist."""
    # Search for duplicates first
    existing = await repo.search_customers(organization_id, query=name, limit=5)
    for c in existing:
        if c.get("name", "").lower().strip() == name.lower().strip():
            log.warning(
                "customer.duplicate_detected",
                existing_id=c["id"],
                name=c["name"],
            )
            # Return the existing customer instead of creating a duplicate.
            # Explicit reuse marker: the agent's narrative MUST reflect
            # reuse (never "newly created").
            return {**c, "reused": True}

    return await repo.create_customer(
        organization_id=organization_id,
        name=name,
        email=email,
        phone=phone,
        legal_name=legal_name,
        tax_number=tax_number,
        currency_code=currency_code,
        payment_terms_days=payment_terms_days,
        credit_limit=credit_limit,
        receivable_account_id=receivable_account_id,
        notes=notes,
    )


async def get_ledger(
    organization_id: uuid.UUID,
    *,
    customer_id: uuid.UUID,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await repo.get_customer_ledger(
        organization_id, customer_id=customer_id, limit=limit
    )


async def get_open_receivables(
    organization_id: uuid.UUID,
    *,
    customer_id: uuid.UUID,
) -> List[Dict[str, Any]]:
    return await repo.get_open_receivables(organization_id, customer_id=customer_id)
