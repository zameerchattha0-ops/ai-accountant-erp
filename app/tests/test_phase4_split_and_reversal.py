"""Tests for Phase 4: Multi-Entity Split Transactions (4A) and One-Click Conversational Undo/Reversal (4B).

Verifies:
1. Multi-entity split transaction decomposition and intent progression.
2. Conversational reversal intent synthesis and target voucher resolution.
3. Contra entry progression tracking.
"""

import pytest
from app.conversational_manager import (
    build_intent_progression,
    synthesize_cumulative_dialogue_intent,
)


def test_multi_entity_split_transaction_intent_progression():
    """Verify that composite multi-item entries render distinct split line facts."""
    entities = {
        "amount": 250000.0,
        "payment_method": "BANK",
        "bank_name": "Meezan Bank",
        "line_items": [
            {
                "description": "Office Rent",
                "amount": 150000.0,
                "category": "Rent",
                "nature": "OPEX",
                "ifrs_standard": "IAS 1",
            },
            {
                "description": "Electricity Bill",
                "amount": 30000.0,
                "category": "Utilities",
                "nature": "OPEX",
                "ifrs_standard": "IAS 1",
            },
            {
                "description": "Executive Laptop",
                "amount": 70000.0,
                "category": "Computer Equipment",
                "nature": "CAPEX",
                "ifrs_standard": "IAS 16",
            },
        ],
    }

    progression = build_intent_progression(
        intent="create_compound_journal",
        entities=entities,
        missing_fields=[],
        status="reviewing",
    )

    facts = progression["verified_facts"]
    fact_labels = [f["label"] for f in facts]
    assert "Split Allocation" in fact_labels
    assert "Line 1" in fact_labels
    assert "Line 2" in fact_labels
    assert "Line 3" in fact_labels

    # Check that line 1 reflects Rent and line 3 reflects Laptop
    line1 = next(f for f in facts if f["label"] == "Line 1")
    line3 = next(f for f in facts if f["label"] == "Line 3")
    assert "Office Rent" in line1["value"]
    assert "150,000" in line1["value"]
    assert "Executive Laptop" in line3["value"]
    assert "70,000" in line3["value"]


def test_reversal_intent_progression():
    """Verify that reversal actions display target voucher and contra entry reasoning."""
    entities = {
        "journal_number": "JV-000085",
        "is_reversal": True,
        "reason": "Incorrect payment account",
    }

    progression = build_intent_progression(
        intent="reverse_journal",
        entities=entities,
        missing_fields=[],
        status="reviewing",
    )

    facts = progression["verified_facts"]
    fact_labels = [f["label"] for f in facts]
    assert "Action" in fact_labels
    assert "Target Voucher" in fact_labels

    target_voucher = next(f for f in facts if f["label"] == "Target Voucher")
    assert target_voucher["value"] == "JV-000085"
    assert "nullify JV-000085" in progression["active_reasoning"]


@pytest.mark.asyncio
async def test_cumulative_synthesis_reversal_command():
    """Verify that a user command to reverse an entry binds intent and target voucher."""
    user_reply = "Please reverse journal entry JV-000085"

    result = await synthesize_cumulative_dialogue_intent(
        user_request="prior transaction",
        history=[],
        current_entities={},
        latest_question="What would you like to do next?",
        user_reply=user_reply,
        missing_fields=[],
    )

    entities = result["entities"]
    assert entities.get("is_reversal") is True
    assert entities.get("intent") == "reverse_journal"
    assert entities.get("journal_number") == "JV-000085"


@pytest.mark.asyncio
async def test_cumulative_synthesis_multi_item_split():
    """Verify that composite payment sentences trigger multi-item disaggregation."""
    msg = (
        "Paid 250,000 today: 150,000 for office rent, 30,000 electricity bill, "
        "and bought an executive laptop for 70,000 via Meezan Bank"
    )

    result = await synthesize_cumulative_dialogue_intent(
        user_request=msg,
        history=[],
        current_entities={},
        latest_question="",
        user_reply="",
        missing_fields=[],
    )

    entities = result["entities"]
    line_items = entities.get("line_items")
    assert isinstance(line_items, list)
    assert len(line_items) == 3
    assert entities.get("total_amount") == 250000.0
    assert entities.get("payment_method") in ("BANK", "BANK_TRANSFER")


