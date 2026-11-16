"""Unit tests for Pre-Flight Statutory & Tax Compliance Auditor (DOC-ACC-2026-V1 Section 7).

Verifies:
1. Section 73 & Section 21(l) cash limits (PKR 50,000 expense, PKR 250,000 fixed asset).
2. Recommended banking channels (Bank Transfer, Crossed Cheque).
3. Section 153 Withholding Tax (WHT) rates across all statutory categories.
4. Tenth Schedule Non-Filer 2x surcharge rates.
5. Section 159 Exemption certificate handling (0% WHT).
6. Net payable and withholding amount mathematical invariants.
7. Forensic duplicate payment detection (identical invoice ref, temporal amount, near-amount).
8. Cash structuring / smurfing evasion pattern detection.
9. Balanced double-entry suggested journal vouchers.
"""
import pytest

from app.statutory_tax_auditor import (
    preflight_tax_compliance_audit,
    TaxAuditResult,
    SECTION_73_EXPENSE_CASH_LIMIT,
    SECTION_73_ASSET_CASH_LIMIT,
)


# ---------------------------------------------------------------------------
# 1. Section 73 Cash Threshold Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_section_73_cash_expense_exceeding_threshold():
    """Expense paid in CASH exceeding PKR 50,000 triggers statutory disallowance hazard u/s 21(l)."""
    result = await preflight_tax_compliance_audit(
        transaction_type="EXPENSE",
        payment_method="CASH",
        total_amount=75000.0,
        party_info={"name": "Office Mart", "is_filer": True, "is_corporate": False},
        line_items=[{"description": "Office Stationery & Consumables", "amount": 75000.0, "nature": "OPERATING_EXPENSE"}],
        is_fixed_asset=False,
    )

    assert isinstance(result, TaxAuditResult)
    assert result.section_73_compliant is False
    assert result.section_73_threshold == SECTION_73_EXPENSE_CASH_LIMIT
    assert result.section_73_warning is not None
    assert "Section 73(1) & 21(l)" in result.section_73_warning
    assert "PKR 75,000.00" in result.section_73_warning
    assert "Bank Transfer" in result.recommended_banking_channels
    assert "Crossed Cheque" in result.recommended_banking_channels

    # Statutory warning is non-blocking (requires disclosure / user confirmation)
    assert result.blocking is False
    assert result.passed is True
    assert len(result.statutory_warnings) >= 1


@pytest.mark.asyncio
async def test_section_73_cash_expense_within_threshold():
    """Expense paid in CASH <= PKR 50,000 is fully compliant."""
    result = await preflight_tax_compliance_audit(
        transaction_type="EXPENSE",
        payment_method="CASH",
        total_amount=35000.0,
        party_info={"name": "Office Mart", "is_filer": True, "is_corporate": False},
        line_items=[{"description": "Printer Paper & Toners", "amount": 35000.0, "nature": "OPERATING_EXPENSE"}],
        is_fixed_asset=False,
    )

    assert result.section_73_compliant is True
    assert result.section_73_warning is None
    assert result.blocking is False
    assert result.passed is True


@pytest.mark.asyncio
async def test_section_73_cash_fixed_asset_exceeding_threshold():
    """Fixed asset paid in CASH exceeding PKR 250,000 triggers critical statutory violation u/s 73(2)/(3)."""
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE",
        payment_method="CASH",
        total_amount=350000.0,
        party_info={"name": "Dell Pakistan", "is_filer": True, "is_corporate": True},
        line_items=[{"description": "High Performance Server", "amount": 350000.0, "category": "Computer Equipment", "nature": "FIXED_ASSET", "is_fixed_asset": True}],
        is_fixed_asset=True,
    )

    assert result.section_73_compliant is False
    assert result.section_73_threshold == SECTION_73_ASSET_CASH_LIMIT
    assert result.section_73_violation is not None
    assert "Section 73(2) & 73(3)" in result.section_73_violation
    assert "depreciation deductions and initial allowance will be legally disallowed" in result.section_73_violation

    # Capital cash violations are blocking hard stops
    assert result.blocking is True
    assert result.passed is False
    assert len(result.blocking_violations) >= 1


