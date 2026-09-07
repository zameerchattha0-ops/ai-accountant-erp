"""
Supplier Service — business logic for supplier operations.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import supplier_repository as repo

log = structlog.get_logger(__name__)


async def search(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await repo.search_suppliers(organization_id, query=query, limit=limit)


async def get(
    organization_id: uuid.UUID, *, supplier_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_supplier(organization_id, supplier_id=supplier_id)


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
    payable_account_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a supplier after verifying it doesn't already exist."""
    existing = await repo.search_suppliers(organization_id, query=name, limit=5)
    for s in existing:
        if s.get("name", "").lower().strip() == name.lower().strip():
            log.warning(
                "supplier.duplicate_detected",
                existing_id=s["id"],
                name=s["name"],
            )
            # Explicit reuse marker: the agent's narrative MUST reflect
            # reuse (never "newly created") — the tool result is the
            # authoritative record of what happened.
            return {**s, "reused": True}

    return await repo.create_supplier(
        organization_id=organization_id,
        name=name,
        email=email,
        phone=phone,
        legal_name=legal_name,
        tax_number=tax_number,
        currency_code=currency_code,
        payment_terms_days=payment_terms_days,
        credit_limit=credit_limit,
        payable_account_id=payable_account_id,
        notes=notes,
    )


async def get_ledger(
    organization_id: uuid.UUID,
    *,
    supplier_id: uuid.UUID,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await repo.get_supplier_ledger(
        organization_id, supplier_id=supplier_id, limit=limit
    )


async def get_open_payables(
    organization_id: uuid.UUID,
    *,
    supplier_id: uuid.UUID,
) -> List[Dict[str, Any]]:
    return await repo.get_open_payables(organization_id, supplier_id=supplier_id)
