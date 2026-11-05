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
    # Withholding Tax u/s 153 (Supplies & Services)
    "WHT_153_GOODS_CORP": 5.5,
    "WHT_153_GOODS_NON_CORP": 6.0,
    "WHT_153_SERVICES_CORP": 9.0,
    "WHT_153_SERVICES_NON_CORP": 11.0,
    "WHT_153_CONTRACTS": 7.5,
    "WHT_SERVICES": 9.0,
    "WHT_IMPORTS": 6.0,
    "CORPORATE": 29.0,
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

    return {
        "organization_id": str(organization_id),
        "is_sales_tax_registered": is_registered,
        "tax_authority": authority,
        "default_tax_pricing": default_pricing,
        "sales_tax_rate": default_rate if is_registered else 0.0,
        "tax_number": org.get("tax_number"),
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
