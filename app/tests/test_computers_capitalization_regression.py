"""End-to-end regression for the production "3 computers" incident
(session ``fda87b21`` / confirmation ``f90ef544``, 2026-09-24).

The incident, restated:

  * plan/confirmation intent = ``record_expense`` (a learned nature
    preference had pinned OPERATING_EXPENSE above the threshold),
  * accounting reasoning proposed ``register_fixed_asset`` (computers,
    67,000, useful life 4y — correctly capitalised),
  * the confirmation froze the mismatch (RC-5),
  * the APPROVAL turn re-seeded the shortlist from the mismatched intent,
    putting the plan's OWN tool into ``excluded_tools`` (RC-1),
  * the executor refused it with the party-duplicate story (RC-2) while
    the REAL prohibition (expense => no capitalisation) mapped to nothing
    (RC-3), and the run FAILED with "Something went wrong".

Three wired flows, all hermetic (process boundaries stubbed; the only
reasoning stage is the patched ``run_reasoning_loop`` — a raising
``get_client`` proves ZERO LLM provider calls):

  A. APPROVED-TURN RESCUE — the frozen plan executes: intent reconciled,
     shortlist never self-blocks, COMPLETED/VERIFIED.
  B. PROPOSAL-TIME FAIL-CLOSED — a plan whose only tool contradicts the
     event profile parks with an accounting-treatment question BEFORE any
     confirmation row exists (FIX-6 wiring).
  C. RECONCILE FORCES CONFIRMATION — a confirmation-class intent revealed
     by reconciliation re-opens the PHASE 5 gate (never silently executed).
"""

import uuid
from unittest.mock import AsyncMock as _AM

import pytest

import app.agent as agent_mod
from app.agent import execute, resume_with_confirmation
from app.models.schemas import (
    ExecutionPlan,
    ExecutionStatus,
    TransactionClassification,
)
from app.accounting_reasoning import PROPOSAL, ReasoningOutcome

ORG = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER = uuid.UUID("55555555-5555-5555-5555-555555555555")
MSG = "i purchased 3 computers from techno it ltd for Rs.67,000"

# The frozen plan from the incident confirmation, minus the model-invented
# ``created_by: "user"`` that separately broke the uuid cast (cash-fix turn).
_ASSET_PLAN = [{
    "tool_name": "register_fixed_asset",
    "arguments": {
        "name": "3 computers",
        "purchase_cost": 67000.0,
        "transaction_date": "2026-09-24",
        "payment_method": "CASH",
        "useful_life_years": 4,
        "depreciation_method": "STRAIGHT_LINE",
    },
}]


class _NoLLM:
    """Any provider call in these tests is a regression (they are all
    deterministic paths — reasoning is the PATCHED loop, never a provider)."""

    async def generate_text(self, *a, **k):
        raise AssertionError("LLM text call in a deterministic test path")

    async def generate_text_light(self, *a, **k):
        raise AssertionError("LLM light call in a deterministic test path")

    async def generate_with_tools(self, *a, **k):
        raise AssertionError("LLM planning call in a deterministic test path")


async def _forbidden(*a, **k):
    raise AssertionError("discarded/prohibited work ran")


class _Ctx:
    """Minimal AgentContext stand-in for the stubbed build_context."""

    def __init__(self, entities):
        self.extracted_entities = dict(entities)
        self.relevant_customers = []
        self.relevant_suppliers = []
        self.relevant_bank_accounts = []
        self.relevant_accounts = []
        self.relevant_products = []
        self.live_evidence = []
        self.organization = {}
        self.classification = None
        self.economic_event = ""
        self.impact_map = {}
        self.prohibited_actions = []


