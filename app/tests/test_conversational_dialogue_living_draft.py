"""Comprehensive Unit & Integration Tests for Conversational Dialogue & Living Draft Architecture.

Verifies the 3 user pillars:
1. Decision 1 (Option A): Single focused high-leverage question at a time with smart accounting defaults.
2. Decision 2 (Option A): Real-time living draft voucher card preview accumulation.
3. Decision 3: Mid-flow consultative question answering and seamless absorption of out-of-order corrections.
"""

import pytest
from app.living_draft import (
    LivingDraft,
    VoucherLinePreview,
    DepreciationSchedulePreview,
    build_living_draft,
)
from app.consultative_advisory import (
    detect_consultative_query,
    generate_consultative_advisory,
    is_consultative_query,
    get_consultative_advice,
    TOPIC_SECTION_73,
    TOPIC_SECTION_153,
    TOPIC_IAS_16,
    TOPIC_DEPRECIATION,
)
from app.conversational_manager import (
    pick_next_leverage_field,
    author_single_focused_question,
    expand_smart_default_answer,
    expand_standard_schedule_answers,
    extract_conversational_corrections,
    format_claude_style_progressive_question,
    compose_consultative_response_with_draft,
)
from app.answer_parsing import detect_out_of_order_correction


# ===========================================================================
# Pillar 1 (Decision 1 Option A): Progressive Pacing & Smart Defaults
# ===========================================================================

def test_pick_next_leverage_field_hierarchy():
    """Verify priority hierarchy selects highest leverage question first."""
    # When nature is missing, ask nature first
    f1 = pick_next_leverage_field(["useful_life_years", "transaction_nature", "supplier_name"])
    assert f1 == "transaction_nature"

    # When amount is missing, ask amount before counterparty or settlement
    f2 = pick_next_leverage_field(["supplier_name", "amount", "payment_channel"])
    assert f2 == "amount"

    # When counterparty is missing, ask counterparty before payment method or depreciation
    f3 = pick_next_leverage_field(["useful_life_years", "supplier_name", "depreciation_method"])
    assert f3 == "supplier_name"

    # When payment channel is missing, ask payment channel before depreciation
    f4 = pick_next_leverage_field(["useful_life_years", "payment_channel", "salvage_value"])
    assert f4 == "payment_channel"


def test_author_single_question_it_equipment_smart_defaults():
    """Verify IT equipment offers 3-year straight-line IAS 16 smart defaults with quick chips."""
    q = author_single_focused_question(
        field_to_ask="useful_life_years",
        entities={"item_description": "Dell XPS 15 Laptop", "amount": 280000},
    )
    assert q.primary_field == "useful_life_years"
    assert "3-year useful life" in q.question_text
    assert "straight-line" in q.question_text
    assert "Accept 3-Yr Straight Line (Recommended)" in q.chips
    assert "Expense Immediately" in q.chips
    assert q.expanded_fields["useful_life_years"] == "3"
    assert q.expanded_fields["depreciation_method"] == "STRAIGHT_LINE"
    assert q.expanded_fields["salvage_value"] == "0"


def test_author_single_question_furniture_smart_defaults():
    """Verify office furniture offers 5-year straight line defaults."""
    q = author_single_focused_question(
        field_to_ask="useful_life_years",
        entities={"item_description": "Conference Room Table and Chairs", "amount": 150000},
    )
    assert q.primary_field == "useful_life_years"
    assert "5-year straight-line" in q.question_text
    assert "Accept 5-Yr Straight Line (Recommended)" in q.chips


def test_author_single_question_payment_section_73_statutory_guidance():
    """Verify payments exceeding PKR 50,000 advise bank transfer under Section 73."""
    q = author_single_focused_question(
        field_to_ask="payment_channel",
        entities={"item_description": "Office Generators", "amount": 120000},
    )
    assert "Section 73" in q.question_text
    assert "PKR 50,000" in q.question_text
    assert "Bank Transfer (Recommended)" in q.chips
    assert "Crossed Cheque" in q.chips


