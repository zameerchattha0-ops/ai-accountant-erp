"""Stage 3 — agent-level flag gating (§25, §18, §2).

Pinned invariants:
* ``TWO_CALL_RUNTIME_ENABLED`` defaults OFF and is a DIFFERENT setting from
  ``TWO_CALL_OBSERVATION_ENABLED`` (Stage 2) — neither repurposes the other.
* flag OFF  → the existing monolithic path is unchanged: the two-call
  runtime is never entered, the reasoning loop runs exactly as before.
* flag ON   → the REAL runtime runs (Call 1 prompt + Call 2 prompt through
  the existing orchestrator), the monolithic reasoning loop is NEVER invoked
  (no hidden fallback, §18) and NOTHING executes: no confirmation row, no
  tool execution, no account/customer/supplier creation.
* candidate completion parks/fails through the EXISTING clarification and
  status machinery — no new persistence surface.
"""

import asyncio
from unittest.mock import AsyncMock as _AM

import pytest

import app.agent as agent_mod
from app.agent import execute
from app.config import Settings, get_settings
from app.models.schemas import ExecutionStatus
from app.two_call_runtime import AWAITING_CLARIFICATION, FAILED, TwoCallOutcome
from test_computers_capitalization_regression import ORG, USER, MSG, _world
from test_two_call_runtime import _Scripted, decision_reply, intake_reply


def _flag(monkeypatch, value: bool) -> None:
    """Toggle the Stage 3 flag on the cached settings object (conftest style)."""
    monkeypatch.setattr(get_settings(), "two_call_runtime_enabled", value)


async def _forbidden(*a, **k):
    raise AssertionError("the monolithic path must not run while the flag is ON")


# ---------------------------------------------------------------------------
# §1 — the flag itself: default OFF, separate from the observation flag
# ---------------------------------------------------------------------------


def test_runtime_flag_defaults_off_and_is_separate_from_observation_flag():
    assert Settings.model_fields["two_call_runtime_enabled"].default is False
    assert Settings.model_fields["two_call_observation_enabled"].default is False
    assert get_settings().two_call_runtime_enabled is False
    # two DISTINCT settings — one flag can be toggled without touching the other
    assert "two_call_runtime_enabled" != "two_call_observation_enabled"


def test_missing_flag_attribute_is_fail_closed():
    assert agent_mod._two_call_runtime_enabled(object()) is False


# ---------------------------------------------------------------------------
# flag OFF — existing path unchanged (§I)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_never_enters_the_two_call_runtime(monkeypatch):
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, False)

    async def _runtime_bomb(**kw):
        raise AssertionError("two-call runtime entered while the flag is OFF")

    monkeypatch.setattr("app.two_call_runtime.run_two_call_runtime", _runtime_bomb)

    # the existing reasoning loop runs exactly as before
    from app.accounting_reasoning import NEEDS_INPUT, ReasoningOutcome

    legacy = _AM(return_value=ReasoningOutcome(
        status=NEEDS_INPUT,
        understanding={"economic_event": "purchase"},
        question={"text": "Cash or credit?", "questions": []},
        missing_facts=[{"fact": "payment terms", "why_material": "x", "question": "?"}],
        rounds=1,
    ))
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", legacy)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-flag-off",
    )

    assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert legacy.await_count == 1          # the monolithic path RAN

# ---------------------------------------------------------------------------
# flag ON — Call 1 + Call 2 invoked; candidate only; NO fallback (§B, §18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_runs_call1_and_call2_and_stops_as_candidate(monkeypatch):
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, True)
    provider = _Scripted([intake_reply(), decision_reply()])
    monkeypatch.setattr(agent_mod, "get_client", lambda: provider)
    # §18: the legacy interpreter may NOT secretly rescue this path.
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)
    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", _forbidden)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-flag-on",
    )
    await asyncio.sleep(0.05)               # let spawned step writes land

    # Call 1 AND Call 2 both ran through the existing orchestrator
    assert provider.calls == 2
    assert "TWO-CALL" in provider.prompts[0]           # Call 1 role prompt
    assert "CALL 2" in provider.prompts[1]             # Call 2 role prompt

    # candidate only — nothing executed, nothing created, nothing confirmed
    assert response.status == ExecutionStatus.COMPLETED
    assert "nothing was executed" in response.summary
    assert rec["tool_runs"] == []
    assert rec["confirmations"] == []
    assert rec["clarifications"] == []
    step_names = [s[1] for s in rec["steps"]]
    assert "STAGE3_CANDIDATE_ONLY" in step_names
    assert "EXECUTING" not in step_names and "VALIDATING" not in step_names



@pytest.mark.asyncio
async def test_flag_on_clarification_parks_via_existing_mechanism(monkeypatch):
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, True)
    provider = _Scripted([
        intake_reply(question={
            "text": "Was this payment received against an invoice?",
            "questions": [{"field": "settlement_position", "kind": "text",
                           "question": "Against an invoice or as an advance?"}],
        }),
    ])
    monkeypatch.setattr(agent_mod, "get_client", lambda: provider)
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-flag-park",
    )

    assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert provider.calls == 1              # Call 1 only — no Call 2
    assert rec["clarifications"], "the existing clarification row was persisted"
    assert response.requires_user_input is True
    assert rec["confirmations"] == [] and rec["tool_runs"] == []


