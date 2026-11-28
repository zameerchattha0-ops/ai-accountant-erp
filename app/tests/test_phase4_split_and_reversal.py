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


@pytest.mark.asyncio
async def test_compound_journal_tool_args_strip_summary_fields_and_pass_contract(monkeypatch):
    """_deterministic_mutation_calls must omit total_debit/total_credit/balanced per create_compound_journal contract."""
    import uuid
    import app.agent as agent_mod
    from app.planner import ExecutionPlan
    from app.tools import tool_contracts
    import app.multi_item_disaggregator as disagg_mod

    async def fake_resolve_coa(org_id, lines):
        return lines

    monkeypatch.setattr(disagg_mod, "resolve_compound_lines_to_org_coa", fake_resolve_coa)

    plan = ExecutionPlan(
        intent="create_compound_journal",
        extracted_entities={
            "amount": 95000.0,
            "payment_method": "BANK",
            "bank_name": "Meezan",
            "transaction_date": "2026-11-28",
            "line_items": [
                {"description": "internet bill", "amount": 25000.0, "nature": "OPERATING_EXPENSE", "account_code": "6140", "account_name": "Utilities"},
                {"description": "2 office desks", "amount": 70000.0, "nature": "FIXED_ASSET", "is_fixed_asset": True, "account_code": "1502", "account_name": "Furniture & Fixtures"},
            ],
        },
        missing_fields=[],
    )
    calls = await agent_mod._deterministic_mutation_calls(
        organization_id=uuid.uuid4(),
        execution_plan=plan,
        classification=None,
    )
    assert len(calls) == 1
    tc = calls[0]
    assert tc.tool_name == "create_compound_journal"
    accepted = set(tool_contracts()["create_compound_journal"]["accepted"])
    assert set(tc.arguments.keys()) <= accepted
    assert "total_debit" not in tc.arguments
    assert "total_credit" not in tc.arguments
    assert "balanced" not in tc.arguments


@pytest.mark.asyncio
async def test_resolve_compound_line_account_skips_group_6150_for_utilities_internet(monkeypatch):
    """When code 6150 points to a grouping heading (is_group=True), fall through to leaf 6140 Utilities."""
    import uuid
    import app.accounting_engine as eng
    from app.repositories import account_repository as a_repo
    from app.services import accounting_service as acct_svc

    org_id = uuid.uuid4()
    group_id = uuid.uuid4()
    leaf_utilities_id = uuid.uuid4()

    group_6150 = {"id": group_id, "code": "6150", "name": "Operating Expenses", "account_type": "EXPENSE", "is_active": True, "is_group": True}
    leaf_6140 = {"id": leaf_utilities_id, "code": "6140", "name": "Utilities", "account_type": "EXPENSE", "is_active": True, "is_group": False}

    async def fake_by_code(oid, code=None):
        return group_6150 if code == "6150" else None

    async def fake_resolve(oid, account_name=None, required_type=None):
        if account_name and "utilit" in account_name.lower():
            return leaf_6140
        return None

    async def fake_coa(oid, is_active=True, limit=500):
        return [group_6150, leaf_6140]

    monkeypatch.setattr(a_repo, "get_account_by_code", fake_by_code)
    monkeypatch.setattr(acct_svc, "resolve_account", fake_resolve)
    monkeypatch.setattr(a_repo, "get_chart_of_accounts", fake_coa)

    resolved = await eng._resolve_compound_line_account(
        org_id,
        raw_acc_id=None,
        code="6150",
        name="Utilities",
        line_desc="internet bill",
        group_ids={group_id},
        expected_type="EXPENSE",
    )
    assert resolved is not None
    assert resolved["code"] == "6140"
    assert resolved["id"] == leaf_utilities_id


