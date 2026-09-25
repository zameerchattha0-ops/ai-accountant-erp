"""P0-① (forensic latency report): approved-plan turns short-circuit.

``resume_with_confirmation`` re-enters ``execute()`` with the FROZEN plan
snapshot (migration 079).  Before this change the approved turn STILL ran the
accounting-reasoning loop (10-30s of discarded LLM rounds), the semantic
layer (a second LLM interpretation), the 12-query domain context build (Phase
4 — its only reader — is skipped) and every clarification gate — then
discarded all of it at the ``approved_tool_calls`` reuse branch.  Beyond the
dead latency, that dead work could park or REJECT a run the user had ALREADY
approved: a NEEDS_INPUT/REFUSAL from the doomed reasoning round (or any
gate/questionnaire question) returns BEFORE the reuse branch.

Pinned invariants:
* ZERO LLM provider calls on an approved turn (all raise on invocation).
* ``build_context`` (the domain fetch) is never invoked.
* No clarification/confirmation can be raised — the approved run EXECUTES
  through real materialization (contract validation stays ON), the frozen
  tools, and Phase 7/8 verification.
* classification still RUNS (its nature refines the prohibited-tools guard)
  but its question can never park the approved plan.
* ``confirmed_intent``: verification keys on the confirmation's
  ``action_type`` even when the keyword planner re-derives nothing.
"""

import uuid
from unittest.mock import AsyncMock as _AM

import pytest

import app.agent as agent_mod
from app.agent import resume_with_confirmation
from app.models.schemas import ExecutionPlan, ExecutionStatus, TransactionClassification

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
MSG = "create invoice for ABC Furnitures for 2 chairs amounting to 25000"


class _NoLLM:
    """Any provider call on an approved turn is a P0-① regression."""

    async def generate_text(self, *a, **k):
        raise AssertionError("P0-①: text LLM call (reasoning/semantic) on approved turn")

    async def generate_text_light(self, *a, **k):
        raise AssertionError("P0-①: light LLM call (semantic) on approved turn")

    async def generate_with_tools(self, *a, **k):
        raise AssertionError("P0-①: planning LLM call on approved turn")


async def _forbidden(*a, **k):
    raise AssertionError("P0-①: discarded work ran on an approved turn")


def _approved_world(
    monkeypatch,
    *,
    planner_intent="create_invoice",
    action_type="create_invoice",
    planner_clarification=False,
    invoice_success=True,
):
    """Hermetic approved-turn world: process boundaries stubbed, all the
    P0-① work items installed as RAISING sentinels (invocation = failure)."""
    session = {
        "id": str(uuid.uuid4()),
        "organization_id": str(ORG),
        "user_id": str(USER),
        "user_request": MSG,
        "conversation_id": "conv-p0",
        "status": "WAITING_FOR_USER",
        "current_phase": "AWAITING_CONFIRMATION",
    }
    recorded = {
        "session": session,
        "steps": [],
        "results": [],
        "tool_runs": [],
        "tool_calls": [],
        "clarifications": [],
    }

    async def fake_fetch_one(table, filters=None, **kw):
        if not getattr(fake_fetch_one, "seen", False):
            fake_fetch_one.seen = True
            return session
        return None

    approved_plan = [
        {"tool_name": "create_customer", "arguments": {"name": "ABC Furnitures"}},
        {
            "tool_name": "create_invoice",
            "arguments": {
                "customer_id": "11111111-1111-4111-8111-111111111111",
                "invoice_date": "2026-09-20",
                "due_date": "2026-10-20",
                "items": [
                    {"description": "chairs", "quantity": 2, "unit_price": 16666.67}
                ],
            },
        },
    ]

    async def fake_fetch_many(table, filters=None, **kw):
        if table == "ai_confirmations":
            return [
                {
                    "id": "conf-1",
                    "execution_session_id": session["id"],
                    "user_confirmed": None,
                    "action_type": action_type,
                    "plan": approved_plan,
                }
            ]
        return []

    async def fake_create_session(**kw):
        return session

    async def fake_execute_planned(tool_calls, executor):
        out = []
        for tc in tool_calls:
            recorded["tool_runs"].append((tc.tool_name, dict(tc.arguments or {})))
            if tc.tool_name == "create_invoice" and not invoice_success:
                out.append(
                    {
                        "success": False,
                        "tool_name": tc.tool_name,
                        "data": {},
                        "error": "An unexpected error occurred while executing this operation.",
                    }
                )
            else:
                out.append(
                    {
                        "success": True,
                        "tool_name": tc.tool_name,
                        "data": {"id": "ok"},
                    }
                )
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
        # If anything tries to PARK the approved run, record it for the
        # assertion AND return a well-formed row (the run must not 500).
        recorded["clarifications"].append(kw)
        return {"id": "cl-x", "question": kw.get("question", "")}

    async def fake_classify(**kw):
        # requires_clarification=True with NO nature pins the E7 guard: the
        # classification QUESTION must never park a confirmed plan, while the
        # classification itself still feeds build_event_profile (the
        # executor's prohibited-tools guard).
        return TransactionClassification(
            transaction_nature=None,
            confidence="LOW",
            source="INFERENCE",
            requires_clarification=True,
        )

    def fake_planner(*args, **kwargs):
        return ExecutionPlan(
            intent=planner_intent,
            entity_type="customer",
            entity_name="ABC Furnitures",
            potential_tools=["create_customer", "create_invoice"],
            requires_validation=True,
            requires_accounting_engine=True,
            requires_confirmation=True,
            # planner_clarification=True pins the E3 questionnaire guard.
            requires_clarification=planner_clarification,
            missing_fields=["amount"] if planner_clarification else [],
            clarification_questions=(
                ["What is the transaction amount?"] if planner_clarification else []
            ),
            expected_outcome="Record the confirmed invoice",
            extracted_entities={"customer_name": "ABC Furnitures", "amount": 25000},
            economic_event="CREDIT_SALE",
            impact_map={},
            prohibited_actions=[],
            transaction_nature="CREDIT_SALE",
            transaction_nature_source="DETERMINISTIC_RULE",
            batch_items=None,
        )

    async def _no_label(account_id):
        return None

    # ---- process boundaries (mirrors the archived verification harness) ----
    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "fetch_many", fake_fetch_many)
    monkeypatch.setattr(agent_mod, "create_execution_session", fake_create_session)
    monkeypatch.setattr(agent_mod, "_close_superseded_sessions", _AM(return_value=0))
    monkeypatch.setattr(agent_mod, "seed_clarification_history", _AM())
    monkeypatch.setattr(agent_mod, "_load_org_preferences", _AM(return_value={}))
    monkeypatch.setattr(agent_mod, "resolve_confirmation", _AM(return_value={"id": "conf-1"}))
    monkeypatch.setattr(agent_mod, "get_clarification_history", _AM(return_value=[]))
    monkeypatch.setattr(agent_mod, "_update_status", _AM())
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)
    monkeypatch.setattr(agent_mod, "log_tool_call", fake_log_tool_call)
    monkeypatch.setattr(agent_mod, "flush_step_logs", _AM())
    monkeypatch.setattr(agent_mod, "create_clarification", fake_create_clarification)
    monkeypatch.setattr(agent_mod, "create_execution_result", fake_create_result)
    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", fake_execute_planned)
    monkeypatch.setattr(agent_mod, "verify_journal", fake_verify_journal)
    monkeypatch.setattr(agent_mod, "_make_account_label_resolver", lambda org: _no_label)
    monkeypatch.setattr(agent_mod, "get_client", lambda: _NoLLM())
    monkeypatch.setattr(agent_mod, "run_planner", fake_planner)
    monkeypatch.setattr("app.classifier.classify_transaction", fake_classify)
    monkeypatch.setattr(
        "app.services.preference_service.record_answer_preference", _AM()
    )

    # ---- P0-① sentinels: any of this work executing fails the test ----
    monkeypatch.setattr(agent_mod, "build_context", _forbidden)
    monkeypatch.setattr("app.accounting_reasoning.run_reasoning_loop", _forbidden)
    monkeypatch.setattr("app.semantic_layer.extract_semantic_facts", _forbidden)
    for gate in (
        "_party_resolution_question",
        "_settlement_check_question",
        "_catalog_check_question",
        "_revenue_ledger_review_gate",
    ):
        monkeypatch.setattr(agent_mod, gate, _forbidden)
    return recorded


