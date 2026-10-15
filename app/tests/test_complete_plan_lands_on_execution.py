"""A COMPLETE recording plan must always land on execution — system-wide.

Production 2026-10-14, session ``ae043ec3`` (the "them Sales" conversation's
final state): every value was known — customer confirmed, amount 640000, date,
nature, item ``laptops`` x2 — yet the run dead-ended on the lookup-only card
("steps I could prepare were: search_customer, search_product … please
resend").  Three compounding defects, each pinned here:

1. **Nature-family leak** — the field-tagged / bare-question merge route
   accepted ANY canonical ``transaction_nature``, so ``INVENTORY`` (the
   PURCHASE family's value) landed on a SALE.  The deterministic invoice fast
   path (GOODS|SERVICE only) then refused the plan.
2. **No deterministic floor** — a lookup-only LLM plan for a complete
   recording intent was bounced to the "resend" card instead of being
   promoted to its own deterministic write.
3. **No execution directive** — the bounded lookup-continuation round never
   told the model the facts were final, so it re-planned the same lookups.

The fast-path gate itself is deliberately NOT widened: the sale family's
canonical stock value is GOODS (INVENTORY is the purchase side), so the leak
is closed at the MERGE and the family's own question re-asks.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock as _AM

import pytest

import app.agent as agent_mod
from app.accounting_reasoning import ReasoningOutcome
from app.agent import execute
from app.models.schemas import ExecutionPlan, ExecutionStatus

ORG = uuid.UUID("77777777-4777-4777-4777-477777777777")
USER = uuid.UUID("88888888-4888-4888-8888-888888888888")
MSG = "create invoice for zeta pvt ltd for selling them 2 laptops"


class _TC:
    """Duck-typed ToolCall (avoids importing pydantic plumbing)."""

    def __init__(self, tool_name, arguments):
        self.tool_name = tool_name
        self.arguments = dict(arguments)


# ---------------------------------------------------------------------------
# 1. Nature-family guard — the leak that put INVENTORY on a sale
# ---------------------------------------------------------------------------
class TestNatureFamilyGuard:
    @staticmethod
    def _merge(qa, intent=""):
        from app.planner import _merge_clarification_answers

        return _merge_clarification_answers({}, [qa], intent=intent)

    def test_inventory_is_never_stored_on_a_sale_intent(self):
        merged = self._merge(
            {"question": "transaction_nature", "answer": "INVENTORY"},
            intent="create_invoice",
        )
        assert "transaction_nature" not in merged, (
            "INVENTORY is the PURCHASE family's value — the sale family's own "
            "question must re-ask (GOODS), never a silent wrong-family store"
        )

    def test_the_field_tag_route_is_guarded_too(self):
        # The authored-questionnaire route (field-tagged answers) is the SAME
        # family-blind entry point as the bare-field route.
        merged = self._merge(
            {"field": "transaction_nature", "answer": "INVENTORY"},
            intent="create_invoice",
        )
        assert "transaction_nature" not in merged

    def test_goods_is_stored_on_a_sale_intent(self):
        merged = self._merge(
            {"question": "transaction_nature", "answer": "GOODS"},
            intent="create_invoice",
        )
        assert merged["transaction_nature"] == "GOODS"

    def test_inventory_is_stored_on_a_purchase_intent(self):
        merged = self._merge(
            {"question": "transaction_nature", "answer": "INVENTORY"},
            intent="record_purchase",
        )
        assert merged["transaction_nature"] == "INVENTORY"

    def test_without_intent_the_legacy_behaviour_is_unchanged(self):
        # Existing callers (scripts, older tests) pass no intent — the route
        # keeps its historical unguarded behaviour for them.
        merged = self._merge(
            {"question": "transaction_nature", "answer": "INVENTORY"}
        )
        assert merged["transaction_nature"] == "INVENTORY"


# ---------------------------------------------------------------------------
# 2. Continuation directive — a complete plan is told to WRITE, not search
# ---------------------------------------------------------------------------
def _plan_stub(*, missing_fields, entities, potential_tools):
    return SimpleNamespace(
        intent="create_invoice",
        missing_fields=list(missing_fields),
        extracted_entities=dict(entities),
        potential_tools=list(potential_tools),
    )


_COMPLETE_ENTITIES = {
    "customer_name": "zeta pvt ltd",
    "customer_create_confirmed": True,
    "amount": 640000.0,
    "transaction_date": "2026-10-14",
    "transaction_nature": "GOODS",
    "item_description": "laptops",
    "quantity": 2.0,
}


class _CapturingClient:
    def __init__(self):
        self.captured = {}

    async def generate_with_tools(self, **kwargs):
        self.captured = kwargs
        return {
            "text": "I'll start by checking the live records.",
            "tool_calls": [_TC("search_customer", {"query": "zeta"})],
            "iteration_count": 1,
        }


async def _run_continuation(monkeypatch, *, plan):
    """Drive ``_continue_lookup_only_plan`` with all boundaries stubbed."""
    client = _CapturingClient()

    async def _router(tc, **kwargs):
        return SimpleNamespace(success=True, error=None, data={"records": []})

    monkeypatch.setattr(agent_mod, "_log_step", _AM())
    monkeypatch.setattr(agent_mod, "route_tool_call", _router)
    calls, text, evidence = await agent_mod._continue_lookup_only_plan(
        client=client,
        session_id=uuid.uuid4(),
        execution_plan=plan,
        planned_tool_calls=[_TC("search_customer", {"query": "zeta"})],
        context=SimpleNamespace(),
        user_message=MSG,
        organization_id=ORG,
        user_id=USER,
        auth=None,
        excluded_tools=set(),
    )
    return client, calls, text, evidence


class TestContinuationDirective:
    @pytest.mark.asyncio
    async def test_a_complete_plan_is_told_to_propose_the_write(self, monkeypatch):
        plan = _plan_stub(
            missing_fields=[],
            entities=_COMPLETE_ENTITIES,
            potential_tools=["search_customer", "get_customer", "create_invoice"],
        )
        client, calls, _, _ = await _run_continuation(monkeypatch, plan=plan)
        message = client.captured["user_message"]
        assert "INTERNAL DIRECTIVE" in message
        assert "create_invoice" in message
        assert "search_customer" not in message.split("INTERNAL DIRECTIVE")[1], (
            "the directive must name only WRITE tools"
        )

    @pytest.mark.asyncio
    async def test_an_incomplete_plan_gets_no_directive(self, monkeypatch):
        plan = _plan_stub(
            missing_fields=["amount"],
            entities={k: v for k, v in _COMPLETE_ENTITIES.items() if k != "amount"},
            potential_tools=["search_customer", "create_invoice"],
        )
        client, _, _, _ = await _run_continuation(monkeypatch, plan=plan)
        assert "INTERNAL DIRECTIVE" not in client.captured["user_message"]



# ---------------------------------------------------------------------------
# 3. End-to-end: a resolved sale reaches CONFIRMATION, never the resend card
# ---------------------------------------------------------------------------
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


def _invoice_plan():
    return ExecutionPlan(
        intent="create_invoice",
        entity_type="invoice",
        entity_name="zeta pvt ltd",
        potential_tools=["search_customer", "get_customer", "create_invoice"],
        requires_validation=True,
        requires_accounting_engine=True,
        requires_confirmation=True,
        requires_clarification=False,
        missing_fields=[],
        clarification_questions=[],
        expected_outcome="Record the laptop sale",
        extracted_entities=dict(_COMPLETE_ENTITIES),
        economic_event="DOCUMENT",
        impact_map={},
        prohibited_actions=[],
        transaction_nature="GOODS",
        transaction_nature_source="USER_ANSWER",
        batch_items=None,
    )


def _world(monkeypatch, *, get_client_stub):
    """Hermetic world (approved-harness pattern) for the invoice flow."""
    from app.repositories import account_repository

    session = {
        "id": str(uuid.uuid4()),
        "organization_id": str(ORG),
        "user_id": str(USER),
        "user_request": MSG,
        "conversation_id": "conv-floor",
        "status": "RUNNING",
        "current_phase": "RUNNING",
    }
    recorded = {"steps": [], "confirmations": [], "clarifications": [], "results": []}

    async def fake_log_step(session_id, step_type, data):
        recorded["steps"].append((session_id, step_type, data))

    async def fake_create_confirmation(**kw):
        recorded["confirmations"].append(kw)
        return {"id": f"conf-{len(recorded['confirmations'])}"}

    async def fake_create_clarification(**kw):
        recorded["clarifications"].append(kw)
        return {"id": "cl-1", "question": kw.get("question", "")}

    async def fake_create_result(**kw):
        recorded["results"].append(kw)
        return {"id": "res-1"}

    async def fake_classify(**kw):
        from app.models.schemas import TransactionClassification

        return TransactionClassification(
            transaction_nature="GOODS",
            confidence="HIGH",
            source="USER_ANSWER",
            requires_clarification=False,
        )

    async def _none_rows(*a, **k):
        return []

    async def _none_row(*a, **k):
        return None

    async def _execution_bomb(tool_calls, executor):
        raise AssertionError("nothing may execute before the user approves")

    monkeypatch.setattr(agent_mod, "fetch_one", _AM(return_value=session))
    monkeypatch.setattr(agent_mod, "fetch_many", _AM(return_value=[]))
    monkeypatch.setattr(
        agent_mod, "create_execution_session", _AM(return_value=session)
    )
    monkeypatch.setattr(agent_mod, "_close_superseded_sessions", _AM(return_value=0))
    monkeypatch.setattr(agent_mod, "seed_clarification_history", _AM())
    monkeypatch.setattr(agent_mod, "_load_org_preferences", _AM(return_value={}))
    monkeypatch.setattr(agent_mod, "resolve_confirmation", _AM(return_value={}))
    monkeypatch.setattr(agent_mod, "get_clarification_history", _AM(return_value=[]))
    monkeypatch.setattr(agent_mod, "_update_status", _AM())
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)
    monkeypatch.setattr(agent_mod, "log_tool_call", _AM(return_value={"id": "tc"}))
    monkeypatch.setattr(agent_mod, "flush_step_logs", _AM())
    monkeypatch.setattr(account_repository, "get_chart_of_accounts", _none_rows)
    monkeypatch.setattr(account_repository, "search_accounts", _none_rows)
    monkeypatch.setattr(agent_mod, "create_clarification", fake_create_clarification)
    monkeypatch.setattr(agent_mod, "create_confirmation", fake_create_confirmation)
    monkeypatch.setattr(agent_mod, "create_execution_result", fake_create_result)
    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", _execution_bomb)
    monkeypatch.setattr(
        "app.account_resolution.preflight_account_gaps", _AM(return_value=[])
    )
    monkeypatch.setattr(agent_mod, "_depreciation_policy_gate", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_revenue_ledger_review_gate", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_catalog_check_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_party_resolution_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_settlement_check_question", _AM(return_value=None))
    monkeypatch.setattr(
        agent_mod, "build_context", _AM(return_value=_Ctx(_COMPLETE_ENTITIES))
    )

    def _sync_planner(*args, **kwargs):
        return _invoice_plan()

    monkeypatch.setattr(agent_mod, "run_planner", _sync_planner)
    monkeypatch.setattr("app.classifier.classify_transaction", fake_classify)
    monkeypatch.setattr(
        "app.services.preference_service.record_answer_preference", _AM()
    )
    monkeypatch.setattr(
        "app.accounting_reasoning.run_reasoning_loop",
        _AM(return_value=ReasoningOutcome(
            status="UNSUPPORTED",
            understanding={"economic_event": "sale"},
            rounds=1,
        )),
    )
    monkeypatch.setattr(
        "app.entity_segregation.extract_request_facts", _AM(return_value={})
    )
    monkeypatch.setattr(
        agent_mod, "verify_journal", _AM(return_value={"verified": True})
    )
    monkeypatch.setattr(
        agent_mod, "_make_account_label_resolver", lambda org: _none_row
    )
    monkeypatch.setattr(agent_mod, "get_client", get_client_stub)
    return recorded



class _NoLLM:
    """Any provider call on a deterministic path is a regression."""

    async def generate_text(self, *a, **k):
        raise AssertionError("LLM text call in a deterministic test path")

    async def generate_with_tools(self, *a, **k):
        raise AssertionError("LLM planning call in a deterministic test path")


class _LookupLoop:
    """The incident's model: read-only calls, round after round."""

    def __init__(self):
        self.calls = 0

    async def generate_text(self, *a, **k):
        return "{}"

    async def generate_with_tools(self, **kwargs):
        self.calls += 1
        return {
            "text": "I'll start by checking the live records for the customer and product.",
            "tool_calls": [
                _TC("search_customer", {"query": "zeta pvt ltd"}),
                _TC("search_product", {"query": "laptops"}),
            ],
            "iteration_count": 1,
        }


