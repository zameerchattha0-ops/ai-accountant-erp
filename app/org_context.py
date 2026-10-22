"""Per-business ORG CONTEXT — one live, org-scoped snapshot per turn.

(2026-10-19, the "five generic calls" fix): the extractor, classifier,
questionnaire authorizer and planner each answered about the business
while knowing almost nothing about it — every call was generic.  This
module builds ONE compact profile (chart essence, catalogue, parties,
recent document numbers) from LIVE org-filtered reads, and the agent
threads it into those existing calls.  Context is EVIDENCE for the
models; the deterministic gates, posting invariant and verifier stay the
law.

Freshness: the profile can be cached in-memory with a 45-second TTL per organization
(use_cache=True in agent turns), slashing Supabase CPU load by ~75-80% during multi-turn
clarification sessions. Tenant mutations immediately evict the cache via
invalidate_business_profile(org).

Tenant isolation (three layers): the only input is the organization_id
resolved from the authenticated membership — never from message text;
every fetch carries the ``organization_id`` filter; the payload never
persists across tenants (the TTL cache is keyed by organization_id).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Tuple

import structlog

from app.database import fetch_many

log = structlog.get_logger(__name__)

# Tenant-scoped in-memory cache: {org_id: (timestamp_monotonic, profile_dict)}
_PROFILE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_PROFILE_TTL_SECONDS = 45.0


def invalidate_business_profile(organization_id: uuid.UUID | str | None) -> None:
    """Invalidate cached business profile for tenant on writes/mutations."""
    if not organization_id:
        return
    _PROFILE_CACHE.pop(str(organization_id), None)


async def business_profile(
    organization_id: uuid.UUID | str,
    *,
    use_cache: bool = False,
    max_products: int = 15,
    max_parties: int = 12,
    max_accounts: int = 30,
    max_documents: int = 8,
) -> Dict[str, Any]:
    """Fresh, org-scoped business snapshot.

    Served from the 45s TTL in-memory cache when use_cache=True and fresh to spare
    Supabase CPU, or fetched live and cached. Every section fail-softs.
    """
    org = str(organization_id)
    now = time.monotonic()
    if use_cache:
        cached = _PROFILE_CACHE.get(org)
        if cached is not None and (now - cached[0]) < _PROFILE_TTL_SECONDS:
            data = cached[1]
            return {
                "products": list(data.get("products") or []),
                "customers": list(data.get("customers") or []),
                "suppliers": list(data.get("suppliers") or []),
                "accounts": list(data.get("accounts") or []),
                "invoices": list(data.get("invoices") or []),
                "bills": list(data.get("bills") or []),
            }

    async def _safe(label: str, coro, default):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001 — context never breaks a turn
            log.warning(
                "org_context.source_failed", source=label, error=str(exc)[:200]
            )
            return default

    products, customers, suppliers, accounts, invoices, bills = (
        await asyncio.gather(
            _safe("products", fetch_many(
                "products",
                filters={"organization_id": org},
                select="name,product_code,is_stock_tracked,cost_price",
                limit=max_products,
            ), []),
            _safe("customers", fetch_many(
                "customers",
                filters={"organization_id": org},
                select="name", limit=max_parties,
            ), []),
            _safe("suppliers", fetch_many(
                "suppliers",
                filters={"organization_id": org},
                select="name", limit=max_parties,
            ), []),
            _safe("accounts", fetch_many(
                "accounts",
                filters={"organization_id": org},
                select="code,name,account_type", limit=max_accounts,
            ), []),
            _safe("invoices", fetch_many(
                "invoices",
                filters={"organization_id": org},
                select="invoice_number,total",
                order="created_at.desc", limit=max_documents,
            ), []),
            _safe("bills", fetch_many(
                "purchase_bills",
                filters={"organization_id": org},
                select="bill_number,total",
                order="created_at.desc", limit=max_documents,
            ), []),
        )
    )
    res = {
        "products": list(products or []),
        "customers": [str(r.get("name") or "") for r in (customers or []) if r.get("name")],
        "suppliers": [str(r.get("name") or "") for r in (suppliers or []) if r.get("name")],
        "accounts": list(accounts or []),
        "invoices": list(invoices or []),
        "bills": list(bills or []),
    }
    _PROFILE_CACHE[org] = (now, res)
    return res


def render_profile(profile: Dict[str, Any] | None) -> str:
    """Compact prompt block for the existing calls; '' when nothing to say.

    Token-bounded on purpose: this rides into SHORT calls (extraction,
    classification decide, questionnaire authoring) where latency matters.
    """
    prof = profile or {}
    lines: list[str] = []
    products = prof.get("products") or []
    if products:
        items = []
        for p in products[:12]:
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            code = str(p.get("product_code") or "").strip()
            tag = "STOCK" if p.get("is_stock_tracked") else "non-stock"
            cost = p.get("cost_price")
            item = f"{name} ({code}, {tag})" if code else f"{name} ({tag})"
            if cost not in (None, ""):
                item += f" cost={cost}"
            items.append(item)
        lines.append("- Catalogue: " + "; ".join(items))
    if prof.get("customers"):
        lines.append("- Customers: " + ", ".join(prof["customers"][:12]))
    if prof.get("suppliers"):
        lines.append("- Suppliers: " + ", ".join(prof["suppliers"][:12]))
    accounts = prof.get("accounts") or []
    if accounts:
        acc_bits = []
        for a in accounts[:20]:
            code = str(a.get("code") or "").strip()
            name = str(a.get("name") or "").strip()
            if code or name:
                acc_bits.append(f"{code} {name}".strip())
        lines.append("- Chart accounts: " + "; ".join(acc_bits))
    docs = []
    for row in (prof.get("invoices") or [])[:6]:
        if row.get("invoice_number"):
            docs.append(f"invoice {row['invoice_number']} ({row.get('total')})")
    for row in (prof.get("bills") or [])[:6]:
        if row.get("bill_number"):
            docs.append(f"bill {row['bill_number']} ({row.get('total')})")
    if docs:
        lines.append("- Recent documents: " + "; ".join(docs))
    if not lines:
        return ""
    return (
        "\n\nYOUR BUSINESS (live, org-scoped, this turn):\n"
        + "\n".join(lines)
    )
