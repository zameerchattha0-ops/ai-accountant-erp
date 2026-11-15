"""LLM item-nature analyst (2026-10-20).

"Where does this purchased/sold item live — resale INVENTORY, a FIXED ASSET,
or both?" is a SEMANTIC, purpose-dependent judgment (a motorbike bought to
resell is inventory; the same motorbike bought for business use is a fixed
asset), so the LLM is the analyst — not a keyword rule or a token-overlap
hint, which only ever cover phrasings someone anticipated.

The analyst FETCHES both live registers (catalogue products + fixed-asset
register), hands them to the model, and asks it to reason about:
  * does the item match an EXISTING inventory product? a FIXED asset? both?
  * what is the PURPOSE OF USE, when the query states it (resell vs business
    use vs own consumption)?
  * is the treatment UNAMBIGUOUS (route it) or genuinely ambiguous (ASK)?

AUTHORITY SPLIT (same principle as extraction + catalogue dedup):
* LLM decides location / purpose / proposed nature / whether to ask;
* Python only FETCHES the two registers (data retrieval) and GROUNDS the
  answer — the model returns 1-based INDEXES into the lists it was given
  (never an invented id), the nature must be a canonical value, and any
  doubt or invalid output degrades to ASK (never a silent guess);
* a flag gates it off for the deterministic unit suite.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# Canonical natures the analyst may propose (kept in step with classifier).
_NATURES = {
    "INVENTORY", "FIXED_ASSET", "OPERATING_EXPENSE", "SERVICE",
    "CONSUMABLE", "PREPAYMENT", "DEPOSIT_ADVANCE", "INTANGIBLE_ASSET",
}

_LOCATIONS = {"INVENTORY_ONLY", "FIXED_ASSET_ONLY", "BOTH", "NEITHER"}

_INSTRUCTION = (
    'You are an expert accounting item-nature analyst for an ERP system. Given a '
    'PURCHASE/SALE request, the organization context and business profile, and live '
    'registers, determine the economic nature and accounting treatment of the item under '
    'accounting standards (IAS 16 / IAS 2 / IAS 38).\n\n'
    'ANALYZE IN THIS SYSTEMATIC ORDER (Query + Business Model + Org Profile + Catalogue + Fixed Assets):\n'
    '1. BUSINESS OPERATIONS & MODEL — inspect the organization name, business type, and '
    'operations in BUSINESS CONTEXT:\n'
    '   * Service / Software / Digital / Professional firms (e.g. SOFTWARE_HOUSE, digital '
    'creators, software agencies, consulting, clinics, law firms): Their business model is '
    'delivering digital services or expertise, NOT goods retail. When they acquire office '
    'furniture (tables, chairs, desks, cabinets), computers, laptops, monitors, servers, '
    'air conditioners, or office machinery, these items are NOT held for resale and will NOT '
    'generate revenue from sale. Under IAS 16, they are tangible assets held for administrative '
    'and office operations -> FIXED_ASSET (Property, Plant & Equipment) if durable (>1 year useful life), '
    'or OPERATING_EXPENSE if consumable supplies. NEVER classify such items as INVENTORY for '
    'a service firm unless explicitly in their sales catalogue as resale stock. Propose FIXED_ASSET '
    'with confidence=HIGH and needs_question=false.\n'
    '   * Retail / Wholesale / Trading firms (e.g. TRADING, RETAIL, merchandise distributors): '
    'Items of their trade (e.g. tables for a furniture showroom) -> INVENTORY. Internal office fixtures -> FIXED_ASSET.\n'
    '2. REQUEST CONTEXT & EXPLICIT PURPOSE — if the request explicitly states purpose ("for office use", '
    '"for employees", "for our studio" -> FIXED_ASSET; "to resell to client", "for shop stock" -> INVENTORY).\n'
    '3. EXISTING REGISTERS — check INVENTORY PRODUCTS (catalogue) and FIXED ASSETS:\n'
    '   * Matches stock-tracked product in catalogue -> INVENTORY.\n'
    '   * Matches existing fixed asset or asset class -> FIXED_ASSET.\n'
    '   * Matches neither: deduce decisively from Business Model + Item Nature. If the business model '
    'clearly dictates the treatment (e.g. software company buying office tables -> FIXED_ASSET), '
    'propose the nature with confidence=HIGH and needs_question=false.\n'
    '4. WHEN TO ASK — set needs_question=true ONLY if the item is genuinely unusual, ambiguous, or '
    'dual-purpose after this 5-dimension analysis (e.g. personal drawing vs business, or an unusual '
    'item completely unrelated to the business with unclear purpose). Never ask unnecessary questions '
    'when the business model and operations make the accounting treatment obvious.\n\n'
    'Output STRICT JSON only, matching EXACTLY: {"location": '
    '"<INVENTORY_ONLY|FIXED_ASSET_ONLY|BOTH|NEITHER>", "inventory_index": '
    '<1-based int or null>, "asset_index": <1-based int or null>, "purpose": '
    '"<RESALE|BUSINESS_USE|CONSUMABLE|SERVICE|UNKNOWN>", "proposed_nature": '
    '"<canonical nature or null>", "confidence": "<HIGH|MEDIUM|LOW>", '
    '"needs_question": <true|false>, "question": "<short question or empty>", '
    '"reasoning": "<one short sentence explaining decision based on business model and item>"}. '
    'inventory_index/asset_index are POSITIONS (starting at 1) in the numbered INVENTORY/ASSET lists, '
    'or null when the item matches none.'
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _inv_block(products: List[Dict[str, Any]]) -> str:
    if not products:
        return "(none)"
    return "\n".join(
        f"{i}. {p.get('name')!r} (code={p.get('product_code')}, "
        f"stock_tracked={bool(p.get('is_stock_tracked'))})"
        for i, p in enumerate(products, start=1)
    )


def _asset_block(assets: List[Dict[str, Any]]) -> str:
    if not assets:
        return "(none)"
    return "\n".join(
        f"{i}. {a.get('name')!r} (code={a.get('asset_code')}, "
        f"status={a.get('status')})"
        for i, a in enumerate(assets, start=1)
    )

async def analyse_item_nature(
    *,
    organization_id,
    item: str,
    intent: str,
    message: str,
    org_context: str = "",
    client: Any = None,
    timeout: Optional[float] = None,
    products: Optional[List[Dict[str, Any]]] = None,
    assets: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """LLM decision on where the item lives + the treatment to propose.

    Returns a dict with the grounded ``location`` / ``proposed_nature`` /
    ``needs_question`` / ``question`` / ``matched_product`` / ``matched_asset``
    / ``reasoning``.  Returns None when the analyst is disabled, unavailable,
    or returns invalid output (the caller keeps its deterministic path).
    Never raises.  Grounding: an out-of-range index is impossible evidence
    and is discarded (treated as no match).
    """
    term = str(item or "").strip()
    if not term:
        return None

    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "llm_item_nature_enabled", False):
        return None

    # Fetch the two live registers (data retrieval — Python's job).
    try:
        if products is None:
            from app.database import fetch_many as _fm

            products = await _fm(
                "products",
                filters={"organization_id": str(organization_id)},
                select="id,name,product_code,is_stock_tracked",
                limit=200,
            ) or []
        if assets is None:
            from app.repositories import fixed_asset_repository as _far

            assets = await _far.list_assets(organization_id, limit=200) or []
    except Exception as exc:  # noqa: BLE001 — a register read never blocks
        log.warning("item_nature.register_fetch_failed", error=str(exc)[:200])
        products = products or []
        assets = assets or []

    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()
        context_section = f"\n\nBUSINESS CONTEXT:\n{org_context}" if org_context else ""
        raw = await asyncio.wait_for(
            client.generate_text_light(
                prompt=(
                    f"{_INSTRUCTION}\n\nREQUEST (intent={intent}):\n"
                    f"{str(message or term)[:800]}\n\nITEM: {term[:200]}"
                    f"{context_section}\n\n"
                    f"INVENTORY PRODUCTS:\n{_inv_block(products)}\n\n"
                    f"FIXED ASSETS:\n{_asset_block(assets)}"
                )
            ),
            timeout=timeout or getattr(settings, "llm_item_nature_timeout", 10.0),
        )
    except Exception as exc:  # noqa: BLE001 — degrade, never block
        log.warning("item_nature.llm_unavailable", error=str(exc)[:160])
        return None

    payload = _extract_json(str(raw or ""))
    if not isinstance(payload, dict):
        log.warning("item_nature.reject", reason="unparseable reply")
        return None

    # ---- GROUNDING (Python validates; the model never invents) ----
    location = str(payload.get("location") or "").strip().upper()
    if location not in _LOCATIONS:
        location = "NEITHER"

    def _ground_index(idx: Any, pool: List[Dict[str, Any]]):
        try:
            pos = int(idx)
        except (TypeError, ValueError):
            return None
        if not (1 <= pos <= len(pool)):
            log.warning("item_nature.index_out_of_range", value=idx)
            return None
        return pool[pos - 1]

    matched_product = _ground_index(payload.get("inventory_index"), products)
    matched_asset = _ground_index(payload.get("asset_index"), assets)

    nature = str(payload.get("proposed_nature") or "").strip().upper()
    if nature not in _NATURES:
        nature = None

    purpose = str(payload.get("purpose") or "").strip().upper()
    confidence = str(payload.get("confidence") or "MEDIUM").strip().upper()
    if confidence not in ("HIGH", "MEDIUM", "LOW"):
        confidence = "MEDIUM"

    needs_question = bool(payload.get("needs_question"))
    question = str(payload.get("question") or "").strip()
    reasoning = str(payload.get("reasoning") or "").strip()[:200]

    # A proposed nature with no grounds AND no question is a silent guess —
    # never trust it: force the ask.
    if nature and not needs_question and location == "NEITHER" and confidence != "HIGH":
        needs_question = True
        question = question or (
            f"How should '{term[:60]}' be treated — resale inventory, a "
            "fixed asset, a consumable/expense, or a service?"
        )

    log.info(
        "item_nature.analysed",
        item=term[:80], intent=intent, location=location,
        nature=nature, purpose=purpose, confidence=confidence,
        needs_question=needs_question,
        matched_product=str((matched_product or {}).get("name")),
        matched_asset=str((matched_asset or {}).get("name")),
        reasoning=reasoning,
    )
    return {
        "location": location,
        "purpose": purpose,
        "proposed_nature": nature,
        "confidence": confidence,
        "needs_question": needs_question,
        "question": question,
        "reasoning": reasoning,
        "matched_product": matched_product,
        "matched_asset": matched_asset,
    }