def _world(
    monkeypatch,
    *,
    approved: bool,
    planner_intent: str,
    potential_tools: list,
    requires_confirmation: bool,
    classify_nature,
    classify_clarification: bool,
):
    """Shared hermetic world (approved-harness pattern)."""
    session = {
        "id": str(uuid.uuid4()),
        "organization_id": str(ORG),
        "user_id": str(USER),
        "user_request": MSG,
        "conversation_id": "conv-rc",
        "status": "WAITING_FOR_USER",
        "current_phase": "AWAITING_CONFIRMATION" if approved else "RUNNING",
    }
    recorded = {
        "session": session,
        "steps": [],
        "results": [],
        "tool_runs": [],
        "tool_calls": [],
        "clarifications": [],
        "confirmations": [],
    }

    async def fake_fetch_one(table, filters=None, **kw):
        if not getattr(fake_fetch_one, "seen", False):
            fake_fetch_one.seen = True
            return session
        return None

    async def fake_fetch_many(table, filters=None, **kw):
        if approved and table == "ai_confirmations":
            return [{
                "id": "conf-1",
                "execution_session_id": session["id"],
                "user_confirmed": None,
                "action_type": "record_expense",   # the POISONED action_type
                "plan": _ASSET_PLAN,
            }]
        return []

    async def fake_execute_planned(tool_calls, executor):
        out = []
        for tc in tool_calls:
            recorded["tool_runs"].append((tc.tool_name, dict(tc.arguments or {})))
            out.append({
                "success": True,
                "tool_name": tc.tool_name,
                "data": {"id": "asset-ok"},
            })
        return out

    async def fake_create_result(**kw):
        recorded["results"].append(kw)
        return {"id": f"res-{len(recorded['results'])}"}

    async def fake_log_step(session_id, step_type, data):
        recorded["steps"].append((session_id, step_type, data))

    async def fake_log_tool_call(**kw):
        recorded["tool_calls"].append(kw)
        return {"id": f"tc-{len(recorded['tool_calls'])}"}

    async def fake_verify_journal(**kw):
        return {"verified": True}

    async def fake_create_clarification(**kw):
        recorded["clarifications"].append(kw)
        return {"id": "cl-x", "question": kw.get("question", "")}

    async def fake_create_confirmation(**kw):
        recorded["confirmations"].append(kw)
        return {"id": f"conf-{len(recorded['confirmations'])}"}

    async def fake_classify(**kw):
        # The NATURE the 3d profile refines from.  None = the post-FIX-4b
        # incident reality (durable item, preference skipped, unclassified).
        return TransactionClassification(
            transaction_nature=classify_nature,
            confidence="HIGH" if classify_nature else "MEDIUM",
            source="DETERMINISTIC_RULE" if classify_nature else "INFERENCE",
            requires_clarification=classify_clarification,
        )

    def fake_planner(*args, **kwargs):
        return ExecutionPlan(
            intent=planner_intent,
            entity_type=(
                "fixed_asset" if planner_intent == "register_fixed_asset"
                else "expense"
            ),
            entity_name=None,
            potential_tools=list(potential_tools),
            requires_validation=True,
            requires_accounting_engine=True,
            requires_confirmation=requires_confirmation,
            requires_clarification=False,
            missing_fields=[],
            clarification_questions=[],
            expected_outcome="Record the computers acquisition",
            extracted_entities={
                "amount": 67000,
                "item_description": "3 computers",
            },
            economic_event="EXPENDITURE",
            impact_map={},
            prohibited_actions=[],
            transaction_nature=classify_nature,
            transaction_nature_source=(
                "USER_ANSWER" if classify_nature else None
            ),
            batch_items=None,
        )

    async def _no_label(account_id):
        return None

    _stubs = dict(
        fetch_one=fake_fetch_one, fetch_many=fake_fetch_many,
        execute_planned=fake_execute_planned, create_result=fake_create_result,
        log_step=fake_log_step, log_tool_call=fake_log_tool_call,
        create_clarification=fake_create_clarification,
        create_confirmation=fake_create_confirmation,
        verify_journal=fake_verify_journal, classify=fake_classify,
        planner=fake_planner, no_label=_no_label,
    )
    _install(monkeypatch, session, _stubs)
    return recorded


