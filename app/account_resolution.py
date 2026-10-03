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
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# IFRS-aware account shape per economic nature: (account_type, normal_balance,
# base_code, ifrs_hint).  DB enums (migration 001): account_type in
# ASSET|LIABILITY|EQUITY|REVENUE|EXPENSE; normal_balance in DEBIT|CREDIT with
# the CHECK constraint ASSET/EXPENSE→DEBIT, LIABILITY/EQUITY/REVENUE→CREDIT
# (migration 005).
# ---------------------------------------------------------------------------
# SINGLE SOURCE OF TRUTH (Wave A) — app/accounting_vocabulary.py; see
# E:\Qoder\AUDIT_REPORT.md §3.1.  The old `_DEFAULT_SHAPE`
# ("EXPENSE", "DEBIT", "6100") is GONE: an unknown treatment now raises
# InvalidAccountingNature instead of silently becoming an operating expense.
from app.accounting_vocabulary import (
    ACCOUNT_SHAPES as _VOCAB_SHAPES,
    InvalidAccountingNature,
    account_shape,
)

#: Membership guards only (``nature in _ACCOUNT_SHAPES``).  Same keys as the
#: vocabulary module — derived, never a second inventory.
_ACCOUNT_SHAPES: Dict[str, Tuple[str, str, str, str]] = {
    name: (
        shape.account_type,
        shape.normal_balance,
        shape.base_code,
        shape.ifrs_hint,
    )
    for name, shape in _VOCAB_SHAPES.items()
}


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
    # Equipment words come BEFORE the vehicle brand names below, so a
    # "Honda generator" stays machinery instead of becoming a vehicle.
    (r"generator|solar|air conditioner|\bac\b|inverter|boiler|pump|"
     r"machinery|\bmachine\b|industrial equipment|compressor|\bcnc\b|"
     r"forklift|tractor|sewing machine|weighing scale|\bplant\b",
     "Plant & Machinery"),
    # Vehicles — MAKE and MODEL names included: an SME buys "Honda Civic",
    # not "a vehicle".  Production 2026-10-02 created the prerequisite ledger
    # for a Honda Civic as "Other Equipment & Fixtures" because only the
    # generic words matched (the old `car\b` even missed the plural "cars").
    (r"vehicle|vehicl|automobile|\bcars?\b|\bbikes?\b|motorcycle|scooter|"
     r"\bvans?\b|\bbuses?\b|\btrucks?\b|lorry|pickup|\bsuv\b|jeep|"
     r"toyota|honda|suzuki|\bkia\b|hyundai|nissan|mitsubishi|mazda|isuzu|"
     r"hino|mercedes|benz|\bbmw\b|audi|ford|chevrolet|renault|peugeot|"
     r"volkswagen|\bvw\b|proton|changan|haval|\bjac\b|foton|dfsk|"
     r"corolla|civic|hilux|fortuner|prado|land cruiser|sportage|tucson|"
     r"hiace|cultus|mehran|baleno|picanto|elantra|sonata|accord|prius|"
     r"aqua|vitz|yaris|wagon r|yamaha",
     "Vehicles"),
    # Property is PPE too — "office building" used to fall into the generic
    # bucket (production 2026-10-02, the 1,200,000 building purchase).
    (r"building|warehouse|godown|factory|premises|showroom|\bland\b|"
     r"\bplot\b|real estate",
     "Buildings & Land"),
    (r"license|licence|software|subscription|patent|trademark|copyright",
     "Intangible Assets"),
    (r"jewel|gold|silver|investment|shares|deposit",
     "Other Non-Current Assets"),
)


# ---------------------------------------------------------------------------
# STATEMENT-SECTION INVARIANT for category-ledger parents.
#
# "Accounts Receivable" is an ASSET, so a type-only parent check happily
# parented a newly created "Vehicles" ledger UNDER it (production
# 2026-09-30: create_parent_name = Accounts Receivable).  A category ledger
# belongs to the same SECTION as its heading, so current-asset / receivable /
# settlement / tax / contra accounts are never acceptable parents for a
# PPE-style category, however well the type matches.
# ---------------------------------------------------------------------------
_NON_CATEGORY_PARENT_PATTERNS: Tuple[str, ...] = (
    "receivab",
    "payable",
    "cash",
    "bank",
    "inventor",
    "stock",
    "prepaid",
    "advance",
    "vat",
    "tax",
    "accumulated depreciation",
    "contra",
)


