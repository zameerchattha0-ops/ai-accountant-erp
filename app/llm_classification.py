"""
LLM DECISION LAYER — transaction classification (nature + account routing)
==========================================================================
WHY THIS EXISTS: the deterministic classifier decided by keyword rules and
search-TERM ORDER — production incident: a motorbike purchase was debited
to 1500 Computer Equipment because "computer equipment" was simply the
FIRST search term that matched the chart. That is string matching, not
accounting judgment. Every decision that requires REASONING — income vs
expense, asset vs liability, capitalise vs expense, and WHICH ledger
receives the posting — belongs to the LLM.

THE SPLIT OF RESPONSIBILITY (never blurred):

    LLM      - DECIDES the economic nature and the CORRECT TREATMENT:
               which existing ledger receives the posting (exact fit, or
               a near-relevant one only after the user agrees), or what
               child account to create under which parent heading when
               nothing in the chart fits.
    Python   — GATHERS the candidates (live chart of accounts), VALIDATES
               every decision against accounting invariants (candidate
               exists, is active, non-contra, account_type fits the
               nature, normal_balance consistent), and EXECUTES it.
               Anything invalid/unreachable/unparseable returns ``None``
               -> the caller falls back to the deterministic chain — a
               fallback, never a guess the engine would reject.

FIXED CONTRACT — the model replies ONLY with this JSON shape (the same
embeddable-format philosophy as app/questionnaire.py):

    {"nature": "<vocabulary>", "fit": "EXACT|RELATED|NONE",
     "account_id": "<candidate id or null>",
     "confidence": "HIGH|MEDIUM|LOW", "needs_clarification": true|false,
     "question": "", "options": [],
     "propose_account": {"name","code","account_type","parent_code"} or null,
     "rationale": "<one sentence>"}

THE TREATMENT LADDER (what fit MEANS - the CORRECT ACCOUNTING TREATMENT,
not merely "a ledger from the chart"):

    EXACT   - a dedicated account for this treatment exists -> pick it
              and post (no interruption).
    RELATED - a relevant but NOT dedicated account exists -> pick it with
              fit=RELATED: the user is INFORMED first ("closest existing:
              X - use it, or create a dedicated one?") and the pick only
              posts after they agree; a REFUSAL (or no relevant account at
              all: fit=NONE) confirms the creation proposal — the dedicated
              child under its heading — never a silent re-pick.
    NONE    - nothing relevant exists -> account_id null +
              propose_account: the right child account WITH its
              parent_code heading, so the entry lands segregated under
              the correct statement section (PPE / Operating Expenses /
              Liabilities ...), never posted to a wrong-segregation head.

parent_code is validated against the chart's HEADINGS: it must exist and
its account_type must fit the proposed ledger; an invalid parent drops the
whole proposal (a child in the wrong section is worse than no child).

Facts stated by the user (``nature_hint``) are AUTHORITATIVE: the hint is
forced over the model's ``nature`` and the account is re-validated against
IT — a model contradicting a user-stated fact is rejected, not honoured.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from app.models.schemas import TransactionClassification
from app.questionnaire import _extract_json  # ONE parser for fixed formats

log = structlog.get_logger(__name__)

# Nature vocabulary the decision layer may return. The three
# balance-statement additions are what make "income vs expense" and
# "asset vs liability" expressible at all — the base 9-value vocabulary
# could only ever answer asset-vs-expense.
from app.classifier import NATURES as _BASE_NATURES  # noqa: E402

DECISION_NATURES: frozenset = frozenset(
    set(_BASE_NATURES) | {"REVENUE", "LIABILITY", "EQUITY"}
)

# nature -> account_types that may legally carry a posting for it.
_NATURE_ACCOUNT_TYPES: Dict[str, frozenset] = {
    "INVENTORY": frozenset({"ASSET"}),
    "FIXED_ASSET": frozenset({"ASSET"}),
    "INTANGIBLE_ASSET": frozenset({"ASSET"}),
    "PREPAYMENT": frozenset({"ASSET"}),
    "DEPOSIT_ADVANCE": frozenset({"ASSET"}),
    "OPERATING_EXPENSE": frozenset({"EXPENSE"}),
    "CONSUMABLE": frozenset({"EXPENSE"}),
    "SERVICE": frozenset({"EXPENSE"}),
    "REVENUE": frozenset({"REVENUE"}),
    "LIABILITY": frozenset({"LIABILITY"}),
    "EQUITY": frozenset({"EQUITY"}),
    # OTHER is the deliberate escape hatch — any posting type allowed,
    # still subject to existence/activity/contra validation.
    "OTHER": frozenset({"ASSET", "EXPENSE", "REVENUE", "LIABILITY", "EQUITY"}),
}

_VALID_ACCOUNT_TYPES = frozenset(
    {"ASSET", "EXPENSE", "REVENUE", "LIABILITY", "EQUITY"}
)

# normal_balance is CHECK-constrained in the DB (migration 005):
_TYPE_NORMAL_BALANCE = {
    "ASSET": "DEBIT",
    "EXPENSE": "DEBIT",
    "REVENUE": "CREDIT",
    "LIABILITY": "CREDIT",
    "EQUITY": "CREDIT",
}

# Party sub-ledgers (1100-0001, 2010-0005 …) are per-counterparty books the
# classifier must never route a category posting into; they are resolved by
# the party-ledger services, not by nature.
_PARTY_SUBLEDGER_CODE = re.compile(r"^\d{4}-\d+")

# Cap so a 500-row chart (incl. every party ledger) cannot blow the prompt.
_MAX_CANDIDATES = 150



_NATURE_DEFS = """\
- INVENTORY: goods held FOR RESALE (stock you sell again).
- FIXED_ASSET: long-lived property/equipment held for USE (vehicle,
  machinery, building, computer equipment).
