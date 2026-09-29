"""Stage 3 — two-call semantic runtime (CANDIDATE ONLY; never executes).

    CALL 1 semantic intake  →  PYTHON evidence/entity acquisition  →
    CALL 2 accounting decision  →  PYTHON validation  →  STOP.

Hard rules implemented here:

* No financial mutation, no tool execution, no confirmation snapshot, no
  account/customer/supplier creation.  The runtime returns a CANDIDATE; the
  caller (``app.agent``) records it and stops.
* No second provider abstraction: the orchestrator handed in by the caller is
  reused as-is; JSON extraction is the Stage 1 contract parsers (→
  ``parse_reasoning_response``); evidence is ``books_evidence.gather_evidence``
  with the per-request cache keying used by the reasoning loop; proposal
  validation is ``accounting_reasoning.validate_outcome`` with the real
  tool-argument contracts.
* Call 1 owns user-facing questions and NEVER the accounting decision
  (Contract A rejects every decision field).
* Call 2 owns the accounting interpretation and NEVER authors questions
  (Contract B has no question surface; ``needs[]`` routes back through
  Call 1).
* Bounded: at most ``CALL1_MAX_ROUNDS`` intake rounds and
  ``CALL2_MAX_ATTEMPTS`` decision attempts — no unbounded C1↔C2 loop.
* Failures are honest: the monolithic interpretation is NEVER used as a
  hidden fallback for this path; it is available only when the flag is OFF.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import structlog

from app.accounting_reasoning import (
    REQUIRED_PROPOSAL_FIELDS,
    _evidence_cache_key,
    _outcome_from_parsed,
    parse_reasoning_response,
    validate_outcome,
)
from app.accounting_vocabulary import (
    CANONICAL_INTENTS,
    DOCUMENT_NATURES,
    TREATMENTS,
    is_canonical_intent,
)
from app.books_evidence import (
    deferred_evidence_requests,
    evidence_catalog_text,
    parse_evidence_requests,
    render_evidence,
    validate_evidence_request,
)
from app.two_call_contracts import (
    ACTIVITIES,
    EVENT_TYPES,
    PAYMENT_METHODS,
    parse_accounting_decision_response,
    parse_semantic_intake_response,
    validate_accounting_decision_response,
    validate_semantic_intake_response,
)

log = structlog.get_logger(__name__)

#: Bounded acquisition: intake rounds and decision attempts per turn.
CALL1_MAX_ROUNDS = 3
CALL2_MAX_ATTEMPTS = 2

#: Outcome statuses (candidate-only vocabulary; nothing here executes).
CANDIDATE_READY = "CANDIDATE_READY"
CANDIDATE_REFUSAL = "CANDIDATE_REFUSAL"
CANDIDATE_COMPLETE = "CANDIDATE_COMPLETE"
AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
FAILED = "FAILED"
PROVIDER_FAILED = "PROVIDER_FAILED"

#: Observation marker (existing free-form step convention).
RUNTIME_STEP = "TWO_CALL_RUNTIME"
CANDIDATE_STEP = "STAGE3_CANDIDATE_ONLY"

_CALL1_REPLY_SKELETON = {
    "understanding": {
        "economic_event": "...",
        "what_user_wants": "...",
        "basis": "...",
        "event_type": "<one of the event classes>",
    },
    "facts": [{"name": "...", "value": "...", "state": "EXPLICIT"}],
    "missing_material_facts": [
        {"name": "...", "why_required": "...", "state": "MISSING"}
    ],
    "questionnaire": {
        "text": "...",
        "questions": [
            {"field": "<erp field>", "kind": "choice|date|money|number|text",
             "question": "<one plain question>", "options": [], "why": "<why>"}
        ],
    },
    "evidence_requests": [{"kind": "<catalogue kind>", "why": "...", "args": {}}],
}


@dataclass
class TwoCallOutcome:
    """Candidate-only result of one two-call turn (nothing executes)."""

    status: str
    reason: Optional[str] = None
    call1: Optional[Dict[str, Any]] = None
    call2: Optional[Dict[str, Any]] = None
    question: Optional[Dict[str, Any]] = None
    required_fields: List[str] = field(default_factory=list)
    candidate: Optional[Dict[str, Any]] = None
    refusal: Optional[Dict[str, Any]] = None
    needs: List[Dict[str, Any]] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    intake_rounds: int = 0
    decision_attempts: int = 0
    timings: Dict[str, int] = field(default_factory=dict)
    observation: Dict[str, Any] = field(default_factory=dict)


_CALL2_REPLY_SKELETON = {
    "decision": {
        "intent": "<one canonical intent>",
        "activity": "<vocabulary value>",
        "document_nature": "<Axis A value or null>",
        "treatment": "<Axis B/C value or null>",
        "payment_terms": "<vocabulary value or null>",
        "ledger": {"fit": "EXACT|RELATED|NONE", "account_id": None},
        "confidence": "HIGH|MEDIUM|LOW",
    },
    "prerequisites": [
        {"name": "...", "status": "present|missing|ambiguous",
         "resolution": "reuse|create|ask", "why": "..."}
    ],
    "proposal": {
        "interpretation": "...", "affected_records": [],
        "accounting_impact": [{"account": "...", "debit": 0, "credit": 0,
                               "reason": "..."}],
        "not_affected": [], "unresolved_uncertainty": [],
        "tools": [{"tool_name": "...", "arguments": {}}],
        "confirmation": "...",
    },
    "rationale": "...",
    "refusal": None,
    "complete": False,
    "needs": [
        {"kind": "EVIDENCE|USER_FACT|CONFIG_PERIOD", "name": "...",
         "why_required": "..."}
    ],
}


def _vocab(values: Any) -> str:
    return ", ".join(sorted(str(v) for v in values))


def _authored_field_names() -> List[str]:
    """The shipped questionnaire field vocabulary (single source of truth)."""
    from app.questionnaire import AUTHORED_FIELDS

    return sorted(AUTHORED_FIELDS)


def _render_history(history: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for pair in list(history)[-8:]:
        if not isinstance(pair, dict):
            continue
        question = str(pair.get("question") or pair.get("field") or "").strip()[:240]
        answer = str(pair.get("answer") or "").strip()[:240]
        if question or answer:
            lines.append(f"Q: {question}\nA: {answer}")
    return "\n".join(lines)


def _pick(row: Any, keys: Sequence[str]) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    return {k: row[k] for k in keys if row.get(k) is not None}


def _mechanical_entry(orchestrator: Any) -> Any:
    """Prefer the MECHANICAL (fast-tier) text entry for CALL 1.

    ``generate_text_light`` is the shipped entry point for work that needs no
    accounting judgement (semantic fact extraction, perception, classification)
    and routes to ``accounting_fast_chain_list``.  CALL 1 — reading the user's
    words into facts — is exactly that work, so it must not be sent to a deep
    THINKING model.

    Measured on the live gateway (2026-09-29, the shipped Call-1 prompt):
    ``generate_text`` starts with Token Harbor's thinking model, whose
    ``reasoning_content`` consumed the whole 2,048-token output cap and returned
    EMPTY content — finish_reason 'length', 8,466 chars of reasoning, 0 chars of
    answer, 20.4 s.  With thinking off the same task answered in 6.0 s / 520
    tokens.  The fast tier is the designed route for mechanical work; CALL 2
    (accounting judgement) keeps the deep entry.

    Falls back to ``generate_text`` so any orchestrator implementation — and
    every test double — keeps working unchanged.

    When the entry understands ``tier_first`` (the real orchestrator does;
    ``**kw`` test doubles absorb it), the wrapper passes ``tier_first=True``
    so the fast chain LEADS the call. Without it the orchestrator fronts
    every text turn with the Token Harbor thinking model, which measured
    live (2026-09-29) burning the whole 2,048-token output budget on
    reasoning and returning EMPTY content on this exact intake prompt —
    the tier was ordered but never reached first. A plain signature (no
    ``tier_first``, no ``**kw``) falls back to the default call, so older
    orchestrators and strict doubles are untouched.
    """
    entry = None
    for name in ("generate_text_light", "generate_text"):
        candidate = getattr(orchestrator, name, None)
        if callable(candidate):
            entry = candidate
            break
    if entry is None:
        return None
    try:
        params = inspect.signature(entry).parameters
        accepts = "tier_first" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
    except (TypeError, ValueError):  # pragma: no cover — exotic callables
        accepts = False
    if not accepts:
        return entry

    async def _chain_first_entry(*, prompt: str) -> str:
        return await entry(prompt=prompt, tier_first=True)  # type: ignore[call-arg]

    return _chain_first_entry


def build_intake_prompt(
    *,
    user_request: str,
    conversation_history: Sequence[Dict[str, Any]] = (),
    preliminary: Optional[Dict[str, Any]] = None,
    evidence_block: str = "",
    feedback: Sequence[str] = (),
) -> str:
    """CALL 1 — the semantic-intake role prompt (Contract A only)."""
    parts = [
        "SYSTEM: You are CALL 1 of a TWO-CALL accounting protocol — the",
        "SEMANTIC INTAKE role. Read the user's message as a business event",
        "and record ONLY what is semantically there.",
        "",
        "You NEVER decide accounting treatment. These keys are FORBIDDEN",
        "anywhere in your answer (the contract rejects the whole reply):",
        "decision, intent, treatment, ledger, prerequisites, proposal,",
        "rationale, refusal, complete, needs, journal, debit, credit,",
        "accounting_impact.",
        "",
        "Return EXACTLY one JSON object with these five keys:",
        json.dumps(_CALL1_REPLY_SKELETON, indent=1),
        "",
        "RULES",
        "1. understanding: the economic event, what the user wants, the basis",
        f"   (their own words) and one event_type from: {_vocab(EVENT_TYPES)}.",
        "2. facts: ONLY facts stated in the message (EXPLICIT) or trivially",
        "   implied by its wording (SAFELY_INFERRED). Never invent amounts,",
        "   dates, parties or tax treatment.",
        "3. missing_material_facts: facts that materially affect bookkeeping",
        "   and are NOT known yet — absent from BOTH the user request AND the",
        "   Question/answer history below (amount, date, paid-vs-unpaid, tax",
        "   inclusive, resale vs internal use). Say WHY each is required.",
        "4. questionnaire: when the user must supply a fact, ask for the FACT",
        "   in one plain question. Each entry MUST be {\"field\": <erp field>,",
        "   \"kind\": choice|date|money|number|text, \"question\": <the text>,",
        "   \"options\": [...]}; 'field' and 'question' are REQUIRED — never use",
        "   'name' or 'prompt' as keys. 'field' MUST be one of the allowed",
        f"   field names: {_vocab(_authored_field_names())}.",
        "   Omit the block when nothing needs asking.",
        "   The BLOCK itself MUST include a \"text\" key — a one-line summary of",
        "   the ask — or the contract rejects your whole reply.",
        "   NEVER ask for a fact the user request already states or the",
        "   Question/answer history already answered — check both first;",
        "   re-asking a known fact wastes the user's turn.",
        "   Never ask an accounting-decision question ('how should I record this',",
        "   'is this a receivable') — that is CALL 2's job, never yours.",
        "   Do NOT ask for accounting-POLICY detail (depreciation method/life/",
        "   salvage, account or GL codes, categorization) — CALL 2 owns those",
        "   decisions and states them as needs; asking them here bypasses",
        "   CALL 2 and delays the turn. Ask only for facts about the event",
        "   itself: who, what, when, how much, how paid, what for.",
        "   Account and GL-code lookups are BOOKS lookups, not user facts:",
        "   request them via evidence_requests (chart_of_accounts,",
        "   bank_accounts, …) and only ask the user if the books cannot answer.",
        "5. evidence_requests: read-only looks at the BOOKS that could answer",
        "   a fact. Use ONLY these kinds and ONLY the arguments each one",
        "   declares (an undeclared argument is rejected and wastes a round):",
        evidence_catalog_text(),
        '   Shape: {"kind": <catalogue kind>, "why": <reason>, "args": {…}}.',
        "   Prefer the books over asking the user when they can answer.",
        "6. BREVITY: every field is MACHINE-READ. ONE short clause per text",
        "   field (<= 120 characters): no prose, no explanation, no restatement",
        "   of the request, no markdown. Anything longer is discarded weight.",
        "",
        "CONTEXT",
        "User request:",
        user_request,
    ]
    if conversation_history:
        parts += ["", "Question/answer history of this conversation:",
                  _render_history(conversation_history)]
    if preliminary:
        parts += ["", "Python literal extraction (values only, no meaning):",
                  json.dumps(preliminary, default=str)[:1200]]
    if evidence_block:
        parts += ["", "LIVE BOOKS EVIDENCE (read-only):", evidence_block[:4000]]
    if feedback:
        parts += ["", "YOUR PREVIOUS ANSWER WAS REJECTED OR INCOMPLETE:"]
        parts += [f"- {item}" for item in list(feedback)[:8]]
    parts += ["", "Answer with the JSON object ONLY. No prose, no code fences."]
    return "\n".join(parts)


def _tool_names() -> List[str]:
    """The trusted tool registry names (read-only reuse; no new abstraction)."""
    try:
        from app.tools import list_tools

        return sorted(str(name) for name in list_tools())
    except Exception:  # noqa: BLE001 — a prompt never breaks the runtime
        return []


def build_decision_prompt(
    *,
    user_request: str,
    intake_packet: Dict[str, Any],
    evidence_block: str = "",
    accounting_context: Optional[Dict[str, Any]] = None,
    feedback: Sequence[str] = (),
) -> str:
    """CALL 2 — the accounting-decision role prompt (Contract B only)."""
    parts = [
        "SYSTEM: You are CALL 2 of a TWO-CALL accounting protocol — the",
        "ACCOUNTING DECISION role. The semantic intake below is FINAL: you",
        "interpret it; you never rewrite its facts.",
        "",
        "You NEVER author user-facing questions. If a user fact is required,",
        "return it in needs[] (kind USER_FACT) — Call 1 asks the user.",
        "",
        "Return EXACTLY one JSON object with these keys:",
        json.dumps(_CALL2_REPLY_SKELETON, indent=1),
        "",
        "DECISION VOCABULARY (closed)",
        f"· intent: one canonical intent — {_vocab(CANONICAL_INTENTS)}.",
        f"· activity: {_vocab(ACTIVITIES)}",
        f"· document_nature (Axis A): {_vocab(DOCUMENT_NATURES)}",
        f"· treatment (Axis B/C): {_vocab(TREATMENTS)}",
        f"· payment_terms: {_vocab(PAYMENT_METHODS)}",
        "· ledger.fit: EXACT | RELATED | NONE (never pick a first match;",
        "  when unsure use NONE and name the need).",
        "· confidence: HIGH | MEDIUM | LOW",
        "",
        "RULES",
        "1. prerequisite entries: {name, status: present|missing|ambiguous,",
        "   resolution: reuse|create|ask, why}. Creating anything is a",
        "   PREREQUISITE for later stages — never assume it happened.",
        "2. proposal: only when the event is safe to record as stated. It",
        f"   must carry {_vocab(REQUIRED_PROPOSAL_FIELDS)} plus the exact",
        "   'confirmation' sentence and 'tools' (tool names from:",
        f"   {_vocab(_tool_names())}).",
        "3. refusal: when the request is unsafe or unsupported — explain what",
        "   is missing and the safe alternative. complete=true only when the",
        "   requested outcome is already recorded and verified.",
        "4. needs[]: kinds EVIDENCE | USER_FACT | CONFIG_PERIOD. An EVIDENCE",
        "   entry carries evidence_request using ONLY these kinds and ONLY the",
        "   arguments each one declares:",
        evidence_catalog_text(),
        "   NEVER name a decision field (intent,",
        "   treatment, document_nature, ledger, decision) as the thing the",
        "   user must supply — that is YOUR interpretation, never theirs.",
        "5. Missing material facts block a proposal: return them in needs[].",
        "6. BREVITY: 'interpretation' and 'confirmation' are ONE sentence each;",
        "   every affected/impact 'reason' is one short clause (<= 120 chars);",
        "   no prose outside the JSON, no restatement, no markdown.",
        "",
        "STAGE 3 CONTRACT: your answer is validated and RECORDED as a",
        "candidate. It is NEVER executed in this stage — no journal, no",
        "invoice, no payment, no account creation.",
        "",
        "SEMANTIC INTAKE PACKET (immutable for this decision):",
        json.dumps(intake_packet, default=str, ensure_ascii=False)[:4000],
        "",
        "ORIGINAL USER REQUEST:",
        user_request,
    ]
    if accounting_context:
        parts += ["", "ACCOUNTING CONTEXT (deterministic):",
                  json.dumps(accounting_context, default=str)[:1200]]
    if evidence_block:
        parts += ["", "LIVE BOOKS EVIDENCE (read-only):", evidence_block[:4000]]
    if feedback:
        parts += ["", "YOUR PREVIOUS ANSWER WAS REJECTED OR INCOMPLETE:"]
        parts += [f"- {item}" for item in list(feedback)[:8]]
    parts += ["", "Answer with the JSON object ONLY. No prose, no code fences."]
    return "\n".join(parts)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


async def _call_model(generate: Any, prompt: str, *, timeout: float) -> Any:
    """ONE bounded provider round-trip on the caller's existing client."""
    return await asyncio.wait_for(
        generate(prompt=prompt), timeout=max(1.0, float(timeout))
    )


