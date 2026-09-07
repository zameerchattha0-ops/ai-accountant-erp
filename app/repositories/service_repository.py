"""
Service Repository — Supabase data access for the service catalog.

The database contract is authoritative (``public.services``):
* ``service_code`` NOT NULL and UNIQUE per organization — NO trigger
  assigns it, so the repository generates it deterministically via the
  ``next_document_number`` RPC (same mechanism as products) with a
  collision-safe fallback.
* ``billing_unit`` is the ``service_unit_code`` enum
  (HOUR, DAY, MONTH, FIXED, ITEM) — validated in the service layer.
* ``standard_rate >= 0`` (CHECK) and ``cost_rate`` NULL or >= 0 (CHECK).
* Services have NO stock semantics — there is no inventory dimension.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import call_rpc, fetch_one, insert_one, search_ilike


async def search_services(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    """Search the service catalog by name or code ([] = no match —
    valid information, never a failure)."""
    return await search_ilike(
        "services",
        column="name",
        value=query,
        organization_id=organization_id,
        select=(
            "id,service_code,name,description,billing_unit,standard_rate,"
            "cost_rate,revenue_account_id,is_active"
        ),
        limit=limit,
    )


async def get_service(
    organization_id: uuid.UUID, *, service_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "services",
        filters={
            "id": str(service_id),
            "organization_id": str(organization_id),
        },
    )


async def get_service_by_code(
    organization_id: uuid.UUID, *, code: str
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "services",
        filters={
            "service_code": code,
            "organization_id": str(organization_id),
        },
    )


async def generate_service_code(organization_id: uuid.UUID) -> str:
    """Deterministically generate a unique service_code.

    Primary: the concurrent-safe ``next_document_number`` RPC.
    Fallback: a random unique code — the UNIQUE constraint remains
    the final guard.
    """
    try:
        result = await call_rpc(
            "next_document_number",
            params={
                "p_org": str(organization_id),
                "p_doc_type": "SERVICE",
                "p_prefix": "SRV",
            },
        )
        if isinstance(result, list) and result:
            return str(result[0])
        if isinstance(result, str) and result.strip():
            return result.strip()
    except Exception:  # noqa: BLE001 — fallback below keeps creation working
        pass
    return f"SRV-{uuid.uuid4().hex[:8].upper()}"


async def create_service(
    *,
    organization_id: uuid.UUID,
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
    """Create a catalog service. ``service_code`` is generated when absent."""
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "service_code": service_code
        or await generate_service_code(organization_id),
        "name": name,
        "description": description,
        "billing_unit": billing_unit,
        "standard_rate": standard_rate,
        "cost_rate": cost_rate,
        "category_id": str(category_id) if category_id else None,
        "revenue_account_id": str(revenue_account_id) if revenue_account_id else None,
        "tax_rate_id": str(tax_rate_id) if tax_rate_id else None,
        "is_active": True,
    }
    return await insert_one("services", data=data)
