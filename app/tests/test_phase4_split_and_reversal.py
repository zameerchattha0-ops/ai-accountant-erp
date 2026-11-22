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