@pytest.mark.asyncio
async def test_split_fixed_asset_dual_registration_uses_furniture_5yr_and_satisfies_goal(monkeypatch):
    """Compound fixed-asset split for furniture registers asset at 5-Yr Straight Line and passes goal finalisation."""
    import uuid
    import app.agent as agent_mod
    import app.services.fixed_asset_service as fa_svc
    from app.reasoning import evaluate_goal_finalisation
    from app.conversational_manager import format_claude_style_progressive_question

    q_text, chips, _ = format_claude_style_progressive_question(
        intent="create_compound_journal",
        missing_fields=["useful_life_years", "depreciation_method"],
        entities={
            "line_items": [
                {"description": "internet bill", "amount": 25000.0, "nature": "OPERATING_EXPENSE"},
                {"description": "2 office desks", "amount": 70000.0, "nature": "FIXED_ASSET", "is_fixed_asset": True},
            ]
        },
    )
    assert "Accept 5-Yr Straight Line (Recommended)" in chips
    assert "Accept 3-Yr Straight Line (Recommended)" not in chips

    captured = []

    async def fake_reg(**kwargs):
        captured.append(kwargs)
        return {"id": uuid.uuid4(), "asset_number": "FA-0042", "name": kwargs["name"]}

    monkeypatch.setattr(fa_svc, "register_asset_from_split_line", fake_reg)

    je_id = uuid.uuid4()
    cap_assets, extra_ents, applied_life, dep_m = await agent_mod._register_compound_split_fixed_assets(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        entities={
            "transaction_date": "2026-11-28",
            "line_items": [
                {"description": "internet bill", "amount": 25000.0, "nature": "OPERATING_EXPENSE", "account_code": "6140"},
                {"description": "2 office desks", "amount": 70000.0, "nature": "FIXED_ASSET", "is_fixed_asset": True, "account_code": "1502"},
            ],
        },
        tool_results=[
            agent_mod.ToolResult(
                tool_name="create_compound_journal",
                success=True,
                data={"journal_entry_id": str(je_id), "entry_number": "JV-2026-0099", "total_debit": 95000.0},
            )
        ],
    )
    assert len(captured) == 1
    assert captured[0]["useful_life_years"] == 5
    assert captured[0]["purchase_cost"] == 70000.0
    assert applied_life == 5
    assert len(cap_assets) == 1
    assert len(extra_ents) == 1 and extra_ents[0].type == "fixed_asset"

    verdict = evaluate_goal_finalisation(
        intent="create_compound_journal",
        entities={
            "line_items": [
                {"description": "internet bill", "amount": 25000.0, "nature": "OPERATING_EXPENSE"},
                {"description": "2 office desks", "amount": 70000.0, "nature": "FIXED_ASSET", "is_fixed_asset": True},
            ]
        },
        successful_tools=["create_compound_journal"],
        affected_entities=[{"type": "journal_entry", "id": str(je_id)}, extra_ents[0].model_dump()],
        accounting_impact=[
            {"account": "6140 - Utilities", "debit": 25000.0, "credit": 0.0},
            {"account": "1502 - Furniture & Fixtures", "debit": 70000.0, "credit": 0.0},
            {"account": "1010 - Bank", "debit": 0.0, "credit": 95000.0},
        ],
        capitalized_assets_count=len(cap_assets),
    )
    assert verdict["goal_achieved"] is True
    assert "split_fixed_asset_registered" in verdict["verified_subgoals"]


@pytest.mark.asyncio
async def test_treatment_review_preserves_compound_journal_lines_without_false_contradiction(monkeypatch):
    """_extract_facts_and_plan keeps GL lines + line_items for create_compound_journal (no false [nature_vs_plan])."""
    import json
    import uuid
    from types import SimpleNamespace
    import app.agent as agent_mod
    from app.config import get_settings
    from app.treatment_review import _extract_facts_and_plan, review_plan_treatment

    lines = [
        {"account_code": "6140", "account_name": "Utilities", "debit": 25000.0, "credit": 0.0, "description": "internet bill"},
        {"account_code": "1502", "account_name": "Furniture & Fixtures", "debit": 70000.0, "credit": 0.0, "description": "2 office desks"},
        {"account_code": "1010", "account_name": "Meezan Bank (Current)", "debit": 0.0, "credit": 95000.0, "description": "Bank settlement"},
    ]
    entities = {
        "amount": 95000.0,
        "payment_method": "BANK",
        "item_description": "2 office desks",
        "transaction_date": "2026-11-28",
        "line_items": [
            {"description": "internet bill", "amount": 25000.0, "nature": "OPERATING_EXPENSE"},
            {"description": "2 office desks", "amount": 70000.0, "nature": "FIXED_ASSET", "is_fixed_asset": True},
        ],
    }
    calls = [
        agent_mod.ToolCall(
            tool_name="create_compound_journal",
            arguments={
                "transaction_date": "2026-11-28",
                "description": "Disaggregated payment: internet bill & 2 office desks",
                "lines": lines,
                "currency_code": "PKR",
            },
        )
    ]

    facts, plan = _extract_facts_and_plan(
        intent="create_compound_journal",
        classification=SimpleNamespace(transaction_nature="OPERATING_EXPENSE", source="llm"),
        entities=entities,
        calls=calls,
    )
    assert facts["transaction_nature"] == "COMPOUND"
    assert "internet bill" in str(facts["item_description"])
    assert "2 office desks" in str(facts["item_description"])
    assert isinstance(facts.get("line_items"), list) and len(facts["line_items"]) == 2
    assert len(plan) == 1
    assert plan[0]["tool"] == "create_compound_journal"
    assert plan[0]["arguments"].get("lines") == lines

    class VerifyLinesClient:
        async def generate_text_light(self, prompt: str) -> str:
            assert '"account_code": "6140"' in prompt
            assert '"account_code": "1502"' in prompt
            assert '"transaction_nature": "COMPOUND"' in prompt
            return json.dumps({"contradictions": [], "missing_material_facts": []})

    monkeypatch.setattr(get_settings(), "treatment_review_enabled", True)
    rev = await review_plan_treatment(
        organization_id=uuid.uuid4(),
        intent="create_compound_journal",
        classification=SimpleNamespace(transaction_nature="OPERATING_EXPENSE", source="llm"),
        entities=entities,
        calls=calls,
        client=VerifyLinesClient(),
    )
    assert rev.blocked is False
    assert rev.ok is True


