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
    if any(k in t for k in ("it consult", "software", "web develop", "web design", "programming", "cloud", "saas", "hosting", "it enabled", "bpo", "data entry", "computer")):
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
