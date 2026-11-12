"""Tests for modular system prompt assembly and unified domain pipelines."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.accounting_reasoning import (
    _BASE_SYSTEM_RULES,
    _DEPRECIATION_RULES,
    _LOAN_RULES,
    _PAYROLL_RULES,
    _PROCUREMENT_RULES,
    _SYSTEM_RULES,
    _TAX_COMPLIANCE_RULES,
    ReasoningFacts,
    build_reasoning_prompt,
)
from app.pipelines import (
    TransactionPlan,
    dispatch_plan,
    expenses,
    fixed_assets,
    purchases,
    sales,
)
from app.pipelines.common import SelectedTool


class TestPromptModules:
    def test_base_prompt_no_args_under_8k_chars(self):
        prompt = build_reasoning_prompt()
        assert prompt == _BASE_SYSTEM_RULES
        assert len(prompt) < 8_000
        assert "PRIMARY ACCOUNTING REASONING LAYER" in prompt
        assert "HARD PROHIBITIONS" in prompt

    @pytest.mark.parametrize(
        "section,module_rules",
        [
            ("tax", _TAX_COMPLIANCE_RULES),
            ("purchases", _PROCUREMENT_RULES),
            ("depreciation", _DEPRECIATION_RULES),
            ("fixed_assets", _DEPRECIATION_RULES),
            ("loans", _LOAN_RULES),
            ("payroll", _PAYROLL_RULES),
        ],
    )
    def test_base_plus_single_module_under_15k_chars(self, section, module_rules):
        prompt = build_reasoning_prompt(section=section)
        assert module_rules in prompt
        assert len(prompt) < 15_000

    def test_purchases_section_includes_procurement_rules(self):
        prompt = build_reasoning_prompt(section="purchases")
        assert _PROCUREMENT_RULES in prompt
        assert "create_purchase_order" in prompt
        assert "RFQ" in prompt

    def test_tax_section_includes_sales_tax_splitting_and_section_73(self):
        prompt = build_reasoning_prompt(section="tax")
        assert "Sales Tax Splitting" in prompt
        assert "Section 73" in prompt
        assert "Section 153" in prompt
        assert "50,000" in prompt

    def test_intent_loads_relevant_module(self):
        payroll_prompt = build_reasoning_prompt(intent="run_payroll")
        assert "Section 149" in payroll_prompt
        assert len(payroll_prompt) < 15_000

        loan_prompt = build_reasoning_prompt(intent="record_loan")
        assert "AMORTIZATION" in loan_prompt
        assert len(loan_prompt) < 15_000

    def test_full_system_rules_retains_statutory_guidance(self):
        assert "STATUTORY TAX & COMPLIANCE RULES" in _SYSTEM_RULES
        assert "Sales Tax Splitting" in _SYSTEM_RULES
        assert "Section 73" in _SYSTEM_RULES

    def test_backward_compatible_with_reasoning_facts(self):
        facts = ReasoningFacts(user_request="Record cash expense of 4000 for fuel")
        prompt = build_reasoning_prompt(facts, section="expenses")
        assert "ORIGINAL USER REQUEST" in prompt
        assert "Record cash expense of 4000 for fuel" in prompt
        assert "Section 73" in prompt
        assert "RESPONSE FORMAT" in prompt


class TestTransactionPlanAndPipelines:
    def test_pipeline_modules_importable_with_handle(self):
        for mod in (purchases, sales, expenses, fixed_assets):
            assert callable(getattr(mod, "handle", None))

    def test_transaction_plan_validation_and_normalization(self):
        plan = TransactionPlan(
            intent="create_invoice",
            nature="services",
            section="SALES",
            entities={"customer_name": "Apex Ltd", "amount": 50000},
            questions=[{"field": "transaction_date", "question": "What date?"}],
            tool_selection=[
                "create_invoice",
                SelectedTool(tool_name="get_organization_tax_profile", arguments={}),
            ],
        )
        assert plan.intent == "create_invoice"
        assert plan.nature == "SERVICE" or plan.nature == "SERVICES"
        assert plan.section == "sales"
        normalized = plan.normalized_tool_selection()
        assert normalized[0]["tool_name"] == "create_invoice"
        assert normalized[1]["tool_name"] == "get_organization_tax_profile"

    def test_transaction_plan_rejects_empty_intent(self):
        with pytest.raises(ValidationError):
            TransactionPlan(intent="   ")

    @pytest.mark.asyncio
    async def test_purchases_pipeline_rfq_and_section_73_warning(self):
        plan = TransactionPlan(
            intent="create_purchase_order",
            nature="FIXED_ASSET",
            entities={
                "supplier_name": "Shabbir Furniture",
                "item_description": "Office Sofa",
                "quantity": 2,
                "amount": 120000,
                "payment_method": "CASH",
                "transaction_date": "2026-10-20",
            },
        )
        res = await purchases.handle(plan, "org-1")
        assert res["status"] == "ready"
        assert res["section"] == "purchases"
        assert res["tool_calls"][0]["tool_name"] == "create_purchase_order"
        assert res["tool_calls"][0]["arguments"]["transaction_nature"] == "FIXED_ASSET"
        assert any("Section 73" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_sales_pipeline_invoice_builds_lines(self):
        plan = TransactionPlan(
            intent="create_invoice",
            nature="GOODS",
            entities={
                "customer_name": "FDS Labs Pvt",
                "amount": 60000,
                "quantity": 2,
                "item_description": "Network Switch",
                "transaction_date": "2026-10-20",
                "tax_pricing_mode": "exclusive",
                "tax_rate_percent": 18.0,
            },
        )
        res = await sales.handle(plan, "org-1")
        assert res["status"] == "ready"
        call = res["tool_calls"][0]
        assert call["tool_name"] == "create_invoice"
        assert call["arguments"]["customer_name"] == "FDS Labs Pvt"
        assert call["arguments"]["items"][0]["unit_price"] == 30000.0
        assert call["arguments"]["tax_rate_percent"] == 18.0

    @pytest.mark.asyncio
    async def test_expenses_pipeline_needs_no_supplier_and_checks_section_73(self):
        plan = TransactionPlan(
            intent="record_expense",
            nature="OPERATING_EXPENSE",
            entities={
                "amount": 75000,
                "transaction_purpose": "Office Rent",
                "payment_method": "CASH",
                "transaction_date": "2026-10-20",
            },
        )
        res = await expenses.handle(plan, "org-1")
        assert res["status"] == "ready"
        assert res["tool_calls"][0]["tool_name"] == "record_expense"
        assert any("Section 73" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_fixed_assets_pipeline_attaches_ito_rate_and_dispatches(self):
        plan = TransactionPlan(
            intent="register_fixed_asset",
            nature="FIXED_ASSET",
            entities={
                "asset_name": "Dell PowerEdge Server",
                "amount": 250000,
                "payment_method": "BANK",
                "transaction_date": "2026-10-20",
            },
        )
        res = await dispatch_plan(plan, "org-1")
        assert res["status"] == "ready"
        assert res["section"] == "fixed_assets"
        call = res["tool_calls"][0]
        assert call["tool_name"] == "register_fixed_asset"
        assert call["arguments"]["ito_rate_percent"] == 30.0
