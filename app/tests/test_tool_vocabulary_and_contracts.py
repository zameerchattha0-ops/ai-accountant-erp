"""Unit and Integration Tests for AI Tool Vocabulary & Argument Contracts.

Verifies:
1. All statutory tools and parameters are registered in _TOOL_REGISTRY.
2. Argument contracts accept new parameters (tax_pricing_mode, tax_rate_percent,
   wht_rate_percent, apply_income_tax, etc.) and aliases.
3. Tool selector exposes tax profile tools for sales, invoice, and tax intents.
4. Tool handlers correctly forward parameters and aliases.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, patch

from app.tools import _TOOL_REGISTRY
from app.tool_contract import validate_arguments
from app.tool_selector import tools_for_intent, intent_tools
from app.accounting_reasoning import _SYSTEM_RULES


class TestToolVocabularyAndContracts:
    """Verifies that LLM tool vocabulary, contracts, and selectors support statutory features."""

    def test_registry_contains_new_and_updated_tools(self):
        """Ensure all required tools are present in the central registry."""
        expected_tools = [
            "get_organization_tax_profile",
            "set_organization_tax_profile",
            "create_invoice",
            "record_cash_sale",
            "record_supplier_payment",
            "run_payroll",
            "pay_employee_salary",
        ]
        for tool_name in expected_tools:
            assert tool_name in _TOOL_REGISTRY, f"Tool {tool_name} must be in _TOOL_REGISTRY"
            assert callable(_TOOL_REGISTRY[tool_name]["handler"]), f"Handler for {tool_name} must be callable"

    def test_create_invoice_argument_contract(self):
        """Validate create_invoice contract accepts statutory tax parameters & aliases."""
        contract = _TOOL_REGISTRY["create_invoice"].get("contract")
        assert contract is not None, "create_invoice must declare an argument contract"

        # Valid payload with tax arguments
        args = {
            "customer_id": str(uuid.uuid4()),
            "tax_pricing_mode": "exclusive",
            "tax_rate_percent": 18.0,
            "tax_amount": 1800.0,
            "amount": 10000.0,
            "description": "IT Consulting Services",
        }
        errors = validate_arguments(contract, args)
        assert not errors, f"create_invoice rejected valid tax arguments: {errors}"

    def test_record_supplier_payment_argument_contract(self):
        """Validate record_supplier_payment contract accepts Section 153 WHT arguments & aliases."""
        contract = _TOOL_REGISTRY["record_supplier_payment"].get("contract")
        assert contract is not None, "record_supplier_payment must declare an argument contract"

        # Valid payload with canonical WHT parameters
        args = {
            "supplier_id": str(uuid.uuid4()),
            "amount": 50000.0,
            "wht_rate_percent": 5.0,
            "wht_amount": 2500.0,
        }
        errors = validate_arguments(contract, args)
        assert not errors, f"record_supplier_payment rejected canonical WHT arguments: {errors}"

        # Valid payload with aliases
        args_alias = {
            "supplier_name": "ABC Logistics",
            "amount": 50000.0,
            "wht_rate": 5.0,
            "payment_mode": "BANK_TRANSFER",
        }
        errors = validate_arguments(contract, args_alias)
        assert not errors, f"record_supplier_payment rejected WHT alias arguments: {errors}"

    def test_run_payroll_argument_contract(self):
        """Validate run_payroll contract accepts apply_income_tax and aliases."""
        contract = _TOOL_REGISTRY["run_payroll"].get("contract")
        assert contract is not None, "run_payroll must declare an argument contract"

        # Valid canonical payload
        args = {
            "apply_income_tax": True,
            "payment_method": "ACCRUED",
            "transaction_date": "2026-10-31",
        }
        errors = validate_arguments(contract, args)
        assert not errors, f"run_payroll rejected canonical income tax argument: {errors}"

        # Valid payload with aliases
        args_alias = {
            "withholding_tax": True,
            "payment_method": "PAID",
        }
        errors = validate_arguments(contract, args_alias)
        assert not errors, f"run_payroll rejected withholding_tax alias: {errors}"

    def test_pay_employee_salary_argument_contract(self):
        """Validate pay_employee_salary contract accepts apply_income_tax and aliases."""
        contract = _TOOL_REGISTRY["pay_employee_salary"].get("contract")
        assert contract is not None, "pay_employee_salary must declare an argument contract"

        args = {
            "employee": "EMP-001",
            "amount": 150000.0,
            "apply_income_tax": True,
        }
        errors = validate_arguments(contract, args)
        assert not errors, f"pay_employee_salary rejected apply_income_tax: {errors}"

        args_alias = {
            "employee": "EMP-001",
            "deduct_tax": True,
        }
        errors = validate_arguments(contract, args_alias)
        assert not errors, f"pay_employee_salary rejected deduct_tax alias: {errors}"

    def test_set_organization_tax_profile_argument_contract(self):
        """Validate set_organization_tax_profile contract."""
        contract = _TOOL_REGISTRY["set_organization_tax_profile"].get("contract")
        assert contract is not None, "set_organization_tax_profile must declare an argument contract"

        args = {
            "is_sales_tax_registered": True,
            "tax_authority": "FBR",
            "default_tax_pricing": "inclusive",
            "sales_tax_rate": 18.0,
        }
        errors = validate_arguments(contract, args)
        assert not errors, f"set_organization_tax_profile rejected valid profile arguments: {errors}"

    def test_tool_selector_intent_coverage(self):
        """Verify tool selector provides tax lookups and intent mappings."""
        # Check configure_tax_profile intent
        tax_tools = intent_tools("configure_tax_profile")
        assert "set_organization_tax_profile" in tax_tools
        assert "get_organization_tax_profile" in tax_tools

        # Check that sale intents include get_organization_tax_profile as a lookup
        sale_tools = tools_for_intent("record_credit_sale")
        assert "get_organization_tax_profile" in sale_tools

        invoice_tools = tools_for_intent("create_invoice")
        assert "get_organization_tax_profile" in invoice_tools

    def test_system_rules_contain_statutory_and_section_73_guidance(self):
        """Verify that _SYSTEM_RULES includes Pakistan tax and Section 73 guidance."""
        assert "STATUTORY TAX & COMPLIANCE RULES" in _SYSTEM_RULES
        assert "Sales Tax Splitting" in _SYSTEM_RULES
        assert "Section 153" in _SYSTEM_RULES
        assert "Section 149" in _SYSTEM_RULES
        assert "Section 73" in _SYSTEM_RULES
        assert "50,000" in _SYSTEM_RULES

    @pytest.mark.asyncio
    async def test_tax_profile_tool_handlers_execution(self):
        """Test invoking tax profile handlers directly through the tool registry."""
        org_id = uuid.uuid4()
        get_handler = _TOOL_REGISTRY["get_organization_tax_profile"]["handler"]
        set_handler = _TOOL_REGISTRY["set_organization_tax_profile"]["handler"]

        with patch("app.services.tax_service.get_organization_tax_profile", new_callable=AsyncMock) as mock_get, \
             patch("app.services.tax_service.set_organization_tax_profile", new_callable=AsyncMock) as mock_set:

            mock_get.return_value = {
                "is_sales_tax_registered": True,
                "tax_authority": "PRA",
                "default_tax_pricing": "exclusive",
                "sales_tax_rate": 16.0,
            }
            mock_set.return_value = {
                "is_sales_tax_registered": True,
                "tax_authority": "PRA",
                "default_tax_pricing": "exclusive",
                "sales_tax_rate": 16.0,
            }

            # Test GET handler
            get_res = await get_handler(org_id)
            assert get_res.success is True
            assert get_res.data["tax_authority"] == "PRA"
            mock_get.assert_awaited_once_with(org_id)

            # Test SET handler
            set_res = await set_handler(
                org_id,
                is_sales_tax_registered=True,
                tax_authority="PRA",
                default_tax_pricing="exclusive",
                sales_tax_rate=16.0,
            )
            assert set_res.success is True
            assert set_res.data["sales_tax_rate"] == 16.0
            mock_set.assert_awaited_once_with(
                organization_id=org_id,
                is_sales_tax_registered=True,
                tax_authority="PRA",
                default_tax_pricing="exclusive",
                sales_tax_rate=16.0,
            )

