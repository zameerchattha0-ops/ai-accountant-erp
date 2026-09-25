"""Separator-insensitive name matching — one source of truth.

Production incident 2026-09-24 (session ``8b2f14dd``): the reasoning layer's
``parties`` evidence came back EMPTY for "Alareesh Engineering" while the
customer ``Al-Areesh Engineering`` existed (created the same afternoon).
Every comparison layer had a separator blind spot:

    ILIKE '%alareesh%'               never matches 'Al-Areesh Engineering'
    'alareesh …' vs 'al areesh …'     never matches either

Given empty evidence the model's clarification was CORRECT behaviour — the
evidence itself was wrong.  ``name_key`` removes every separator, so case,
spacing, hyphens, punctuation and punctuation runs stop mattering:

    name_key('Al-Areesh Engineering') == name_key('Alareesh Engineering')

``normalized_matches`` is the bounded Python-side fallback used ONLY when
the strict SQL ILIKE search found nothing (the fast path never runs it).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

# \W = anything but a unicode letter/digit; _ (word char) is stripped too.
# Runs collapse, so "al-areesh  eng." -> "alareesheng".
_NON_ALNUM = re.compile(r"[\W_]+", flags=re.UNICODE)


def name_key(text: Any) -> str:
    """Lowercase, separator-stripped comparison key.

    ``None``/empty become ``""`` (callers must treat empty keys as "no
    match" — an empty needle would otherwise contain-match everything).
    """
    if text is None:
        return ""
    return _NON_ALNUM.sub("", str(text).lower())


def normalized_matches(
    rows: Iterable[Any],
    query: str,
    *,
    limit: int = 25,
    field: str = "name",
    min_key_length: int = 3,
) -> List[Dict[str, Any]]:
    """Rank *rows* by ``name_key`` containment against *query*.

    Ranks (stable within each):

        0 — keys equal                ("Alareesh Engineering" vs the same)
        1 — the full name sits inside the query
            (model worded it "... in cash" — the name is still a prefix key)
        2 — the query sits inside the name ("alareesh" vs "Al-Areesh …")

    Rows matching none of these are excluded.  Bounded to *limit*; a query
    shorter than *min_key_length* is never fuzzy-matched (too loose to be
    evidence).  Only ever called after the strict ILIKE search returned
    nothing, so established behaviour is untouched.
    """
    q = name_key(query)
    if len(q) < min_key_length:
        return []
    ranked: List[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = name_key(row.get(field))
        if not key:
            continue
        if key == q:
            rank = 0
        elif key in q:
            rank = 1
        elif q in key:
            rank = 2
        else:
            continue
        ranked.append((rank, row))
    ranked.sort(key=lambda item: item[0])  # stable within rank
    return [row for _, row in ranked[:limit]]
