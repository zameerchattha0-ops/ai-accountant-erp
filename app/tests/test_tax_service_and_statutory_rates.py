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


# =====================================================================
# Tests: Provincial Services Matrix & Dual Withholding
# =====================================================================

def test_classify_supply_nature():
    """Verify goods vs services classification."""
    from app.services.tax_service import classify_supply_nature, SupplyNature
    assert classify_supply_nature("Software development and cloud setup") == SupplyNature.SERVICE
    assert classify_supply_nature("Legal advisory services") == SupplyNature.SERVICE
    assert classify_supply_nature("Office furniture and desks") == SupplyNature.GOODS
    assert classify_supply_nature("Computer laptops and toners") == SupplyNature.GOODS


def test_classify_service_sector():
    """Verify sector detection for provincial tariffs."""
    from app.services.tax_service import classify_service_sector
    assert classify_service_sector("Custom software programming") == "IT_SERVICES"
    assert classify_service_sector("Civil building construction") == "CONSTRUCTION"
    assert classify_service_sector("Restaurant banquet catering") == "RESTAURANT_HOTEL"
    assert classify_service_sector("Electronic billboard advertising") == "ADVERTISING"
    assert classify_service_sector("Freight cargo transport") == "TRANSPORT_CARGO"
    assert classify_service_sector("Cellular bandwidth leased line") == "TELECOM"


def test_provincial_services_purchase_standard_rate_pra():
    """PS-01: Standard rate active parties in Punjab (PRA: 16%, input tax eligible, 0% further tax)."""
    from app.services.tax_service import evaluate_provincial_services_purchase_matrix
    res = evaluate_provincial_services_purchase_matrix(
        buyer_status="REGISTERED_ACTIVE",
        supplier_status="REGISTERED_ACTIVE",
        subtotal=100000.0,
        authority="PRA",
        sector="GENERAL_SERVICES",
    )
    assert res["rule_code"] == "PS-01"
    assert res["service_tax_rate"] == 16.0
    assert res["service_tax_amount"] == 16000.0
    assert res["input_tax_eligible"] is True
    assert res["input_tax_asset_amount"] == 16000.0
    assert res["further_tax_rate"] == 0.0
    assert res["further_tax_amount"] == 0.0
    assert res["gross_total"] == 116000.0


def test_provincial_services_purchase_reduced_rate_it_srb():
    """PS-01R: Reduced IT scheme in Sindh (SRB: 3%, input tax NOT claimable by statute, 0% further tax)."""
    from app.services.tax_service import evaluate_provincial_services_purchase_matrix
    res = evaluate_provincial_services_purchase_matrix(
        buyer_status="REGISTERED_ACTIVE",
        supplier_status="REGISTERED_ACTIVE",
        subtotal=100000.0,
        authority="SRB",
        sector="IT_SERVICES",
        use_reduced_rate=True,
    )
    assert res["rule_code"] == "PS-01R"
    assert res["service_tax_rate"] == 3.0
    assert res["service_tax_amount"] == 3000.0
    assert res["input_tax_eligible"] is False
    assert res["input_tax_asset_amount"] == 0.0
    assert res["expense_or_cost_amount"] == 103000.0
    assert res["further_tax_rate"] == 0.0
    assert res["further_tax_amount"] == 0.0
    assert res["gross_total"] == 103000.0


def test_provincial_services_sales_zero_further_tax_on_unregistered_client():
    """SS-03: Services to UNREGISTERED client has 0% Further Tax (unlike Goods where 4% applies)."""
    from app.services.tax_service import evaluate_provincial_services_sales_matrix
    res = evaluate_provincial_services_sales_matrix(
        seller_status="REGISTERED_ACTIVE",
        customer_status="UNREGISTERED",
        subtotal=100000.0,
        authority="SRB",
        sector="GENERAL_SERVICES",
    )
    assert res["rule_code"] == "SS-03"
    assert res["service_tax_rate"] == 15.0
    assert res["service_tax_amount"] == 15000.0
    # Statutory Invariant: NO Further Tax on services
    assert res["further_tax_rate"] == 0.0
    assert res["further_tax_amount"] == 0.0
    assert res["total_tax_amount"] == 15000.0
    assert res["gross_total"] == 115000.0