def test_expand_smart_default_answer():
    """Verify quick chip responses expand into complete accounting parameters."""
    res1 = expand_smart_default_answer("Accept 3-Yr Straight Line (Recommended)")
    assert res1 == {
        "useful_life_years": "3",
        "depreciation_method": "STRAIGHT_LINE",
        "salvage_value": "0",
    }

    res2 = expand_smart_default_answer("Accept 5-Yr Straight Line (Recommended)")
    assert res2 == {
        "useful_life_years": "5",
        "depreciation_method": "STRAIGHT_LINE",
        "salvage_value": "0",
    }

    res3 = expand_smart_default_answer("Expense Immediately")
    assert res3 == {
        "transaction_nature": "OPERATING_EXPENSE",
        "capitalization_decision": "EXPENSE",
        "useful_life_years": "NONE",
        "depreciation_method": "NONE",
    }

    res4 = expand_smart_default_answer("Bank Transfer (Recommended)")
    assert res4 == {
        "payment_channel": "bank_transfer",
        "payment_method": "BANK",
    }


# ===========================================================================
# Pillar 2 (Decision 2 Option A): Real-Time Living Draft Voucher Card
# ===========================================================================

def test_build_living_draft_fixed_asset():
    """Verify fixed asset draft builds complete voucher preview, depreciation schedule, and compliance notes."""
    entities = {
        "amount": 300000.0,
        "payment_method": "bank_transfer",
        "bank_name": "Meezan Bank",
        "supplier_name": "Dell Technologies",
        "description": "2 Dell XPS Laptops",
        "transaction_nature": "FIXED_ASSET",
        "useful_life_years": 3,
        "depreciation_method": "STRAIGHT_LINE",
        "salvage_value": 0.0,
    }
    draft = build_living_draft(
        intent="record_purchase",
        entities=entities,
        missing_fields=[],
    )

    assert isinstance(draft, LivingDraft)
    assert "Fixed Asset Capitalization" in draft.document_type
    assert draft.total_amount == 300000.0
    assert draft.payment_channel == "bank_transfer"
    assert draft.bank_name == "Meezan Bank"
    assert draft.counterparty is not None
    assert draft.counterparty.name == "Dell Technologies"
    assert draft.status == "ready_for_confirmation"
    assert draft.missing_fields == []

    # Voucher Preview (Debit IT Equipment, Credit Meezan Bank)
    assert len(draft.voucher_preview) == 2
    debit_line = draft.voucher_preview[0]
    credit_line = draft.voucher_preview[1]
    assert "Computer & IT Equipment" in debit_line.account_name
    assert debit_line.debit == 300000.0
    assert "Meezan Bank" in credit_line.account_name
    assert credit_line.credit == 300000.0

    # Depreciation Schedule
    assert draft.depreciation_schedule is not None
    assert draft.depreciation_schedule.useful_life_years == 3
    assert draft.depreciation_schedule.method == "STRAIGHT_LINE"
    assert draft.depreciation_schedule.annual_depreciation == 100000.0
    assert draft.depreciation_schedule.monthly_depreciation == 8333.33

    # Compliance Notes
    notes_str = " ".join(draft.compliance_notes)
    assert "Section 73 Compliance" in notes_str
    assert "Meezan Bank" in notes_str
    assert "IAS 16" in notes_str

    # to_dict compatibility
    d_dict = draft.to_dict()
    assert isinstance(d_dict, dict)
    assert d_dict["document_type"] == draft.document_type


def test_build_living_draft_cash_expense_with_section_73_warning():
    """Verify cash operating expense > PKR 50,000 generates statutory Section 73 warning note."""
    entities = {
        "amount": 85000.0,
        "payment_method": "cash",
        "description": "Office Renovation Supplies",
        "transaction_nature": "OPERATING_EXPENSE",
    }
    draft = build_living_draft(
        intent="record_expense",
        entities=entities,
        missing_fields=["transaction_date"],
    )

    assert draft.status == "awaiting_input"
    assert draft.missing_fields == ["transaction_date"]
    assert any("Section 73 / 21(l) Warning" in n for n in draft.compliance_notes)
    assert any("PKR 50,000" in n for n in draft.compliance_notes)


