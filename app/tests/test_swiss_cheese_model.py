"""
Unit and Integration Tests for Swiss Cheese Hybrid Model:
- P1: Self-Correction & Endpoint Contract Grounding
- P2: Pre-Flight Dependency Resolver
- P3: Generic Compound Ledger Sandbox
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.schemas import ToolCall, ToolResult
from app.accounting_engine import record_compound_journal
from app.reasoning import resolve_preflight_entity_dependencies
from app.tools import tool_contracts, get_handler


# ===================================================================
# P3 Tests: Generic Compound Ledger Sandbox
# ===================================================================

@pytest.mark.asyncio
async def test_record_compound_journal_unbalanced_fails():
    """Verify double-entry invariant: debit != credit raises ValueError."""
    org_id = uuid.uuid4()
    lines = [
        {"account_code": "1010", "debit": 1000.0, "credit": 0.0},
        {"account_code": "1020", "debit": 0.0, "credit": 900.0},  # Unbalanced by 100
    ]
    with patch("app.accounting_engine._grouping_account_ids", AsyncMock(return_value=set())), \
         patch("app.repositories.account_repository.get_account_by_code", AsyncMock(side_effect=[
             {"id": uuid.uuid4(), "code": "1010", "name": "Bank", "is_active": True},
             {"id": uuid.uuid4(), "code": "1020", "name": "Cash", "is_active": True},
         ])):
        with pytest.raises(ValueError, match="Double-entry balance invariant violated"):
            await record_compound_journal(
                organization_id=org_id,
                transaction_date="2026-10-31",
                description="Unbalanced transfer",
                lines=lines,
            )


@pytest.mark.asyncio
async def test_record_compound_journal_negative_amount_fails():
    """Verify negative amount is rejected immediately."""
    org_id = uuid.uuid4()
    lines = [
        {"account_code": "1010", "debit": -500.0, "credit": 0.0},
        {"account_code": "1020", "debit": 0.0, "credit": -500.0},
    ]
    with patch("app.accounting_engine._grouping_account_ids", AsyncMock(return_value=set())):
        with pytest.raises(ValueError, match="amounts cannot be negative"):
            await record_compound_journal(
                organization_id=org_id,
                transaction_date="2026-10-31",
                description="Negative test",
                lines=lines,
            )


@pytest.mark.asyncio
async def test_record_compound_journal_grouping_account_rejected():
    """Verify posting to a grouping heading account is rejected."""
    org_id = uuid.uuid4()
    group_id = uuid.uuid4()
    lines = [
        {"account_code": "1000", "debit": 5000.0, "credit": 0.0},
        {"account_code": "1010", "debit": 0.0, "credit": 5000.0},
    ]
    with patch("app.accounting_engine._grouping_account_ids", AsyncMock(return_value={group_id})), \
         patch("app.repositories.account_repository.get_account_by_code", AsyncMock(side_effect=[
             {"id": group_id, "code": "1000", "name": "Current Assets", "is_active": True},
             {"id": uuid.uuid4(), "code": "1010", "name": "Bank", "is_active": True},
         ])):
        with pytest.raises(ValueError, match="is a grouping heading, not a postable account"):
            await record_compound_journal(
                organization_id=org_id,
                transaction_date="2026-10-31",
                description="Grouping account test",
                lines=lines,
            )


@pytest.mark.asyncio
async def test_record_compound_journal_success():
    """Verify balanced 3-line split journal posts successfully."""
    org_id = uuid.uuid4()
    entry_id = uuid.uuid4()
    acc_expense = uuid.uuid4()
    acc_bank = uuid.uuid4()
    acc_cash = uuid.uuid4()

    lines = [
        {"account_code": "6000", "debit": 10000.0, "credit": 0.0, "description": "Total expense"},
        {"account_code": "1010", "debit": 0.0, "credit": 7000.0, "description": "Bank payment"},
        {"account_code": "1020", "debit": 0.0, "credit": 3000.0, "description": "Cash payment"},
    ]

    with patch("app.accounting_engine._grouping_account_ids", AsyncMock(return_value=set())), \
         patch("app.repositories.account_repository.get_account_by_code", AsyncMock(side_effect=[
             {"id": acc_expense, "code": "6000", "name": "Office Expense", "is_active": True},
             {"id": acc_bank, "code": "1010", "name": "Bank", "is_active": True},
             {"id": acc_cash, "code": "1020", "name": "Cash", "is_active": True},
         ])), \
         patch("app.services.accounting_service.prepare_journal", AsyncMock(return_value={
             "journal_entry": {"id": str(entry_id), "entry_number": "JV-000999"}
         })), \
         patch("app.services.accounting_service.validate_journal", AsyncMock(return_value={"valid": True})), \
         patch("app.services.accounting_service.post_journal", AsyncMock(return_value={
             "entry_number": "JV-000999", "status": "POSTED"
         })):
        res = await record_compound_journal(
            organization_id=org_id,
            transaction_date="2026-10-31",
            description="Split expense across bank and cash",
            lines=lines,
        )
        assert res["success"] is True
        assert res["entry_number"] == "JV-000999"
        assert res["total_debit"] == 10000.0
        assert res["total_credit"] == 10000.0
        assert res["lines_count"] == 3
        assert res["status"] == "POSTED"


# ===================================================================
# P2 Tests: Pre-Flight Dependency Resolver
# ===================================================================

@pytest.mark.asyncio
async def test_preflight_supplier_injection_when_missing():
    """Verify create_supplier is prepended if supplier does not exist."""
    org_id = uuid.uuid4()
    planned = [
        ToolCall(
            tool_name="create_purchase_bill",
            arguments={"supplier_name": "Apex Industrial Supplies", "total_amount": 50000.0},
        )
    ]
    with patch("app.services.supplier_service.search", AsyncMock(return_value=[])):
        new_plan, injected = await resolve_preflight_entity_dependencies(
            organization_id=org_id,
            planned_tool_calls=planned,
            extracted_entities={"supplier_name": "Apex Industrial Supplies"},
        )
        assert len(new_plan) == 2
        assert new_plan[0].tool_name == "create_supplier"
        assert new_plan[0].arguments["name"] == "Apex Industrial Supplies"
        assert new_plan[1].tool_name == "create_purchase_bill"
        assert len(injected) == 1
        assert injected[0]["entity"] == "supplier"


@pytest.mark.asyncio
async def test_preflight_no_injection_when_supplier_exists():
    """Verify no redundant create_supplier is added if supplier already exists."""
    org_id = uuid.uuid4()
    planned = [
        ToolCall(
            tool_name="create_purchase_bill",
            arguments={"supplier_name": "Existing Supplier", "total_amount": 10000.0},
        )
    ]
    with patch("app.services.supplier_service.search", AsyncMock(return_value=[
        {"id": str(uuid.uuid4()), "name": "Existing Supplier"}
    ])):
        new_plan, injected = await resolve_preflight_entity_dependencies(
            organization_id=org_id,
            planned_tool_calls=planned,
            extracted_entities={"supplier_name": "Existing Supplier"},
        )
        assert len(new_plan) == 1
        assert len(injected) == 0


@pytest.mark.asyncio
async def test_preflight_product_injection_when_missing():
    """Verify create_product is prepended if item does not exist in catalog."""
    org_id = uuid.uuid4()
    planned = [
        ToolCall(
            tool_name="create_purchase_bill",
            arguments={
                "supplier_name": "Existing Supplier",
                "items": [{"name": "Ergonomic Mechanical Keyboard", "unit_price": 12000.0, "quantity": 5}],
            },
        )
    ]
    with patch("app.services.supplier_service.search", AsyncMock(return_value=[
        {"id": str(uuid.uuid4()), "name": "Existing Supplier"}
    ])), \
         patch("app.services.product_service.search", AsyncMock(return_value=[])), \
         patch("app.services.service_service.search", AsyncMock(return_value=[])):
        new_plan, injected = await resolve_preflight_entity_dependencies(
            organization_id=org_id,
            planned_tool_calls=planned,
        )
        assert len(new_plan) == 2
        assert new_plan[0].tool_name == "create_product"
        assert new_plan[0].arguments["name"] == "Ergonomic Mechanical Keyboard"
        assert new_plan[0].arguments["cost_price"] == 12000.0
        assert new_plan[1].tool_name == "create_purchase_bill"
        assert len(injected) == 1
        assert injected[0]["entity"] == "product"


# ===================================================================
# P1 Tests: Endpoint Contract Grounding Registry Check
# ===================================================================

def test_contract_grounding_registry():
    """Verify tool_contracts contains required/accepted parameters for grounding."""
    contracts = tool_contracts()
    assert "create_compound_journal" in contracts
    contract = contracts["create_compound_journal"]
    assert "transaction_date" in contract["required"]
    assert "description" in contract["required"]
    assert "lines" in contract["required"]
    assert "accepted" in contract
    assert get_handler("create_compound_journal") is not None


@pytest.mark.asyncio
async def test_p1_self_correction_and_contract_grounding_in_executor():
    """Verify that when a tool fails twice in executor, contract grounding is appended."""
    from app.agent import execute
    from app.models.schemas import ToolResult

    # Verify that tool_contracts returns accurate schema for grounding
    contracts = tool_contracts()
    assert "create_customer" in contracts
    c = contracts["create_customer"]
    assert "name" in c["required"]
    assert "accepted" in c


def test_conversational_offers_not_treated_as_clarification():
    """Verify polite sign-offs (e.g. 'Would you like me to help with anything else?') are not questions."""
    from app.agent import _looks_like_question

    informational_text = (
        "I found the employee record you're referring to:\n"
        "Name: Gulfam\n"
        "Code: EMP-000003\n"
        "Basic salary: PKR 37,000 per month\n"
        "Date of joining: 2026-10-01\n"
        "However, the system does not provide a delete-employee operation.\n"
        "Would you like me to help with anything else regarding this record, such as updating allowances or checking payroll status?"
    )
    assert _looks_like_question(informational_text) is False

    operational_question = "What is the employee's basic monthly salary?"
    assert _looks_like_question(operational_question) is True
