"""Two-Call Contracts — Stage 1 boundary tests (infrastructure/observation only).

Proves the role boundaries of ``app/two_call_contracts.py`` (Two-Call Design
Report, Stage 1):

* Contract A (Semantic Intake) accepts only the semantic-intake surface and
  rejects every accounting-decision field.
* Contract B (Accounting Decision) accepts only the accounting-decision
  surface and rejects the Call-1 surface.
* ``needs[]`` states requirements — it never authors a user-facing question
  and never names one of its own decision fields.
* The fact vocabulary is the existing four states; ``ASSUMED`` does not exist.
* ``event_type`` is a surface classification: it never derives accounting
  intent; a proposal requires an explicit canonical ``decision.intent``.
* Observation projects existing monolithic responses onto A/B without any
  runtime wiring (neither contract is authoritative in Stage 1).

These tests only import the new module — no runtime behavior changes.
"""
from __future__ import annotations

import json

import pytest

from app import two_call_contracts as tcc


def _full_intake() -> dict:
    """A response carrying every Contract A field (incl. event_type)."""
    return {
        "understanding": {
            "economic_event": "Receipt of funds from ABC",
            "what_user_wants": "Record the receipt",
            "basis": "User stated ABC paid the outstanding invoice.",
            "event_type": "settlement",
        },
        "facts": [
            {"name": "amount", "value": 50000, "state": "EXPLICIT"},
            {
                "name": "party_name",
                "value": "ABC",
                "state": "SAFELY_INFERRED",
                "evidence": "party name copied verbatim from the request",
            },
        ],
        "missing_material_facts": [
            {
                "fact": "Economic nature of the receipt",
                "why_material": "Settlement vs advance changes the posting.",
                "state": "MISSING",
            }
        ],
        "questionnaire": {
            "text": "To record this receipt I need one detail:",
            "questions": [
                {
                    "field": "transaction_nature",
                    "kind": "choice",
                    "question": "Does this receipt settle an existing invoice or is it an advance?",
                    "options": [
                        {"value": "settlement", "label": "Settlement"},
                        {"value": "advance", "label": "Advance"},
                    ],
                    "answer_hint": "Choose one.",
                    "why": "Determines which records change.",
                }
            ],
        },
        "evidence_requests": [
            {
                "kind": "open_receivables",
                "why": "Check whether the money settles an existing invoice.",
                "args": {"party_name": "ABC"},
            }
        ],
    }


def _full_decision() -> dict:
    """A response carrying every Contract B field (vocabulary-consistent).

    Note the discipline the vocabulary enforces: ``record_receipt`` is the
    canonical INTENT; ``record_customer_receipt`` is the TOOL slug.
    """
    return {
        "decision": {
            "intent": "record_receipt",
            "activity": "receipt",
            "document_nature": "GOODS",
            "treatment": "REVENUE",
            "payment_terms": "BANK_TRANSFER",
            "ledger": {
                "fit": "EXACT",
                "account_id": None,
                "propose_account": {
                    "name": "Trade Receivables",
                    "code": "",
                    "account_type": "ASSET",
                    "parent_code": "",
                },
            },
            "confidence": "HIGH",
        },
        "prerequisites": [
            {
                "name": "customer_receivable_ledger",
                "status": "missing",
                "resolution": "create",
                "why": "A receipt needs a receivable ledger to settle against.",
            }
        ],
        "proposal": {
            "interpretation": "Receipt settling ABC's open invoice.",
            "affected_records": ["trade receivables", "bank"],
            "accounting_impact": [
                {
                    "account": "Bank",
                    "debit": 50000,
                    "credit": 0,
                    "reason": "money received",
                }
            ],
            "not_affected": ["no new invoice will be created"],
            "unresolved_uncertainty": [],
            "tools": [{"tool_name": "record_customer_receipt", "arguments": {}}],
            "confirmation": (
                "Record the receipt of 50,000 from ABC against the open invoice?"
            ),
        },
        "rationale": (
            "The money settles an open receivable, so cash increases and the "
            "receivable decreases."
        ),
    }