def _emit(step_logger: Any, event: str, payload: Dict[str, Any]) -> None:
    """Best-effort audit hook — observation must never break the runtime."""
    if not callable(step_logger):
        return
    try:
        step_logger(event, payload)
    except Exception:  # noqa: BLE001
        log.warning("two_call_runtime.step_logger_failed", event=event)


def _intake_admissible(payload: Any) -> bool:
    """Deterministic sufficiency of a Call-1 packet (no LLM flag involved).

    Sufficient = structurally valid + understanding present + nothing left to
    ask the user (no questionnaire questions) + nothing left to fetch (no
    evidence requests).  Missing facts do NOT block the decision — Call 2
    returns needs[] for those.
    """
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("understanding"), dict) or not payload["understanding"]:
        return False
    questionnaire = payload.get("questionnaire")
    if isinstance(questionnaire, dict) and questionnaire.get("questions"):
        return False
    if payload.get("evidence_requests"):
        return False
    return True


def _question_from_intake(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The intake questionnaire in the existing cleaned question shape."""
    from app.accounting_reasoning import _clean_question

    questionnaire = payload.get("questionnaire") if isinstance(payload, dict) else None
    if not isinstance(questionnaire, dict):
        return None
    return _clean_question(questionnaire)


def _required_fields(question: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(question, dict):
        return []
    fields = [
        str(entry.get("field")).strip()
        for entry in (question.get("questions") or [])
        if isinstance(entry, dict) and str(entry.get("field") or "").strip()
    ]
    return fields[:12] or ["information"]


def _known_facts(
    payload: Dict[str, Any],
    conversation_history: Sequence[Dict[str, Any]],
    preliminary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Field -> value facts ALREADY established for this turn.

    Mechanical collection only (no interpretation): Python literal
    extraction values, intake facts explicitly stated (or trivially implied)
    by the user, and conversation-history entries that carry a ``field``.
    """
    known: Dict[str, Any] = {}
    if isinstance(preliminary, dict):
        known.update(
            {str(k): v for k, v in preliminary.items() if v is not None}
        )
    facts = payload.get("facts")
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            name = str(fact.get("name") or "").strip()
            value = fact.get("value")
            if (
                name
                and value is not None
                and fact.get("state") in ("EXPLICIT", "SAFELY_INFERRED")
            ):
                known.setdefault(name, value)
    for pair in conversation_history or ():
        if not isinstance(pair, dict):
            continue
        field_name = str(pair.get("field") or "").strip()
        answer = pair.get("answer")
        if field_name and answer:
            known.setdefault(field_name, answer)
    return known


def _filter_intake_questionnaire(
    payload: Dict[str, Any],
    conversation_history: Sequence[Dict[str, Any]] = (),
    preliminary: Optional[Dict[str, Any]] = None,
) -> None:
    """Apply the SHIPPED authored-question floor to Call 1's questionnaire.

    ``questionnaire.validate_authored_questions`` is the field-vocabulary +
    never-re-ask-known filter the monolithic response site uses. Stage 3's
    park site must apply the SAME filter, or Call 1 asks unknown field names
    and re-asks stated facts (live 2026-09-29: a 12-turn spiral re-asking
    supplier_name / bank_account_name that were already stated or answered).
    Entries are never repaired: unknown, duplicate and already-known fields
    are dropped. When nothing survives, the block disappears and intake is
    admitted instead of parking on a question Python already knows the
    answer to.
    """
    from app.questionnaire import validate_authored_questions

    questionnaire = payload.get("questionnaire")
    if not isinstance(questionnaire, dict):
        return
    entries = questionnaire.get("questions")
    if not isinstance(entries, list):
        return
    specs = validate_authored_questions(
        entries, _known_facts(payload, conversation_history, preliminary)
    )
    kept = {spec.field for spec in specs}
    kept_entries: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("field") or "").strip()
        if name in kept and name not in seen:
            seen.add(name)
            kept_entries.append(entry)
    if kept_entries:
        questionnaire["questions"] = kept_entries
    else:
        payload.pop("questionnaire", None)