# ===========================================================================
# Pillar 3 (Decision 3): Consultative Questions & Out-of-Order Corrections
# ===========================================================================

def test_detect_consultative_query_topics():
    """Verify mid-flow consultative inquiries are recognized accurately."""
    assert detect_consultative_query("What is the cash limit under Section 73?") == TOPIC_SECTION_73
    assert detect_consultative_query("Can I pay 80,000 in cash?") == TOPIC_SECTION_73
    assert detect_consultative_query("What is the WHT rate for IT services u/s 153?") == TOPIC_SECTION_153
    assert detect_consultative_query("Should I capitalize or expense this laptop under IAS 16?") == TOPIC_IAS_16
    assert detect_consultative_query("What depreciation rate does FBR prescribe for furniture?") == TOPIC_DEPRECIATION

    # Direct answers are NOT consultative queries
    assert detect_consultative_query("3 years straight line") is None
    assert detect_consultative_query("Paid via Meezan Bank") is None
    assert detect_consultative_query("Meezan Bank") is None
    assert detect_consultative_query("Dell Pakistan") is None


def test_generate_consultative_advisory():
    """Verify statutory advisory response includes citations, resume bridge, and chips."""
    res = generate_consultative_advisory(
        topic=TOPIC_SECTION_73,
        user_message="What is the cash limit under Section 73?",
        current_amount=90000.0,
        entities={"item_description": "Server Equipment", "amount": 90000},
    )
    assert res.is_consultative is True
    assert "Section 73 & Section 21(l)" in res.statutory_reference
    assert "PKR 50,000" in res.advisory_markdown
    assert "PKR 250,000" in res.advisory_markdown
    assert "Server Equipment" in res.context_resume_prompt
    assert "Pay via Bank Transfer (Recommended)" in res.suggested_chips


def test_detect_out_of_order_corrections():
    """Verify corrections mid-flow are absorbed and extracted into canonical fields."""
    # Amount correction
    c1 = detect_out_of_order_correction("Wait, change the amount to 280,000")
    assert c1 is not None
    assert c1["amount"] == 280000.0

    # Shorthand 250k amount correction
    c1_short = detect_out_of_order_correction("Actually it was 250k")
    assert c1_short is not None
    assert c1_short["amount"] == 250000.0

    # Payment channel & bank correction
    c2 = detect_out_of_order_correction("Actually paid via Meezan Bank, not cash")
    assert c2 is not None
    assert c2["payment_method"] == "BANK"
    assert c2["bank_name"] == "Meezan Bank"

    # Supplier correction
    c3 = detect_out_of_order_correction("Correction: supplier is Dell Pakistan")
    assert c3 is not None
    assert c3["supplier_name"] == "Dell Pakistan"

    # Depreciation schedule correction
    c4 = detect_out_of_order_correction("Make it 5 years straight line instead")
    assert c4 is not None
    assert c4["useful_life_years"] == "5"
    assert c4["depreciation_method"] == "STRAIGHT_LINE"

    # Nature / expense correction
    c5 = detect_out_of_order_correction("Expense it instead of capitalizing")
    assert c5 is not None
    assert c5["transaction_nature"] == "OPERATING_EXPENSE"


def test_compose_consultative_response_with_draft():
    """Verify composed consultative turn preserves draft status while delivering advice."""
    advice = "Section 73 limits cash payments to PKR 50,000."
    draft = {
        "document_type": "Fixed Asset Capitalization Voucher",
        "total_amount": 300000.0,
        "payment_channel": "bank_transfer",
        "bank_name": "Meezan Bank",
        "status": "AWAITING_INPUT",
    }
    composed = compose_consultative_response_with_draft(
        user_query="Can I pay cash?",
        living_draft=draft,
        next_question="Who was the supplier?",
        advice=advice,
    )
    assert "Section 73 limits cash" in composed
    assert "Fixed Asset Capitalization Voucher" in composed
    assert "Rs. 300,000.00" in composed
    assert "Bank Transfer (Meezan Bank)" in composed
    assert "Who was the supplier?" in composed