def _stub_catalog_services(monkeypatch):
    """Party + catalog services the invoice fast path resolves through."""
    from app.services import customer_service, product_service, service_service

    async def _no_rows(*a, **k):
        return []

    async def _create(org, *, name, **k):
        return {"id": uuid.uuid4(), "name": name}

    monkeypatch.setattr(customer_service, "search", _no_rows)
    monkeypatch.setattr(customer_service, "create", _create)
    monkeypatch.setattr(product_service, "search", _no_rows)
    monkeypatch.setattr(service_service, "search", _no_rows)


def _step_names(recorded):
    return [s[1] for s in recorded["steps"]]


@pytest.mark.asyncio
async def test_the_resolved_sale_is_planned_deterministically(monkeypatch):
    """The fast path fires BEFORE the model — zero provider calls."""
    _stub_catalog_services(monkeypatch)
    recorded = _world(monkeypatch, get_client_stub=lambda: _NoLLM())

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-fast",
    )

    assert response.status == ExecutionStatus.AWAITING_CONFIRMATION
    det = [
        d for _, step, d in recorded["steps"] if step == "DETERMINISTIC_EXECUTION"
    ]
    assert det, "a fully-resolved sale must be planned without the model"
    assert "create_invoice" in det[0]["tools"]
    assert det[0].get("source") != "lookup_only_fallback"
    assert "plan_incomplete" not in _step_names(recorded)
    assert recorded["confirmations"], "the confirmation snapshot must exist"
    assert recorded["confirmations"][0]["action_type"] == "create_invoice"


