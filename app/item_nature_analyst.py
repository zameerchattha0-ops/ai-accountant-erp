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
    'You are an item-nature analyst for an accounting/ERP system. Given a '
    'PURCHASE/SALE request and the business LIVE registers, decide where '
    'the item lives and how it should be treated. REASON IN THIS ORDER:\n'
    '1. PURPOSE OF USE — if the request states WHY the item is bought/sold '
    '(resale to customers, own business use, personal, service delivery), '
    'that purpose is the strongest signal. Reselling -> INVENTORY. Own '
    'long-term business use -> FIXED ASSET. Consumed immediately -> '
    'CONSUMABLE/EXPENSE. A service -> SERVICE.\n'
    '2. EXISTING RECORDS — check whether the item already exists as an '
    'inventory product (stock you resell) and/or a registered fixed asset. '
    'Set location to INVENTORY_ONLY, FIXED_ASSET_ONLY, BOTH, or NEITHER.\n'
    '3. ROUTING:\n'
    '   - INVENTORY_ONLY -> propose INVENTORY (no question).\n'
    '   - FIXED_ASSET_ONLY -> this is usually a FIXED ASSET, but a business '
    'may start reselling it, so ASK (needs_question=true) unless the purpose '
    'is already crystal clear from the request.\n'
    '   - BOTH -> the SAME item is sometimes stock, sometimes an asset: if '
    'the purpose is stated, use it to decide; otherwise ASK.\n'
    '   - NEITHER -> rely on purpose alone; if the purpose is clear propose '
    'the nature, else ASK.\n'
    '4. NEVER GUESS a material treatment. When unsure, set needs_question='
    'true and write a short, specific question for the user.\n'
    'Output STRICT JSON only, matching EXACTLY: {"location": '
    '"<INVENTORY_ONLY|FIXED_ASSET_ONLY|BOTH|NEITHER>", "inventory_index": '
    '<1-based int or null>, "asset_index": <1-based int or null>, "purpose": '
    '"<RESALE|BUSINESS_USE|CONSUMABLE|SERVICE|UNKNOWN>", "proposed_nature": '
    '"<canonical nature or null>", "confidence": "<HIGH|MEDIUM|LOW>", '
    '"needs_question": <true|false>, "question": "<short question or empty>", '
    '"reasoning": "<one short sentence>"}.  inventory_index/asset_index are '
    'POSITIONS (starting at 1) in the numbered INVENTORY/ASSET lists, or null '
    'when the item matches none.'
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
        raw = await asyncio.wait_for(
            client.generate_text_light(
                prompt=(
                    f"{_INSTRUCTION}\n\nREQUEST (intent={intent}):\n"
                    f"{str(message or term)[:800]}\n\nITEM: {term[:200]}\n\n"
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