def is_category_parent(
    account: Optional[Mapping[str, Any]], *, nature: str
) -> bool:
    """May *account* parent a category ledger of *nature*?

    Two conditions, both necessary:

    * the SAME statement section as the nature's shape (``account_type``);
    * for ASSET natures, the account must not sit in a current-asset /
      receivable / settlement / tax / contra section.

    An unknown treatment never certifies a section, and a missing account is
    never a parent — the caller then creates the ledger top-level instead of
    guessing (a parent is never invented).
    """
    if not account:
        return False
    try:
        expected_type = account_shape(nature)[0]
    except InvalidAccountingNature:
        return False
    if str(account.get("account_type") or "").upper() != expected_type:
        return False
    if expected_type != "ASSET":
        return True
    name = str(account.get("name") or "").strip().lower()
    return not any(pattern in name for pattern in _NON_CATEGORY_PARENT_PATTERNS)


# ---------------------------------------------------------------------------
# MAIN ACCOUNTING HEADS — the balance-sheet structure every fixed-asset
# decision is scoped to.
#
#   Assets      → Fixed Assets (non-current) , then Current Assets
#   Liabilities → Non-current Liabilities    , then Current Liabilities
#   Capital     → Equity
#
# REQUIREMENT (2026-10-03): when a request is identified as a FIXED-ASSET
# query, ONLY the Fixed Assets head may be analysed — never Current Assets
# (Receivables, Bank, Cash, Prepaid …) and never a contra account.
#
# The head is derived STRUCTURALLY: a party sub-ledger hangs UNDER its
# control account, so it inherits that account's head, however well its NAME
# matches a PPE category.  Production 2026-10-03 (session 169a88e0): the
# customer ledger "alpha associates" and the AR control "Accounts Receivable"
# both landed on "Vehicles" through category_for_item's nearest-vocabulary
# fallback while "ABC Furnitures" matched the PPE keyword "furniture" — a
# phantom tie that left the plan with no ledger and killed the acquisition
# with "No fixed-asset account could be determined".
# ---------------------------------------------------------------------------
HEAD_FIXED_ASSETS = "FIXED_ASSETS"
HEAD_CURRENT_ASSETS = "CURRENT_ASSETS"
HEAD_CONTRA = "CONTRA"

#: The CURRENT-ASSETS head: never a PPE ledger, never a fixed-asset
#: candidate, however descriptive its name.
_CURRENT_ASSET_SECTION_PATTERNS: Tuple[str, ...] = (
    "receivab", "payable", "cash", "bank", "inventor", "stock", "prepaid",
    "advance", "vat", "tax",
)

#: Contra accounts sit on the fixed-asset side of the sheet but never
#: receive a capitalised cost.
_CONTRA_SECTION_PATTERNS: Tuple[str, ...] = ("accumulated depreciation", "contra")

#: Union of both — the single "not a PPE ledger" test (the same pattern list
#: already backs the heading guard ``is_category_parent``).
_NON_PPE_SECTION_PATTERNS: Tuple[str, ...] = _NON_CATEGORY_PARENT_PATTERNS


def _section_of_name(name: Any) -> Optional[str]:
    """Head implied by an account's NAME alone, or ``None`` when undecided."""
    low = str(name or "").strip().lower()
    if any(p in low for p in _CONTRA_SECTION_PATTERNS):
        return HEAD_CONTRA
    if any(p in low for p in _CURRENT_ASSET_SECTION_PATTERNS):
        return HEAD_CURRENT_ASSETS
    return None


