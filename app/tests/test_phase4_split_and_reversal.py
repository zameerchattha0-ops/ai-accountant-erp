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
