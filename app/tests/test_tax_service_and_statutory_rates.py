"""
Unit tests for Section 153 Withholding Tax Statutory Rates & Sales Tax Act Input Tax Treatment.

Statutory Rules (Active Taxpayer List / ATL Rates):
1. Purchase of goods – companies: 5%
2. Purchase of goods – individuals/AOPs: 5.5%
3. Specified services: 7%
4. IT and IT-enabled services: 4%
5. Independent professional services: 15%
6. Other services: 14%
7. Contracts – companies: 7.5%
8. Contracts – individuals/AOPs: 8%
9. Advertising through print/electronic media: 1.5%
10. Payee with Section 153 Exemption Certificate: 0%

Sales Tax / GST on Purchase of Goods:
- Registered supplier (with STRN) -> Input tax is an ASSET (Sales Tax Recoverable).
- Unregistered supplier -> Input tax CANNOT be claimed or recorded as asset (capitalized into cost).
"""

from __future__ import annotations

import pytest
from app.services.tax_service import (
    resolve_section_153_rate,
    evaluate_input_tax_treatment,
    SECTION_153_STATUTORY_RATES,
)


def test_section_153_statutory_rates_table():
    """Verify official ATL rate constants are correctly defined."""
    assert SECTION_153_STATUTORY_RATES["GOODS_CORP"]["rate"] == 5.0
    assert SECTION_153_STATUTORY_RATES["GOODS_INDIVIDUAL"]["rate"] == 5.5
    assert SECTION_153_STATUTORY_RATES["SPECIFIED_SERVICES"]["rate"] == 7.0
    assert SECTION_153_STATUTORY_RATES["IT_SERVICES"]["rate"] == 4.0
    assert SECTION_153_STATUTORY_RATES["PROFESSIONAL_SERVICES"]["rate"] == 15.0
    assert SECTION_153_STATUTORY_RATES["OTHER_SERVICES"]["rate"] == 14.0
    assert SECTION_153_STATUTORY_RATES["CONTRACTS_CORP"]["rate"] == 7.5
    assert SECTION_153_STATUTORY_RATES["CONTRACTS_INDIVIDUAL"]["rate"] == 8.0
    assert SECTION_153_STATUTORY_RATES["ADVERTISING_MEDIA"]["rate"] == 1.5


def test_resolve_section_153_rate_exemption_certificate():
    """Payee with exemption certificate gets 0% WHT."""
    rate, cat = resolve_section_153_rate("IT Consulting services", has_exemption_cert=True)
    assert rate == 0.0
    assert cat == "EXEMPT"


def test_resolve_section_153_rate_it_services():
    """IT and IT-enabled services are mapped to 4%."""
    rate, cat = resolve_section_153_rate("IT Consulting services for cloud migration")
    assert rate == 4.0
    assert cat == "IT_SERVICES"

    rate, cat = resolve_section_153_rate("Custom software development & web design")
    assert rate == 4.0
    assert cat == "IT_SERVICES"


def test_resolve_section_153_rate_purchase_of_goods():
    """Purchase of goods: 5% for companies, 5.5% for individuals/AOPs."""
    rate_corp, cat_corp = resolve_section_153_rate("Supply of office chairs & furniture", payee_is_corporate=True)
    assert rate_corp == 5.0
    assert cat_corp == "GOODS_CORP"

    rate_ind, cat_ind = resolve_section_153_rate("Supply of stationery materials", payee_is_corporate=False)
    assert rate_ind == 5.5
    assert cat_ind == "GOODS_INDIVIDUAL"


def test_resolve_section_153_rate_independent_professional_services():
    """Independent professional services (legal, audit, tax, architectural) are mapped to 15%."""
    rate, cat = resolve_section_153_rate("Statutory audit and annual tax filing fees")
    assert rate == 15.0
    assert cat == "PROFESSIONAL_SERVICES"

    rate, cat = resolve_section_153_rate("Legal consultancy & advocate retainership")
    assert rate == 15.0
    assert cat == "PROFESSIONAL_SERVICES"


def test_resolve_section_153_rate_specified_services():
    """Specified services (freight, courier, transport, hotel, security) are mapped to 7%."""
    rate, cat = resolve_section_153_rate("Freight forwarding and courier charges")
    assert rate == 7.0
    assert cat == "SPECIFIED_SERVICES"


def test_resolve_section_153_rate_advertising_media():
    """Advertising through print or electronic media is mapped to 1.5%."""
    rate, cat = resolve_section_153_rate("Electronic media TV commercial advertising")
    assert rate == 1.5
    assert cat == "ADVERTISING_MEDIA"


def test_resolve_section_153_rate_contracts():
    """Execution of contracts: 7.5% for companies, 8% for individuals/AOPs."""
    rate_corp, cat_corp = resolve_section_153_rate("Civil construction contract", payee_is_corporate=True)
    assert rate_corp == 7.5
    assert cat_corp == "CONTRACTS_CORP"

    rate_ind, cat_ind = resolve_section_153_rate("Turnkey electrical contract", payee_is_corporate=False)
    assert rate_ind == 8.0
    assert cat_ind == "CONTRACTS_INDIVIDUAL"


def test_resolve_section_153_rate_other_services():
    """Other services default to 14%."""
    rate, cat = resolve_section_153_rate("Building repair and maintenance service")
    assert rate == 14.0
    assert cat == "OTHER_SERVICES"


def test_evaluate_input_tax_treatment_registered_supplier():
    """When purchased from a registered supplier (has STRN), input tax is recognized as an Asset."""
    res = evaluate_input_tax_treatment(
        subtotal=100000.0,
        sales_tax_amount=18000.0,
        supplier_has_strn=True,
        org_is_registered=True,
    )
    assert res["can_claim_input_tax"] is True
    assert res["input_tax_asset"] == 18000.0
    assert res["inventory_or_expense_cost"] == 100000.0
    assert res["asset_account_code"] == "1060"


def test_evaluate_input_tax_treatment_unregistered_supplier():
    """When purchased from an unregistered supplier, input tax cannot be claimed as an asset."""
    res = evaluate_input_tax_treatment(
        subtotal=100000.0,
        sales_tax_amount=18000.0,
        supplier_has_strn=False,
        org_is_registered=True,
    )
    assert res["can_claim_input_tax"] is False
    assert res["input_tax_asset"] == 0.0
    assert res["inventory_or_expense_cost"] == 118000.0  # Absorbed into cost
    assert "Section 8 of Sales Tax Act 1990" in res["reason"]
