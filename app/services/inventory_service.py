"""
Inventory Service — the PERPETUAL stock ledger.

Every inventory purchase adds a RECEIPT movement (quantity + purchase unit
cost); every sale of stock-tracked goods adds an ISSUE movement carrying the
weighted-average cost the accounting engine used for its Cost-of-Sales
journal — the ledger and the journal can therefore never disagree about the
cost of an issue.

Contracts (deliberately strict — a stock ledger that silently drifts is
worse than no ledger at all):

* ``receive_stock``   — purchases only.  Adds quantity at the given unit cost.
* ``issue_stock``     — sales only.  REFUSES (ValueError) when the product
                        has insufficient stock: an oversold issue would
                        understate inventory and fabricate Cost of Sales.
                        The caller surfaces the refusal as an honest
                        warning (the sale itself is never blocked — the
                        revenue entry stands, the COGS entry is skipped).
* ``stock_position``  — read-time derivation from ``v_product_stock``; a
                        lookup failure returns None (fail-open for callers
                        that only need a best-effort cost).

No aggregate is ever cached on ``products``: quantity/value are derived
from the movement rows at read time (migration 091), so a journal reversal
or manual correction can never leave a stale counter behind.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.database import fetch_many, insert_one

log = structlog.get_logger(__name__)


async def receive_stock(
    organization_id: uuid.UUID,
    *,
    product_id: uuid.UUID,
    quantity: float,
    unit_cost: float,
    source_type: Optional[str] = None,
    source_id: Optional[uuid.UUID] = None,
    movement_date: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a stock RECEIPT (purchase).  Raises on invalid input."""
    if float(quantity) <= 0:
        raise ValueError("Stock receipt quantity must be greater than 0.")
    if float(unit_cost) < 0:
        raise ValueError("Stock receipt unit cost cannot be negative.")
    movement = await insert_one(
        "inventory_movements",
        data={
            "organization_id": str(organization_id),
            "product_id": str(product_id),
            "direction": "RECEIPT",
            "quantity": float(quantity),
            "unit_cost": float(unit_cost),
            "source_type": source_type,
            "source_id": str(source_id) if source_id else None,
            "movement_date": movement_date,
            "description": description,
        },
    )
    log.info(
        "inventory.received",
        product_id=str(product_id),
        quantity=float(quantity),
        unit_cost=float(unit_cost),
        source_type=source_type,
    )
    return movement



async def issue_stock(
    organization_id: uuid.UUID,
    *,
    product_id: uuid.UUID,
    quantity: float,
    source_type: Optional[str] = None,
    source_id: Optional[uuid.UUID] = None,
    movement_date: Optional[str] = None,
    description: Optional[str] = None,
    unit_cost: Optional[float] = None,
) -> Dict[str, Any]:
    """Record a stock ISSUE (sale) at weighted-average cost.

    ``unit_cost`` may be supplied by the caller when the accounting engine
    already computed the cost for its Cost-of-Sales journal — the movement
    then records EXACTLY the figure the journal used.  When omitted the
    weighted-average cost is read from ``v_product_stock``.

    Raises ``ValueError`` when stock is insufficient OR when no cost can be
    determined (an issue valued at zero would fabricate profit).
    """
    qty = float(quantity)
    if qty <= 0:
        raise ValueError("Stock issue quantity must be greater than 0.")

    resolved_cost = unit_cost
    if resolved_cost is None:
        position = await stock_position(organization_id, product_id=product_id)
        if position is None:
            raise ValueError(
                "Stock position is unavailable — the issue cannot be valued."
            )
        resolved_cost = float(position.get("average_cost") or 0)
    resolved_cost = float(resolved_cost)
    if resolved_cost < 0:
        raise ValueError("Stock issue unit cost cannot be negative.")

    # Insufficient-stock guard: read the CURRENT quantity first so an
    # oversold issue is refused instead of silently driving stock negative.
    position = await stock_position(organization_id, product_id=product_id)
    on_hand = float((position or {}).get("quantity_on_hand") or 0)
    if position is not None and on_hand < qty - 1e-9:
        raise ValueError(
            f"Insufficient stock: {on_hand:g} on hand, {qty:g} requested. "
            "The Cost-of-Sales entry was NOT recorded — record the missing "
            "purchase (or a stock adjustment) first."
        )
    if position is not None and resolved_cost == 0 and on_hand > 0:
        raise ValueError(
            "The stock ledger has no unit cost for this product — the "
            "Cost-of-Sales entry cannot be valued. Set the product's cost "
            "price or record the purchase that seeded the stock."
        )

    movement = await insert_one(
        "inventory_movements",
        data={
            "organization_id": str(organization_id),
            "product_id": str(product_id),
            "direction": "ISSUE",
            "quantity": qty,
            "unit_cost": resolved_cost,
            "source_type": source_type,
            "source_id": str(source_id) if source_id else None,
            "movement_date": movement_date,
            "description": description,
        },
    )
    log.info(
        "inventory.issued",
        product_id=str(product_id),
        quantity=qty,
        unit_cost=resolved_cost,
        source_type=source_type,
    )
    return movement


