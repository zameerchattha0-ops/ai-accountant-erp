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


@pytest.mark.asyncio
async def test_cash_purchase_does_not_prompt_party_creation(monkeypatch):
    """Bug 3 regression: cash purchase with supplier name must never prompt to create supplier ledger."""
    from types import SimpleNamespace
    from app.agent import _party_resolution_question

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("Should not look up/create party for cash purchase")

    monkeypatch.setattr("app.database.fetch_one", fail_if_called, raising=False)

    plan_cash_intent = SimpleNamespace(
        intent="record_cash_purchase",
        extracted_entities={"supplier_name": "Shabbir Furnitures", "payment_method": "CASH"},
        impact_map={"party_ledger": False},
    )
    assert await _party_resolution_question(organization_id="org-1", execution_plan=plan_cash_intent) is None

    plan_purchase_cash = SimpleNamespace(
        intent="record_purchase",
        extracted_entities={"supplier_name": "Shabbir Furnitures", "payment_method": "CASH"},
        impact_map={},
    )
    assert await _party_resolution_question(organization_id="org-1", execution_plan=plan_purchase_cash) is None


def test_parse_usage_intent_question_emits_asset_vs_inventory_choices():
    """Bug 4a regression: office-use vs resale single question emits clickable KIND_CHOICE options."""
    from app.questionnaire import KIND_CHOICE, parse_model_question_text

    q_text = (
        "Please confirm one thing: Are the two tables for the business's own use "
        "(office furniture — to be capitalised as a fixed asset), or are they stock held for resale (inventory)?"
    )
    parsed = parse_model_question_text(q_text, intent="record_cash_purchase")
    assert parsed is not None
    assert len(parsed.questions) == 1
    assert parsed.questions[0].field == "transaction_nature"
    assert parsed.questions[0].kind == KIND_CHOICE
    values = [opt[0] for opt in parsed.questions[0].options]
    assert values == ["FIXED_ASSET", "INVENTORY"]


def test_transactional_clarification_question_not_wiped_after_coa_lookup():
    """Bug 4b regression: write intent with read-only lookups + >150 char usage question is NOT suppressed."""
    from types import SimpleNamespace
    from app.agent import _should_suppress_model_question, _usable_question
    from app.questionnaire import parse_model_question_text

    llm_question = (
        "I checked your Chart of Accounts and found Office Furniture and Inventory accounts. "
        "Please confirm one thing before I record this cash purchase: Are the two tables for the business's "
        "own use (office furniture — to be capitalised as a fixed asset), or are they stock held for resale (inventory)?"
    )
    plan_write = SimpleNamespace(intent="record_cash_purchase", missing_fields=[])
    read_tool_ok = [SimpleNamespace(success=True, tool_name="get_chart_of_accounts")]

    assert _should_suppress_model_question(
        "purchased two tables from shabbir furnitures today on cash",
        plan_write,
        llm_question,
        read_tool_ok,
    ) is False

    q = _usable_question(llm_question)
    assert q is not None
    parsed = parse_model_question_text(q, intent="record_cash_purchase")
    assert parsed is not None
    assert [opt[0] for opt in parsed.questions[0].options] == ["FIXED_ASSET", "INVENTORY"]

    # Meanwhile an analytical/read-only inquiry that answered with a table still suppresses trailing chat suggestions
    plan_read = SimpleNamespace(intent="get_cash_accounts", missing_fields=[])
    assert _should_suppress_model_question(
        "What is our current cash and bank balance?",
        plan_read,
        "Here are your current cash and bank balances:\n| Account | Balance |\n| Cash | 0.00 |\nWould you like a breakdown?",
        read_tool_ok,
    ) is True


@pytest.mark.asyncio
async def test_validate_and_post_journal_idempotent_when_already_posted(monkeypatch):
    """validate_journal & post_journal succeed idempotently when entry was already auto-posted."""
    import uuid
    from app.tools import _validate_journal, _post_journal

    org_id = uuid.uuid4()
    entry_id = uuid.uuid4()

    async def fake_validate(*, entry_id):
        raise RuntimeError("Error P0001:\nMessage: Only DRAFT entries can be validated, entry is POSTED")

    async def fake_post(*, entry_id):
        raise RuntimeError("Error P0001:\nMessage: Journal entry JV-000002 cannot be posted from status POSTED")

    async def fake_get_entry(oid, *, entry_id):
        return {"id": str(entry_id), "status": "POSTED", "journal_number": "JV-000002"}

    monkeypatch.setattr("app.tools.accounting_service.validate_journal", fake_validate)
    monkeypatch.setattr("app.tools.accounting_service.post_journal", fake_post)
    monkeypatch.setattr("app.tools.accounting_service.get_entry", fake_get_entry)

    v_res = await _validate_journal(org_id, entry_id=str(entry_id))
    assert v_res.success is True
    assert v_res.data["already_validated"] is True
    assert v_res.data["already_posted"] is True

    p_res = await _post_journal(org_id, entry_id=str(entry_id))
    assert p_res.success is True
    assert p_res.data["already_posted"] is True


def test_normalize_error_extracts_postgrest_p0001_message():
    """Error P0001 multi-line PostgREST messages classify as CONSTRAINT_VIOLATION with exact reason."""
    from app.error_normalizer import CONSTRAINT_VIOLATION, normalize_error

    raw = "Error P0001:\nMessage: Journal entry JV-000002 cannot be posted from status POSTED"
    norm = normalize_error(raw, operation="post_journal")
    assert norm["category"] == CONSTRAINT_VIOLATION
    assert norm["recoverable"] is True
    assert norm["requires_user_input"] is False
    assert "cannot be posted from status POSTED" in norm["reason"]


@pytest.mark.asyncio
async def test_create_expense_links_journal_entry_and_marks_paid(monkeypatch):
    """_create_expense links journal_entry_id and marks status=PAID when journal posts."""
    import uuid
    from app.tools import _create_expense

    org_id = uuid.uuid4()
    exp_id = uuid.uuid4()
    entry_id = uuid.uuid4()
    linked_calls = []

    async def fake_create_exp(**kw):
        return {"id": str(exp_id), "total": 15000.0, "expense_date": "2026-11-12", "description": "Office rent", "status": "DRAFT"}

    async def fake_auto_journal(**kw):
        return {"journal_entry": {"entry": {"id": str(entry_id), "journal_number": "JV-000003"}}}

    async def fake_ok(*args, **kwargs):
        return {"success": True}

    async def fake_link(*, expense_id, journal_entry_id, status=None):
        linked_calls.append((expense_id, journal_entry_id, status))
        return {"id": str(expense_id), "journal_entry_id": str(journal_entry_id), "status": status}

    monkeypatch.setattr("app.tools.expense_service.create_expense", fake_create_exp)
    monkeypatch.setattr("app.tools.auto_journal", fake_auto_journal)
    monkeypatch.setattr("app.tools.accounting_service.validate_journal", fake_ok)
    monkeypatch.setattr("app.tools.accounting_service.post_journal", fake_ok)
    monkeypatch.setattr("app.repositories.expense_repository.link_journal_to_expense", fake_link)

    res = await _create_expense(org_id, description="Office rent", subtotal=15000.0, total=15000.0, payment_mode="BANK_TRANSFER")
    assert res.success is True
    assert res.data["journal_posted"] is True
    assert res.data["journal_entry_id"] == str(entry_id)
    assert res.data["status"] == "PAID"
    assert linked_calls == [(exp_id, entry_id, "PAID")]
