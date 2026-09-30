"""The FIRST call carries everything: analysis + the written questionnaire.

The requirement (user): the Token Harbor reasoning request must not only
decide *whether* to ask — it must WRITE the questions itself, in the fixed
JSON format with quick tap-ready answers, in the SAME response that carries
the analysis.  No authoring round-trip, no Python template.

Pinned here:

  1. the contract (`_RESPONSE_SHAPE`) demands the questionnaire in the same
     response, mandates tap-ready options, and forbids a proposal while
     material facts are open;
  2. `validate_outcome` ENFORCES that rule — a proposal carrying open
     missing facts is a violation, fed back to the model within the round
     budget (never repaired by a second pipeline stage);
  3. the agent's NEEDS_INPUT return runs AFTER `run_planner` binds
     `execution_plan` — before this move the branch referenced
     execution_plan BEFORE its binding (latent NameError that silently
     killed every authored single-call questionnaire);
  4. full agent-level proof: a NEEDS_INPUT outcome returns the authored
     questionnaire with ZERO provider calls beyond the reasoning loop
     (any extra call lands on `_NoLLM` and raises).
"""

import inspect

from unittest.mock import AsyncMock as _AM

import pytest

import app.agent as agent_mod
from app.accounting_reasoning import (
    PROPOSAL,
    _RESPONSE_SHAPE,
    NEEDS_INPUT,
    ReasoningOutcome,
    validate_outcome,
)
from app.agent import execute
from app.models.schemas import ExecutionStatus
from test_computers_capitalization_regression import ORG, USER, MSG, _world


def test_contract_demands_questions_in_the_same_response():
    # one output: understanding + missing facts + questions
    assert "ONE output; question-writing is" in _RESPONSE_SHAPE
    assert "never deferred to another call" in _RESPONSE_SHAPE
    # quick actionable answers (tap chips) on every finite choice
    assert "quick, actionable answers the user can tap" in _RESPONSE_SHAPE
    # a proposal with open material facts is invalid
    assert "a proposal is INVALID" in _RESPONSE_SHAPE


def test_proposal_with_open_material_facts_is_violated():
    outcome = ReasoningOutcome(
        status=PROPOSAL,
        proposal={
            "interpretation": "buy a car",
            "tools": [{"tool_name": "create_purchase", "arguments": {}}],
        },
        missing_facts=[
            {
                "fact": "cash or credit",
                "why_material": "decides payable vs immediate payment",
                "question": "cash or credit?",
            }
        ],
        rounds=1,
    )
    violations = validate_outcome(outcome, offered_tools=["create_purchase"])
    assert any("SAME response" in v for v in violations), violations


def test_proposal_without_open_facts_is_not_hit_by_the_single_call_rule():
    outcome = ReasoningOutcome(
        status=PROPOSAL,
        proposal={
            "interpretation": "buy a car",
            "tools": [{"tool_name": "create_purchase", "arguments": {}}],
        },
        missing_facts=[],
        rounds=1,
    )
    violations = validate_outcome(outcome, offered_tools=["create_purchase"])
    assert not any("SAME response" in v for v in violations)


def test_needs_input_return_runs_after_the_planner_bind():
    """execution_plan must be BOUND before the authored-questionnaire return.

    The branch historically referenced execution_plan.intent/extracted_
    entities while it was still unbound (planner runs ~60 lines later) —
    a NameError fired on every NEEDS_INPUT turn, so the model-authored
    single-call questionnaire NEVER reached the user.
    """
    src = inspect.getsource(agent_mod.execute)
    bind = src.index("execution_plan = run_planner(")
    branch = src.index("_reasoning.status == _R_NEEDS_INPUT")
    assert bind < branch, (
        "the NEEDS_INPUT return must run AFTER run_planner binds execution_plan"
    )


@pytest.mark.asyncio
async def test_needs_input_returns_the_authored_questionnaire_single_call(
    monkeypatch,
):
    """The first call's OWN questionnaire reaches the user — ONE round-trip.

    The reasoning outcome arrives with the authored fixed-format
    ``questions[]``; the agent must return them (validated against the
    planner's entities) instead of crashing on the unbound
    ``execution_plan`` (the pre-move NameError) or falling through to the
    planner's template.  The world's ``get_client`` raises on ANY provider
    use, so a second call would fail the test outright.
    """
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase", "classify_expense"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    # The accounting-reasoning stage ships OFF in the presentation profile
    # (app/config.py "PRESENTATION PROFILE"); this test pins the SINGLE-CALL
    # questionnaire wiring, so enable the stage it exercises.
    from app.config import get_settings as _get_settings

    monkeypatch.setattr(_get_settings(), "accounting_reasoning_enabled", True)
    monkeypatch.setattr(
        "app.accounting_reasoning.run_reasoning_loop",
        _AM(
            return_value=ReasoningOutcome(
                status=NEEDS_INPUT,
                understanding={"economic_event": "asset acquisition"},
                question={
                    "text": (
                        "I can post this once two things are settled:\n"
                        "1. Was the 67,000 paid in cash or on credit?\n"
                        "2. Is this a long-term fleet asset or a running cost?"
                    ),
                    "questions": [
                        {
                            "field": "payment_type",
                            "kind": "choice",
                            "question": (
                                "Was the 67,000 paid in cash or on credit?"
                            ),
                            "options": [
                                {"value": "CASH", "label": "Cash"},
                                {"value": "CREDIT", "label": "On credit"},
                            ],
                        },
                        {
                            "field": "transaction_nature",
                            "kind": "choice",
                            "question": (
                                "Is this a long-term fleet asset or a running cost?"
                            ),
                            "options": [
                                {"value": "FIXED_ASSET", "label": "Long-term asset"},
                                {
                                    "value": "OPERATING_EXPENSE",
                                    "label": "Running cost",
                                },
                            ],
                        },
                    ],
                },
                missing_facts=[
                    {
                        "fact": "payment method",
                        "why_material": "decides payable vs immediate payment",
                        "question": "?",
                    },
                    {
                        "fact": "item nature",
                        "why_material": "decides the ledger",
                        "question": "?",
                    },
                ],
                rounds=1,
            )
        ),
    )

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-single-call",
    )

    # The authored questionnaire from the FIRST call — not the template.
    assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert response.questionnaire is not None
    assert response.questionnaire["source"] == "reasoning_llm"
    fields = [q["field"] for q in response.questionnaire["questions"]]
    assert fields == ["payment_type", "transaction_nature"]
    assert (
        response.questionnaire["questions"][0]["options"][0]["value"] == "CASH"
    )
    # tap chips index-aligned with the numbered lines
    assert response.question_options
    assert response.question_options[0][0].value == "CASH"
    # the model's own wording, verbatim
    assert "cash or on credit" in (response.question or "")
    # required = the missing facts the question resolves
    assert response.required_information == ["payment method", "item nature"]
    assert rec["clarifications"], "the clarification row was not persisted"
