"""Stage 3 §26 — deterministic two-call integration fixtures.

Scripted providers + a fake read-only gather: NO database, NO provider, NO
financial mutation is reachable from this harness.  Each fixture pins the
terminal status, the provider call count and that only OBSERVATION step
events were emitted (RUNTIME_STEP / CANDIDATE_STEP — never execution).

Matrix: E1 credit purchase · E2 supplier balance query · A1 received customer
payment · A2 cash expense · R1 disguised personal expense · R2 destructive
chart-of-accounts request · P1 cash sale · P2 manual journal ·
C1 already-recorded transaction · ambiguous payment · missing customer ·
missing supplier · missing account · ambiguous ledger · evidence-required
transaction · Call2 USER_FACT · Call2 EVIDENCE.
"""

import json

import pytest

import app.two_call_runtime as tcr
from test_two_call_runtime import (
    MSG,
    ORG,
    _gather_fake,
    _run,
    decision_reply,
    intake_reply,
)


_UUID = "11111111-1111-1111-1111-111111111111"


def _proposal(tools, *, interpretation, confirmation, impact=None):
    return {
        "interpretation": interpretation,
        "affected_records": ["books"],
        "accounting_impact": impact or [
            {"account": "Cash", "debit": 0, "credit": 0, "reason": "fixture"}
        ],
        "not_affected": [],
        "unresolved_uncertainty": [],
        "tools": tools,
        "confirmation": confirmation,
    }


def _decision(*, intent, activity="purchase", tools=None, payment_terms="CREDIT",
              nature=None, treatment=None, ledger=None, prerequisites=None,
              needs=None, refusal=None, complete=False,
              rationale="Deterministic fixture decision."):
    payload = {
        "decision": {
            "intent": intent,
            "activity": activity,
            "document_nature": nature,
            "treatment": treatment,
            "payment_terms": payment_terms,
            "ledger": ledger or {"fit": "NONE", "account_id": None},
            "confidence": "HIGH",
        },
        "prerequisites": prerequisites or [{
            "name": "party", "status": "present", "resolution": "reuse",
            "why": "Fixture party already exists.",
        }],
        "proposal": None,
        "rationale": rationale,
        "refusal": refusal,
        "complete": complete,
        "needs": needs or [],
    }
    if tools is not None and refusal is None and not complete:
        payload["proposal"] = _proposal(
            tools,
            interpretation=f"Candidate interpretation for {intent}.",
            confirmation=f"Record {intent}?",
        )
    return json.dumps(payload)


def _assert_observation_only(events):
    """Only observation events — the runtime has no execution surface."""
    allowed = {tcr.RUNTIME_STEP, tcr.CANDIDATE_STEP}
    assert {e for e, _ in events} <= allowed, events


