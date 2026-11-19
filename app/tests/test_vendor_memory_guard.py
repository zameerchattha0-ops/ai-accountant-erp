"""Unit tests for Episodic Memory & Proactive Vendor Fingerprinting Guard (DOC-CFO-2026-FRONTIER-V1 Section 2.3).

Verifies:
1. Historical Vendor Term Fingerprinting:
   - Identify customary settlement method (CASH vs BANK vs CREDIT) and confidence score.
   - Detect standard bank name (e.g. Meezan Bank, HBL) and account details.
   - Extract typical Tier-4 analytical expense/asset account (e.g. 5100 Office Supplies).
   - Evaluate Section 153 Withholding Tax (WHT) rates and categories.
   - Enforce Active Taxpayer List (ATL) 30-day verification TTL under Tenth Schedule (CFO Mandate Q3.2).
   - Generate natural, personalized chat suggestion prompts:
     "For Apex Supplies, you usually pay via Meezan Bank with 5% WHT deducted. Shall I use these terms?"
2. Proactive Duplicate Transaction & Invoice Guard:
   - Vector 1: Identical supplier invoice reference match (Hard stop / CRITICAL).
   - Vector 2: Exact net amount & vendor collision within 72-hour window (HIGH).
   - Vector 3: Legitimate recurring subscription & utility disambiguation (CFO Mandate Q3.1).
   - Vector 4: Section 73 & Section 21(l) cash structuring / smurfing evasion detection (CFO Mandate Q3.3).
   - Vector 5: Near-amount payment anomaly detection within ±2%.
   - Clean / non-duplicate transaction clearance (NONE).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.vendor_memory_guard import (
    DuplicateDetectionVector,
    DuplicateRiskLevel,
    DuplicateScanResult,
    VendorFingerprint,
    VendorMemoryGuard,
    VendorWhtTreatment,
    check_duplicate_risk,
    lookup_vendor_fingerprint,
    normalize_vendor_key,
)


# ---------------------------------------------------------------------------
# Test Fixtures & Sample Historical Records
# ---------------------------------------------------------------------------

@pytest.fixture
def apex_supplies_history():
    """Historical records for Apex Supplies: typically paid via Meezan Bank with 5% WHT."""
    return [
        {
            "id": "tx_apex_01",
            "vendor_name": "Apex Supplies Pvt Ltd",
            "amount": 120000.0,
            "payment_method": "BANK",
            "bank_name": "Meezan Bank",
            "bank_account": "PK12MEZN00012345678901",
            "account_code": "5100",
            "account_name": "Office Supplies Expense",
            "wht_rate": 5.0,
            "wht_section": "153(1)(a)",
            "wht_category": "GOODS",
            "atl_status": "ACTIVE",
            "atl_last_verified_at": "2026-11-01T10:00:00Z",
            "created_at": "2026-11-01T10:00:00Z",
        },
        {
            "id": "tx_apex_02",
            "vendor_name": "Apex Supplies",
            "amount": 85000.0,
            "payment_method": "BANK",
            "bank_name": "Meezan Bank",
            "bank_account": "PK12MEZN00012345678901",
            "account_code": "5100",
            "account_name": "Office Supplies Expense",
            "wht_rate": 5.0,
            "wht_section": "153(1)(a)",
            "wht_category": "GOODS",
            "atl_status": "ACTIVE",
            "atl_last_verified_at": "2026-11-05T12:00:00Z",
            "created_at": "2026-11-05T12:00:00Z",
        },
        {
            "id": "tx_apex_03",
            "vendor_name": "Apex Supplies Ltd",
            "amount": 95000.0,
            "payment_method": "BANK",
            "bank_name": "Meezan Bank",
            "account_code": "5100",
            "account_name": "Office Supplies Expense",
            "wht_rate": 5.0,
            "atl_status": "ACTIVE",
            "atl_last_verified_at": "2026-11-10T09:30:00Z",
            "created_at": "2026-11-10T09:30:00Z",
        },
    ]


@pytest.fixture
def petty_vendor_cash_history():
    """Historical records for Local Courier Services paid in cash."""
    return [
        {
            "id": "tx_courier_01",
            "vendor_name": "Speedy Courier Services",
            "amount": 8000.0,
            "payment_method": "CASH",
            "account_code": "5120",
            "account_name": "Postage & Courier Expense",
            "wht_rate": 0.0,
            "created_at": "2026-10-15T09:00:00Z",
        },
        {
            "id": "tx_courier_02",
            "vendor_name": "Speedy Courier Services",
            "amount": 12000.0,
            "payment_method": "CASH",
            "account_code": "5120",
            "account_name": "Postage & Courier Expense",
            "wht_rate": 0.0,
            "created_at": "2026-10-25T11:00:00Z",
        },
    ]


# ---------------------------------------------------------------------------
# 1. Historical Vendor Term Fingerprinting Tests
# ---------------------------------------------------------------------------

def test_lookup_vendor_fingerprint_apex_supplies(apex_supplies_history):
    """Test standard historical defaults extraction for Apex Supplies."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    fingerprint = lookup_vendor_fingerprint("Apex Supplies", apex_supplies_history, as_of_date=ref_date)

    assert fingerprint is not None
    assert fingerprint.vendor_name == "Apex Supplies"
    assert fingerprint.customary_payment_method == "BANK"
    assert fingerprint.standard_bank_name == "Meezan Bank"
    assert fingerprint.standard_bank_account == "PK12MEZN00012345678901"
    assert fingerprint.typical_account_code == "5100"
    assert fingerprint.typical_account_name == "Office Supplies Expense"
    assert fingerprint.wht_treatment.wht_applicable is True
    assert fingerprint.wht_treatment.standard_wht_rate == 5.0
    assert fingerprint.wht_treatment.wht_section == "153(1)(a)"
    assert fingerprint.total_transactions_analyzed == 3
    assert fingerprint.total_spend == 300000.0