def account_head(
    account: Optional[Mapping[str, Any]],
    *,
    by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[str]:
    """The MAIN head an ASSET account belongs to.

    ``FIXED_ASSETS`` | ``CURRENT_ASSETS`` | ``CONTRA`` (``None`` only for an
    absent row, which is never a candidate).

    Order: the account's own name, then its PARENT (a party sub-ledger
    inherits its control account's head — this is what keeps
    "alpha associates" out of Fixed Assets), then the conservative default:
    an ASSET that is neither current nor contra is FIXED_ASSETS, so an oddly
    named PPE ledger is never silently dropped from its own acquisition.
    """
    if not account:
        return None
    head = _section_of_name(account.get("name"))
    if head is not None:
        return head
    parent_id = str(account.get("parent_account_id") or "").strip()
    if parent_id and by_id:
        parent = by_id.get(parent_id)
        if parent is not None:
            return account_head(parent, by_id=by_id)
    return HEAD_FIXED_ASSETS


def is_ppe_ledger_candidate(
    account: Optional[Mapping[str, Any]],
    *,
    by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> bool:
    """May *account* serve as the ASSET-COST ledger of a PPE acquisition?

    Exactly "is this account in the FIXED_ASSETS head?" — current-asset
    accounts, contra accounts and party sub-ledgers (which inherit their
    control account's head) are all excluded.  A genuine PPE ledger parented
    under a PPE heading stays a candidate.
    """
    if not account:
        return False
    return account_head(account, by_id=by_id) == HEAD_FIXED_ASSETS


# ---------------------------------------------------------------------------
# DESCRIPTIVE KEYWORD MATCH — how well a ledger's name explains the
# ACQUISITION being recorded.  Used ONLY to break a genuine tie between 2+
# ledgers of the SAME category, and only above the 75% floor: below that a
# "choice" would be a guess, so a unique ledger is created instead.
# ---------------------------------------------------------------------------
#: Strictly GREATER than this share of the acquisition's descriptive
#: keywords must be carried by the winning ledger's name.
_TIE_KEYWORD_FLOOR = 0.75

#: Words describing the DEAL, not the ASSET — they can never identify a
#: ledger ("We buy today Honda Civic for 3,450,000 on cash" → {honda, civic}).
_DESCRIPTIVE_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "by",
    "is", "was", "its", "this", "that", "we", "our", "my", "it", "as",
    "new", "old", "used", "bought", "buy", "buying", "purchase", "purchased",
    "purchases", "acquired", "acquire", "from", "with", "some", "unit",
    "units", "pcs", "pc", "nos", "set", "sets", "one", "two", "three",
    "four", "five", "amount", "worth", "paid", "cash", "credit", "today",
    "yesterday", "tomorrow", "daily", "total", "cost", "price", "pkr", "usd",
})


def descriptive_keywords(text: Any) -> List[str]:
    """Significant, folded words that DESCRIBE *text* (its identity)."""
    words: List[str] = []
    for raw in re.split(r"[^a-z0-9]+", str(text or "").lower()):
        if len(raw) < 3 or raw in _DESCRIPTIVE_STOPWORDS:
            continue
        folded = raw[:-1] if len(raw) > 3 and raw.endswith("s") else raw
        if folded and folded not in words:
            words.append(folded)
    return words


def descriptive_keyword_match(asset_name: Any, ledger_name: Any) -> float:
    """Share (0..1) of the ASSET's descriptive keywords the LEDGER carries.

    Plural-insensitive and prefix-tolerant ("vehicle" ~ "vehicles"),
    deterministic, no model: ``0.0`` means the ledger's name explains
    nothing about this acquisition.
    """
    wanted = descriptive_keywords(asset_name)
    if not wanted:
        return 0.0
    have = set(descriptive_keywords(ledger_name))
    if not have:
        return 0.0
    hits = 0
    for w in wanted:
        for h in have:
            if w == h or (
                len(w) >= 4 and len(h) >= 4
                and (w.startswith(h) or h.startswith(w))
            ):
                hits += 1
                break
    return hits / len(wanted)


