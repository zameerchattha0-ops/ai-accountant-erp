"""Tax Service — deterministic tax calculations, authority splits, and Pakistan tax regimes.

This service is authoritative for tax calculations:
1. Sales Tax Act 1990 (FBR Federal Goods 18%)
2. Provincial Sales Tax on Services (PRA 16%, SRB 15%, KPRA 15%, BRA 15%)
3. Income Tax Ordinance 2001 Section 153 (Withholding Tax on Payments)
4. Income Tax Ordinance 2001 Section 149 (Salary Progressive Slabs)
5. Net vs. Gross & Inclusive vs. Exclusive back-calculation invariants
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple
import structlog

log = structlog.get_logger(__name__)

# Standard known tax codes mapped to rate percentages
KNOWN_TAX_RATES: Dict[str, float] = {
    # Federal Sales Tax (FBR) - Goods
    "STANDARD": 18.0,
    "GST_18": 18.0,
    "GST 18%": 18.0,
    "18%": 18.0,
    "FBR_18": 18.0,
    # Historical / Transitional
    "GST_17": 17.0,
    "GST 17%": 17.0,
    "17%": 17.0,
    # Provincial Sales Tax on Services
    "PRA_16": 16.0,
    "PRA 16%": 16.0,
    "16%": 16.0,
    "SRB_15": 15.0,
    "SRB 15%": 15.0,
    "KPRA_15": 15.0,
    "KPRA 15%": 15.0,
    "BRA_15": 15.0,
    "BRA 15%": 15.0,
    "15%": 15.0,
    # Reduced Rates & Exemptions
    "REDUCED_10": 10.0,
    "REDUCED_5": 5.0,
    "REDUCED_1": 1.0,
    "REDUCED": 5.0,
    "GST_5": 5.0,
    "GST 5%": 5.0,
    "5%": 5.0,
    "ZERO": 0.0,
    "0%": 0.0,
    "EXEMPT": 0.0,
    # Withholding Tax u/s 153 (Active Taxpayer List / ATL Statutory Rates)
    "WHT_153_GOODS_CORP": 5.0,
    "WHT_153_GOODS_INDIVIDUAL": 5.5,
    "WHT_153_SPECIFIED_SERVICES": 7.0,
    "WHT_153_IT_SERVICES": 4.0,
    "WHT_153_PROFESSIONAL_SERVICES": 15.0,
    "WHT_153_OTHER_SERVICES": 14.0,
    "WHT_153_CONTRACTS_CORP": 7.5,
    "WHT_153_CONTRACTS_INDIVIDUAL": 8.0,
    "WHT_153_ADVERTISING": 1.5,
    "WHT_SERVICES": 14.0,
    "WHT_IMPORTS": 6.0,
    "CORPORATE": 29.0,
}

# Section 153 Statutory Rate Schedule & Metadata
SECTION_153_STATUTORY_RATES: Dict[str, Dict[str, Any]] = {
    "GOODS_CORP": {
        "rate": 5.0,
        "label": "Purchase of goods – companies (5%)",
        "description": "Supplies/goods purchased from corporate vendors",
    },
    "GOODS_INDIVIDUAL": {
        "rate": 5.5,
        "label": "Purchase of goods – individuals/AOPs (5.5%)",
        "description": "Supplies/goods purchased from sole proprietors or AOPs",
    },
    "SPECIFIED_SERVICES": {
        "rate": 7.0,
        "label": "Specified services (7%)",
        "description": "Transport, freight, courier, hoteling, security, cargo services",
    },
    "IT_SERVICES": {
        "rate": 4.0,
        "label": "IT and IT-enabled services (4%)",
        "description": "Software, web development, cloud hosting, IT consulting, BPO, data services",
    },
    "PROFESSIONAL_SERVICES": {
        "rate": 15.0,
        "label": "Independent professional services (15%)",
        "description": "Legal, accounting, auditing, medical, engineering, architecture, consulting",
    },
    "OTHER_SERVICES": {
        "rate": 14.0,
        "label": "Other services (14%)",
        "description": "General services provided by companies, individuals, or AOPs",
    },
    "CONTRACTS_CORP": {
        "rate": 7.5,
        "label": "Contracts – companies (7.5%)",
        "description": "Execution of contracts by corporate entities",
    },
    "CONTRACTS_INDIVIDUAL": {
        "rate": 8.0,
        "label": "Contracts – individuals/AOPs (8%)",
        "description": "Execution of contracts by sole proprietors or AOPs",
    },
    "ADVERTISING_MEDIA": {
        "rate": 1.5,
        "label": "Advertising through print/electronic media (1.5%)",
        "description": "Print, electronic, and digital media advertising services",
    },
}


def resolve_section_153_rate(
    text_or_nature: str = "",
    payee_is_corporate: bool = False,
    has_exemption_cert: bool = False,
    custom_rate: Optional[float] = None,
) -> Tuple[float, str]:
    """Deterministically resolve Section 153 Withholding Tax rate.

    Rules:
    - If payee holds valid Section 153 Exemption Certificate: 0% WHT.
    - If custom rate explicitly provided: custom rate wins.
    - Otherwise, maps payment nature & payee type to official ATL rate:
      * IT and IT-enabled services: 4%
      * Purchase of goods – companies: 5%
      * Purchase of goods – individuals/AOPs: 5.5%
      * Specified services (freight, courier, hotel, transport): 7%
      * Contracts – companies: 7.5%
      * Contracts – individuals/AOPs: 8%
      * Independent professional services: 15%
      * Other services: 14%
      * Advertising (print/electronic media): 1.5%
    """
    if has_exemption_cert:
        return 0.0, "EXEMPT"

    if custom_rate is not None:
        r = float(custom_rate)
        return r, "CUSTOM"

    t = (text_or_nature or "").lower()

    # 1. Advertising / Media
    if any(k in t for k in ("advertis", "print media", "electronic media", "billboard", "tv ad", "newspaper ad")):
        return 1.5, "ADVERTISING_MEDIA"

    # 2. IT and IT-enabled services (4%)
    if any(k in t for k in ("it_service", "it service", "it consult", "software", "web develop", "web design", "programming", "cloud", "saas", "hosting", "it enabled", "bpo", "data entry", "computer", "information technology")):
        return 4.0, "IT_SERVICES"

    # 3. Independent professional services (15%)
    if any(k in t for k in ("legal", "lawyer", "advocate", "audit", "chartered account", "accountant", "doctor", "medical", "architect", "engineer", "professional fee", "professional consult")):
        return 15.0, "PROFESSIONAL_SERVICES"

    # 4. Specified services (7%)
    if any(k in t for k in ("transport", "freight", "courier", "cargo", "hotel", "security guard", "security service", "tracking", "clearing agent")):
        return 7.0, "SPECIFIED_SERVICES"

    # 5. Contracts (7.5% corp / 8% ind)
    if any(k in t for k in ("contract", "construction", "civil work", "fabrication", "turnkey")):
        return (7.5, "CONTRACTS_CORP") if payee_is_corporate else (8.0, "CONTRACTS_INDIVIDUAL")

    # 6. Goods / Supplies (5% corp / 5.5% ind)
    if any(k in t for k in ("goods", "product", "supplies", "material", "inventory", "hardware", "furniture", "stationery", "toner", "paper", "equipment", "parts")):
        return (5.0, "GOODS_CORP") if payee_is_corporate else (5.5, "GOODS_INDIVIDUAL")

    # 7. Other services default (14%)
    if any(k in t for k in ("service", "consulting", "maintenance", "repair", "cleaning", "cater")):
        return 14.0, "OTHER_SERVICES"

    # Fallback: Goods vs Corporate default
    return (5.0, "GOODS_CORP") if payee_is_corporate else (5.5, "GOODS_INDIVIDUAL")


def evaluate_input_tax_treatment(
    subtotal: float,
    sales_tax_amount: float,
    supplier_has_strn: bool = False,
    org_is_registered: bool = True,
) -> Dict[str, Any]:
    """Evaluate GST / Sales Tax input treatment under Sales Tax Act 1990.

    Statutory Invariant:
    - Input tax on purchase of goods is an ASSET (Sales Tax Recoverable / Input Tax),
      claimable against output sales tax liabilities.
    - S. 8 & S. 73 Restriction: Input tax can ONLY be recorded/claimed as an asset if
      purchased from a REGISTERED person (valid Sales Tax Registration Number / STRN).
    - If purchased from an UNREGISTERED vendor, input tax CANNOT be recorded or claimed
      as an asset; the full cost must be capitalized into inventory/expense cost.
    """
    sub = round(float(subtotal or 0.0), 2)
    tax = round(float(sales_tax_amount or 0.0), 2)

    if not org_is_registered:
        return {
            "can_claim_input_tax": False,
            "input_tax_asset": 0.0,
            "inventory_or_expense_cost": round(sub + tax, 2),
            "reason": "Organization is not registered for Sales Tax with FBR/provincial authority. Input tax cannot be claimed.",
        }

    if not supplier_has_strn:
        return {
            "can_claim_input_tax": False,
            "input_tax_asset": 0.0,
            "inventory_or_expense_cost": round(sub + tax, 2),
            "reason": "Supplier is not registered for Sales Tax (No active STRN). Under Section 8 of Sales Tax Act 1990, input tax cannot be claimed as an asset and is absorbed into cost.",
        }

    return {
        "can_claim_input_tax": True,
        "input_tax_asset": tax,
        "inventory_or_expense_cost": sub,
        "asset_account_code": "1060",
        "asset_account_name": "Input Sales Tax Recoverable",
        "reason": "Valid registered supplier: Input sales tax is recognized as an Asset / Tax Recoverable to offset against output sales tax.",
    }

# Authority default rates
AUTHORITY_DEFAULT_RATES: Dict[str, float] = {
    "FBR": 18.0,
    "PRA": 16.0,
    "SRB": 15.0,
    "KPRA": 15.0,
    "BRA": 15.0,
    "ICT": 15.0,
}


def calculate_tax(
    subtotal: float,
    tax_code: Optional[str] = None,
    tax_rate_percent: Optional[float] = None,
) -> float:
    """Deterministically calculate expected tax on a subtotal.

    Tax is calculated via exact percentage, rounded to 2 decimal places.
    Authority Split Rule: Python logic is authoritative over OCR/LLM tax amounts.
    """
    subtotal = float(subtotal or 0.0)
    if subtotal <= 0:
        return 0.0

    rate = 0.0
    if tax_rate_percent is not None:
        rate = float(tax_rate_percent)
    elif tax_code:
        code_key = str(tax_code).strip().upper()
        rate = KNOWN_TAX_RATES.get(code_key, 0.0)

    computed = round(subtotal * (rate / 100.0), 2)
    return computed


def calculate_tax_split(
    amount: float,
    rate_percent: float = 18.0,
    pricing_mode: str = "EXCLUSIVE",
) -> Dict[str, Any]:
    """Calculate net revenue, tax amount, and gross total based on pricing mode.

    Modes:
    - EXCLUSIVE: `amount` is net of tax. Tax is added on top.
      net = amount, tax = amount * (rate / 100), gross = net + tax
    - INCLUSIVE: `amount` is gross (already contains tax). Net is back-calculated.
      net = round(amount / (1 + rate / 100), 2), tax = round(amount - net, 2), gross = amount
    - EXEMPT / ZERO: 0% tax.
      net = amount, tax = 0.0, gross = amount

    Returns:
        dict(net_amount, tax_amount, gross_amount, rate_percent, pricing_mode)
    """
    total = round(float(amount or 0.0), 2)
    rate = round(float(rate_percent or 0.0), 2)
    mode = str(pricing_mode or "EXCLUSIVE").strip().upper()

    if total <= 0 or mode in ("EXEMPT", "ZERO") or rate <= 0:
        return {
            "net_amount": total,
            "tax_amount": 0.0,
            "gross_amount": total,
            "rate_percent": 0.0,
            "pricing_mode": mode if mode in ("EXEMPT", "ZERO") else "EXEMPT",
        }

    if mode == "INCLUSIVE":
        # Back-calculate net: Net = Total / (1 + rate/100)
        net = round(total / (1.0 + (rate / 100.0)), 2)
        tax = round(total - net, 2)
        return {
            "net_amount": net,
            "tax_amount": tax,
            "gross_amount": total,
            "rate_percent": rate,
            "pricing_mode": "INCLUSIVE",
        }

    # Default is EXCLUSIVE: Net is base, tax added on top
    net = total
    tax = round(net * (rate / 100.0), 2)
    gross = round(net + tax, 2)
    return {
        "net_amount": net,
        "tax_amount": tax,
        "gross_amount": gross,
        "rate_percent": rate,
        "pricing_mode": "EXCLUSIVE",
    }


def calculate_salary_tax_withholding(
    monthly_gross: float,
) -> Dict[str, Any]:
    """Calculate Section 149 statutory salary income tax withholding.

    Based on the official 8 progressive annual tax slabs for salaried individuals:
    Slab 1: Up to 600,000                   -> 0% (Exempt)
    Slab 2: 600,001 to 1,200,000            -> 1% of amount over 600,000
    Slab 3: 1,200,001 to 2,200,000          -> 6,000 + 11% of amount over 1,200,000
    Slab 4: 2,200,001 to 3,200,000          -> 116,000 + 20% of amount over 2,200,000
    Slab 5: 3,200,001 to 4,100,000          -> 316,000 + 25% of amount over 3,200,000
    Slab 6: 4,100,001 to 5,600,000          -> 541,000 + 29% of amount over 4,100,000
    Slab 7: 5,600,001 to 7,000,000          -> 976,000 + 32% of amount over 5,600,000
    Slab 8: Exceeding 7,000,000             -> 1,424,000 + 35% of amount over 7,000,000

    Monthly Tax Withheld = Annual Tax / 12.
    """
    monthly = round(float(monthly_gross or 0.0), 2)
    if monthly <= 0:
        return {
            "monthly_tax": 0.0,
            "annual_tax": 0.0,
            "slab": 1,
            "annual_income": 0.0,
            "monthly_gross": 0.0,
            "effective_rate_percent": 0.0,
        }

    annual_income = round(monthly * 12.0, 2)

    if annual_income <= 600000.0:
        slab = 1
        annual_tax = 0.0
    elif annual_income <= 1200000.0:
        slab = 2
        annual_tax = (annual_income - 600000.0) * 0.01
    elif annual_income <= 2200000.0:
        slab = 3
        annual_tax = 6000.0 + ((annual_income - 1200000.0) * 0.11)
    elif annual_income <= 3200000.0:
        slab = 4
        annual_tax = 116000.0 + ((annual_income - 2200000.0) * 0.20)
    elif annual_income <= 4100000.0:
        slab = 5
        annual_tax = 316000.0 + ((annual_income - 3200000.0) * 0.25)
    elif annual_income <= 5600000.0:
        slab = 6
        annual_tax = 541000.0 + ((annual_income - 4100000.0) * 0.29)
    elif annual_income <= 7000000.0:
        slab = 7
        annual_tax = 976000.0 + ((annual_income - 5600000.0) * 0.32)
    else:
        slab = 8
        annual_tax = 1424000.0 + ((annual_income - 7000000.0) * 0.35)

    annual_tax = round(max(annual_tax, 0.0), 2)
    monthly_tax = round(annual_tax / 12.0, 2)
    effective_rate = round((annual_tax / annual_income) * 100.0, 2) if annual_income > 0 else 0.0

    return {
        "monthly_tax": monthly_tax,
        "annual_tax": annual_tax,
        "slab": slab,
        "annual_income": annual_income,
        "monthly_gross": monthly,
        "effective_rate_percent": effective_rate,
    }


def evaluate_tax_deviation(
    subtotal: float,
    printed_tax: Optional[float],
    tax_code: Optional[str] = None,
    tax_rate_percent: Optional[float] = None,
    tolerance: float = 1.0,
) -> Tuple[bool, float, float]:
    """Check if printed/extracted tax deviates materially from computed tax.

    Returns:
        (is_material_deviation, computed_tax, diff)
    """
    if printed_tax is None:
        return False, 0.0, 0.0

    computed = calculate_tax(
        subtotal, tax_code=tax_code, tax_rate_percent=tax_rate_percent
    )
    diff = abs(float(printed_tax) - computed)
    is_material = (
        tax_code is not None or tax_rate_percent is not None
    ) and (diff > tolerance)
    return is_material, computed, diff


# ---------------------------------------------------------------------------
# Organization Tax Profile & Preference Persistence
# ---------------------------------------------------------------------------

KEY_IS_SALES_TAX_REGISTERED = "is_sales_tax_registered"
KEY_TAX_AUTHORITY = "tax_authority"
KEY_DEFAULT_TAX_PRICING = "default_tax_pricing"
KEY_SALES_TAX_RATE = "sales_tax_rate"


async def get_organization_tax_profile(
    organization_id: uuid.UUID,
) -> Dict[str, Any]:
    """Get durable tax settings for an organisation.

    If an organisation is NOT registered for sales tax, sales tax cannot
    be charged and input sales tax cannot be claimed.
    """
    from app.services import preference_service
    from app.repositories import organization_repository

    org = await organization_repository.get_organization(organization_id=organization_id) or {}
    prefs = await preference_service.get_all_preferences(organization_id)

    # Tax registration check: preference wins, or inferred from tax_number / registration_number
    registered_pref = prefs.get(KEY_IS_SALES_TAX_REGISTERED)
    if registered_pref is not None:
        is_registered = str(registered_pref).strip().lower() in ("true", "1", "yes")
    else:
        # Default to False unless explicit tax_number (STRN) is configured
        tax_num = str(org.get("tax_number") or "").strip()
        is_registered = bool(tax_num and len(tax_num) >= 7)

    authority = (prefs.get(KEY_TAX_AUTHORITY) or "FBR").strip().upper()
    default_pricing = (prefs.get(KEY_DEFAULT_TAX_PRICING) or "EXCLUSIVE").strip().upper()

    default_rate = float(
        prefs.get(KEY_SALES_TAX_RATE)
        or AUTHORITY_DEFAULT_RATES.get(authority, 18.0)
    )

    org_strn = org.get("strn") or org.get("tax_number")
    org_gst_status = org.get("sales_tax_status")
    if not org_gst_status:
        if is_registered:
            org_gst_status = "REGISTERED_ACTIVE"
        else:
            org_gst_status = "UNREGISTERED"

    return {
        "organization_id": str(organization_id),
        "is_sales_tax_registered": is_registered,
        "strn": org_strn,
        "sales_tax_status": org_gst_status,
        "tax_authority": authority,
        "default_tax_pricing": default_pricing,
        "sales_tax_rate": default_rate if is_registered else 0.0,
        "tax_number": org.get("tax_number"),
    }


# =====================================================================
# Sales Tax Act 1990 Scenario Matrices (P-01 to P-07 & S-01 to S-06)
# =====================================================================

class GSTPartyStatus:
    REGISTERED_ACTIVE = "REGISTERED_ACTIVE"
    REGISTERED_INACTIVE = "REGISTERED_INACTIVE"
    UNREGISTERED = "UNREGISTERED"


def normalize_gst_status(status: Optional[str]) -> str:
    s = str(status or "").strip().upper()
    if any(k in s for k in ("INACTIVE", "SUSPENDED", "BLACKLISTED", "NON_ACTIVE", "NON-ACTIVE")):
        return GSTPartyStatus.REGISTERED_INACTIVE
    if any(k in s for k in ("ACTIVE", "ATL")):
        return GSTPartyStatus.REGISTERED_ACTIVE
    return GSTPartyStatus.UNREGISTERED


def evaluate_purchase_gst_matrix(
    buyer_status: str,
    supplier_status: str,
    subtotal: float,
    ordinary_rate: float = 18.0,
) -> Dict[str, Any]:
    """Execute complete Purchase-Side GST Matrix (P-01 to P-07) under Sales Tax Act 1990.

    P-01: Active buyer + Active supplier -> Applicable 18% GST, claimable Input Tax (Asset 1060).
    P-02: Active buyer + Inactive supplier -> Applicable, but Input Tax held under compliance review.
    P-03: Active buyer + Unregistered supplier -> Supplier cannot charge GST, No Input Tax, NO 4% further tax.
    P-04: Inactive buyer + Active supplier -> Applicable, but buyer input tax eligibility requires separate review.
    P-05: Inactive buyer + Inactive supplier -> Verify supplier compliance, input tax held.
    P-06: Inactive buyer + Unregistered supplier -> No ordinary GST, no input tax claimable.
    P-07: Unregistered buyer + Active supplier -> Supplier charges 18% GST (and 4% Further Tax under S.3(1A)).
          Buyer CANNOT claim input tax; total gross amount capitalized into inventory/purchase cost.
    P-08/P-09: Unregistered buyer + Inactive/Unregistered supplier -> No ordinary input tax claimable.
    """
    b_st = normalize_gst_status(buyer_status)
    s_st = normalize_gst_status(supplier_status)
    sub = round(float(subtotal or 0.0), 2)
    rate = float(ordinary_rate or 18.0)

    # P-01: Both registered and active
    if b_st == GSTPartyStatus.REGISTERED_ACTIVE and s_st == GSTPartyStatus.REGISTERED_ACTIVE:
        gst_amt = round(sub * (rate / 100.0), 2)
        return {
            "rule_code": "P-01",
            "ordinary_gst_rate": rate,
            "ordinary_gst_amount": gst_amt,
            "input_tax_eligible": True,
            "input_tax_asset_amount": gst_amt,
            "inventory_or_expense_cost": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": round(sub + gst_amt, 2),
            "requires_compliance_review": False,
            "advisory": (
                "P-01: Both buyer and supplier are registered and active on FBR ATL. "
                f"Ordinary {rate}% GST is applicable. Input tax of Rs. {gst_amt:,.2f} is recognized "
                "as an Asset (Account 1060: Input Sales Tax Recoverable) claimable against output tax, "
                "subject to Section 73 banking channel verification."
            ),
        }

    # P-02: Buyer active, supplier registered but inactive
    if b_st == GSTPartyStatus.REGISTERED_ACTIVE and s_st == GSTPartyStatus.REGISTERED_INACTIVE:
        gst_amt = round(sub * (rate / 100.0), 2)
        return {
            "rule_code": "P-02",
            "ordinary_gst_rate": rate,
            "ordinary_gst_amount": gst_amt,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "inventory_or_expense_cost": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": round(sub + gst_amt, 2),
            "requires_compliance_review": True,
            "advisory": (
                "P-02: Supplier is registered but INACTIVE/SUSPENDED on FBR Sales Tax ATL. "
                "Input tax cannot be automatically approved or claimed. Verify whether supplier was "
                "active on invoice date and check tax-deposit compliance before approving input adjustment."
            ),
        }

    # P-03: Buyer active, supplier unregistered
    if b_st == GSTPartyStatus.REGISTERED_ACTIVE and s_st == GSTPartyStatus.UNREGISTERED:
        return {
            "rule_code": "P-03",
            "ordinary_gst_rate": 0.0,
            "ordinary_gst_amount": 0.0,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "inventory_or_expense_cost": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": sub,
            "requires_compliance_review": False,
            "advisory": (
                "P-03: Supplier is UNREGISTERED. Unregistered suppliers cannot legally issue FBR tax invoices "
                "or charge GST. Input tax is zero. Do not apply 4% Further Tax to the purchase merely because "
                "the supplier is unregistered. Total invoice is booked to inventory/expense cost."
            ),
        }

    # P-04: Buyer registered but inactive, supplier active
    if b_st == GSTPartyStatus.REGISTERED_INACTIVE and s_st == GSTPartyStatus.REGISTERED_ACTIVE:
        gst_amt = round(sub * (rate / 100.0), 2)
        return {
            "rule_code": "P-04",
            "ordinary_gst_rate": rate,
            "ordinary_gst_amount": gst_amt,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "inventory_or_expense_cost": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": round(sub + gst_amt, 2),
            "requires_compliance_review": True,
            "advisory": (
                "P-04: Buyer organization is registered but INACTIVE/SUSPENDED on ATL. Ordinary input adjustment "
                "rights are restricted. Hold input tax approval pending resolution of company registration status."
            ),
        }

    # P-05: Both registered but inactive
    if b_st == GSTPartyStatus.REGISTERED_INACTIVE and s_st == GSTPartyStatus.REGISTERED_INACTIVE:
        gst_amt = round(sub * (rate / 100.0), 2)
        return {
            "rule_code": "P-05",
            "ordinary_gst_rate": rate,
            "ordinary_gst_amount": gst_amt,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "inventory_or_expense_cost": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": round(sub + gst_amt, 2),
            "requires_compliance_review": True,
            "advisory": "P-05: Both parties are inactive on FBR ATL. Input tax deduction held under compliance review.",
        }

    # P-06: Buyer inactive, supplier unregistered
    if b_st == GSTPartyStatus.REGISTERED_INACTIVE and s_st == GSTPartyStatus.UNREGISTERED:
        return {
            "rule_code": "P-06",
            "ordinary_gst_rate": 0.0,
            "ordinary_gst_amount": 0.0,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "inventory_or_expense_cost": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": sub,
            "requires_compliance_review": False,
            "advisory": "P-06: Unregistered supplier cannot charge GST. Buyer inactive. Entire amount booked to cost.",
        }

    # P-07: Buyer unregistered, supplier registered and active
    if b_st == GSTPartyStatus.UNREGISTERED and s_st == GSTPartyStatus.REGISTERED_ACTIVE:
        gst_amt = round(sub * (rate / 100.0), 2)
        further_rate = 4.0
        further_amt = round(sub * (further_rate / 100.0), 2)
        total_tax = round(gst_amt + further_amt, 2)
        gross = round(sub + total_tax, 2)
        return {
            "rule_code": "P-07",
            "ordinary_gst_rate": rate,
            "ordinary_gst_amount": gst_amt,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "inventory_or_expense_cost": gross,
            "further_tax_rate": further_rate,
            "further_tax_amount": further_amt,
            "gross_total": gross,
            "requires_compliance_review": False,
            "advisory": (
                "P-07: Buyer is UNREGISTERED. Active supplier charges ordinary 18% GST and 4% Further Tax under S.3(1A). "
                "Buyer CANNOT claim input tax. Total gross amount (including Rs. "
                f"{total_tax:,.2f} tax) is capitalized into inventory/purchase cost."
            ),
        }

    # P-08 / P-09: Buyer unregistered, supplier inactive or unregistered
    return {
        "rule_code": "P-09" if s_st == GSTPartyStatus.UNREGISTERED else "P-08",
        "ordinary_gst_rate": 0.0,
        "ordinary_gst_amount": 0.0,
        "input_tax_eligible": False,
        "input_tax_asset_amount": 0.0,
        "inventory_or_expense_cost": sub,
        "further_tax_rate": 0.0,
        "further_tax_amount": 0.0,
        "gross_total": sub,
        "requires_compliance_review": False,
        "advisory": "P-09: Neither party is registered. No ordinary FBR GST or input tax claim can be created.",
    }


def evaluate_sales_gst_matrix(
    seller_status: str,
    customer_status: str,
    subtotal: float,
    ordinary_rate: float = 18.0,
) -> Dict[str, Any]:
    """Execute complete Sales-Side GST Matrix (S-01 to S-06) under Sales Tax Act 1990.

    S-01: Active seller to Active buyer -> 18% ordinary GST, 0% Further Tax.
    S-02: Active seller to Inactive buyer -> 18% ordinary GST, 4% Further Tax under S.3(1A).
    S-03: Active seller to Unregistered buyer -> 18% ordinary GST, 4% Further Tax under S.3(1A).
    S-04: Inactive seller -> Compliance review required before issuing normal GST invoice.
    S-05: Unregistered seller -> Cannot charge FBR GST or Further Tax. Total price is commercial revenue.
    """
    s_st = normalize_gst_status(seller_status)
    c_st = normalize_gst_status(customer_status)
    sub = round(float(subtotal or 0.0), 2)
    rate = float(ordinary_rate or 18.0)

    # S-05 / S-06: Seller is unregistered
    if s_st == GSTPartyStatus.UNREGISTERED:
        return {
            "rule_code": "S-05" if c_st != GSTPartyStatus.UNREGISTERED else "S-06",
            "ordinary_gst_rate": 0.0,
            "ordinary_gst_amount": 0.0,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "total_tax_amount": 0.0,
            "gross_total": sub,
            "requires_compliance_review": False,
            "advisory": (
                "S-05: Seller company is NOT registered for Sales Tax. The company cannot legally charge FBR GST "
                "or Further Tax. Total amount is recognized as commercial sales revenue without sales tax."
            ),
        }

    # S-04: Seller is registered but inactive / suspended
    if s_st == GSTPartyStatus.REGISTERED_INACTIVE:
        return {
            "rule_code": "S-04",
            "ordinary_gst_rate": 0.0,
            "ordinary_gst_amount": 0.0,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "total_tax_amount": 0.0,
            "gross_total": sub,
            "requires_compliance_review": True,
            "advisory": (
                "S-04: Seller registration is INACTIVE/SUSPENDED on FBR ATL. Cannot issue a normal GST invoice or collect "
                "sales tax without establishing legal authority. Hold sales invoice pending tax compliance review."
            ),
        }

    # Active registered seller:
    # S-01: Customer is active
    if c_st == GSTPartyStatus.REGISTERED_ACTIVE:
        gst_amt = round(sub * (rate / 100.0), 2)
        return {
            "rule_code": "S-01",
            "ordinary_gst_rate": rate,
            "ordinary_gst_amount": gst_amt,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "total_tax_amount": gst_amt,
            "gross_total": round(sub + gst_amt, 2),
            "requires_compliance_review": False,
            "advisory": (
                f"S-01: Active registered seller to active registered buyer. Applicable {rate}% GST charged (Rs. {gst_amt:,.2f}). "
                "Further Tax is 0%. Official FBR Sales Tax invoice issued."
            ),
        }

    # S-02: Customer is registered but INACTIVE on ATL
    if c_st == GSTPartyStatus.REGISTERED_INACTIVE:
        gst_amt = round(sub * (rate / 100.0), 2)
        further_rate = 4.0
        further_amt = round(sub * (further_rate / 100.0), 2)
        tot_tax = round(gst_amt + further_amt, 2)
        return {
            "rule_code": "S-02",
            "ordinary_gst_rate": rate,
            "ordinary_gst_amount": gst_amt,
            "further_tax_rate": further_rate,
            "further_tax_amount": further_amt,
            "total_tax_amount": tot_tax,
            "gross_total": round(sub + tot_tax, 2),
            "requires_compliance_review": False,
            "advisory": (
                f"S-02: Customer is registered but INACTIVE on FBR ATL. Ordinary {rate}% GST applies (Rs. {gst_amt:,.2f}), "
                f"plus 4% Further Tax under Section 3(1A) of Sales Tax Act 1990 (Rs. {further_amt:,.2f}). "
                "Further tax is recorded separately to Account 2135 Further Tax Payable."
            ),
        }

    # S-03: Customer is UNREGISTERED
    gst_amt = round(sub * (rate / 100.0), 2)
    further_rate = 4.0
    further_amt = round(sub * (further_rate / 100.0), 2)
    tot_tax = round(gst_amt + further_amt, 2)
    return {
        "rule_code": "S-03",
        "ordinary_gst_rate": rate,
        "ordinary_gst_amount": gst_amt,
        "further_tax_rate": further_rate,
        "further_tax_amount": further_amt,
        "total_tax_amount": tot_tax,
        "gross_total": round(sub + tot_tax, 2),
        "requires_compliance_review": False,
        "advisory": (
            f"S-03: Supplies to UNREGISTERED buyer. Ordinary {rate}% GST applies (Rs. {gst_amt:,.2f}), "
            f"plus statutory 4% Further Tax under Section 3(1A) of Sales Tax Act 1990 (Rs. {further_amt:,.2f}). "
            "Total tax = 22%. Further Tax recorded separately to Account 2135 Further Tax Payable."
        ),
    }


# =====================================================================
# Provincial Sales Tax on Services (PRA, SRB, KPRA, BRA, ICT)
# Sector Regimes, 0% Further Tax Invariant & Dual Withholding (Wh-ST + S.153)
# =====================================================================

class TaxAuthority:
    FBR = "FBR"      # Federal (Goods 18%, ICT Services, Customs, S.153 Income Tax WHT)
    PRA = "PRA"      # Punjab Revenue Authority (Punjab Sales Tax on Services Act 2012 - 16%)
    SRB = "SRB"      # Sindh Revenue Board (Sindh Sales Tax on Services Act 2011 - 15%)
    KPRA = "KPRA"    # Khyber Pakhtunkhwa Revenue Authority (KP Finance Act 2013 - 15%)
    BRA = "BRA"      # Balochistan Revenue Authority (Balochistan Sales Tax on Services Act 2015 - 15%)
    ICT = "ICT"      # Islamabad Capital Territory (ICT Tax on Services Ordinance 2001 - 15%)


class SupplyNature:
    GOODS = "GOODS"
    SERVICE = "SERVICE"


def normalize_tax_authority(authority: Optional[str]) -> str:
    """Normalize tax authority string to canonical authority constant."""
    a = str(authority or "").strip().upper()
    if "PUNJAB" in a or "PRA" in a:
        return TaxAuthority.PRA
    if "SINDH" in a or "SRB" in a:
        return TaxAuthority.SRB
    if "KHYBER" in a or "KPRA" in a or "KPK" in a or "KP" in a:
        return TaxAuthority.KPRA
    if "BALOCH" in a or "BRA" in a:
        return TaxAuthority.BRA
    if "ISLAMABAD" in a or "ICT" in a:
        return TaxAuthority.ICT
    return TaxAuthority.FBR


def classify_supply_nature(text_or_nature: str = "") -> str:
    """Classify whether a transaction/item is a SERVICE or GOODS.

    Statutory Invariant (18th Constitutional Amendment):
    - GOODS fall under Federal jurisdiction (FBR Sales Tax Act 1990).
      Section 3(1A) 4% Further Tax applies on supplies of goods to unregistered persons.
    - SERVICES fall under Provincial jurisdiction (PRA, SRB, KPRA, BRA, ICT).
      Section 3(1A) 4% Further Tax NEVER applies to services under provincial law.
    """
    t = str(text_or_nature or "").lower()

    # Explicit service indicators
    if any(k in t for k in (
        "service", "consult", "software", "development", "repair", "maintenance",
        "install", "freight", "transport", "courier", "audit", "legal", "cater",
        "hotel", "cleaning", "construction", "civil work", "marketing", "advertis",
        "hosting", "cloud", "saas", "telecom", "security guard", "training",
        "medical", "engineering", "architecture", "commission", "brokerage",
        "contract", "turnkey", "labour", "hire", "fee", "retainer"
    )):
        return SupplyNature.SERVICE

    # Explicit goods indicators
    if any(k in t for k in (
        "goods", "product", "material", "supplies", "stationery", "furniture",
        "chair", "table", "laptop", "computer", "hardware", "toner", "paper",
        "inventory", "stock", "raw material", "equipment", "parts", "consumable",
        "vehicle", "machinery", "asset"
    )):
        return SupplyNature.GOODS

    return SupplyNature.GOODS


def classify_service_sector(text_or_nature: str = "") -> str:
    """Classify specific service sector for provincial tariff and withholding determination."""
    t = str(text_or_nature or "").lower()
    if any(k in t for k in ("it consult", "software", "web develop", "web design", "programming", "cloud", "saas", "hosting", "bpo", "data entry", "it enabled", "computer")):
        return "IT_SERVICES"
    if any(k in t for k in ("construction", "civil work", "building contractor", "renovation", "fabrication", "turnkey")):
        return "CONSTRUCTION"
    if any(k in t for k in ("restaurant", "food", "cafe", "catering", "hotel", "guest house", "banquet")):
        return "RESTAURANT_HOTEL"
    if any(k in t for k in ("advertis", "billboard", "print media", "electronic media", "commercial ad", "tv commercial")):
        return "ADVERTISING"
    if any(k in t for k in ("transport", "freight", "cargo", "courier", "logistics", "shipping")):
        return "TRANSPORT_CARGO"
    if any(k in t for k in ("telecom", "cellular", "bandwidth", "leased line", "internet service")):
        return "TELECOM"
    return "GENERAL_SERVICES"


# Sector-specific provincial rate schedules (Standard vs Reduced Schemes)
PROVINCIAL_SECTOR_RATES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "IT_SERVICES": {
        "SRB": {
            "standard_rate": 15.0,
            "reduced_rate": 3.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "Sindh Sales Tax on Services Act 2011, Tariff heading 9815.6000",
            "notes": "Option for 3% reduced rate without input tax claim OR 15% standard rate with input tax credit.",
        },
        "PRA": {
            "standard_rate": 16.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "Punjab Sales Tax on Services Act 2012, Second Schedule",
            "notes": "Option for 5% reduced rate without input tax claim OR 16% standard rate with input tax credit.",
        },
        "KPRA": {
            "standard_rate": 15.0,
            "reduced_rate": 2.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "KP Finance Act 2013, Schedule II",
            "notes": "2% reduced schedule for IT & IT-enabled services without input tax adjustment.",
        },
        "BRA": {
            "standard_rate": 15.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "Balochistan Sales Tax on Services Act 2015",
            "notes": "15% standard rate or 5% reduced rate without input tax.",
        },
        "ICT": {
            "standard_rate": 15.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "ICT Tax on Services Ordinance 2001",
            "notes": "15% standard rate or 5% reduced rate without input tax.",
        },
    },
    "CONSTRUCTION": {
        "PRA": {
            "standard_rate": 16.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "PSTSA 2012, Heading 9824.0000",
            "notes": "5% reduced rate on gross value without input tax credit OR 16% with input tax.",
        },
        "SRB": {
            "standard_rate": 15.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "SSTSA 2011, Heading 9824.0000",
            "notes": "5% reduced rate on gross value without input tax credit OR 15% with input tax.",
        },
        "KPRA": {
            "standard_rate": 15.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "KP Finance Act 2013",
            "notes": "5% reduced rate for civil work contractors.",
        },
        "BRA": {"standard_rate": 15.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "BRA 2015", "notes": ""},
        "ICT": {"standard_rate": 15.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "ICT 2001", "notes": ""},
    },
    "RESTAURANT_HOTEL": {
        "PRA": {
            "standard_rate": 16.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "PSTSA 2012, Heading 9801.2000",
            "notes": "5% reduced rate for cash / POS / e-IMS integration without input tax; 16% standard for non-POS.",
        },
        "SRB": {
            "standard_rate": 15.0,
            "reduced_rate": 8.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "SSTSA 2011, Heading 9801.2000",
            "notes": "8% on integrated POS card payments; 15% standard.",
        },
        "KPRA": {
            "standard_rate": 15.0,
            "reduced_rate": 5.0,
            "reduced_allows_input_tax": False,
            "statutory_ref": "KP Finance Act 2013",
            "notes": "5% or 8% reduced rate depending on tier.",
        },
        "BRA": {"standard_rate": 15.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "BRA 2015", "notes": ""},
        "ICT": {"standard_rate": 15.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "ICT 2001", "notes": ""},
    },
    "ADVERTISING": {
        "PRA": {"standard_rate": 16.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "PSTSA 2012", "notes": "Subject to 100% sales tax withholding by withholding agents."},
        "SRB": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "SSTSA 2011", "notes": "Subject to 100% sales tax withholding by withholding agents."},
        "KPRA": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "KP Finance Act 2013", "notes": "Subject to withholding."},
        "BRA": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "BRA 2015", "notes": ""},
        "ICT": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "ICT 2001", "notes": ""},
    },
    "TRANSPORT_CARGO": {
        "PRA": {"standard_rate": 16.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "PSTSA 2012", "notes": "5% reduced rate without input tax claim."},
        "SRB": {"standard_rate": 15.0, "reduced_rate": 3.0, "reduced_allows_input_tax": False, "statutory_ref": "SSTSA 2011", "notes": "3% or fixed tariff on inter-city carriage."},
        "KPRA": {"standard_rate": 15.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "KP Finance Act 2013", "notes": "5% reduced."},
        "BRA": {"standard_rate": 15.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "BRA 2015", "notes": ""},
        "ICT": {"standard_rate": 15.0, "reduced_rate": 5.0, "reduced_allows_input_tax": False, "statutory_ref": "ICT 2001", "notes": ""},
    },
    "TELECOM": {
        "PRA": {"standard_rate": 19.5, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "PSTSA 2012", "notes": "19.5% telecommunications tariff."},
        "SRB": {"standard_rate": 19.5, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "SSTSA 2011", "notes": "19.5% telecommunications tariff."},
        "KPRA": {"standard_rate": 19.5, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "KP Finance Act 2013", "notes": "19.5% telecommunications tariff."},
        "BRA": {"standard_rate": 19.5, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "BRA 2015", "notes": "19.5% telecommunications tariff."},
        "ICT": {"standard_rate": 19.5, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "ICT 2001", "notes": "19.5% telecommunications tariff."},
    },
    "GENERAL_SERVICES": {
        "PRA": {"standard_rate": 16.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "PSTSA 2012", "notes": "16% standard PRA services rate."},
        "SRB": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "SSTSA 2011", "notes": "15% standard SRB services rate."},
        "KPRA": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "KP Finance Act 2013", "notes": "15% standard KPRA services rate."},
        "BRA": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "BRA 2015", "notes": "15% standard BRA services rate."},
        "ICT": {"standard_rate": 15.0, "reduced_rate": None, "reduced_allows_input_tax": True, "statutory_ref": "ICT 2001", "notes": "15% standard ICT services rate."},
    },
}


def resolve_provincial_service_rate(
    authority: str,
    sector: str = "GENERAL_SERVICES",
    use_reduced_rate: bool = False,
) -> Tuple[float, bool, str]:
    """Resolve applicable service tax rate, input tax eligibility, and statutory reference.

    Returns:
        (rate_percentage, input_tax_admissible, statutory_reference)
    """
    auth = normalize_tax_authority(authority)
    if auth == TaxAuthority.FBR:
        # Federal services default to ICT rate (15%)
        auth = TaxAuthority.ICT

    sec_data = PROVINCIAL_SECTOR_RATES.get(sector, PROVINCIAL_SECTOR_RATES["GENERAL_SERVICES"])
    auth_data = sec_data.get(auth, sec_data.get(TaxAuthority.PRA, {"standard_rate": 16.0, "reduced_rate": None, "reduced_allows_input_tax": True}))

    if use_reduced_rate and auth_data.get("reduced_rate") is not None:
        return (
            float(auth_data["reduced_rate"]),
            bool(auth_data.get("reduced_allows_input_tax", False)),
            auth_data.get("statutory_ref", f"{auth} Reduced Tariff"),
        )

    return (
        float(auth_data.get("standard_rate", 16.0 if auth == TaxAuthority.PRA else 15.0)),
        True,
        auth_data.get("statutory_ref", f"{auth} Standard Tariff"),
    )


def evaluate_provincial_services_purchase_matrix(
    buyer_status: str,
    supplier_status: str,
    subtotal: float,
    authority: str = "PRA",
    sector: str = "GENERAL_SERVICES",
    use_reduced_rate: bool = False,
) -> Dict[str, Any]:
    """Execute complete Purchase-Side Provincial Services Tax Matrix (PS-01 to PS-06).

    Statutory Invariants:
    1. ZERO FURTHER TAX: Section 3(1A) 4% Further Tax strictly applies to Federal Goods only.
       Further tax is 0% on services across all provincial revenue authorities (PRA, SRB, KPRA, BRA, ICT).
    2. REDUCED RATE NO-INPUT RESTRICTION: Where a reduced rate (e.g. 3% SRB / 5% PRA on IT) is elected,
       input tax adjustment is NOT admissible by statutory condition. The tax is absorbed into cost.
    3. STANDARD RATE INPUT ASSET: Input tax is recognized as an Asset (Account 1060: Input Sales Tax Recoverable)
       only if both buyer and supplier are registered & active, and the standard rate applies.
    """
    b_st = normalize_gst_status(buyer_status)
    s_st = normalize_gst_status(supplier_status)
    sub = round(float(subtotal or 0.0), 2)
    auth = normalize_tax_authority(authority)

    rate, input_admissible, ref = resolve_provincial_service_rate(auth, sector, use_reduced_rate)
    tax_amt = round(sub * (rate / 100.0), 2)

    # PS-01: Both registered and active (Standard Rate elected)
    if b_st == GSTPartyStatus.REGISTERED_ACTIVE and s_st == GSTPartyStatus.REGISTERED_ACTIVE:
        if use_reduced_rate and not input_admissible:
            return {
                "rule_code": "PS-01R",
                "authority": auth,
                "sector": sector,
                "service_tax_rate": rate,
                "service_tax_amount": tax_amt,
                "input_tax_eligible": False,
                "input_tax_asset_amount": 0.0,
                "expense_or_cost_amount": round(sub + tax_amt, 2),
                "further_tax_rate": 0.0,
                "further_tax_amount": 0.0,
                "gross_total": round(sub + tax_amt, 2),
                "requires_compliance_review": False,
                "advisory": (
                    f"PS-01R: Active parties under {auth} {sector} reduced regime ({rate}%). "
                    f"Service tax of Rs. {tax_amt:,.2f} is payable to vendor. By statutory condition ({ref}), "
                    "no input tax adjustment is admissible; tax is capitalized into operating expense. "
                    "Further Tax is 0% (statutory invariant: no 4% further tax on provincial services)."
                ),
            }
        # Standard rate with full input tax asset
        return {
            "rule_code": "PS-01",
            "authority": auth,
            "sector": sector,
            "service_tax_rate": rate,
            "service_tax_amount": tax_amt,
            "input_tax_eligible": True,
            "input_tax_asset_amount": tax_amt,
            "expense_or_cost_amount": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": round(sub + tax_amt, 2),
            "requires_compliance_review": False,
            "advisory": (
                f"PS-01: Both buyer and supplier registered & active on {auth} ATL. "
                f"Standard service tax of {rate}% applies (Rs. {tax_amt:,.2f}). Input tax is recognized "
                "as an Asset (Account 1060: Input Sales Tax Recoverable) claimable against output provincial tax. "
                "Further Tax is 0% (statutory invariant: no 4% further tax on provincial services)."
            ),
        }

    # PS-02: Buyer active, supplier inactive
    if b_st == GSTPartyStatus.REGISTERED_ACTIVE and s_st == GSTPartyStatus.REGISTERED_INACTIVE:
        return {
            "rule_code": "PS-02",
            "authority": auth,
            "sector": sector,
            "service_tax_rate": rate,
            "service_tax_amount": tax_amt,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "expense_or_cost_amount": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": round(sub + tax_amt, 2),
            "requires_compliance_review": True,
            "advisory": (
                f"PS-02: Supplier is INACTIVE / SUSPENDED on {auth} ATL. Input tax claim of Rs. {tax_amt:,.2f} "
                f"is HELD under compliance review. Under {auth} Withholding Rules, buyer as withholding agent "
                "must withhold 100% of the sales tax on services pending status verification."
            ),
        }

    # PS-03: Buyer active, supplier unregistered
    if b_st == GSTPartyStatus.REGISTERED_ACTIVE and s_st == GSTPartyStatus.UNREGISTERED:
        return {
            "rule_code": "PS-03",
            "authority": auth,
            "sector": sector,
            "service_tax_rate": 0.0,
            "service_tax_amount": 0.0,
            "input_tax_eligible": False,
            "input_tax_asset_amount": 0.0,
            "expense_or_cost_amount": sub,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "gross_total": sub,
            "requires_compliance_review": False,
            "advisory": (
                f"PS-03: Supplier is UNREGISTERED with {auth}. Unregistered vendor cannot legally charge provincial sales tax. "
                "Input tax is 0. NO 4% Further Tax applies (Further Tax is strictly an FBR Goods tax under S.3(1A)). "
                f"Recorded as gross operating expense. Under {auth} Withholding Rules, verify whether recipient withholding applies."
            ),
        }

    # PS-04 / PS-05 / PS-06 / PS-07: Buyer unregistered or inactive
    return {
        "rule_code": "PS-07" if s_st == GSTPartyStatus.REGISTERED_ACTIVE else "PS-08",
        "authority": auth,
        "sector": sector,
        "service_tax_rate": rate if s_st == GSTPartyStatus.REGISTERED_ACTIVE else 0.0,
        "service_tax_amount": tax_amt if s_st == GSTPartyStatus.REGISTERED_ACTIVE else 0.0,
        "input_tax_eligible": False,
        "input_tax_asset_amount": 0.0,
        "expense_or_cost_amount": round(sub + (tax_amt if s_st == GSTPartyStatus.REGISTERED_ACTIVE else 0.0), 2),
        "further_tax_rate": 0.0,
        "further_tax_amount": 0.0,
        "gross_total": round(sub + (tax_amt if s_st == GSTPartyStatus.REGISTERED_ACTIVE else 0.0), 2),
        "requires_compliance_review": False,
        "advisory": (
            f"PS-07: Buyer is UNREGISTERED with {auth}. Active supplier charges {rate}% provincial service tax. "
            "Buyer CANNOT claim input tax credit; entire gross amount is capitalized into operating cost. "
            "Further Tax is 0% (statutory invariant: no 4% further tax on provincial services)."
        ),
    }


def evaluate_provincial_services_sales_matrix(
    seller_status: str,
    customer_status: str,
    subtotal: float,
    authority: str = "PRA",
    sector: str = "GENERAL_SERVICES",
    use_reduced_rate: bool = False,
) -> Dict[str, Any]:
    """Execute complete Sales-Side Provincial Services Tax Matrix (SS-01 to SS-05).

    Crucial Statutory Difference from Federal Goods:
    - On Federal Goods (S-02 / S-03), an active seller MUST charge 4% Further Tax under Section 3(1A)
      when supplying to unregistered/inactive persons (Total 22%).
    - On Provincial Services (SS-01 to SS-03), **NO 4% FURTHER TAX IS LEVIED**, regardless of whether
      the customer is registered or unregistered. The tax is strictly the standard rate (16%/15%)
      or elected reduced rate (3%/5%).
    """
    s_st = normalize_gst_status(seller_status)
    c_st = normalize_gst_status(customer_status)
    sub = round(float(subtotal or 0.0), 2)
    auth = normalize_tax_authority(authority)

    rate, input_admissible, ref = resolve_provincial_service_rate(auth, sector, use_reduced_rate)

    # SS-05: Seller is unregistered
    if s_st == GSTPartyStatus.UNREGISTERED:
        return {
            "rule_code": "SS-05",
            "authority": auth,
            "sector": sector,
            "service_tax_rate": 0.0,
            "service_tax_amount": 0.0,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "total_tax_amount": 0.0,
            "gross_total": sub,
            "requires_compliance_review": False,
            "advisory": (
                f"SS-05: Seller is NOT registered with {auth}. The company cannot legally charge provincial sales tax "
                "or issue a tax invoice. Total invoice is commercial service revenue without sales tax."
            ),
        }

    # SS-04: Seller is inactive / suspended
    if s_st == GSTPartyStatus.REGISTERED_INACTIVE:
        return {
            "rule_code": "SS-04",
            "authority": auth,
            "sector": sector,
            "service_tax_rate": 0.0,
            "service_tax_amount": 0.0,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "total_tax_amount": 0.0,
            "gross_total": sub,
            "requires_compliance_review": True,
            "advisory": (
                f"SS-04: Seller registration is INACTIVE / SUSPENDED on {auth} ATL. Hold sales invoice pending "
                "tax compliance review before charging provincial sales tax."
            ),
        }

    # Active Seller:
    tax_amt = round(sub * (rate / 100.0), 2)

    # SS-01: Customer is Active
    if c_st == GSTPartyStatus.REGISTERED_ACTIVE:
        return {
            "rule_code": "SS-01",
            "authority": auth,
            "sector": sector,
            "service_tax_rate": rate,
            "service_tax_amount": tax_amt,
            "further_tax_rate": 0.0,
            "further_tax_amount": 0.0,
            "total_tax_amount": tax_amt,
            "gross_total": round(sub + tax_amt, 2),
            "requires_compliance_review": False,
            "advisory": (
                f"SS-01: Active registered service provider to active registered client under {auth} ({sector}). "
                f"Provincial sales tax of {rate}% applies (Rs. {tax_amt:,.2f}) under {ref}. "
                "Further Tax is 0% (services invariant). Official provincial tax invoice issued."
            ),
        }

    # SS-02 / SS-03: Customer is Inactive or Unregistered
    # INVARIANT: NO 4% Further Tax on services!
    rule_code = "SS-02" if c_st == GSTPartyStatus.REGISTERED_INACTIVE else "SS-03"
    cust_desc = "INACTIVE on ATL" if c_st == GSTPartyStatus.REGISTERED_INACTIVE else "UNREGISTERED"
    return {
        "rule_code": rule_code,
        "authority": auth,
        "sector": sector,
        "service_tax_rate": rate,
        "service_tax_amount": tax_amt,
        "further_tax_rate": 0.0,
        "further_tax_amount": 0.0,
        "total_tax_amount": tax_amt,
        "gross_total": round(sub + tax_amt, 2),
        "requires_compliance_review": False,
        "advisory": (
            f"{rule_code}: Service supply to {cust_desc} customer. Applicable {auth} service tax is {rate}% "
            f"(Rs. {tax_amt:,.2f}). In stark contrast to Goods GST, **Further Tax is strictly 0%** under {auth} law. "
            f"Total tax = {rate}%. Tax recorded to Account 2130 Sales Tax Payable."
        ),
    }


def evaluate_provincial_sales_tax_withholding(
    authority: str,
    supplier_status: str,
    service_tax_amount: float,
    sector: str = "GENERAL_SERVICES",
    recipient_is_withholding_agent: bool = True,
) -> Dict[str, Any]:
    """Evaluate Provincial Sales Tax Withholding (Wh-ST) on service payments.

    Governed by:
    - Punjab Sales Tax on Services (Withholding) Rules 2015
    - Sindh Sales Tax Special Procedure (Withholding) Rules 2014
    - KPRA Sales Tax on Services Withholding Regulations 2020

    Rules:
    1. Unregistered / Inactive vendor: 100% of the sales tax is withheld by the recipient.
    2. Active vendor in 100% withholding sectors (Advertising, Security, Courier, Janitorial): 100% withheld.
    3. Active vendor in general sectors: 1/5th (20%) of the sales tax is withheld by corporate withholding agents.
    4. Telecommunication & Banking companies: 0% sales tax withholding (exempted from deduction at source).
    """
    s_st = normalize_gst_status(supplier_status)
    tax_amt = round(float(service_tax_amount or 0.0), 2)
    auth = normalize_tax_authority(authority)

    if not recipient_is_withholding_agent or tax_amt <= 0.0:
        return {
            "withholding_required": False,
            "withholding_percentage": 0.0,
            "withheld_tax_amount": 0.0,
            "payable_to_vendor_tax": tax_amt,
            "reason": "Recipient is not a designated withholding agent or zero service tax.",
        }

    # Telecom / Banking exemption
    if sector.upper() in ("TELECOM", "BANKING"):
        return {
            "withholding_required": False,
            "withholding_percentage": 0.0,
            "withheld_tax_amount": 0.0,
            "payable_to_vendor_tax": tax_amt,
            "reason": f"Statutory exemption: {sector} services are exempt from sales tax withholding under {auth} rules.",
        }

    # 1. Unregistered or Inactive vendor -> 100% withholding
    if s_st != GSTPartyStatus.REGISTERED_ACTIVE:
        return {
            "withholding_required": True,
            "withholding_percentage": 100.0,
            "withheld_tax_amount": tax_amt,
            "payable_to_vendor_tax": 0.0,
            "account_code": "2130-WHST",
            "account_name": "Provincial Sales Tax Withholding Payable",
            "reason": (
                f"Under {auth} Withholding Rules, payments to non-active/unregistered service providers "
                "require 100% deduction of sales tax at source."
            ),
        }

    # 2. Specified 100% withholding sectors
    if sector.upper() in ("ADVERTISING", "SECURITY", "COURIER", "JANITORIAL"):
        return {
            "withholding_required": True,
            "withholding_percentage": 100.0,
            "withheld_tax_amount": tax_amt,
            "payable_to_vendor_tax": 0.0,
            "account_code": "2130-WHST",
            "account_name": "Provincial Sales Tax Withholding Payable",
            "reason": f"{sector} is a prescribed category requiring 100% sales tax withholding under {auth} Withholding Rules.",
        }

    # 3. Standard active corporate withholding -> 1/5th (20%)
    wh_pct = 20.0
    wh_amt = round(tax_amt * (wh_pct / 100.0), 2)
    payable_vendor = round(tax_amt - wh_amt, 2)
    return {
        "withholding_required": True,
        "withholding_percentage": wh_pct,
        "withheld_tax_amount": wh_amt,
        "payable_to_vendor_tax": payable_vendor,
        "account_code": "2130-WHST",
        "account_name": "Provincial Sales Tax Withholding Payable",
        "reason": f"Standard corporate withholding agent deduction: 1/5th (20%) withheld under {auth} Withholding Rules.",
    }


def evaluate_dual_withholding(
    subtotal: float,
    *,
    nature: str = "SERVICE",
    authority: str = "PRA",
    payee_is_corporate: bool = False,
    supplier_status: str = "REGISTERED_ACTIVE",
    has_section_153_exemption: bool = False,
    sector: Optional[str] = None,
    use_reduced_service_rate: bool = False,
    custom_income_tax_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate combined Federal Income Tax (Section 153) and Provincial Sales Tax Withholding (Wh-ST).

    Comprehensive dual withholding settlement logic:
    1. Service Tax Calculation (PRA / SRB / KPRA / FBR).
    2. Provincial Sales Tax Withholding (Wh-ST).
    3. Federal Income Tax Withholding (Section 153 ATL rates: IT 4%, Prof 15%, Specified 7%, Other 14%, Goods 5%/5.5%).
    4. Exact Net Cash / Bank payout to vendor.
    5. Double-entry verification:
       Debits = Gross Expense + Recoverable Input Tax
       Credits = Bank Settlement + S.153 IT Payable + Provincial Wh-ST Payable
    """
    sub = round(float(subtotal or 0.0), 2)
    auth = normalize_tax_authority(authority)
    sec = sector or classify_service_sector(str(sector or ""))

    # 1. Income tax u/s 153 rate
    it_rate, it_cat = resolve_section_153_rate(
        text_or_nature=sec if nature == SupplyNature.SERVICE else "goods",
        payee_is_corporate=payee_is_corporate,
        has_exemption_cert=has_section_153_exemption,
        custom_rate=custom_income_tax_rate,
    )
    it_wht_amount = round(sub * (it_rate / 100.0), 2)

    # 2. Sales tax calculation
    if nature == SupplyNature.SERVICE:
        st_eval = evaluate_provincial_services_purchase_matrix(
            buyer_status=GSTPartyStatus.REGISTERED_ACTIVE,
            supplier_status=supplier_status,
            subtotal=sub,
            authority=auth,
            sector=sec,
            use_reduced_rate=use_reduced_service_rate,
        )
        st_amt = st_eval["service_tax_amount"]
        input_eligible = st_eval["input_tax_eligible"]
        input_asset = st_eval["input_tax_asset_amount"]
        further_tax = 0.0
    else:
        # Federal Goods
        st_eval = evaluate_purchase_gst_matrix(
            buyer_status=GSTPartyStatus.REGISTERED_ACTIVE,
            supplier_status=supplier_status,
            subtotal=sub,
            ordinary_rate=18.0,
        )
        st_amt = st_eval["ordinary_gst_amount"]
        input_eligible = st_eval["input_tax_eligible"]
        input_asset = st_eval["input_tax_asset_amount"]
        further_tax = st_eval["further_tax_amount"]

    # 3. Provincial Sales Tax Withholding (Wh-ST)
    whst_eval = evaluate_provincial_sales_tax_withholding(
        authority=auth,
        supplier_status=supplier_status,
        service_tax_amount=st_amt,
        sector=sec,
        recipient_is_withholding_agent=True,
    )
    st_withheld = whst_eval["withheld_tax_amount"]
    st_paid_to_vendor = whst_eval["payable_to_vendor_tax"]

    # 4. Net Settlement
    # Total invoice billed by vendor = subtotal + st_amt
    # Vendor receives: subtotal - it_wht_amount + st_paid_to_vendor
    gross_invoice = round(sub + st_amt + further_tax, 2)
    net_payable_to_vendor = round(sub - it_wht_amount + st_paid_to_vendor, 2)

    return {
        "subtotal": sub,
        "supply_nature": nature,
        "tax_authority": auth,
        "service_sector": sec,
        # Provincial / Federal Sales Tax
        "sales_tax_rate": st_eval.get("service_tax_rate", st_eval.get("ordinary_gst_rate", 0.0)),
        "sales_tax_amount": st_amt,
        "further_tax_amount": further_tax,
        "input_tax_eligible": input_eligible,
        "input_tax_asset_amount": input_asset,
        # Provincial Sales Tax Withholding (Wh-ST)
        "sales_tax_withholding_percentage": whst_eval["withholding_percentage"],
        "sales_tax_withheld_amount": st_withheld,
        "sales_tax_paid_to_vendor": st_paid_to_vendor,
        "whst_account_code": "2130-WHST",
        "whst_account_name": "Provincial Sales Tax Withholding Payable",
        # Federal Income Tax Withholding (u/s 153)
        "income_tax_wht_rate": it_rate,
        "income_tax_wht_category": it_cat,
        "income_tax_wht_amount": it_wht_amount,
        "it_wht_account_code": "2130",
        "it_wht_account_name": "Withholding Tax Payable u/s 153",
        # Settlement summary
        "gross_invoice_total": gross_invoice,
        "total_tax_deducted": round(it_wht_amount + st_withheld, 2),
        "net_cash_payment_to_vendor": net_payable_to_vendor,
        "journal_balance_verified": round(sub + input_asset, 2) == round(net_payable_to_vendor + it_wht_amount + st_withheld, 2),
        "advisory": (
            f"Dual Withholding Analysis ({auth} {sec}): Gross invoice Rs. {gross_invoice:,.2f}. "
            f"Deductions: Section 153 Income Tax ({it_rate}%) = Rs. {it_wht_amount:,.2f}; "
            f"Provincial Sales Tax Withheld ({whst_eval['withholding_percentage']}%) = Rs. {st_withheld:,.2f}. "
            f"Net bank disbursement to vendor = Rs. {net_payable_to_vendor:,.2f}. "
            f"Input Tax Asset recognized = Rs. {input_asset:,.2f}."
        ),
    }


