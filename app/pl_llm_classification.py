"""AI-assisted fallback for P&L statement-section classification.

The deterministic chain (app/pl_structure.py) maps accounts to statement
sections from their SECTION-HEAD names with phrase lists.  A genuinely
custom chart — or an unusual head name — falls through to the catch-all
(``other_operating`` for expenses; ``operating_revenue`` is the revenue
default).  THIS layer, gated by ``settings.llm_pl_enabled`` (default OFF,
mirroring ``llm_classification_enabled``), sends ONLY those ambiguous
leaves to one short light-tier LLM call and lets it refine where they sit.

Contract — mirrored from the deployed ``llm_classification.decide()``:

  * flag off            -> deterministic buckets returned untouched, no call;
  * no candidates       -> deterministic buckets returned untouched, no call;
  * any failure         -> log + deterministic buckets returned untouched;
  * AssertionError      -> re-raised (a test's no-LLM guard stays loud);
  * LLM output          -> validated strictly: known section keys, candidate
                           codes only, account-type compatibility.

The LLM never supplies AMOUNTS: rows (and their figures) only MOVE between
buckets, so a bad reply can mis-section one line but can never change a
total, and ``build_statement`` still computes every subtotal from the same
rows it presents.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import structlog

from app.pl_structure import (
    OPERATING_REVENUE,
    OTHER_INCOME,
    OTHER_OPERATING,
    SECTION_LABELS,
)

log = structlog.get_logger(__name__)

# A section a row may be moved INTO, by account type.  The LLM can never
# cross the type line: revenue stays in the two revenue sections, expenses
# stay below gross profit.
_REVENUE_SECTIONS = frozenset({OPERATING_REVENUE, OTHER_INCOME})
_EXPENSE_SECTIONS = frozenset(set(SECTION_LABELS) - _REVENUE_SECTIONS)
_ALLOWED_BY_TYPE: Dict[str, Any] = {
    "REVENUE": _REVENUE_SECTIONS,
    "EXPENSE": _EXPENSE_SECTIONS,
}

_SECTION_GUIDE = """\
Sections (pick EXACTLY ONE per account):
- operating_revenue: revenue from the entity's CORE operations (sales of
  goods, services, subscriptions, consulting, project work).
- other_income: NON-operating income only (interest income, gains on
  disposal, dividends, incidental rent) — kept OUTSIDE operating revenue.
- cost_of_sales: direct cost of goods/services SOLD (stock consumed,
  subcontractors, freight-in, import duties).
- administrative: rent, utilities, salaries, office supplies, insurance,
  professional/audit/legal fees, general office costs.