@pytest.mark.asyncio
async def test_section_73_cash_fixed_asset_within_threshold():
    """Fixed asset paid in CASH <= PKR 250,000 is compliant under Section 73(2)."""
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE",
        payment_method="CASH",
        total_amount=120000.0,
        party_info={"name": "Habib Furniture", "is_filer": True, "is_corporate": False},
        line_items=[{"description": "Executive Conference Table", "amount": 120000.0, "category": "Furniture & Fixtures", "nature": "FIXED_ASSET", "is_fixed_asset": True}],
        is_fixed_asset=True,
    )

    assert result.section_73_compliant is True
    assert result.section_73_violation is None
    assert result.blocking is False
    assert result.passed is True


@pytest.mark.asyncio
async def test_section_73_banking_channel_unlimited():
    """Payment via Bank Transfer / Crossed Cheque is compliant regardless of amount."""
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE",
        payment_method="BANK_TRANSFER",
        total_amount=5000000.0,
        party_info={"name": "Enterprise Cloud Services", "is_filer": True, "is_corporate": True},
        line_items=[{"description": "Annual Infrastructure Hosting", "amount": 5000000.0, "category": "Cloud Infrastructure"}],
        is_fixed_asset=False,
    )

    assert result.section_73_compliant is True
    assert result.section_73_warning is None
    assert result.section_73_violation is None
    assert result.blocking is False
    assert result.passed is True


# ---------------------------------------------------------------------------
# 2. Section 153 Withholding Tax (WHT) Rates & Deductions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_section_153_wht_it_services():
    """IT and IT-enabled services: 4.0% WHT for active filer."""
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=100000.0,
        party_info={"name": "DevSolutions Ltd", "is_filer": True, "is_corporate": True},
        line_items=[{"description": "Web Application Development & Cloud Hosting", "amount": 100000.0}],
    )

    assert result.section_153_applicable is True
    assert result.wht_category == "IT_SERVICES"
    assert result.wht_rate_percent == 4.0
    assert result.wht_amount == 4000.0
    assert result.net_payable == 96000.0
    assert result.wht_amount + result.net_payable == 100000.0


@pytest.mark.asyncio
async def test_section_153_wht_professional_services():
    """Independent professional services (legal, audit): 15.0% WHT for active filer."""
    result = await preflight_tax_compliance_audit(
        transaction_type="SUPPLIER_PAYMENT",
        payment_method="BANK_TRANSFER",
        total_amount=200000.0,
        party_info={"name": "Ahmad & Co Advocates", "is_filer": True, "is_corporate": False},
        line_items=[{"description": "Corporate Legal Advisory & Litigation Retainer", "amount": 200000.0}],
    )

    assert result.section_153_applicable is True
    assert result.wht_category == "PROFESSIONAL_SERVICES"
    assert result.wht_rate_percent == 15.0
    assert result.wht_amount == 30000.0
    assert result.net_payable == 170000.0


@pytest.mark.asyncio
async def test_section_153_wht_specified_services():
    """Specified services (freight, courier, cargo, transport): 7.0% WHT."""
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=50000.0,
        party_info={"name": "Speedy Cargo & Freight", "is_filer": True, "is_corporate": True},
        line_items=[{"description": "Inbound Marine Cargo & Freight Delivery", "amount": 50000.0}],
    )

    assert result.section_153_applicable is True
    assert result.wht_category == "SPECIFIED_SERVICES"
    assert result.wht_rate_percent == 7.0
    assert result.wht_amount == 3500.0
    assert result.net_payable == 46500.0


