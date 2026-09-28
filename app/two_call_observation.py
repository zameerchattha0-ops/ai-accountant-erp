"""Stage 2 — two-call OBSERVATION (diagnostic only; never authoritative).

One EXISTING authoritative reasoning response (the monolithic
``accounting_reasoning`` contract) is projected onto the two future roles:

    CALL 1  SemanticIntakeResponse      (Contract A)
    CALL 2  AccountingDecisionResponse  (Contract B)

and classified strictly for telemetry.  This module:

* makes NO additional provider call — the projection is derived from the
  response the existing loop already parsed;
* never repairs or normalizes the model's answer — an unrepresentable value
  is REPORTED, never rewritten or defaulted (projection is not normalization);
* has NO authority — the returned dict is only forwarded to the audit hook
  (``_notify`` → execution step).  Nothing here may feed intent, execution
  plan, treatment, ledger, prerequisites, proposal, confirmation or
  execution; the §12 authority gate stays closed.

Deterministic categories:

    both sides represented : A_AND_B_VALID | A_VALID_B_INVALID |
                             A_INVALID_B_VALID | BOTH_INVALID
    one side represented   : A_VALID | A_INVALID | B_VALID | B_INVALID
                             (the absent side's status is MODEL_ABSENT)
    neither side           : MODEL_ABSENT

Fields are never manufactured to fill a side.  Everything recorded is
metadata only: no prompts, no raw completion, no user text.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.accounting_vocabulary import (
    TREATMENTS,
    is_canonical_intent,
    is_document_nature,
)
from app.two_call_contracts import observe_two_call_representation

__all__ = ["OBSERVATION_TYPE", "build_two_call_observation"]

OBSERVATION_TYPE = "TWO_CALL_OBSERVATION"

_VIOLATION_LIMIT = 8
_VIOLATION_WIDTH = 200

#: Presence probes — the monolithic spelling of each role surface.
#: ``question`` is the monolithic name of Contract A's ``questionnaire``.
_CALL1_PRESENCE = (
    "understanding",
    "facts",
    "missing_material_facts",
    "question",
    "evidence_requests",
)
_CALL2_PRESENCE = (
    "decision",
    "prerequisites",
    "proposal",
    "rationale",
    "refusal",
    "complete",
    "needs",
)


def _bounded(items: List[str]) -> List[str]:
    return [str(item)[:_VIOLATION_WIDTH] for item in items[:_VIOLATION_LIMIT]]


def _fit_under_step_cap(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the serialized payload valid under the 2000-char step cap.

    ``create_execution_step`` shears ``input_summary`` at 2000 chars unless the
    payload carries the evidence-memo escape key; a sheared payload is invalid
    JSON and the SQL guard drops the row.  Violation ARRAYS are therefore
    trimmed (counts keep the full truth) until the payload deterministically
    fits — the observation must never lose its row to the cap.
    """
    for limit in (8, 6, 4, 3, 2, 1, 0):
        for key in ("a_violations", "b_violations", "evidence_invalid", "needs_invalid"):
            payload[key] = payload[key][:limit]
        if len(json.dumps(payload, default=str)) <= 1900:
            break
    return payload


def _intent_observation(decision: Any) -> Dict[str, Any]:
    """§8 — classify the response's intent against CANONICAL_INTENTS.

    Observation only: the runtime intent is never read back from here and is
    never copied into ``execution_plan.intent``.
    """
    intent = decision.get("intent") if isinstance(decision, dict) else None
    if not isinstance(intent, str) or not intent.strip():
        return {"intent": None, "intent_result": "MODEL_ABSENT"}
    if is_canonical_intent(intent):
        return {"intent": intent[:64], "intent_result": "AGREEMENT"}
    return {"intent": intent[:64], "intent_result": "MODEL_NONCANONICAL"}


def _nature_observation(decision: Any) -> Dict[str, Any]:
    """§9 — record document_nature / treatment against the Stage 1 axes.

    Records only; NEVER repairs (no ASSET_DISPOSAL → OPERATING_EXPENSE), never
    defaults a missing treatment, never infers one from event_type.
    """
    data = decision if isinstance(decision, dict) else {}
    nature = data.get("document_nature")
    treatment = data.get("treatment")
    out: Dict[str, Any] = {
        "nature_present": bool(nature),
        "document_nature": (str(nature)[:64] if nature else None),
        "nature_valid": None,
        "treatment_present": bool(treatment),
        "treatment": (str(treatment)[:64] if treatment else None),
        "treatment_valid": None,
    }
    if nature:
        out["nature_valid"] = bool(is_document_nature(nature))
    if treatment:
        out["treatment_valid"] = treatment in TREATMENTS
    return out


