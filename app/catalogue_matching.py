"""LLM catalogue dedup/match analyst (2026-10-20).

"Is this purchased/sold item the SAME PRODUCT as an existing catalogue
entry?" is a SEMANTIC judgment (same real-world good vs merely sharing a
generic word), so the LLM is the analyst — not a Python token-overlap rule,
which only ever covers phrasings someone anticipated and is exactly what
collapsed distinct items into one row.

AUTHORITY SPLIT (same principle as the stage-2 extraction inversion):
* LLM decides reuse-vs-distinct over the FETCHED candidate products;
* Python only FETCHES the candidates (data retrieval) and GROUNDS the
  answer — the model returns a 1-based INDEX into the candidate list I gave
  it, so it can never invent or point at a product that wasn't fetched;
* a deterministic EXACT-name floor keeps the fast path working when the
  model is disabled / unavailable / invalid, and any doubt returns None
  (never merge on a guess).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

_INSTRUCTION = (
    'You are a catalogue-dedup analyst for an accounting/ERP system. Decide '
    'whether the ITEM below is the SAME PRODUCT as one of the CANDIDATES. '
    'They are the SAME when they are the same real-world good you would buy '
    'once and stock (ignore singular/plural, letter case, spacing and minor '
    'wording differences). They are DIFFERENT when they are genuinely '
    'different goods (different model, brand, size, variant or type), even '
    'if they share a generic word. When you are not certain the two are the '
    'same good, treat them as DIFFERENT. Output STRICT JSON only, matching '
    'EXACTLY: {"match_index": <1-based integer or null>, "reason": "<short>"} '
    'where match_index is the POSITION (starting at 1) of the SAME product '
    'in the numbered CANDIDATES list, or null when the item matches NONE of '
    'them.'
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _candidates_block(candidates: List[Dict[str, Any]]) -> str:
    lines = []
    for i, p in enumerate(candidates, start=1):
        lines.append(
            f"{i}. {p.get('name')!r} (code={p.get('product_code')}, "
            f"stock_tracked={bool(p.get('is_stock_tracked'))})"
        )
    return "\n".join(lines)


async def llm_match_catalogue_item(
    item_name: str,
    candidates: List[Dict[str, Any]],
    *,
    client: Any = None,
    timeout: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Return the SAME-product candidate the LLM matched, else None.

    ``candidates`` are the already-fetched products (id required).  The model
    answers with a 1-based index into THIS list — grounding it to the fetched
    set — and we return that candidate.  None means "distinct item" (create a
    new product) or "could not decide" (deterministic fallback by caller).
    Never raises.
    """
    term = str(item_name or "").strip()
    usable = [c for c in candidates or () if isinstance(c, dict) and c.get("id")]
    if not term or not usable:
        return None

    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "llm_catalogue_match_enabled", False):
        return None
    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()
        raw = await asyncio.wait_for(
            client.generate_text_light(
                prompt=(
                    f"{_INSTRUCTION}\n\nITEM:\n{term[:200]}\n\n"
                    f"CANDIDATES:\n{_candidates_block(usable)}"
                )
            ),
            timeout=timeout
            or getattr(settings, "llm_catalogue_match_timeout", 8.0),
        )
    except Exception as exc:  # noqa: BLE001 — degrade to deterministic floor
        log.warning("catalogue_match.llm_unavailable", error=str(exc)[:160])
        return None

    payload = _extract_json(str(raw or ""))
    if not isinstance(payload, dict):
        log.warning("catalogue_match.reject", reason="unparseable reply")
        return None
    idx = payload.get("match_index")
    if idx is None:
        return None  # the model judged it a DISTINCT item
    try:
        pos = int(idx)
    except (TypeError, ValueError):
        log.warning("catalogue_match.reject", reason="index not an integer", value=idx)
        return None
    if not (1 <= pos <= len(usable)):
        # GROUNDING GUARD: an index outside the fetched list is impossible
        # evidence — never trust it.
        log.warning("catalogue_match.reject", reason="index out of range", value=pos)
        return None
    chosen = usable[pos - 1]
    log.info(
        "catalogue_match.llm_matched",
        item=term[:80], matched=str(chosen.get("name")),
        product_code=chosen.get("product_code"),
        reason=str(payload.get("reason") or "")[:120],
    )
    return chosen


async def exact_name_match(
    item_name: str, candidates: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Deterministic EXACT (case/space-insensitive) name floor — the fast,
    safe reuse that needs no model.  Used first, and as the fallback when the
    LLM is off/unavailable/invalid."""
    term = str(item_name or "").strip().lower()
    if not term:
        return None
    for c in candidates or ():
        if not isinstance(c, dict):
            continue
        if str(c.get("name") or "").strip().lower() == term:
            return c
    return None