@pytest.mark.asyncio
async def test_section_153_wht_goods_corporate_vs_individual():
    """Supply of goods: 5.0% for corporate vendor, 5.5% for individual/AOP vendor."""
    # Corporate Vendor: 5.0%
    res_corp = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=100000.0,
        party_info={"name": "Tech Corp Pvt Ltd", "is_filer": True, "is_corporate": True},
        line_items=[{"description": "Computer Hardware & Peripheral Supplies", "amount": 100000.0}],
    )
    assert res_corp.wht_category == "GOODS_CORP"
    assert res_corp.wht_rate_percent == 5.0
    assert res_corp.wht_amount == 5000.0
    assert res_corp.net_payable == 95000.0

    # Individual / Sole Proprietor: 5.5%
    res_ind = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=100000.0,
        party_info={"name": "Usman Electronics", "is_filer": True, "is_corporate": False},
        line_items=[{"description": "Computer Hardware & Peripheral Supplies", "amount": 100000.0}],
    )
    assert res_ind.wht_category == "GOODS_INDIVIDUAL"
    assert res_ind.wht_rate_percent == 5.5
    assert res_ind.wht_amount == 5500.0
    assert res_ind.net_payable == 94500.0


@pytest.mark.asyncio
async def test_section_153_wht_contracts():
    """Execution of contracts: 7.5% corporate / 8.0% individual."""
    res_contract = await preflight_tax_compliance_audit(
        transaction_type="CONTRACT",
        payment_method="BANK_TRANSFER",
        total_amount=500000.0,
        party_info={"name": "BuildWell Engineering", "is_filer": True, "is_corporate": True},
        line_items=[{"description": "Office Turnkey Civil Work Contract", "amount": 500000.0}],
    )
    assert res_contract.wht_category == "CONTRACTS_CORP"
    assert res_contract.wht_rate_percent == 7.5
    assert res_contract.wht_amount == 37500.0
    assert res_contract.net_payable == 462500.0


@pytest.mark.asyncio
async def test_section_153_tenth_schedule_non_filer_double_rate():
    """Non-filer / Inactive taxpayer invokes Tenth Schedule 2x statutory rate penalty."""
    # Professional services: 15% * 2 = 30%
    result = await preflight_tax_compliance_audit(
        transaction_type="SUPPLIER_PAYMENT",
        payment_method="BANK_TRANSFER",
        total_amount=100000.0,
        party_info={"name": "Tariq Tax Advisory", "is_filer": False, "is_corporate": False},
        line_items=[{"description": "Tax Consultancy Retainer", "amount": 100000.0}],
    )

    assert result.is_non_filer_surcharge_applied is True
    assert result.wht_rate_percent == 30.0  # 15.0 * 2
    assert result.wht_amount == 30000.0
    assert result.net_payable == 70000.0
    assert any("TENTH_SCHEDULE_NON_FILER" in flag for flag in result.audit_flags)


@pytest.mark.asyncio
async def test_section_159_exemption_certificate():
    """Vendor with valid Section 159 Exemption Certificate: 0% WHT applies."""
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=250000.0,
        party_info={"name": "Exempted Vendor Pvt Ltd", "has_exemption_cert": True, "is_filer": True, "is_corporate": True},
        line_items=[{"description": "IT Consulting Services", "amount": 250000.0}],
    )

    assert result.wht_category == "EXEMPT_SECTION_159"
    assert result.wht_rate_percent == 0.0
    assert result.wht_amount == 0.0
    assert result.net_payable == 250000.0
    assert result.wht_status == "EXEMPT_CERTIFICATE"