@pytest.mark.asyncio
async def test_the_lookup_only_dead_end_is_promoted_not_bounced(monkeypatch):
    """Floor: model loops lookups for a COMPLETE plan → deterministic write.

    The first ``_deterministic_mutation_calls`` call returns None (the
    incident's setup — the run falls to the model), the model returns
    read-only calls, and the completeness-gate floor re-tries the builder:
    the promotion must land on CONFIRMATION, never the plan_incomplete
    "please resend" card.
    """
    loop = _LookupLoop()
    recorded = _world(monkeypatch, get_client_stub=lambda: loop)

    state = {"n": 0}

    async def _stateful(*, organization_id, execution_plan, classification):
        state["n"] += 1
        if state["n"] == 1:
            return None  # PHASE 4: the model path is chosen (incident setup)
        return [_TC("create_invoice", {
            "invoice_date": "2026-10-14",
            "items": [{"description": "laptops", "quantity": 2.0,
                       "unit_price": 320000.0}],
        })]

    monkeypatch.setattr(agent_mod, "_deterministic_mutation_calls", _stateful)

    response = await execute(
        user_message=MSG,
        user_id=USER,
        organization_id=ORG,
        conversation_id="conv-floor",
    )

    assert response.status == ExecutionStatus.AWAITING_CONFIRMATION, (
        "a complete recording plan must reach confirmation, not a dead-end"
    )
    assert "plan_incomplete" not in _step_names(recorded), (
        "the 'please resend' card must never fire for a complete plan"
    )
    promoted = [
        d for _, step, d in recorded["steps"]
        if step == "DETERMINISTIC_EXECUTION"
        and d.get("source") == "lookup_only_fallback"
    ]
    assert promoted, "the floor must record its promotion durably"
    assert "create_invoice" in promoted[0]["tools"]
    assert loop.calls == 1, (
        "the lookup-continuation round must be skipped once the floor promotes"
    )
    assert recorded["confirmations"][0]["action_type"] == "create_invoice"

