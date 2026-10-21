"""Word-level catalogue matching — shared by classifier, purchase sync and
line linking (single source of truth, 2026-10-18).

The old substring/exact checks failed on the everyday forms: "office
chair" vs catalogue "chairs" (plural), "Office Chair" vs "chairs" (case +
word order). The purchase handler then CREATED a duplicate product and
credited stock to it instead of the existing item (live verified on
PRD-000002 vs PRD-000004, session 2026-10-18).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional


def match_catalogue_product(
    item: Any, products: Iterable[Optional[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """Best product match for an item — WORD-LEVEL, singular/plural tolerant.

    Matching on shared significant words (>=3 chars, 's'-stripped) catches
    the real synonyms; among multiple hits, stock-tracked products win
    (they carry the resale answer) and longer overlaps rank higher.
    Returns None when nothing overlaps.
    """

    def _toks(text: Any) -> set:
        out = set()
        for t in re.findall(r"[a-z]+", str(text or "").lower()):
            t = t.rstrip("s")
            if len(t) >= 3:
                out.add(t)
        return out

    item_toks = _toks(item)
    if not item_toks:
        return None
    best_score = 0
    best = None
    for p in products or ():
        if not isinstance(p, dict):
            continue
        prod_toks = _toks(p.get("name"))
        if not prod_toks:
            continue
        # SUBSET-CONTAINMENT GATE (2026-10-20, per-item tracking): require
        # full containment in ONE direction — every significant word of the
        # SHORTER name must appear in the longer.  'office chair' still finds
        # 'chairs' (chair fully contained), but distinct items that merely
        # share ONE generic word no longer merge ('office chair' vs 'dining
        # chair', 'Honda bike' vs 'Yamaha bike', 'Batt Gadget' vs 'Batt
        # CashUnit').  The old any-overlap rule collapsed such items into a
        # single product and corrupted per-item stock tracking.
        if not (prod_toks <= item_toks or item_toks <= prod_toks):
            continue
        overlap = item_toks & prod_toks
        if not overlap:
            continue
        score = len(overlap) * 2 + (1 if p.get("is_stock_tracked") else 0)
        if score > best_score:
            best_score = score
            best = p
    return best