def test_author_single_focused_question_isolates_laptop_and_suggests_recommendation():
    """Verify that multi-entity split clarification isolates the capital asset and provides the 3-yr recommendation chip."""
    from app.conversational_manager import author_single_focused_question, format_claude_style_progressive_question

    entities = {
        "amount": 250000.0,
        "payment_method": "BANK",
        "bank_name": "Meezan Bank",
        "description": "Office rent / Electricity bill / Executive laptop",
        "line_items": [
            {"description": "Office rent", "amount": 150000.0, "category": "Rent", "nature": "OPEX", "ifrs_standard": "IAS 1"},
            {"description": "Electricity bill", "amount": 30000.0, "category": "Utilities", "nature": "OPEX", "ifrs_standard": "IAS 1"},
            {"description": "Executive laptop", "amount": 70000.0, "category": "Computer Equipment", "nature": "CAPEX", "ifrs_standard": "IAS 16"},
        ],
    }

    q_text, chips, opts = format_claude_style_progressive_question(
        intent="create_compound_journal",
        missing_fields=["useful_life_years", "depreciation_method"],
        entities=entities,
    )

    # 1. Question targets Executive laptop specifically, not the concatenated string
    assert "Executive laptop" in q_text
    assert "Office rent" not in q_text

    # 2. Chips contains the recommended 3-yr straight line option
    assert "Accept 3-Yr Straight Line (Recommended)" in chips
    assert any(o.get("label") == "Accept 3-Yr Straight Line (Recommended)" for o in opts)


def test_expand_standard_schedule_acceptance_with_recommendation_chip():
    """Verify that accepting 'Accept 3-Yr Straight Line (Recommended)' unpacks 3-year straight line schedule."""
    from app.conversational_manager import is_standard_schedule_acceptance, expand_standard_schedule_answers

    user_reply = "Accept 3-Yr Straight Line (Recommended)"
    assert is_standard_schedule_acceptance(user_reply) is True

    entities = {
        "amount": 250000.0,
        "line_items": [
            {"description": "Office rent", "amount": 150000.0, "nature": "OPEX"},
            {"description": "Electricity bill", "amount": 30000.0, "nature": "OPEX"},
            {"description": "Executive laptop", "amount": 70000.0, "nature": "FIXED_ASSET"},
        ],
    }
    expanded = expand_standard_schedule_answers(user_reply, entities)
    assert expanded is not None
    assert expanded["useful_life_years"] == 3
    assert expanded["depreciation_method"] == "STRAIGHT_LINE"
    assert expanded["salvage_value"] == 0.0


def test_zero_assumption_rule_omits_useful_life_during_clarification():
    """Verify Zero-Assumption Rule: useful life is NEVER shown as verified while clarifying."""
    from app.conversational_manager import build_intent_progression

    entities = {
        "amount": 250000.0,
        "payment_method": "BANK",
        "bank_name": "Meezan Bank",
        "useful_life_years": 3,  # Pre-existing in entities from prior default
        "line_items": [
            {"description": "Office rent", "amount": 150000.0, "nature": "OPEX", "ifrs_standard": "IAS 1"},
            {"description": "Electricity bill", "amount": 30000.0, "nature": "OPEX", "ifrs_standard": "IAS 1"},
            {"description": "Executive laptop", "amount": 70000.0, "nature": "FIXED_ASSET", "ifrs_standard": "IAS 16"},
        ],
    }

    progression = build_intent_progression(
        intent="create_compound_journal",
        entities=entities,
        missing_fields=["useful_life_years", "depreciation_method"],
        status="clarifying",
        active_question="For IT equipment like Executive laptop, standard policy recommends 3-year useful life. Apply?",
    )

    facts = progression["verified_facts"]
    fact_labels = [f["label"] for f in facts]

    # Classification must be Multi-Entity Split (Opex + Capex)
    class_fact = next(f for f in facts if f["label"] == "Classification")
    assert class_fact["value"] == "Multi-Entity Split (Opex + Capex)"

    # Useful Life must NOT be in verified facts while clarifying!
    assert "Useful Life" not in fact_labels