# ---------------------------------------------------------------------------
# Contract A — accepts / rejects
# ---------------------------------------------------------------------------


def test_call1_accepts_full_intake_payload():
    assert tcc.validate_semantic_intake_response(_full_intake()) == []


@pytest.mark.parametrize(
    "field",
    ["decision", "intent", "treatment", "ledger", "prerequisites", "proposal"],
)
def test_call1_rejects_accounting_field(field):
    payload = _full_intake()
    payload[field] = {"intent": "record_purchase"} if field == "decision" else "x"
    violations = tcc.validate_semantic_intake_response(payload)
    assert any(f"forbidden field '{field}'" in v for v in violations), violations


def test_call1_rejects_unknown_top_level_field():
    payload = _full_intake()
    payload["banana"] = True
    violations = tcc.validate_semantic_intake_response(payload)
    assert any("unknown field 'banana'" in v for v in violations), violations


def test_call1_rejects_assumed_fact_state():
    payload = _full_intake()
    payload["missing_material_facts"][0]["state"] = "ASSUMED"
    violations = tcc.validate_semantic_intake_response(payload)
    assert any("not an unresolved fact state" in v for v in violations), violations


def test_call1_rejects_ambiguous_state_in_facts():
    payload = _full_intake()
    payload["facts"][0]["state"] = "AMBIGUOUS"
    violations = tcc.validate_semantic_intake_response(payload)
    assert any("not a resolved fact state" in v for v in violations), violations


def test_call1_rejects_resolved_state_in_missing_facts():
    payload = _full_intake()
    payload["missing_material_facts"][0]["state"] = "EXPLICIT"
    violations = tcc.validate_semantic_intake_response(payload)
    assert any("not an unresolved fact state" in v for v in violations), violations


def test_call1_rejects_unknown_event_type():
    payload = _full_intake()
    payload["understanding"]["event_type"] = "banana_event"
    violations = tcc.validate_semantic_intake_response(payload)
    assert any("unknown event_type" in v for v in violations), violations


def test_call1_rejects_unknown_evidence_kind():
    payload = _full_intake()
    payload["evidence_requests"][0]["kind"] = "not_a_kind"
    violations = tcc.validate_semantic_intake_response(payload)
    assert any("Unknown evidence kind" in v for v in violations), violations


def test_call1_rejects_unknown_question_kind():
    payload = _full_intake()
    payload["questionnaire"]["questions"][0]["kind"] = "essay"
    violations = tcc.validate_semantic_intake_response(payload)
    assert any("kind 'essay'" in v for v in violations), violations


def test_parse_semantic_intake_reuses_shipped_extractor():
    payload = _full_intake()
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert tcc.parse_semantic_intake_response(fenced) == payload
    assert tcc.parse_semantic_intake_response(payload) == payload
    assert tcc.parse_semantic_intake_response("no json here") is None

# ---------------------------------------------------------------------------
# Contract B — accepts / rejects
# ---------------------------------------------------------------------------


def test_call2_accepts_full_decision_payload():
    assert tcc.validate_accounting_decision_response(_full_decision()) == []


def test_call2_accepts_response_carrying_all_envelope_fields():
    payload = _full_decision()
    payload["refusal"] = {"reason": "not applicable — proposal path chosen"}
    payload["complete"] = True
    payload["needs"] = [
        {
            "kind": "USER_FACT",
            "name": "purpose_of_purchase",
            "why_required": "Required to determine the economic treatment.",
        }
    ]
    assert tcc.validate_accounting_decision_response(payload) == []


@pytest.mark.parametrize(
    "field", ["facts", "question", "questionnaire", "evidence_requests"]
)
def test_call2_rejects_intake_field(field):
    payload = _full_decision()
    if field in ("facts", "evidence_requests"):
        payload[field] = []
    elif field == "questionnaire":
        payload[field] = {"text": "x", "questions": []}
    else:
        payload[field] = "Which invoice?"
    violations = tcc.validate_accounting_decision_response(payload)
    assert any(f"forbidden field '{field}'" in v for v in violations), violations