# ---------------------------------------------------------------------------
# 3. Duplicate Payment & Fraud Detection Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_invoice_number_hard_block():
    """Vector 1: Identical supplier invoice reference triggers CRITICAL blocking stop."""
    recent_txs = [
        {
            "supplier_id": "VEND-001",
            "supplier_name": "Mega Supplies",
            "supplier_invoice_ref": "INV-2026-887",
            "amount": 125000.0,
        }
    ]

    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=125000.0,
        party_info={"id": "VEND-001", "name": "Mega Supplies", "supplier_invoice_ref": "INV-2026-887", "is_filer": True},
        line_items=[{"description": "Office Supplies", "amount": 125000.0}],
        recent_transactions=recent_txs,
    )

    assert result.is_duplicate_risk is True
    assert result.duplicate_risk_severity == "CRITICAL"
    assert result.blocking is True
    assert result.passed is False
    assert "DUPLICATE INVOICE DETECTED" in result.duplicate_reason
    assert "INV-2026-887" in result.duplicate_reason


@pytest.mark.asyncio
async def test_duplicate_temporal_amount_proximity_warning():
    """Vector 2: Identical net amount to same vendor within recent window triggers HIGH risk warning."""
    recent_txs = [
        {
            "supplier_name": "Mega Supplies",
            "supplier_invoice_ref": "INV-2026-100",
            "amount": 75000.0,
        }
    ]

    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=75000.0,
        party_info={"name": "Mega Supplies", "supplier_invoice_ref": "INV-2026-101", "is_filer": True},
        line_items=[{"description": "Office Supplies", "amount": 75000.0}],
        recent_transactions=recent_txs,
    )

    assert result.is_duplicate_risk is True
    assert result.duplicate_risk_severity == "HIGH"
    assert result.blocking is False  # Warning, not hard stop (different invoice ref)
    assert result.passed is True
    assert "POTENTIAL DUPLICATE PAYMENT" in result.duplicate_reason


@pytest.mark.asyncio
async def test_duplicate_near_amount_anomaly():
    """Vector 3: Near-amount disbursement within ±2% triggers MEDIUM risk audit flag."""
    recent_txs = [
        {
            "supplier_name": "Acme Contractors",
            "amount": 100000.0,
        }
    ]

    # Current amount 101,000 is within 1% of 100,000
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=101000.0,
        party_info={"name": "Acme Contractors", "is_filer": True},
        line_items=[{"description": "Maintenance Work", "amount": 101000.0}],
        recent_transactions=recent_txs,
    )

    assert result.is_duplicate_risk is True
    assert result.duplicate_risk_severity == "MEDIUM"
    assert any("NEAR-AMOUNT PAYMENT ANOMALY" in flag for flag in result.audit_flags)


@pytest.mark.asyncio
async def test_section_73_cash_structuring_hazard():
    """Vector 4: Multiple cash payments near PKR 50,000 threshold trigger structuring hazard flag."""
    recent_txs = [
        {
            "supplier_name": "Subcontractor",
            "payment_method": "CASH",
            "amount": 48000.0,
        }
    ]

    result = await preflight_tax_compliance_audit(
        transaction_type="EXPENSE",
        payment_method="CASH",
        total_amount=47000.0,
        party_info={"name": "Subcontractor", "is_filer": True},
        line_items=[{"description": "Site Labour Charges", "amount": 47000.0}],
        recent_transactions=recent_txs,
    )

    assert any("SECTION_73_STRUCTURING_HAZARD" in flag for flag in result.audit_flags)


# ---------------------------------------------------------------------------
# 4. Double-Entry Invariant Verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suggested_journal_lines_balance_invariant():
    """Verify that suggested journal lines maintain strict double-entry balance: sum(Dr) == sum(Cr)."""
    result = await preflight_tax_compliance_audit(
        transaction_type="PURCHASE_BILL",
        payment_method="BANK_TRANSFER",
        total_amount=200000.0,
        party_info={"name": "Legal Counsel", "is_filer": True, "is_corporate": False},
        line_items=[{"description": "Legal Services", "amount": 200000.0}],
    )

    lines = result.suggested_journal_lines
    assert lines is not None
    assert len(lines) == 3

    total_dr = sum(line["debit"] for line in lines)
    total_cr = sum(line["credit"] for line in lines)

    assert total_dr == 200000.0
    assert total_cr == 200000.0
    assert total_dr == total_cr