def test_suggest_terms_prompt_apex_supplies(apex_supplies_history):
    """Verifies the exact chat prompt generation required by Task 3:

    'For Apex Supplies, you usually pay via Meezan Bank with 5% WHT deducted. Shall I use these terms?'
    """
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    fingerprint = lookup_vendor_fingerprint("Apex Supplies", apex_supplies_history, as_of_date=ref_date)
    assert fingerprint is not None

    prompt = fingerprint.suggest_terms_prompt()
    expected = "For Apex Supplies, you usually pay via Meezan Bank with 5% WHT deducted. Shall I use these terms?"
    assert prompt == expected


def test_suggest_terms_prompt_with_account_code(apex_supplies_history):
    """Verifies prompt with optional analytical ledger account code included."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    fingerprint = lookup_vendor_fingerprint("Apex Supplies", apex_supplies_history, as_of_date=ref_date)
    assert fingerprint is not None

    prompt = fingerprint.suggest_terms_prompt(include_account=True)
    expected = (
        "For Apex Supplies, you usually pay via Meezan Bank with 5% WHT deducted "
        "(allocated to 5100 - Office Supplies Expense). Shall I use these terms?"
    )
    assert prompt == expected


def test_suggest_terms_prompt_cash_method(petty_vendor_cash_history):
    """Verifies prompt phrasing for vendors settled in cash."""
    fingerprint = lookup_vendor_fingerprint("Speedy Courier Services", petty_vendor_cash_history)
    assert fingerprint is not None
    assert fingerprint.customary_payment_method == "CASH"

    prompt = fingerprint.suggest_terms_prompt()
    expected = "For Speedy Courier Services, you usually pay in Cash. Shall I use these terms?"
    assert prompt == expected


def test_lookup_vendor_fingerprint_unknown_vendor(apex_supplies_history):
    """Querying an unknown vendor with no transaction history returns None."""
    fingerprint = lookup_vendor_fingerprint("Unknown Delta Corp", apex_supplies_history)
    assert fingerprint is None


# ---------------------------------------------------------------------------
# 2. Dynamic ATL Freshness & 30-Day TTL Tests (CFO Mandate Q3.2)
# ---------------------------------------------------------------------------

def test_atl_freshness_within_30_days():
    """ATL verified 10 days ago is fresh (is_atl_stale == False)."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    records = [
        {
            "vendor_name": "Vertex Technologies",
            "amount": 50000.0,
            "payment_method": "BANK",
            "bank_name": "HBL",
            "wht_rate": 4.0,
            "atl_status": "ACTIVE",
            "atl_last_verified_at": "2026-11-08T10:00:00Z",  # 10 days before ref_date
        }
    ]
    fingerprint = lookup_vendor_fingerprint("Vertex Technologies", records, atl_ttl_days=30, as_of_date=ref_date)
    assert fingerprint is not None
    assert fingerprint.wht_treatment.is_atl_stale is False
    assert fingerprint.wht_treatment.atl_warning is None


