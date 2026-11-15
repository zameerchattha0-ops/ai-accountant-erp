"""
Unit Tests for Advisory Query Router & Virtual CFO Dynamic Routing
===================================================================
Tests for Recommendation 1: Dynamic Query Routing (Mutations vs. Advisory).

Verifies:
1. Advisory queries like "Analyze our cash flow and expense trends",
   "How is our working capital?", "Give me a financial health check"
   are deterministically classified as 'financial_advisory'.
2. _missing_fields("financial_advisory", ...) returns [] so that no questionnaire is triggered.
3. No transactional questionnaires, party creation gates, or payment method questions
   are prompted for advisory queries.
4. Virtual CFO advisory engine connection in app.agent.execute().
"""

from __future__ import annotations

import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from app.models.schemas import AgentResponse, ExecutionStatus
from app.planner import (
    ADVISORY_INTENTS,
    _missing_fields,
    intent_for_message,
    plan,
    run_planner,
)


# ============================================================================
# 1. Intent Classification & Routing Tests
# ============================================================================

class TestAdvisoryQueryRouting:
    """Verifies that natural language advisory queries route to 'financial_advisory'."""

    @pytest.mark.parametrize(
        "query",
        [
            "Analyze our cash flow and expense trends",
            "How is our working capital?",
            "Give me a financial health check",
            "What is our working capital?",
            "Assess our financial health and performance",
            "Provide a Virtual CFO advisory assessment",
            "Virtual CFO financial diagnostic and report",
            "Give me tax advisory on compliance",
            "What are our cash runway and burn rate trends?",
            "Run DuPont analysis on our profitability and margins",
            "Strategic financial advice on liquidity and ratios",
            "Expense analysis and cost of sales trends",
            "Cash flow analysis for recent periods",
        ],
    )
    def test_advisory_queries_route_to_financial_advisory(self, query: str):
        execution_plan = plan(query)
        assert execution_plan.intent == "financial_advisory", (
            f"Query '{query}' expected intent 'financial_advisory' but got '{execution_plan.intent}'"
        )

    def test_run_planner_alias_matches_plan(self):
        """run_planner alias must function identically to plan()."""
        query = "Give me a financial health check"
        p1 = plan(query)
        p2 = run_planner(query)
        assert p1.intent == p2.intent == "financial_advisory"

    def test_intent_for_message_identifies_financial_advisory(self):
        assert intent_for_message("Analyze our cash flow and expense trends") == "financial_advisory"
        assert intent_for_message("How is our working capital?") == "financial_advisory"
        assert intent_for_message("Give me a financial health check") == "financial_advisory"

    def test_regular_reports_and_mutations_not_routed_to_advisory(self):
        """Standard reports and transactional mutations must NOT be hijacked by advisory patterns."""
        assert plan("generate cash flow statement").intent == "generate_cash_flow"
        assert plan("generate balance sheet").intent == "generate_balance_sheet"
        assert plan("generate profit and loss").intent == "generate_profit_loss"
        assert plan("list expenses").intent == "list_expenses"
        assert plan("Record cash purchase of laptop for 50000").intent in (
            "record_purchase",
            "record_cash_purchase",
        )
        assert plan("Create customer ABC Ltd").intent == "create_customer"


# ============================================================================
# 2. Missing Fields & Questionnaire Suppression Tests
# ============================================================================

class TestAdvisoryMissingFieldsAndQuestionnaires:
    """Verifies that advisory queries never trigger questionnaires or missing fields."""

    @pytest.mark.parametrize(
        "advisory_intent",
        [
            "financial_advisory",
            "financial_analysis",
            "health_check",
            "cash_flow_analysis",
            "expense_analysis",
            "tax_advisory",
        ],
    )
    def test_missing_fields_returns_empty_list(self, advisory_intent: str):
        # Even with completely empty entities or missing transactional fields
        empty_entities: Dict[str, Any] = {}
        assert _missing_fields(advisory_intent, empty_entities) == []

        sparse_entities: Dict[str, Any] = {
            "amount": None,
            "supplier_name": None,
            "customer_name": None,
            "payment_method": None,
            "transaction_date": None,
        }
        assert _missing_fields(advisory_intent, sparse_entities) == []

    @pytest.mark.parametrize(
        "query",
        [
            "Analyze our cash flow and expense trends",
            "How is our working capital?",
            "Give me a financial health check",
        ],
    )
    def test_execution_plan_has_no_missing_fields_or_clarification(self, query: str):
        execution_plan = plan(query)
        assert execution_plan.missing_fields == []
        assert execution_plan.clarification_questions == []
        assert execution_plan.requires_clarification is False
        assert execution_plan.requires_confirmation is False
        assert not execution_plan.batch_items

    def test_advisory_intents_constant_membership(self):
        assert "financial_advisory" in ADVISORY_INTENTS
        assert "financial_analysis" in ADVISORY_INTENTS
        assert "health_check" in ADVISORY_INTENTS
        assert "cash_flow_analysis" in ADVISORY_INTENTS
        assert "expense_analysis" in ADVISORY_INTENTS
        assert "tax_advisory" in ADVISORY_INTENTS