def test_call2_rejects_unknown_top_level_field():
    payload = _full_decision()
    payload["understanding"] = {}
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("unknown field 'understanding'" in v for v in violations), violations


def test_call2_rejects_noncanonical_intent():
    payload = _full_decision()
    payload["decision"]["intent"] = "verify_existing_purchase"
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("not a canonical intent" in v for v in violations), violations


def test_call2_rejects_axis_value_in_treatment():
    payload = _full_decision()
    payload["decision"]["treatment"] = "GOODS"  # an Axis-A value
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("Axis-B/C" in v for v in violations), violations


def test_call2_rejects_treatment_value_as_document_nature():
    payload = _full_decision()
    payload["decision"]["document_nature"] = "INVENTORY"  # an Axis-B value
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("Axis-A" in v for v in violations), violations


def test_call2_rejects_unknown_payment_terms():
    payload = _full_decision()
    payload["decision"]["payment_terms"] = "CRYPTO"
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("payment_terms" in v for v in violations), violations


def test_call2_rejects_response_without_accounting_step():
    payload = {"decision": {"intent": "record_receipt"}}
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("accounting step required" in v for v in violations), violations


def test_call2_proposal_requires_explicit_canonical_intent():
    payload = _full_decision()
    payload["decision"].pop("intent")
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("never implied" in v for v in violations), violations


def test_call2_rejects_unknown_prerequisite_resolution():
    payload = _full_decision()
    payload["prerequisites"][0]["resolution"] = "ask_or_create"
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("resolution" in v for v in violations), violations


def test_call2_rejects_empty_rationale():
    payload = _full_decision()
    payload["rationale"] = ""
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("rationale" in v for v in violations), violations

# ---------------------------------------------------------------------------
# needs[] — requirements, never a questionnaire
# ---------------------------------------------------------------------------


def test_needs_user_fact_accepted():
    payload = _full_decision()
    payload["proposal"] = None
    payload["needs"] = [
        {
            "kind": "USER_FACT",
            "name": "purpose_of_purchase",
            "why_required": "Required to determine the economic treatment.",
        }
    ]
    assert tcc.validate_accounting_decision_response(payload) == []


def test_needs_rejects_accounting_answer_name():
    payload = _full_decision()
    payload["proposal"] = None
    payload["needs"] = [
        {
            "kind": "USER_FACT",
            "name": "treatment",
            "why_required": "Required to determine the economic treatment.",
        }
    ]
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("accounting answer" in v for v in violations), violations


def test_needs_rejects_user_facing_question():
    payload = _full_decision()
    payload["proposal"] = None
    payload["needs"] = [
        {
            "kind": "USER_FACT",
            "name": "purpose_of_purchase",
            "why_required": "Is this an operating expense or fixed asset?",
        }
    ]
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("declarative" in v for v in violations), violations


def test_needs_evidence_kind_uses_closed_catalogue():
    good = _full_decision()
    good["proposal"] = None
    good["needs"] = [
        {
            "kind": "EVIDENCE",
            "evidence_request": {
                "kind": "open_receivables",
                "why": "Check whether the money settles an invoice.",
                "args": {"party_name": "ABC"},
            },
        }
    ]
    assert tcc.validate_accounting_decision_response(good) == []
    bad = json.loads(json.dumps(good))
    bad["needs"][0]["evidence_request"]["kind"] = "not_a_kind"
    violations = tcc.validate_accounting_decision_response(bad)
    assert any("Unknown evidence kind" in v for v in violations), violations


def test_needs_rejects_question_fields():
    payload = _full_decision()
    payload["proposal"] = None
    payload["needs"] = [
        {
            "kind": "USER_FACT",
            "name": "purpose_of_purchase",
            "why_required": "Required to determine the economic treatment.",
            "question": "What will this laptop be used for?",
        }
    ]
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("unknown field 'question'" in v for v in violations), violations