def test_atl_freshness_expired_over_30_days():
    """ATL verified 45 days ago triggers stale status and statutory double WHT warning."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    records = [
        {
            "vendor_name": "Vertex Technologies",
            "amount": 50000.0,
            "payment_method": "BANK",
            "bank_name": "HBL",
            "wht_rate": 4.0,
            "atl_status": "ACTIVE",
            "atl_last_verified_at": "2026-10-01T10:00:00Z",  # 48 days before ref_date
        }
    ]
    fingerprint = lookup_vendor_fingerprint("Vertex Technologies", records, atl_ttl_days=30, as_of_date=ref_date)
    assert fingerprint is not None
    assert fingerprint.wht_treatment.is_atl_stale is True
    assert fingerprint.wht_treatment.atl_warning is not None
    assert "Active Taxpayer List (ATL) verification is 48 days old" in fingerprint.wht_treatment.atl_warning
    assert "Double WHT" in fingerprint.wht_treatment.atl_warning

    # Suggest prompt with ATL warning enabled
    prompt = fingerprint.suggest_terms_prompt(include_atl_warning=True)
    assert "Double WHT" in prompt


def test_atl_freshness_missing_timestamp():
    """Missing verification timestamp in history defaults to is_atl_stale == True."""
    records = [
        {
            "vendor_name": "Alpha Builders",
            "amount": 250000.0,
            "payment_method": "BANK",
            "bank_name": "Standard Chartered",
            "wht_rate": 7.5,
            "atl_status": "ACTIVE",
            # No atl_last_verified_at provided
        }
    ]
    fingerprint = lookup_vendor_fingerprint("Alpha Builders", records, atl_ttl_days=30)
    assert fingerprint is not None
    assert fingerprint.wht_treatment.is_atl_stale is True
    assert "No verified Active Taxpayer List (ATL) timestamp" in fingerprint.wht_treatment.atl_warning


# ---------------------------------------------------------------------------
# 3. Duplicate Transaction & Invoice Guard Tests
# ---------------------------------------------------------------------------

def test_duplicate_invoice_reference_match():
    """Vector 1: Identical invoice reference from the same vendor is a CRITICAL hard block."""
    recent_txs = [
        {
            "id": "bill_101",
            "vendor_name": "Apex Supplies",
            "supplier_invoice_ref": "INV-2026-0042",
            "amount": 50000.0,
            "created_at": "2026-11-17T10:00:00Z",
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="Apex Supplies",
        amount=50000.0,
        invoice_ref="INV-2026-0042",
        recent_transactions=recent_txs,
    )

    assert scan.risk_level in (DuplicateRiskLevel.CRITICAL, DuplicateRiskLevel.HIGH)
    assert scan.is_duplicate is True
    assert scan.detection_vector == DuplicateDetectionVector.INVOICE_REF_MATCH
    assert "bill_101" in scan.matched_transaction_ids
    assert "DUPLICATE INVOICE DETECTED" in scan.warning_message
    assert "INV-2026-0042" in scan.warning_message


def test_duplicate_exact_amount_within_72_hours():
    """Vector 2: Identical amount and vendor within 72 hours triggers HIGH duplicate risk."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "bill_102",
            "vendor_name": "Apex Supplies",
            "supplier_invoice_ref": "INV-OLD",
            "amount": 75000.0,
            "created_at": "2026-11-17T15:00:00Z",  # 21 hours ago
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="Apex Supplies",
        amount=75000.0,
        invoice_ref="INV-NEW",  # Different invoice ref
        recent_transactions=recent_txs,
        window_hours=72,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.HIGH
    assert scan.is_duplicate is True
    assert scan.detection_vector == DuplicateDetectionVector.IDENTICAL_AMOUNT_WINDOW
    assert "bill_102" in scan.matched_transaction_ids
    assert "POTENTIAL ACCIDENTAL DUPLICATE" in scan.warning_message
    assert "PKR 75,000.00" in scan.warning_message


