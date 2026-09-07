"""
Service Service — business logic for the service catalog.

Follows the established entity conventions (supplier_service /
product_service): search-before-create, exact-name reuse with an
explicit ``reused`` marker, and NO inventory semantics — a service is
never stock, never a fixed asset, regardless of price.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import service_repository as repo

log = structlog.get_logger(__name__)

# Authoritative DB enum: service_unit_code
BILLING_UNITS = ("HOUR", "DAY", "MONTH", "FIXED", "ITEM")


async def search(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await repo.search_services(organization_id, query=query, limit=limit)


async def get(
    organization_id: uuid.UUID, *, service_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_service(organization_id, service_id=service_id)


async def create(
    organization_id: uuid.UUID,
    *,
    name: str,
    service_code: Optional[str] = None,
    description: Optional[str] = None,
    billing_unit: str = "HOUR",
    standard_rate: float = 0.0,
    cost_rate: Optional[float] = None,
    category_id: Optional[uuid.UUID] = None,
    revenue_account_id: Optional[uuid.UUID] = None,
    tax_rate_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create a catalog service after verifying it doesn't already exist."""
    if not name or not name.strip():
        raise ValueError("Service name is required.")
    if billing_unit not in BILLING_UNITS:
        raise ValueError(
            f"billing_unit must be one of {', '.join(BILLING_UNITS)} "
            f"(got {billing_unit})."
        )
    if standard_rate is None or float(standard_rate) < 0:
        raise ValueError("Service standard rate must be a non-negative number.")
    if cost_rate is not None and float(cost_rate) < 0:
        raise ValueError("Service cost rate must be a non-negative number.")

    existing = await repo.search_services(
        organization_id, query=name.strip(), limit=5
    )
    for s in existing:
        if s.get("name", "").lower().strip() == name.lower().strip():
            log.warning(
                "service.duplicate_detected",
                existing_id=s["id"],
                name=s["name"],
            )
            # Explicit reuse marker: the agent's narrative MUST reflect
            # reuse (never "newly created").
            return {**s, "reused": True}

    return await repo.create_service(
        organization_id=organization_id,
        name=name.strip(),
        service_code=service_code,
        description=description,
        billing_unit=billing_unit,
        standard_rate=float(standard_rate),
        cost_rate=cost_rate,
        category_id=category_id,
        revenue_account_id=revenue_account_id,
        tax_rate_id=tax_rate_id,
    )
