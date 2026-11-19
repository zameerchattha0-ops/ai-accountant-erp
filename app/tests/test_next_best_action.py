"""
Unit Tests for Post-Transaction "Next Best Action" (NBA) & Virtual CFO Advisory
================================================================================
Comprehensive tests for `app/next_best_action.py`:
1. Budget & Envelope Burn Monitoring (Capex/Opex headroom, 80%+ warnings, overruns).
2. Statutory FBR Tax Calendar Reminders (Section 153 WHT, Section 73 Cash, Sales Tax, S.147).
3. Cash Flow & Liquidity Runway (Liquid bank balances / monthly burn, runway reduction).
4. Audit Trail & Voucher Substantiation.
5. Edge cases: Missing snapshot, zero values, year-boundary month transitions, journal lines format.
"""

from __future__ import annotations

from datetime import date
import pytest

from app.next_best_action import (
    ActionCategory,
    ActionPriority,
    EnvelopeType,
    NextBestActionItem,
    NextBestActionResult,
    calculate_next_month_deadlines,
    find_next_advance_tax_deadline,
    generate_next_best_actions,
    parse_transaction_date,
)


@pytest.fixture
def sample_capex_transaction():
    """A realistic Capex purchase: Laptop acquisition on bank transfer with WHT deducted."""
    return {
        "id": "BILL-CAPEX-2026-001",
        "bill_number": "BILL-CAPEX-2026-001",
        "transaction_date": "2026-03-24",
        "description": "5x Dell Latitude Laptops for Engineering Team",
        "account_code": "1510",
        "account_name": "Computer & IT Equipment",
        "category": "CAPEX",
        "subtotal": 150000.0,
        "tax_amount": 27000.0,
        "wht_amount": 7500.0,
        "total": 169500.0,
        "payment_method": "BANK",
        "currency": "PKR",
    }


@pytest.fixture
def sample_financial_snapshot():
    """A realistic grounded financial evidence snapshot."""
    return {
        "budgets": {
            "capex": {
                "budget": 500000.0,
                "actual_mtd": 270000.0,
                "period": "Q2 2026",
            },
            "opex": {
                "budget": 800000.0,
                "actual_mtd": 650000.0,
                "period": "March 2026",
            },
        },
        "cash_flow": {
            "total_liquid_cash": 450000.0,
            "bank_and_cash_balances": 450000.0,
        },
        "cash_runway": {
            "total_liquid_cash": 450000.0,
            "monthly_burn_rate": 100000.0,
            "average_monthly_burn_rate": 100000.0,
            "runway_months": 4.5,
        },
        "working_capital_metrics": {
            "working_capital": 300000.0,
            "current_ratio": 1.75,
        },
    }


# ===========================================================================
# 1. Date & Statutory Calendar Helpers Tests
# ===========================================================================

def test_parse_transaction_date_variations():
    """Verify parsing of various date types and formats."""
    assert parse_transaction_date("2026-03-24") == date(2026, 3, 24)
    assert parse_transaction_date("2026-11-18T10:30:00Z") == date(2026, 11, 18)
    assert parse_transaction_date(date(2026, 5, 1)) == date(2026, 5, 1)
    # Fallback on empty or invalid string
    assert parse_transaction_date(None) == date.today()
    assert parse_transaction_date("") == date.today()


def test_calculate_next_month_deadlines_normal_month():
    """March transaction triggers April deadlines."""
    tx_date = date(2026, 3, 24)
    deadlines = calculate_next_month_deadlines(tx_date)
    assert deadlines["provincial_gst"] == date(2026, 4, 14)
    assert deadlines["fbr_gst_payment"] == date(2026, 4, 15)
    assert deadlines["wht_statement"] == date(2026, 4, 15)
    assert deadlines["fbr_gst_return"] == date(2026, 4, 18)