def test_duplicate_exact_amount_outside_window():
    """Identical amount for same vendor outside the 72-hour window is cleared (NONE)."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "bill_103",
            "vendor_name": "Apex Supplies",
            "amount": 75000.0,
            "created_at": "2026-11-10T12:00:00Z",  # 8 days (192 hours) ago
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="Apex Supplies",
        amount=75000.0,
        invoice_ref="INV-DIFFERENT",
        recent_transactions=recent_txs,
        window_hours=72,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.NONE
    assert scan.is_duplicate is False


# ---------------------------------------------------------------------------
# 4. Recurring Subscription Disambiguation Tests (CFO Mandate Q3.1)
# ---------------------------------------------------------------------------

def test_recurring_monthly_bill_different_billing_periods():
    """Q3.1: Genuine recurring subscription (e.g. broadband or rent) with different billing period

    (e.g. 'April 2026' vs 'March 2026') is recognized as legitimate (LOW risk, not blocked).
    """
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "tx_stormfiber_march",
            "vendor_name": "StormFiber Internet",
            "amount": 25000.0,
            "billing_period": "March 2026",
            "is_recurring": True,
            "created_at": "2026-10-15T10:00:00Z",
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="StormFiber Internet",
        amount=25000.0,
        invoice_ref="INV-SF-APRIL",
        billing_period="April 2026",
        recent_transactions=recent_txs,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.LOW
    assert scan.is_duplicate is False
    assert scan.is_legitimate_recurring is True
    assert scan.detection_vector == DuplicateDetectionVector.RECURRING_PERIODIC_CONFIRMED
    assert "Legitimate recurring periodic payment detected" in scan.warning_message
    assert "April 2026" in scan.warning_message
    assert "March 2026" in scan.warning_message


def test_recurring_monthly_bill_same_billing_period_accidental_double():
    """Q3.1: Recurring bill with the SAME billing period (accidental double payment of April rent)

    is flagged as a HIGH duplicate risk!
    """
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "tx_rent_apr_01",
            "vendor_name": "Commercial Plaza Landlord",
            "amount": 150000.0,
            "billing_period": "April 2026",
            "is_recurring": True,
            "created_at": "2026-11-16T10:00:00Z",  # Processed 2 days ago
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="Commercial Plaza Landlord",
        amount=150000.0,
        billing_period="April 2026",
        recent_transactions=recent_txs,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.HIGH
    assert scan.is_duplicate is True
    assert scan.is_legitimate_recurring is False
    assert "DUPLICATE RECURRING BILL DETECTED" in scan.warning_message
    assert "April 2026" in scan.warning_message


def test_recurring_cycle_approx_30_days_apart():
    """Utility bill (e.g. K-Electric) arriving 30 days after prior bill is recognized as periodic cycle."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "tx_ke_oct",
            "vendor_name": "K-Electric",
            "amount": 85000.0,
            "created_at": "2026-10-19T10:00:00Z",  # Exactly 30 days prior
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="K-Electric",
        amount=85000.0,
        recent_transactions=recent_txs,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.LOW
    assert scan.is_duplicate is False
    assert scan.is_legitimate_recurring is True
    assert scan.detection_vector == DuplicateDetectionVector.RECURRING_PERIODIC_CONFIRMED
    assert "Legitimate recurring periodic cycle detected" in scan.warning_message


# ---------------------------------------------------------------------------
# 5. Section 73 Cash Structuring / Smurfing Evasion Tests (CFO Mandate Q3.3)
# ---------------------------------------------------------------------------

