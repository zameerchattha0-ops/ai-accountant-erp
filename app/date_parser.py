"""
ERP AI Agent - Deterministic Transaction-Date Parser (Work Stream A)
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
* keywords: ``today``, ``yesterday``, ``tomorrow``

Everything else is rejected with an error that names both accepted
formats so the agent can re-ask once, with guidance.

Also provides ``resolve_date_range`` for report intents (Work Stream G):
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

_KEYWORD_DAYS = {
    "today": 0,
    "yesterday": -1,
    "tomorrow": 1,
}


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

    return _reject(raw)


# ---------------------------------------------------------------------------
# Work Stream G1 - relative-range resolution for REPORT intents.
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

