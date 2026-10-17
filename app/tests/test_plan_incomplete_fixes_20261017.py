"""Fix tests for the 2026-10-17 production sale dead-end (session 7d46349f).

Three stacked defects, three guards:

C. REQUIREMENT_ANALYSIS derived the unit price from amount / quantity
   ("SELL 2 CHAIRS FOR 54000" → 27,000) instead of raising a phantom
   MISSING_AND_REQUIRED line-detail gap.
B. The plan_incomplete card routes the REAL open gaps (from
   analyze_requirements) into its question when the questionnaire's own
   missing_fields are empty — the "nothing is missing, please resend"
   dead-end survives only for the truly-empty case.
A. _continue_lookup_only_plan gained ONE escalated re-plan round that
   demands the financial write call when the first continuation proposed
   only party-master steps (create_customer for a credit sale).
"""
from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace

import pytest

import app.agent as agent_mod
from app.agent import _continue_lookup_only_plan, _plan_performs_no_financial_mutation
from app.models.schemas import AgentContext, ToolCall
from app.reasoning import (
    FieldResolutionState,
    analyze_requirements,
    collect_open_questions,
)


# ---------------------------------------------------------------------------
# C — derivable line detail
# ---------------------------------------------------------------------------

def _sale_nodes(entities, missing=()):
    return analyze_requirements(
        intent="record_credit_sale",
        entities=entities,
        missing_fields=list(missing),
    )


class TestDerivableLineDetail:
    def test_unit_price_is_derived_from_total_and_quantity(self):
        nodes = _sale_nodes({
            "amount": 54000.0, "item_quantity": 2.0, "item": "CHAIRS",
            "item_description": "CHAIRS", "transaction_nature": "INVENTORY",
            "transaction_date": "2026-10-17", "customer_name": "GETA LTD",
        })
        line = next(n for n in nodes if n.key == "item_line_details")
        assert line.state is FieldResolutionState.DETERMINISTICALLY_RESOLVABLE
        assert "27,000.00" in (line.detail or "")
        assert line.question is None
        fields = [q["field"] for q in collect_open_questions(nodes)]
        assert "item_line_details" not in fields, fields

    def test_quantity_is_derived_from_total_and_unit_price(self):
        nodes = _sale_nodes({
            "amount": 54000.0, "item_unit_price": 27000.0,
            "item": "CHAIRS", "item_description": "CHAIRS",
            "transaction_nature": "INVENTORY",
        })
        line = next(n for n in nodes if n.key == "item_line_details")
        assert line.state is FieldResolutionState.DETERMINISTICALLY_RESOLVABLE
        assert "quantity 2" in (line.detail or "")
        assert "item_line_details" not in [
            q["field"] for q in collect_open_questions(nodes)
        ]

    def test_an_undivable_line_detail_still_asks(self):
        nodes = _sale_nodes(
            {"item": "CHAIRS", "item_description": "CHAIRS",
             "item_quantity": 2.0},
            missing=["amount"],
        )
        line = next(n for n in nodes if n.key == "item_line_details")
        assert line.state is FieldResolutionState.MISSING_AND_REQUIRED
        assert "Unit price" in (line.question or "")
        assert "item_line_details" in [
            q["field"] for q in collect_open_questions(nodes)
        ]

    def test_zero_or_garbage_amounts_never_derive(self):
        for bad in (0, -5, "x", None):
            nodes = _sale_nodes({
                "amount": bad, "item_quantity": 2.0, "item": "CHAIRS",
            })
            line = next(n for n in nodes if n.key == "item_line_details")
            assert line.state is FieldResolutionState.MISSING_AND_REQUIRED


# ---------------------------------------------------------------------------
# A — the escalated re-plan round
# ---------------------------------------------------------------------------

class _StubClient:
    """Captures the planning message; returns a scripted reply."""

    def __init__(self, reply):
        self._reply = reply
        self.seen_messages: list[str] = []

    async def generate_with_tools(self, *, user_message, context,
                                  executor=None, excluded_tools=None,
                                  light_budget=False, thinking_off=False):
        self.seen_messages.append(user_message)
        return dict(self._reply)