def _category_regex_only(text: Any) -> Optional[str]:
    """The category a name LITERALLY matches — never the fuzzy fallback.

    Ledger CANDIDACY must be literal.  ``category_for_item``'s
    nearest-vocabulary fallback exists for the user's ITEM wording
    ("vhecle" → Vehicles); applied to ACCOUNT NAMES it mapped
    "accounts receivable" and "alpha associates" onto "Vehicles".
    """
    low = str(text or "").strip().lower()
    if not low:
        return None
    for pattern, category in _ITEM_CATEGORY_RULES:
        if re.search(pattern, low):
            return category
    return None


def category_for_item(text: Any) -> str:
    """The CATEGORY ledger an item belongs to (never the item's own name).

    Matched exactly first, then by the GENERAL nearest-vocabulary rule
    (``best_class_match``): "vhecle"/"vehical"/"lapotp" land on the category
    they are nearest to, so a misspelling — any misspelling — never silently
    moves an item into the generic bucket.
    """
    low = str(text or "").strip().lower()
    if not low:
        return "Other Equipment & Fixtures"
    for pattern, category in _ITEM_CATEGORY_RULES:
        if re.search(pattern, low):
            return category
    from app.reasoning import best_class_match

    matched = best_class_match(
        low, {category: pattern for pattern, category in _ITEM_CATEGORY_RULES}
    )
    return matched or "Other Equipment & Fixtures"


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


def gap_for_nature(
    name: str, nature: Optional[str], source: str
) -> Optional[AccountGap]:
    """Shape-backed gap, or ``None`` when the treatment has no determined shape.

    Wave A (AUDIT_REPORT §3.1): an unknown treatment is a REJECTION, not an
    expense.  ``None`` means no gap is proposed here — the run falls through to
    its normal ask/FAILED path instead of inventing a 6100 ledger.
    """
    try:
        at, nb, code, ifrs = account_shape(nature)
    except InvalidAccountingNature:
        log.warning(
            "account_resolution.unsupported_treatment",
            name=str(name)[:80],
            nature=str(nature)[:40],
            source=source,
        )
        return None
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
    """A planned call pins the account (by id OR by name) → resolved itself."""
    for tc in tool_calls or []:
        args = getattr(tc, "arguments", None) or {}
        if args.get("asset_account_name"):
            # Pinned by exact name: the service resolves the ledger by name
            # (it will exist — this plan creates it or the user confirmed it),
            # so no nature probe may propose a DIFFERENT ledger on top.
            return True
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


# ---------------------------------------------------------------------------
# FIXED-ASSET LEDGER INTELLIGENCE (plan time — deterministic)
# ---------------------------------------------------------------------------
# Production 2026-10-03, "Record a purchase of Building @ Model Town for
# 35,000,000 on Cash": the plan carried NO account, the tool's keyword match
# was ambiguous ("Computer Equipment" + "Vehicle - Car"), the approved turn
# skipped the probes and the ladder was exhausted — the run died with "No
# fixed-asset account could be determined for this acquisition."  The fix is
# DECISION, not rescue: read the fixed-asset ledgers ONCE at plan time and
# pin the call — reuse a fitting ledger, segregate a unique asset into its
# OWN ledger, create the missing category, or (only when several existing
# ledgers fit equally) ask.

#: Categories where every asset is unique (property): each parcel gets its
#: OWN ledger with a segregating identifier — "Building - Model Town", later
#: "Building - Johar Town" — so separate buildings are recorded separately.
_SEGREGATED_CATEGORIES = frozenset({"Buildings & Land"})

#: "Building @ Model Town" | "Building - Johar Town" | "Land: Block C" …
#: Intra-word hyphens ("Sialkot-Multan") are NOT separators — the head must
#: be a clean category word for the name to read correctly.
_LEDGER_SEP = re.compile(r"\s*(?:[@|:—–]|(?<!\w)-(?!\w))\s*")