def test_calculate_next_month_deadlines_year_boundary():
    """December transaction triggers January deadlines of next year."""
    tx_date = date(2026, 12, 10)
    deadlines = calculate_next_month_deadlines(tx_date)
    assert deadlines["provincial_gst"] == date(2027, 1, 14)
    assert deadlines["fbr_gst_payment"] == date(2027, 1, 15)
    assert deadlines["wht_statement"] == date(2027, 1, 15)
    assert deadlines["fbr_gst_return"] == date(2027, 1, 18)


def test_find_next_advance_tax_deadline():
    """Advance tax falls on 15th Oct, 15th Jan, 15th Apr, 15th Jun."""
    # From March 24, next is April 15
    assert find_next_advance_tax_deadline(date(2026, 3, 24)) == date(2026, 4, 15)
    # From April 20, next is June 15
    assert find_next_advance_tax_deadline(date(2026, 4, 20)) == date(2026, 6, 15)
    # From July 1, next is Oct 15
    assert find_next_advance_tax_deadline(date(2026, 7, 1)) == date(2026, 10, 15)


# ===========================================================================
# 2. Budget & Envelope Burn Monitoring Tests
# ===========================================================================

def test_capex_budget_monitoring_headroom_and_warning(sample_capex_transaction, sample_financial_snapshot):
    """PKR 169.5k Capex brings Q2 Capex to PKR 439.5k / PKR 500k (87.9% utilized, warning)."""
    # Adjust total amount to exactly PKR 150k for canonical test
    sample_capex_transaction["total"] = 150000.0

    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)
    assert result.budget_summary is not None
    bs = result.budget_summary

    assert bs.envelope_type == EnvelopeType.CAPEX
    assert bs.budget_amount == 500000.0
    assert bs.actual_before == 270000.0
    assert bs.actual_after == 420000.0
    assert bs.utilization_pct == 84.0
    assert bs.headroom == 80000.0
    assert bs.is_over_budget is False
    assert bs.warning_threshold_exceeded is True

    # Check that a budget action item was created
    budget_items = [it for it in result.items if it.category == ActionCategory.BUDGET]
    assert len(budget_items) == 1
    item = budget_items[0]
    assert item.priority in (ActionPriority.MEDIUM, ActionPriority.HIGH)
    assert "84.0% utilized" in item.executive_summary
    assert "80,000.00 remaining" in item.executive_summary


def test_budget_overrun_critical_priority(sample_capex_transaction, sample_financial_snapshot):
    """Transaction exceeding budget triggers HIGH priority overrun directive."""
    sample_capex_transaction["total"] = 300000.0  # 270k + 300k = 570k > 500k budget

    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)
    bs = result.budget_summary
    assert bs.is_over_budget is True
    assert bs.headroom < 0

    budget_items = [it for it in result.items if it.category == ActionCategory.BUDGET]
    assert len(budget_items) == 1
    item = budget_items[0]
    assert item.priority == ActionPriority.HIGH
    assert "Critical" in item.title or "Overrun" in item.title
    assert item.action_type == "BUDGET_REALLOCATION_APPROVAL"


def test_budget_within_comfortable_limits(sample_capex_transaction, sample_financial_snapshot):
    """Transaction with low utilization produces INFO item."""
    sample_capex_transaction["total"] = 20000.0
    sample_financial_snapshot["budgets"]["capex"]["actual_mtd"] = 100000.0  # 120k / 500k = 24%

    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)
    bs = result.budget_summary
    assert bs.warning_threshold_exceeded is False
    budget_items = [it for it in result.items if it.category == ActionCategory.BUDGET]
    assert budget_items[0].priority == ActionPriority.INFO


# ===========================================================================
# 3. Statutory FBR Tax Calendar Reminders Tests
# ===========================================================================

