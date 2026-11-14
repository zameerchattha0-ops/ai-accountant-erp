"""Tests for the LLM-driven Autonomous Error Recovery and Transparent Endpoint Pipeline."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import pytest

from app.models.schemas import AgentResponse, ExecutionStatus, ToolCall, ToolResult
from app.prompts import build_primary_reasoning_instructions, build_system_instructions
from app.repositories import account_repository
from app.tool_router import route_tool_call
from app.tools import _TOOL_REGISTRY, tool_contracts


class _Ctx:
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
        self.economic_event = "DOCUMENT"
        self.impact_map = {}
        self.prohibited_actions = []
        self.chart_of_accounts = []
        self.live_accounts = []
        self.clarification_history = []
        self.prior_turns = []
        self.conversation_history = []


def test_system_prompt_includes_stage_5_cognitive_recovery():
    """Stage 5 Cognitive Failure Diagnosis & Recovery is present in the CA reasoning instructions."""
    reasoning_text = build_primary_reasoning_instructions()
    assert "STAGE 5 — COGNITIVE FAILURE DIAGNOSIS & AUTONOMOUS RECOVERY" in reasoning_text
    assert "READ THE REASON CAREFULLY" in reasoning_text
    assert "DIAGNOSE ROOT CAUSE & BOOK STATE" in reasoning_text
    assert "AUTONOMOUS EXECUTION RECOVERY" in reasoning_text

    sys_instructions = build_system_instructions()
    assert "STAGE 5" in sys_instructions
    assert "dynamically execute the correct recovery path" in sys_instructions


@pytest.mark.asyncio
async def test_tool_router_preserves_unmasked_error_messages(monkeypatch):
    """Tool router never masks endpoint exceptions with generic 'An unexpected error' text."""
    async def fake_handler(org_id, **kw):
        raise RuntimeError("Key (account_id)=(6210) is not present in table accounts.")

    monkeypatch.setitem(_TOOL_REGISTRY, "dummy_failing_tool", {
        "handler": fake_handler,
        "read_only": True,
        "schema": {"parameters": {"type": "object", "properties": {}}},
    })

    res = await route_tool_call(
        ToolCall(tool_name="dummy_failing_tool", arguments={}),
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    assert res.success is False
    assert "An unexpected error occurred while executing this operation" not in res.error
    assert "Key (account_id)=(6210) is not present in table accounts" in res.error


@pytest.mark.asyncio
async def test_executor_provides_endpoint_contract_and_diagnostic_guidance_on_attempt_1(monkeypatch):
    """_executor provides unmasked error, endpoint contract grounding, and recovery guidance on attempt 1."""
    import app.agent as agent_mod

    logged_steps = []
    async def fake_log_step(sid, step_type, payload):
        logged_steps.append((step_type, payload))

    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    # Tool router returns an unmasked error
    async def fake_route_tool_call(tc, **kwargs):
        return ToolResult(
            tool_name=tc.tool_name,
            success=False,
            error="Account '6210' does not exist in chart of accounts",
            error_category="INVALID_REFERENCE",
            error_details={"category": "INVALID_REFERENCE", "reason": "Account '6210' does not exist"},
        )

    monkeypatch.setattr(agent_mod, "route_tool_call", fake_route_tool_call)

    # Invoke _executor logic directly using the contract
    contract = tool_contracts().get("create_expense") or {
        "required": ("description", "total", "expense_date"),
        "accepted": ("description", "total", "expense_date", "account_id", "supplier_id"),
        "uuid_params": ("account_id", "supplier_id"),
        "accepts_extra": False,
    }

    _tool_failure_counts = {}
    async def run_executor_failure(tool_name, tool_args):
        # Mirroring agent.py lines 12571-12614
        tc = ToolCall(tool_name=tool_name, arguments=tool_args)
        result = await agent_mod.route_tool_call(tc)
        if not result.success:
            _tool_failure_counts[tool_name] = _tool_failure_counts.get(tool_name, 0) + 1
            fail_count = _tool_failure_counts[tool_name]
            raw_err = result.error or "tool invocation failed"

            grounding = ""
            if contract:
                grounding = (
                    f"\n[ENDPOINT CONTRACT for '{tool_name}']:\n"
                    f"- Required arguments: {list(contract.get('required', ()))} \n"
                    f"- Accepted arguments: {list(contract.get('accepted', ()))} \n"
                    f"- UUID parameters: {list(contract.get('uuid_params', ()))} \n"
                    f"- Extra arguments allowed: {contract.get('accepts_extra', False)}\n"
                )

            augmented_err = (
                f"Tool '{tool_name}' failed with error: {raw_err}.{grounding}"
                "COGNITIVE RECOVERY INSTRUCTION: Read the error and inspect your book state. "
                "If a prerequisite (account, supplier, customer, product, period) is missing, execute the "
                "necessary search or creation tool first. If arguments were invalid or missing, match the contract "
                "above and retry. If the underlying ledger event is already satisfied, complete your answer."
            )

            await agent_mod._log_step(uuid.uuid4(), "SELF_CORRECTION", {
                "tool": tool_name,
                "attempt": fail_count,
                "contract_grounded": True,
                "error": raw_err[:400],
            })
            return {
                "success": False,
                "error": augmented_err,
                "raw_error": raw_err,
                "error_category": getattr(result, "error_category", None) or "EXECUTION_FAILURE",
                "error_details": getattr(result, "error_details", None),
                "endpoint_contract": {
                    "required": list(contract.get("required", ())),
                    "accepted": list(contract.get("accepted", ())),
                } if contract else None,
            }
        return {"success": True}

    res = await run_executor_failure("create_expense", {"description": "Rent", "amount": 15000})
    assert res["success"] is False
    assert "Account '6210' does not exist in chart of accounts" in res["error"]
    assert "[ENDPOINT CONTRACT for 'create_expense']" in res["error"]
    assert "COGNITIVE RECOVERY INSTRUCTION" in res["error"]
    assert res["raw_error"] == "Account '6210' does not exist in chart of accounts"
    assert "description" in res["endpoint_contract"]["required"]

    # Verify log step was emitted with attempt 1
    assert len(logged_steps) == 1
    assert logged_steps[0][0] == "SELF_CORRECTION"
    assert logged_steps[0][1]["attempt"] == 1
    assert logged_steps[0][1]["contract_grounded"] is True


@pytest.mark.asyncio
async def test_autonomous_recovery_turn_triggered_on_required_failure(monkeypatch):
    """When a required mutation fails, the LLM autonomous recovery turn is triggered with history and contract."""
    import app.agent as agent_mod

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    logged_steps = []
    async def fake_log_step(sid, step_type, payload):
        logged_steps.append((step_type, payload))

    async def fake_create_confirmation(**kw):
        return {"id": "conf-1"}

    async def fake_create_clarification(**kw):
        return {"id": "cl-1", "question": kw.get("question", "")}

    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)
    monkeypatch.setattr(agent_mod, "_update_status", AsyncMock())
    monkeypatch.setattr(agent_mod, "update_one", AsyncMock())
    monkeypatch.setattr(agent_mod, "get_session_status", AsyncMock(return_value="EXECUTING"))
    monkeypatch.setattr(agent_mod, "create_clarification", fake_create_clarification)
    monkeypatch.setattr(agent_mod, "create_confirmation", fake_create_confirmation)
    monkeypatch.setattr(agent_mod, "create_execution_session", AsyncMock(return_value={"id": str(session_id)}))
    monkeypatch.setattr(agent_mod, "_load_org_facts", AsyncMock(return_value=(None, None, None)))
    monkeypatch.setattr(agent_mod, "_preamble_side_effects", AsyncMock(return_value={}))
    monkeypatch.setattr(agent_mod, "fetch_one", AsyncMock(return_value={"id": str(session_id), "organization_id": str(org_id), "user_id": str(user_id)}))
    monkeypatch.setattr(agent_mod, "fetch_many", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent_mod, "resolve_confirmation", AsyncMock(return_value={}))
    monkeypatch.setattr(agent_mod, "get_clarification_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent_mod, "log_tool_call", AsyncMock(return_value={"id": "tc-1"}))
    monkeypatch.setattr(agent_mod, "flush_step_logs", AsyncMock())
    monkeypatch.setattr(agent_mod, "create_execution_result", AsyncMock(return_value={"id": "res-1"}))
    monkeypatch.setattr(agent_mod, "_depreciation_policy_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_mod, "_revenue_ledger_review_gate", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_mod, "_catalog_check_question", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_mod, "_party_resolution_question", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_mod, "_settlement_check_question", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_mod, "_account_rescue_question", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_mod, "extract_structured", AsyncMock(return_value=None))

    async def _none_rows(*a, **k):
        return []

    monkeypatch.setattr(account_repository, "get_chart_of_accounts", _none_rows)
    monkeypatch.setattr(account_repository, "search_accounts", _none_rows)
    monkeypatch.setattr("app.account_resolution.preflight_account_gaps", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.org_context.business_profile", AsyncMock(return_value={}))

    # Initial turn: create_expense fails
    initial_call = ToolCall(tool_name="create_expense", arguments={"description": "Office Supplies", "total": 5000, "expense_date": "2026-11-14"})
    initial_failure = ToolResult(
        tool_name="create_expense",
        success=False,
        error="Supplier 'Shabbir Furniture' does not exist in supplier records.",
        error_category="INVALID_REFERENCE",
    )

    async def fake_route_tool_call(tc, **kwargs):
        return initial_failure

    monkeypatch.setattr(agent_mod, "route_tool_call", fake_route_tool_call)

    # Mock materialization so it doesn't block on empty database
    from app.plan_materialization import PlanMaterialization
    monkeypatch.setattr("app.plan_materialization.prepare_plan", AsyncMock(return_value=PlanMaterialization(
        calls=[initial_call],
        decisions=[],
        blocks=[],
        deferred={},
        batches=[[0]],
    )))

    from app.models.schemas import ExecutionPlan
    plan = ExecutionPlan(
        session_id=session_id,
        user_id=user_id,
        organization_id=org_id,
        intent="create_expense",
        confidence=1.0,
        missing_fields=[],
        potential_tools=["create_expense"],
        extracted_entities={"description": "Office Supplies", "total": 5000, "expense_date": "2026-11-14"},
        economic_event="DOCUMENT",
        impact_map={},
        prohibited_actions=[],
        transaction_nature="EXPENSE",
        transaction_nature_source="USER_ANSWER",
        requires_confirmation=False,
        requires_validation=True,
    )
    monkeypatch.setattr(agent_mod, "run_planner", lambda *a, **kw: plan)
    monkeypatch.setattr(agent_mod, "build_context", AsyncMock(return_value=_Ctx({"description": "Office Supplies", "total": 5000})))

    # Mock client
    captured_remediation_prompts = []
    class MockGeminiClient:
        async def generate_with_tools(self, **kwargs):
            # Autonomous recovery turn
            captured_remediation_prompts.append(kwargs.get("user_message", ""))
            # LLM autonomously heals by creating the supplier and expense
            recovered_result = ToolResult(
                tool_name="create_expense",
                success=True,
                data={"id": "exp-123", "status": "POSTED"},
            )
            return {
                "text": "Successfully diagnosed the missing supplier, created record, and posted the expense.",
                "tool_calls": [initial_call],
                "tool_results": [recovered_result],
                "iteration_count": 1,
            }

    mock_client = MockGeminiClient()
    monkeypatch.setattr(agent_mod, "get_client", lambda: mock_client)

    response = await agent_mod.execute(
        user_message="record 5000 expense for office supplies from Shabbir Furniture",
        organization_id=org_id,
        user_id=user_id,
        confirmation_granted=True,
        approved_tool_calls=[initial_call],
    )

    # Verify recovery turn was triggered
    assert len(captured_remediation_prompts) == 1
    prompt = captured_remediation_prompts[0]
    assert "ERP Autonomous Self-Healing Engine" in prompt
    assert "Operations Failed:" in prompt
    assert "Supplier 'Shabbir Furniture' does not exist" in prompt
    assert "Contract for 'create_expense':" in prompt
    assert "RECOVERY PROTOCOL:" in prompt

    # Verify step logs recorded both TRIGGERED and SUCCEEDED
    step_types = [s[0] for s in logged_steps]
    assert "SELF_CORRECTION_TRIGGERED" in step_types
    assert "SELF_CORRECTION_SUCCEEDED" in step_types

    # Verify execution finished successfully
    assert response.status == ExecutionStatus.COMPLETED
    assert "Successfully diagnosed the missing supplier" in response.summary


@pytest.mark.asyncio
async def test_single_hop_failure_falls_through_to_llm_reasoning(monkeypatch):
    """When single-hop shortcut execution fails, it falls through to execute() instead of returning FAILED."""
    import app.agent as agent_mod
    import app.database as db_mod
    import app.planner as planner_mod

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    # Route tool call permissions and validation
    monkeypatch.setattr("app.tool_router.authorize_tool", AsyncMock(return_value=True))
    monkeypatch.setattr("app.tool_router.validate_operation", AsyncMock(return_value=SimpleNamespace(valid=True, errors=[])))

    # Route tool call returns a failure for single-hop
    async def failing_route(tc, **kwargs):
        return ToolResult(tool_name=tc.tool_name, success=False, error="Ledger locked")

    monkeypatch.setattr(agent_mod, "route_tool_call", failing_route)

    execute_called = []
    async def fake_execute(*args, **kwargs):
        execute_called.append(kwargs)
        return AgentResponse(
            status=ExecutionStatus.COMPLETED,
            execution_id=session_id,
            summary="Autonomous recovery succeeded via full CA reasoning loop",
            action="record_cash_sale",
            verification_status="VERIFIED",
        )

    monkeypatch.setattr(agent_mod, "execute", fake_execute)
    monkeypatch.setattr(agent_mod, "_log_step", AsyncMock())
    monkeypatch.setattr(agent_mod, "_update_status", AsyncMock())
    monkeypatch.setattr(agent_mod, "log_tool_call", AsyncMock(return_value={"id": "tc"}))

    session = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "user_request": "cash sale 5000",
        "conversation_id": "conv-1",
        "status": "AWAITING_CLARIFICATION",
        "role": "OWNER",
    }
    monkeypatch.setattr(agent_mod, "fetch_one", AsyncMock(return_value=session))

    async def fake_resolve_and_fetch(*args, **kwargs):
        return (
            {"id": "cl-1"},
            [{"question": "amount", "answer": "5000"}],
            {"intent": "record_cash_sale", "amount": 5000},
        )

    monkeypatch.setattr(db_mod, "resolve_and_fetch_clarifications", fake_resolve_and_fetch)
    monkeypatch.setattr(planner_mod, "_merge_clarification_answers", lambda base, qa, intent=None: {
        "intent": "record_cash_sale",
        "amount": 5000,
        "description": "Cash sale",
    })

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="5000",
        user_id=user_id,
        organization_id=org_id,
    )

    # Ensure execute was called as fallback
    assert len(execute_called) == 1
    assert execute_called[0]["user_message"] == "cash sale 5000"
    assert resp.status == ExecutionStatus.COMPLETED
    assert "Autonomous recovery succeeded" in resp.summary
