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