def test_living_draft_compound_split_voucher_preview():
    """Verify Living Draft creates a 4-line double-entry preview for multi-entity split."""
    from app.living_draft import build_living_draft

    entities = {
        "amount": 250000.0,
        "payment_method": "BANK_TRANSFER",
        "bank_name": "Meezan Bank",
        "line_items": [
            {"description": "Office rent", "amount": 150000.0, "account_code": "6210", "account_name": "Rent"},
            {"description": "Electricity bill", "amount": 30000.0, "account_code": "6220", "account_name": "Utilities"},
            {"description": "Executive laptop", "amount": 70000.0, "account_code": "1500", "account_name": "Computer Equipment"},
        ],
    }

    draft = build_living_draft(
        intent="create_compound_journal",
        entities=entities,
        missing_fields=[],
        nature="COMPOUND",
    )

    assert "Compound Split" in draft.document_type
    assert len(draft.voucher_preview) == 4

    debits = [ln for ln in draft.voucher_preview if ln.debit > 0]
    credits = [ln for ln in draft.voucher_preview if ln.credit > 0]

    assert len(debits) == 3
    assert len(credits) == 1

    assert debits[0].debit == 150000.0
    assert "Rent" in debits[0].account_name
    assert debits[1].debit == 30000.0
    assert "Utilities" in debits[1].account_name
    assert debits[2].debit == 70000.0
    assert "Computer Equipment" in debits[2].account_name

    assert credits[0].credit == 250000.0
    assert "Meezan Bank" in credits[0].account_name
    assert sum(d.debit for d in debits) == sum(c.credit for c in credits)


def test_build_compound_journal_from_unit_price_only_items():
    """Verify unit_price-only line_items (from STRUCTURED_EXTRACTION) compute exact debits & ISO date."""
    import re
    from app.multi_item_disaggregator import build_compound_journal_from_entities

    entities = {
        "amount": 250000.0,
        "payment_method": "BANK",
        "bank_name": "Meezan Bank",
        "transaction_date": "today",
        "line_items": [
            {"description": "Office rent", "quantity": 1.0, "unit_price": 150000.0},
            {"description": "Electricity bill", "quantity": 1.0, "unit_price": 30000.0},
            {"description": "Executive laptop", "quantity": 1.0, "unit_price": 70000.0},
        ],
    }

    payload = build_compound_journal_from_entities(entities)
    assert payload["balanced"] is True
    assert payload["total_debit"] == 250000.0
    assert payload["total_credit"] == 250000.0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["transaction_date"] or "")
    debits = [l for l in payload["lines"] if l["debit"] > 0]
    credits = [l for l in payload["lines"] if l["credit"] > 0]
    assert [d["debit"] for d in debits] == [150000.0, 30000.0, 70000.0]
    assert credits[0]["credit"] == 250000.0