def _install(monkeypatch, session, s: dict):
    """Patch every process boundary (approved-harness pattern)."""
    monkeypatch.setattr(agent_mod, "fetch_one", s["fetch_one"])
    monkeypatch.setattr(agent_mod, "fetch_many", s["fetch_many"])
    monkeypatch.setattr(
        agent_mod, "create_execution_session", _AM(return_value=session),
    )
    monkeypatch.setattr(
        agent_mod, "_close_superseded_sessions", _AM(return_value=0),
    )
    monkeypatch.setattr(agent_mod, "seed_clarification_history", _AM())
    monkeypatch.setattr(agent_mod, "_load_org_preferences", _AM(return_value={}))
    monkeypatch.setattr(
        agent_mod, "resolve_confirmation", _AM(return_value={"id": "conf-1"}),
    )
    monkeypatch.setattr(
        agent_mod, "get_clarification_history", _AM(return_value=[]),
    )
    monkeypatch.setattr(agent_mod, "_update_status", _AM())
    monkeypatch.setattr(agent_mod, "_log_step", s["log_step"])
    monkeypatch.setattr(agent_mod, "log_tool_call", s["log_tool_call"])
    monkeypatch.setattr(agent_mod, "flush_step_logs", _AM())
    monkeypatch.setattr(
        agent_mod, "create_clarification", s["create_clarification"],
    )
    monkeypatch.setattr(
        agent_mod, "create_confirmation", s["create_confirmation"],
    )
    monkeypatch.setattr(agent_mod, "create_execution_result", s["create_result"])
    monkeypatch.setattr(
        agent_mod, "execute_planned_tool_calls", s["execute_planned"],
    )
    monkeypatch.setattr(agent_mod, "verify_journal", s["verify_journal"])
    monkeypatch.setattr(
        agent_mod, "_make_account_label_resolver", lambda org: s["no_label"],
    )
    monkeypatch.setattr(agent_mod, "get_client", lambda: _NoLLM())
    monkeypatch.setattr(agent_mod, "run_planner", s["planner"])
    monkeypatch.setattr("app.classifier.classify_transaction", s["classify"])
    monkeypatch.setattr(
        "app.services.preference_service.record_answer_preference", _AM(),
    )
    monkeypatch.setattr(
        agent_mod, "build_context",
        _AM(return_value=_Ctx(
            {"amount": 67000, "item_description": "3 computers"},
        )),
    )
    for gate in (
        "_party_resolution_question",
        "_settlement_check_question",
        "_catalog_check_question",
        "_revenue_ledger_review_gate",
    ):
        monkeypatch.setattr(agent_mod, gate, _AM(return_value=None))
    monkeypatch.setattr(
        "app.accounting_reasoning.run_reasoning_loop",
        _AM(return_value=ReasoningOutcome(
            status="UNSUPPORTED",
            understanding={"economic_event": "asset acquisition"},
            rounds=1,
        )),
    )


# ---------------------------------------------------------------------- A --
@pytest.mark.asyncio
async def test_approved_turn_rescues_the_poisoned_confirmation(monkeypatch):
    """FIX-1 + FIX-5 end-to-end: the approved register_fixed_asset plan
    living under confirmed action_type record_expense now EXECUTES."""
    rec = _world(
        monkeypatch,
        approved=True,
        planner_intent="record_expense",
        potential_tools=["create_expense", "classify_expense"],
        requires_confirmation=True,
        classify_nature=None,               # post-FIX-4b reality
        classify_clarification=True,        # arms the E7 skip guard
    )

    response = await resume_with_confirmation(
        session_id=uuid.UUID(rec["session"]["id"]),
        approved=True,
        user_id=USER,
        organization_id=ORG,
    )

    step_names = [s[1] for s in rec["steps"]]
    step_data = {s[1]: s[2] for s in rec["steps"]}

    # The plan RAN (the incident: FAILED + "duplicate party" refusal).
    assert response.status == ExecutionStatus.COMPLETED, response.summary
    assert "APPROVED_PLAN_REUSED" in step_names
    assert [t for t, _ in rec["tool_runs"]] == ["register_fixed_asset"]

    # FIX-5: the intent was reconciled with the planned tools...
    planning_steps = [s[2] for s in rec["steps"] if s[1] == "PLANNING"]
    reconciled = [
        p for p in planning_steps
        if p.get("source") == "intent_tool_reconcile"
    ]
    assert reconciled, "the intent/tool mismatch was never reconciled"
    assert reconciled[0]["intent_before"] == "record_expense"
    assert reconciled[0]["intent_after"] == "register_fixed_asset"
    assert step_data["APPROVED_PLAN_REUSED"]["tools"] == ["register_fixed_asset"]

    # ...and NOTHING parked or refused it: no clarifications, no FAILED,
    # no fabricated party story anywhere in the durable timeline.
    assert rec["clarifications"] == []
    assert "AWAITING_CLARIFICATION" not in step_names
    assert "FAILED" not in step_names
    for _sid, _type, data in rec["steps"]:
        assert "already found for this party" not in str(data)