- INTANGIBLE_ASSET: software/licences/patents.
- PREPAYMENT / DEPOSIT_ADVANCE: cash paid BEFORE the benefit is received.
- OPERATING_EXPENSE / CONSUMABLE / SERVICE: costs of THIS period.
- REVENUE: income EARNED (income statement credit).
- LIABILITY: amounts the business OWES and must repay.
- EQUITY: the owner's claim on the business.
- OTHER: only when nothing above fits (explain in rationale).

DECISION RULES:
* INCOME vs EXPENSE: money the business EARNED -> REVENUE; money it SPENT
  for operations -> EXPENSE (or an asset if the benefit lasts on).
* ASSET vs LIABILITY: something the business OWNS/will use -> ASSET;
  something it OWS/will repay -> LIABILITY.
* CAPITALISE vs EXPENSE: a long-lived item for use -> FIXED_ASSET
  (account_type ASSET); a consumable/service of this period -> EXPENSE.
* account_id MUST be copied verbatim from CANDIDATES — never invent one.
* account_type of the pick must FIT the chosen nature (see vocabulary).
* fit decides the treatment:
  - EXACT: a DEDICATED account for this treatment exists -> pick it,
    fit="EXACT", needs_clarification=false (post directly).
  - RELATED: a relevant but NOT dedicated account exists -> pick it with
    fit="RELATED", AND give propose_account (the dedicated child to create
    instead): the user is informed first and the pick posts ONLY after
    they agree.
  - NONE: nothing relevant -> fit="NONE", account_id null, propose_account.
* needs_clarification=true ONLY when a material fact is genuinely missing
  AND no candidate fits — then ask exactly ONE plain-text question.
* propose_account ONLY when the right ledger does not exist in the chart:
  give its canonical name, a free code, the correct account_type, and
  parent_code - the HEADINGS entry the child belongs under (its statement
  section: PPE, Operating Expenses, Liabilities, ...). Omitting
  parent_code while HEADINGS exist drops the proposal.