- selling_marketing: advertising, marketing, promotions, sales commissions.
- distribution: freight-out, delivery and warehousing/shipping costs.
- other_operating: operating costs that genuinely fit none of the above.
- finance_costs: interest on loans/leases, bank charges, forex losses.
- tax_expense: corporate income tax ONLY."""

_HINT = (
    "When genuinely ambiguous between two sections, prefer the one that "
    "keeps the account INSIDE operating results (operating_revenue, "
    "administrative, selling_marketing, distribution, other_operating) — "
    "only choose other_income/finance_costs/tax_expense when the account "
    "clearly IS non-operating."
)


def _default_client() -> Any:
    """The same light-tier provider client the deployed layer uses."""
    from app.ai_orchestrator import get_client

    return get_client()


def _candidates(
    buckets: Dict[str, List[Dict[str, Any]]]
) -> List[Tuple[str, Dict[str, Any]]]:
    """Rows the deterministic pass could only GUESS at.

    * expenses in ``other_operating`` — the explicit catch-all for a custom
      chart whose head name matched no phrase;
    * revenue in ``operating_revenue`` — the revenue DEFAULT when no
      other-income phrase matched (an "Interest Income" leaf with an odd
      head name would otherwise sit inside gross profit).

    Rows already confident in another section (phrase-matched heads) are
    never offered to the model.
    """
    out: List[Tuple[str, Dict[str, Any]]] = []
    for section, rows in buckets.items():
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            atype = str(row.get("account_type") or "").upper()
            if atype == "EXPENSE" and section == OTHER_OPERATING:
                out.append((section, row))
            elif atype == "REVENUE" and section == OPERATING_REVENUE:
                out.append((section, row))
    return out


def _build_prompt(candidates: List[Tuple[str, Dict[str, Any]]]) -> str:
    import json

    items = [
        {
            "code": str(row.get("code") or ""),
            "name": str(row.get("name") or ""),
            "account_type": str(row.get("account_type") or ""),
            "current_section": section,
        }
        for section, row in candidates
    ]
    return (
        "Classify these general-ledger accounts for a multi-step Profit & "
        "Loss statement.\n\n"
        f"{_SECTION_GUIDE}\n\n"
        "Accounts:\n"
        f"{json.dumps(items, ensure_ascii=False)}\n\n"
        "Rules:\n"
        "- REVENUE accounts: section must be operating_revenue or "
        "other_income ONLY.\n"
        "- EXPENSE accounts: section must be one of cost_of_sales, "
        "administrative, selling_marketing, distribution, other_operating, "
        "finance_costs, tax_expense ONLY.\n"
        "- Return EVERY account above exactly once, using its exact code.\n"
        f"- {_HINT}\n"
        '- Reply with ONLY JSON: {"assignments": [{"code": "...", '
        '"section": "..."}]}'
    )


def _apply_moves(
    buckets: Dict[str, List[Dict[str, Any]]],
    payload: Dict[str, Any],
    candidates: List[Tuple[str, Dict[str, Any]]],
) -> int:
    """Validate the reply and move rows.  Returns how many actually moved.

    Every assignment must survive FOUR gates or it is silently ignored
    (never an error, never a guess): known candidate code, known section
    key, type compatibility, and an actual change.  Rows are matched by
    IDENTITY (never by dict equality) so a duplicated row can never be
    moved by accident.
    """
    assignments = payload.get("assignments")
    if not isinstance(assignments, list):
        return 0

    by_code: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for section, row in candidates:
        code = str(row.get("code") or "").strip()
        if code and code not in by_code:
            by_code[code] = (section, row)

    moved = 0
    for entry in assignments:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        target = str(entry.get("section") or "").strip()
        if code not in by_code:
            continue  # unknown/invented code — ignore
        if target not in SECTION_LABELS:
            continue  # hallucinated section — ignore
        current, row = by_code[code]
        if target == current:
            continue  # re-affirmation, nothing to do
        allowed = _ALLOWED_BY_TYPE.get(
            str(row.get("account_type") or "").upper()
        )
        if not allowed or target not in allowed:
            continue  # type crossing (e.g. expense → operating_revenue)
        source = buckets.get(current) or []
        for i, existing in enumerate(source):
            if existing is row:  # identity, not equality
                del source[i]
                break
        else:
            continue
        buckets.setdefault(target, []).append(row)
        by_code[code] = (target, row)
        moved += 1

    if moved:
        for rows in buckets.values():
            rows.sort(key=lambda r: (str(r.get("code") or ""),
                                     str(r.get("name") or "")))
    return moved


async def refine_buckets(
    buckets: Dict[str, List[Dict[str, Any]]],
    *,
    organization_id: Optional[Any] = None,
    client: Any = None,
    timeout: Optional[float] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Refine the ambiguous P&L buckets with ONE short light-tier LLM call.

    Never raises except AssertionError (a test's no-LLM guard stays loud);
    ANY other failure returns the deterministic ``buckets`` untouched —
    the statement still renders, one section possibly less refined.
    """
    from app.config import get_settings
    from app.questionnaire import _extract_json

    if not isinstance(buckets, dict):
        return buckets
    settings = get_settings()
    if not getattr(settings, "llm_pl_enabled", False):
        return buckets  # disabled by default — no client, no call
    candidates = _candidates(buckets)
    if not candidates:
        return buckets  # nothing ambiguous → nothing to ask

    try:
        if client is None:
            client = _default_client()
        prompt = _build_prompt(candidates)
        raw = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt),
            timeout=timeout or getattr(settings, "llm_pl_timeout", 15.0),
        )
    except AssertionError:
        raise  # a test's no-LLM guard must never be swallowed
    except Exception as exc:  # noqa: BLE001 — degrade to deterministic
        log.warning(
            "pl_llm.unavailable",
            error=str(exc)[:200],
            organization_id=str(organization_id or ""),
        )
        return buckets

    try:
        payload = _extract_json(str(raw or ""))
        if not isinstance(payload, dict):
            log.warning("pl_llm.reject", reason="unparseable reply")
            return buckets
        moved = _apply_moves(buckets, payload, candidates)
        if moved:
            log.info(
                "pl_llm.refined",
                moved=moved,
                candidates=len(candidates),
                organization_id=str(organization_id or ""),
            )
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001 — degrade to deterministic
        log.warning("pl_llm.apply_failed", error=str(exc)[:200])
        return buckets
    return buckets
