"""
ERP AI Agent - Deterministic Transaction-Date Parser
=====================================================================
Pure, deterministic date parsing for the mandatory transaction-date
protocol.  The LLM NEVER parses dates (house rule): every date the agent
accepts flows through ``parse_transaction_date``.

Accepted inputs (case-insensitive, trimmed):
* ``YYYY-MM-DD``  - ISO, preferred
* ``DD/MM/YYYY``  - day-first: the organisation is PKR-based (Pakistan),
  so the day comes first.  ``MM/DD/YYYY`` is deliberately NOT accepted -
  ambiguity is worse than a helpful error.
* ``DD-MM-YYYY``
* ``DD/MM`` / ``DD-MM``            - current year assumed
* ``26 sep 2026`` / ``26th September`` / ``sep 26, 2026``
* keywords: ``today``, ``yesterday``, ``tomorrow``
* relative phrases: ``day before yesterday``, ``2 days ago``,
  ``3 weeks ago``, ``a week ago``

Everything else is rejected with an error that names both accepted
formats so the agent can re-ask once, with guidance.

``resolve_relative_date_text`` scans a FREE-TEXT message for a date the
user already stated (keywords, relative phrases, numeric or month-name
dates) so the agent never asks for a date that is already in the request.

Also provides ``resolve_date_range`` for report intents:
deterministic resolution of "last month", "this month", "last week",
"this quarter", "last quarter" into ``date_from`` / ``date_to``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Tuple

# The single canonical re-ask guidance appended to every rejection.
DATE_HELP = (
    "Reply TODAY, or the date as YYYY-MM-DD or DD/MM/YYYY "
    "(for example 2026-09-04 or 04/09/2026)."
)

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# Day-first only.  A 2-digit year is rejected: "04/09/26" is ambiguous
# human input and the cost of a wrong century outweighs the convenience.
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DASH_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
# Day-first WITHOUT a year ("04/09") - the current year is assumed.  Only
# accepted as a whole answer (never scanned out of free text: "2/3 of the
# goods" is not a date).
_SHORT_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_SHORT_DASH_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_KEYWORD_DAYS = {
    "today": 0,
    "tonight": 0,
    "this morning": 0,
    "yesterday": -1,
    "tomorrow": 1,
}

# Relative phrases *inside* a sentence.  Ordered: the multi-word forms are
# checked before their shorter substrings.
_RELATIVE_PHRASES: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bday\s+before\s+yesterday\b"), "relative:day-before-yesterday"),
    (re.compile(r"\b(\d{1,3})\s+days?\s+ago\b"), "relative:days-ago"),
    (re.compile(r"\b(\d{1,3})\s+weeks?\s+ago\b"), "relative:weeks-ago"),
    (re.compile(r"\b(?:a|one|last)\s+week\s+ago\b"), "relative:week-ago"),
)
_RELATIVE_DAYS_AGO_RE = re.compile(r"\b(\d{1,3})\s+days?\s+ago\b")
_RELATIVE_WEEKS_AGO_RE = re.compile(r"\b(\d{1,3})\s+weeks?\s+ago\b")
_MONTH_DAY_FIRST_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\.?(?:,?\s+(\d{4}))?\b"
)
_MONTH_FIRST_RE = re.compile(
    r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b"
)


@dataclass
class DateParseResult:
    """Outcome of a deterministic transaction-date parse."""

    ok: bool
    iso_date: Optional[str] = None
    error: Optional[str] = None
    matched_format: Optional[str] = None


def _mk(iso: Optional[str], fmt: Optional[str]) -> DateParseResult:
    return DateParseResult(ok=True, iso_date=iso, matched_format=fmt)


def _reject(raw: str) -> DateParseResult:
    return DateParseResult(
        ok=False,
        error=f"Could not understand the date \"{raw}\". {DATE_HELP}",
    )


def _valid(y: int, m: int, d: int) -> bool:
    """Real calendar-date check (2026-02-30 is rejected; leap years ok)."""
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def parse_transaction_date(
    raw: str, today: Optional[date] = None
) -> DateParseResult:
    """Parse a user-supplied transaction date deterministically.

    Returns a :class:`DateParseResult`; ``ok=False`` results carry a
    helpful ``error`` listing the two accepted numeric formats.  No LLM
    is involved anywhere in this module.
    """
    base = today or date.today()
    text = (raw or "").strip().strip("\"'").rstrip(".").lower()
    if not text:
        return DateParseResult(
            ok=False, error=f"A transaction date is required. {DATE_HELP}"
        )

    # Keyword forms (exact word - "today-ish" is not a date)
    if text in _KEYWORD_DAYS:
        d = base + timedelta(days=_KEYWORD_DAYS[text])
        return _mk(d.isoformat(), f"keyword:{text}")

    # Relative phrases as a WHOLE answer ("2 days ago", "day before yesterday").
    if re.fullmatch(r"day\s+before\s+yesterday", text):
        return _mk((base - timedelta(days=2)).isoformat(), "relative:day-before-yesterday")
    m = _RELATIVE_WEEKS_AGO_RE.fullmatch(text)
    if m:
        return _mk((base - timedelta(days=7 * int(m.group(1)))).isoformat(), "relative:weeks-ago")
    m = _RELATIVE_DAYS_AGO_RE.fullmatch(text)
    if m:
        return _mk((base - timedelta(days=int(m.group(1)))).isoformat(), "relative:days-ago")
    if re.fullmatch(r"(?:a|one|last)\s+week\s+ago", text):
        return _mk((base - timedelta(days=7)).isoformat(), "relative:week-ago")

    # ISO YYYY-MM-DD (preferred)
    m = _ISO_RE.match(text)
    if m:
        y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid(y, mo, dd):
            return _mk(f"{y:04d}-{mo:02d}-{dd:02d}", "YYYY-MM-DD")
        return DateParseResult(
            ok=False,
            error=f"\"{raw}\" is not a real calendar date. {DATE_HELP}",
        )

    # DD/MM/YYYY (day-first, PKR convention) or DD-MM-YYYY
    m = _SLASH_RE.match(text) or _DASH_RE.match(text)
    if m:
        dd, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= dd <= 31 and 1 <= mo <= 12 and _valid(y, mo, dd):
            return _mk(f"{y:04d}-{mo:02d}-{dd:02d}", "DD/MM/YYYY")
        if mo > 12:
            # Helpfully name the likely mistake instead of guessing.
            return DateParseResult(
                ok=False,
                error=(
                    f"\"{raw}\" looks like MM/DD/YYYY - only day-first "
                    f"DD/MM/YYYY is accepted. {DATE_HELP}"
                ),
            )
        return DateParseResult(
            ok=False,
            error=f"\"{raw}\" is not a real calendar date. {DATE_HELP}",
        )

    # DD/MM or DD-MM without a year - the CURRENT year is assumed.
    m = _SHORT_SLASH_RE.match(text) or _SHORT_DASH_RE.match(text)
    if m:
        dd, mo = int(m.group(1)), int(m.group(2))
        if 1 <= dd <= 31 and 1 <= mo <= 12 and _valid(base.year, mo, dd):
            return _mk(f"{base.year:04d}-{mo:02d}-{dd:02d}", "DD/MM")

    # Month-name forms: "26 sep 2026", "26th September", "sep 26, 2026".
    named = _parse_named_date(text, base)
    if named:
        return named

    return _reject(raw)


def _parse_named_date(text: str, base: date) -> Optional[DateParseResult]:
    """Deterministic month-name parse ("26 sep 2026" / "sep 26 2026")."""
    m = _MONTH_DAY_FIRST_RE.fullmatch(text)
    if m and m.group(2)[:3] in _MONTHS:
        dd = int(m.group(1))
        mo = _MONTHS[m.group(2)[:3]]
        y = int(m.group(3)) if m.group(3) else base.year
        if 1 <= dd <= 31 and _valid(y, mo, dd):
            return _mk(f"{y:04d}-{mo:02d}-{dd:02d}", "D Month YYYY")
    m = _MONTH_FIRST_RE.fullmatch(text)
    if m and m.group(1)[:3] in _MONTHS:
        dd = int(m.group(2))
        mo = _MONTHS[m.group(1)[:3]]
        y = int(m.group(3)) if m.group(3) else base.year
        if 1 <= dd <= 31 and _valid(y, mo, dd):
            return _mk(f"{y:04d}-{mo:02d}-{dd:02d}", "Month D YYYY")
    return None


# ---------------------------------------------------------------------------
# relative-range resolution for REPORT intents.
# Deterministic; returns inclusive (date_from, date_to) ISO strings.
# ---------------------------------------------------------------------------
_WEEK_START_MONDAY = 0  # weeks run Monday-Sunday


def _quarter_bounds(d: date) -> Tuple[date, date]:
    q_start_month = 3 * ((d.month - 1) // 3) + 1
    start = date(d.year, q_start_month, 1)
    end_month = q_start_month + 2
    end = date(d.year, end_month, calendar.monthrange(d.year, end_month)[1])
    return start, end


def _month_bounds(d: date) -> Tuple[date, date]:
    start = date(d.year, d.month, 1)
    end = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    return start, end


def _shift_months(d: date, months: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + months
    y, m = divmod(total, 12)
    return date(y, m + 1, 1)


def resolve_date_range(
    raw: str, today: Optional[date] = None
) -> Optional[Tuple[str, str]]:
    """Resolve a relative period phrase to ``(date_from, date_to)`` ISO.

    Accepted: "this month", "last month", "this week", "last week",
    "this quarter", "last quarter".  Returns ``None`` when the text does
    not name a supported range (the caller keeps its normal behaviour).
    """
    base = today or date.today()
    text = (raw or "").strip().lower()

    # Common synonyms users type instead of "this month".
    text = text.replace("current month", "this month").replace(
        "present month", "this month"
    )

    if "this month" in text:
        s, e = _month_bounds(base)
        return s.isoformat(), e.isoformat()
    if "last month" in text:
        s, e = _month_bounds(_shift_months(base, -1))
        return s.isoformat(), e.isoformat()
    if "this week" in text:
        start = base - timedelta(days=base.weekday() - _WEEK_START_MONDAY)
        return start.isoformat(), (start + timedelta(days=6)).isoformat()
    if "last week" in text:
        start = base - timedelta(days=base.weekday() + 7)
        return start.isoformat(), (start + timedelta(days=6)).isoformat()
    if "this quarter" in text:
        s, e = _quarter_bounds(base)
        return s.isoformat(), e.isoformat()
    if "last quarter" in text:
        s, e = _quarter_bounds(_shift_months(base, -3))
        return s.isoformat(), e.isoformat()
    return None


# ---------------------------------------------------------------------------
# FREE-TEXT resolution - "never ask a date the user already stated".
# Run over the raw request (and its clarification answers) BEFORE any
# transaction-date question may exist.  Deterministic; no LLM.
# ---------------------------------------------------------------------------
def resolve_relative_date_text(
    text: str, today: Optional[date] = None
) -> Optional[DateParseResult]:
    """Resolve a date stated ANYWHERE inside *text*, or ``None``.

    Handles keywords ("yesterday", "today"), relative phrases ("day before
    yesterday", "2 days ago", "3 weeks ago", "a week ago") and explicit
    dates (ISO, day-first numeric, month-name).  Only the FIRST hit in the
    text wins - users state one transaction date per request.
    """
    base = today or date.today()
    raw_text = text or ""
    low = raw_text.strip().lower()
    if not low:
        return None

    # Multi-word relatives first: "day before yesterday" before "yesterday".
    if re.search(r"\bday\s+before\s+yesterday\b", low):
        return _mk(
            (base - timedelta(days=2)).isoformat(), "relative:day-before-yesterday"
        )
    m = _RELATIVE_DAYS_AGO_RE.search(low)
    if m:
        return _mk(
            (base - timedelta(days=int(m.group(1)))).isoformat(), "relative:days-ago"
        )
    m = _RELATIVE_WEEKS_AGO_RE.search(low)
    if m:
        return _mk(
            (base - timedelta(days=7 * int(m.group(1)))).isoformat(),
            "relative:weeks-ago",
        )
    if re.search(r"\b(?:a|one|last)\s+week\s+ago\b", low):
        return _mk((base - timedelta(days=7)).isoformat(), "relative:week-ago")
    for word in ("yesterday", "tomorrow", "tonight", "today"):
        if re.search(rf"\b{word}\b", low):
            return _mk(
                (base + timedelta(days=_KEYWORD_DAYS[word])).isoformat(),
                f"keyword:{word}",
            )

    # Explicit dates inside the text: ISO, then day-first numeric, then
    # month-name forms.
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw_text)
    if m and _valid(int(m.group(1)), int(m.group(2)), int(m.group(3))):
        return _mk(
            f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
            "YYYY-MM-DD",
        )
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", raw_text)
    if m:
        dd, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= dd <= 31 and 1 <= mo <= 12 and _valid(y, mo, dd):
            return _mk(f"{y:04d}-{mo:02d}-{dd:02d}", "DD/MM/YYYY")
    for pattern in (_MONTH_DAY_FIRST_RE, _MONTH_FIRST_RE):
        for match in pattern.finditer(low):
            month_group = 2 if pattern is _MONTH_DAY_FIRST_RE else 1
            if match.group(month_group)[:3] not in _MONTHS:
                continue
            named = _parse_named_date(match.group(0).strip(), base)
            if named:
                return named
    return None