@pytest.fixture()
def _no_log(monkeypatch):
    calls: list[tuple] = []

    async def _capture(step, description, payload=None):
        calls.append((description, payload or {}))

    monkeypatch.setattr(agent_mod, "_log_step", _capture)
    return calls


def _plan(intent="record_credit_sale"):
    return SimpleNamespace(
        intent=intent,
        extracted_entities={
            "customer_name": "GETA LTD", "item_description": "CHAIRS",
            "quantity": 2.0, "amount": 54000.0,
            "transaction_date": "2026-10-17", "transaction_nature": "INVENTORY",
        },
        missing_fields=[],
        # intent record_credit_sale -> TOOL create_invoice (tool_selector)
        potential_tools=["search_customer", "create_customer", "create_invoice"],
    )


def _ctx_with_evidence():
    ctx = AgentContext(organization={}, user={})
    ctx.pre_executed_lookups = [
        {"tool": "search_customer", "records": [{"id": 1}], "error": None},
    ]
    return ctx


class TestEscalatedReplan:
    @pytest.mark.asyncio
    async def test_retry_demands_the_write_and_reuses_evidence(self, _no_log):
        reply = {
            "tool_calls": [ToolCall(tool_name="create_invoice",
                                    arguments={"amount": 54000})],
            "text": "Recording the credit sale now.",
        }
        client = _StubClient(reply)
        calls, text, evidence = await _continue_lookup_only_plan(
            client=client,
            session_id=uuid.uuid4(),
            execution_plan=_plan(),
            planned_tool_calls=[ToolCall(tool_name="search_customer",
                                         arguments={"query": "GETA"})],
            context=_ctx_with_evidence(),
            user_message="SELL 2 CHAIRS TO GETA LTD FOR 54000",
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
            previous_calls=[ToolCall(tool_name="create_customer", arguments={})],
            escalated=True,
        )
        assert [c.tool_name for c in calls] == ["create_invoice"]
        assert "Recording the credit sale" in text
        # the escalated directive names the hollow plan and demands the write
        msg = client.seen_messages[0]
        assert "create_customer" in msg and "NO financial write" in msg
        assert "create_invoice" in msg
        # evidence was REUSED from round 1 — no lookup re-queried
        assert evidence == [
            {"kind": "search_customer", "records": [{"id": 1}], "error": None}
        ]
        # distinct telemetry source
        assert any(
            d == "PLANNING" and p.get("source") == "lookup_continuation_retry_result"
            for d, p in _no_log
        )

    @pytest.mark.asyncio
    async def test_a_write_less_retry_passes_its_text_back_for_the_card(self, _no_log):
        reply = {"tool_calls": [], "text": "I need the discount rate."}
        client = _StubClient(reply)
        calls, text, _ = await _continue_lookup_only_plan(
            client=client,
            session_id=uuid.uuid4(),
            execution_plan=_plan(),
            planned_tool_calls=[ToolCall(tool_name="search_customer",
                                         arguments={"query": "GETA"})],
            context=_ctx_with_evidence(),
            user_message="SELL 2 CHAIRS TO GETA LTD FOR 54000",
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
            previous_calls=[ToolCall(tool_name="create_customer", arguments={})],
            escalated=True,
        )
        assert calls == []
        assert text == "I need the discount rate."

    def test_the_gate_still_refuses_a_party_only_plan(self):
        assert _plan_performs_no_financial_mutation(
            intent="record_credit_sale",
            calls=[ToolCall(tool_name="create_customer", arguments={})],
        ) is True


# ---------------------------------------------------------------------------
# B — the card routes the real open gaps (source-contract test: the card is
# inline in execute(); the live behaviour is verified against production)
# ---------------------------------------------------------------------------

class TestCompletenessCardRoutesOpenGaps:
    def test_the_card_asks_open_gaps_before_the_dead_end(self):
        src = inspect.getsource(agent_mod)
        open_ask = src.index('f"Please answer: {_open_ask}')
        dead_end = src.index('"Nothing in your request is missing')
        assert open_ask < dead_end, (
            "the open-gap ask must be offered before the resend dead-end"
        )
        assert "required_fields=_required_info" in src
        assert '"open_questions": [q.get("field") for q in _open_qs]' in src