def test_provincial_sales_tax_withholding_unregistered_vendor():
    """Under PRA/SRB rules, payments to unregistered service providers require 100% withholding."""
    from app.services.tax_service import evaluate_provincial_sales_tax_withholding
    res = evaluate_provincial_sales_tax_withholding(
        authority="PRA",
        supplier_status="UNREGISTERED",
        service_tax_amount=16000.0,
        sector="GENERAL_SERVICES",
    )
    assert res["withholding_required"] is True
    assert res["withholding_percentage"] == 100.0
    assert res["withheld_tax_amount"] == 16000.0
    assert res["payable_to_vendor_tax"] == 0.0


def test_provincial_sales_tax_withholding_active_vendor_advertising_vs_general():
    """Active vendor: Advertising has 100% withholding; General has 20% (1/5th) corporate withholding."""
    from app.services.tax_service import evaluate_provincial_sales_tax_withholding
    # Advertising
    res_ad = evaluate_provincial_sales_tax_withholding(
        authority="PRA",
        supplier_status="REGISTERED_ACTIVE",
        service_tax_amount=16000.0,
        sector="ADVERTISING",
    )
    assert res_ad["withholding_percentage"] == 100.0
    assert res_ad["withheld_tax_amount"] == 16000.0
    assert res_ad["payable_to_vendor_tax"] == 0.0

    # General Services
    res_gen = evaluate_provincial_sales_tax_withholding(
        authority="PRA",
        supplier_status="REGISTERED_ACTIVE",
        service_tax_amount=16000.0,
        sector="GENERAL_SERVICES",
    )
    assert res_gen["withholding_percentage"] == 20.0
    assert res_gen["withheld_tax_amount"] == 3200.0
    assert res_gen["payable_to_vendor_tax"] == 12800.0


def test_dual_withholding_settlement():
    """Verify dual withholding: Income Tax u/s 153 + Provincial Sales Tax Withholding."""
    from app.services.tax_service import evaluate_dual_withholding
    # Subtotal 100,000 IT Services under PRA:
    # Service Tax (PRA 16%) = 16,000
    # Sales Tax Withholding (20% of 16,000) = 3,200
    # Vendor gets 12,800 of sales tax
    # Income Tax WHT u/s 153 (IT services: 4%) = 4,000
    # Net cash payment = 100,000 - 4,000 + 12,800 = 108,800
    # Total deductions = 4,000 (IT) + 3,200 (Wh-ST) = 7,200
    res = evaluate_dual_withholding(
        subtotal=100000.0,
        nature="SERVICE",
        authority="PRA",
        payee_is_corporate=True,
        supplier_status="REGISTERED_ACTIVE",
        sector="IT_SERVICES",
    )
    assert res["income_tax_wht_rate"] == 4.0
    assert res["income_tax_wht_amount"] == 4000.0
    assert res["sales_tax_amount"] == 16000.0
    assert res["sales_tax_withheld_amount"] == 3200.0
    assert res["net_cash_payment_to_vendor"] == 108800.0
    assert res["journal_balance_verified"] is True


def test_unified_supply_tax_auto_dispatch():
    """Unified entry point accurately routes goods to 18%+4% Further Tax and services to 0% Further Tax."""
    from app.services.tax_service import evaluate_unified_supply_tax
    # Goods to unregistered client -> S.3(1A) 4% Further Tax applied (Total 22%)
    goods_res = evaluate_unified_supply_tax(
        subtotal=100000.0,
        text_or_item="Supply of 10 office chairs and desks",
        tax_authority="FBR",
        is_purchase=False,
        seller_status="REGISTERED_ACTIVE",
        customer_status="UNREGISTERED",
    )
    assert goods_res["further_tax_rate"] == 4.0
    assert goods_res["further_tax_amount"] == 4000.0
    assert goods_res["gross_total"] == 122000.0

    # Services to unregistered client -> 0% Further Tax
    service_res = evaluate_unified_supply_tax(
        subtotal=100000.0,
        text_or_item="Software consultancy and cloud migration service",
        tax_authority="PRA",
        is_purchase=False,
        seller_status="REGISTERED_ACTIVE",
        customer_status="UNREGISTERED",
    )
    assert service_res["service_tax_rate"] == 16.0
    assert service_res["further_tax_rate"] == 0.0
    assert service_res["further_tax_amount"] == 0.0
    assert service_res["gross_total"] == 116000.0