_CALL1_FIELD_KEYS = (
    "understanding", "facts", "missing_material_facts",
    "questionnaire", "evidence_requests",
)
_CALL2_DECISION_KEYS = (
    "intent", "activity", "document_nature", "treatment",
    "payment_terms", "ledger", "confidence",
)


def _presence(payload: Any, keys: Sequence[str]) -> Dict[str, bool]:
    data = payload if isinstance(payload, dict) else {}
    return {key: data.get(key) is not None for key in keys}


def _build_observation(
    outcome: TwoCallOutcome, *, event_type: Optional[str]
) -> Dict[str, Any]:
    """§19 observation — structured metadata only (no prompts, no payloads)."""
    decision = (outcome.call2 or {}).get("decision")
    decision = decision if isinstance(decision, dict) else {}
    prerequisites = (outcome.call2 or {}).get("prerequisites")
    needs = (outcome.call2 or {}).get("needs")
    if outcome.status == CANDIDATE_READY:
        proposal_status = "VALIDATED"
    elif outcome.status == CANDIDATE_REFUSAL:
        proposal_status = "REFUSED"
    elif outcome.status == CANDIDATE_COMPLETE:
        proposal_status = "COMPLETE"
    elif outcome.call2 is not None:
        proposal_status = "REJECTED"
    else:
        proposal_status = "NONE"
    call2_status = {
        CANDIDATE_READY: "VALID",
        CANDIDATE_REFUSAL: "VALID",
        CANDIDATE_COMPLETE: "VALID",
    }.get(outcome.status)
    if call2_status is None:
        call2_status = "NOT_REACHED" if outcome.call2 is None else "INVALID"
    return {
        "observation_type": RUNTIME_STEP,
        "status": outcome.status,
        "reason": outcome.reason,
        "call_1_status": "VALID" if outcome.call1 is not None else "MODEL_ABSENT",
        "call_2_status": call2_status,
        "call_1_elapsed_ms": outcome.timings.get("call_1_ms", 0),
        "call_2_elapsed_ms": outcome.timings.get("call_2_ms", 0),
        "python_acquisition_ms": outcome.timings.get("python_ms", 0),
        "total_elapsed_ms": outcome.timings.get("total_ms", 0),
        "call_1_field_validity": _presence(outcome.call1, _CALL1_FIELD_KEYS),
        "call_2_field_validity": _presence(decision, _CALL2_DECISION_KEYS),
        "event_type": event_type,
        "intent": (str(decision.get("intent"))[:64] if decision.get("intent") else None),
        "document_nature": (str(decision.get("document_nature"))[:64]
                            if decision.get("document_nature") else None),
        "treatment": (str(decision.get("treatment"))[:64]
                      if decision.get("treatment") else None),
        "payment_terms": (str(decision.get("payment_terms"))[:64]
                          if decision.get("payment_terms") else None),
        "prerequisite_count": len(prerequisites) if isinstance(prerequisites, list) else 0,
        "need_count": len(needs) if isinstance(needs, list) else 0,
        "proposal_status": proposal_status,
        "intake_rounds": outcome.intake_rounds,
        "decision_attempts": outcome.decision_attempts,
        "violation_count": len(outcome.violations),
    }


