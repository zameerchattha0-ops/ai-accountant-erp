"""Unit tests for Multi-Item Conversational Disaggregator (DOC-ACC-2026-V1 Section 6).

Verifies:
1. Composite sentence parsing and decomposition into LineItemArgs compatible items.
2. Double-entry balance invariant: sum(line amounts) == total amount paid.
3. Categorization and IAS/IFRS nature classification (IAS 1 vs IAS 16 vs IAS 2).
4. Capitalization threshold logic (>= 50k single item, >= 100k aggregate block).
5. Fixed asset registration proposals triggered for capital items.
6. Compound journal voucher generation with balanced debits and credits.
7. Arithmetic imbalance detection and discrepancy reporting.
8. Single-item (non-composite) handling and cash purchase payloads.
"""
import pytest

from app.multi_item_disaggregator import (
    disaggregate_conversational_items,
    DisaggregatedLineItem,
    MultiItemDisaggregationResult,
)
from app.tools import LineItemArgs


@pytest.mark.asyncio
async def test_composite_payment_sentence_disaggregation():
    """Verify parsing of the canonical multi-item compound sentence:

    'Paid 250,000 today: 150,000 for office rent, 30,000 electricity bill,
     and bought an executive laptop for 70,000 via Meezan Bank'
    """
    msg = (
        "Paid 250,000 today: 150,000 for office rent, 30,000 electricity bill, "
        "and bought an executive laptop for 70,000 via Meezan Bank"
    )
    result = await disaggregate_conversational_items(msg, entities={})

    assert isinstance(result, MultiItemDisaggregationResult)
    assert result.is_composite is True
    assert result.total_amount == 250000.0
    assert result.payment_method == "BANK_TRANSFER"
    assert result.bank_name == "Meezan Bank"
    assert result.currency == "PKR"

    # Line Items verification
    assert len(result.line_items) == 3

    # Line 1: Office rent
    l1 = result.line_items[0]
    assert l1.description == "Office rent"
    assert l1.amount == 150000.0
    assert l1.category == "Rent"
    assert l1.nature == "OPERATING_EXPENSE"
    assert l1.is_fixed_asset is False
    assert l1.account_code == "6110"

    # Line 2: Electricity bill
    l2 = result.line_items[1]
    assert l2.description == "Electricity bill"
    assert l2.amount == 30000.0
    assert l2.category == "Utilities"
    assert l2.nature == "OPERATING_EXPENSE"
    assert l2.is_fixed_asset is False
    assert l2.account_code == "6120"

    # Line 3: Executive laptop (Capitalized as Fixed Asset under IAS 16)
    l3 = result.line_items[2]
    assert l3.description == "Executive laptop"
    assert l3.amount == 70000.0
    assert l3.category == "Computer Equipment"
    assert l3.nature == "FIXED_ASSET"
    assert l3.is_fixed_asset is True
    assert l3.account_code == "1520"

    # Invariant: sum(lines) == total
    assert result.sum_line_amounts == 250000.0
    assert result.is_balanced is True
    assert result.balance_discrepancy == 0.0
    assert result.validation_error is None

    # Fixed asset registration triggered
    assert len(result.fixed_asset_registrations_needed) == 1
    fa = result.fixed_asset_registrations_needed[0]
    assert fa["asset_name"] == "Executive laptop"
    assert fa["cost"] == 70000.0
    assert fa["account_code"] == "1520"
    assert fa["useful_life_years"] == 3


@pytest.mark.asyncio
async def test_conversion_to_line_item_args():
    """Verify conversion of disaggregated items into LineItemArgs for tool execution."""
    msg = "Paid 250,000 today: 150,000 for office rent, 30,000 electricity bill, and bought an executive laptop for 70,000 via Meezan Bank"
    result = await disaggregate_conversational_items(msg, entities={})

    args_list = result.to_line_item_args_list()
    assert len(args_list) == 3
    for arg in args_list:
        assert isinstance(arg, LineItemArgs)
        assert arg.quantity >= 1.0
        assert arg.unit_price > 0.0
        assert arg.line_total == arg.quantity * arg.unit_price

    assert args_list[0].description == "Office rent"
    assert args_list[0].line_total == 150000.0
    assert args_list[1].description == "Electricity bill"
    assert args_list[1].line_total == 30000.0
    assert args_list[2].description == "Executive laptop"
    assert args_list[2].line_total == 70000.0