def test_needs_rejects_unknown_kind():
    payload = _full_decision()
    payload["proposal"] = None
    payload["needs"] = [{"kind": "ASK_USER", "name": "x", "why_required": "y"}]
    violations = tcc.validate_accounting_decision_response(payload)
    assert any("kind 'ASK_USER'" in v for v in violations), violations

# ---------------------------------------------------------------------------
# event_type separation — surface classification only, never derived intent
# ---------------------------------------------------------------------------


def test_event_type_settlement_does_not_imply_intent():
    """The design report §8: 'settlement' in Contract A must not produce or
    derive an accounting intent — that remains a Call 2 decision."""
    intake = _full_intake()
    assert intake["understanding"]["event_type"] == "settlement"
    assert tcc.validate_semantic_intake_response(intake) == []
    assert "decision" not in intake  # the intake carries no accounting decision

    # Call 1 cannot carry the derivation either:
    smuggled = json.loads(json.dumps(intake))
    smuggled["decision"] = {"intent": "record_receipt"}
    assert any(
        "forbidden field 'decision'" in v
        for v in tcc.validate_semantic_intake_response(smuggled)
    )

    # The intent is a Call 2 decision: without an explicit decision.intent a
    # proposal is rejected — the event type never fills it in.
    no_intent = _full_decision()
    no_intent["decision"].pop("intent")
    assert any(
        "never implied" in v
        for v in tcc.validate_accounting_decision_response(no_intent)
    )

    # Both settlement outcomes remain expressible only via B's explicit intent:
    for intent in ("record_receipt", "record_payment"):
        payload = _full_decision()
        payload["decision"]["intent"] = intent
        assert tcc.validate_accounting_decision_response(payload) == []


# ---------------------------------------------------------------------------
# Stage 1 observation — projections of existing monolithic responses
# ---------------------------------------------------------------------------


def _monolithic_intake_response() -> dict:
    """Shape of a real evidence-step response (abridged from the study data)."""
    return {
        "understanding": {
            "economic_event": "Credit purchase of three laptops",
            "what_user_wants": "Record the purchase",
            "basis": "User request states supplier, amount and credit terms.",
            "event_type": "new_event",
        },
        "evidence_requests": [
            {
                "kind": "parties",
                "why": "Check whether the supplier already exists.",
                "args": {"terms": ["FDS Labs"], "party_role": "supplier"},
            }
        ],
        "missing_material_facts": [],
        "question": None,
        "decision": {
            "intent": "record_credit_purchase",
            "treatment": None,
            "document_nature": None,
        },
        "prerequisites": [],
        "proposal": None,
        "refusal": None,
        "complete": False,
    }


def test_observation_projects_intake_step_to_contract_a():
    observed = tcc.observe_two_call_representation(_monolithic_intake_response())
    assert observed["step"] == "evidence"
    assert observed["owner"] == "CALL_1"
    assert observed["contract_a"]["representable"] is True
    assert observed["contract_a"]["violations"] == []
    # an intake step carries no accounting step → not representable as B
    assert observed["contract_b"]["representable"] is False
    assert any(
        "accounting step required" in v for v in observed["contract_b"]["violations"]
    )


def test_observation_projects_proposal_step_to_contract_b():
    monolithic = _monolithic_intake_response()
    monolithic["evidence_requests"] = []
    monolithic["decision"] = {
        "intent": "record_credit_purchase",
        "treatment": "INVENTORY",
        "document_nature": "GOODS",
    }
    monolithic["proposal"] = _full_decision()["proposal"]
    observed = tcc.observe_two_call_representation(monolithic)
    assert observed["step"] == "proposal"
    assert observed["owner"] == "CALL_2"
    assert observed["contract_b"]["representable"] is True
    assert observed["contract_b"]["violations"] == []




