"""
Purchase Return Service — business logic for purchase returns.
Returns reduce a supplier's payable balance.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import purchase_return_repository as repo
from app.repositories import supplier_repository as supplier_repo

log = structlog.get_logger(__name__)


async def create_purchase_return(
    organization_id: uuid.UUID,
    *,
    supplier_id: Optional[str] = None,
    supplier_name: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    bill_id: Optional[str] = None,
    reason: Optional[str] = None,
    **kw,
) -> Dict[str, Any]:
    """Create a purchase return with validation."""
    if not items:
        raise ValueError("Purchase return requires at least one line item.")
    if not reason:
        raise ValueError("Purchase return requires a reason.")

    # Resolve supplier
    resolved_supplier = None
    if supplier_id:
        resolved_supplier = await supplier_repo.get_supplier(
            organization_id, supplier_id=uuid.UUID(supplier_id)
        )
    if not resolved_supplier and supplier_name:
        results = await supplier_repo.search_suppliers(
            organization_id, query=supplier_name, limit=5
        )
        for s in results:
            if s.get("name", "").lower().strip() == supplier_name.lower().strip():
                resolved_supplier = s
                break
    if not resolved_supplier:
        raise ValueError(f"Supplier not found: {supplier_name or supplier_id}")

    purchase_return = await repo.create_purchase_return(
        organization_id=organization_id,
        supplier_id=uuid.UUID(resolved_supplier["id"]),
        items=items,
        bill_id=uuid.UUID(bill_id) if bill_id else None,
        reason=reason,
        **kw,
    )
    log.info("purchase_return.created", return_id=purchase_return["id"], total=purchase_return["total"])
    return purchase_return