def test_section_153_wht_calendar_reminder(sample_capex_transaction, sample_financial_snapshot):
    """Section 153 WHT triggers CPR treasury deposit reminder due by 15th of next month."""
    sample_capex_transaction["wht_amount"] = 7500.0
    sample_capex_transaction["transaction_date"] = "2026-03-24"

    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)
    tax_items = [it for it in result.items if it.category == ActionCategory.TAX_COMPLIANCE and "153" in (it.statutory_reference or "")]
    assert len(tax_items) == 1

    wht_item = tax_items[0]
    assert wht_item.priority == ActionPriority.HIGH
    assert "7,500.00" in wht_item.executive_summary
    assert "15 April 2026" in wht_item.executive_summary
    assert "CPR" in wht_item.executive_summary
    assert wht_item.deadline_date == "2026-04-15"
    assert wht_item.action_type == "DEPOSIT_WHT_CPR"


def test_section_73_cash_opex_disallowance_risk(sample_financial_snapshot):
    """Cash expense payment exceeding PKR 50,000 incurs 100% tax disallowance under Section 21(l)."""
    tx_cash = {
        "id": "CASH-OPEX-001",
        "transaction_date": "2026-03-24",
        "description": "Office Renovation & Painting Service",
        "account_code": "5200",
        "category": "OPEX",
        "total": 150000.0,
        "payment_method": "CASH",
        "currency": "PKR",
    }
    result = generate_next_best_actions(tx_cash, sample_financial_snapshot)

    s73_items = [it for it in result.items if "Section 73" in it.title or "Section 73" in (it.statutory_reference or "")]
    assert len(s73_items) == 1
    item = s73_items[0]
    assert item.priority == ActionPriority.HIGH
    assert "Section 21(l)" in item.executive_summary
    assert "100% expense disallowance" in item.executive_summary
    # 29% penalty on 150k = 43,500
    assert "43,500.00" in item.executive_summary


def test_section_73_cash_capex_depreciation_forfeiture(sample_financial_snapshot):
    """Cash purchase of capital asset exceeding PKR 250,000 permanently forfeits depreciation."""
    tx_cash_capex = {
        "id": "CASH-CAPEX-001",
        "transaction_date": "2026-03-24",
        "description": "Machinery Purchase",
        "account_code": "1540",
        "category": "CAPEX",
        "total": 300000.0,
        "payment_method": "CASH",
    }
    result = generate_next_best_actions(tx_cash_capex, sample_financial_snapshot)

    s73_items = [it for it in result.items if "Section 73" in it.title or "Section 73" in (it.statutory_reference or "")]
    assert len(s73_items) == 1
    item = s73_items[0]
    assert item.priority == ActionPriority.HIGH
    assert "forfeits all tax depreciation" in item.executive_summary


def test_section_73_bank_payment_compliance(sample_capex_transaction, sample_financial_snapshot):
    """Bank settlement is verified as Section 73 compliant with INFO item."""
    sample_capex_transaction["payment_method"] = "BANK"
    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)

    s73_items = [it for it in result.items if "Section 73 Banking Channel" in it.title]
    assert len(s73_items) == 1
    assert s73_items[0].priority == ActionPriority.INFO


def test_sales_tax_return_calendar(sample_capex_transaction, sample_financial_snapshot):
    """Transaction with sales tax includes provincial (14th), payment (15th) and return (18th) deadlines."""
    sample_capex_transaction["tax_amount"] = 27000.0
    sample_capex_transaction["transaction_date"] = "2026-03-24"

    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)
    gst_items = [it for it in result.items if "Sales Tax Return" in it.title]
    assert len(gst_items) == 1
    item = gst_items[0]
    assert "14 April 2026" in item.executive_summary
    assert "15 April 2026" in item.executive_summary
    assert "18 April 2026" in item.executive_summary


# ===========================================================================
# 4. Cash Flow & Liquidity Runway Tests
# ===========================================================================

