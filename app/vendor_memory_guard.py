"""Episodic Memory & Proactive Vendor Fingerprinting Guard (DOC-CFO-2026-FRONTIER-V1 Section 2.3).

Architectural Pillar & Statutory Alignment:
1. Historical Vendor Term Fingerprinting:
   - Derives customary settlement method (CASH vs BANK vs CREDIT).
   - Identifies standard bank title / account (e.g. Meezan Bank, HBL, Standard Chartered).
   - Resolves typical Tier-4 analytical expense/asset accounts (e.g. 5100 Office Supplies, 1510 IT Equipment).
   - Evaluates Section 153 Withholding Tax (WHT) posture & enforces dynamic Active Taxpayer List (ATL)
     30-day verification TTL under Tenth Schedule of ITO 2001.
   - Generates natural, personalized chat suggestion prompts:
     "For Apex Supplies, you usually pay via Meezan Bank with 5% WHT deducted. Shall I use these terms?"

2. Proactive Duplicate Transaction & Invoice Guard:
   - Multi-vector detection within configurable rolling window (e.g. 72 hours).
   - Vector 1: Identical Invoice / Bill Reference collision (CRITICAL / HIGH).
   - Vector 2: Exact Net Amount & Vendor Collision within temporal window.
   - Vector 3: Legitimate Recurring Subscription Disambiguation (differentiates periodic utility bills,
     monthly rent, and retainer contracts from accidental duplicate billing).
   - Vector 4: Section 73 / 21(l) Cash Structuring & Smurfing Evasion Guard (flags split cash payments
     below PKR 50,000 threshold when rolling 72-hour sum breaches statutory limit).
   - Vector 5: Near-Amount Anomaly Detection (within ±2% window).

3. Quality Standards:
   - Modern, high-end Python 3.12+, Pydantic v2 validation, zero external network or database dependencies.
   - High-performance, deterministic, hermetic unit testability.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Statutory & Operational Constants
# ---------------------------------------------------------------------------

SECTION_73_CASH_EXPENSE_LIMIT = 50000.0  # PKR 50k cash disallowance ceiling u/s 73/21(l)
DEFAULT_ATL_TTL_DAYS = 30                # Maximum ATL freshness window before re-verification
DEFAULT_DUPLICATE_WINDOW_HOURS = 72      # Configurable 72-hour duplicate detection window
NEAR_AMOUNT_DEFAULT_TOLERANCE = 0.02     # ±2% near-amount anomaly threshold

# Standard Recurring Bill Indicators (Utilities, Rent, Retainers, SaaS)
KNOWN_RECURRING_PATTERNS = [
    r"\brent\b",
    r"\blease\b",
    r"\bretainer\b",
    r"\bsubscription\b",
    r"\butility\b",
    r"\belectricity\b",
    r"\binternet\b",
    r"\bbroadband\b",
    r"\btelecom\b",
    r"\bk-?electric\b",
    r"\blesco\b",
    r"\biesco\b",
    r"\bfesco\b",
    r"\bmepco\b",
    r"\bsngpl\b",
    r"\bssgc\b",
    r"\bptcl\b",
    r"\bstormfiber\b",
    r"\bnayatel\b",
    r"\btransworld\b",
    r"\bjazz\b",
    r"\bzong\b",
    r"\btelenor\b",
    r"\bufone\b",
    r"\baws\b",
    r"\bamazon web services\b",
    r"\bgoogle cloud\b",
    r"\bgoogle workspace\b",
    r"\bslack\b",
    r"\bzoom\b",
    r"\bgithub\b",
    r"\bmicrosoft 365\b",
    r"\boffice 365\b",
]

_RECURRING_REGEX = re.compile("|".join(KNOWN_RECURRING_PATTERNS), re.IGNORECASE)
_NON_ALNUM = re.compile(r"[\W_]+", flags=re.UNICODE)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DuplicateRiskLevel(str, Enum):
    """Proactive duplicate risk severity rating."""
    NONE = "NONE"
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DuplicateDetectionVector(str, Enum):
    """Detection vector triggering the duplicate guard result."""
    INVOICE_REF_MATCH = "INVOICE_REF_MATCH"
    IDENTICAL_AMOUNT_WINDOW = "IDENTICAL_AMOUNT_WINDOW"
    CASH_STRUCTURING_HAZARD = "CASH_STRUCTURING_HAZARD"
    NEAR_AMOUNT_ANOMALY = "NEAR_AMOUNT_ANOMALY"
    RECURRING_PERIODIC_CONFIRMED = "RECURRING_PERIODIC_CONFIRMED"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Helper Normalization Utilities
# ---------------------------------------------------------------------------

def normalize_vendor_key(text: Any) -> str:
    """Normalize vendor name into alphanumeric lowercase key for resilient matching.

    Strips punctuation, spaces, and collapses legal suffixes like 'ltd', 'pvt', 'inc'.
    """
    if not text:
        return ""
    cleaned = str(text).lower()
    # Strip common corporate suffixes for comparison
    cleaned = re.sub(r"\b(pvt|private|ltd|limited|inc|incorporated|llc|co|corp|corporation)\b", "", cleaned)
    return _NON_ALNUM.sub("", cleaned)


def _parse_dt(val: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, date):
        return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        v = val.strip()
        if not v:
            return None
        # ISO format parser
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
        # Common text formats
        for fmt in (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%d %b %Y",
            "%d %B %Y",
        ):
            try:
                dt = datetime.strptime(v, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _extract_billing_period_text(data: Union[str, Dict[str, Any], None]) -> Optional[str]:
    """Extract and normalize billing period / service month from text or record."""
    if not data:
        return None
    if isinstance(data, dict):
        explicit = (
            data.get("billing_period")
            or data.get("service_period")
            or data.get("billing_month")
            or data.get("period")
        )
        if explicit:
            return str(explicit).strip()
        # Fall back to inspecting description / notes
        text = " ".join([
            str(data.get("description") or ""),
            str(data.get("notes") or ""),
            str(data.get("memo") or ""),
            str(data.get("narration") or ""),
            str(data.get("invoice_ref") or data.get("supplier_invoice_ref") or ""),
        ])
    else:
        text = str(data)

    # Match patterns like "March 2026", "Apr 2026", "2026-03", "03/2026"
    iso_match = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])\b", text)
    if iso_match:
        return f"{iso_match.group(1)}-{iso_match.group(2)}"

    month_match = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"[,\s]+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if month_match:
        month_str = month_match.group(1).title()
        year_str = month_match.group(2)
        return f"{month_str} {year_str}"

    return None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class VendorWhtTreatment(BaseModel):
    """Section 153 Withholding Tax posture and Active Taxpayer List (ATL) verification state."""
    model_config = ConfigDict(frozen=False)

    wht_applicable: bool = False
    standard_wht_rate: float = 0.0
    wht_section: Optional[str] = None       # e.g. "153(1)(a)" for goods, "153(1)(b)" for services
    wht_category: Optional[str] = None      # e.g. "GOODS", "SERVICES", "IT_SERVICES"
    atl_status: str = "UNKNOWN"             # "ACTIVE", "INACTIVE", "UNKNOWN"
    atl_last_verified_at: Optional[datetime] = None
    atl_ttl_days: int = DEFAULT_ATL_TTL_DAYS
    is_atl_stale: bool = False
    atl_warning: Optional[str] = None


class VendorFingerprint(BaseModel):
    """Personalized historical vendor defaults and behavioral profile."""
    model_config = ConfigDict(frozen=False)

    vendor_name: str
    normalized_name: str
    customary_payment_method: Literal["CASH", "BANK", "CREDIT"] = "BANK"
    payment_method_confidence: float = 1.0
    standard_bank_name: Optional[str] = None
    standard_bank_account: Optional[str] = None
    typical_account_code: Optional[str] = None
    typical_account_name: Optional[str] = None
    wht_treatment: VendorWhtTreatment = Field(default_factory=VendorWhtTreatment)
    customary_payment_terms: Optional[str] = None
    is_recurring: bool = False
    recurring_frequency: Optional[str] = None
    typical_amount: Optional[float] = None
    total_transactions_analyzed: int = 0
    total_spend: float = 0.0
    last_transaction_date: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def suggest_terms_prompt(
        self,
        vendor_display_name: Optional[str] = None,
        include_account: bool = False,
        include_atl_warning: bool = False,
    ) -> str:
        """Generate personalized natural conversational prompt for chat defaults.

        Standard Output Format:
        "For Apex Supplies, you usually pay via Meezan Bank with 5% WHT deducted. Shall I use these terms?"
        """
        display_name = vendor_display_name or self.vendor_name

        account_clause = ""
        if include_account and self.typical_account_code:
            desc = f" - {self.typical_account_name}" if self.typical_account_name else ""
            account_clause = f" (allocated to {self.typical_account_code}{desc})"

        wht_clause = ""
        if self.wht_treatment.wht_applicable and self.wht_treatment.standard_wht_rate > 0:
            rate_val = self.wht_treatment.standard_wht_rate
            rate_formatted = f"{rate_val:g}%"
            wht_clause = f" with {rate_formatted} WHT deducted"

        # Construct settlement clause
        if self.customary_payment_method == "BANK":
            if self.standard_bank_name:
                base_clause = f"you usually pay via {self.standard_bank_name}"
            else:
                base_clause = "you usually pay via Bank Transfer"
        elif self.customary_payment_method == "CASH":
            base_clause = "you usually pay in Cash"
        elif self.customary_payment_method == "CREDIT":
            terms = f" on {self.customary_payment_terms}" if self.customary_payment_terms else " on Credit"
            base_clause = f"you usually record purchases{terms}"
        else:
            base_clause = f"you usually pay via {self.customary_payment_method}"

        prompt = f"For {display_name}, {base_clause}{wht_clause}{account_clause}. Shall I use these terms?"

        if include_atl_warning and self.wht_treatment.is_atl_stale and self.wht_treatment.atl_warning:
            prompt += f"\n⚠️ {self.wht_treatment.atl_warning}"

        return prompt


class DuplicateScanResult(BaseModel):
    """Result of multi-vector duplicate transaction & invoice screening."""
    model_config = ConfigDict(frozen=False)

    risk_level: DuplicateRiskLevel
    is_duplicate: bool = False
    warning_message: Optional[str] = None
    matched_transaction_ids: List[str] = Field(default_factory=list)
    detection_vector: DuplicateDetectionVector = DuplicateDetectionVector.NONE
    is_legitimate_recurring: bool = False
    is_structuring_detected: bool = False
    cumulative_cash_amount: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core Engine: VendorMemoryGuard
# ---------------------------------------------------------------------------

class VendorMemoryGuard:
    """Enterprise-grade episodic memory engine & proactive duplicate guard."""

    def __init__(
        self,
        atl_ttl_days: int = DEFAULT_ATL_TTL_DAYS,
        duplicate_window_hours: int = DEFAULT_DUPLICATE_WINDOW_HOURS,
        structuring_cash_limit: float = SECTION_73_CASH_EXPENSE_LIMIT,
        near_amount_tolerance: float = NEAR_AMOUNT_DEFAULT_TOLERANCE,
    ) -> None:
        self.atl_ttl_days = atl_ttl_days
        self.duplicate_window_hours = duplicate_window_hours
        self.structuring_cash_limit = structuring_cash_limit
        self.near_amount_tolerance = near_amount_tolerance

    # -----------------------------------------------------------------------
    # 1. Historical Vendor Term Fingerprinting
    # -----------------------------------------------------------------------

    def lookup_vendor_fingerprint(
        self,
        vendor_name: str,
        historical_records: Sequence[Dict[str, Any]],
        as_of_date: Optional[Union[date, datetime, str]] = None,
    ) -> Optional[VendorFingerprint]:
        """Synthesize historical vendor transactions into an episodic behavioral profile.

        Args:
            vendor_name: Counterparty name to analyze.
            historical_records: Sequence of past vouchers, bills, purchase orders, or ledger items.
            as_of_date: Reference date for ATL freshness verification (defaults to current date).

        Returns:
            VendorFingerprint if historical transactions match, or None if unknown vendor.
        """
        if not vendor_name or not historical_records:
            return None

        target_key = normalize_vendor_key(vendor_name)
        if not target_key:
            return None

        # Filter matching records
        matching_records: List[Dict[str, Any]] = []
        for record in historical_records:
            if not isinstance(record, dict):
                continue
            rec_vendor = (
                record.get("vendor_name")
                or record.get("supplier_name")
                or record.get("party_name")
                or record.get("name")
                or record.get("vendor")
                or record.get("counterparty")
                or ""
            )
            rec_key = normalize_vendor_key(rec_vendor)
            if not rec_key:
                continue

            # Substring or exact match guard
            if rec_key == target_key or rec_key in target_key or target_key in rec_key:
                matching_records.append(record)

        if not matching_records:
            return None

        # 1. Payment Method Frequency
        payment_methods: List[str] = []
        for r in matching_records:
            pm = str(
                r.get("payment_method")
                or r.get("method")
                or r.get("payment_type")
                or r.get("settlement_channel")
                or ""
            ).strip().upper()
            if not pm:
                continue
            if any(k in pm for k in ("CASH", "PETTY")):
                payment_methods.append("CASH")
            elif any(k in pm for k in ("BANK", "CHEQUE", "CHECK", "ONLINE", "WIRE", "IBFT", "CROSSED", "TRANSFER")):
                payment_methods.append("BANK")
            elif any(k in pm for k in ("CREDIT", "AP", "PAYABLE", "ON_ACCOUNT", "BILL")):
                payment_methods.append("CREDIT")
            else:
                payment_methods.append(pm)

        dominant_method: Literal["CASH", "BANK", "CREDIT"] = "BANK"
        method_confidence = 1.0
        if payment_methods:
            counts = Counter(payment_methods)
            most_common_method, freq = counts.most_common(1)[0]
            if most_common_method in ("CASH", "BANK", "CREDIT"):
                dominant_method = most_common_method  # type: ignore[assignment]
            else:
                dominant_method = "BANK"
            method_confidence = round(freq / len(payment_methods), 2)

        # 2. Standard Bank Name & Account
        bank_names: List[str] = []
        bank_accounts: List[str] = []
        for r in matching_records:
            b_name = (
                r.get("bank_name")
                or r.get("bank")
                or r.get("bank_account_name")
                or r.get("source_account_name")
                or r.get("settlement_bank")
            )
            if b_name and str(b_name).strip():
                bank_names.append(str(b_name).strip())

            b_acc = r.get("bank_account") or r.get("account_number") or r.get("iban")
            if b_acc and str(b_acc).strip():
                bank_accounts.append(str(b_acc).strip())

        standard_bank = Counter(bank_names).most_common(1)[0][0] if bank_names else None
        standard_acc = Counter(bank_accounts).most_common(1)[0][0] if bank_accounts else None

        # 3. Typical Analytical Expense / Asset Account Code
        account_codes: List[str] = []
        account_name_map: Dict[str, str] = {}
        for r in matching_records:
            code = str(
                r.get("account_code")
                or r.get("expense_account")
                or r.get("debit_account")
                or r.get("ledger_code")
                or ""
            ).strip()
            name = str(
                r.get("account_name")
                or r.get("expense_account_name")
                or r.get("debit_account_name")
                or ""
            ).strip()

            # Also inspect nested lines if present
            if not code and isinstance(r.get("lines"), list):
                for line in r["lines"]:
                    if isinstance(line, dict):
                        l_code = str(line.get("account_code") or "").strip()
                        l_debit = float(line.get("debit") or 0.0)
                        if l_debit > 0 and l_code and not l_code.startswith(("1010", "1020", "2000")):
                            code = l_code
                            name = str(line.get("account_name") or "").strip()
                            break

            if code:
                account_codes.append(code)
                if name:
                    account_name_map[code] = name

        typical_code = Counter(account_codes).most_common(1)[0][0] if account_codes else None
        typical_name = account_name_map.get(typical_code or "", None)

        # 4. Section 153 Withholding Tax Posture & ATL Verification TTL
        wht_rates: List[float] = []
        wht_sections: List[str] = []
        wht_categories: List[str] = []
        atl_statuses: List[str] = []
        atl_verified_dates: List[datetime] = []

        for r in matching_records:
            # WHT rate
            raw_rate = r.get("wht_rate") or r.get("tax_rate") or r.get("wht_percentage")
            if raw_rate is not None:
                try:
                    rate_f = float(raw_rate)
                    if rate_f > 0:
                        wht_rates.append(rate_f)
                except (ValueError, TypeError):
                    pass

            sec = r.get("wht_section") or r.get("tax_section")
            if sec:
                wht_sections.append(str(sec).strip())

            cat = r.get("wht_category") or r.get("tax_category") or r.get("nature")
            if cat:
                wht_categories.append(str(cat).strip().upper())

            # ATL status & timestamp
            status = r.get("atl_status") or r.get("tax_status")
            if status:
                s_str = str(status).strip().upper()
                if "ACTIVE" in s_str or "FILER" in s_str:
                    atl_statuses.append("ACTIVE")
                elif "INACTIVE" in s_str or "NON" in s_str:
                    atl_statuses.append("INACTIVE")

            v_dt = _parse_dt(
                r.get("atl_last_verified_at")
                or r.get("atl_verified_at")
                or r.get("atl_verified_date")
                or r.get("tax_status_verified_at")
            )
            if v_dt:
                atl_verified_dates.append(v_dt)

        wht_applicable = len(wht_rates) > 0
        standard_rate = Counter(wht_rates).most_common(1)[0][0] if wht_rates else 0.0
        wht_section = Counter(wht_sections).most_common(1)[0][0] if wht_sections else ("153(1)(a)" if standard_rate in (5.0, 5.5) else "153(1)(b)" if standard_rate > 0 else None)
        wht_category = Counter(wht_categories).most_common(1)[0][0] if wht_categories else ("GOODS" if standard_rate in (5.0, 5.5) else "SERVICES" if standard_rate > 0 else None)
        atl_status = Counter(atl_statuses).most_common(1)[0][0] if atl_statuses else "ACTIVE"

        # Determine latest verification datetime
        latest_atl_dt: Optional[datetime] = None
        if atl_verified_dates:
            latest_atl_dt = max(atl_verified_dates)

        # Enforce Section 2.3 Mandate: 30-Day TTL for ATL Status
        ref_dt = _parse_dt(as_of_date) or datetime.now(timezone.utc)
        is_atl_stale = False
        atl_warning: Optional[str] = None

        if latest_atl_dt is not None:
            age_days = (ref_dt.date() - latest_atl_dt.date()).days
            if age_days > self.atl_ttl_days:
                is_atl_stale = True
                atl_warning = (
                    f"Active Taxpayer List (ATL) verification is {age_days} days old "
                    f"(exceeds {self.atl_ttl_days}-day limit). Under Tenth Schedule ITO 2001, "
                    "inactive status incurs 100% higher withholding tax (Double WHT). "
                    "Please re-verify vendor status on FBR portal."
                )
        else:
            # No verification timestamp present in historical records
            is_atl_stale = True
            atl_warning = (
                f"No verified Active Taxpayer List (ATL) timestamp on file. Under Tenth Schedule ITO 2001, "
                f"vendor active status must be validated every {self.atl_ttl_days} days to safeguard against 100% WHT penalty."
            )

        wht_treatment = VendorWhtTreatment(
            wht_applicable=wht_applicable,
            standard_wht_rate=standard_rate,
            wht_section=wht_section,
            wht_category=wht_category,
            atl_status=atl_status,
            atl_last_verified_at=latest_atl_dt,
            atl_ttl_days=self.atl_ttl_days,
            is_atl_stale=is_atl_stale,
            atl_warning=atl_warning,
        )

        # 5. Recurring Bill & Spend Analysis
        amounts: List[float] = []
        payment_terms_list: List[str] = []
        is_recurring = False
        recurring_freq: Optional[str] = None
        dates: List[str] = []

        for r in matching_records:
            amt = r.get("amount") or r.get("total") or r.get("net_amount") or r.get("gross_amount")
            if amt is not None:
                try:
                    amounts.append(round(float(amt), 2))
                except (ValueError, TypeError):
                    pass

            terms = r.get("payment_terms") or r.get("terms")
            if terms:
                payment_terms_list.append(str(terms).strip())

            if r.get("is_recurring") is True or r.get("recurring") is True:
                is_recurring = True
                recurring_freq = str(r.get("recurring_frequency") or r.get("frequency") or "MONTHLY").upper()

            d = str(r.get("date") or r.get("transaction_date") or r.get("created_at") or "").strip()
            if d:
                dates.append(d)

        # Check vendor name / nature for recurring subscription profile
        if not is_recurring and _RECURRING_REGEX.search(vendor_name):
            is_recurring = True
            recurring_freq = "MONTHLY"

        typical_terms = Counter(payment_terms_list).most_common(1)[0][0] if payment_terms_list else None
        typical_amt = Counter(amounts).most_common(1)[0][0] if amounts else None
        total_spend = round(sum(amounts), 2)
        last_date = sorted(dates)[-1] if dates else None

        return VendorFingerprint(
            vendor_name=vendor_name,
            normalized_name=target_key,
            customary_payment_method=dominant_method,
            payment_method_confidence=method_confidence,
            standard_bank_name=standard_bank,
            standard_bank_account=standard_acc,
            typical_account_code=typical_code,
            typical_account_name=typical_name,
            wht_treatment=wht_treatment,
            customary_payment_terms=typical_terms,
            is_recurring=is_recurring,
            recurring_frequency=recurring_freq,
            typical_amount=typical_amt,
            total_transactions_analyzed=len(matching_records),
            total_spend=total_spend,
            last_transaction_date=last_date,
        )

    # -----------------------------------------------------------------------
    # 2. Proactive Duplicate Transaction & Invoice Guard
    # -----------------------------------------------------------------------

    def check_duplicate_risk(
        self,
        vendor_name: str,
        amount: float,
        invoice_ref: Optional[str] = None,
        recent_transactions: Sequence[Dict[str, Any]] = (),
        reference_date: Optional[Union[date, datetime, str]] = None,
        payment_method: Optional[str] = None,
        account_code: Optional[str] = None,
        billing_period: Optional[str] = None,
        is_recurring: Optional[bool] = None,
    ) -> DuplicateScanResult:
        """Evaluate duplicate transaction risk across five forensic statutory vectors.

        Args:
            vendor_name: Target counterparty name.
            amount: Transaction gross or net amount.
            invoice_ref: Optional supplier bill / invoice number reference.
            recent_transactions: Sequence of recently processed transactions within review window.
            reference_date: Baseline evaluation date (defaults to current UTC datetime).
            payment_method: Settlement channel (e.g. CASH, BANK).
            account_code: COA debit account code.
            billing_period: Optional period label (e.g. "April 2026", "2026-04").
            is_recurring: Explicit override indicating a recurring periodic transaction.

        Returns:
            DuplicateScanResult with risk_level (NONE, LOW, HIGH, CRITICAL), warning message,
            and matched prior transaction IDs.
        """
        if not recent_transactions or amount <= 0:
            return DuplicateScanResult(risk_level=DuplicateRiskLevel.NONE)

        target_vendor_key = normalize_vendor_key(vendor_name)
        norm_inv_ref = str(invoice_ref or "").strip().lower().lstrip("#")
        eval_dt = _parse_dt(reference_date) or datetime.now(timezone.utc)
        current_period = billing_period or _extract_billing_period_text(invoice_ref)
        pay_method_upper = str(payment_method or "").strip().upper()

        # Check recurring classification
        effective_recurring = is_recurring if is_recurring is not None else bool(_RECURRING_REGEX.search(vendor_name))

        matched_ids: List[str] = []
        recent_cash_txs: List[Dict[str, Any]] = []

        # Scan transactions for target vendor
        for tx in recent_transactions:
            if not isinstance(tx, dict):
                continue

            tx_vendor = (
                tx.get("vendor_name")
                or tx.get("supplier_name")
                or tx.get("party_name")
                or tx.get("name")
                or tx.get("vendor")
                or ""
            )
            tx_key = normalize_vendor_key(tx_vendor)

            # Vendor identity match check
            vendor_match = False
            if target_vendor_key and tx_key:
                vendor_match = (
                    target_vendor_key == tx_key
                    or target_vendor_key in tx_key
                    or tx_key in target_vendor_key
                )
            elif not target_vendor_key and not tx_key:
                vendor_match = True

            if not vendor_match:
                continue

            tx_id = str(tx.get("id") or tx.get("transaction_id") or tx.get("bill_id") or tx.get("voucher_id") or "UNKNOWN")
            tx_amt = round(float(tx.get("amount") or tx.get("total") or tx.get("net_amount") or 0.0), 2)
            tx_inv_ref = str(
                tx.get("supplier_invoice_ref")
                or tx.get("invoice_no")
                or tx.get("invoice_ref")
                or tx.get("bill_number")
                or ""
            ).strip().lower().lstrip("#")

            tx_dt = _parse_dt(tx.get("created_at") or tx.get("date") or tx.get("transaction_date"))
            tx_method = str(tx.get("payment_method") or tx.get("method") or "").strip().upper()

            # Track cash disbursements for Section 73 structuring guard
            if tx_dt:
                hours_diff = abs((eval_dt - tx_dt).total_seconds()) / 3600.0
            else:
                hours_diff = 0.0

            if "CASH" in tx_method and hours_diff <= self.duplicate_window_hours:
                recent_cash_txs.append({"id": tx_id, "amount": tx_amt, "hours_ago": hours_diff})

            # ===============================================================
            # Vector 1: Identical Invoice Reference (Hard Block / CRITICAL)
            # ===============================================================
            if norm_inv_ref and tx_inv_ref and norm_inv_ref == tx_inv_ref:
                msg = (
                    f"DUPLICATE INVOICE DETECTED: Supplier invoice reference '{invoice_ref}' "
                    f"has already been processed in transaction '{tx_id}' for vendor '{vendor_name}'. "
                    "Transaction blocked to prevent double payment."
                )
                return DuplicateScanResult(
                    risk_level=DuplicateRiskLevel.CRITICAL,
                    is_duplicate=True,
                    warning_message=msg,
                    matched_transaction_ids=[tx_id],
                    detection_vector=DuplicateDetectionVector.INVOICE_REF_MATCH,
                    details={"matched_invoice_ref": invoice_ref, "matched_transaction_id": tx_id},
                )

            # Check temporal window for amount collisions
            within_window = hours_diff <= self.duplicate_window_hours or (tx_dt is None)

            # ===============================================================
            # Vector 2 & 3: Identical Net Amount Collision vs Recurring Period
            # ===============================================================
            if abs(amount - tx_amt) < 0.01:
                matched_ids.append(tx_id)

                # Disambiguate Genuine Recurring Subscriptions (CFO Q3.1)
                tx_period = _extract_billing_period_text(tx)
                curr_period = current_period or _extract_billing_period_text(invoice_ref)

                # Check if this is a recurring periodic service
                tx_is_rec = tx.get("is_recurring") is True or bool(_RECURRING_REGEX.search(tx_vendor))
                is_recurring_context = effective_recurring or tx_is_rec

                if is_recurring_context:
                    # Distinguish different billing periods (e.g. April 2026 vs March 2026)
                    if curr_period and tx_period and curr_period.lower() != tx_period.lower():
                        msg = (
                            f"Legitimate recurring periodic payment detected for vendor '{vendor_name}' "
                            f"(Billing Period: {curr_period}). Prior transaction '{tx_id}' was settled for period '{tx_period}'."
                        )
                        return DuplicateScanResult(
                            risk_level=DuplicateRiskLevel.LOW,
                            is_duplicate=False,
                            warning_message=msg,
                            matched_transaction_ids=[tx_id],
                            detection_vector=DuplicateDetectionVector.RECURRING_PERIODIC_CONFIRMED,
                            is_legitimate_recurring=True,
                            details={
                                "current_period": curr_period,
                                "prior_period": tx_period,
                                "prior_transaction_id": tx_id,
                            },
                        )

                    # Distinct calendar month check if dates are ~25-35 days apart
                    if tx_dt and 20.0 <= (abs((eval_dt - tx_dt).total_seconds()) / 86400.0) <= 40.0:
                        msg = (
                            f"Legitimate recurring periodic cycle detected for vendor '{vendor_name}'. "
                            f"Prior payment in transaction '{tx_id}' was settled {int(hours_diff / 24)} days ago."
                        )
                        return DuplicateScanResult(
                            risk_level=DuplicateRiskLevel.LOW,
                            is_duplicate=False,
                            warning_message=msg,
                            matched_transaction_ids=[tx_id],
                            detection_vector=DuplicateDetectionVector.RECURRING_PERIODIC_CONFIRMED,
                            is_legitimate_recurring=True,
                            details={"prior_transaction_id": tx_id, "days_apart": round(hours_diff / 24, 1)},
                        )

                    # If SAME billing period on a recurring bill -> Accidental Duplicate!
                    if curr_period and tx_period and curr_period.lower() == tx_period.lower():
                        msg = (
                            f"DUPLICATE RECURRING BILL DETECTED: A payment for billing period '{curr_period}' "
                            f"has already been processed in transaction '{tx_id}' for vendor '{vendor_name}'. "
                            "Accidental duplicate booking blocked."
                        )
                        return DuplicateScanResult(
                            risk_level=DuplicateRiskLevel.HIGH,
                            is_duplicate=True,
                            warning_message=msg,
                            matched_transaction_ids=[tx_id],
                            detection_vector=DuplicateDetectionVector.IDENTICAL_AMOUNT_WINDOW,
                            is_legitimate_recurring=False,
                            details={"conflicting_period": curr_period, "matched_transaction_id": tx_id},
                        )

                # Non-recurring or within immediate window with identical amount -> Accidental Duplicate!
                if within_window:
                    time_desc = f"{hours_diff:.1f} hours ago" if tx_dt else "recently"
                    msg = (
                        f"POTENTIAL ACCIDENTAL DUPLICATE: An identical disbursement of PKR {amount:,.2f} "
                        f"for vendor '{vendor_name}' was processed in transaction '{tx_id}' ({time_desc}). "
                        "Verify that this is not an accidental re-entry."
                    )
                    return DuplicateScanResult(
                        risk_level=DuplicateRiskLevel.HIGH,
                        is_duplicate=True,
                        warning_message=msg,
                        matched_transaction_ids=[tx_id],
                        detection_vector=DuplicateDetectionVector.IDENTICAL_AMOUNT_WINDOW,
                        is_legitimate_recurring=False,
                        details={"matched_amount": amount, "matched_transaction_id": tx_id, "hours_ago": hours_diff},
                    )

        # ===================================================================
        # Vector 4: Section 73 Cash Structuring / Smurfing Evasion (CFO Q3.3)
        # ===================================================================
        if "CASH" in pay_method_upper:
            prior_cash_total = sum(t["amount"] for t in recent_cash_txs)
            cumulative_cash = amount + prior_cash_total

            # Structuring condition: split cash payments under PKR 50k, but combined >= PKR 50k
            if (
                amount < self.structuring_cash_limit
                and recent_cash_txs
                and cumulative_cash >= self.structuring_cash_limit
            ):
                cash_tx_ids = [t["id"] for t in recent_cash_txs]
                msg = (
                    f"STATUTORY STRUCTURING HAZARD (Section 73 & Section 21(l) ITO 2001): "
                    f"Multiple cash payments under PKR {self.structuring_cash_limit:,.2f} to vendor '{vendor_name}' "
                    f"totaling PKR {cumulative_cash:,.2f} within {self.duplicate_window_hours} hours detected "
                    f"(Current: PKR {amount:,.2f}, Prior: PKR {prior_cash_total:,.2f} in transactions {cash_tx_ids}). "
                    "Splitting transactions to evade banking channel requirements violates Section 73 anti-avoidance rules "
                    "and incurs 100% tax deduction disallowance."
                )
                return DuplicateScanResult(
                    risk_level=DuplicateRiskLevel.HIGH,
                    is_duplicate=False,
                    warning_message=msg,
                    matched_transaction_ids=cash_tx_ids,
                    detection_vector=DuplicateDetectionVector.CASH_STRUCTURING_HAZARD,
                    is_structuring_detected=True,
                    cumulative_cash_amount=cumulative_cash,
                    details={
                        "cumulative_cash": cumulative_cash,
                        "prior_cash_total": prior_cash_total,
                        "cash_transaction_ids": cash_tx_ids,
                    },
                )

        # ===================================================================
        # Vector 5: Near-Amount Payment Anomaly (Within ±2%)
        # ===================================================================
        for tx in recent_transactions:
            if not isinstance(tx, dict):
                continue
            tx_vendor = (
                tx.get("vendor_name")
                or tx.get("supplier_name")
                or tx.get("party_name")
                or tx.get("name")
                or tx.get("vendor")
                or ""
            )
            tx_key = normalize_vendor_key(tx_vendor)
            if tx_key != target_vendor_key and target_vendor_key not in tx_key and tx_key not in target_vendor_key:
                continue

            tx_amt = round(float(tx.get("amount") or tx.get("total") or tx.get("net_amount") or 0.0), 2)
            tx_dt = _parse_dt(tx.get("created_at") or tx.get("date") or tx.get("transaction_date"))
            hours_diff = abs((eval_dt - tx_dt).total_seconds()) / 3600.0 if tx_dt else 0.0

            if hours_diff <= self.duplicate_window_hours:
                # Exclude exact match (already checked)
                if 0.01 < abs(amount - tx_amt) <= (amount * self.near_amount_tolerance):
                    tx_id = str(tx.get("id") or tx.get("transaction_id") or "UNKNOWN")
                    msg = (
                        f"NEAR-AMOUNT PAYMENT ANOMALY: A disbursement of PKR {tx_amt:,.2f} "
                        f"(within ±{int(self.near_amount_tolerance * 100)}% of current PKR {amount:,.2f}) was processed "
                        f"for vendor '{vendor_name}' in transaction '{tx_id}'. Review to ensure no duplicate billing."
                    )
                    return DuplicateScanResult(
                        risk_level=DuplicateRiskLevel.LOW,
                        is_duplicate=False,
                        warning_message=msg,
                        matched_transaction_ids=[tx_id],
                        detection_vector=DuplicateDetectionVector.NEAR_AMOUNT_ANOMALY,
                        details={"current_amount": amount, "prior_amount": tx_amt, "prior_transaction_id": tx_id},
                    )

        return DuplicateScanResult(risk_level=DuplicateRiskLevel.NONE)


# ---------------------------------------------------------------------------
# Standalone Functional Entry Points
# ---------------------------------------------------------------------------

def lookup_vendor_fingerprint(
    vendor_name: str,
    historical_records: Sequence[Dict[str, Any]],
    atl_ttl_days: int = DEFAULT_ATL_TTL_DAYS,
    as_of_date: Optional[Union[date, datetime, str]] = None,
) -> Optional[VendorFingerprint]:
    """Identify vendor historical defaults from episodic memory records.

    Suggests personalized terms in chat:
    "For Apex Supplies, you usually pay via Meezan Bank with 5% WHT deducted. Shall I use these terms?"
    """
    guard = VendorMemoryGuard(atl_ttl_days=atl_ttl_days)
    return guard.lookup_vendor_fingerprint(vendor_name, historical_records, as_of_date=as_of_date)


def check_duplicate_risk(
    vendor_name: str,
    amount: float,
    invoice_ref: Optional[str] = None,
    recent_transactions: Sequence[Dict[str, Any]] = (),
    window_hours: int = DEFAULT_DUPLICATE_WINDOW_HOURS,
    reference_date: Optional[Union[date, datetime, str]] = None,
    payment_method: Optional[str] = None,
    account_code: Optional[str] = None,
    billing_period: Optional[str] = None,
    is_recurring: Optional[bool] = None,
) -> DuplicateScanResult:
    """Proactively check duplicate transaction risk within configurable window."""
    guard = VendorMemoryGuard(duplicate_window_hours=window_hours)
    return guard.check_duplicate_risk(
        vendor_name=vendor_name,
        amount=amount,
        invoice_ref=invoice_ref,
        recent_transactions=recent_transactions,
        reference_date=reference_date,
        payment_method=payment_method,
        account_code=account_code,
        billing_period=billing_period,
        is_recurring=is_recurring,
    )