async def stock_position(
    organization_id: uuid.UUID, *, product_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Current quantity / value / average cost — derived, never cached.

    Returns None when the ledger view is unreadable (migration not applied
    yet, network failure): callers treat None as "cannot value" and warn,
    never as "stock is zero".
    """
    try:
        rows = await fetch_many(
            "v_product_stock",
            filters={
                "organization_id": str(organization_id),
                "product_id": str(product_id),
            },
            limit=1,
        )
    except Exception as exc:  # noqa: BLE001 — fail open, same as chart reads
        log.warning(
            "inventory.position_lookup_failed",
            product_id=str(product_id),
            error=str(exc)[:200],
        )
        return None
    return rows[0] if rows else None


async def positions_for_products(
    organization_id: uuid.UUID, *, product_ids: List[uuid.UUID]
) -> Dict[str, Dict[str, Any]]:
    """One read for many products (the sale path values several lines)."""
    wanted = {str(p) for p in product_ids}
    if not wanted:
        return {}
    try:
        rows = await fetch_many(
            "v_product_stock",
            filters={"organization_id": str(organization_id)},
            limit=1000,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "inventory.positions_lookup_failed", error=str(exc)[:200]
        )
        return {}
    return {
        str(r.get("product_id")): r
        for r in rows
        if str(r.get("product_id")) in wanted
    }


# ---------------------------------------------------------------------------
# Catalogue synchronisation — the purchase must create/find the product,
# assign its SKU (product_code), inventory category and valuation cost in
# the SAME call that records the stock movement.
# ---------------------------------------------------------------------------

_INVENTORY_CATEGORY_NAME = "Inventory"


async def ensure_inventory_category(
    organization_id: uuid.UUID,
) -> Optional[uuid.UUID]:
    """Find-or-create the "Inventory" product category (fail-soft).

    A category failure must never block a purchase: the product is still
    created (category_id None) and the stock movement still records — only
    the catalogue grouping is missing, which the user can fix later.
    """
    from app.database import fetch_one

    try:
        existing = await fetch_one(
            "product_categories",
            filters={
                "organization_id": str(organization_id),
                "name": _INVENTORY_CATEGORY_NAME,
            },
        )
        if existing:
            return uuid.UUID(str(existing["id"]))
        created = await insert_one(
            "product_categories",
            data={
                "organization_id": str(organization_id),
                "name": _INVENTORY_CATEGORY_NAME,
            },
        )
        return uuid.UUID(str(created["id"]))
    except Exception as exc:  # noqa: BLE001 — fail soft, never block a sale
        log.warning(
            "inventory.category_lookup_failed", error=str(exc)[:200]
        )
        return None


async def find_or_create_catalogue_product(
    organization_id: uuid.UUID,
    *,
    name: str,
    quantity: float,
    unit_cost: float,
) -> Optional[Dict[str, Any]]:
    """Find-or-create the catalogue product for a purchased stock line.

    * exact (case-insensitive) name match -> REUSE (never a duplicate row);
    * else WORD-LEVEL match (user rule 2026-10-18) -> REUSE: 'office chair'
      must find 'chairs'.  The exact-only check created the live duplicate
      'Office Chair' PRD-000004 next to 'chairs' PRD-000002 and credited
      the stock receipt to the wrong item;
    * otherwise create with ``is_stock_tracked=True``, the SKU generated by
      the product repository, the Inventory category and ``cost_price`` set
      to the purchase unit cost (the first cost the perpetual ledger sees).

    Reused rows carry ``reused=True`` so the caller's catalogue note is
    honest ("Reused ..." vs "Created ...").

    Returns the product row, or None when the catalogue write failed — the
    caller records an honest warning; the purchase itself must not fail
    because the catalogue is down.
    """
    from app.services import product_service

    term = str(name or "").strip()
    if not term:
        return None
    try:
        rows = await product_service.search(
            organization_id, query=term, limit=10
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "inventory.product_search_failed", name=term, error=str(exc)[:200]
        )
        rows = []
    for row in rows or ():
        if str(row.get("name") or "").strip().lower() == term.lower():
            return {**row, "reused": True}

    # LLM CATALOGUE ANALYST (2026-10-20): "is this the SAME product as an
    # existing entry?" is a semantic judgment, so the model decides reuse-vs-
    # distinct over the FETCHED candidates.  Python only grounds the answer
    # (a 1-based index into this list) and keeps the exact-name floor.  The
    # purchase side fetches the WHOLE catalogue (not a prefix search) so the
    # analyst sees every plausible candidate, not just token-overlapping ones.
    try:
        from app.database import fetch_many as _fetch_many
        from app.catalogue_matching import llm_match_catalogue_item

        catalogue = await _fetch_many(
            "products",
            filters={"organization_id": str(organization_id)},
            select="id,name,product_code,is_stock_tracked,cost_price",
            limit=200,
        )
        match = await llm_match_catalogue_item(term, catalogue)
        if match and match.get("id"):
            log.info(
                "inventory.product_reused_by_llm_match",
                name=term,
                matched=str(match.get("name")),
                product_code=match.get("product_code"),
            )
            return {**match, "reused": True}
    except Exception as exc:  # noqa: BLE001 — fall through to create
        log.warning(
            "inventory.llm_match_failed", name=term, error=str(exc)[:200]
        )

    category_id = await ensure_inventory_category(organization_id)
    try:
        return await product_service.create(
            organization_id,
            name=term,
            is_stock_tracked=True,
            unit_price=float(unit_cost),
            cost_price=float(unit_cost),
            category_id=category_id,
        )
    except Exception as exc:  # noqa: BLE001 — fail soft with a warning
        log.warning(
            "inventory.product_create_failed", name=term, error=str(exc)[:200]
        )
        return None




async def get_product_unit_tracing(
    organization_id: uuid.UUID,
    *,
    product_id: Optional[uuid.UUID] = None,
    fiscal_year_start: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Calculate the unit tracing breakdown for products:
    Closing Stock (t0) = Opening Stock + Purchased (Inward) - Sold (Outward).
    """
    filters: Dict[str, Any] = {"organization_id": str(organization_id)}
    if product_id:
        filters["product_id"] = str(product_id)

    movements = await fetch_many(
        "inventory_movements",
        filters=filters,
        order="created_at.asc",
        limit=5000,
    )

    results: Dict[str, Dict[str, Any]] = {}
    for m in movements:
        pid = str(m.get("product_id"))
        if pid not in results:
            results[pid] = {
                "opening_quantity": 0.0,
                "purchased_quantity": 0.0,
                "sold_quantity": 0.0,
                "closing_quantity": 0.0,
                "total_cost": 0.0,
                "average_cost": 0.0,
                "valuation": 0.0,
            }
        direction = str(m.get("direction") or "").upper()
        source_type = str(m.get("source_type") or "").lower()
        qty = float(m.get("quantity") or 0.0)
        unit_cost = float(m.get("unit_cost") or 0.0)
        m_date = str(m.get("movement_date") or "")

        is_opening = source_type in ("opening_stock", "opening") or (
            fiscal_year_start and m_date and m_date < fiscal_year_start
        )

        if is_opening:
            results[pid]["opening_quantity"] += qty
            results[pid]["total_cost"] += (qty * unit_cost)
        elif direction == "RECEIPT":
            results[pid]["purchased_quantity"] += qty
            results[pid]["total_cost"] += (qty * unit_cost)
        elif direction == "ISSUE":
            results[pid]["sold_quantity"] += qty

    for pid, data in results.items():
        data["closing_quantity"] = (
            data["opening_quantity"] + data["purchased_quantity"] - data["sold_quantity"]
        )
        total_inward = data["opening_quantity"] + data["purchased_quantity"]
        if total_inward > 0 and data["total_cost"] > 0:
            data["average_cost"] = data["total_cost"] / total_inward
        else:
            data["average_cost"] = 0.0
        data["valuation"] = max(0.0, data["closing_quantity"]) * data["average_cost"]

    return results


async def get_product_movements(
    organization_id: uuid.UUID,
    *,
    product_id: uuid.UUID,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return chronological stock movements for product tracing."""
    return await fetch_many(
        "inventory_movements",
        filters={
            "organization_id": str(organization_id),
            "product_id": str(product_id),
        },
        order="created_at.desc",
        limit=limit,
    )


async def get_all_inventory_movements(
    organization_id: uuid.UUID,
    *,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Return all chronological stock movements across products for global tracing."""
    movements = await fetch_many(
        "inventory_movements",
        filters={"organization_id": str(organization_id)},
        order="created_at.desc",
        limit=limit,
    )
    if not movements:
        return []
    pids = list({str(m.get("product_id")) for m in movements if m.get("product_id")})
    products_map = {}
    if pids:
        from app.database import fetch_many as _fetch_many
        p_rows = await _fetch_many(
            "products",
            filters={"organization_id": str(organization_id)},
            select="id,name,product_code,unit",
            limit=500,
        )
        products_map = {str(p["id"]): p for p in p_rows}

    for m in movements:
        p_info = products_map.get(str(m.get("product_id")), {})
        m["product_name"] = p_info.get("name") or "—"
        m["sku"] = p_info.get("product_code") or "—"
        m["product_code"] = p_info.get("product_code") or "—"
        m["unit"] = p_info.get("unit") or "—"
        m["valuation"] = float(m.get("value") or (float(m.get("quantity") or 0.0) * float(m.get("unit_cost") or 0.0)))
    return movements


async def get_inventory_status_summary(
    organization_id: uuid.UUID,
    *,
    product_name: Optional[str] = None,
    only_low_stock: bool = False,
) -> Dict[str, Any]:
    """Summary of stock positions, units received/issued, and valuation."""
    from app.services import product_service
    rows = await product_service.list_catalog(organization_id, status="ALL")
    tracing_map = await get_product_unit_tracing(organization_id)

    total_val = 0.0
    total_on_hand = 0.0
    total_received = 0.0
    total_issued = 0.0
    tracked_items = []

    for r in rows:
        if not r.get("is_stock_tracked"):
            continue
        pid = str(r.get("id"))
        tr = tracing_map.get(pid, {
            "opening_quantity": 0.0,
            "purchased_quantity": 0.0,
            "sold_quantity": 0.0,
            "closing_quantity": 0.0,
            "average_cost": float(r.get("cost_price") or 0.0),
            "valuation": 0.0,
        })
        on_hand = float(tr.get("closing_quantity") or 0.0)
        val = float(tr.get("valuation") or 0.0)
        inward = float(tr.get("purchased_quantity") or 0.0)
        outward = float(tr.get("sold_quantity") or 0.0)

        total_val += val
        total_on_hand += on_hand
        total_received += inward
        total_issued += outward

        item_status = "IN_STOCK" if on_hand > 0 else "OUT_OF_STOCK"
        item_dict = {
            "id": pid,
            "name": r.get("name"),
            "product_code": r.get("product_code"),
            "unit": r.get("unit") or "unit",
            "quantity_on_hand": on_hand,
            "purchased_quantity": inward,
            "sold_quantity": outward,
            "average_cost": tr.get("average_cost", 0.0),
            "valuation": val,
            "status": item_status,
        }

        if product_name:
            p_low = product_name.lower()
            if p_low in str(r.get("name", "")).lower() or p_low in str(r.get("product_code", "")).lower():
                tracked_items.append(item_dict)
        elif only_low_stock:
            if on_hand <= 0:
                tracked_items.append(item_dict)
        else:
            tracked_items.append(item_dict)

    out_of_stock_count = sum(1 for item in tracked_items if item["quantity_on_hand"] <= 0)

    return {
        "total_valuation": round(total_val, 2),
        "total_units_on_hand": round(total_on_hand, 2),
        "total_received_units": round(total_received, 2),
        "total_issued_units": round(total_issued, 2),
        "out_of_stock_count": out_of_stock_count,
        "tracked_products_count": len(tracked_items),
        "products": tracked_items,
    }