@pytest.mark.asyncio
async def test_compound_split_preserves_quantity_and_plurality_for_2_office_desks():
    """'70,000 for 2 office desks' preserves '2 Office Desks' in disaggregator, journal, draft, and asset."""
    from app.living_draft import build_living_draft
    from app.multi_item_disaggregator import disaggregate_conversational_items, format_item_with_quantity

    assert format_item_with_quantity("Office Desk", 2.0) == "2 Office Desks"
    assert format_item_with_quantity("Executive Laptop", 1.0) == "Executive Laptop"
    assert format_item_with_quantity("workstation tables", 5.0) == "5 workstation tables"

    msg = "Paid 95,000 today: 25,000 for internet bill and 70,000 for 2 office desks via Meezan Bank"
    res = await disaggregate_conversational_items(msg, {})
    assert len(res.line_items) == 2
    assert res.fixed_asset_registrations_needed
    assert res.fixed_asset_registrations_needed[0]["asset_name"].lower().startswith("2 ")

    journal = res.to_compound_journal(transaction_date="2026-11-28")
    descs = [ln.get("description", "").lower() for ln in journal["lines"]]
    assert any("2 " in d and "desk" in d for d in descs)

    ld = build_living_draft(
        intent="create_compound_journal",
        entities={
            "amount": 95000.0,
            "payment_method": "BANK",
            "line_items": [
                {"description": "Internet Bill", "amount": 25000.0, "quantity": 1.0, "nature": "OPERATING_EXPENSE"},
                {"description": "Office Desk", "amount": 70000.0, "quantity": 2.0, "nature": "FIXED_ASSET"},
            ],
        },
        missing_fields=[],
        nature="COMPOUND",
    )
    assert any("2 Office Desks" in (vp.description or "") for vp in ld.voucher_preview)


@pytest.mark.asyncio
async def test_reverse_journal_synchronizes_linked_undepr_fixed_assets(monkeypatch):
    """Reversing a purchase journal retires linked 0-depreciation ACTIVE assets (WRITTEN_OFF) without touching depreciated ones."""
    import uuid
    import app.services.accounting_service as acct_svc
    import app.repositories.journal_repository as j_repo
    import app.repositories.fixed_asset_repository as fa_repo
    import app.database as db_mod

    org_id = uuid.uuid4()
    entry_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    undepr_asset_id = uuid.uuid4()
    depr_asset_id = uuid.uuid4()

    async def fake_reverse_rpc(**kwargs):
        return {"success": True, "result": str(rev_id)}

    async def fake_fetch_many(table, filters=None, **kwargs):
        if table == "fixed_assets" and filters and filters.get("purchase_journal_entry_id") == str(entry_id):
            return [
                {
                    "id": str(undepr_asset_id),
                    "organization_id": str(org_id),
                    "name": "2 Office Desks",
                    "description": "Acquired via compound split: 2 Office Desks",
                    "purchase_cost": 70000.0,
                    "accumulated_depreciation": 0.0,
                    "status": "ACTIVE",
                },
                {
                    "id": str(depr_asset_id),
                    "organization_id": str(org_id),
                    "name": "Existing Laptop",
                    "purchase_cost": 100000.0,
                    "accumulated_depreciation": 5000.0,
                    "status": "ACTIVE",
                },
            ]
        return []

    updated = []
    txns = []

    async def fake_update_asset(row_id, *, fields):
        updated.append((row_id, fields))
        return {"id": str(row_id), **fields}

    async def fake_record_txn(**kwargs):
        txns.append(kwargs)
        return {"id": str(uuid.uuid4())}

    monkeypatch.setattr(j_repo, "reverse_journal_entry", fake_reverse_rpc)
    monkeypatch.setattr(db_mod, "fetch_many", fake_fetch_many)
    monkeypatch.setattr(fa_repo, "update_asset_by_id", fake_update_asset)
    monkeypatch.setattr(fa_repo, "record_asset_transaction", fake_record_txn)

    out = await acct_svc.reverse_journal(entry_id=entry_id, reason="Duplicate posting", reversal_date="2026-11-28")
    assert out["success"] is True
    assert len(updated) == 1
    assert updated[0][0] == undepr_asset_id
    assert updated[0][1]["status"] == "WRITTEN_OFF"
    assert "[Purchase Journal Reversed]" in updated[0][1]["description"]
    assert len(txns) == 1
    assert txns[0]["transaction_type"] == "WRITE_OFF"
    assert txns[0]["journal_entry_id"] == rev_id


