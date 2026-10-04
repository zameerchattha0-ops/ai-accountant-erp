"""
professional_name — industry-grade casing for stored master-data names.

Natural-language input arrives in whatever shape the user typed it
("motorbike", "abc autos"); an ERP must store catalogue items, party ledgers
and employees with consistent display casing ("Motorbike", "Abc Autos") so
documents, dropdowns and reports read professionally.

Rules (deliberately conservative — casing the user INTENTIONALLY set is
preserved):

* a word typed fully in lowercase gets its first letter capitalised;
* ALL-CAPS acronyms (ABC, PVT, NTN) are never rewritten;
* mixed-case tokens (iPhone, MacBook) are never rewritten;
* small connector words (and, for, of, the, â€¦) stay lowercase mid-name so
  "john and sons" reads "John and Sons", never "John And Sons";
* punctuation, digits and spacing around words are untouched — only runs of
  whitespace collapse.
"""

from __future__ import annotations

import re
from typing import Optional

# Kept lowercase when they are NOT the first word of the name.
_CONNECTORS = frozenset(
    {
        "and", "or", "of", "for", "the", "at", "in", "on", "to", "with",
        "de", "del", "van", "von", "bin", "ibn",
    }
)

# Unicode letter runs with optional internal apostrophes ("don't", "o'reilly").
# Hyphens act as separators, so "al-areesh" capitalises both parts.
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def professional_name(raw: Optional[str]) -> str:
    """Return *raw* with display-grade casing; ``None``/empty stays empty."""
    if not raw:
        return ""
    text = re.sub(r"\s+", " ", str(raw)).strip()
    if not text:
        return ""

    parts: list[str] = []
    pos = 0
    first = True
    for match in _WORD_RE.finditer(text):
        parts.append(text[pos : match.start()])
        word = match.group(0)
        low = word.lower()
        if word.islower() and (first or low not in _CONNECTORS):
            word = word[0].upper() + word[1:]
        parts.append(word)
        first = False
        pos = match.end()
    parts.append(text[pos:])
    return "".join(parts)
