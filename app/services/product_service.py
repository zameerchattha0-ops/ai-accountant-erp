"""
Product Service — business logic for the product catalog.

Follows the established service conventions (see supplier_service):
search-before-create, duplicate-name reuse with an explicit ``reused``
marker, and NO stock-quantity semantics (the database has no stock
ledger — ``is_stock_tracked`` is a catalog flag only).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import product_repository as repo

log = structlog.get_logger(__name__)


async def search(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await repo.search_products(organization_id, query=query, limit=limit)


async def get(
    organization_id: uuid.UUID, *, product_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_product(organization_id, product_id=product_id)


async def create(
    organization_id: uuid.UUID,
    *,
    name: str,
    product_code: Optional[str] = None,
    description: Optional[str] = None,
    unit: Optional[str] = None,
    is_stock_tracked: bool = False,
    unit_price: float = 0.0,
    cost_price: Optional[float] = None,
    revenue_account_id: Optional[uuid.UUID] = None,
    tax_rate_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create a catalog product after verifying it doesn't already exist."""
    if not name or not name.strip():
        raise ValueError("Product name is required.")
    if unit_price is None or float(unit_price) < 0:
        raise ValueError("Product unit price must be a non-negative number.")

    existing = await repo.search_products(
        organization_id, query=name.strip(), limit=5
    )
    for p in existing:
        if p.get("name", "").lower().strip() == name.lower().strip():
            log.warning(
                "product.duplicate_detected",
                existing_id=p["id"],
                name=p["name"],
            )
            # Explicit reuse marker: the agent's narrative MUST reflect
            # reuse (never "newly created").
            return {**p, "reused": True}

    return await repo.create_product(
        organization_id=organization_id,
        name=name.strip(),
        product_code=product_code,
        description=description,
        unit=unit,
        is_stock_tracked=bool(is_stock_tracked),
        unit_price=float(unit_price),
        cost_price=cost_price,
        revenue_account_id=revenue_account_id,
        tax_rate_id=tax_rate_id,
    )
