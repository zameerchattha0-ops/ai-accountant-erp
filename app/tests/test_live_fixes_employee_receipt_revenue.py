"""
Tests verifying fixes for:
1. Employee creation ("record an employee", "record an emplyee") - correct intent, requires date_of_joining, basic_salary, never goes to COA.
2. Receipt & payment adjustment against open invoice/bill ("against invoice 12", "against bill 5").
3. Cash sale revenue account resolution for items with general revenue fallback.
"""

import uuid
import pytest
from app.planner import plan as run_planner, intent_for_message, _identify_intent
from app.plan_materialization import resolve_reference, ReferenceSpec
from app.services import revenue_ledger_service


def test_employee_intent_matching_and_missing_fields():
    # Test intent matching with 'record' and typos
    assert _identify_intent("record an employee") == "create_employee"
    assert _identify_intent("record an emplyee") == "create_employee"
    assert _identify_intent("record employee Ahmad") == "create_employee"
    assert _identify_intent("add employee") == "create_employee"

    # Plan for bare "record an employee"
    plan = run_planner("record an employee")
    assert plan.intent == "create_employee"
    assert "employee_name" in plan.missing_fields
    assert "date_of_joining" in plan.missing_fields
    assert "basic_salary" in plan.missing_fields
    assert plan.requires_clarification is True

    # Check that questions are generated for missing fields
    assert any("full name" in q.lower() for q in plan.clarification_questions)
    assert any("joining" in q.lower() for q in plan.clarification_questions)
    assert any("salary" in q.lower() for q in plan.clarification_questions)


def test_employee_operational_task_bypass():
    from app.erp_endpoints import is_operational_task
    assert is_operational_task("create_employee") is True


@pytest.mark.asyncio
async def test_resolve_open_invoice_and_bill():
    from app.agent import _resolve_open_document_reference
    from unittest.mock import AsyncMock, patch

    org_id = uuid.uuid4()
    mock_inv_id = uuid.uuid4()
    mock_cust_id = uuid.uuid4()

    mock_invoice = {
        "id": str(mock_inv_id),
        "invoice_number": "INV-000012",
        "customer_id": str(mock_cust_id),
        "total": 30000.0,
        "paid_amount": 10000.0,
    }

    mock_customer = {
        "id": str(mock_cust_id),
        "name": "Ahmad Enterprise",
    }

    with patch("app.repositories.invoice_repository.get_invoice_by_number", new=AsyncMock(side_effect=lambda o, invoice_number: mock_invoice if invoice_number in ("12", "INV-000012") else None)), \
         patch("app.repositories.invoice_repository.list_invoices", new=AsyncMock(return_value=[mock_invoice])), \
         patch("app.services.customer_service.get", new=AsyncMock(return_value=mock_customer)):

        entities = {"invoice_number": "12"}
        await _resolve_open_document_reference(org_id, entities)

        assert entities["invoice_id"] == str(mock_inv_id)
        assert entities["invoice_number"] == "INV-000012"
        assert entities["customer_id"] == str(mock_cust_id)
        assert entities["customer_name"] == "Ahmad Enterprise"
        assert entities["amount"] == 20000.0  # Remaining balance (30000 - 10000)


@pytest.mark.asyncio
async def test_revenue_ledger_fallback_to_general_revenue():
    org_id = uuid.uuid4()
    general_rev_account = {
        "id": str(uuid.uuid4()),
        "name": "Sales Revenue",
        "type": "REVENUE",
    }
    consulting_rev_account = {
        "id": str(uuid.uuid4()),
        "name": "Consulting Revenue",
        "type": "REVENUE",
    }

    from unittest.mock import AsyncMock, patch

    with patch("app.services.revenue_ledger_service.list_revenue_accounts", new=AsyncMock(return_value=[general_rev_account, consulting_rev_account])):
        account, label, reason = await revenue_ledger_service.resolve_revenue_account(org_id, "2 office chairs")
        assert account is not None
        assert account["name"] == "Sales Revenue"
        assert reason == "general"


def test_llm_primary_intent_authority():
    # Even with unusual wording that regex would classify as unknown,
    # the LLM's semantic intent and extracted facts are authoritative
    unusual_msg = "Please welcome our newest colleague Zameer into the personnel system"
    llm_prefill = {
        "semantic_intent": "create_employee",
        "employee_name": "Zameer",
        "date_of_joining": "2026-11-01",
        "basic_salary": 150000.0,
    }
    plan = run_planner(unusual_msg, prefill_entities=llm_prefill)
    assert plan.intent == "create_employee"
    assert plan.extracted_entities["employee_name"] == "Zameer"
    assert plan.extracted_entities["date_of_joining"] == "2026-11-01"
    assert plan.extracted_entities["basic_salary"] == 150000.0
    assert plan.missing_fields == []
    assert plan.requires_clarification is False