def test_cash_structuring_evasion_detected():
    """Q3.3: Two cash payments of PKR 48,000 and PKR 46,000 within 72 hours breach

    the Section 73 PKR 50,000 threshold cumulatively (PKR 94,000).
    """
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "tx_cash_prior_01",
            "vendor_name": "Prime Hardware",
            "amount": 48000.0,
            "payment_method": "CASH",
            "created_at": "2026-11-17T10:00:00Z",  # 26 hours ago
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="Prime Hardware",
        amount=46000.0,  # Second payment under 50k
        payment_method="CASH",
        recent_transactions=recent_txs,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.HIGH
    assert scan.is_structuring_detected is True
    assert scan.cumulative_cash_amount == 94000.0
    assert scan.detection_vector == DuplicateDetectionVector.CASH_STRUCTURING_HAZARD
    assert "tx_cash_prior_01" in scan.matched_transaction_ids
    assert "STATUTORY STRUCTURING HAZARD" in scan.warning_message
    assert "Section 73 & Section 21(l)" in scan.warning_message
    assert "PKR 94,000.00" in scan.warning_message


def test_cash_without_structuring_below_50k():
    """Single cash payment below PKR 50,000 with no prior transactions does not trigger structuring."""
    scan = check_duplicate_risk(
        vendor_name="Office Stationery Shop",
        amount=15000.0,
        payment_method="CASH",
        recent_transactions=[],
    )

    assert scan.risk_level == DuplicateRiskLevel.NONE
    assert scan.is_structuring_detected is False


