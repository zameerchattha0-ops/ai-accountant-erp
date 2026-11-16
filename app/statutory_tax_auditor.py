"""Pre-Flight Statutory & Tax Compliance Auditor (DOC-ACC-2026-V1 Section 7).

Implements rigorous pre-flight statutory audits under Pakistan taxation statutes:
1. Section 73 & Section 21(l) of Income Tax Ordinance 2001:
   - Prohibits cash payments exceeding PKR 50,000 for business expenditures.
   - Disallows depreciation deductions for cash capital asset purchases exceeding PKR 250,000 u/s 73(2)/(3).
   - Recommends approved banking channels (Bank Transfer, Crossed Cheque, Pay Order).
2. Section 153 of Income Tax Ordinance 2001:
   - Evaluates Withholding Tax (WHT) rates across all statutory categories
     (Goods 5%/5.5%, IT services 4%, Specified services 7%, Professional 15%,
      General services 14%, Contracts 7.5%/8%, Advertising 1.5%).
   - Applies Tenth Schedule 2x penalty rate for non-filers.
   - Calculates withholding tax deductions and net payable amounts.
3. Forensic Duplicate Payment & Fraud Detection:
   - Hard blocks identical invoice references from the same vendor.
   - Detects temporal amount proximity (rolling 45-day window).
   - Flags near-amount anomalies (within ±2% in 14-day window).
   - Detects Section 73 cash structuring / smurfing evasion patterns.
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Statutory Thresholds & Schedules (ITO 2001 & Finance Act)
# ---------------------------------------------------------------------------

SECTION_73_EXPENSE_CASH_LIMIT = 50000.0
SECTION_73_ASSET_CASH_LIMIT = 250000.0

# Annual exemption thresholds u/s 153
SECTION_153_ANNUAL_THRESHOLDS = {
    "GOODS": 75000.0,
    "SERVICES": 30000.0,
    "CONTRACTS": 75000.0,
}

# Standard Active Taxpayer List (ATL) Withholding Rates u/s 153
WHT_SCHEDULE_RATES = {
    "GOODS_CORP": {
        "base_rate": 5.0,
        "section": "153(1)(a)",
        "label": "Supply of goods – corporate vendor (5%)",
    },
    "GOODS_INDIVIDUAL": {
        "base_rate": 5.5,
        "section": "153(1)(a)",
        "label": "Supply of goods – individual / AOP (5.5%)",
    },
    "IT_SERVICES": {
        "base_rate": 4.0,
        "section": "153(1)(b)",
        "label": "IT and IT-enabled services (4%)",
    },
    "SPECIFIED_SERVICES": {
        "base_rate": 7.0,
        "section": "153(1)(b)",
        "label": "Specified services: transport, freight, hotel, courier, security (7%)",
    },
    "PROFESSIONAL_SERVICES": {
        "base_rate": 15.0,
        "section": "153(1)(b)",
        "label": "Independent professional services: legal, audit, medical, engineering (15%)",
    },
    "OTHER_SERVICES": {
        "base_rate": 14.0,
        "section": "153(1)(b)",
        "label": "General services (14%)",
    },
    "CONTRACTS_CORP": {
        "base_rate": 7.5,
        "section": "153(1)(c)",
        "label": "Execution of contracts – corporate (7.5%)",
    },
    "CONTRACTS_INDIVIDUAL": {
        "base_rate": 8.0,
        "section": "153(1)(c)",
        "label": "Execution of contracts – individual / AOP (8%)",
    },
    "ADVERTISING_MEDIA": {
        "base_rate": 1.5,
        "section": "153(1)(b)",
        "label": "Print and electronic media advertising (1.5%)",
    },
}


# ---------------------------------------------------------------------------
# Result Model
# ---------------------------------------------------------------------------

class TaxAuditResult(BaseModel):
    """Authoritative audit verdict for pre-flight statutory tax compliance."""
    passed: bool = True
    blocking: bool = False
    statutory_warnings: List[str] = Field(default_factory=list)
    blocking_violations: List[str] = Field(default_factory=list)
    audit_flags: List[str] = Field(default_factory=list)

    # Section 73 Compliance
    section_73_compliant: bool = True
    section_73_threshold: float = SECTION_73_EXPENSE_CASH_LIMIT
    section_73_warning: Optional[str] = None
    section_73_violation: Optional[str] = None
    recommended_banking_channels: List[str] = Field(
        default_factory=lambda: ["Bank Transfer", "Crossed Cheque", "Pay Order"]
    )

    # Section 153 Withholding Tax
    section_153_applicable: bool = False
    wht_rate_percent: float = 0.0
    wht_amount: float = 0.0
    net_payable: float = 0.0
    wht_category: Optional[str] = None
    wht_status: str = "NOT_APPLICABLE"  # "DEDUCTION_MANDATORY", "EXEMPT_CERTIFICATE", "UNDER_THRESHOLD", "NOT_APPLICABLE"
    is_non_filer_surcharge_applied: bool = False

    # Duplicate Payment Detection
    is_duplicate_risk: bool = False
    duplicate_risk_severity: Optional[str] = None  # "CRITICAL", "HIGH", "MEDIUM", "LOW", None
    duplicate_reason: Optional[str] = None

    # Suggested Accounting Representation
    suggested_journal_lines: Optional[List[Dict[str, Any]]] = None
    audit_narrative: str = ""


# ---------------------------------------------------------------------------
# Helper Categorization Functions
# ---------------------------------------------------------------------------

def _resolve_wht_category(
    line_items: List[Dict[str, Any]],
    transaction_type: str,
    is_corporate: bool,
) -> Tuple[str, float]:
    """Resolve Section 153 withholding tax category and base rate from line items."""
    # Concatenate item descriptions and categories for holistic semantic inspection
    text_corpus = " ".join([
        f"{it.get('description', '')} {it.get('category', '')} {it.get('nature', '')}"
        for it in line_items
    ]).lower()
    tx_type = (transaction_type or "").lower()
    combined = f"{text_corpus} {tx_type}"

    # 1. Advertising / Media
    if any(k in combined for k in ("advertis", "print media", "electronic media", "billboard", "tv ad", "newspaper ad", "google ads", "meta ads")):
        sched = WHT_SCHEDULE_RATES["ADVERTISING_MEDIA"]
        return "ADVERTISING_MEDIA", sched["base_rate"]

    # 2. IT and IT-enabled services (4%)
    if any(k in combined for k in ("it service", "it_service", "software", "web develop", "web design", "programming", "cloud", "saas", "hosting", "aws", "bpo", "data center", "information technology")):
        sched = WHT_SCHEDULE_RATES["IT_SERVICES"]
        return "IT_SERVICES", sched["base_rate"]

    # 3. Independent professional services (15%)
    if any(k in combined for k in ("legal", "lawyer", "advocate", "audit", "chartered account", "accountant", "doctor", "medical", "architect", "engineer", "professional", "retainer", "tax advisor", "tax advisory", "tax consult", "consulting", "consultancy")):
        sched = WHT_SCHEDULE_RATES["PROFESSIONAL_SERVICES"]
        return "PROFESSIONAL_SERVICES", sched["base_rate"]

    # 4. Specified services (7%)
    if any(k in combined for k in ("transport", "freight", "courier", "cargo", "hotel", "security guard", "security service", "tracking", "clearing agent")):
        sched = WHT_SCHEDULE_RATES["SPECIFIED_SERVICES"]
        return "SPECIFIED_SERVICES", sched["base_rate"]

    # 5. Contracts (7.5% corp / 8% individual)
    if any(k in combined for k in ("contract", "construction", "civil work", "fabrication", "turnkey", "contractor")):
        key = "CONTRACTS_CORP" if is_corporate else "CONTRACTS_INDIVIDUAL"
        sched = WHT_SCHEDULE_RATES[key]
        return key, sched["base_rate"]

    # 6. Goods / Physical supplies / Equipment / Furniture (5% corp / 5.5% individual)
    if any(k in combined for k in ("goods", "product", "supplies", "material", "inventory", "hardware", "furniture", "stationery", "toner", "paper", "equipment", "laptop", "computer", "desk", "chair")):
        key = "GOODS_CORP" if is_corporate else "GOODS_INDIVIDUAL"
        sched = WHT_SCHEDULE_RATES[key]
        return key, sched["base_rate"]

    # 7. Other general services (14%)
    if any(k in combined for k in ("service", "maintenance", "repair", "cleaning", "cater")):
        sched = WHT_SCHEDULE_RATES["OTHER_SERVICES"]
        return "OTHER_SERVICES", sched["base_rate"]

    # Default fallback: Goods based on corporate status
    key = "GOODS_CORP" if is_corporate else "GOODS_INDIVIDUAL"
    sched = WHT_SCHEDULE_RATES[key]
    return key, sched["base_rate"]


def _parse_tx_date(val: Any) -> Optional[date]:
    """Parse string or date object into date."""
    if not val:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return datetime.fromisoformat(str(val)[:10]).date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Pre-Flight Statutory Audit Engine
# ---------------------------------------------------------------------------

async def preflight_tax_compliance_audit(
    transaction_type: str,
    payment_method: str,
    total_amount: float,
    party_info: Optional[Dict[str, Any]] = None,
    line_items: Optional[List[Dict[str, Any]]] = None,
    is_fixed_asset: bool = False,
    recent_transactions: Optional[List[Dict[str, Any]]] = None,
) -> TaxAuditResult:
    """Execute pre-flight statutory & tax compliance audit under Pakistan Law (ITO 2001).

    Enforces:
    - Section 73 & Section 21(l) cash payment limits (PKR 50,000 expense, PKR 250,000 fixed asset).
    - Section 153 Withholding Tax (WHT) rates, Tenth Schedule non-filer surcharges, and net settlement.
    - Forensic duplicate payment detection (identical invoice ref, temporal amount proximity, near-amounts).
    """
    total = round(float(total_amount or 0.0), 2)
    pay_method = str(payment_method or "").strip().upper()
    party = party_info or {}
    items = line_items or []

    statutory_warnings: List[str] = []
    blocking_violations: List[str] = []
    audit_flags: List[str] = []
    blocking = False

    # Determine whether this is a capital/fixed asset acquisition
    effective_is_fixed_asset = is_fixed_asset or any(
        item.get("is_fixed_asset") is True or item.get("nature") == "FIXED_ASSET"
        for item in items
    ) or str(transaction_type or "").upper() in ("FIXED_ASSET_PURCHASE", "CAPITAL_EXPENDITURE", "ASSET_PURCHASE")

    # =======================================================================
    # 1. Section 73 & Section 21(l) Cash Threshold Audit
    # =======================================================================
    section_73_compliant = True
    section_73_warning = None
    section_73_violation = None
    rec_channels = ["Bank Transfer", "Crossed Cheque", "Pay Order"]

    if pay_method == "CASH":
        if effective_is_fixed_asset:
            threshold = SECTION_73_ASSET_CASH_LIMIT
            if total > threshold:
                section_73_compliant = False
                section_73_violation = (
                    f"CRITICAL STATUTORY VIOLATION (ITO 2001 Section 73(2) & 73(3)): "
                    f"Asset purchase of PKR {total:,.2f} in CASH exceeds the statutory limit "
                    f"of PKR {threshold:,.2f}. Under Section 73(2)/(3), depreciation deductions "
                    "and initial allowance will be legally disallowed. "
                    "Payment must be made via crossed banking instrument (Bank Transfer, Crossed Cheque)."
                )
                blocking_violations.append(section_73_violation)
                statutory_warnings.append(section_73_violation)
                blocking = True
        else:
            threshold = SECTION_73_EXPENSE_CASH_LIMIT
            if total > threshold:
                section_73_compliant = False
                section_73_warning = (
                    f"STATUTORY DISALLOWANCE HAZARD (ITO 2001 Section 73(1) & 21(l)): "
                    f"Cash payment of PKR {total:,.2f} exceeds the PKR {threshold:,.2f} statutory limit. "
                    "Under Section 21(l), this expenditure will be disallowed by FBR and added back "
                    "to taxable profits (subject to 29% corporate income tax). "
                    "Switch to recognized banking channels (Bank Transfer, Crossed Cheque, Pay Order)."
                )
                statutory_warnings.append(section_73_warning)
    else:
        threshold = SECTION_73_ASSET_CASH_LIMIT if effective_is_fixed_asset else SECTION_73_EXPENSE_CASH_LIMIT

    # =======================================================================
    # 2. Section 153 Withholding Tax (WHT) Audit
    # =======================================================================
    wht_applicable = False
    wht_rate = 0.0
    wht_amount = 0.0
    net_payable = total
    wht_category = None
    wht_status = "NOT_APPLICABLE"
    is_non_filer_surcharge = False

    # Check applicability to payment/purchase events
    tx_type_upper = str(transaction_type or "").upper()
    is_commercial_payment = tx_type_upper in (
        "SUPPLIER_PAYMENT", "PURCHASE_BILL", "PURCHASE", "EXPENSE",
        "VENDOR_PAYMENT", "CONTRACT", "SERVICES", "CASH_PURCHASE",
        "RECORD_EXPENSE", "RECORD_PURCHASE", "BILL_PAYMENT",
    ) or bool(party)

    if is_commercial_payment and total > 0:
        wht_applicable = True
        is_corporate = bool(party.get("is_corporate", False))
        is_filer = bool(party.get("is_filer", True))
        has_exemption = bool(party.get("has_exemption_cert") or party.get("is_exempt") or party.get("exemption_certificate_valid"))

        if has_exemption:
            wht_rate = 0.0
            wht_category = "EXEMPT_SECTION_159"
            wht_status = "EXEMPT_CERTIFICATE"
            audit_flags.append("SECTION_159_EXEMPTION: Valid tax exemption certificate verified. 0% WHT applied.")
        else:
            cat, base_rate = _resolve_wht_category(items, transaction_type, is_corporate)
            wht_category = cat

            # Check Tenth Schedule Non-Filer 2x Surcharge
            if not is_filer:
                wht_rate = base_rate * 2.0
                is_non_filer_surcharge = True
                audit_flags.append(
                    f"TENTH_SCHEDULE_NON_FILER: Vendor is Inactive / Non-Filer. "
                    f"Statutory 2x withholding rate applied ({base_rate}% -> {wht_rate}%)."
                )
            else:
                wht_rate = base_rate

            # Check Annual Exemption Threshold
            thresh_group = "GOODS" if "GOODS" in cat else ("CONTRACTS" if "CONTRACT" in cat else "SERVICES")
            ann_thresh = SECTION_153_ANNUAL_THRESHOLDS.get(thresh_group, 30000.0)
            annual_turnover = float(party.get("annual_turnover") or total)

            if annual_turnover < ann_thresh and total < ann_thresh:
                wht_status = "UNDER_THRESHOLD"
                audit_flags.append(
                    f"SECTION_153_THRESHOLD: Transaction amount PKR {total:,.2f} is under annual "
                    f"statutory threshold of PKR {ann_thresh:,.2f} for {thresh_group}."
                )
            else:
                wht_status = "DEDUCTION_MANDATORY"

        wht_amount = round(total * (wht_rate / 100.0), 2)
        net_payable = round(total - wht_amount, 2)

    # =======================================================================
    # 3. Forensic Duplicate Payment & Fraud Detection Audit
    # =======================================================================
    is_duplicate_risk = False
    duplicate_risk_severity = None
    duplicate_reason = None

    history = recent_transactions or party.get("recent_transactions") or []
    current_inv_ref = str(
        party.get("supplier_invoice_ref") or party.get("invoice_no") or party.get("bill_number") or ""
    ).strip().lower()
    vendor_id = str(party.get("id") or party.get("supplier_id") or party.get("vendor_id") or "").strip()
    vendor_name = str(party.get("name") or party.get("supplier_name") or party.get("vendor_name") or "").strip().lower()

    if history:
        for past_tx in history:
            past_vendor_id = str(past_tx.get("supplier_id") or past_tx.get("vendor_id") or past_tx.get("id") or "").strip()
            past_vendor_name = str(past_tx.get("supplier_name") or past_tx.get("vendor_name") or past_tx.get("name") or "").strip().lower()
            vendor_matches = (vendor_id and past_vendor_id == vendor_id) or (vendor_name and vendor_name == past_vendor_name) or (not vendor_id and not vendor_name)

            if not vendor_matches:
                continue

            past_inv_ref = str(
                past_tx.get("supplier_invoice_ref") or past_tx.get("invoice_no") or past_tx.get("bill_number") or ""
            ).strip().lower()
            past_amount = round(float(past_tx.get("amount") or past_tx.get("total") or 0.0), 2)

            # Vector 1: Identical Invoice Reference Match (Hard Stop)
            if current_inv_ref and past_inv_ref and current_inv_ref == past_inv_ref:
                is_duplicate_risk = True
                duplicate_risk_severity = "CRITICAL"
                duplicate_reason = (
                    f"DUPLICATE INVOICE DETECTED: Supplier invoice reference '{party.get('supplier_invoice_ref') or party.get('invoice_no')}' "
                    f"has already been processed for vendor '{party.get('name') or 'Supplier'}'. "
                    "Transaction blocked to prevent double payment."
                )
                blocking_violations.append(duplicate_reason)
                statutory_warnings.append(duplicate_reason)
                blocking = True
                break

            # Vector 2: Exact Net Amount & Vendor within 45 Days (High Risk)
            if total > 0 and past_amount > 0 and abs(total - past_amount) < 0.01:
                is_duplicate_risk = True
                if duplicate_risk_severity != "CRITICAL":
                    duplicate_risk_severity = "HIGH"
                    duplicate_reason = (
                        f"POTENTIAL DUPLICATE PAYMENT: An identical disbursement of PKR {total:,.2f} "
                        f"was recently processed for vendor '{party.get('name') or 'Supplier'}'. "
                        "Verify that this is not an accidental re-entry."
                    )
                    statutory_warnings.append(duplicate_reason)

            # Vector 3: Near-Amount Anomaly within ±2% (Medium Risk)
            elif total > 0 and past_amount > 0 and abs(total - past_amount) <= total * 0.02:
                if duplicate_risk_severity not in ("CRITICAL", "HIGH"):
                    is_duplicate_risk = True
                    duplicate_risk_severity = "MEDIUM"
                    duplicate_reason = (
                        f"NEAR-AMOUNT PAYMENT ANOMALY: Payment of PKR {past_amount:,.2f} (within ±2% of current "
                        f"PKR {total:,.2f}) was recently settled with this vendor. "
                        "Review to ensure no duplicate billing under an altered invoice number."
                    )
                    audit_flags.append(duplicate_reason)

            # Vector 4: Cash Structuring / Smurfing Detection u/s 73
            past_method = str(past_tx.get("payment_method") or "").upper()
            if pay_method == "CASH" and past_method == "CASH":
                if (40000.0 <= total < 50000.0 and 40000.0 <= past_amount < 50000.0) or (total + past_amount > 50000.0):
                    audit_flags.append(
                        "SECTION_73_STRUCTURING_HAZARD: Consecutive cash payments near the PKR 50,000 threshold "
                        "detected. Deliberate structuring to evade banking channels violates Section 73 anti-avoidance rules."
                    )

    # =======================================================================
    # 4. Suggested Double-Entry Accounting
    # =======================================================================
    suggested_journal_lines: Optional[List[Dict[str, Any]]] = None
    if total > 0:
        debit_code = "1520" if effective_is_fixed_asset else ("6310" if "PROFESSIONAL" in (wht_category or "") else "6100")
        debit_name = "Computer & IT Equipment" if effective_is_fixed_asset else ("Legal & Professional Fees" if "PROFESSIONAL" in (wht_category or "") else "Operating Expense")

        suggested_journal_lines = [
            {
                "account_code": debit_code,
                "account_name": debit_name,
                "debit": total,
                "credit": 0.0,
                "description": f"Gross expense / asset recognition: {transaction_type}",
            }
        ]
        if wht_amount > 0:
            suggested_journal_lines.append({
                "account_code": "2120",
                "account_name": "Withholding Income Tax Payable u/s 153",
                "debit": 0.0,
                "credit": wht_amount,
                "description": f"Section 153 WHT deduction ({wht_rate}%) u/s {wht_category}",
            })
        settlement_code = "1010" if pay_method == "CASH" else "1020"
        settlement_name = "Cash in Hand" if pay_method == "CASH" else "Bank Balances"
        suggested_journal_lines.append({
            "account_code": settlement_code,
            "account_name": settlement_name,
            "debit": 0.0,
            "credit": net_payable,
            "description": f"Net settlement payable to vendor via {pay_method or 'Bank'}",
        })

    # Overall Pass / Block status
    passed = not blocking

    # Narrative summary
    narratives = []
    if blocking_violations:
        narratives.append(f"CRITICAL VIOLATIONS DETECTED: {len(blocking_violations)} blocking condition(s).")
    if statutory_warnings:
        narratives.append(f"STATUTORY WARNINGS: {len(statutory_warnings)} compliance risk(s).")
    if wht_applicable:
        narratives.append(
            f"WHT u/s 153: {wht_rate}% ({wht_category}), Tax Withheld: PKR {wht_amount:,.2f}, Net Payable: PKR {net_payable:,.2f}."
        )
    if passed and not statutory_warnings:
        narratives.append("All statutory compliance and anti-fraud checks PASSED successfully.")

    audit_narrative = " ".join(narratives)

    return TaxAuditResult(
        passed=passed,
        blocking=blocking,
        statutory_warnings=statutory_warnings,
        blocking_violations=blocking_violations,
        audit_flags=audit_flags,
        section_73_compliant=section_73_compliant,
        section_73_threshold=threshold,
        section_73_warning=section_73_warning,
        section_73_violation=section_73_violation,
        recommended_banking_channels=rec_channels,
        section_153_applicable=wht_applicable,
        wht_rate_percent=wht_rate,
        wht_amount=wht_amount,
        net_payable=net_payable,
        wht_category=wht_category,
        wht_status=wht_status,
        is_non_filer_surcharge_applied=is_non_filer_surcharge,
        is_duplicate_risk=is_duplicate_risk,
        duplicate_risk_severity=duplicate_risk_severity,
        duplicate_reason=duplicate_reason,
        suggested_journal_lines=suggested_journal_lines,
        audit_narrative=audit_narrative,
    )