@pytest.mark.asyncio
async def test_record_compound_journal_resolves_semantic_coa_conflict():
    """Verify record_compound_journal avoids cross-org code collisions (1520 Vehicle vs Computer)."""
    import uuid
    from unittest.mock import AsyncMock, patch
    from app.accounting_engine import record_compound_journal

    org_id = uuid.uuid4()
    entry_id = uuid.uuid4()
    acc_rent = {"id": uuid.uuid4(), "code": "6151", "name": "Rent Expense", "account_type": "EXPENSE", "is_active": True}
    acc_util = {"id": uuid.uuid4(), "code": "6140", "name": "Utilities", "account_type": "EXPENSE", "is_active": True}
    acc_comp = {"id": uuid.uuid4(), "code": "1500", "name": "Computer Equipment", "account_type": "ASSET", "is_active": True}
    acc_veh = {"id": uuid.uuid4(), "code": "1520", "name": "Vehicle - Car", "account_type": "ASSET", "is_active": True}
    acc_bank = {"id": uuid.uuid4(), "code": "1010", "name": "Bank", "account_type": "ASSET", "is_active": True}

    by_code = {"1520": acc_veh, "1010": acc_bank, "1500": acc_comp, "6151": acc_rent, "6140": acc_util}
    by_name = {"Rent": acc_rent, "Utilities": acc_util, "Computer & IT Equipment": acc_comp}

    async def fake_by_code(_org, *, code):
        return by_code.get(code)

    async def fake_resolve(_org, *, account_name=None, **_kw):
        return by_name.get(account_name)

    captured_lines = []

    async def fake_prepare(**kw):
        captured_lines.extend(kw["lines"])
        assert kw["transaction_date"] != "today"
        return {"entry": {"id": str(entry_id), "journal_number": "JV-TEST-01"}}

    lines = [
        {"account_code": "6210", "account_name": "Rent", "debit": 150000.0, "credit": 0.0, "description": "Office rent"},
        {"account_code": "6220", "account_name": "Utilities", "debit": 30000.0, "credit": 0.0, "description": "Electricity bill"},
        {"account_code": "1520", "account_name": "Computer & IT Equipment", "debit": 70000.0, "credit": 0.0, "description": "Executive laptop"},
        {"account_code": "1010", "account_name": "Meezan Bank", "debit": 0.0, "credit": 250000.0, "description": "Settlement"},
    ]

    with patch("app.accounting_engine._grouping_account_ids", AsyncMock(return_value=set())), \
         patch("app.repositories.account_repository.get_account_by_code", side_effect=fake_by_code), \
         patch("app.services.accounting_service.resolve_account", side_effect=fake_resolve), \
         patch("app.services.accounting_service.prepare_journal", side_effect=fake_prepare), \
         patch("app.services.accounting_service.validate_journal", AsyncMock(return_value={"valid": True})), \
         patch("app.services.accounting_service.post_journal", AsyncMock(return_value={"status": "POSTED"})):
        res = await record_compound_journal(
            organization_id=org_id,
            transaction_date="today",
            description="Split compound",
            lines=lines,
        )

    assert res["success"] is True
    assert captured_lines[0]["account_id"] == str(acc_rent["id"])
    assert captured_lines[1]["account_id"] == str(acc_util["id"])
    # Crucial: must pick Computer Equipment, NEVER Vehicle - Car!
    assert captured_lines[2]["account_id"] == str(acc_comp["id"])
    assert captured_lines[3]["account_id"] == str(acc_bank["id"])


@pytest.mark.asyncio
async def test_register_asset_from_split_line_multi_ppe_and_today_date():
    """Verify register_asset_from_split_line passes explicit_id and selects Computer Equipment at 70k/3yr."""
    import re
    import uuid
    from unittest.mock import AsyncMock, patch
    from app.services.fixed_asset_service import register_asset_from_split_line

    org_id = uuid.uuid4()
    entry_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    comp_id = uuid.uuid4()

    coa = [
        {"id": str(comp_id), "code": "1500", "name": "Computer Equipment", "account_type": "ASSET", "is_active": True},
        {"id": str(uuid.uuid4()), "code": "1502", "name": "Furniture & Fixtures", "account_type": "ASSET", "is_active": True},
        {"id": str(uuid.uuid4()), "code": "1520", "name": "Vehicle - Car", "account_type": "ASSET", "is_active": True},
    ]

    created_payload = {}

    async def fake_create_asset(**kw):
        created_payload.update(kw)
        return {"id": str(asset_id), "name": kw["name"], "purchase_cost": kw["purchase_cost"]}

    with patch("app.repositories.account_repository.get_chart_of_accounts", AsyncMock(return_value=coa)), \
         patch("app.repositories.fixed_asset_repository.create_asset", side_effect=fake_create_asset), \
         patch("app.repositories.fixed_asset_repository.update_asset_by_id", AsyncMock(return_value={})), \
         patch("app.repositories.fixed_asset_repository.record_asset_transaction", AsyncMock(return_value={})), \
         patch("app.repositories.fixed_asset_repository.record_depreciation_schedule", AsyncMock(return_value={})):
        res = await register_asset_from_split_line(
            organization_id=org_id,
            name="Executive laptop",
            purchase_cost=70000.0,
            transaction_date="today",
            journal_entry_id=entry_id,
            useful_life_years=3,
            depreciation_method="STRAIGHT_LINE",
            account_code="1520",
            account_name="Computer & IT Equipment",
        )

    assert res["asset_registered"] is True
    assert created_payload["purchase_cost"] == 70000.0
    assert created_payload["useful_life_years"] == 3
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", created_payload["purchase_date"])
    assert str(created_payload["gl_asset_account_id"]) == str(comp_id)


