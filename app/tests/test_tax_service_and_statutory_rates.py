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


def test_purchase_gst_matrix_p01_both_active():
    """P-01: Both registered and active -> 18% ordinary GST, claimable Input Tax (Asset 1060)."""
    from app.services.tax_service import evaluate_purchase_gst_matrix
    p = evaluate_purchase_gst_matrix("REGISTERED_ACTIVE", "REGISTERED_ACTIVE", subtotal=100000.0)
    assert p["rule_code"] == "P-01"
    assert p["ordinary_gst_rate"] == 18.0
    assert p["ordinary_gst_amount"] == 18000.0
    assert p["input_tax_eligible"] is True
    assert p["input_tax_asset_amount"] == 18000.0
    assert p["inventory_or_expense_cost"] == 100000.0
    assert p["further_tax_rate"] == 0.0
    assert p["further_tax_amount"] == 0.0
    assert p["gross_total"] == 118000.0
    assert p["requires_compliance_review"] is False


def test_purchase_gst_matrix_p02_supplier_inactive():
    """P-02: Buyer active, supplier inactive -> input tax held under compliance review."""
    from app.services.tax_service import evaluate_purchase_gst_matrix
    p = evaluate_purchase_gst_matrix("REGISTERED_ACTIVE", "REGISTERED_INACTIVE", subtotal=100000.0)
    assert p["rule_code"] == "P-02"
    assert p["ordinary_gst_amount"] == 18000.0
    assert p["input_tax_eligible"] is False
    assert p["input_tax_asset_amount"] == 0.0
    assert p["requires_compliance_review"] is True


def test_purchase_gst_matrix_p03_supplier_unregistered():
    """P-03: Buyer active, supplier unregistered -> Supplier cannot charge GST, NO 4% Further Tax."""
    from app.services.tax_service import evaluate_purchase_gst_matrix
    p = evaluate_purchase_gst_matrix("REGISTERED_ACTIVE", "UNREGISTERED", subtotal=100000.0)
    assert p["rule_code"] == "P-03"
    assert p["ordinary_gst_rate"] == 0.0
    assert p["ordinary_gst_amount"] == 0.0
    assert p["input_tax_eligible"] is False
    assert p["input_tax_asset_amount"] == 0.0
    assert p["further_tax_rate"] == 0.0
    assert p["further_tax_amount"] == 0.0
    assert p["gross_total"] == 100000.0


def test_purchase_gst_matrix_p07_unregistered_buyer():
    """P-07: Unregistered buyer + Active supplier -> 18% GST + 4% Further Tax (S.3(1A)), capitalized into cost."""
    from app.services.tax_service import evaluate_purchase_gst_matrix
    p = evaluate_purchase_gst_matrix("UNREGISTERED", "REGISTERED_ACTIVE", subtotal=100000.0)
    assert p["rule_code"] == "P-07"
    assert p["ordinary_gst_rate"] == 18.0
    assert p["ordinary_gst_amount"] == 18000.0
    assert p["further_tax_rate"] == 4.0
    assert p["further_tax_amount"] == 4000.0
    assert p["input_tax_eligible"] is False
    assert p["input_tax_asset_amount"] == 0.0
    # Total tax Rs. 22,000 capitalized into purchase cost
    assert p["inventory_or_expense_cost"] == 122000.0
    assert p["gross_total"] == 122000.0


def test_sales_gst_matrix_s01_active_to_active():
    """S-01: Active registered seller to active registered customer -> 18% GST, 0% Further Tax."""
    from app.services.tax_service import evaluate_sales_gst_matrix
    s = evaluate_sales_gst_matrix("REGISTERED_ACTIVE", "REGISTERED_ACTIVE", subtotal=100000.0)
    assert s["rule_code"] == "S-01"
    assert s["ordinary_gst_rate"] == 18.0
    assert s["ordinary_gst_amount"] == 18000.0
    assert s["further_tax_rate"] == 0.0
    assert s["further_tax_amount"] == 0.0
    assert s["total_tax_amount"] == 18000.0
    assert s["gross_total"] == 118000.0


def test_sales_gst_matrix_s02_and_s03_further_tax():
    """S-02 & S-03: Active registered seller to Inactive or Unregistered customer -> 18% GST + 4% Further Tax."""
    from app.services.tax_service import evaluate_sales_gst_matrix
    s2 = evaluate_sales_gst_matrix("REGISTERED_ACTIVE", "REGISTERED_INACTIVE", subtotal=100000.0)
    assert s2["rule_code"] == "S-02"
    assert s2["ordinary_gst_rate"] == 18.0
    assert s2["further_tax_rate"] == 4.0
    assert s2["further_tax_amount"] == 4000.0
    assert s2["total_tax_amount"] == 22000.0
    assert s2["gross_total"] == 122000.0

    s3 = evaluate_sales_gst_matrix("REGISTERED_ACTIVE", "UNREGISTERED", subtotal=100000.0)
    assert s3["rule_code"] == "S-03"
    assert s3["ordinary_gst_rate"] == 18.0
    assert s3["further_tax_rate"] == 4.0
    assert s3["further_tax_amount"] == 4000.0
    assert s3["total_tax_amount"] == 22000.0
    assert s3["gross_total"] == 122000.0


def test_sales_gst_matrix_s04_and_s05_unregistered_seller():
    """S-04 & S-05: Unregistered or Inactive seller cannot legally charge FBR GST or Further Tax."""
    from app.services.tax_service import evaluate_sales_gst_matrix
    s4 = evaluate_sales_gst_matrix("REGISTERED_INACTIVE", "REGISTERED_ACTIVE", subtotal=100000.0)
    assert s4["rule_code"] == "S-04"
    assert s4["ordinary_gst_amount"] == 0.0
    assert s4["requires_compliance_review"] is True

    s5 = evaluate_sales_gst_matrix("UNREGISTERED", "REGISTERED_ACTIVE", subtotal=100000.0)
    assert s5["rule_code"] == "S-05"
    assert s5["ordinary_gst_rate"] == 0.0
    assert s5["further_tax_rate"] == 0.0
    assert s5["total_tax_amount"] == 0.0
    assert s5["gross_total"] == 100000.0