def evaluate_unified_supply_tax(
    subtotal: float,
    *,
    text_or_item: str = "",
    tax_authority: Optional[str] = None,
    is_purchase: bool = True,
    buyer_status: str = "REGISTERED_ACTIVE",
    supplier_status: str = "REGISTERED_ACTIVE",
    seller_status: str = "REGISTERED_ACTIVE",
    customer_status: str = "REGISTERED_ACTIVE",
    use_reduced_rate: bool = False,
) -> Dict[str, Any]:
    """Unified tax entry point dispatching to Federal Goods or Provincial Services matrix.

    Automatically handles:
    - Goods vs Service classification
    - 0% Further Tax invariant for services
    - S.3(1A) 4% Further Tax for goods to unregistered persons
    - Sector-specific provincial schedules (IT 3%/5%, Construction 5%, etc.)
    """
    nature = classify_supply_nature(text_or_item)
    auth = normalize_tax_authority(tax_authority)

    if nature == SupplyNature.SERVICE:
        sec = classify_service_sector(text_or_item)
        if is_purchase:
            return evaluate_provincial_services_purchase_matrix(
                buyer_status=buyer_status,
                supplier_status=supplier_status,
                subtotal=subtotal,
                authority=auth,
                sector=sec,
                use_reduced_rate=use_reduced_rate,
            )
        return evaluate_provincial_services_sales_matrix(
            seller_status=seller_status,
            customer_status=customer_status,
            subtotal=subtotal,
            authority=auth,
            sector=sec,
            use_reduced_rate=use_reduced_rate,
        )

    # Federal Goods
    if is_purchase:
        return evaluate_purchase_gst_matrix(
            buyer_status=buyer_status,
            supplier_status=supplier_status,
            subtotal=subtotal,
            ordinary_rate=18.0,
        )
    return evaluate_sales_gst_matrix(
        seller_status=seller_status,
        customer_status=customer_status,
        subtotal=subtotal,
        ordinary_rate=18.0,
    )


async def set_organization_tax_profile(
    organization_id: uuid.UUID,
    *,
    is_sales_tax_registered: Optional[bool] = None,
    tax_authority: Optional[str] = None,
    default_tax_pricing: Optional[str] = None,
    sales_tax_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Save durable tax configuration for an organisation."""
    from app.services import preference_service

    if is_sales_tax_registered is not None:
        await preference_service.set_preference(
            organization_id,
            KEY_IS_SALES_TAX_REGISTERED,
            "true" if is_sales_tax_registered else "false",
            source="user_set",
        )

    if tax_authority:
        auth_clean = str(tax_authority).strip().upper()
        await preference_service.set_preference(
            organization_id,
            KEY_TAX_AUTHORITY,
            auth_clean,
            source="user_set",
        )

    if default_tax_pricing:
        pricing_clean = str(default_tax_pricing).strip().upper()
        await preference_service.set_preference(
            organization_id,
            KEY_DEFAULT_TAX_PRICING,
            pricing_clean,
            source="user_set",
        )

    if sales_tax_rate is not None:
        await preference_service.set_preference(
            organization_id,
            KEY_SALES_TAX_RATE,
            str(sales_tax_rate),
            source="user_set",
        )

    return await get_organization_tax_profile(organization_id)