@pytest.mark.asyncio
async def test_single_hop_runs_treatment_review_gate(monkeypatch):
    """Single-hop clarification execution runs treatment review before mutating."""
    import uuid
    import app.agent as agent_mod
    import app.treatment_review as tr_mod
    from app.models.schemas import ToolCall, ExecutionStatus

    steps = []
    clars = []

    async def fake_log(sid, st, data):
        steps.append((st, data))

    async def fake_clar(**kwargs):
        clars.append(kwargs)
        return kwargs

    async def fake_status(sid, st):
        return None

    async def fake_review(**kwargs):
        return tr_mod.TreatmentReview(
            ran=True,
            ok=False,
            blocked=True,
            question="Contradiction flagged before single-hop execution.",
            flags=[{"kind": "amount_vs_plan", "why": "Test contradiction"}],
            audit={"stage": "treatment_review", "llm": "flagged", "flags": 1},
        )

    monkeypatch.setattr(tr_mod, "review_plan_treatment", fake_review)

    blocked = await agent_mod._single_hop_treatment_review_gate(
        organization_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        intent="create_compound_journal",
        entities={"amount": 95000.0},
        single_hop_call=ToolCall(tool_name="create_compound_journal", arguments={"lines": []}),
        create_clarification_fn=fake_clar,
        update_status_fn=fake_status,
        log_step_fn=fake_log,
    )
    assert blocked is not None
    assert blocked.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert clars and "Contradiction flagged" in clars[0]["question"]
    assert any(st == "TREATMENT_REVIEW" for st, _ in steps)


def test_extracted_agent_submodules_keep_agent_exports_intact():
    """Verify agent.py cleanly re-exports extracted compound and post-execution helpers."""
    import app.agent as agent_mod
    import app.agent_compound as comp_mod
    import app.agent_post_execution as post_mod

    assert agent_mod._register_compound_split_fixed_assets is comp_mod.register_compound_split_fixed_assets
    assert agent_mod._format_compound_journal_summary is comp_mod.format_compound_journal_summary
    assert agent_mod._single_hop_treatment_review_gate is comp_mod.single_hop_treatment_review_gate
    assert agent_mod._document_integrity_violations is post_mod.document_integrity_violations
    assert agent_mod._build_batch_breakdown is post_mod.build_batch_breakdown
    assert agent_mod._execution_failure_summary is post_mod.execution_failure_summary


def test_diverted_purchase_order_living_draft_skips_fixed_asset_depreciation():
    """Diverting to create_purchase_order renders Purchase Order draft with no fake GL lines or depreciation reqs."""
    from app.living_draft import build_living_draft

    ld = build_living_draft(
        intent="create_purchase_order",
        entities={
            "supplier_name": "Tech Depot",
            "item_description": "Laser printer",
            "amount": 45000.0,
            "transaction_nature": "FIXED_ASSET",
        },
        missing_fields=[],
    )
    assert "Purchase Order" in ld.document_type
    assert ld.depreciation_schedule is None
    assert ld.voucher_preview == []
    assert not any("useful life" in p.lower() for p in ld.pending_requirements)











