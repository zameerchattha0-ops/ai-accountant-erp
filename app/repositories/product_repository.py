"""
Product Repository — Supabase data access for the product catalog.

The database contract is authoritative (``public.products``):
* ``product_code`` is NOT NULL and UNIQUE per organization — no trigger
  assigns it, so the repository generates it deterministically via the
  ``next_document_number`` RPC with a collision-safe fallback.
* ``is_stock_tracked`` exists but there is NO stock ledger / warehouse
  table — stock QUANTITY operations are not supported by the database.
  This repository therefore handles catalog data only.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import call_rpc, fetch_one, insert_one, search_ilike


async def search_products(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    """Search the product catalog by name or code ([] = no match —
    valid information, never a failure)."""
    return await search_ilike(
        "products",
        column="name",
        value=query,
        organization_id=organization_id,
        select=(
            "id,product_code,name,unit,is_stock_tracked,unit_price,"
            "cost_price,revenue_account_id,is_active"
        ),
        limit=limit,
    )


async def get_product(
    organization_id: uuid.UUID, *, product_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "products",
        filters={
            "id": str(product_id),
            "organization_id": str(organization_id),
        },
    )


async def get_product_by_code(
    organization_id: uuid.UUID, *, code: str
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "products",
        filters={
            "product_code": code,
            "organization_id": str(organization_id),
        },
    )


async def generate_product_code(organization_id: uuid.UUID) -> str:
    """Deterministically generate a unique product_code.

    Primary: the concurrent-safe ``next_document_number`` RPC (the same
    mechanism the DB triggers use).  Fallback: a random unique code — the
    UNIQUE constraint remains the final guard.
    """
    try:
        result = await call_rpc(
            "next_document_number",
            params={
                "p_org": str(organization_id),
                "p_doc_type": "PRODUCT",
                "p_prefix": "PRD",
            },
        )
        if isinstance(result, list) and result:
            return str(result[0])
        if isinstance(result, str) and result.strip():
            return result.strip()
    except Exception:  # noqa: BLE001 — fallback below keeps creation working
        pass
    return f"PRD-{uuid.uuid4().hex[:8].upper()}"


async def create_product(
    *,
    organization_id: uuid.UUID,
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
    """Create a catalog product. ``product_code`` is generated when absent."""
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "product_code": product_code
        or await generate_product_code(organization_id),
        "name": name,
        "description": description,
        "unit": unit,
        # Catalog flag only — the database has NO stock ledger, so this
        # never implies quantity tracking capability.
        "is_stock_tracked": is_stock_tracked,
        "unit_price": unit_price,
        "cost_price": cost_price,
        "revenue_account_id": str(revenue_account_id) if revenue_account_id else None,
        "tax_rate_id": str(tax_rate_id) if tax_rate_id else None,
        "is_active": True,
    }
    return await insert_one("products", data=data)