# ---------------------------------------------------------------------------
# E — event-class fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e1_credit_purchase_is_a_validated_candidate():
    outcome, provider, events = await _run([intake_reply(), decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 2
    assert outcome.candidate["intent"] == "record_credit_purchase"
    assert outcome.candidate["proposal_present"] is True
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_e2_supplier_balance_query_is_a_report_candidate():
    decision = _decision(
        intent="supplier_balance", activity="report", payment_terms=None,
        tools=[{"tool_name": "get_supplier_ledger",
                "arguments": {"supplier_name": "FDS Labs Pvt"}}],
    )
    outcome, provider, events = await _run([
        intake_reply(event_type="report"), decision,
    ])
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 2
    assert outcome.candidate["intent"] == "supplier_balance"
    _assert_observation_only(events)


# ---------------------------------------------------------------------------
# A — settlement / expense fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a1_received_customer_payment_is_a_validated_candidate():
    decision = _decision(
        intent="record_receipt", activity="receipt", payment_terms="CASH",
        tools=[{"tool_name": "record_customer_receipt",
                "arguments": {"customer_id": _UUID, "amount": 45000}}],
    )
    outcome, provider, events = await _run([
        intake_reply(event_type="settlement"), decision,
    ])
    assert outcome.status == tcr.CANDIDATE_READY
    assert outcome.candidate["intent"] == "record_receipt"
    assert provider.calls == 2
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_a2_cash_expense_is_a_validated_candidate():
    decision = _decision(
        intent="record_expense", activity="expense", payment_terms="CASH",
        tools=[{"tool_name": "create_expense",
                "arguments": {"description": "Office supplies",
                              "subtotal": 12000}}],
    )
    outcome, provider, events = await _run([intake_reply(), decision])
    assert outcome.status == tcr.CANDIDATE_READY
    assert outcome.candidate["intent"] == "record_expense"
    _assert_observation_only(events)


# ---------------------------------------------------------------------------
# R — refusal fixtures (unsafe / destructive requests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r1_disguised_personal_expense_is_refused():
    decision = _decision(
        intent="record_expense", activity="expense", tools=None,
        refusal={"reason": "The purchase is a personal expense booked through "
                           "the business — recording it would misstate the "
                           "accounts.",
                 "safe_alternative": "Reimburse the owner personally or use a "
                                     "drawings account."},
    )
    outcome, provider, events = await _run([intake_reply(), decision])
    assert outcome.status == tcr.CANDIDATE_REFUSAL
    assert outcome.refusal and outcome.refusal.get("reason")
    assert outcome.candidate is None
    assert provider.calls == 2
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_r2_destructive_chart_of_accounts_request_is_refused():
    decision = _decision(
        intent="record_adjustment", activity="expense", tools=None,
        refusal={"reason": "Deleting accounts from the chart would destroy "
                           "posted history; the platform does not support it.",
                 "safe_alternative": "Deactivate the account instead of "
                                     "deleting it."},
    )
    outcome, provider, events = await _run([intake_reply(), decision])
    assert outcome.status == tcr.CANDIDATE_REFUSAL
    assert outcome.candidate is None
    _assert_observation_only(events)


# ---------------------------------------------------------------------------
# P — posting fixtures (candidate proposals, never executed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p1_cash_sale_is_a_validated_candidate():
    decision = _decision(
        intent="record_cash_sale", activity="sale", payment_terms="CASH",
        tools=[{"tool_name": "record_cash_sale",
                "arguments": {"total": 25000}}],
    )
    outcome, provider, events = await _run([intake_reply(), decision])
    assert outcome.status == tcr.CANDIDATE_READY
    assert outcome.candidate["intent"] == "record_cash_sale"
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_p2_manual_journal_is_a_validated_candidate():
    decision = _decision(
        intent="record_adjustment", activity="expense",
        tools=[{"tool_name": "prepare_journal", "arguments": {
            "transaction_date": "2026-09-29",
            "description": "Manual reclassification fixture",
            "lines": [
                {"account": "Office Expense", "debit": 100, "credit": 0},
                {"account": "Cash", "debit": 0, "credit": 100},
            ],
        }}],
    )
    outcome, provider, events = await _run([intake_reply(), decision])
    assert outcome.status == tcr.CANDIDATE_READY
    assert outcome.candidate["intent"] == "record_adjustment"
    _assert_observation_only(events)


# ---------------------------------------------------------------------------
# C — already-recorded fixture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c1_already_recorded_transaction_is_complete_not_reposted():
    outcome, provider, events = await _run(
        [intake_reply(), decision_reply(complete=True, proposal=False)]
    )
    assert outcome.status == tcr.CANDIDATE_COMPLETE
    assert outcome.candidate is None       # nothing proposed, nothing posted
    assert provider.calls == 2
    _assert_observation_only(events)

# ---------------------------------------------------------------------------
# Ambiguity / missing-entity fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ambiguous_payment_parks_at_call1_questionnaire():
    """Settlement vs advance is a FACT question — Call 1 asks, Call 2 waits."""
    question = {
        "text": "Was this received against an existing invoice or as an advance?",
        "questions": [{"field": "settlement_position", "kind": "choice",
                       "question": "Against an invoice or as an advance?",
                       "options": ["Against an invoice", "As an advance"]}],
    }
    outcome, provider, events = await _run(
        [intake_reply(event_type="settlement", question=question)]
    )
    assert outcome.status == tcr.AWAITING_CLARIFICATION
    assert provider.calls == 1              # Call 2 never ran
    assert outcome.required_fields == ["settlement_position"]
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_missing_customer_routes_a_user_fact_through_call1():
    """Call 2 states the need; Call 1 AUTHORS the question (§13)."""
    asked = decision_reply(proposal=False, needs=[{
        "kind": "USER_FACT", "name": "customer_name",
        "why_required": "The receipt must be attributed to a customer.",
    }])
    question = {
        "text": "Which customer sent this payment?",
        "questions": [{"field": "customer_name", "kind": "text",
                       "question": "Which customer sent this payment?"}],
    }
    outcome, provider, events = await _run(
        [intake_reply(event_type="settlement"), asked,
         intake_reply(question=question)]
    )
    assert outcome.status == tcr.AWAITING_CLARIFICATION
    assert provider.calls == 3
    assert outcome.required_fields == ["customer_name"]
    # the wording is CALL 1's — Call 2 never authored it
    assert "Which customer" in outcome.question["text"]
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_missing_supplier_is_a_candidate_prerequisite_not_a_creation():
    """§16: prerequisite = CANDIDATE requirement — Stage 3 creates nothing."""
    decision = _decision(
        intent="record_credit_purchase",
        prerequisites=[{"name": "supplier", "status": "missing",
                        "resolution": "create",
                        "why": "No supplier named FDS Labs Pvt exists."}],
        tools=[{"tool_name": "create_purchase_bill",
                "arguments": {"supplier_name": "FDS Labs Pvt",
                              "total": 450000}}],
    )
    outcome, provider, events = await _run([intake_reply(), decision])
    assert outcome.status == tcr.CANDIDATE_READY
    assert outcome.candidate["prerequisites"] == 1
    # recorded as a candidate requirement only — no create_supplier tool ran
    assert "create_supplier" not in outcome.candidate["tools"]
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_missing_account_is_a_candidate_prerequisite_not_a_creation():
    decision = _decision(
        intent="record_expense", activity="expense",
        prerequisites=[{"name": "account", "status": "missing",
                        "resolution": "create",
                        "why": "No ledger exists for this expense."}],
        tools=[{"tool_name": "create_expense",
                "arguments": {"description": "Mystery cost", "subtotal": 100}}],
    )
    outcome, provider, events = await _run([intake_reply(), decision])
    assert outcome.status == tcr.CANDIDATE_READY
    assert outcome.candidate["prerequisites"] == 1
    assert "create_account" not in outcome.candidate["tools"]
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_ambiguous_ledger_never_takes_a_first_match():
    """Contract B rejects ledger.fit FIRST_MATCH; the model must retry NONE."""
    bad = _decision(
        intent="record_expense", activity="expense",
        ledger={"fit": "FIRST_MATCH", "account_id": None},
        tools=[{"tool_name": "create_expense",
                "arguments": {"description": "Ambiguous cost", "subtotal": 50}}],
    )
    good = _decision(
        intent="record_expense", activity="expense",
        ledger={"fit": "NONE", "account_id": None},
        tools=[{"tool_name": "create_expense",
                "arguments": {"description": "Ambiguous cost", "subtotal": 50}}],
    )
    outcome, provider, events = await _run([intake_reply(), bad, good])
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 3
    assert "ledger" in provider.prompts[2]   # the rejection was fed back
    _assert_observation_only(events)


# ---------------------------------------------------------------------------
# Evidence fixtures (existing books layer + cache; read-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_required_transaction_gathers_then_decides():
    wants = intake_reply(evidence=[{
        "kind": "open_receivables", "why": "match the payment", "args": {}}])
    outcome, provider, events = await _run(
        [wants, intake_reply(), decision_reply()], gather=_gather_fake
    )
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 3              # C1(books) → C1(+evidence) → C2
    assert "open_receivables title" in provider.prompts[1]
    _assert_observation_only(events)


# ---------------------------------------------------------------------------
# Call 2 needs[] routing fixtures (§13, §14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call2_user_fact_requirement_routes_through_call1():
    asked = decision_reply(proposal=False, needs=[{
        "kind": "USER_FACT", "name": "transaction_purpose",
        "why_required": "capital vs operating treatment depends on it",
    }])
    question = {
        "text": "Are the laptops for business use?",
        "questions": [{"field": "transaction_purpose", "kind": "choice",
                       "question": "Business use?",
                       "options": ["Business", "Personal"]}],
    }
    outcome, provider, events = await _run(
        [intake_reply(), asked, intake_reply(question=question)]
    )
    assert outcome.status == tcr.AWAITING_CLARIFICATION
    assert provider.calls == 3
    assert "question" not in (outcome.call2 or {})   # Call 2 authored nothing
    _assert_observation_only(events)


@pytest.mark.asyncio
async def test_call2_evidence_requirement_gathers_then_redecides():
    asked = decision_reply(proposal=False, needs=[{
        "kind": "EVIDENCE", "name": "open_receivables",
        "why_required": "Find which invoice the payment settles.",
        "evidence_request": {"kind": "open_receivables",
                             "why": "identify the invoice",
                             "args": {"party_name": "ABC"}},
    }])
    outcome, provider, events = await _run(
        [intake_reply(), asked, intake_reply(), decision_reply()],
        gather=_gather_fake,
    )
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 4              # C1, C2(need), C1(+books), C2
    assert "open_receivables title" in provider.prompts[2]
    _assert_observation_only(events)

