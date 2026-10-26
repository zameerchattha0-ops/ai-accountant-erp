"""
Unit tests for Universal Module Execution, Intelligent LLM Identification,
Anti-Blind-Assumption Guard, and Direct Endpoint Delegation across all ERP modules.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.erp_endpoints import (
    ERP_MODULES,
    ERP_TASKS,
    is_operational_task,
    format_operational_summary,
)
from app.planner import plan, _missing_fields, _questions_for_fields
from app.reasoning import options_for_question
from app.models.schemas import ToolResult


class TestERPModuleRegistry:
    def test_all_14_modules_registered(self):
        expected_modules = {
            "accounting", "customers", "suppliers", "catalogue", "banking",
            "sales", "purchases", "expenses", "employees", "fixed_assets",
            "loans", "projects", "recurring", "reports",
        }
        assert expected_modules.issubset(set(ERP_MODULES.keys()))

    def test_operational_task_classification(self):
        assert is_operational_task("create_account") is True
        assert is_operational_task("create_customer") is True
        assert is_operational_task("create_supplier") is True
        assert is_operational_task("create_product") is True
        assert is_operational_task("create_bank_account") is True
        assert is_operational_task("create_employee") is True
        # Financial transactions are not operational tasks
        assert is_operational_task("record_credit_sale") is False
        assert is_operational_task("record_expense") is False

    def test_operational_summary_formatting(self):
        acct_summary = format_operational_summary("create_account", {
            "name": "Software Subscriptions",
            "code": "6150",
            "account_type": "EXPENSE",
        })
        assert "Software Subscriptions" in acct_summary
        assert "6150" in acct_summary
        assert "EXPENSE" in acct_summary
        assert "/accounting" in acct_summary

        cust_summary = format_operational_summary("create_customer", {
            "name": "Global Traders",
        })
        assert "Global Traders" in cust_summary
        assert "/customers" in cust_summary


class TestIntelligentPerceptionAndAntiBlindAssumption:
    def test_create_account_missing_type_triggers_clarification(self):
        """When user says 'CREATE A CHART OF ACCOUNT Marketing Expense' without type,
        the system must NOT assume blindly - it MUST ask for the account type."""
        plan_obj = plan("CREATE A CHART OF ACCOUNT 'Marketing Expense'")
        assert plan_obj.intent == "create_account"
        assert plan_obj.extracted_entities.get("account_name") == "Marketing Expense"
        assert "account_type" in plan_obj.missing_fields
        assert plan_obj.requires_clarification is True
        assert any("type of account" in q.lower() for q in plan_obj.clarification_questions)

    def test_account_type_question_provides_structured_chips(self):
        """The question for account type must offer structured chips: Expense, Asset, Liability, Revenue, Equity."""
        q = "What type of account is this in the Chart of Accounts? Reply with ASSET, LIABILITY, EQUITY, REVENUE, or EXPENSE."
        opts = options_for_question(q)
        assert opts is not None
        values = [o["value"] for o in opts]
        assert "EXPENSE" in values
        assert "ASSET" in values
        assert "LIABILITY" in values
        assert "REVENUE" in values
        assert "EQUITY" in values

    def test_create_account_with_all_facts_requires_no_clarification(self):
        """When user provides name and type (via prefill or message), no clarification is needed."""
        prefill = {
            "account_name": "Office Stationery",
            "account_type": "EXPENSE",
            "code": "6120",
        }
        plan_obj = plan("Create an expense chart of account for Office Stationery with code 6120", prefill_entities=prefill)
        assert plan_obj.intent == "create_account"
        assert plan_obj.requires_clarification is False
        assert plan_obj.requires_accounting_engine is False  # Operational task!

    def test_create_customer_missing_name_triggers_clarification(self):
        """Creating customer with no name requires clarification."""
        plan_obj = plan("Add new customer")
        assert plan_obj.intent == "create_customer"
        assert "customer_name" in plan_obj.missing_fields
        assert plan_obj.requires_clarification is True

    def test_create_customer_with_llm_prefill_proceeds(self):
        """LLM extracted customer name from natural query without regex template."""
        prefill = {"customer_name": "Pak Arab Mills Ltd"}
        plan_obj = plan("Please register our regular buyer Pak Arab Mills Ltd in the system", prefill_entities=prefill)
        assert plan_obj.intent == "create_customer"
        assert plan_obj.extracted_entities.get("customer_name") == "Pak Arab Mills Ltd"
        assert plan_obj.requires_clarification is False
        assert plan_obj.requires_accounting_engine is False

    def test_create_product_missing_price_triggers_clarification(self):
        """Adding product without sales price must not assume 0; it asks clarification."""
        prefill = {"product_name": "Industrial Valves"}
        plan_obj = plan("Add product Industrial Valves into catalogue", prefill_entities=prefill)
        assert plan_obj.intent == "create_product"
        assert "sales_price" in plan_obj.missing_fields
        assert plan_obj.requires_clarification is True


class TestClarificationAnswerParsing:
    def test_account_type_answer_merges_cleanly(self):
        """When user answers 'Expense' or 'Liability', it normalizes to uppercase."""
        from app.planner import _merge_field_answer
        merged = {}
        ok = _merge_field_answer(merged, "account_type", "expense")
        assert ok is True
        assert merged["account_type"] == "EXPENSE"

        merged2 = {}
        ok2 = _merge_field_answer(merged2, "account_type", "Liability")
        assert ok2 is True
        assert merged2["account_type"] == "LIABILITY"

    def test_clarification_history_resolves_plan(self):
        """Round 1 asks for account_type; Round 2 provides it in history -> plan is complete."""
        history = [
            {
                "question": "What type of account is this in the Chart of Accounts?",
                "answer": "Expense",
                "required_information": ["account_type"],
            }
        ]
        prefill = {"account_name": "Travel Allowance"}
        plan_obj = plan(
            "CREATE A CHART OF ACCOUNT 'Travel Allowance'",
            clarification_history=history,
            prefill_entities=prefill,
        )
        assert plan_obj.intent == "create_account"
        assert plan_obj.extracted_entities.get("account_type") == "EXPENSE"
        assert plan_obj.requires_clarification is False