@pytest.mark.asyncio
async def test_parse_packed_reply_accept_3yr_chip_never_overwrites_with_5():
    """Verify 'Accept 3-Yr Straight Line (Recommended)' preserves useful_life_years == '3'."""
    from app.answer_parsing import parse_packed_reply_to_endpoints

    parsed = await parse_packed_reply_to_endpoints(
        question_text="For IT equipment like Executive laptop, apply 3-year straight-line?",
        user_reply="Accept 3-Yr Straight Line (Recommended)",
        allowed_endpoints=["useful_life_years", "depreciation_method"],
    )
    assert parsed is not None
    assert parsed.get("useful_life_years") == "3"
    assert parsed.get("depreciation_method") == "STRAIGHT_LINE"


def test_living_draft_depreciation_schedule_uses_split_asset_cost_not_total():
    """Verify compound Living Draft depreciation_schedule uses 70k laptop cost, not 250k total."""
    from app.living_draft import build_living_draft

    entities = {
        "amount": 250000.0,
        "payment_method": "BANK",
        "bank_name": "Meezan Bank",
        "useful_life_years": 3,
        "depreciation_method": "STRAIGHT_LINE",
        "line_items": [
            {"description": "Office rent", "amount": 150000.0, "nature": "OPERATING_EXPENSE", "account_code": "6151", "account_name": "Rent Expense"},
            {"description": "Electricity bill", "amount": 30000.0, "nature": "OPERATING_EXPENSE", "account_code": "6140", "account_name": "Utilities"},
            {"description": "Executive laptop", "amount": 70000.0, "nature": "FIXED_ASSET", "is_fixed_asset": True, "account_code": "1500", "account_name": "Computer Equipment", "ifrs_standard": "IAS 16"},
        ],
    }

    draft = build_living_draft(
        intent="create_compound_journal",
        entities=entities,
        missing_fields=[],
        nature="COMPOUND",
    )
    assert draft.depreciation_schedule is not None
    assert draft.depreciation_schedule.useful_life_years == 3
    assert draft.depreciation_schedule.cost == 70000.0
    assert draft.depreciation_schedule.annual_depreciation == round(70000.0 / 3, 2)


def test_collect_account_refs_skips_resolved_uuid_lines():
    """Verify collect_account_refs skips compound lines already resolved by account_id UUID."""
    import uuid
    from app.models.schemas import ToolCall
    from app.account_resolution import collect_account_refs

    tc = ToolCall(
        tool_name="create_compound_journal",
        arguments={
            "lines": [
                {"account_id": str(uuid.uuid4()), "account_code": "6151", "account_name": "Rent Expense", "debit": 150000.0, "credit": 0.0},
                {"account_id": str(uuid.uuid4()), "account_code": "1010", "account_name": "Bank", "debit": 0.0, "credit": 150000.0},
            ]
        },
    )
    assert collect_account_refs([tc]) == []