def segregated_asset_ledger_name(asset_name: Any, category: str = "") -> Optional[str]:
    """``"Building @ Model Town"`` → ``"Building - Model Town"``.

    Returns ``None`` when the name carries no identifier after a separator
    ("warehouse", "office chairs") — the caller then falls back to the plain
    category ledger.
    """
    text = " ".join(str(asset_name or "").split())
    if not text:
        return None
    parts = _LEDGER_SEP.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    head, identifier = parts[0].strip(), parts[1].strip()
    if not head or not identifier:
        return None
    # The head must LOOK like the category it will prefix — never prefix a
    # ledger with a price or a date fragment.
    if len(head) < 3 or head.replace(".", "").isdigit():
        return None
    if category and category in _SEGREGATED_CATEGORIES:
        head_word = head.lower().rstrip("s")
        cat_head = category.split("&")[0].strip().lower().rstrip("s")
        if head_word and cat_head and head_word != cat_head and not (
            cat_head.startswith(head_word) or head_word.startswith(cat_head)
        ):
            return None
    return f"{head} - {identifier}"


@dataclass
class AssetLedgerDecision:
    """What the plan must do about the PPE ledger of ONE acquisition."""

    mode: str = "unresolved"  # reuse | create | ask | unresolved
    category: str = ""
    account_id: Optional[str] = None
    name: Optional[str] = None  # ledger to pin / create / offer
    candidates: List[str] = field(default_factory=list)


def _bucket_category() -> str:
    """The catch-all category — fits-scanning it would match Cash/Bank."""
    return category_for_item("zzz unknown item")


async def decide_fixed_asset_ledger(
    organization_id: uuid.UUID, *, asset_name: Any
) -> AssetLedgerDecision:
    """Reuse → segregate → create → ask, from ONE reading of the chart.

    Deterministic (the fast path never reaches an LLM): an existing ledger of
    the SAME category is reused — never a second COA entry — a unique asset
    (a building identified by its location) is segregated into its own
    ``<Head> - <Identifier>`` ledger, a missing category is proposed for
    creation, and only a genuine TIE between two fitting existing ledgers
    becomes an ask.
    """
    name = str(asset_name or "").strip()
    if not name:
        return AssetLedgerDecision(mode="unresolved")
    category = category_for_item(name)
    try:
        from app.repositories import account_repository as a_repo

        chart = await a_repo.get_chart_of_accounts(
            organization_id, account_type="ASSET", limit=100
        )
    except Exception as exc:  # noqa: BLE001 — fail open: old paths remain
        log.warning("account_resolution.ledger_decision_chart_failed",
                    error=str(exc)[:200])
        return AssetLedgerDecision(mode="unresolved", category=category)

    def _key(value: Any) -> str:
        return str(value or "").strip().lower()

    # Only genuine PPE-candidate ledgers may be reused or counted as a TIE.
    # Party sub-ledgers (children of a receivable/payable control account) and
    # current-asset / settlement / tax / contra accounts are structurally
    # excluded — never a lexical guess, and never by name alone.
    chart_rows = list(chart or [])
    by_id = {str(a.get("id") or ""): a for a in chart_rows}
    rows = [
        a for a in chart_rows
        if is_ppe_ledger_candidate(a, by_id=by_id)
    ]

    def _exact(ledger_name: str) -> Optional[Dict[str, Any]]:
        wanted = _key(ledger_name)
        for row in rows:
            if _key(row.get("name")) == wanted:
                return row
        return None

    def _reuse(row: Dict[str, Any]) -> AssetLedgerDecision:
        return AssetLedgerDecision(
            mode="reuse", category=category,
            account_id=str(row.get("id") or "") or None,
            name=str(row.get("name") or ""),
        )

    # 1) This exact asset already has its own ledger → reuse it (a repeat
    #    purchase for the same building posts to the SAME ledger).
    segregated = segregated_asset_ledger_name(name, category)
    if segregated:
        row = _exact(segregated)
        if row:
            return _reuse(row)

    # 2) Unique categories: EVERY parcel keeps its own ledger.
    if category in _SEGREGATED_CATEGORIES:
        target = segregated or category
        row = _exact(target)
        if row:
            return _reuse(row)
        return AssetLedgerDecision(mode="create", category=category, name=target)

    # 3) The category ledger itself already exists → reuse it.
    row = _exact(category)
    if row:
        return _reuse(row)

    # 4) Same-category ledgers under other names: exactly one fits → reuse
    #    it; several fit → only a descriptive match STRICTLY better than 75%
    #    may choose between them, otherwise a UNIQUE ledger is created in this
    #    category; none fit → create.
    if category != _bucket_category():
        # LITERAL match only: the fuzzy nearest-vocabulary fallback is for the
        # user's ITEM wording ("vhecle" → Vehicles).  Applied to ACCOUNT NAMES
        # it made "accounts receivable" / "alpha associates" fit "Vehicles",
        # inventing a multi-way tie that left the plan with no ledger.
        fits = [
            a for a in rows
            if _category_regex_only(a.get("name")) == category
        ]
        if len(fits) == 1:
            return _reuse(fits[0])
        if len(fits) > 1:
            # 2+ PPE ledgers in the SAME category.  The acquisition's own
            # descriptive keywords must EXPLAIN a ledger (>75% of them) —
            # otherwise choosing one would be a guess.
            best_score, best = max(
                (
                    (descriptive_keyword_match(name, a.get("name")), a)
                    for a in fits
                ),
                key=lambda pair: pair[0],
            )
            if best_score > _TIE_KEYWORD_FLOOR:
                return _reuse(best)
            # Nothing explains this acquisition well enough → create a UNIQUE
            # ledger in this category.  Step 3 proved no ledger is named
            # exactly `category`, so the new one cannot collide, and every
            # later acquisition in the category then reuses it.
            return AssetLedgerDecision(mode="create", category=category, name=category)

    # 5) Nothing fits → the category ledger must be created first.
    return AssetLedgerDecision(mode="create", category=category, name=category)