# ============================================================================
# 3. Agent Execution End-to-End Route Tests
# ============================================================================

class TestAgentAdvisoryExecutionRoute:
    """Verifies that agent.execute() routes advisory inquiries to CFO engine without gates."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query",
        [
            "Analyze our cash flow and expense trends",
            "How is our working capital?",
            "Give me a financial health check",
        ],
    )
    async def test_execute_advisory_bypasses_gates_and_completes(self, query: str):
        from app.agent import execute

        dummy_session_id = uuid.uuid4()
        dummy_org_id = uuid.uuid4()
        dummy_user_id = uuid.uuid4()

        mock_report = "## 📊 Executive Financial Health Summary\nOverall Health Score: **Strong**"

        with patch("app.agent.create_execution_session", new_callable=AsyncMock) as mock_create_sess, \
             patch("app.agent._preamble_side_effects", new_callable=AsyncMock) as mock_preamble, \
             patch("app.agent._load_org_facts", new_callable=AsyncMock) as mock_facts, \
             patch("app.org_context.business_profile", new_callable=AsyncMock) as mock_bprof, \
             patch("app.agent._update_status", new_callable=AsyncMock) as mock_update_status, \
             patch("app.agent._log_step", new_callable=AsyncMock) as mock_log_step, \
             patch("app.agent.create_execution_result", new_callable=AsyncMock) as mock_create_res, \
             patch("app.financial_advisor.generate_cfo_advisory", new_callable=AsyncMock) as mock_cfo_adv, \
             patch("app.financial_advisor.collect_cfo_evidence", new_callable=AsyncMock) as mock_collect_ev:

            mock_create_sess.return_value = {"id": str(dummy_session_id)}
            mock_preamble.return_value = {}
            mock_facts.return_value = ({}, {}, {})
            mock_bprof.return_value = {"name": "Test Org", "currency": "PKR"}
            mock_collect_ev.return_value = {"profit_and_loss": {"revenue": 1000000.0}}
            mock_cfo_adv.return_value = mock_report

            resp: AgentResponse = await execute(
                user_message=query,
                user_id=dummy_user_id,
                organization_id=dummy_org_id,
            )

            # 1. Must NOT park in clarification or confirmation
            assert resp.status == ExecutionStatus.COMPLETED
            assert resp.requires_user_input is not True
            assert resp.question is None

            # 2. Must invoke the CFO advisory engine
            mock_cfo_adv.assert_called_once()
            call_kwargs = mock_cfo_adv.call_args.kwargs
            assert call_kwargs["user_query"] == query
            assert "profit_and_loss" in call_kwargs["evidence"]

            # 3. Must log steps and update session to COMPLETED
            mock_update_status.assert_any_call(dummy_session_id, ExecutionStatus.COMPLETED)
            mock_log_step.assert_any_call(
                dummy_session_id,
                "COMPLETED",
                {"route": "financial_advisory", "intent": "financial_advisory"},
            )

            # 4. Must persist execution result
            mock_create_res.assert_called_once()
            res_kwargs = mock_create_res.call_args.kwargs
            assert res_kwargs["session_id"] == dummy_session_id
            assert res_kwargs["status"] == "COMPLETED"
            assert res_kwargs["action_type"] == "financial_advisory"
            assert res_kwargs["summary"] == mock_report

    @pytest.mark.asyncio
    async def test_execute_advisory_graceful_fallback_when_cfo_fails(self):
        """When CFO LLM generation raises an exception, graceful fallback synthesis succeeds."""
        from app.agent import execute

        dummy_session_id = uuid.uuid4()
        dummy_org_id = uuid.uuid4()
        dummy_user_id = uuid.uuid4()

        with patch("app.agent.create_execution_session", new_callable=AsyncMock) as mock_create_sess, \
             patch("app.agent._preamble_side_effects", new_callable=AsyncMock) as mock_preamble, \
             patch("app.agent._load_org_facts", new_callable=AsyncMock) as mock_facts, \
             patch("app.org_context.business_profile", new_callable=AsyncMock) as mock_bprof, \
             patch("app.agent._update_status", new_callable=AsyncMock), \
             patch("app.agent._log_step", new_callable=AsyncMock), \
             patch("app.agent.create_execution_result", new_callable=AsyncMock), \
             patch("app.financial_advisor.generate_cfo_advisory", side_effect=RuntimeError("AI provider error")), \
             patch("app.financial_advisor.collect_cfo_evidence", new_callable=AsyncMock) as mock_collect_ev:

            mock_create_sess.return_value = {"id": str(dummy_session_id)}
            mock_preamble.return_value = {}
            mock_facts.return_value = ({}, {}, {})
            mock_bprof.return_value = {"name": "Test Org", "currency": "PKR"}
            mock_collect_ev.return_value = {}

            resp: AgentResponse = await execute(
                user_message="Analyze our cash flow and expense trends",
                user_id=dummy_user_id,
                organization_id=dummy_org_id,
            )

            # Must still complete gracefully via deterministic fallback synthesis
            assert resp.status == ExecutionStatus.COMPLETED
            assert "Executive Financial Health Summary" in resp.summary
            assert resp.requires_user_input is not True