@pytest.mark.asyncio
async def test_compound_journal_generation():
    """Verify compound journal generation with balanced debits and credits."""
    msg = "Paid 250,000 today: 150,000 for office rent, 30,000 electricity bill, and bought an executive laptop for 70,000 via Meezan Bank"
    result = await disaggregate_conversational_items(msg, entities={})

    journal = result.to_compound_journal(transaction_date="2026-10-20", narration="Composite payment via Meezan Bank")
    assert journal["balanced"] is True
    assert journal["total_debit"] == 250000.0
    assert journal["total_credit"] == 250000.0
    assert len(journal["lines"]) == 4  # 3 debits + 1 balancing credit

    # Check debit lines
    debits = [line for line in journal["lines"] if line["debit"] > 0]
    assert len(debits) == 3
    assert sum(d["debit"] for d in debits) == 250000.0

    # Check credit line
    credit_line = [line for line in journal["lines"] if line["credit"] > 0][0]
    assert credit_line["credit"] == 250000.0
    assert credit_line["account_code"] == "1020"
    assert "Meezan Bank" in credit_line["account_name"]


@pytest.mark.asyncio
async def test_arithmetic_imbalance_detection():
    """Verify arithmetic mismatch is flagged when sum(lines) != total amount."""
    msg = "Paid 300,000: 150,000 for office rent and 100,000 for electricity bill"
    result = await disaggregate_conversational_items(msg, entities={})

    assert result.total_amount == 300000.0
    assert result.sum_line_amounts == 250000.0
    assert result.is_balanced is False
    assert result.balance_discrepancy == 50000.0
    assert result.validation_error is not None
    assert "Discrepancy: PKR 50,000.00" in result.validation_error


@pytest.mark.asyncio
async def test_capitalization_threshold_boundaries():
    """Verify IAS 16 vs IAS 1 capitalization threshold rules:

    - Single durable item >= 50,000 -> Capitalized (FIXED_ASSET).
    - Single durable item < 50,000 -> Expense (OPERATING_EXPENSE).
    - Bulk acquisition of furniture >= 100,000 -> Capitalized as aggregate asset block.
    - Consumable supplies (paper) >= 50,000 -> NEVER capitalized.
    """
    # 1. Computer mouse for 4,000 (< 50k -> Expense)
    msg1 = "Paid 4,000 for computer mouse via cash"
    res1 = await disaggregate_conversational_items(msg1, {})
    assert res1.line_items[0].is_fixed_asset is False
    assert res1.line_items[0].nature == "OPERATING_EXPENSE"

    # 2. Executive laptop for 85,000 (>= 50k -> Fixed Asset)
    msg2 = "Paid 85,000 for executive laptop via bank transfer"
    res2 = await disaggregate_conversational_items(msg2, {})
    assert res2.line_items[0].is_fixed_asset is True
    assert res2.line_items[0].nature == "FIXED_ASSET"

    # 3. 5 workstation tables for 120,000 (Bulk aggregate >= 100k -> Capitalized)
    msg3 = "Paid 120,000: 5 workstation tables for 120,000 via bank transfer"
    res3 = await disaggregate_conversational_items(msg3, {})
    assert res3.line_items[0].is_fixed_asset is True
    assert res3.line_items[0].quantity == 5.0
    assert res3.line_items[0].unit_price == 24000.0

    # 4. Consumable stationery for 60,000 (Never capitalized per IAS 1 / Sec 2.3)
    msg4 = "Paid 60,000 for paper reams and printer toners"
    res4 = await disaggregate_conversational_items(msg4, {})
    assert res4.line_items[0].is_fixed_asset is False
    assert res4.line_items[0].nature == "OPERATING_EXPENSE"


@pytest.mark.asyncio
async def test_shorthand_notation_k_and_m():
    """Verify parsing of 'k' and 'M' numerical shorthand."""
    msg = "Spent 500k: 300k factory machinery, 150k raw materials, and 50k courier shipping via Allied Bank"
    res = await disaggregate_conversational_items(msg, {})

    assert res.total_amount == 500000.0
    assert res.sum_line_amounts == 500000.0
    assert res.is_balanced is True
    assert len(res.line_items) == 3
    assert res.line_items[0].amount == 300000.0
    assert res.line_items[0].nature == "FIXED_ASSET"
    assert res.line_items[1].amount == 150000.0
    assert res.line_items[2].amount == 50000.0


@pytest.mark.asyncio
async def test_single_item_cash_purchase():
    """Verify single non-composite cash purchase routing."""
    msg = "Paid 45,000 in cash for office stationery"
    res = await disaggregate_conversational_items(msg, {})

    assert res.is_composite is False
    assert res.total_amount == 45000.0
    assert res.payment_method == "CASH"
    assert res.recommended_action == "RECORD_CASH_PURCHASE"

    payload = res.to_cash_purchase_payload()
    assert payload["amount"] == 45000.0
    assert payload["payment_method"] == "CASH"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["description"] == "Office stationery"


@pytest.mark.asyncio
async def test_cash_section_73_warning_note():
    """Verify cash transaction > 50,000 generates Section 73 warning note."""
    msg = "Paid 80,000 in cash: 50,000 for office rent and 30,000 for utilities"
    res = await disaggregate_conversational_items(msg, {})

    assert res.total_amount == 80000.0
    assert res.payment_method == "CASH"
    assert len(res.statutory_notes) > 0
    assert any("SECTION 73 HAZARD" in note for note in res.statutory_notes)