def test_bank_transfers_do_not_trigger_cash_structuring():
    """Multiple bank transfers exceeding PKR 50,000 do not trigger cash structuring."""
    recent_txs = [
        {
            "id": "tx_bank_01",
            "vendor_name": "Steel Suppliers",
            "amount": 48000.0,
            "payment_method": "BANK",
            "created_at": "2026-11-17T10:00:00Z",
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="Steel Suppliers",
        amount=46000.0,
        payment_method="BANK",
        recent_transactions=recent_txs,
    )

    # Different amounts (46k vs 48k) via bank -> No risk
    assert scan.risk_level == DuplicateRiskLevel.NONE
    assert scan.is_structuring_detected is False


# ---------------------------------------------------------------------------
# 6. Near-Amount Payment Anomaly Tests (Vector 5)
# ---------------------------------------------------------------------------

def test_near_amount_anomaly_detection():
    """Payment of PKR 99,000 within 2% of recent PKR 100,000 payment triggers LOW risk anomaly."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "tx_near_prior",
            "vendor_name": "Equipment Corp",
            "amount": 100000.0,
            "created_at": "2026-11-17T12:00:00Z",  # 24 hours ago
        }
    ]

    scan = check_duplicate_risk(
        vendor_name="Equipment Corp",
        amount=99000.0,  # 1% difference
        recent_transactions=recent_txs,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.LOW
    assert scan.is_duplicate is False
    assert scan.detection_vector == DuplicateDetectionVector.NEAR_AMOUNT_ANOMALY
    assert "NEAR-AMOUNT PAYMENT ANOMALY" in scan.warning_message
    assert "tx_near_prior" in scan.matched_transaction_ids


# ---------------------------------------------------------------------------
# 7. Dependency Injection & Clean Class API
# ---------------------------------------------------------------------------

def test_vendor_memory_guard_class_injection(apex_supplies_history):
    """Verifies VendorMemoryGuard instance configuration and custom parameters."""
    guard = VendorMemoryGuard(
        atl_ttl_days=15,
        duplicate_window_hours=48,
        structuring_cash_limit=50000.0,
        near_amount_tolerance=0.03,
    )

    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    fp = guard.lookup_vendor_fingerprint("Apex Supplies", apex_supplies_history, as_of_date=ref_date)
    assert fp is not None
    assert fp.wht_treatment.atl_ttl_days == 15

    # 10 Nov to 18 Nov is 8 days <= 15 days -> fresh
    assert fp.wht_treatment.is_atl_stale is False


# ---------------------------------------------------------------------------
# 8. Forensic Edge Cases & Extended Invariants
# ---------------------------------------------------------------------------

def test_multi_step_cash_structuring_three_payments():
    """Structuring detected across three small cash disbursements exceeding PKR 50,000."""
    ref_date = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    recent_txs = [
        {
            "id": "tx_cash_1",
            "vendor_name": "Apex Supplies",
            "amount": 15000.0,
            "payment_method": "CASH",
            "created_at": "2026-11-17T08:00:00Z",  # 28 hrs ago
        },
        {
            "id": "tx_cash_2",
            "vendor_name": "Apex Supplies",
            "amount": 20000.0,
            "payment_method": "CASH",
            "created_at": "2026-11-17T16:00:00Z",  # 20 hrs ago
        },
    ]

    scan = check_duplicate_risk(
        vendor_name="Apex Supplies",
        amount=18000.0,  # 15k + 20k + 18k = 53,000.0 >= 50,000.0
        payment_method="CASH",
        recent_transactions=recent_txs,
        reference_date=ref_date,
    )

    assert scan.risk_level == DuplicateRiskLevel.HIGH
    assert scan.is_structuring_detected is True
    assert scan.cumulative_cash_amount == 53000.0
    assert "tx_cash_1" in scan.matched_transaction_ids
    assert "tx_cash_2" in scan.matched_transaction_ids


def test_vendor_name_normalization_resilience():
    """Ensures corporate suffixes, punctuation, and case differences match seamlessly."""
    assert normalize_vendor_key("Apex Supplies (Pvt) Ltd.") == normalize_vendor_key("Apex Supplies")
    assert normalize_vendor_key("Al-Areesh Engineering Inc.") == normalize_vendor_key("Alareesh Engineering")

    records = [
        {
            "vendor_name": "Apex-Supplies (Pvt) Ltd.",
            "amount": 50000.0,
            "payment_method": "BANK",
            "bank_name": "Meezan Bank",
            "wht_rate": 5.0,
        }
    ]
    fp = lookup_vendor_fingerprint("Apex Supplies", records)
    assert fp is not None
    assert fp.standard_bank_name == "Meezan Bank"


def test_nested_journal_lines_account_resolution():
    """Extracts analytical account code from nested journal lines preview."""
    records = [
        {
            "vendor_name": "Dell Technologies",
            "amount": 350000.0,
            "payment_method": "BANK",
            "bank_name": "Standard Chartered",
            "lines": [
                {"account_code": "1510", "account_name": "Computer & IT Equipment", "debit": 350000.0, "credit": 0.0},
                {"account_code": "1020", "account_name": "Bank Balances", "debit": 0.0, "credit": 350000.0},
            ],
        }
    ]
    fp = lookup_vendor_fingerprint("Dell Technologies", records)
    assert fp is not None
    assert fp.typical_account_code == "1510"
    assert fp.typical_account_name == "Computer & IT Equipment"


def test_credit_payment_terms_prompt_generation():
    """Generates proper conversational terms for credit/payable vendor."""
    records = [
        {
            "vendor_name": "Global Raw Materials",
            "amount": 500000.0,
            "payment_method": "CREDIT",
            "payment_terms": "Net 30 Days",
            "wht_rate": 5.0,
        }
    ]
    fp = lookup_vendor_fingerprint("Global Raw Materials", records)
    assert fp is not None
    assert fp.customary_payment_method == "CREDIT"
    prompt = fp.suggest_terms_prompt()
    assert "on Net 30 Days with 5% WHT deducted" in prompt


def test_pydantic_v2_serialization():
    """Verifies that all models serialize cleanly to JSON-compatible dictionaries."""
    result = DuplicateScanResult(
        risk_level=DuplicateRiskLevel.HIGH,
        is_duplicate=True,
        warning_message="Duplicate test",
        matched_transaction_ids=["tx_01"],
        detection_vector=DuplicateDetectionVector.IDENTICAL_AMOUNT_WINDOW,
    )
    dumped = result.model_dump()
    assert dumped["risk_level"] == "HIGH"
    assert dumped["is_duplicate"] is True
    assert dumped["matched_transaction_ids"] == ["tx_01"]

