"""
Unit tests for Live Grounded Financial Evidence Retrieval Layer
(app/financial_evidence.py).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from app.financial_evidence import (
    gather_financial_evidence,
    is_current_asset,
    is_long_term_liability,
)
from app.repositories import (
    bank_repository,
    invoice_repository,
    organization_repository,
    purchase_repository,
    report_repository,
)
from app.services import reporting_service


# ---------------------------------------------------------------------------
# Classification Helper Tests
# ---------------------------------------------------------------------------

def test_is_current_asset_classification():
    # By account name keywords
    assert is_current_asset({"account_name": "Bank Current Account", "account_code": "1010"}) is True
    assert is_current_asset({"account_name": "Petty Cash", "account_code": "1020"}) is True
    assert is_current_asset({"account_name": "Accounts Receivable", "account_code": "1100"}) is True
    assert is_current_asset({"account_name": "Inventory - Raw Materials", "account_code": "1200"}) is True
    assert is_current_asset({"account_name": "Prepaid Rent", "account_code": "1310"}) is True

    # Non-current terms
    assert is_current_asset({"account_name": "Machinery & Equipment", "account_code": "1510"}) is False
    assert is_current_asset({"account_name": "Furniture & Fixtures", "account_code": "1520"}) is False
    assert is_current_asset({"account_name": "Accumulated Depreciation - Plant", "account_code": "1555"}) is False
    assert is_current_asset({"account_name": "Software Licences", "account_code": "1710"}) is False

    # By parent account name
    assert is_current_asset({"account_name": "Custom Asset", "parent_account_name": "Current Assets"}) is True
    assert is_current_asset({"account_name": "Custom Asset", "parent_account_name": "Non-Current Assets"}) is False


def test_is_long_term_liability_classification():
    # Long term terms
    assert is_long_term_liability({"account_name": "Long-Term Bank Loan", "account_code": "2610"}) is True
    assert is_long_term_liability({"account_name": "Lease Liability (Non-Current)", "account_code": "2710"}) is True
    assert is_long_term_liability({"account_name": "Bonds Payable", "account_code": "2810"}) is True

    # Current liability terms
    assert is_long_term_liability({"account_name": "Accounts Payable", "account_code": "2010"}) is False
    assert is_long_term_liability({"account_name": "Sales Tax Payable", "account_code": "2110"}) is False
    assert is_long_term_liability({"account_name": "Accrued Salaries", "account_code": "2210"}) is False
    assert is_long_term_liability({"account_name": "Short-Term Loan", "account_code": "2310"}) is False

    # By parent account name
    assert is_long_term_liability({"account_name": "Special Loan", "parent_account_name": "Non-Current Liabilities"}) is True
    assert is_long_term_liability({"account_name": "Special Loan", "parent_account_name": "Current Liabilities"}) is False


# ---------------------------------------------------------------------------
# Full Grounded Evidence Gathering Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_evidence_gathering_with_mocked_data(monkeypatch):
    org_id = uuid.uuid4()

    fake_income = [
        {"account_code": "4010", "account_name": "Services Revenue", "account_type": "REVENUE", "net_amount": -100000.0},
        {"account_code": "5010", "account_name": "Cost of Goods Sold", "account_type": "EXPENSE", "net_amount": 30000.0},
        {"account_code": "6010", "account_name": "Office Rent", "account_type": "EXPENSE", "net_amount": 15000.0},
        {"account_code": "6020", "account_name": "Salaries & Wages", "account_type": "EXPENSE", "net_amount": 25000.0},
        {"account_code": "7010", "account_name": "Finance Costs", "account_type": "EXPENSE", "net_amount": 2000.0},
        {"account_code": "8010", "account_name": "Tax Expense", "account_type": "EXPENSE", "net_amount": 3000.0},
    ]

    fake_balance_sheet = [
        {"account_code": "1010", "account_name": "Bank Current Account", "account_type": "ASSET", "net_amount": 50000.0},
        {"account_code": "1100", "account_name": "Accounts Receivable", "account_type": "ASSET", "net_amount": 30000.0},
        {"account_code": "1200", "account_name": "Inventory", "account_type": "ASSET", "net_amount": 20000.0},
        {"account_code": "1510", "account_name": "Machinery & Equipment", "account_type": "ASSET", "net_amount": 100000.0},
        {"account_code": "2010", "account_name": "Accounts Payable", "account_type": "LIABILITY", "net_amount": -25000.0},
        {"account_code": "2110", "account_name": "Sales Tax Payable", "account_type": "LIABILITY", "net_amount": -5000.0},
        {"account_code": "2610", "account_name": "Long-Term Loan", "account_type": "LIABILITY", "net_amount": -30000.0},
        {"account_code": "3010", "account_name": "Owner Capital", "account_type": "EQUITY", "net_amount": -140000.0},
    ]

    fake_cash_flow = [
        {"cash_flow_category": "OPERATING", "net_amount": 25000.0, "transaction_date": "2026-11-01"},
        {"cash_flow_category": "INVESTING", "net_amount": -10000.0, "transaction_date": "2026-11-05"},
        {"cash_flow_category": "FINANCING", "net_amount": -5000.0, "transaction_date": "2026-11-10"},
    ]

    fake_banks = [
        {"id": "b1", "account_name": "Main Bank", "bank_name": "Meezan Bank", "current_balance": 50000.0, "currency_code": "PKR"},
    ]
    fake_cash = [
        {"id": "c1", "name": "Cash Drawer", "current_balance": 5000.0, "currency_code": "PKR"},
    ]

    fake_customer_aging = [
        {"customer_id": "cust1", "total_outstanding": 30000.0, "bucket_current": 20000.0, "bucket_1_30": 10000.0},
    ]
    fake_supplier_aging = [
        {"supplier_id": "supp1", "total_outstanding": 25000.0, "bucket_current": 15000.0, "bucket_1_30": 10000.0},
    ]

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=fake_income))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=fake_balance_sheet))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=fake_cash_flow))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=fake_banks))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=fake_cash))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=fake_customer_aging))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=fake_supplier_aging))

    evidence = await gather_financial_evidence(org_id)

    # 1. Profit & Loss checks
    pl = evidence["profit_and_loss"]
    assert pl["revenue"] == 100000.0
    assert pl["cost_of_sales"] == 30000.0
    assert pl["gross_profit"] == 70000.0
    assert pl["operating_expenses"] == 40000.0
    assert pl["operating_profit"] == 30000.0
    assert pl["finance_costs"] == 2000.0
    assert pl["tax_expense"] == 3000.0
    assert pl["net_profit"] == 25000.0
    assert pl["is_loss"] is False

    # 2. Balance Sheet checks
    bs = evidence["balance_sheet"]
    assert bs["current_assets"] == 100000.0
    assert bs["non_current_assets"] == 100000.0
    assert bs["total_assets"] == 200000.0
    assert bs["current_liabilities"] == 30000.0
    assert bs["long_term_liabilities"] == 30000.0
    assert bs["total_liabilities"] == 60000.0
    assert bs["equity"] == 140000.0
    assert bs["net_assets"] == 140000.0

    # 3. Cash Flow checks
    cf = evidence["cash_flow"]
    assert cf["operating_cash_flows"] == 25000.0
    assert cf["investing_cash_flows"] == -10000.0
    assert cf["financing_cash_flows"] == -5000.0
    assert cf["net_cash_change"] == 10000.0
    assert cf["total_liquid_cash"] == 55000.0
    assert len(cf["bank_balances"]) == 1
    assert len(cf["cash_balances"]) == 1

    # 4. Working Capital Metrics
    wc = evidence["working_capital_metrics"]
    assert wc["working_capital"] == 70000.0
    assert wc["current_ratio"] == round(100000.0 / 30000.0, 2)  # 3.33
    # Quick Ratio: (55000 liquid cash + 30000 AR) / 30000 = 85000 / 30000 = 2.83
    assert wc["quick_ratio"] == round(85000.0 / 30000.0, 2)  # 2.83
    assert wc["status"] == "Adequate"

    # 5. Financial Ratios Accuracy
    ratios = evidence["financial_ratios"]
    assert ratios["gross_profit_margin"] == 70.0  # (70k / 100k) * 100
    assert ratios["net_profit_margin"] == 25.0    # (25k / 100k) * 100
    assert ratios["operating_margin"] == 30.0     # (30k / 100k) * 100
    assert ratios["return_on_assets"] == 12.5     # (25k / 200k) * 100
    assert ratios["return_on_equity"] == round((25000.0 / 140000.0) * 100, 2)  # 17.86%
    assert ratios["debt_to_equity_ratio"] == round(60000.0 / 140000.0, 2)       # 0.43

    # 6. Aging Summary
    aging = evidence["aging_summary"]
    assert aging["total_open_receivables"] == 30000.0
    assert aging["overdue_receivables"] == 10000.0
    assert aging["total_open_payables"] == 25000.0
    assert aging["overdue_payables"] == 10000.0

    # 7. Expense Breakdown
    breakdown = evidence["expense_breakdown"]
    assert len(breakdown) == 2
    assert breakdown[0]["account_code"] == "6020"
    assert breakdown[0]["amount"] == 25000.0
    assert breakdown[0]["percentage"] == 62.5  # 25k / 40k * 100
    assert breakdown[1]["account_code"] == "6010"
    assert breakdown[1]["amount"] == 15000.0
    assert breakdown[1]["percentage"] == 37.5  # 15k / 40k * 100

    # 8. Cash Runway
    runway = evidence["cash_runway"]
    assert runway["total_liquid_cash"] == 55000.0
    assert runway["monthly_burn_rate"] == 40000.0
    assert runway["runway_months"] == round(55000.0 / 40000.0, 2)  # 1.38 months


# ---------------------------------------------------------------------------
# Division by Zero and Edge Case Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edge_case_zero_revenue(monkeypatch):
    """When revenue is zero, margins must safely return 0.0 without ZeroDivisionError."""
    org_id = uuid.uuid4()
    fake_income = [
        {"account_code": "6010", "account_name": "Office Rent", "account_type": "EXPENSE", "net_amount": 10000.0},
    ]

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=fake_income))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=[]))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))

    evidence = await gather_financial_evidence(org_id)
    ratios = evidence["financial_ratios"]
    assert ratios["gross_profit_margin"] == 0.0
    assert ratios["net_profit_margin"] == 0.0
    assert ratios["operating_margin"] == 0.0


@pytest.mark.asyncio
async def test_edge_case_zero_expenses_cash_runway(monkeypatch):
    """When operating expenses are zero, monthly burn rate is 0.0 and runway handles zero division safely."""
    org_id = uuid.uuid4()
    fake_income = [
        {"account_code": "4010", "account_name": "Services Revenue", "account_type": "REVENUE", "net_amount": -50000.0},
    ]
    fake_banks = [
        {"id": "b1", "account_name": "Bank", "current_balance": 100000.0},
    ]

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=fake_income))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=[]))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=fake_banks))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))

    evidence = await gather_financial_evidence(org_id)
    runway = evidence["cash_runway"]
    assert runway["monthly_burn_rate"] == 0.0
    assert runway["total_liquid_cash"] == 100000.0
    # No burn rate with positive cash results in safe None (infinite runway) without error
    assert runway["runway_months"] is None
    assert evidence["expense_breakdown"] == []


@pytest.mark.asyncio
async def test_edge_case_zero_liabilities(monkeypatch):
    """When liabilities are zero, Current Ratio and Quick Ratio must handle zero division safely."""
    org_id = uuid.uuid4()
    fake_balance_sheet = [
        {"account_code": "1010", "account_name": "Cash", "account_type": "ASSET", "net_amount": 50000.0},
    ]

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=fake_balance_sheet))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=[]))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))

    evidence = await gather_financial_evidence(org_id)
    wc = evidence["working_capital_metrics"]
    assert wc["working_capital"] == 50000.0
    assert wc["current_ratio"] == 0.0
    assert wc["quick_ratio"] == 0.0
    assert wc["status"] == "Adequate"


# ---------------------------------------------------------------------------
# Empty Database Degradation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_database_graceful_degradation(monkeypatch):
    """Empty views/tables return clean zero defaults and empty lists without raising."""
    org_id = uuid.uuid4()

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=[]))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))

    evidence = await gather_financial_evidence(org_id)

    assert evidence["profit_and_loss"]["revenue"] == 0.0
    assert evidence["profit_and_loss"]["net_profit"] == 0.0
    assert evidence["balance_sheet"]["total_assets"] == 0.0
    assert evidence["balance_sheet"]["total_liabilities"] == 0.0
    assert evidence["cash_flow"]["net_cash_change"] == 0.0
    assert evidence["cash_flow"]["bank_balances"] == []
    assert evidence["cash_flow"]["cash_balances"] == []
    assert evidence["working_capital_metrics"]["working_capital"] == 0.0
    assert evidence["working_capital_metrics"]["current_ratio"] == 0.0
    assert evidence["working_capital_metrics"]["quick_ratio"] == 0.0
    assert evidence["financial_ratios"]["gross_profit_margin"] == 0.0
    assert evidence["financial_ratios"]["return_on_assets"] == 0.0
    assert evidence["aging_summary"]["total_open_receivables"] == 0.0
    assert evidence["aging_summary"]["overdue_receivables"] == 0.0
    assert evidence["expense_breakdown"] == []
    assert evidence["cash_runway"]["monthly_burn_rate"] == 0.0
    assert evidence["cash_runway"]["runway_months"] == 0.0


# ---------------------------------------------------------------------------
# Exception Resilience Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repository_exceptions_handled_gracefully(monkeypatch):
    """When individual repository sources raise exceptions, evidence gathering must degrade gracefully."""
    org_id = uuid.uuid4()

    def _raise(*args, **kwargs):
        raise RuntimeError("Database connection down")

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(side_effect=_raise))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(side_effect=_raise))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(side_effect=_raise))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(side_effect=_raise))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(side_effect=_raise))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(side_effect=_raise))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(side_effect=_raise))

    evidence = await gather_financial_evidence(org_id)
    assert isinstance(evidence, dict)
    assert evidence["profit_and_loss"]["revenue"] == 0.0
    assert evidence["balance_sheet"]["total_assets"] == 0.0


# ---------------------------------------------------------------------------
# Working Capital Status Threshold Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_working_capital_status_thresholds(monkeypatch):
    """Test Adequate (>= 1.5), Tight (1.0 <= ratio < 1.5), Deficit (< 1.0)."""
    org_id = uuid.uuid4()

    async def _run_with_assets_and_liabilities(assets: float, liabilities: float):
        fake_bs = [
            {"account_code": "1010", "account_name": "Bank", "account_type": "ASSET", "net_amount": assets},
            {"account_code": "2010", "account_name": "Accounts Payable", "account_type": "LIABILITY", "net_amount": -liabilities},
        ]
        monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=[]))
        monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=fake_bs))
        monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=[]))
        monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=[]))
        monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
        monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
        monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))

        res = await gather_financial_evidence(org_id)
        return res["working_capital_metrics"]["status"], res["working_capital_metrics"]["current_ratio"]

    # 1. Adequate: ratio = 2.0 (>= 1.5)
    status, ratio = await _run_with_assets_and_liabilities(20000.0, 10000.0)
    assert ratio == 2.0
    assert status == "Adequate"

    # 2. Tight: ratio = 1.2 (1.0 <= ratio < 1.5)
    status, ratio = await _run_with_assets_and_liabilities(12000.0, 10000.0)
    assert ratio == 1.2
    assert status == "Tight"

    # 3. Deficit: ratio = 0.8 (< 1.0)
    status, ratio = await _run_with_assets_and_liabilities(8000.0, 10000.0)
    assert ratio == 0.8
    assert status == "Deficit"


# ---------------------------------------------------------------------------
# Date Filtering and Period Calculations Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_date_filtering_and_runway_period(monkeypatch):
    """Test date filtering on cash flow and multi-month burn rate calculation."""
    org_id = uuid.uuid4()

    fake_income = [
        {"account_code": "6010", "account_name": "Office Rent", "account_type": "EXPENSE", "net_amount": 60000.0},
    ]

    fake_cash_flow = [
        {"cash_flow_category": "OPERATING", "net_amount": 1000.0, "transaction_date": "2026-01-15"},
        {"cash_flow_category": "OPERATING", "net_amount": 5000.0, "transaction_date": "2026-02-15"},
        {"cash_flow_category": "OPERATING", "net_amount": 9000.0, "transaction_date": "2026-05-15"},
    ]

    fake_banks = [
        {"id": "b1", "account_name": "Bank", "current_balance": 60000.0},
    ]

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=fake_income))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=fake_cash_flow))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=fake_banks))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))

    # Period: 3 months (90 days: 2026-01-01 to 2026-03-31)
    evidence = await gather_financial_evidence(
        org_id,
        from_date="2026-01-01",
        to_date="2026-03-31",
    )

    # Only 2 transactions fall within from_date and to_date (1000 and 5000)
    assert evidence["cash_flow"]["operating_cash_flows"] == 6000.0

    # Period months ≈ 90 / 30.4375 ≈ 2.96 months
    # Burn rate = 60,000 / 2.96 ≈ 20,270.27
    runway = evidence["cash_runway"]
    assert runway["monthly_burn_rate"] > 0
    assert runway["runway_months"] is not None
    assert round(runway["total_liquid_cash"] / runway["monthly_burn_rate"], 2) == runway["runway_months"]


# ---------------------------------------------------------------------------
# Fallback and Hierarchy De-duplication Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aging_fallback_to_invoice_and_purchase_repositories(monkeypatch):
    """When aging views return empty, fallback to invoices and purchase bills."""
    org_id = uuid.uuid4()

    fake_invoices = [
        {"status": "ISSUED", "total": 12000.0, "amount_paid": 2000.0},
        {"status": "OVERDUE", "total": 8000.0, "amount_paid": 0.0},
        {"status": "DRAFT", "total": 5000.0, "amount_paid": 0.0},  # should be excluded
    ]

    fake_bills = [
        {"status": "OPEN", "total": 15000.0, "amount_paid": 5000.0},
        {"status": "OVERDUE", "total": 7000.0, "amount_paid": 0.0},
        {"status": "PAID", "total": 10000.0, "amount_paid": 10000.0},  # should be excluded
    ]

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=[]))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(invoice_repository, "list_invoices", AsyncMock(return_value=fake_invoices))
    monkeypatch.setattr(purchase_repository, "list_purchase_bills", AsyncMock(return_value=fake_bills))

    evidence = await gather_financial_evidence(org_id)
    aging = evidence["aging_summary"]

    # Open receivables = (12000 - 2000) + 8000 = 18000.0
    # Overdue receivables = 8000.0
    assert aging["total_open_receivables"] == 18000.0
    assert aging["overdue_receivables"] == 8000.0

    # Open payables = (15000 - 5000) + 7000 = 17000.0
    # Overdue payables = 7000.0
    assert aging["total_open_payables"] == 17000.0
    assert aging["overdue_payables"] == 7000.0


@pytest.mark.asyncio
async def test_balance_sheet_hierarchy_group_filtering(monkeypatch):
    """Grouping accounts with is_group=True must not be double counted with leaf accounts."""
    org_id = uuid.uuid4()

    fake_bs_with_hierarchy = [
        # Group account
        {"account_code": "1000", "account_name": "Current Assets", "account_type": "ASSET", "net_amount": 0.0, "is_group": True, "subtree_balance": 50000.0},
        # Leaf accounts
        {"account_code": "1010", "account_name": "Bank", "account_type": "ASSET", "net_amount": 30000.0, "is_group": False},
        {"account_code": "1020", "account_name": "Cash", "account_type": "ASSET", "net_amount": 20000.0, "is_group": False},
        # Group account
        {"account_code": "2000", "account_name": "Current Liabilities", "account_type": "LIABILITY", "net_amount": 0.0, "is_group": True, "subtree_balance": -15000.0},
        # Leaf account
        {"account_code": "2010", "account_name": "Accounts Payable", "account_type": "LIABILITY", "net_amount": -15000.0, "is_group": False},
    ]

    monkeypatch.setattr(report_repository, "get_income_statement", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_balance_sheet", AsyncMock(return_value=fake_bs_with_hierarchy))
    monkeypatch.setattr(report_repository, "get_cash_flow", AsyncMock(return_value=[]))
    monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank_repository, "list_cash_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_customer_aging", AsyncMock(return_value=[]))
    monkeypatch.setattr(report_repository, "get_supplier_aging", AsyncMock(return_value=[]))

    evidence = await gather_financial_evidence(org_id)
    bs = evidence["balance_sheet"]

    # Assets must be 30k + 20k = 50k (not 100k)
    assert bs["current_assets"] == 50000.0
    assert bs["total_assets"] == 50000.0
    # Liabilities must be 15k (not 30k)
    assert bs["current_liabilities"] == 15000.0
    assert bs["total_liabilities"] == 15000.0
    assert bs["net_assets"] == 35000.0
    assert bs["equity"] == 35000.0