@pytest.mark.asyncio
async def test_approved_turn_zero_llm_zero_context_and_executes(monkeypatch):
    """The approved turn performs NO discarded work and still completes.

    planner_clarification=True + classify(requires_clarification=True) arm the
    questionnaire (E3) and classification-question (E7) guards; the four gates
    are raising sentinels; both LLM stages and build_context raise on call.
    The run must reach COMPLETED/VERIFIED through the frozen plan.
    """
    rec = _approved_world(monkeypatch, planner_clarification=True)

    response = await resume_with_confirmation(
        session_id=uuid.UUID(rec["session"]["id"]),
        approved=True,
        user_id=USER,
        organization_id=ORG,
    )

    step_names = [s[1] for s in rec["steps"]]
    # Executes and verifies — the approved plan ran end-to-end.
    assert response.status == ExecutionStatus.COMPLETED
    assert response.verification_status == "VERIFIED"
    assert "APPROVED_PLAN_REUSED" in step_names
    # No parked states: questionnaire, classification question and all four
    # gates were skipped, not answered.
    assert rec["clarifications"] == []
    assert "AWAITING_CLARIFICATION" not in step_names
    assert "AWAITING_CONFIRMATION" not in step_names
    # LLM stages never ran (sentinels above would have raised otherwise) —
    # their audit markers must be absent from the durable timeline.
    assert "ACCOUNTING_REASONING" not in step_names
    assert "AI_PERCEPTION" not in step_names
    # The frozen plan executed in order through real materialization
    # (contract validation ON) and the execution stack.
    assert [t for t, _ in rec["tool_runs"]] == ["create_customer", "create_invoice"]
    # 0 = measurement: zero LLM calls, zero domain-context builds, zero gate
    # lookups on this turn (baseline before P0-①: >=2 LLM calls + 12-query
    # context + 4 gate lookups per approval).
    assert len(rec["results"]) >= 1


@pytest.mark.asyncio
async def test_confirmed_intent_drives_verification_when_planner_blind(monkeypatch):
    """``confirmed_intent`` keys Phase 7/8 on what the user APPROVED.

    The keyword planner on an approved turn runs WITHOUT the semantic prefill
    this path skips; here it re-derives ``unknown`` while the confirmation's
    action_type is ``create_invoice``.  Without the override, verification
    would treat the run as non-financial and a FAILED invoice would be
    reported as a benign completion.
    """
    rec = _approved_world(
        monkeypatch,
        planner_intent="unknown",      # keyword planner re-derives nothing
        action_type="create_invoice",  # what the user actually approved
        invoice_success=False,         # primary mutation fails
    )

    response = await resume_with_confirmation(
        session_id=uuid.UUID(rec["session"]["id"]),
        approved=True,
        user_id=USER,
        organization_id=ORG,
    )

    assert response.status == ExecutionStatus.FAILED
    assert response.verification_status == "FAILED"
    assert "create_invoice" in response.summary
    assert "APPROVED_PLAN_REUSED" in [s[1] for s in rec["steps"]]



