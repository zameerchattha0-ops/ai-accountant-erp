"""Tests for Phase 3: Cumulative Dialogue Intent Synthesizer & Zero-Assumption Rule.

Verifies:
1. Multi-turn dialogue synthesis (Turn 0 + Turn 1 + Turn 2 context evaluation).
2. Zero-assumption enforcement (never guess or invent unstated fields).
3. Out-of-order corrections (updating quantity/amount/bank mid-dialogue).
4. Tax exemption certificate handling under Section 153.
"""

import pytest
from app.conversational_manager import synthesize_cumulative_dialogue_intent


@pytest.mark.asyncio
async def test_cumulative_synthesis_multi_turn_laptop_purchase():
    user_request = "bought 5 laptops for 750,000"
    current_entities = {
        "item_description": "laptop",
        "quantity": 5,
        "total_amount": 750000.0,
        "amount": 750000.0,
        "transaction_nature": "FIXED_ASSET",
    }
    history = [
        {"field": "user_request", "question": "user_request", "answer": user_request},
        {
            "field": "payment_method",
            "question": "Which payment method was used and what is the expected useful life?",
            "answer": None,
        },
    ]
    latest_question = "Which payment method was used and what is the expected useful life?"
    user_reply = "Paid via Meezan Bank, 3 years useful life"
    missing_fields = ["payment_method", "useful_life_years"]

    result = await synthesize_cumulative_dialogue_intent(
        user_request=user_request,
        history=history,
        current_entities=current_entities,
        latest_question=latest_question,
        user_reply=user_reply,
        missing_fields=missing_fields,
    )

    entities = result["entities"]
    assert entities.get("payment_method") == "BANK"
    assert entities.get("bank_name") == "Meezan"
    assert entities.get("useful_life_years") == 3
    assert result["is_complete"] is True


@pytest.mark.asyncio
async def test_cumulative_synthesis_zero_assumption_rule():
    """Ensure the synthesizer never assumes missing fields if user did not provide them."""
    user_request = "bought 5 laptops for 750,000"
    current_entities = {
        "item_description": "laptop",
        "quantity": 5,
        "total_amount": 750000.0,
        "amount": 750000.0,
        "transaction_nature": "FIXED_ASSET",
    }
    latest_question = "Which payment method was used and what is the expected useful life?"
    # User only answers payment, omits useful life
    user_reply = "Paid via Meezan Bank"
    missing_fields = ["payment_method", "useful_life_years"]

    result = await synthesize_cumulative_dialogue_intent(
        user_request=user_request,
        history=[],
        current_entities=current_entities,
        latest_question=latest_question,
        user_reply=user_reply,
        missing_fields=missing_fields,
    )

    entities = result["entities"]
    assert entities.get("payment_method") == "BANK"
    assert entities.get("bank_name") == "Meezan"
    # Zero-assumption: useful_life_years must not be assumed/guessed
    assert entities.get("useful_life_years") is None
    assert result["is_complete"] is False


@pytest.mark.asyncio
async def test_cumulative_synthesis_out_of_order_correction():
    """Ensure user corrections mid-dialogue update earlier verified facts."""
    user_request = "bought 5 laptops for 750,000"
    current_entities = {
        "item_description": "laptop",
        "quantity": 5,
        "total_amount": 750000.0,
        "amount": 750000.0,
    }
    user_reply = "actually 4 laptops for 600,000, paid via HBL"

    result = await synthesize_cumulative_dialogue_intent(
        user_request=user_request,
        history=[],
        current_entities=current_entities,
        latest_question="Confirm details",
        user_reply=user_reply,
        missing_fields=["payment_method"],
    )

    entities = result["entities"]
    assert entities.get("payment_method") == "BANK"
    assert entities.get("bank_name") == "Hbl"
    assert entities.get("quantity") in (4, 4.0)
    assert entities.get("amount") in (600000, 600000.0)


@pytest.mark.asyncio
async def test_cumulative_synthesis_tax_exemption_certificate():
    """Ensure tax exemption certificate is correctly bound without assumptions."""
    user_request = "paid vendor ABC 300,000"
    current_entities = {
        "supplier_name": "ABC",
        "amount": 300000.0,
    }
    user_reply = "vendor provided Section 153 exemption certificate"

    result = await synthesize_cumulative_dialogue_intent(
        user_request=user_request,
        history=[],
        current_entities=current_entities,
        latest_question="Is tax deduction applicable under Section 153?",
        user_reply=user_reply,
        missing_fields=["wht_certificate"],
    )

    entities = result["entities"]
    assert entities.get("wht_exempt") is True
    assert entities.get("wht_status") == "EXEMPT"
    assert entities.get("wht_rate_percent") == 0.0