async def pin_planned_asset_accounts(
    organization_id: uuid.UUID,
    *,
    tool_calls: Optional[Sequence[Any]],
    entities: Optional[Mapping[str, Any]] = None,
) -> Optional[AccountGap]:
    """Pin every planned ``register_fixed_asset`` call to a decided ledger.

    The call gets EXACTLY ONE of:

    * ``asset_account_id``   — a fitting existing ledger was found;
    * ``asset_account_name`` — a ledger will exist by execution time (this
      plan creates it, or the user confirmed a name).

    Returns the creation/choice GAP the prerequisite/ask flow must handle,
    or ``None`` when the plan is already executable.  Runs on EVERY path —
    deterministic fast path, model plan and approved-plan replay — before
    the confirmation snapshot, so the user never approves a transaction
    that cannot post.
    """
    ents = dict(entities or {})
    confirmed = str(
        ents.get("create_account") or ents.get("account_name") or ""
    ).strip()
    gap: Optional[AccountGap] = None
    for tc in tool_calls or ():
        if str(getattr(tc, "tool_name", "")) != "register_fixed_asset":
            continue
        args = getattr(tc, "arguments", None)
        if not isinstance(args, dict):
            continue
        if args.get("asset_account_id") or args.get("asset_account_name"):
            continue  # already pinned (by the model or a previous turn)
        asset_name = str(
            args.get("name") or ents.get("asset_name") or ""
        ).strip()
        if confirmed:
            # The user's own answer is ground truth (merge contract): pin it
            # and let the planner's confirmed create_account run first.
            args["asset_account_name"] = confirmed
            continue
        decision = await decide_fixed_asset_ledger(
            organization_id, asset_name=asset_name
        )
        if decision.mode == "reuse" and decision.account_id:
            args["asset_account_id"] = decision.account_id
        elif decision.mode in ("create", "ask") and decision.name:
            if decision.mode == "create":
                args["asset_account_name"] = decision.name
            proposed = gap_for_nature(
                decision.name, "FIXED_ASSET", "fixed_asset_nature"
            )
            if proposed is not None:
                proposed.candidates = list(decision.candidates)
                gap = gap or proposed
        # unresolved → leave the call alone; the service's own resolution
        # and the existing ask/rescue paths behave exactly as before.
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
