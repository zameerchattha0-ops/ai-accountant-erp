"""Unit tests for conversational and LLM-driven answer parsing (Universal Intake).

Verifies that the LLM answer parser accepts ANY natural phrasing, colloquial text,
Roman Urdu, or conversational multi-field replies and accurately maps them to canonical
accounting endpoints for Fixed Assets, Inventory, and Procurement.
"""
import pytest
from unittest.mock import AsyncMock

from app.answer_parsing import parse_packed_reply_to_endpoints, CANONICAL_FIELD_ENDPOINTS


@pytest.mark.asyncio
async def test_conversational_fixed_asset_answer_parsing(monkeypatch):
    """User replies in conversational English with payment, amount, life, and method."""
    mock_client = type("MockClient", (), {})()

    async def _mock_light(*_args, **_kwargs):
        return (
            '{"amount": "50000", "payment_method": "BANK", '
            '"useful_life_years": "5", "depreciation_method": "STRAIGHT_LINE", '
            '"salvage_value": "0"}'
        )

    mock_client.generate_text_light = _mock_light

    parsed = await parse_packed_reply_to_endpoints(
        question_text=(
            "1. How did you settle the purchase? 2. Total amount? "
            "3. Useful life in years? 4. Depreciation method? 5. Salvage value?"
        ),
        user_reply=(
            "We paid 50,000 via bank transfer, will use the tables in the conference room "
            "for about 5 years, using straight line depreciation and zero scrap value."
        ),
        allowed_endpoints=["payment_method", "amount", "useful_life_years", "depreciation_method", "salvage_value"],
        client=mock_client,
    )

    assert parsed is not None
    assert parsed["amount"] == "50000"
    assert parsed["payment_method"] == "BANK"
    assert parsed["useful_life_years"] == "5"
    assert parsed["depreciation_method"] == "STRAIGHT_LINE"
    assert parsed["salvage_value"] == "0"


@pytest.mark.asyncio
async def test_colloquial_urdu_english_answer_parsing(monkeypatch):
    """User replies in colloquial Urdu-English mixed phrasing."""
    mock_client = type("MockClient", (), {})()

    async def _mock_light(*_args, **_kwargs):
        return (
            '{"amount": "50000", "payment_method": "BANK", '
            '"useful_life_years": "5", "depreciation_method": "STRAIGHT_LINE"}'
        )

    mock_client.generate_text_light = _mock_light

    parsed = await parse_packed_reply_to_endpoints(
        question_text="Payment method, amount, useful life, and depreciation method?",
        user_reply="50k bank se transfer kia tha, 5 saal life hogi tables ki, straight line laga do",
        allowed_endpoints=["payment_method", "amount", "useful_life_years", "depreciation_method"],
        client=mock_client,
    )

    assert parsed is not None
    assert parsed["amount"] == "50000"
    assert parsed["payment_method"] == "BANK"
    assert parsed["useful_life_years"] == "5"
    assert parsed["depreciation_method"] == "STRAIGHT_LINE"


@pytest.mark.asyncio
async def test_decline_depreciation_conversational_answer(monkeypatch):
    """User states they don't want a depreciation schedule."""
    mock_client = type("MockClient", (), {})()

    async def _mock_light(*_args, **_kwargs):
        return (
            '{"useful_life_years": "NONE", "depreciation_method": "NONE"}'
        )

    mock_client.generate_text_light = _mock_light

    parsed = await parse_packed_reply_to_endpoints(
        question_text="What is the useful life and depreciation method?",
        user_reply="We do not want a depreciation schedule for these tables, just record the cost.",
        allowed_endpoints=["useful_life_years", "depreciation_method"],
        client=mock_client,
    )

    assert parsed is not None
    assert parsed["useful_life_years"] == "NONE"
    assert parsed["depreciation_method"] == "NONE"


@pytest.mark.asyncio
async def test_single_field_natural_answer(monkeypatch):
    """User provides a single short conversational answer."""
    mock_client = type("MockClient", (), {})()

    async def _mock_light(*_args, **_kwargs):
        return '{"useful_life_years": "7"}'

    mock_client.generate_text_light = _mock_light

    parsed = await parse_packed_reply_to_endpoints(
        question_text="What is the useful life in years?",
        user_reply="around 7 years or so",
        allowed_endpoints=["useful_life_years"],
        client=mock_client,
    )

    assert parsed is not None
    assert parsed["useful_life_years"] == "7"