@pytest.mark.asyncio
async def test_resume_with_clarification_compound_turn2_executes_single_hop_and_registers_70k_3yr(monkeypatch):
    """End-to-end Turn-2 regression: Accept 3-Yr chip -> single-hop 4-line COA split & 70k/3yr asset."""
    import uuid
    import app.agent as agent_mod
    import app.database as db_mod
    import app.tool_router as router_mod
    import app.repositories.account_repository as acct_repo
    import app.services.fixed_asset_service as fa_svc
    from app.models.schemas import ToolResult, ExecutionStatus

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    je_id = uuid.uuid4()

    zameer_coa = [
        {"id": str(uuid.uuid4()), "code": "1010", "name": "Bank", "account_type": "ASSET", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "1020", "name": "Cash", "account_type": "ASSET", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "1500", "name": "Computer Equipment", "account_type": "ASSET", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "1520", "name": "Vehicle - Car", "account_type": "ASSET", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "2140", "name": "Current Portion of Long-Term Loan", "account_type": "LIABILITY", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "6130", "name": "Office Supplies", "account_type": "EXPENSE", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "6140", "name": "Utilities", "account_type": "EXPENSE", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "6151", "name": "Rent Expense", "account_type": "EXPENSE", "is_active": True, "is_group": False},
    ]

    snapshot = {
        "intent": "create_compound_journal",
        "extracted_entities": {
            "amount": 250000.0,
            "payment_method": "BANK",
            "bank_name": "Meezan Bank",
            "transaction_date": "2026-11-26",
            "description": "Office Rent / Electricity Bill / Executive Laptop",
            "transaction_nature": "COMPOUND",
            "line_items": [
                {"description": "Office Rent", "amount": 150000.0, "category": "Rent", "nature": "OPEX", "ifrs_standard": "IAS 1"},
                {"description": "Electricity Bill", "amount": 30000.0, "category": "Utilities", "nature": "OPEX", "ifrs_standard": "IAS 1"},
                {"description": "Executive Laptop", "amount": 70000.0, "category": "Computer Equipment", "nature": "CAPEX", "ifrs_standard": "IAS 16", "is_fixed_asset": True},
            ],
        },
        "missing_fields": ["useful_life_years", "depreciation_method"],
    }

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return {
                "id": str(sess_id),
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "role": "OWNER",
                "status": "AWAITING_CLARIFICATION",
                "user_request": "Paid 250,000 today: 150,000 for office rent, 30,000 electricity bill, and bought an executive laptop for 70,000 via Meezan Bank",
            }
        return None

    async def fake_resolve_and_fetch_clarifications(*, session_id, user_response):
        history = [
            {
                "question": "For Executive Laptop (Rs. 70,000), confirm useful life and depreciation method.",
                "answer": user_response,
                "required_information": ["useful_life_years", "depreciation_method"],
            }
        ]
        return None, history, snapshot

    async def fake_noop(*args, **kwargs):
        return None

    async def fake_get_coa(organization_id, *args, **kwargs):
        return zameer_coa

    async def fake_get_by_code(organization_id, *, code=None, **kwargs):
        for acc in zameer_coa:
            if acc["code"] == str(code):
                return acc
        return None

    async def fake_search_accounts(organization_id, *, query="", **kwargs):
        q = str(query or "").lower()
        return [
            acc for acc in zameer_coa
            if q in acc["name"].lower() or q in acc["code"].lower()
        ]

    async def fake_get_grouping_ids(organization_id):
        return set()

    captured_tool_calls = []
    async def fake_route_tool_call(tool_call, **kwargs):
        captured_tool_calls.append(tool_call)
        return ToolResult(
            success=True,
            tool_name=tool_call.tool_name,
            data={
                "journal_entry_id": str(je_id),
                "entry_number": "JV-TEST-0103",
                "total_debit": 250000.0,
                "total_credit": 250000.0,
                "status": "POSTED",
            },
        )

    captured_assets = []
    async def fake_register_asset_from_split_line(**kwargs):
        captured_assets.append(kwargs)
        return {
            "id": str(uuid.uuid4()),
            "asset_number": "AST-TEST-0013",
            "name": kwargs.get("name"),
            "purchase_cost": kwargs.get("purchase_cost"),
            "useful_life_years": kwargs.get("useful_life_years"),
            "depreciation_method": kwargs.get("depreciation_method"),
        }

    import app.ai_orchestrator as ai_orch

    async def fake_generate_text_light(*args, **kwargs):
        return None

    async def forbid_execute(*args, **kwargs):
        raise AssertionError("resume_with_clarification fell back to execute() instead of single-hop")

    monkeypatch.setattr(ai_orch.AIOrchestrator, "generate_text_light", fake_generate_text_light)
    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "_update_status", fake_noop)
    monkeypatch.setattr(agent_mod, "_log_step", fake_noop)
    monkeypatch.setattr(agent_mod, "execute", forbid_execute)
    monkeypatch.setattr(db_mod, "resolve_and_fetch_clarifications", fake_resolve_and_fetch_clarifications)
    monkeypatch.setattr(acct_repo, "get_chart_of_accounts", fake_get_coa)
    monkeypatch.setattr(acct_repo, "get_account_by_code", fake_get_by_code)
    monkeypatch.setattr(acct_repo, "search_accounts", fake_search_accounts)
    monkeypatch.setattr(acct_repo, "get_grouping_account_ids", fake_get_grouping_ids)
    monkeypatch.setattr(router_mod, "route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(fa_svc, "register_asset_from_split_line", fake_register_asset_from_split_line)

    resp = await agent_mod.resume_with_clarification(
        session_id=sess_id,
        user_answer="Accept 3-Yr Straight Line (Recommended)",
        user_id=user_id,
        organization_id=org_id,
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(captured_tool_calls) == 1
    tc = captured_tool_calls[0]
    assert tc.tool_name == "create_compound_journal"
    lines = tc.arguments["lines"]
    assert len(lines) == 4
    codes = {ln["account_code"] for ln in lines}
    assert codes == {"6151", "6140", "1500", "1010"}
    assert "1520" not in codes
    assert sum(ln["debit"] for ln in lines) == pytest.approx(250000.0)
    assert sum(ln["credit"] for ln in lines) == pytest.approx(250000.0)

    assert len(captured_assets) == 1
    assert captured_assets[0]["name"] == "Executive Laptop"
    assert float(captured_assets[0]["purchase_cost"]) == pytest.approx(70000.0)
    assert int(captured_assets[0]["useful_life_years"]) == 3

    assert resp.living_draft is not None
    dep = resp.living_draft.get("depreciation_schedule") or {}
    assert dep.get("useful_life_years") == 3
    assert float(dep.get("cost") or 0.0) == pytest.approx(70000.0)


@pytest.mark.asyncio
async def test_rent_substring_never_resolves_to_current_liability_2140(monkeypatch):
    """Ensure 'Rent' never matches 'Current Portion of Long-Term Loan' (2140) and slider uses 70k."""
    import uuid
    import app.repositories.account_repository as acct_repo
    from app.services import accounting_service
    from app.accounting_engine import _account_category_tag, _is_semantic_account_mismatch
    from app.living_draft import build_living_draft
    from app.interactive_artifacts import _build_depreciation_slider

    org_id = uuid.uuid4()
    coa = [
        {"id": str(uuid.uuid4()), "code": "2140", "name": "Current Portion of Long-Term Loan", "account_type": "LIABILITY", "is_active": True, "is_group": False},
        {"id": str(uuid.uuid4()), "code": "6151", "name": "Rent Expense", "account_type": "EXPENSE", "is_active": True, "is_group": False},
    ]

    async def fake_search_accounts(organization_id, *, query="", limit=25, **kwargs):
        q = str(query or "").lower()
        return [a for a in coa if q in a["name"].lower() or q in a["code"].lower()][:limit]

    monkeypatch.setattr(acct_repo, "search_accounts", fake_search_accounts)

    assert _account_category_tag("Current Portion of Long-Term Loan") is None
    assert _is_semantic_account_mismatch("Current Portion of Long-Term Loan", "Rent Expense", "Office Rent") is False
    resolved = await accounting_service.resolve_account(org_id, account_name="Rent")
    assert resolved is not None
    assert resolved["code"] == "6151"
    assert resolved["account_type"] == "EXPENSE"

    ld = build_living_draft(
        intent="create_compound_journal",
        entities={
            "amount": 250000.0,
            "payment_method": "BANK",
            "bank_name": "Meezan Bank",
            "useful_life_years": 3,
            "depreciation_method": "STRAIGHT_LINE",
            "line_items": [
                {"description": "Office Rent", "amount": 150000.0, "category": "Rent", "nature": "OPEX"},
                {"description": "Electricity Bill", "amount": 30000.0, "category": "Utilities", "nature": "OPEX"},
                {"description": "Executive Laptop", "amount": 70000.0, "category": "Computer Equipment", "nature": "CAPEX", "is_fixed_asset": True},
            ],
        },
        missing_fields=[],
        nature="COMPOUND",
        session_phase="COMPLETED",
    )
    slider_ctrl = _build_depreciation_slider(ld)
    assert slider_ctrl is not None and slider_ctrl.slider is not None
    assert slider_ctrl.slider.live_calculated_values[1]["annual"] == pytest.approx(70000.0)
    assert slider_ctrl.slider.live_calculated_values[3]["annual"] == pytest.approx(23333.33)


def test_agent_contains_no_hardcoded_test_laptop_question_or_setattr_override():
    """Verify agent.py has no hardcoded test-case strings or secret setattr intent overrides."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "agent.py").read_text(encoding="utf-8")
    assert "For IT equipment like Executive Laptop (Rs. 70,000)" not in src
    assert 'setattr(execution_plan, "intent"' not in src


def test_evaluate_goal_finalisation_authenticates_split_and_asset_subgoals():
    """Goal finalisation requires BOTH compound journal AND split fixed asset registration."""
    from app.reasoning import evaluate_goal_finalisation

    entities = {
        "line_items": [
            {"description": "Office Rent", "amount": 150000.0, "nature": "OPEX"},
            {"description": "Server Rack", "amount": 120000.0, "nature": "FIXED_ASSET", "is_fixed_asset": True},
        ]
    }
    impact = [
        {"account": "6151 - Rent Expense", "debit": 150000.0, "credit": 0.0},
        {"account": "1500 - Computer Equipment", "debit": 120000.0, "credit": 0.0},
        {"account": "1010 - Bank", "debit": 0.0, "credit": 270000.0},
    ]

    incomplete = evaluate_goal_finalisation(
        intent="create_compound_journal",
        entities=entities,
        successful_tools=["create_compound_journal"],
        affected_entities=[{"type": "journal_entry", "id": "je-1"}],
        accounting_impact=impact,
        capitalized_assets_count=0,
    )
    assert incomplete["goal_achieved"] is False
    assert "split_fixed_asset_registered" in incomplete["missing_subgoals"]

    complete = evaluate_goal_finalisation(
        intent="create_compound_journal",
        entities=entities,
        successful_tools=["create_compound_journal"],
        affected_entities=[{"type": "journal_entry", "id": "je-1"}],
        accounting_impact=impact,
        capitalized_assets_count=1,
    )
    assert complete["goal_achieved"] is True
    assert "compound_journal_posted" in complete["verified_subgoals"]
    assert "split_fixed_asset_registered" in complete["verified_subgoals"]


@pytest.mark.asyncio
async def test_resume_with_clarification_supports_flexible_llm_diversion_and_cancel(monkeypatch):
    """LLM can freely divert mid-clarification or cancel honestly without rigid single-hop trapping."""
    import uuid
    import json
    import app.agent as agent_mod
    import app.database as db_mod
    import app.ai_orchestrator as ai_orch
    from app.models.schemas import AgentResponse, ExecutionStatus

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    sess_id = uuid.uuid4()

    snapshot = {
        "intent": "record_expense",
        "extracted_entities": {"amount": 80000.0, "description": "Office Desks"},
        "missing_fields": ["payment_method"],
    }

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return {
                "id": str(sess_id),
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "role": "OWNER",
                "status": "AWAITING_CLARIFICATION",
                "user_request": "Bought 2 office desks for 80,000",
            }
        return None

    async def fake_resolve_and_fetch(*, session_id, user_response):
        return None, [{"question": "How did you pay?", "answer": user_response, "required_information": ["payment_method"]}], snapshot

    async def fake_noop(*args, **kwargs):
        return None

    execute_calls = []

    async def fake_execute(**kwargs):
        execute_calls.append(kwargs)
        return AgentResponse(
            status=ExecutionStatus.AWAITING_CONFIRMATION,
            execution_id=sess_id,
            action="create_purchase_order",
            summary="Diverted to Purchase Order flow.",
            confirmation_required=True,
        )

    async def fake_divert_llm(*args, **kwargs):
        return json.dumps({
            "next_action": "DIVERT",
            "resolved_intent": "create_purchase_order",
            "diversion_reason": "User switched from direct expense to creating a purchase order.",
            "updated_entities": {"supplier_name": "Metro Furniture"},
            "reasoning": "Diverting to purchase order workflow per user instruction.",
        })

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "_update_status", fake_noop)
    monkeypatch.setattr(agent_mod, "_log_step", fake_noop)
    monkeypatch.setattr(agent_mod, "execute", fake_execute)
    monkeypatch.setattr(db_mod, "resolve_and_fetch_clarifications", fake_resolve_and_fetch)
    monkeypatch.setattr(ai_orch.AIOrchestrator, "generate_text_light", fake_divert_llm)

    resp_divert = await agent_mod.resume_with_clarification(
        session_id=sess_id,
        user_answer="Actually make it a purchase order to Metro Furniture instead",
        user_id=user_id,
        organization_id=org_id,
    )
    assert len(execute_calls) == 1
    assert resp_divert.action == "create_purchase_order"

    # Cancellation returns ExecutionStatus.CANCELLED without calling execute()
    resp_cancel = await agent_mod.resume_with_clarification(
        session_id=sess_id,
        user_answer="Cancel this, do not record",
        user_id=user_id,
        organization_id=org_id,
    )
    assert resp_cancel.status == ExecutionStatus.CANCELLED
    assert len(execute_calls) == 1