def _question_observation(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """§10 — what the response's question representation looks like.

    Never rewrites the question, never authors a new one; field names and
    kinds only — no question text (metadata only).
    """
    question = parsed.get("question")
    out: Dict[str, Any] = {
        "question_present": bool(question),
        "question_valid": None,
        "question_fields": [],
        "question_kinds": [],
        "question_options_provided": False,
    }
    if not question:
        return out
    entries = question.get("questions") if isinstance(question, dict) else None
    if isinstance(entries, list):
        dicts = [e for e in entries[:8] if isinstance(e, dict)]
        out["question_fields"] = [str(e.get("field"))[:48] for e in dicts if e.get("field")]
        out["question_kinds"] = [str(e.get("kind"))[:16] for e in dicts if e.get("kind")]
        out["question_options_provided"] = any(
            isinstance(e.get("options"), list) and e.get("options") for e in dicts
        )
    return out


def build_two_call_observation(
    parsed: Any, *, round_index: int = 1, elapsed_ms: Optional[int] = None
) -> Dict[str, Any]:
    """Project ONE parsed monolithic response onto Contract A/B (metadata only).

    Uses the sealed Stage 1 projections/validators exclusively — no new
    interpretation rules live here.  Returns a JSON-serializable dict for the
    audit step; the caller forwards it verbatim and consumes NOTHING back.
    """
    if not isinstance(parsed, dict):
        parsed = {}  # not a JSON object -> every side is MODEL_ABSENT

    projection = observe_two_call_representation(parsed)  # Stage 1 validators

    a_present = any(parsed.get(key) is not None for key in _CALL1_PRESENCE)
    b_present = any(parsed.get(key) is not None for key in _CALL2_PRESENCE)
    a_violations = list(projection["contract_a"]["violations"]) if a_present else []
    b_violations = list(projection["contract_b"]["violations"]) if b_present else []
    a_valid = a_present and not a_violations
    b_valid = b_present and not b_violations
    a_status = "MODEL_ABSENT" if not a_present else ("VALID" if a_valid else "INVALID")
    b_status = "MODEL_ABSENT" if not b_present else ("VALID" if b_valid else "INVALID")

    if a_present and b_present:
        if a_valid and b_valid:
            category = "A_AND_B_VALID"
        elif a_valid:
            category = "A_VALID_B_INVALID"
        elif b_valid:
            category = "A_INVALID_B_VALID"
        else:
            category = "BOTH_INVALID"
    elif a_present:
        category = "A_VALID" if a_valid else "A_INVALID"
    elif b_present:
        category = "B_VALID" if b_valid else "B_INVALID"
    else:
        category = "MODEL_ABSENT"

    understanding = parsed.get("understanding")
    event_type = understanding.get("event_type") if isinstance(understanding, dict) else None
    evidence = parsed.get("evidence_requests")
    evidence_kinds = (
        [str(r.get("kind"))[:48] for r in evidence[:8] if isinstance(r, dict)]
        if isinstance(evidence, list)
        else []
    )
    needs = parsed.get("needs")
    needs_kinds = (
        [str(n.get("kind"))[:32] for n in needs[:8] if isinstance(n, dict)]
        if isinstance(needs, list)
        else []
    )
    question_obs = _question_observation(parsed)
    if question_obs["question_present"]:
        question_obs["question_valid"] = not [
            v for v in a_violations if "questionnaire" in v or "questions[" in v
        ]

    payload = {
        "observation_type": OBSERVATION_TYPE,
        "round": int(round_index),
        "elapsed_ms": (int(elapsed_ms) if elapsed_ms is not None else None),
        "category": category,
        "a_status": a_status,
        "b_status": b_status,
        "a_fields": [k for k in _CALL1_PRESENCE if parsed.get(k) is not None],
        "b_fields": [k for k in _CALL2_PRESENCE if parsed.get(k) is not None],
        "a_violation_count": len(a_violations),
        "b_violation_count": len(b_violations),
        "violation_count": len(a_violations) + len(b_violations),
        "a_violations": _bounded(a_violations),
        "b_violations": _bounded(b_violations),
        "event_type": (str(event_type)[:48] if event_type else None),
        **_intent_observation(parsed.get("decision")),
        **_nature_observation(parsed.get("decision")),
        **question_obs,
        "evidence_requested": len(evidence_kinds),
        "evidence_kinds": evidence_kinds,
        "evidence_invalid": _bounded(
            [v for v in a_violations if "evidence_requests[" in v]
        ),
        "needs_count": len(needs_kinds),
        "needs_kinds": needs_kinds,
        "needs_invalid": _bounded([v for v in b_violations if "needs[" in v]),
    }

    return _fit_under_step_cap(payload)