def test_cash_runway_impact_calculation(sample_capex_transaction, sample_financial_snapshot):
    """Verify runway reduction calculation after cash outflow."""
    sample_capex_transaction["total"] = 150000.0
    sample_capex_transaction["payment_method"] = "BANK"
    # Liquid cash before: 450k, monthly burn: 100k -> 4.5 months
    # Outflow: 150k -> Liquid cash after: 300k -> 3.0 months

    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)
    assert result.runway_summary is not None
    rs = result.runway_summary

    assert rs.total_liquid_cash_before == 450000.0
    assert rs.cash_outflow == 150000.0
    assert rs.total_liquid_cash_after == 300000.0
    assert rs.runway_months_before == 4.5
    assert rs.runway_months_after == 3.0
    assert rs.runway_reduction_months == 1.5


def test_critical_liquidity_alert_when_runway_under_three_months(sample_financial_snapshot):
    """Runway dropping below 3 months triggers HIGH priority critical liquidity alert."""
    tx_heavy = {
        "id": "HEAVY-EXPENSE-001",
        "transaction_date": "2026-03-24",
        "total": 350000.0,
        "payment_method": "BANK",
        "category": "OPEX",
    }
    # 450k - 350k = 100k left / 100k burn = 1.0 month runway
    result = generate_next_best_actions(tx_heavy, sample_financial_snapshot)
    rs = result.runway_summary
    assert rs.liquidity_status == "Critical"
    assert rs.runway_months_after == 1.0

    cash_items = [it for it in result.items if it.category == ActionCategory.CASH_FLOW]
    assert len(cash_items) == 1
    assert cash_items[0].priority == ActionPriority.HIGH
    assert "Critical Liquidity Alert" in cash_items[0].title


def test_credit_transaction_does_not_reduce_liquid_cash(sample_capex_transaction, sample_financial_snapshot):
    """Credit / Accounts Payable purchase leaves liquid cash untouched."""
    sample_capex_transaction["payment_method"] = "CREDIT"
    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)

    rs = result.runway_summary
    assert rs.cash_outflow == 0.0
    assert rs.total_liquid_cash_after == sample_financial_snapshot["cash_flow"]["total_liquid_cash"]


# ===========================================================================
# 5. Audit Trail & Voucher Substantiation Tests
# ===========================================================================

def test_audit_trail_substantiation_capex(sample_capex_transaction, sample_financial_snapshot):
    """Capex transaction mandates asset tags and GRN in audit trail item."""
    result = generate_next_best_actions(sample_capex_transaction, sample_financial_snapshot)
    audit_items = [it for it in result.items if it.category == ActionCategory.AUDIT_TRAIL]
    assert len(audit_items) == 1
    item = audit_items[0]
    assert item.priority == ActionPriority.MEDIUM
    assert "Fixed Asset Tagging Record" in item.executive_summary
    assert "Section 174 & 177" in item.statutory_reference


# ===========================================================================
# 6. Edge Cases & Hermetic Resilience
# ===========================================================================

def test_generate_next_best_actions_minimal_transaction_no_snapshot():
    """Engine functions gracefully without crashing when snapshot is None or transaction minimal."""
    result = generate_next_best_actions({}, None)
    assert isinstance(result, NextBestActionResult)
    assert result.total_amount == 0.0
    assert len(result.items) > 0
    assert result.budget_summary is not None
    assert result.runway_summary is not None
    assert result.compliance_summary is not None


def test_transaction_with_journal_lines():
    """Parse debit/credit lines structure when top-level total is missing."""
    tx_with_lines = {
        "id": "JE-2026-999",
        "transaction_date": "2026-03-24",
        "lines": [
            {"account_code": "1520", "account_name": "Office Furniture", "debit": 85000.0, "credit": 0.0},
            {"account_code": "2120", "account_name": "WHT Payable", "debit": 0.0, "credit": 4250.0},
            {"account_code": "1020", "account_name": "Meezan Bank", "debit": 0.0, "credit": 80750.0},
        ],
    }
    result = generate_next_best_actions(tx_with_lines)
    assert result.total_amount == 85000.0
    assert result.compliance_summary.wht_amount == 4250.0
    assert result.budget_summary.envelope_type == EnvelopeType.CAPEX
    assert any("Section 153" in (it.statutory_reference or "") for it in result.items)
