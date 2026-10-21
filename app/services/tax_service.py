"""Tax Service — deterministic tax calculations and authority split enforcement.

This service is authoritative for tax calculations. OCR extractions and LLM
proposals are advisory; this service guarantees math invariants and flags
unsupported deviations.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import structlog

log = structlog.get_logger(__name__)

# Standard known tax codes mapped to rate percentages
KNOWN_TAX_RATES: Dict[str, float] = {
    "STANDARD": 17.0,
    "GST_17": 17.0,
    "GST 17%": 17.0,
    "17%": 17.0,
    "REDUCED": 5.0,
    "GST_5": 5.0,
    "GST 5%": 5.0,
    "5%": 5.0,
    "ZERO": 0.0,
    "0%": 0.0,
    "EXEMPT": 0.0,
    "WHT_SERVICES": 8.0,
    "WHT_IMPORTS": 6.0,
    "CORPORATE": 29.0,
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