@pytest.mark.asyncio
async def test_flag_on_failure_is_honest_without_legacy_fallback(monkeypatch):
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, True)
    provider = _Scripted(["not json at all"])   # Call 1 unparseable → FAILED
    monkeypatch.setattr(agent_mod, "get_client", lambda: provider)
    # §18: a failed candidate path must NOT fall back to the monolith.
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-flag-fail",
    )

    assert response.status == ExecutionStatus.FAILED
    assert provider.calls == 1
    assert rec["tool_runs"] == [] and rec["confirmations"] == []


@pytest.mark.asyncio
async def test_flag_on_park_outcome_reuses_the_existing_session(monkeypatch):
    """The translator records candidates only — no new persistence surface."""
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, True)

    async def _runtime(**kw):
        return TwoCallOutcome(
            status=AWAITING_CLARIFICATION,
            question={"text": "Which invoice?", "questions": []},
            required_fields=["invoice_id"],
        )

    monkeypatch.setattr("app.two_call_runtime.run_two_call_runtime", _runtime)
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)
    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", _forbidden)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-flag-map",
    )

    assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert response.execution_id is not None  # EXISTING session reused
    assert rec["confirmations"] == [] and rec["tool_runs"] == []


@pytest.mark.asyncio
async def test_flag_on_failed_outcome_is_failed_not_fallback(monkeypatch):
    _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, True)

    async def _runtime(**kw):
        return TwoCallOutcome(status=FAILED, reason="decision_attempts_exhausted")

    monkeypatch.setattr("app.two_call_runtime.run_two_call_runtime", _runtime)
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-flag-failed",
    )

    assert response.status == ExecutionStatus.FAILED
    assert "Nothing was recorded" in response.summary


# ---------------------------------------------------------------------------
# §3 — the FOUR flag combinations (observation must never drive the runtime)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observation_on_runtime_off_does_not_activate_the_runtime(
    monkeypatch,
):
    """Combination 2: observation ON must not switch the runtime on."""
    _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    monkeypatch.setattr(get_settings(), "two_call_observation_enabled", True)
    _flag(monkeypatch, False)

    async def _runtime_bomb(**kw):
        raise AssertionError("observation flag activated the two-call runtime")

    monkeypatch.setattr("app.two_call_runtime.run_two_call_runtime", _runtime_bomb)

    from app.accounting_reasoning import NEEDS_INPUT, ReasoningOutcome

    legacy = _AM(return_value=ReasoningOutcome(
        status=NEEDS_INPUT,
        understanding={"economic_event": "purchase"},
        question={"text": "Cash or credit?", "questions": []},
        missing_facts=[{"fact": "payment terms", "why_material": "x", "question": "?"}],
        rounds=1,
    ))
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", legacy)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-obs-on-runtime-off",
    )

    assert legacy.await_count == 1          # legacy path ran, as when both OFF
    assert response.status == ExecutionStatus.AWAITING_CLARIFICATION


@pytest.mark.asyncio
async def test_runtime_on_does_not_require_the_observation_flag(monkeypatch):
    """Combination 3: runtime ON + observation OFF (its default) still runs."""
    _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, True)
    # observation stays at its default OFF — the runtime must not need it
    assert get_settings().two_call_observation_enabled is False

    provider = _Scripted([intake_reply(), decision_reply()])
    monkeypatch.setattr(agent_mod, "get_client", lambda: provider)
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-runtime-on-obs-off",
    )
    await asyncio.sleep(0.05)

    assert provider.calls == 2              # both calls ran without observation
    assert response.status == ExecutionStatus.COMPLETED
    assert "nothing was executed" in response.summary


# ---------------------------------------------------------------------------
# §12 — the clarification loop across turns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_two_keeps_the_original_facts_in_call1(monkeypatch):
    """§12 turn 2: the answer reaches CALL 1 in the SAME conversation.

    Pins that a resumed turn (a) carries the prior Q&A into the intake role so
    nothing is re-asked or lost, (b) still runs BOTH calls through the existing
    orchestrator, and (c) remains candidate-only — no unrelated execution, no
    tool run, no confirmation row.
    """
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_purchase",
        potential_tools=["create_purchase_bill"],
        requires_confirmation=False,
        classify_nature=None,
        classify_clarification=False,
    )
    _flag(monkeypatch, True)
    provider = _Scripted([intake_reply(), decision_reply()])
    monkeypatch.setattr(agent_mod, "get_client", lambda: provider)
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)
    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", _forbidden)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-turn-two",
        clarification_history=[
            {"question": "What is the amount?", "answer": "450000"},
        ],
    )
    await asyncio.sleep(0.05)

    # (a) the prior answer is IN the intake prompt — facts are preserved
    call1_prompt = provider.prompts[0]
    assert "Question/answer history" in call1_prompt
    assert "450000" in call1_prompt
    # (b) one conversation runs both calls
    assert provider.calls == 2
    assert "TWO-CALL" in call1_prompt and "CALL 2" in provider.prompts[1]
    # (c) candidate only — nothing executed, nothing confirmed
    assert response.status == ExecutionStatus.COMPLETED
    assert "nothing was executed" in response.summary
    assert rec["tool_runs"] == [] and rec["confirmations"] == []