def _finish(outcome: TwoCallOutcome, step_logger: Any, started: float) -> TwoCallOutcome:
    outcome.timings["total_ms"] = _elapsed_ms(started)
    event_type = None
    try:
        understanding = (outcome.call1 or {}).get("understanding")
        if isinstance(understanding, dict):
            event_type = understanding.get("event_type")
    except Exception:  # noqa: BLE001 — observation only
        event_type = None
    try:
        outcome.observation = _build_observation(outcome, event_type=event_type)
        _emit(step_logger, RUNTIME_STEP, outcome.observation)
        if outcome.status == CANDIDATE_READY:
            _emit(step_logger, CANDIDATE_STEP, {
                "intent": outcome.observation.get("intent"),
                "proposal_status": "VALIDATED",
                "note": "candidate only — nothing was executed",
            })
    except Exception:  # noqa: BLE001 — observation must never break the turn
        log.warning("two_call_runtime.observation_failed")
    return outcome


async def run_two_call_runtime(
    *,
    user_request: str,
    organization_id: uuid.UUID,
    session_id: Optional[uuid.UUID] = None,
    auth: Any = None,
    conversation_history: Sequence[Dict[str, Any]] = (),
    orchestrator: Any = None,
    step_logger: Any = None,
    gather: Any = None,
    preliminary: Optional[Dict[str, Any]] = None,
    accounting_context: Optional[Dict[str, Any]] = None,
) -> TwoCallOutcome:
    """Run the two-call runtime for ONE turn — CANDIDATE ONLY.

    Flow (§21): CALL1_INTAKE → AWAITING_EVIDENCE / AWAITING_CLARIFICATION →
    CALL1_INTAKE → CALL2_DECISION → needs[] routing (EVIDENCE → books, then
    CALL 1 again; USER_FACT → CALL 1 authors the questionnaire; CONFIG_PERIOD
    → recorded deterministically, never invented) → DECISION_READY →
    STAGE3_CANDIDATE_ONLY.  Nothing executes: no tool call, no confirmation
    snapshot, no accounting mutation.  Failures never fall back to the
    monolithic interpretation — that path exists only when the flag is OFF.
    """
    started = time.monotonic()
    timings: Dict[str, int] = {"call_1_ms": 0, "python_ms": 0, "call_2_ms": 0}
    outcome = TwoCallOutcome(status=FAILED, reason="not_started", timings=timings)

    try:
        from app.config import get_settings

        settings = get_settings()
        # CALL 1 = mechanical intake (fast tier); CALL 2 = accounting
        # judgement (deep tier).  See _mechanical_entry for the measured
        # reason a thinking model must not serve the intake call.
        generate_intake = _mechanical_entry(orchestrator)
        generate_decision = getattr(orchestrator, "generate_text", None)
        if not callable(generate_decision) and not callable(generate_intake):
            outcome.status = PROVIDER_FAILED
            outcome.reason = "no_provider_or_empty_request"
            return _finish(outcome, step_logger, started)
        if generate_intake is None:
            generate_intake = generate_decision
        if generate_decision is None:
            generate_decision = generate_intake
        if not str(user_request or "").strip():
            outcome.status = PROVIDER_FAILED
            outcome.reason = "no_provider_or_empty_request"
            return _finish(outcome, step_logger, started)
        if gather is None:
            from app.books_evidence import gather_evidence

            gather = gather_evidence
        request_timeout = float(getattr(settings, "accounting_reasoning_timeout", 90.0))
        # WHOLE-TURN budget: the per-call cap alone lets 6 calls add up to three
        # minutes.  Mirrors accounting_reasoning_total_timeout for the
        # monolithic stage; on exhaustion the runtime fails honestly.
        turn_budget = float(
            getattr(settings, "two_call_runtime_total_timeout", 60.0)
        )
        deadline = asyncio.get_running_loop().time() + max(1.0, turn_budget)

        evidence_block = ""
        evidence_cache: Dict[Any, Any] = {}
        feedback: List[str] = []
        decision_feedback: List[str] = []
        packet: Optional[Dict[str, Any]] = None

        async def _acquire(raw_requests: Any) -> List[str]:
            """Existing evidence layer + existing cache keying (read-only).

            Returns EXPLICIT feedback lines: a request that is refused OR
            deferred past the per-round cap is named back to the model so it
            can re-ask next round.  A model-requested lookup must never
            disappear silently (AUDIT_REPORT §7).
            """
            nonlocal evidence_block
            parsed_requests = parse_evidence_requests(raw_requests)
            notes: List[str] = []
            deferred = deferred_evidence_requests(raw_requests)
            if deferred:
                notes.append(
                    "EVIDENCE CAPACITY: these requests were DEFERRED to the next "
                    "round (the cap is unchanged) — ask for them again now if you "
                    "still need them: " + ", ".join(dict.fromkeys(deferred))
                )
            usable = []
            rejections: List[str] = []
            for request in parsed_requests:
                problem = validate_evidence_request(request)
                if problem:
                    rejections.append(problem)
                else:
                    usable.append(request)
            if rejections:
                notes.append(
                    "REFUSED evidence requests: " + " | ".join(rejections)
                )
            if not usable:
                return notes or ["no usable evidence request was provided"]
            t_py = time.monotonic()
            misses = [
                r for r in usable if _evidence_cache_key(r) not in evidence_cache
            ]
            if misses:
                fresh = await gather(
                    misses,
                    organization_id=organization_id,
                    auth=auth,
                    session_id=session_id,
                )
                for request, result in zip(misses, fresh or []):
                    result.args = dict(request.args or {})
                    if getattr(result, "error", None) is None:
                        evidence_cache[_evidence_cache_key(request)] = result
            evidence_block = render_evidence(list(evidence_cache.values()))
            timings["python_ms"] += _elapsed_ms(t_py)
            return notes

        # +1: after the final Call 1 round the budget must still allow the
        # decision-attempt bound check to run (it parks honestly, no 3rd C2).
        max_cycles = CALL1_MAX_ROUNDS + CALL2_MAX_ATTEMPTS + 1
        for _cycle in range(max_cycles):
            # Whole-turn bound: a slower-than-usual provider must not chain
            # several 30 s calls into minutes of user-visible waiting.
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0.5:
                outcome.status = FAILED
                outcome.reason = "turn_budget_exhausted"
                return _finish(outcome, step_logger, started)
            call_timeout = min(request_timeout, remaining)
            # ---------------- CALL 1 — semantic intake ----------------
            if packet is None:
                if outcome.intake_rounds >= CALL1_MAX_ROUNDS:
                    outcome.status = FAILED
                    outcome.reason = "intake_rounds_exhausted"
                    return _finish(outcome, step_logger, started)
                outcome.intake_rounds += 1
                prompt = build_intake_prompt(
                    user_request=user_request,
                    conversation_history=conversation_history,
                    preliminary=preliminary,
                    evidence_block=evidence_block,
                    feedback=feedback,
                )
                t0 = time.monotonic()
                try:
                    raw = await _call_model(
                        generate_intake, prompt, timeout=call_timeout
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — transport failure
                    # Attribute the spent time even when the call FAILED: a
                    # 0 ms Call 1 on a 30 s timeout hides where the turn went.
                    timings["call_1_ms"] += _elapsed_ms(t0)
                    outcome.status = PROVIDER_FAILED
                    outcome.reason = f"call1_transport:{type(exc).__name__}"
                    return _finish(outcome, step_logger, started)
                timings["call_1_ms"] += _elapsed_ms(t0)

                payload = parse_semantic_intake_response(raw)
                if payload is None:  # parse failure — no fabricated facts
                    outcome.status = PROVIDER_FAILED
                    # An EMPTY provider reply (HTTP 200 with no content) is not
                    # a malformed answer: label it truthfully so the operator
                    # investigates the provider, not the JSON contract.
                    outcome.reason = (
                        "call1_no_provider_content"
                        if not str(raw or "").strip()
                        else "call1_unparseable"
                    )
                    return _finish(outcome, step_logger, started)
                violations = validate_semantic_intake_response(payload)
                if violations:  # contract violation — reject, feed back
                    outcome.violations = list(violations)
                    feedback = ["Contract A violations:"] + list(violations)
                    continue

                # Deterministic question floor: shipped field vocabulary +
                # never-re-ask-known BEFORE any park decision (see
                # _filter_intake_questionnaire).
                _filter_intake_questionnaire(
                    payload, conversation_history, preliminary
                )
                outcome.call1 = payload
                question = _question_from_intake(payload)
                if question:  # Call 1 owns the question → existing park
                    outcome.status = AWAITING_CLARIFICATION
                    outcome.reason = "call1_questionnaire"
                    outcome.question = question
                    outcome.required_fields = _required_fields(question)
                    return _finish(outcome, step_logger, started)

                if payload.get("evidence_requests"):
                    # _acquire returns EXPLICIT notes — refusals AND requests
                    # deferred past the cap (AUDIT_REPORT §7), never a silent drop.
                    feedback = await _acquire(payload.get("evidence_requests"))
                    continue  # reassess with the books in hand

                if not _intake_admissible(payload):
                    feedback = ["The intake packet is incomplete for a decision."]
                    continue
                packet = payload
                continue

            # ---------------- CALL 2 — accounting decision ----------------
            if outcome.decision_attempts >= CALL2_MAX_ATTEMPTS:
                # Bounded: material information is still missing after the
                # decision budget.  A USER_FACT need parks the turn (Call 1
                # owns the wording); anything else fails honestly.  Never the
                # monolithic fallback, never an invented answer.
                user_names = [
                    str(n.get("name"))[:64]
                    for n in (outcome.needs or [])
                    if isinstance(n, dict) and n.get("kind") == "USER_FACT"
                ]
                if user_names:
                    outcome.status = AWAITING_CLARIFICATION
                    outcome.reason = "call2_needs_user_fact"
                    outcome.required_fields = user_names
                    outcome.question = {
                        "text": "To record this correctly I need: "
                                + ", ".join(user_names) + ".",
                        "questions": [],
                    }
                else:
                    outcome.status = FAILED
                    outcome.reason = "decision_attempts_exhausted"
                return _finish(outcome, step_logger, started)

            outcome.decision_attempts += 1
            prompt = build_decision_prompt(
                user_request=user_request,
                intake_packet=packet,
                evidence_block=evidence_block,
                accounting_context=accounting_context,
                feedback=decision_feedback,
            )
            t0 = time.monotonic()
            try:
                raw = await _call_model(
                    generate_decision, prompt, timeout=call_timeout
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — transport failure
                timings["call_2_ms"] += _elapsed_ms(t0)
                outcome.status = PROVIDER_FAILED
                outcome.reason = f"call2_transport:{type(exc).__name__}"
                return _finish(outcome, step_logger, started)
            timings["call_2_ms"] += _elapsed_ms(t0)

            parsed = parse_accounting_decision_response(raw)
            if parsed is None:  # parse failure — no execution, no repair
                outcome.status = PROVIDER_FAILED
                outcome.reason = (
                    "call2_no_provider_content"
                    if not str(raw or "").strip()
                    else "call2_unparseable"
                )
                return _finish(outcome, step_logger, started)
            outcome.call2 = parsed
            violations = validate_accounting_decision_response(parsed)
            if violations:  # contract violation — reject, feed back
                outcome.violations = list(violations)
                decision_feedback = ["Contract B violations:"] + list(violations)
                continue

            # ---- needs[] routing (§14) — decided BEFORE any proposal ----
            needs = [n for n in (parsed.get("needs") or []) if isinstance(n, dict)]
            if needs:
                outcome.needs = needs
                config_needs = [n for n in needs if n.get("kind") == "CONFIG_PERIOD"]
                if config_needs:
                    # Period/configuration resolution is deterministic Python
                    # OUTSIDE this runtime (out of Stage 3 scope): record the
                    # need and stop honestly — never invent a period.
                    outcome.status = FAILED
                    outcome.reason = "config_period_required:" + ",".join(
                        str(n.get("name"))[:40] for n in config_needs[:4]
                    )
                    return _finish(outcome, step_logger, started)
                evidence_needs = [
                    n.get("evidence_request")
                    for n in needs
                    if n.get("kind") == "EVIDENCE"
                    and isinstance(n.get("evidence_request"), dict)
                ]
                if evidence_needs:
                    # Surface refusals/deferrals to CALL 1, which runs next.
                    feedback = await _acquire(evidence_needs)
                    packet = None  # Call 1 absorbs the books next round (§10)
                    decision_feedback = []
                    continue
                user_names = [
                    str(n.get("name"))[:64]
                    for n in needs
                    if n.get("kind") == "USER_FACT"
                ]
                if user_names:
                    # Route back through Call 1 — it authors the question;
                    # Call 2 never writes user-facing questions (§13).
                    packet = None
                    feedback = [
                        "The decision role requires these USER facts — ask the",
                        "user for each as ONE plain factual question:",
                        *user_names,
                    ]
                    decision_feedback = []
                    continue
                decision_feedback = ["needs[] did not route to a known handler."]
                continue

            # ---- refusal / complete / proposal (candidate only) ----
            if isinstance(parsed.get("refusal"), dict) and parsed["refusal"]:
                outcome.status = CANDIDATE_REFUSAL
                outcome.refusal = parsed["refusal"]
                return _finish(outcome, step_logger, started)
            if parsed.get("complete") is True:
                outcome.status = CANDIDATE_COMPLETE
                return _finish(outcome, step_logger, started)

            proposal_outcome = _outcome_from_parsed(
                parsed, rounds=outcome.decision_attempts
            )
            try:
                from app.tools import tool_contracts as _tool_contracts

                contracts = _tool_contracts()
            except Exception:  # noqa: BLE001 — contracts optional at validation
                contracts = {}
            enforcement = validate_outcome(
                proposal_outcome,
                # The SAME tool set the Call 2 prompt offers — an invented or
                # unregistered tool name must not reach the candidate (the
                # argument gate alone cannot judge an unknown name).
                offered_tools=tuple(_tool_names()),
                forbidden_tools=(),
                tool_contracts=contracts,
            )
            if enforcement:  # not engine-compatible -> fed back, never executed
                outcome.violations = list(enforcement)
                decision_feedback = ["Proposal violations:"] + list(enforcement)
                continue

            decision = parsed.get("decision") or {}
            tools = [
                str(call.get("tool_name"))
                for call in ((parsed.get("proposal") or {}).get("tools") or [])
                if isinstance(call, dict)
            ]
            prerequisites = parsed.get("prerequisites") or []
            outcome.status = CANDIDATE_READY
            outcome.candidate = {
                "intent": decision.get("intent"),
                "activity": decision.get("activity"),
                "document_nature": decision.get("document_nature"),
                "treatment": decision.get("treatment"),
                "payment_terms": decision.get("payment_terms"),
                "confidence": decision.get("confidence"),
                "prerequisites": (
                    len(prerequisites) if isinstance(prerequisites, list) else 0
                ),
                "tools": tools[:12],
                "proposal_present": True,
            }
            return _finish(outcome, step_logger, started)




        outcome.status = FAILED
        outcome.reason = (
            outcome.reason if outcome.reason != "not_started" else "cycles_exhausted"
        )
        return _finish(outcome, step_logger, started)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — the runtime must never raise
        log.warning("two_call_runtime.failed", error=str(exc)[:200])
        outcome.status = FAILED
        outcome.reason = f"runtime_error:{type(exc).__name__}"
        return _finish(outcome, step_logger, started)