* Never pick a heading (they only group - they never carry a posting),
  never pick a contra account (accumulated depreciation) or an inactive
  account; never contradict FACTS."""


@dataclass
class CandidateSet:
    """Python-gathered evidence handed to the model (and used to validate)."""

    accounts: List[Dict[str, Any]] = field(default_factory=list)
    # Grouping HEADINGS (accounts that are some account's parent): never
    # posting candidates themselves - offered to the model as the legal
    # parents under which a missing child ledger may be created.
    headings: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def by_id(self) -> Dict[str, Dict[str, Any]]:
        return {str(a.get("id")): a for a in self.accounts}

    @property
    def headings_by_code(self) -> Dict[str, Dict[str, Any]]:
        return {
            str(h.get("code") or ""): h
            for h in self.headings
            if str(h.get("code") or "")
        }

    @property
    def names(self) -> List[str]:
        return [str(a.get("name") or "") for a in self.accounts]


async def gather_candidates(organization_id: uuid.UUID) -> CandidateSet:
    """Fetch the posting-worthy accounts: active, non-contra, non-control,
    non-party-sub-ledger - one DB round-trip, the ONLY one this layer adds.
    Grouping headings are split out into ``headings`` (parents, never posts).
    """
    from app.repositories import account_repository as a_repo

    try:
        rows = await a_repo.get_chart_of_accounts(organization_id, limit=500)
    except Exception as exc:  # noqa: BLE001 — decision layer degrades to rules
        log.warning("llm_classification.candidate_fetch_failed", error=str(exc)[:200])
        return CandidateSet()

    # A grouping HEAD (any row that is some account's parent) never carries
    # a posting - it is offered separately as the PARENT under which the
    # model may create a missing child ledger. Derived from the SAME fetch
    # (the select already carries parent_account_id): no extra DB round-trip.
    parent_ids = {
        str(r.get("parent_account_id"))
        for r in rows or []
        if r.get("parent_account_id")
    }
    keep: List[Dict[str, Any]] = []
    for row in rows or []:
        code = str(row.get("code") or "")
        name = str(row.get("name") or "")
        low = name.lower()
        if not row.get("is_active", True):
            continue
        if row.get("is_control_account"):
            continue  # AR/AP controls resolve via party services, never here
        if "accumulated" in low:
            continue  # contra — must never receive an acquisition posting
        if "depreciation" in low and str(row.get("account_type")) != "EXPENSE":
            continue  # keep "Depreciation Expense", drop accumulated-style contras
        if _PARTY_SUBLEDGER_CODE.match(code):
            continue
        keep.append(row)
    keep.sort(key=lambda r: str(r.get("code") or ""))
    headings = [r for r in keep if str(r.get("id")) in parent_ids]
    postings = [r for r in keep if str(r.get("id")) not in parent_ids]
    return CandidateSet(
        accounts=postings[:_MAX_CANDIDATES],
        headings=sorted(headings, key=lambda r: str(r.get("code") or "")),
    )


def _allowed_account_types(nature: Optional[str]) -> frozenset:
    """Posting types that may legally carry a posting for *nature*.

    An unknown/undecided nature (clarification round) allows any posting
    type — the answer re-validates it.
    """
    if nature is None:
        return frozenset(_VALID_ACCOUNT_TYPES)
    return _NATURE_ACCOUNT_TYPES.get(nature, frozenset(_VALID_ACCOUNT_TYPES))


def build_prompt(
    *,
    intent: str,
    entities: Dict[str, Any],
    message: Optional[str],
    nature_hint: Optional[str],
    candidates: CandidateSet,
    rule_hint: Optional[str] = None,
) -> str:
    """The fixed-format decision request (facts + candidates + contract)."""
    facts = {
        k: v
        for k, v in (entities or {}).items()
        if v not in (None, "", [], {}) and not isinstance(v, (bytes, bytearray))
    }
    lines = [
        "CLASSIFY ONE ACCOUNTING REQUEST — reply with ONLY the JSON contract.",
        "",
        f"INTENT: {intent or 'unknown'}",
        f"USER MESSAGE: {message or '(none)'}",
        f"FACTS: {facts}",
    ]
    if nature_hint:
        lines.append(
            "NATURE HINT (authoritative — user/system stated, "
            f"do NOT contradict): {nature_hint}"
        )
    if rule_hint:
        lines.append(f"DETERMINISTIC HINT (advisory only): {rule_hint}")
    lines += [
        "",
        "NATURE VOCABULARY:",
        _NATURE_DEFS,
        "",
        "CANDIDATES (id | code | name | account_type) — pick at most one:",
    ]
    lines += [
        f"{a.get('id')} | {a.get('code')} | {a.get('name')} | {a.get('account_type')}"
        for a in candidates.accounts
    ]
    if candidates.headings:
        lines += [
            "",
            "HEADINGS (code | name | account_type) - grouping accounts: NEVER",
            "post to a heading, but propose_account.parent_code MUST name the",
            "heading the new account belongs under (its statement section):",
        ]
        lines += [
            f"{h.get('code')} | {h.get('name')} | {h.get('account_type')}"
            for h in candidates.headings[:60]
        ]
    lines += [
        "",
        "REPLY WITH ONLY THIS JSON (no markdown, no prose):",
        '{"nature": "<vocabulary value>", "fit": "EXACT|RELATED|NONE",',
        ' "account_id": "<candidate id or null>",',
        ' "confidence": "HIGH|MEDIUM|LOW", "needs_clarification": false,',
        ' "question": "", "options": [],',
        ' "propose_account": {"name":"","code":"","account_type":"",',
        '                     "parent_code":""} or null,',
        ' "rationale": "<one sentence>"}',
    ]
    return "\n".join(lines)


def _clean_line(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[*`#]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]



def _treatment_question(
    *,
    proposed_name: str,
    proposed_code: Optional[str],
    parent_name: Optional[str],
    related_name: Optional[str] = None,
    related_code: Optional[str] = None,
) -> str:
    """The account-treatment confirmation question.

    TEXT CONTRACT with planner ``_merge_clarification_answers`` - the round
    only routes when these phrases survive verbatim:
      * "should i create" - a YES answer folds the quoted name into
        ``entities["create_account"]``;
      * ``no '<name>' account`` - the regex the YES arm extracts the name
        from (apostrophes are stripped so extraction stays exact);
      * ``under '<head>'`` - the parent heading, extracted into
        ``entities["create_parent_name"]`` so the confirmed create_account
        lands the child under the right statement section.
    A "use ..." answer names an existing account instead
    (``entities["account_name"]``), which the classifier pins as the
    USER_ANSWER posting hint - informed consent closes both legs.
    """
    name = str(proposed_name or "").replace("'", "").strip()
    head = str(parent_name or "").replace("'", "").strip()
    rel = str(related_name or "").replace("'", "").strip()
    text = f"There is no '{name}' account in your chart of accounts"
    if rel:
        text += (
            f" — the closest existing is '{rel}'"
            + (f" ({related_code})" if related_code else "")
        )
    if proposed_code:
        text += f" (suggested code {proposed_code})"
    text += ". Should I create it"
    if head:
        text += f" under '{head}'"
    text += ", or use an existing account instead?"
    return text


def validate(
    payload: Any,
    *,
    candidates: CandidateSet,
    nature_hint: Optional[str] = None,
    entity: Optional[str] = None,
) -> Optional[TransactionClassification]:
    """Validate a model payload against the invariants → classification.

    Returns ``None`` (never a partial/invalid decision) on ANY violation:
    the caller then falls back to the deterministic chain.
    """
    if not isinstance(payload, dict):
        return None

    # --- fit: HOW WELL the picked account serves the treatment ----------
    # EXACT = the dedicated ledger exists -> post.  RELATED = a relevant
    # but NOT dedicated ledger exists -> the user must be INFORMED first
    # (forced clarification below).  NONE = nothing relevant -> propose the
    # right child under the correct heading.  An omitted fit defaults to
    # EXACT-with-a-pick / NONE-without, the shape pre-fit replies used.
    raw_fit = str(payload.get("fit") or "").strip().upper()
    if raw_fit and raw_fit not in ("EXACT", "RELATED", "NONE"):
        log.warning("llm_classification.reject", reason="unknown fit", raw=raw_fit)
        return None

    # --- nature (fact hint wins outright) -------------------------------
    raw_nature = str(payload.get("nature") or "").strip().upper()
    nature: Optional[str]
    if nature_hint:
        nature = str(nature_hint).strip().upper()
    elif raw_nature in DECISION_NATURES:
        nature = raw_nature
    elif raw_nature in ("", "NONE", "UNKNOWN"):
        # An UNDECIDED nature is only legal when the model is ASKING —
        # the same shape the deterministic INFERENCE branch returns.
        nature = None
    else:
        log.warning("llm_classification.reject", reason="unknown nature", raw=raw_nature)
        return None

    clarify = bool(payload.get("needs_clarification"))
    question = _clean_line(payload.get("question"), 300)
    # (A clarify WITHOUT a question is rejected after the fit/proposal
    #  rounds below, where the contract question may still be generated.)
    if nature is None and not clarify:
        log.warning("llm_classification.reject", reason="no nature, not asking")
        return None

    # --- account proposal (missing ledger) + its PARENT heading ---------
    proposal = payload.get("propose_account")
    proposed_name = proposed_code = None
    proposed_parent_id: Optional[str] = None
    proposed_parent_name: Optional[str] = None
    if isinstance(proposal, dict):
        proposed_name = _clean_line(proposal.get("name"), 60)
        proposed_code = str(proposal.get("code") or "").strip() or None
        p_type = str(proposal.get("account_type") or "").strip().upper()
        parent_code = str(proposal.get("parent_code") or "").strip() or None
        if not proposed_name:
            proposal = None
        elif p_type not in _allowed_account_types(nature):
            # The proposed ledger's type must fit the decided nature.
            log.warning(
                "llm_classification.reject",
                reason="proposed account_type does not fit nature",
                nature=nature, account_type=p_type,
            )
            proposal = None
        if proposal is not None and proposed_code and not re.fullmatch(
            r"\d{2,6}", proposed_code
        ):
            proposed_code = None
        if proposal is not None:
            # PARENT PLACEMENT (segregation of statement heads): the child
            # must land under a REAL chart heading of its own section.
            if parent_code is None and candidates.headings:
                log.warning(
                    "llm_classification.reject",
                    reason="proposal without parent_code while headings exist",
                    proposed=proposed_name,
                )
                proposal = None
            elif parent_code:
                parent = candidates.headings_by_code.get(parent_code)
                if parent is None:
                    log.warning(
                        "llm_classification.reject",
                        reason="parent_code is not a chart heading",
                        parent_code=parent_code,
                    )
                    proposal = None
                elif str(parent.get("account_type") or "").upper() != p_type:
                    # Wrong statement section (an EXPENSE child under an
                    # ASSET head) would mis-segregate the balance sheet.
                    log.warning(
                        "llm_classification.reject",
                        reason="parent section does not fit proposal",
                        parent_code=parent_code, account_type=p_type,
                    )
                    proposal = None
                else:
                    proposed_parent_id = str(parent.get("id"))
                    proposed_parent_name = (
                        str(parent.get("name") or "").strip() or None
                    )
        if proposal is None:
            # A dropped proposal drops its name/code too — the
            # classification must never advertise a rejected ledger.
            proposed_name = proposed_code = None
            proposed_parent_id = proposed_parent_name = None

    # --- account pick ---------------------------------------------------
    account: Optional[Dict[str, Any]] = None
    account_id = payload.get("account_id")
    if account_id not in (None, "", "null"):
        account = candidates.by_id.get(str(account_id))
        if account is None:
            log.warning(
                "llm_classification.reject",
                reason="account_id not in candidate set", account_id=str(account_id),
            )
            return None
        a_type = str(account.get("account_type") or "").strip().upper()
        if a_type not in _allowed_account_types(nature):
            log.warning(
                "llm_classification.reject",
                reason="account_type does not fit nature",
                nature=nature, account_type=a_type,
                account=str(account.get("name")),
            )
            return None
        expected_balance = _TYPE_NORMAL_BALANCE.get(a_type)
        actual_balance = str(account.get("normal_balance") or "").upper()
        if expected_balance and actual_balance and actual_balance != expected_balance:
            log.warning(
                "llm_classification.reject",
                reason="normal_balance inconsistent with account_type",
                account_type=a_type, normal_balance=actual_balance,
            )
            return None


    # --- fit semantics: EXACT posts, RELATED informs first, NONE proposes -
    fit = raw_fit or ("EXACT" if account is not None else "NONE")
    if fit == "NONE" and account is not None:
        log.warning(
            "llm_classification.reject",
            reason="fit NONE contradicts a picked account",
            account=str(account.get("name")),
        )
        return None
    if fit == "RELATED" and account is None:
        log.warning(
            "llm_classification.reject", reason="fit RELATED without an account"
        )
        return None
    if fit == "RELATED":
        # INFORMED CONSENT: a relevant-but-not-exact ledger is NEVER posted
        # to silently.  The round offers both legs of the owner's directive:
        # use the near-relevant account, or create the dedicated child under
        # its heading (the proposal is mandatory so "create" stays answerable).
        if proposal is None:
            log.warning(
                "llm_classification.reject",
                reason="RELATED without a create proposal",
            )
            return None
        if question:
            log.info(
                "llm_classification.model_question_superseded", question=question
            )
        clarify = True
        question = _treatment_question(
            proposed_name=proposed_name,
            proposed_code=proposed_code,
            parent_name=proposed_parent_name,
            related_name=str(account.get("name") or ""),
            related_code=str(account.get("code") or ""),
        )
    elif proposal is not None:
        # The creation round ALWAYS uses the contract question: the planner
        # answer-merge keys on "should i create" + no '<name>' account, so a
        # model-phrased question would break YES -> create routing.
        if question:
            log.info(
                "llm_classification.model_question_superseded", question=question
            )
        clarify = True
        question = _treatment_question(
            proposed_name=proposed_name,
            proposed_code=proposed_code,
            parent_name=proposed_parent_name,
        )
    if clarify and not question:
        log.warning("llm_classification.reject", reason="clarify without question")
        return None

    # A decision must DO something: route, ask, or propose.
    if account is None and not clarify and proposal is None:
        log.warning("llm_classification.reject", reason="decision does nothing")
        return None

    # --- offered options (existing candidate names only) ----------------
    options: List[str] = []
    if clarify:
        valid_names = set(candidates.names)
        for opt in payload.get("options") or []:
            name = _clean_line(opt, 60)
            if name and name in valid_names and name not in options:
                options.append(name)
            if len(options) >= 4:
                break
        if fit == "RELATED" and account is not None:
            # The near-relevant account is always the FIRST offer: using it
            # is the user's first-choice leg; creation stays the second.
            _rel = str(account.get("name") or "")
            if _rel and _rel not in options:
                options.insert(0, _rel)
            options = options[:4]

    confidence = str(payload.get("confidence") or "MEDIUM").strip().upper()
    if confidence not in ("HIGH", "MEDIUM", "LOW"):
        confidence = "MEDIUM"

    if clarify:
        reason = question
        if options:
            reason += " Existing options: " + ", ".join(options) + "."
        return TransactionClassification(
            transaction_nature=nature,
            confidence=confidence,
            source="LLM_DECISION",
            entity=entity,
            account_hint_id=str(account.get("id")) if account else None,
            account_hint_code=str(account.get("code")) if account else None,
            account_hint_name=str(account.get("name")) if account else None,
            candidate_accounts=options or None,
            proposed_account_name=proposed_name,
            proposed_account_code=proposed_code,
            proposed_parent_id=proposed_parent_id,
            proposed_parent_name=proposed_parent_name,
            requires_clarification=True,
            clarification_reason=reason,
        )

    # No proposal can reach here: a proposal ALWAYS forced the clarify
    # round above (both legs — RELATED's and NONE's — are answer rounds).
    return TransactionClassification(
        transaction_nature=nature,
        confidence=confidence,
        source="LLM_DECISION",
        entity=entity,
        account_hint_id=str(account.get("id")) if account else None,
        account_hint_code=str(account.get("code")) if account else None,
        account_hint_name=str(account.get("name")) if account else None,
        proposed_account_name=proposed_name,
        proposed_account_code=proposed_code,
        proposed_parent_id=proposed_parent_id,
        proposed_parent_name=proposed_parent_name,
        requires_clarification=False,
        clarification_reason=None,
    )



async def decide(
    *,
    organization_id: uuid.UUID,
    intent: str,
    entities: Dict[str, Any],
    message: Optional[str] = None,
    nature_hint: Optional[str] = None,
    client: Any = None,
    timeout: Optional[float] = None,
) -> Optional[TransactionClassification]:
    """The full decision round-trip.

    NEVER raises except AssertionError (test no-LLM guards stay loud);
    ANY other failure returns ``None`` → deterministic fallback in the
    caller. Returns None immediately when the layer is disabled.
    """
    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "llm_classification_enabled", False):
        return None
    candidates: CandidateSet = CandidateSet()
    try:
        candidates = await gather_candidates(organization_id)
        if not candidates.accounts:
            return None  # nothing to choose from → rules decide
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()
        rule_hint = None
        try:
            from app.classifier import rule_based_nature

            text = " ".join(
                str(x) for x in (
                    entities.get("item_description"),
                    entities.get("description"),
                    message,
                ) if x
            )
            hint_nature, hint_conf = rule_based_nature(text, entities)
            if hint_nature:
                rule_hint = f"{hint_nature} (confidence {hint_conf})"
        except Exception:  # noqa: BLE001 — advisory only
            rule_hint = None

        prompt = build_prompt(
            intent=intent, entities=entities, message=message,
            nature_hint=nature_hint, candidates=candidates, rule_hint=rule_hint,
        )
        raw = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt),
            timeout=timeout or getattr(settings, "llm_classification_timeout", 15.0),
        )
    except AssertionError:
        raise  # a test's no-LLM guard must never be swallowed
    except Exception as exc:  # noqa: BLE001 — degrade to the rule chain
        log.warning("llm_classification.unavailable", error=str(exc)[:200])
        return None

    payload = _extract_json(str(raw or ""))
    if not payload:
        log.warning("llm_classification.reject", reason="unparseable reply")
        return None
    entity = (
        entities.get("item_description")
        or entities.get("description")
        or entities.get("entity_name")
    )
    return validate(
        payload,
        candidates=candidates,
        nature_hint=nature_hint,
        entity=str(entity) if entity else None,
    )

