"""Pinning test: verify expenses are unlinked from supplier requirements.

Operating expenses (rent, utilities, travel, refreshments, repairs) do NOT
relate to trade suppliers. They must never require supplier records, trigger
party gates, or block on unknown supplier names.
"""
import uuid
import pytest
from app.models.schemas import ToolCall, ExecutionPlan
from app.plan_materialization import prepare_plan, DECLARED_REFERENCES
from app.agent import _party_resolution_question, _expense_fast_path_call


def test_create_expense_not_in_declared_references():
    """create_expense does not need foreign-key UUID resolution for suppliers."""
    assert "create_expense" not in DECLARED_REFERENCES


@pytest.mark.asyncio
async def test_create_expense_does_not_block_on_unregistered_payee():
    """An expense paid to an unregistered entity (e.g. landlord, power company)

    must never be blocked by plan_materialization demanding a supplier ledger.
    """
    call = ToolCall(
        tool_name="create_expense",
        arguments={
            "description": "Warehouse Rent",
            "subtotal": 45000.0,
            "payee_name": "Random Landlord LLC",
        },
    )
    mat = await prepare_plan(
        organization_id=uuid.uuid4(),
        calls=[call],
    )
    assert not mat.blocked, f"Expected unblocked plan but got blocks: {mat.blocks}"
    assert len(mat.calls) == 1
    assert mat.calls[0].tool_name == "create_expense"
    assert mat.calls[0].arguments["payee_name"] == "Random Landlord LLC"


@pytest.mark.asyncio
async def test_party_resolution_question_skips_record_expense():
    """_party_resolution_question must never ask to create a supplier ledger

    when the intent is record_expense, even if supplier_name or party is present.
    """
    plan = ExecutionPlan(
        intent="record_expense",
        clarification=False,
        extracted_entities={
            "amount": 12000.0,
            "transaction_purpose": "electricity",
            "supplier_name": "K-Electric Utility",
            "party": "K-Electric Utility",
        },
    )
    q = await _party_resolution_question(
        organization_id=uuid.uuid4(),
        execution_plan=plan,
    )
    assert q is None, f"Expected None but got party question: {q}"


def test_expense_fast_path_does_not_inject_local_vendor():
    """_expense_fast_path_call must not inject 'Local Vendor' as payee placeholder."""
    from types import SimpleNamespace
    entities = {
        "amount": 850.0,
        "transaction_date": "2026-10-22",
        "transaction_purpose": "travel",
        "transaction_nature": "OPERATING_EXPENSE",
        "payment_method": "CASH",
        "settlement_position": "PAID_NOW",
    }
    classification = SimpleNamespace(account_hint_id="00000000-0000-0000-0000-000000000001")
    calls = _expense_fast_path_call(entities, classification)
    assert calls is not None
    assert len(calls) == 1
    assert calls[0].tool_name == "create_expense"
    assert calls[0].arguments["payee_name"] == ""