# ---------------------------------------------------------------------- B --
@pytest.mark.asyncio
async def test_proposal_conflict_fails_closed_before_confirmation(monkeypatch):
    """FIX-6 wiring: reasoning proposes register_fixed_asset for an
    expense-classified event -> accounting-treatment question, NO
    confirmation row, NO execution (the incident froze exactly this)."""
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_expense",
        potential_tools=["create_expense", "classify_expense"],
        requires_confirmation=False,
        classify_nature="OPERATING_EXPENSE",   # 3d adds the prohibition
        classify_clarification=True,           # gate must NOT park first
    )
    # reasoning proposes the asset tool (the incident's proposal):
    _asset_outcome = ReasoningOutcome(
        status=PROPOSAL,
        understanding={"economic_event": "asset acquisition"},
        proposal={
            "interpretation": "Purchase of 3 computers for cash",
            "affected_records": ["Fixed assets", "Cash"],
            "accounting_impact": [
                {"account": "Computer Equipment", "debit": 67000, "credit": 0},
                {"account": "Cash", "debit": 0, "credit": 67000},
            ],
            "not_affected": ["Inventory"],
            "unresolved_uncertainty": [],
            "tools": [{
                "tool_name": "register_fixed_asset",
                "arguments": dict(_ASSET_PLAN[0]["arguments"]),
            }],
            "confirmation": "Register 3 computers for Rs.67,000?",
        },
        rounds=1,
    )
    monkeypatch.setattr(
        "app.accounting_reasoning.run_reasoning_loop",
        _AM(return_value=_asset_outcome),
    )
    # a confirmation or an execution here = the incident replayed:
    async def _confirmation_bomb(**kw):
        raise AssertionError(
            "FIX-6: a doomed plan was frozen into a confirmation",
        )

    async def _execution_bomb(tool_calls, executor):
        raise AssertionError("FIX-6: a prohibited plan reached execution")

    monkeypatch.setattr(agent_mod, "create_confirmation", _confirmation_bomb)
    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", _execution_bomb)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-rc-b",
    )

    assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert "accounting_treatment" in (response.required_information or [])
    assert response.question and "register_fixed_asset" in response.question
    # the durable question names the blocked tool and its reason:
    clash_steps = [
        s[2] for s in rec["steps"]
        if s[1] == "AWAITING_CLARIFICATION"
        and s[2].get("source") == "intent_tool_conflict"
    ]
    assert clash_steps, "the conflict was not surfaced durably"
    assert "register_fixed_asset" in clash_steps[0]["blocked_tools"]
    assert rec["clarifications"], "no clarification row was persisted"
    assert rec["tool_runs"] == []


# ---------------------------------------------------------------------- C --
@pytest.mark.asyncio
async def test_reconcile_reopens_the_confirmation_gate(monkeypatch):
    """FIX-5 safety net: when reconciliation reveals a confirmation-class
    intent under a non-confirmation plan, PHASE 5 opens (AWAITING_
    CONFIRMATION with the RECONCILED action_type) — never a silent
    execution of an unauthorized financial mutation."""
    rec = _world(
        monkeypatch,
        approved=False,
        planner_intent="record_expense",
        potential_tools=["create_expense", "classify_expense"],
        requires_confirmation=False,           # the mismatch being fixed
        classify_nature=None,                  # no prohibition -> no conflict
        classify_clarification=False,
    )

    class _TC:  # duck-typed ToolCall (avoids importing pydantic plumbing)
        def __init__(self, tool_name, arguments):
            self.tool_name = tool_name
            self.arguments = dict(arguments)

    monkeypatch.setattr(
        agent_mod, "_deterministic_mutation_calls",
        _AM(return_value=[_TC("register_fixed_asset",
                              dict(_ASSET_PLAN[0]["arguments"]))]),
    )

    # no execution may happen before authorization:
    async def _execution_bomb(tool_calls, executor):
        raise AssertionError("an unauthorized financial mutation executed")

    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", _execution_bomb)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-rc-c",
    )

    assert response.status == ExecutionStatus.AWAITING_CONFIRMATION
    assert response.confirmation_required is True
    assert rec["confirmations"], "no confirmation was raised"
    assert rec["confirmations"][0]["action_type"] == "register_fixed_asset"
    step_names = [s[1] for s in rec["steps"]]
    assert "AWAITING_CONFIRMATION" in step_names
    assert rec["tool_runs"] == []
