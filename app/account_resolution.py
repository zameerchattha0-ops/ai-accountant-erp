"""
ERP AI Agent — Execution-Agent Loop: chart-of-accounts resolution
=================================================================
Why: LLM-proposed entries (and approved/deterministic paths) used to die
DEEP in execution with "No fixed-asset account could be determined …"
(2026-09-25 screenshot-2 incident) because account-hint / config-gap
resolution is skipped on proposal & approved paths (P1-⑧).  This module
closes the loop, generically:

* PRE-FLIGHT — every account a planned call REQUIRES (register_fixed_asset
  needs a PPE ledger; a known expense category needs its own ledger) or
  NAMES (explicit account args, journal lines) is resolved against the
  live chart BEFORE the user approves anything.
* RESOLVE-OR-CREATE — a missing ledger becomes the account-creation
  clarification (IFRS-aware proposal, user-confirmed).  The confirmed name
  flows through the existing merge contract (planner
  _merge_clarification_answers: question text "should i create" +
  ``no '<name>' account`` → entities["create_account"]) and the classifier
  marks create_account_confirmed so execution runs create_account FIRST
  (tool-order guard) before the recording mutation.
* RESCUE — an execution-time account-DETERMINATION error with nothing
  recorded yet becomes the SAME clarification instead of a dead-end
  FAILED run.

No per-activity templates: any intent that plans a tool which names or
requires an account routes through the same pre-flight and rescue.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# IFRS-aware account shape per economic nature: (account_type, normal_balance,
# base_code, ifrs_hint).  DB enums (migration 001): account_type in
# ASSET|LIABILITY|EQUITY|REVENUE|EXPENSE; normal_balance in DEBIT|CREDIT with
# the CHECK constraint ASSET/EXPENSE→DEBIT, LIABILITY/EQUITY/REVENUE→CREDIT
# (migration 005).
# ---------------------------------------------------------------------------
_ACCOUNT_SHAPES: Dict[str, Tuple[str, str, str, str]] = {
    "FIXED_ASSET": ("ASSET", "DEBIT", "1500", "IFRS: property, plant and equipment"),
    "INTANGIBLE_ASSET": ("ASSET", "DEBIT", "1510", "IFRS: intangible assets"),
    "INVENTORY": ("ASSET", "DEBIT", "1200", "IFRS: inventories"),
    "PREPAYMENT": ("ASSET", "DEBIT", "1400", "IFRS: prepayments"),
    "DEPOSIT_ADVANCE": ("ASSET", "DEBIT", "1410", "IFRS: deposits and advances"),
    "OPERATING_EXPENSE": (
        "EXPENSE", "DEBIT", "6100", "IFRS: operating / administrative expenses",
    ),
    "CONSUMABLE": (
        "EXPENSE", "DEBIT", "6190", "IFRS: consumables (operating expenses)",
    ),
    "SERVICE": ("EXPENSE", "DEBIT", "6100", "IFRS: operating expenses"),
    "REVENUE": (
        "REVENUE", "CREDIT", "4100", "IFRS 15: revenue from contracts with customers",
    ),
    "OTHER_INCOME": ("REVENUE", "CREDIT", "4200", "IFRS: other income"),
}
_DEFAULT_SHAPE = ("EXPENSE", "DEBIT", "6100", "IFRS: operating expenses")


def account_shape(nature: Optional[str]) -> Tuple[str, str, str, str]:
    """(account_type, normal_balance, base_code, ifrs_hint) for *nature*."""
    return _ACCOUNT_SHAPES.get(str(nature or "").upper(), _DEFAULT_SHAPE)


def nature_for_intent(intent: str, entities: Optional[Dict[str, Any]] = None) -> str:
    """Best-effort economic nature for a gap proposal (explicit answer first)."""
    explicit = str((entities or {}).get("transaction_nature") or "").upper()
    if explicit in _ACCOUNT_SHAPES:
        return explicit
    intent = str(intent or "")
    if intent.startswith((
        "register_fixed_asset", "dispose_fixed_asset", "record_asset_depreciation",
    )):
        return "FIXED_ASSET"
    if "sale" in intent or "invoice" in intent or "receipt" in intent:
        return "REVENUE"
    return "OPERATING_EXPENSE"


# ---------------------------------------------------------------------------
# Category-level granularity: an item NEVER becomes an account.  "2 office
# chairs" opens/uses a FURNITURE ledger (all beds/sofas/chairs/tables post
# there), fittings their own ledger — matching the balance-sheet grouping
# the user sees (PPE → Furniture, PPE → Fixtures & Fittings, …).
# Order matters: the most specific family first.
# ---------------------------------------------------------------------------
_ITEM_CATEGORY_RULES: Tuple[Tuple[str, str], ...] = (
    (r"bed|sofa|couch|chair|table|desk|cabinet|shelf|cupboard|wardrobe|furnitur",
     "Furniture & Fixtures"),
    (r"fitting|fixture|partition|false ceiling|flooring|racking",
     "Fixtures & Fittings"),
    (r"laptop|desktop|computer|printer|scanner|monitor|server|router|"
     r"\bups\b|it equipment|keyboard|mouse",
     "Computer Equipment"),
    (r"vehicle|car\b|motorcycle|\bbike\b|truck|van\b|delivery vehicle",
     "Vehicles"),
    (r"generator|solar|air conditioner|\bac\b|inverter|boiler|pump|"
     r"machinery|\bmachine\b|industrial equipment",
     "Plant & Machinery"),
    (r"license|licence|software|subscription|patent|trademark|copyright",
     "Intangible Assets"),
    (r"jewel|gold|silver|investment|shares|deposit",
     "Other Non-Current Assets"),
)


def category_for_item(text: Any) -> str:
    """The CATEGORY ledger an item belongs to (never the item's own name)."""
    low = str(text or "").strip().lower()
    if not low:
        return "Other Equipment & Fixtures"
    for pattern, category in _ITEM_CATEGORY_RULES:
        if re.search(pattern, low):
            return category
    return "Other Equipment & Fixtures"


async def heading_account_id(
    organization_id: uuid.UUID, *, nature: str
) -> Optional[str]:
    """Id of the grouping account a category ledger should hang under.

    ASSET → the Property/Plant & Equipment (or non-current-assets)
    HEADING when the chart has one with real children, so a new
    "Furniture & Fixtures" ledger posts UNDER PPE on the balance sheet.
    Returns None when no such heading exists — the account is then created
    top-level; a parent is never invented.
    """
    if str(nature or "").upper() != "ASSET":
        return None
    from app.repositories import account_repository as a_repo

    try:
        chart = await a_repo.get_chart_of_accounts(organization_id, limit=500)
        grouping = await a_repo.get_grouping_account_ids(organization_id)
    except Exception as exc:  # noqa: BLE001 — parent is best-effort
        log.warning("account_resolution.heading_lookup_failed", error=str(exc)[:200])
        return None
    if not chart or not grouping:
        return None
    for keyword in (
        "property, plant", "property plant", "plant and equipment",
        "plant & equipment", "fixed asset", "non-current asset",
    ):
        for acc in chart:
            aid = str(acc.get("id") or "")
            if not aid or aid not in grouping:
                continue  # only a real heading (it has children) qualifies
            if keyword in str(acc.get("name") or "").lower():
                return aid
    return None


# ---------------------------------------------------------------------------
# Account-DETERMINATION failure classification (execution rescue trigger).
# Deliberately conservative: only errors whose remedy is a chart-of-accounts
# gap (create the ledger or name an existing one) — never party/permission/
# validation errors.
# ---------------------------------------------------------------------------
_ACCOUNT_RESOLUTION_PATTERNS = (
    r"no .*account.*could be determined",
    r"account could not be (determined|resolved)",
    r"add one to the chart of accounts",
    r"specify the asset account",
    r"no .*account.*exists",
    r"unknown account",
    r"account ['\"].+?['\"] (was )?not found",
    r"account .* does not exist",
    r"missing account",
)


def is_account_resolution_error(message: Optional[str]) -> bool:
    """True when *message* is a chart-of-accounts gap the loop can fix."""
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(re.search(p, text) for p in _ACCOUNT_RESOLUTION_PATTERNS)


# ---------------------------------------------------------------------------
# A missing-ledger proposal: what to create (IFRS-aware), where it came from.
# ---------------------------------------------------------------------------
@dataclass
class AccountGap:
    name: str
    account_type: str = "EXPENSE"
    normal_balance: str = "DEBIT"
    base_code: str = "6100"
    ifrs_hint: str = "IFRS: operating expenses"
    source: str = "explicit_reference"
    candidates: List[str] = field(default_factory=list)


def gap_for_nature(name: str, nature: Optional[str], source: str) -> AccountGap:
    at, nb, code, ifrs = account_shape(nature)
    return AccountGap(
        name=name, account_type=at, normal_balance=nb,
        base_code=code, ifrs_hint=ifrs, source=source,
    )


def question_for_gap(gap: AccountGap) -> str:
    """The account-creation clarification.

    TEXT CONTRACT (do not reword casually): the planner's answer-merge
    (``_merge_clarification_answers``) recognises this question by the
    literal phrases "should i create" and ``no '<name>' account`` — a YES
    answer folds ``<name>`` into ``entities["create_account"]``; any other
    answer names an existing account instead (``entities["account_name"]``).
    Apostrophes are stripped from the name so the extraction stays exact.
    """
    name = (gap.name or "").strip().replace("'", "") or "the required"
    candidates = [c for c in (gap.candidates or []) if c][:4]
    cand_clause = ""
    if candidates:
        listed = ", ".join(f"'{c}'" for c in candidates)
        cand_clause = f" (similar existing accounts: {listed})"
    return (
        f"This entry needs the '{name}' ledger, but there is no '{name}' account "
        f"in your chart of accounts{cand_clause}. Should I create it "
        f"({gap.account_type} — {gap.ifrs_hint})? If a suitable account already "
        f"exists, name it instead."
    )


def options_for_gap(gap: AccountGap) -> List[str]:
    """Tap-to-answer options for :func:`question_for_gap`."""
    return ["Yes, create it", "Use an existing account"]


def gap_already_asked(prior_qa: Optional[Sequence[Dict[str, str]]]) -> bool:
    """One-shot guard: a merge-contract account question was already asked."""
    for qa in prior_qa or []:
        q = (qa.get("question") or "").lower()
        if "should i create" in q and "no '" in q:
            return True
    return False


# ---------------------------------------------------------------------------
# Chart lookups (read-only, best-effort — a lookup failure never breaks a run)
# ---------------------------------------------------------------------------
async def account_exists(organization_id: uuid.UUID, name: str) -> Optional[Dict[str, Any]]:
    """Exact (normalized) name match among active accounts, else None."""
    from app.name_matching import name_key
    from app.repositories import account_repository as a_repo

    ref = str(name or "").strip()
    if not ref:
        return None
    try:
        candidates = await a_repo.search_accounts(organization_id, query=ref, limit=25)
    except Exception as exc:  # noqa: BLE001 — lookup is best-effort
        log.warning("account_resolution.search_failed", error=str(exc)[:200])
        return None
    key = name_key(ref)
    for acc in candidates or []:
        if acc.get("is_active") is False:
            continue
        if name_key(acc.get("name")) == key:
            return acc
        if str(acc.get("code") or "").strip() == ref:
            return acc
    return None


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ACCOUNT_REF_KEYS = frozenset({
    "account", "account_name", "account_code", "asset_account",
    "expense_account", "income_account", "cash_account", "bank_account",
    "ledger_account",
})


def _ref_value(value: Any) -> Optional[str]:
    """A usable account NAME reference (ids are the service's business)."""
    if not isinstance(value, str):
        return None
    ref = value.strip()
    if not ref or _UUID_RE.match(ref):
        return None
    if ">" in ref:  # path form "Admin Expense > Utilities" → leaf name
        ref = ref.split(">")[-1].strip()
    return ref or None


def collect_account_refs(tool_calls: Optional[Sequence[Any]]) -> List[str]:
    """Account NAME references a planned call carries (args + journal lines)."""
    refs: List[str] = []
    for tc in tool_calls or []:
        args = getattr(tc, "arguments", None) or {}
        for key, value in args.items():
            if key in _ACCOUNT_REF_KEYS:
                ref = _ref_value(value)
                if ref:
                    refs.append(ref)
            if key in ("lines", "entries") and isinstance(value, list):
                for line in value:
                    if not isinstance(line, dict):
                        continue
                    for lkey in ("account", "account_name", "account_code"):
                        ref = _ref_value(line.get(lkey))
                        if ref:
                            refs.append(ref)
    # order-preserving unique
    seen: set = set()
    ordered: List[str] = []
    for ref in refs:
        k = ref.lower()
        if k not in seen:
            seen.add(k)
            ordered.append(ref)
    return ordered


# ---------------------------------------------------------------------------
# Nature probes: would the domain service find ITS account today?
# ---------------------------------------------------------------------------
def _has_explicit_account_id(tool_calls: Optional[Sequence[Any]]) -> bool:
    """A planned call pins the account by id → the service resolves it itself."""
    for tc in tool_calls or []:
        args = getattr(tc, "arguments", None) or {}
        for key, value in args.items():
            if key.endswith("account_id") and value:
                return True
    return False


async def fixed_asset_account_gap(
    organization_id: uuid.UUID, *, entities: Dict[str, Any]
) -> Optional[AccountGap]:
    """register_fixed_asset with no unambiguous PPE ledger → creation gap.

    Mirrors ``fixed_asset_service.register_asset``'s resolution exactly
    (same keywords / exclusions), so the pre-flight asks exactly when
    execution would otherwise raise.  Ambiguous keyword matches (several
    asset accounts) surface as candidates the user can name instead.
    """
    from app.services.fixed_asset_service import (
        _ASSET_ACCOUNT_KEYWORDS,
        _resolve_gl_account,
    )

    try:
        found = await _resolve_gl_account(
            organization_id,
            account_type="ASSET",
            keywords=_ASSET_ACCOUNT_KEYWORDS,
            explicit_id=None,
            exclude_keywords=("accumulated depreciation",),
        )
    except Exception as exc:  # noqa: BLE001 — fail open (status quo)
        log.warning("account_resolution.asset_probe_failed", error=str(exc)[:200])
        return None
    if found is not None:
        return None

    # Distinguish zero-match from ambiguity for an honest question.
    from app.repositories import account_repository as a_repo

    candidates: List[str] = []
    try:
        chart = await a_repo.get_chart_of_accounts(
            organization_id, account_type="ASSET", limit=100
        )
        names = [
            str(a.get("name") or "")
            for a in chart or []
            if any(
                k in str(a.get("name") or "").lower()
                for k in _ASSET_ACCOUNT_KEYWORDS
            )
            and not any(
                x in str(a.get("name") or "").lower()
                for x in ("accumulated depreciation",)
            )
        ]
        candidates = names[:4] if len(names) > 1 else []
    except Exception as exc:  # noqa: BLE001
        log.warning("account_resolution.asset_chart_failed", error=str(exc)[:200])

    # Category-level proposal: the ITEM never becomes an account — "office
    # chairs" proposes the Furniture & Fixtures ledger (all beds/sofas/
    # chairs/tables post there), fittings theirs, and so on.
    name = category_for_item(
        entities.get("asset_name")
        or entities.get("item_description")
        or entities.get("description")
        or ""
    )
    gap = gap_for_nature(name, "FIXED_ASSET", "fixed_asset_nature")
    gap.candidates = candidates
    return gap


async def expense_category_gap(
    organization_id: uuid.UUID,
    *,
    entities: Dict[str, Any],
    message: str = "",
) -> Optional[AccountGap]:
    """A KNOWN expense category without its own ledger → creation gap."""
    from app.classifier import _matched_expense_label, _propose_expense_account

    text = " ".join(
        str(x) for x in (
            entities.get("item_description"), entities.get("description"), message
        ) if x
    ).lower()
    label = _matched_expense_label(text)
    if not label:
        return None
    try:
        proposal = await _propose_expense_account(organization_id, label)
    except Exception as exc:  # noqa: BLE001 — fail open
        log.warning("account_resolution.expense_probe_failed", error=str(exc)[:200])
        return None
    if not proposal:
        return None
    name, code = proposal
    if await account_exists(organization_id, name) is not None:
        return None
    gap = gap_for_nature(name, "OPERATING_EXPENSE", "expense_category")
    if code:
        gap.base_code = str(code)
    return gap


# ---------------------------------------------------------------------------
# PRE-FLIGHT: the single chokepoint every path (reasoning proposal, model,
# deterministic fast path, approved plan) passes before confirmation/execute.
# ---------------------------------------------------------------------------
async def preflight_account_gaps(
    organization_id: uuid.UUID,
    *,
    tool_calls: Optional[Sequence[Any]],
    entities: Optional[Dict[str, Any]],
    intent: str,
    message: str = "",
    include_nature_probes: bool = True,
) -> List[AccountGap]:
    """Missing ledgers the planned calls require or name (order = priority).

    ``include_nature_probes`` mirrors the classifier's ``resolve_account_hints``
    flag (P1-⑧): the DB-heavy NATURE probes (fixed-asset / expense-category)
    run only on plain planner/model paths — proposal & approved paths keep
    their zero-extra-DB budget and are covered by the execution-time RESCUE
    instead.  Explicit NAME references are checked on every path (one search).
    """
    ents = dict(entities or {})
    gaps: List[AccountGap] = []
    seen: set = set()

    def _add(gap: Optional[AccountGap]) -> None:
        if gap is None:
            return
        key = (gap.name or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            gaps.append(gap)

    nature = nature_for_intent(intent, ents)

    # (a) explicit NAME references (args + journal lines) must exist
    for ref in collect_account_refs(tool_calls):
        if await account_exists(organization_id, ref) is None:
            _add(gap_for_nature(ref, nature, "explicit_reference"))

    if not include_nature_probes:
        return gaps

    names = {getattr(tc, "tool_name", "") for tc in tool_calls or ()}

    # (b) register_fixed_asset REQUIRES an unambiguous PPE ledger
    if ("register_fixed_asset" in names or intent == "register_fixed_asset") and (
        not _has_explicit_account_id(tool_calls)
    ):
        _add(await fixed_asset_account_gap(organization_id, entities=ents))

    # (c) a KNOWN expense category REQUIRES its own ledger
    if "create_expense" in names or intent == "record_expense":
        _add(await expense_category_gap(
            organization_id, entities=ents, message=message,
        ))

    return gaps


# ---------------------------------------------------------------------------
# RESCUE: map an execution-time account failure to the same proposal.
# ---------------------------------------------------------------------------
def gap_from_execution_failure(
    errors: Sequence[str],
    *,
    entities: Optional[Dict[str, Any]],
    intent: str,
) -> Optional[AccountGap]:
    """The creation proposal for a failed account-DETERMINATION call."""
    text = " ".join(str(e) for e in errors or () if e)
    if not is_account_resolution_error(text):
        return None
    ents = dict(entities or {})
    low = text.lower()
    example = re.search(r"e\.g\.\s*'(.+?)'", text)
    name = (example.group(1).strip() if example else "") or category_for_item(
        ents.get("asset_name")
        or ents.get("item_description")
        or ents.get("description")
        or ents.get("account_name")
        or ""
    )
    name = str(name).strip().replace("'", "")
    if not name:
        if "expense" in low:
            name = "Expense"
        elif "asset" in low:
            name = "Fixed Assets"
        else:
            return None  # nothing sensible to propose → FAILED as before
    nature = str(ents.get("transaction_nature") or "").upper()
    if nature not in _ACCOUNT_SHAPES:
        if "fixed-asset" in low or "fixed asset" in low or str(intent).startswith(
            ("register_fixed_asset", "dispose_fixed_asset")
        ):
            nature = "FIXED_ASSET"
        elif "revenue" in low or "income" in low:
            nature = "REVENUE"
        else:
            nature = "OPERATING_EXPENSE"
    return gap_for_nature(name, nature, "execution_rescue")


# ---------------------------------------------------------------------------
# EXECUTION ORDERING: the user-confirmed creation runs FIRST so the
# tool-order guard (agent) unblocks the recording mutation behind it.
# ---------------------------------------------------------------------------
def ensure_create_account_first(
    planned: Sequence[Any], *, arguments: Dict[str, Any]
) -> List[Any]:
    """Return *planned* with ``create_account`` as the first call.

    A call the model already added wins its own arguments (moved, not
    duplicated); otherwise one is constructed from *arguments*.
    """
    from app.models.schemas import ToolCall

    calls = list(planned or [])
    for index, call in enumerate(calls):
        if getattr(call, "tool_name", "") == "create_account":
            first = calls.pop(index)
            calls.insert(0, first)
            return calls
    calls.insert(0, ToolCall(tool_name="create_account", arguments=dict(arguments)))
    return calls
