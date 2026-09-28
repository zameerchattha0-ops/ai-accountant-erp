"""Two-Call LLM Contracts — Stage 1 foundation (infrastructure only).

    CALL 1 = Semantic Intake     -> SemanticIntakeResponse    (Contract A)
    CALL 2 = Accounting Decision -> AccountingDecisionResponse (Contract B)

STAGE 1 SCOPE (Two-Call Design Report, Stage 1 / AUDIT_REPORT §5)
--------------------------------------------------------------
This module is PURE: no I/O, no LLM, no database — same rule as
``app/semantic_contract.py``.  It defines the two role contracts, their
parsers and their validators, plus a projection helper that records whether an
EXISTING monolithic reasoning response could be represented by either role.

**Neither contract is authoritative.**  The monolithic reasoning contract
(``accounting_reasoning._RESPONSE_SHAPE``) remains the only runtime contract;
nothing in this module feeds ``execution_plan.intent``; no runtime path calls
these functions yet.  Wave A/B/C/D authority work is untouched.

Boundary rules enforced here (design report §C–§E):

* Contract A carries ONLY semantic-intake concerns.  It may never carry
  decision/intent/treatment/ledger/prerequisites/proposal/journal/debit/
  credit/accounting impact; unknown top-level fields fail validation.
* Contract B carries ONLY accounting-decision concerns.  It may never carry
  facts/question/questionnaire/evidence_requests as top-level fields;
  unknown top-level fields fail validation.
* Adaptive question authoring belongs to CALL 1 alone.  ``B.needs[]`` states
  *requirements* (EVIDENCE / USER_FACT / CONFIG_PERIOD) — it never authors a
  user-facing question and never names one of its own ``decision`` fields as
  the thing the user must supply.
* ``understanding.event_type`` is a surface event class only.  Accounting
  intent is a CALL 2 decision: no function here derives intent from an event
  type, and a proposal without an explicit canonical ``decision.intent`` is
  rejected.

Vocabulary is REUSED, never forked:

* fact states        -> ``semantic_contract`` (EXPLICIT / SAFELY_INFERRED /
                         AMBIGUOUS / MISSING; no new state, no ``ASSUMED``)
* event_type set     -> keys of ``accounting_vocabulary.EVENT_TYPE_INTENT_COVERAGE``
                         (coverage = which intents *can represent* an event;
                         it documents representability, never derivation)
* intents            -> ``accounting_vocabulary.CANONICAL_INTENTS`` / ``is_canonical_intent``
* document_nature    -> ``accounting_vocabulary.DOCUMENT_NATURES`` (Axis A)
* treatment          -> ``accounting_vocabulary.TREATMENTS`` (Axis B|C)
* activities/terms   -> ``semantic_contract.ACTIVITIES`` / ``PAYMENT_METHODS``
* evidence requests  -> ``books_evidence.validate_evidence_request`` (closed
                         catalogue, arg shapes)
* proposal fields    -> ``accounting_reasoning.REQUIRED_PROPOSAL_FIELDS``
* JSON extraction    -> ``accounting_reasoning.parse_reasoning_response``
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, TypedDict

from app.accounting_reasoning import (
    REQUIRED_PROPOSAL_FIELDS,
    parse_reasoning_response,
)
from app.accounting_vocabulary import (
    DOCUMENT_NATURES,
    EVENT_TYPE_INTENT_COVERAGE,
    TREATMENTS,
    is_canonical_intent,
    is_document_nature,
)
from app.books_evidence import (
    EvidenceRequest,
    validate_evidence_request,
)
from app.semantic_contract import (
    ACTIVITIES,
    PAYMENT_METHODS,
    RESOLVED_STATES,
    UNRESOLVED_STATES,
)

__all__ = [
    "SemanticIntakeResponse",
    "AccountingDecisionResponse",
    "parse_semantic_intake_response",
    "validate_semantic_intake_response",
    "parse_accounting_decision_response",
    "validate_accounting_decision_response",
    "observe_two_call_representation",
    "CALL1_FIELDS",
    "CALL1_FORBIDDEN",
    "CALL2_FIELDS",
    "CALL2_FORBIDDEN",
    "NEED_KINDS",
]

# ---------------------------------------------------------------------------
# Contract field sets (closed — unknown top-level fields fail validation)
# ---------------------------------------------------------------------------

#: The complete semantic-intake surface (Contract A).
CALL1_FIELDS: FrozenSet[str] = frozenset(
    {
        "understanding",
        "facts",
        "missing_material_facts",
        "questionnaire",
        "evidence_requests",
    }
)

#: Fields Contract A must never carry (accounting decisions, plan structure,
#: journal mechanics, and Contract B's envelope fields).
CALL1_FORBIDDEN: FrozenSet[str] = frozenset(
    {
        "decision",
        "intent",
        "treatment",
        "ledger",
        "prerequisites",
        "proposal",
        "rationale",
        "refusal",
        "complete",
        "needs",
        "journal",
        "debit",
        "credit",
        "accounting_impact",
    }
)

#: The complete accounting-decision surface (Contract B).
CALL2_FIELDS: FrozenSet[str] = frozenset(
    {
        "decision",
        "prerequisites",
        "proposal",
        "rationale",
        "refusal",
        "complete",
        "needs",
    }
)

#: Contract B must never carry the semantic-intake surface (questionnaire
#: authoring and fact ownership stay with CALL 1).
CALL2_FORBIDDEN: FrozenSet[str] = frozenset(
    {"facts", "question", "questionnaire", "evidence_requests"}
)

#: Contract B: ``decision`` sub-field vocabulary (audit §5 v2 field set).
CALL2_DECISION_FIELDS: FrozenSet[str] = frozenset(
    {
        "intent",
        "activity",
        "document_nature",
        "treatment",
        "payment_terms",
        "ledger",
        "confidence",
    }
)

#: Contract A: ``understanding`` sub-field vocabulary (existing contract).
CALL1_UNDERSTANDING_FIELDS: FrozenSet[str] = frozenset(
    {"economic_event", "what_user_wants", "basis", "event_type"}
)

#: The event_type enum — single source is the existing coverage table; its
#: keys are exactly the values the reasoning contract offers.  Coverage says
#: which canonical intents CAN represent an event; it never derives one.
EVENT_TYPES: FrozenSet[str] = frozenset(EVENT_TYPE_INTENT_COVERAGE)

#: Contract A fact entry fields (existing semantic contract shape + state).
CALL1_FACT_FIELDS: FrozenSet[str] = frozenset({"name", "value", "state", "evidence"})

#: Contract A missing-material-fact entry fields — compatibility layer over
#: the existing contract spelling (``fact`` / ``why_material`` / ``question``)
#: and the design-report spelling (``name`` / ``why_required`` / ``state`` /
#: ``candidates``).  Vocabulary NOT changed: only the four existing states.
CALL1_MISSING_FIELDS: FrozenSet[str] = frozenset(
    {"fact", "name", "why_material", "why_required", "state", "candidates", "question"}
)

#: Contract A questionnaire block (existing contract shape).
CALL1_QUESTIONNAIRE_FIELDS: FrozenSet[str] = frozenset({"text", "questions"})
CALL1_QUESTION_FIELDS: FrozenSet[str] = frozenset(
    {"field", "kind", "question", "options", "answer_hint", "why"}
)
#: Transcribed from the contract's fixed questionnaire format
#: (``accounting_reasoning._RESPONSE_SHAPE`` question block).
QUESTION_KINDS: FrozenSet[str] = frozenset(
    {"choice", "date", "money", "number", "text"}
)

#: Contract A evidence entry (existing contract shape).
CALL1_EVIDENCE_FIELDS: FrozenSet[str] = frozenset({"kind", "why", "args"})

#: Contract B prerequisites entry (existing contract shape).
CALL2_PREREQ_FIELDS: FrozenSet[str] = frozenset(
    {"name", "status", "resolution", "record_args", "why"}
)
PREREQ_STATUSES: FrozenSet[str] = frozenset({"present", "missing", "ambiguous"})
PREREQ_RESOLUTIONS: FrozenSet[str] = frozenset({"reuse", "create", "ask"})

#: Contract B proposal entry (existing contract shape).
CALL2_PROPOSAL_FIELDS: FrozenSet[str] = frozenset(
    {
        "interpretation",
        "affected_records",
        "accounting_impact",
        "not_affected",
        "unresolved_uncertainty",
        "tools",
        "confirmation",
    }
)
CALL2_PROPOSAL_TOOL_FIELDS: FrozenSet[str] = frozenset({"tool_name", "arguments"})
CALL2_PROPOSAL_IMPACT_FIELDS: FrozenSet[str] = frozenset(
    {"account", "debit", "credit", "reason"}
)

#: Contract B ledger block (audit §5 v2; fit literals as accepted by
#: ``llm_classification``:389-392).
CALL2_LEDGER_FIELDS: FrozenSet[str] = frozenset(
    {"fit", "account_id", "propose_account"}
)
LEDGER_FITS: FrozenSet[str] = frozenset({"EXACT", "RELATED", "NONE"})
LEDGER_PROPOSE_ACCOUNT_FIELDS: FrozenSet[str] = frozenset(
    {"name", "code", "account_type", "parent_code"}
)
CONFIDENCE_LEVELS: FrozenSet[str] = frozenset({"HIGH", "MEDIUM", "LOW"})

#: Contract B needs[] kinds (design report §J).
NEED_KINDS: FrozenSet[str] = frozenset({"EVIDENCE", "USER_FACT", "CONFIG_PERIOD"})
CALL1_NEED_FIELDS: FrozenSet[str] = frozenset(
    {"kind", "name", "why_required", "evidence_request"}
)
#: A needs[] entry may never name one of Contract B's own decision fields —
#: that would make CALL 2 ask the user to supply the accounting answer
#: (design report §J, the ``treatment`` anti-pattern).
CALL2_DECISION_ANSWER_NAMES: FrozenSet[str] = CALL2_DECISION_FIELDS | {"decision"}

# ---------------------------------------------------------------------------
# Parsers — reuse the shipped JSON extractor (fence/brace tolerant)
# ---------------------------------------------------------------------------


def parse_semantic_intake_response(raw: Any) -> Optional[Dict[str, Any]]:
    """Extract a Contract A object from raw model text (or pass a dict).

    Delegates JSON extraction to the shipped ``parse_reasoning_response`` —
    no second parser.  Returns ``None`` when nothing parseable is present;
    validation is a separate step (parse-then-validate, as everywhere else
    in ``accounting_reasoning``).
    """
    if isinstance(raw, dict):
        return raw
    return parse_reasoning_response(raw)


def parse_accounting_decision_response(raw: Any) -> Optional[Dict[str, Any]]:
    """Extract a Contract B object from raw model text (or pass a dict).

    Same extractor as Contract A; see ``parse_semantic_intake_response``.
    """
    if isinstance(raw, dict):
        return raw
    return parse_reasoning_response(raw)


# ---------------------------------------------------------------------------
# Validators — return violation messages ([] = valid), mirroring
# accounting_reasoning.validate_outcome: rejections are reported to the model,
# never silently repaired.
# ---------------------------------------------------------------------------


def _check_closed_keys(
    payload: Dict[str, Any],
    allowed: FrozenSet[str],
    forbidden: FrozenSet[str],
    prefix: str,
    violations: List[str],
) -> None:
    for key in payload:
        if key in forbidden:
            violations.append(f"{prefix}: forbidden field '{key}'")
        elif key not in allowed:
            violations.append(f"{prefix}: unknown field '{key}'")


def _validate_understanding(value: Any, violations: List[str]) -> None:
    if not isinstance(value, dict):
        violations.append("contract A: understanding must be an object")
        return
    for key in value:
        if key not in CALL1_UNDERSTANDING_FIELDS:
            violations.append(f"contract A: unknown understanding field '{key}'")
    event_type = value.get("event_type")
    if event_type is not None and event_type not in EVENT_TYPES:
        violations.append(
            f"contract A: unknown event_type {event_type!r} "
            f"(allowed: {', '.join(sorted(EVENT_TYPES))})"
        )


def _validate_facts(value: Any, violations: List[str]) -> None:
    if not isinstance(value, list):
        violations.append("contract A: facts must be a list")
        return
    for index, entry in enumerate(value):
        where = f"contract A: facts[{index}]"
        if not isinstance(entry, dict):
            violations.append(f"{where} must be an object")
            continue
        for key in entry:
            if key not in CALL1_FACT_FIELDS:
                violations.append(f"{where}: unknown field '{key}'")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            violations.append(f"{where}: 'name' is required")
        if "value" not in entry or entry.get("value") is None:
            violations.append(f"{where}: 'value' is required (a resolved fact carries a value)")
        state = entry.get("state")
        if state is None:
            violations.append(f"{where}: 'state' is required")
        elif state not in RESOLVED_STATES:
            # EXACT semantic_contract rule: facts[] carries only resolved
            # states; AMBIGUOUS/MISSING belong in missing_material_facts.
            violations.append(
                f"{where}: state {state!r} is not a resolved fact state "
                f"(EXPLICIT or SAFELY_INFERRED)"
            )

def _validate_missing(value: Any, violations: List[str]) -> None:
    if not isinstance(value, list):
        violations.append("contract A: missing_material_facts must be a list")
        return
    for index, entry in enumerate(value):
        where = f"contract A: missing_material_facts[{index}]"
        if not isinstance(entry, dict):
            violations.append(f"{where} must be an object")
            continue
        for key in entry:
            if key not in CALL1_MISSING_FIELDS:
                violations.append(f"{where}: unknown field '{key}'")
        identifier = entry.get("fact") or entry.get("name")
        if not isinstance(identifier, str) or not identifier.strip():
            violations.append(f"{where}: requires a non-empty 'fact' or 'name'")
        why = entry.get("why_material") or entry.get("why_required")
        if not isinstance(why, str) or not why.strip():
            violations.append(f"{where}: requires a non-empty 'why_material' or 'why_required'")
        state = entry.get("state")
        if state is not None and state not in UNRESOLVED_STATES:
            # ASSUMED (and any other invented state) is rejected: the
            # vocabulary is EXPLICIT | SAFELY_INFERRED | AMBIGUOUS | MISSING.
            violations.append(
                f"{where}: state {state!r} is not an unresolved fact state "
                f"(AMBIGUOUS or MISSING)"
            )
        if "candidates" in entry and not isinstance(entry["candidates"], list):
            violations.append(f"{where}: 'candidates' must be a list")
        question = entry.get("question")
        if question is not None and (not isinstance(question, str) or not question.strip()):
            violations.append(f"{where}: 'question' must be a non-empty string")


def _validate_questionnaire(value: Any, violations: List[str]) -> None:
    if not isinstance(value, dict):
        violations.append("contract A: questionnaire must be an object or null")
        return
    for key in value:
        if key not in CALL1_QUESTIONNAIRE_FIELDS:
            violations.append(f"contract A: unknown questionnaire field '{key}'")
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        violations.append("contract A: questionnaire.text is required")
    questions = value.get("questions")
    if not isinstance(questions, list):
        violations.append("contract A: questionnaire.questions must be a list")
        return
    for index, question in enumerate(questions):
        where = f"contract A: questions[{index}]"
        if not isinstance(question, dict):
            violations.append(f"{where} must be an object")
            continue
        for key in question:
            if key not in CALL1_QUESTION_FIELDS:
                violations.append(f"{where}: unknown field '{key}'")
        if not isinstance(question.get("field"), str) or not question["field"].strip():
            violations.append(f"{where}: 'field' is required")
        if question.get("kind") not in QUESTION_KINDS:
            violations.append(
                f"{where}: kind {question.get('kind')!r} "
                f"(allowed: {', '.join(sorted(QUESTION_KINDS))})"
            )
        if not isinstance(question.get("question"), str) or not question["question"].strip():
            violations.append(f"{where}: 'question' is required")
        if "options" in question and not isinstance(question["options"], list):
            violations.append(f"{where}: 'options' must be a list")

def _validate_evidence(value: Any, violations: List[str]) -> None:
    if not isinstance(value, list):
        violations.append("contract A: evidence_requests must be a list")
        return
    for index, entry in enumerate(value):
        where = f"contract A: evidence_requests[{index}]"
        if not isinstance(entry, dict):
            violations.append(f"{where} must be an object")
            continue
        for key in entry:
            if key not in CALL1_EVIDENCE_FIELDS:
                violations.append(f"{where}: unknown field '{key}'")
        if not isinstance(entry.get("kind"), str) or not entry["kind"].strip():
            violations.append(f"{where}: 'kind' is required")
            continue
        if not isinstance(entry.get("why"), str) or not entry["why"].strip():
            violations.append(f"{where}: 'why' is required")
        args = entry.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            violations.append(f"{where}: 'args' must be an object")
            continue
        # Reuse the shipped catalogue validator (kind membership + arg shapes).
        problem = validate_evidence_request(
            EvidenceRequest(kind=entry["kind"], why=str(entry.get("why") or ""), args=args)
        )
        if problem:
            violations.append(f"{where}: {problem}")


def validate_semantic_intake_response(parsed: Any) -> List[str]:
    """Validate a Contract A payload.  Returns violations (empty = valid).

    Rejects: forbidden accounting fields (decision/intent/treatment/ledger/
    prerequisites/proposal/...), unknown top-level fields, unresolved states
    placed in ``facts``, invented fact states (no ``ASSUMED``), unknown
    event_types, malformed questionnaire shapes, and evidence requests the
    closed catalogue would refuse.
    """
    violations: List[str] = []
    if not isinstance(parsed, dict):
        return ["contract A: response is not a JSON object"]
    _check_closed_keys(parsed, CALL1_FIELDS, CALL1_FORBIDDEN, "contract A", violations)
    if not (set(parsed) & CALL1_FIELDS):
        violations.append(
            "contract A: at least one of understanding/facts/"
            "missing_material_facts/questionnaire/evidence_requests is required"
        )
    if "understanding" in parsed and parsed["understanding"] is not None:
        _validate_understanding(parsed["understanding"], violations)
    if "facts" in parsed and parsed["facts"] is not None:
        _validate_facts(parsed["facts"], violations)
    if "missing_material_facts" in parsed and parsed["missing_material_facts"] is not None:
        _validate_missing(parsed["missing_material_facts"], violations)
    if "questionnaire" in parsed and parsed["questionnaire"] is not None:
        _validate_questionnaire(parsed["questionnaire"], violations)
    if "evidence_requests" in parsed and parsed["evidence_requests"] is not None:
        _validate_evidence(parsed["evidence_requests"], violations)
    return violations

def _validate_decision(value: Any, violations: List[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        violations.append("contract B: decision must be an object")
        return None
    for key in value:
        if key not in CALL2_DECISION_FIELDS:
            violations.append(f"contract B: unknown decision field '{key}'")
    intent = value.get("intent")
    if intent:  # non-empty intent must be canonical; empty/absent handled by caller rules
        if not is_canonical_intent(intent):
            violations.append(
                f"contract B: decision.intent {intent!r} is not a canonical intent"
            )
    activity = value.get("activity")
    if activity and activity not in ACTIVITIES:
        violations.append(
            f"contract B: decision.activity {activity!r} "
            f"(allowed: {', '.join(sorted(ACTIVITIES))})"
        )
    document_nature = value.get("document_nature")
    if document_nature and not is_document_nature(document_nature):
        violations.append(
            f"contract B: decision.document_nature {document_nature!r} is not an "
            f"Axis-A value (allowed: {', '.join(sorted(DOCUMENT_NATURES))})"
        )
    treatment = value.get("treatment")
    if treatment and treatment not in TREATMENTS:
        violations.append(
            f"contract B: decision.treatment {treatment!r} is not an Axis-B/C "
            f"value (allowed: {', '.join(sorted(TREATMENTS))})"
        )
    payment_terms = value.get("payment_terms")
    if payment_terms and payment_terms not in PAYMENT_METHODS:
        violations.append(
            f"contract B: decision.payment_terms {payment_terms!r} "
            f"(allowed: {', '.join(sorted(PAYMENT_METHODS))})"
        )
    confidence = value.get("confidence")
    if confidence and confidence not in CONFIDENCE_LEVELS:
        violations.append(
            f"contract B: decision.confidence {confidence!r} "
            f"(allowed: {', '.join(sorted(CONFIDENCE_LEVELS))})"
        )
    ledger = value.get("ledger")
    if ledger is not None:
        if not isinstance(ledger, dict):
            violations.append("contract B: decision.ledger must be an object")
        else:
            for key in ledger:
                if key not in CALL2_LEDGER_FIELDS:
                    violations.append(f"contract B: unknown decision.ledger field '{key}'")
            fit = ledger.get("fit")
            if fit and fit not in LEDGER_FITS:
                violations.append(
                    f"contract B: decision.ledger.fit {fit!r} "
                    f"(allowed: {', '.join(sorted(LEDGER_FITS))})"
                )
            propose = ledger.get("propose_account")
            if propose is not None:
                if not isinstance(propose, dict):
                    violations.append(
                        "contract B: decision.ledger.propose_account must be an object"
                    )
                else:
                    for key in propose:
                        if key not in LEDGER_PROPOSE_ACCOUNT_FIELDS:
                            violations.append(
                                f"contract B: unknown propose_account field '{key}'"
                            )
    return value


def _validate_prerequisites(value: Any, violations: List[str]) -> None:
    if not isinstance(value, list):
        violations.append("contract B: prerequisites must be a list")
        return
    for index, entry in enumerate(value):
        where = f"contract B: prerequisites[{index}]"
        if not isinstance(entry, dict):
            violations.append(f"{where} must be an object")
            continue
        for key in entry:
            if key not in CALL2_PREREQ_FIELDS:
                violations.append(f"{where}: unknown field '{key}'")
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            violations.append(f"{where}: 'name' is required")
        status = entry.get("status")
        if status is not None and status not in PREREQ_STATUSES:
            violations.append(
                f"{where}: status {status!r} "
                f"(allowed: {', '.join(sorted(PREREQ_STATUSES))})"
            )
        resolution = entry.get("resolution")
        if resolution is not None and resolution not in PREREQ_RESOLUTIONS:
            # catches drift like the observed 'ask_or_create'
            violations.append(
                f"{where}: resolution {resolution!r} "
                f"(allowed: {', '.join(sorted(PREREQ_RESOLUTIONS))})"
            )
        if "record_args" in entry and not isinstance(entry["record_args"], dict):
            violations.append(f"{where}: 'record_args' must be an object")

def _validate_proposal(value: Any, violations: List[str]) -> None:
    if not isinstance(value, dict):
        violations.append("contract B: proposal must be an object")
        return
    for key in value:
        if key not in CALL2_PROPOSAL_FIELDS:
            violations.append(f"contract B: unknown proposal field '{key}'")
    for field_name in REQUIRED_PROPOSAL_FIELDS:
        if field_name not in value:
            violations.append(
                f"contract B: proposal is missing required disclosure '{field_name}'"
            )
    tools = value.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            violations.append("contract B: proposal.tools must be a list")
        else:
            for index, tool in enumerate(tools):
                where = f"contract B: proposal.tools[{index}]"
                if not isinstance(tool, dict):
                    violations.append(f"{where} must be an object")
                    continue
                for key in tool:
                    if key not in CALL2_PROPOSAL_TOOL_FIELDS:
                        violations.append(f"{where}: unknown field '{key}'")
                if not isinstance(tool.get("tool_name"), str) or not tool["tool_name"].strip():
                    violations.append(f"{where}: 'tool_name' is required")
    impact = value.get("accounting_impact")
    if impact is not None:
        if not isinstance(impact, list):
            violations.append("contract B: proposal.accounting_impact must be a list")
        else:
            for index, line in enumerate(impact):
                where = f"contract B: proposal.accounting_impact[{index}]"
                if not isinstance(line, dict):
                    violations.append(f"{where} must be an object")
                    continue
                for key in line:
                    if key not in CALL2_PROPOSAL_IMPACT_FIELDS:
                        violations.append(f"{where}: unknown field '{key}'")


def _validate_needs(value: Any, violations: List[str]) -> None:
    if not isinstance(value, list):
        violations.append("contract B: needs must be a list")
        return
    for index, entry in enumerate(value):
        where = f"contract B: needs[{index}]"
        if not isinstance(entry, dict):
            violations.append(f"{where} must be an object")
            continue
        for key in entry:
            if key not in CALL1_NEED_FIELDS:
                violations.append(
                    f"{where}: unknown field '{key}' "
                    f"(needs states requirements only — question fields belong to Contract A)"
                )
        kind = entry.get("kind")
        if kind not in NEED_KINDS:
            violations.append(
                f"{where}: kind {kind!r} "
                f"(allowed: {', '.join(sorted(NEED_KINDS))})"
            )
            continue
        name = entry.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                violations.append(f"{where}: 'name' must be a non-empty string")
            elif name.strip().lower() in CALL2_DECISION_ANSWER_NAMES:
                # GOOD: name="purpose_of_purchase" ... BAD: name="treatment"
                violations.append(
                    f"{where}: name {name!r} is a Contract B decision field — "
                    f"needs[] may not ask the user to supply the accounting answer"
                )
        if kind == "EVIDENCE":
            raw_request = entry.get("evidence_request")
            if not isinstance(raw_request, dict):
                violations.append(
                    f"{where}: EVIDENCE needs require an 'evidence_request' object"
                )
                continue
            for key in raw_request:
                if key not in CALL1_EVIDENCE_FIELDS:
                    violations.append(f"{where}.evidence_request: unknown field '{key}'")
            problem = validate_evidence_request(
                EvidenceRequest(
                    kind=str(raw_request.get("kind") or ""),
                    why=str(raw_request.get("why") or ""),
                    args=raw_request.get("args")
                    if isinstance(raw_request.get("args"), dict)
                    else {},
                )
            )
            if problem:
                violations.append(f"{where}.evidence_request: {problem}")
        else:
            if entry.get("evidence_request") is not None:
                violations.append(
                    f"{where}: 'evidence_request' is only valid for kind EVIDENCE"
                )
            if not isinstance(name, str) or not name.strip():
                violations.append(f"{where}: {kind} requires a non-empty 'name'")
            why = entry.get("why_required")
            if not isinstance(why, str) or not why.strip():
                violations.append(f"{where}: {kind} requires a non-empty 'why_required'")
            elif "?" in why:
                # deterministic proxy for "no user-facing question wording":
                # requirements are declarative; CALL 1 authors the question.
                violations.append(
                    f"{where}: 'why_required' must be declarative — question "
                    f"wording belongs to Contract A"
                )

def validate_accounting_decision_response(parsed: Any) -> List[str]:
    """Validate a Contract B payload.  Returns violations (empty = valid).

    Rejects: the Call-1 surface (facts/question/questionnaire/
    evidence_requests), unknown top-level fields, responses with no
    accounting step (one of proposal|refusal|complete|needs required),
    non-canonical intents, cross-axis vocabulary mixes (Axis-A values as
    treatment and vice versa), malformed prerequisites/proposal, and
    needs[] entries that author questions or name their own decision fields.
    """
    violations: List[str] = []
    if not isinstance(parsed, dict):
        return ["contract B: response is not a JSON object"]
    _check_closed_keys(parsed, CALL2_FIELDS, CALL2_FORBIDDEN, "contract B", violations)

    decision = None
    if "decision" in parsed and parsed["decision"] is not None:
        decision = _validate_decision(parsed["decision"], violations)
    if "prerequisites" in parsed and parsed["prerequisites"] is not None:
        _validate_prerequisites(parsed["prerequisites"], violations)
    if "proposal" in parsed and parsed["proposal"] is not None:
        _validate_proposal(parsed["proposal"], violations)
    if "rationale" in parsed and parsed["rationale"] is not None:
        if not isinstance(parsed["rationale"], str) or not parsed["rationale"].strip():
            violations.append("contract B: rationale must be a non-empty string")
    if "refusal" in parsed and parsed["refusal"] is not None:
        if not isinstance(parsed["refusal"], dict):
            violations.append("contract B: refusal must be an object or null")
    if "complete" in parsed and parsed["complete"] is not None:
        if not isinstance(parsed["complete"], bool):
            violations.append("contract B: complete must be a boolean")
    if "needs" in parsed and parsed["needs"] is not None:
        _validate_needs(parsed["needs"], violations)

    if not (set(parsed) & CALL2_FIELDS):
        violations.append(
            "contract B: at least one of decision/prerequisites/proposal/"
            "rationale/refusal/complete/needs is required"
        )

    # The accounting step: a decision response must DO one of the four things.
    has_step = (
        parsed.get("proposal") is not None
        or parsed.get("refusal") is not None
        or parsed.get("complete") is True
        or bool(parsed.get("needs"))
    )
    if not has_step:
        violations.append(
            "contract B: accounting step required — one of proposal|refusal|"
            "complete|needs must be present"
        )

    # A proposal is an accounting act: it may not proceed without an explicit
    # canonical intent.  event_type (a Call 1 field) never implies intent.
    if parsed.get("proposal") is not None:
        intent = (decision or {}).get("intent")
        if not intent or not is_canonical_intent(intent):
            violations.append(
                "contract B: proposal requires an explicit canonical "
                "decision.intent — accounting intent is a Call 2 decision "
                "and is never implied"
            )
    return violations

# ---------------------------------------------------------------------------
# Named contract types (documentation-level; the validators are authoritative)
# ---------------------------------------------------------------------------


class SemanticIntakeResponse(TypedDict, total=False):
    """Contract A — semantic intake (CALL 1).

    Fields are optional at the schema level; ``validate_semantic_intake_response``
    enforces shapes, the fact-state vocabulary and the boundary against every
    accounting-decision field.
    """

    understanding: Dict[str, Any]
    facts: List[Dict[str, Any]]
    missing_material_facts: List[Dict[str, Any]]
    questionnaire: Optional[Dict[str, Any]]
    evidence_requests: List[Dict[str, Any]]


class AccountingDecisionResponse(TypedDict, total=False):
    """Contract B — accounting decision (CALL 2).

    Fields are optional at the schema level; ``validate_accounting_decision_response``
    enforces shapes, the canonical vocabularies and the boundary against the
    semantic-intake surface.
    """

    decision: Dict[str, Any]
    prerequisites: List[Dict[str, Any]]
    proposal: Optional[Dict[str, Any]]
    rationale: str
    refusal: Optional[Dict[str, Any]]
    complete: bool
    needs: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Stage 1 observation — projection of EXISTING monolithic responses.
# Pure helper for tests/observation; not wired into any runtime path.
# ---------------------------------------------------------------------------


def observe_two_call_representation(parsed: Any) -> Dict[str, Any]:
    """Record whether an existing monolithic reasoning response could be
    represented by Contract A and/or Contract B (Stage 1, observation only).

    The monolithic response's ``question`` block is Contract A's
    ``questionnaire`` (same shape); everything else maps field-for-field.
    The two projections are independent: a response that mixes an intake step
    with future decision fields reports both sides with their violations.
    Never feeds ``execution_plan.intent``; never called by the runtime.
    """
    result: Dict[str, Any] = {
        "step": "unknown",
        "owner": "UNASSIGNED",
        "contract_a": {"representable": False, "violations": ["no contract-A content"]},
        "contract_b": {"representable": False, "violations": ["no contract-B content"]},
    }
    if not isinstance(parsed, dict):
        result["contract_a"] = {"representable": False, "violations": ["not a JSON object"]}
        result["contract_b"] = {"representable": False, "violations": ["not a JSON object"]}
        return result

    # Which slot does the monolithic response occupy (existing CHOOSING rule)?
    if parsed.get("proposal") is not None:
        result["step"], result["owner"] = "proposal", "CALL_2"
    elif parsed.get("refusal") is not None:
        result["step"], result["owner"] = "refusal", "CALL_2"
    elif parsed.get("complete") is True:
        result["step"], result["owner"] = "complete", "CALL_2"
    elif parsed.get("question"):
        result["step"], result["owner"] = "question", "CALL_1"
    elif parsed.get("evidence_requests"):
        result["step"], result["owner"] = "evidence", "CALL_1"

    a_projection: Dict[str, Any] = {}
    for key in ("understanding", "facts", "missing_material_facts", "evidence_requests"):
        if key in parsed:
            a_projection[key] = parsed[key]
    if parsed.get("question"):
        a_projection["questionnaire"] = parsed["question"]
    if a_projection:
        a_violations = validate_semantic_intake_response(a_projection)
        result["contract_a"] = {
            "representable": not a_violations,
            "violations": a_violations,
        }

    b_projection: Dict[str, Any] = {}
    for key in ("decision", "prerequisites", "proposal", "rationale", "refusal", "complete"):
        if key in parsed:
            b_projection[key] = parsed[key]
    if b_projection:
        b_violations = validate_accounting_decision_response(b_projection)
        result["contract_b"] = {
            "representable": not b_violations,
            "violations": b_violations,
        }
    return result







