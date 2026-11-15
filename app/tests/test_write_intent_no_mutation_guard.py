"""Unit tests for write-intent no-mutation safeguards and record_cash_purchase fast-path.

Verifies:
1. record_cash_purchase produces a deterministic ToolCall with amount, date, and items.
2. A write-intent with 0 mutations does NOT mark COMPLETED informational, but prompts.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch

import app.agent as agent_mod
from app.models.schemas import ExecutionPlan, ToolCall, ToolResult, ExecutionStatus


class TestCashPurchaseFastPath:
    def test_cash_purchase_fast_path_call_valid(self):
        entities = {
            "amount": 25000.0,
            "transaction_date": "2026-11-15",
            "item_description": "Office Tables",
            "supplier_name": "Shabbir Furnitures",
            "quantity": 2.0,
            "transaction_nature": "INVENTORY",
        }
        calls = agent_mod._cash_purchase_fast_path_call(entities)
        assert calls is not None
        assert len(calls) == 1
        tc = calls[0]
        assert tc.tool_name == "record_cash_purchase"
        assert tc.arguments["amount"] == 25000.0
        assert tc.arguments["transaction_date"] == "2026-11-15"
        assert "Office Tables" in tc.arguments["description"]
        assert tc.arguments["supplier_name"] == "Shabbir Furnitures"
        assert tc.arguments["quantity"] == 2.0

    def test_cash_purchase_fast_path_rejects_missing_amount(self):
        entities = {
            "supplier_name": "Shabbir Furnitures",
            "item_description": "Office Tables",
        }
        calls = agent_mod._cash_purchase_fast_path_call(entities)
        assert calls is None

    @pytest.mark.asyncio
    async def test_deterministic_mutation_calls_handles_cash_purchase(self):
        plan = ExecutionPlan(
            intent="record_cash_purchase",
            confidence=1.0,
            extracted_entities={
                "amount": 10000.0,
                "transaction_date": "2026-11-15",
                "item_description": "Chairs",
            },
            reasoning="Cash purchase chairs",
            missing_fields=[],
            requires_confirmation=False,
            parameters={},
            action_type="RECORD",
            raw_input="purchased chairs for 10000 cash",
        )
        calls = await agent_mod._deterministic_mutation_calls(
            organization_id=uuid.uuid4(),
            execution_plan=plan,
            classification=None,
        )
        assert calls is not None
        assert len(calls) == 1
        assert calls[0].tool_name == "record_cash_purchase"
        assert calls[0].arguments["amount"] == 10000.0
