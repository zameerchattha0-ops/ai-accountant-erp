"""Master Pipeline Upgrades Integration Tests.

Validates the full cognitive accounting reasoning pipeline:
1. Multi-Item Conversational Disaggregation (compound purchases -> LineItemArgs).
2. 4-Dimensional Contextual Nature Convergence (IAS 16 Fixed Asset vs IAS 2 Inventory vs IAS 1 Expense).
3. Intelligent COA and Category Resolution (IFRS 4-tier mapping, Statement-Section Invariant, Contra Guard).
4. Semantic Catalog Reconciliation & UOM Normalization (Packaging variants, Consumable Guard).
5. Party Role & Counterparty Disambiguation (Money-flow vector, IAS 32 Offsetting Guard).
6. Pre-flight Statutory & Tax Compliance Auditing (Pakistan ITO 2001 Section 73 Cash Limits & Section 153 WHT).
7. End-to-end Agent Pipeline Verification for Digital Creators studio acquisition.

Deterministic and offline: Zero live network/database calls.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.contextual_nature import classify_contextual_nature, ContextualNatureResult
from app.party_disambiguation import disambiguate_party_role, PartyRoleResult
from app.intelligent_coa import resolve_or_propose_account, COAResolutionResult
from app.catalog_reconciler import reconcile_catalog_item, CatalogReconciliationResult
from app.multi_item_disaggregator import (
    disaggregate_conversational_items,
    MultiItemDisaggregationResult,
)
from app.statutory_tax_auditor import (
    preflight_tax_compliance_audit,
    TaxAuditResult,
)


@pytest.fixture
def enable_all_intelligence_flags(monkeypatch):
    """Enable all intelligence feature flags for testing."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_contextual_nature_enabled", True)
    monkeypatch.setattr(settings, "llm_party_disambiguation_enabled", True)
    monkeypatch.setattr(settings, "intelligent_coa_mapper_enabled", True)
    monkeypatch.setattr(settings, "semantic_catalog_reconciler_enabled", True)
    monkeypatch.setattr(settings, "multi_item_disaggregator_enabled", True)
    monkeypatch.setattr(settings, "statutory_tax_auditor_enabled", True)


class TestMultiItemDisaggregationIntegration:
    """Task 5: Multi-item Conversational Disaggregation."""

    @pytest.mark.asyncio
    async def test_disaggregate_composite_purchase_prompt(self, enable_all_intelligence_flags):
        query = (
            "Bought 2 executive office chairs for Rs 70,000 and 1 Dell 4K editing monitor "
            "for 85,000 paid in cash"
        )
        result = await disaggregate_conversational_items(query)
        assert result.is_composite is True
        assert len(result.line_items) == 2
        assert result.payment_method == "CASH"
        assert result.total_amount == 155_000.0
        assert result.is_balanced is True

        chair_line = next(l for l in result.line_items if "chair" in l.description.lower())
        assert chair_line.quantity == 2.0
        assert chair_line.amount == 70_000.0
        assert chair_line.is_fixed_asset is True

        monitor_line = next(l for l in result.line_items if "monitor" in l.description.lower())
        assert monitor_line.quantity == 1.0
        assert monitor_line.amount == 85_000.0
        assert monitor_line.is_fixed_asset is True


class TestContextualAccountingNatureIntegration:
    """Task 1: Contextual Nature Classification (Digital Creators scenario)."""

    @pytest.mark.asyncio
    async def test_digital_creators_studio_furniture_classified_as_fixed_asset(
        self, enable_all_intelligence_flags
    ):
        org_profile = {
            "name": "Digital Creators",
            "business_type": "SOFTWARE_HOUSE",
            "industry": "Media & Creative Services",
        }
        res = await classify_contextual_nature(
            query="Purchasing 5 workstations & studio tables for Rs. 150,000",
            org_profile=org_profile,
            catalog_items=[],
            asset_items=[],
            preliminary={"amount": 150000.0, "quantity": 5},
        )
        assert res.nature == "FIXED_ASSET"
        assert res.standard == "IAS 16"
        assert res.is_capitalized is True
        assert res.requires_clarification is False
        assert res.confidence >= 0.65

    @pytest.mark.asyncio
    async def test_trading_firm_buying_merchandise_classified_as_inventory(
        self, enable_all_intelligence_flags
    ):
        org_profile = {
            "name": "SuperMart Traders",
            "business_type": "retail_store",
            "industry": "Retail & Wholesale",
        }
        res = await classify_contextual_nature(
            query="Purchased 50 computer mice for resale stock Rs. 45,000",
            org_profile=org_profile,
            catalog_items=[{"id": "prod-1", "name": "Computer Mouse"}],
            asset_items=[],
            preliminary={"amount": 45000.0, "quantity": 50},
        )
        assert res.nature == "INVENTORY"
        assert res.standard == "IAS 2"
        assert res.is_capitalized is False


class TestIntelligentCOAMapperIntegration:
    """Task 2: Intelligent COA & Category Resolution."""

    @pytest.mark.asyncio
    async def test_resolve_furniture_fixtures_asset_and_contra_guard(
        self, enable_all_intelligence_flags
    ):
        chart = [
            {"id": "acc-1001", "account_code": "1001", "name": "Cash on Hand", "account_type": "ASSET"},
            {"id": "acc-1050", "account_code": "1050", "name": "Accounts Receivable", "account_type": "ASSET"},
            {"id": "acc-1500", "account_code": "1500", "name": "Property, Plant & Equipment", "account_type": "ASSET", "is_group": True},
            {"id": "acc-1510", "account_code": "1510", "name": "Furniture & Fixtures", "account_type": "ASSET", "parent_account_id": "acc-1500"},
            {"id": "acc-1519", "account_code": "1519", "name": "Accumulated Depreciation - Furniture", "account_type": "ASSET", "parent_account_id": "acc-1500"},
            {"id": "acc-5000", "account_code": "5000", "name": "Cost of Goods Sold", "account_type": "EXPENSE"},
            {"id": "acc-6100", "account_code": "6100", "name": "Office Supplies", "account_type": "EXPENSE"},
        ]
        res = await resolve_or_propose_account(
            item_description="Ergonomic Executive Office Chair",
            nature="FIXED_ASSET",
            chart_of_accounts=chart,
            org_context={"industry": "Digital Media"},
        )
        assert res.action == "reuse"
        assert res.account_name == "Furniture & Fixtures"
        assert res.account_code == "1510"
        assert res.account_code != "1519"  # Never debit contra account

    @pytest.mark.asyncio
    async def test_propose_new_computer_equipment_under_ppe_parent(
        self, enable_all_intelligence_flags
    ):
        chart = [
            {"id": "acc-1500", "account_code": "1500", "name": "Property, Plant & Equipment", "account_type": "ASSET", "is_group": True},
            {"id": "acc-1510", "account_code": "1510", "name": "Furniture & Fixtures", "account_type": "ASSET", "parent_account_id": "acc-1500"},
        ]
        res = await resolve_or_propose_account(
            item_description="Dell 4K Editing Monitor",
            nature="FIXED_ASSET",
            chart_of_accounts=chart,
            org_context={"industry": "Digital Media"},
        )
        assert res.action == "create"
        assert "Computer" in res.account_name or "IT Equipment" in res.account_name
        assert res.parent_account_id == "acc-1500"  # Parented under PPE


class TestSemanticCatalogReconcilerIntegration:
    """Task 4: Semantic Catalog Reconciler & Consumable Guard."""

    @pytest.mark.asyncio
    async def test_packaging_variant_normalization(self, enable_all_intelligence_flags):
        catalog = [
            {"id": "prod-001", "name": "Logitech Mouse", "unit_price": 2500.0}
        ]
        res = await reconcile_catalog_item(
            item_description="Box of 10 Logitech Mice",
            is_inventory=True,
            catalog_products=catalog,
            catalog_services=[],
        )
        assert res.action == "match_product"
        assert res.matched_id == "prod-001"
        assert res.packaging_multiplier == 10

    @pytest.mark.asyncio
    async def test_consumable_guard_prevents_catalog_bloat(self, enable_all_intelligence_flags):
        res = await reconcile_catalog_item(
            item_description="A4 Photocopy Paper 80gsm",
            is_inventory=True,
            catalog_products=[],
            catalog_services=[],
        )
        assert res.action == "expense_only"


class TestPartyRoleDisambiguationIntegration:
    """Task 3: Party Role Disambiguation & Money Flow Vector."""

    @pytest.mark.asyncio
    async def test_money_out_settles_supplier_payable(self, enable_all_intelligence_flags):
        payables = [
            {"id": "bill-001", "supplier_name": "Apex Tech Solutions", "balance": 45000.0}
        ]
        res = await disambiguate_party_role(
            party_name="Apex Tech Solutions",
            money_direction="OUT",
            open_receivables=[],
            open_payables=payables,
            employees=[],
            org_officers=[],
        )
        assert res.role.lower() == "supplier"
        assert res.matched_record is not None
        assert res.matched_record.get("id") == "bill-001"
        assert res.requires_clarification is False

    @pytest.mark.asyncio
    async def test_money_in_collects_customer_receivable(self, enable_all_intelligence_flags):
        receivables = [
            {"id": "inv-001", "customer_name": "Global Media LLC", "balance": 200000.0}
        ]
        res = await disambiguate_party_role(
            party_name="Global Media LLC",
            money_direction="IN",
            open_receivables=receivables,
            open_payables=[],
            employees=[],
            org_officers=[],
        )
        assert res.role.lower() == "customer"
        assert res.matched_record is not None
        assert res.matched_record.get("id") == "inv-001"
        assert res.requires_clarification is False


class TestStatutoryTaxComplianceIntegration:
    """Task 6: Pre-flight Statutory & Tax Compliance Auditing (ITO 2001)."""

    @pytest.mark.asyncio
    async def test_section_73_cash_disallowance_warning_triggered(
        self, enable_all_intelligence_flags
    ):
        res = await preflight_tax_compliance_audit(
            transaction_type="EXPENSE",
            payment_method="CASH",
            total_amount=75_000.0,
            party_info={"name": "Furniture Haven", "is_filer": True, "is_corporate": False},
            line_items=[{"description": "Office Chairs", "amount": 75_000.0, "nature": "OPERATING_EXPENSE"}],
            is_fixed_asset=False,
        )
        assert res.section_73_compliant is False
        assert res.section_73_warning is not None
        assert any("Section 73" in w for w in res.statutory_warnings)
        assert res.section_153_applicable is True
        assert res.wht_rate_percent == 5.5  # Filer goods rate
        assert res.wht_amount == round(75_000.0 * 0.055, 2)
        assert res.net_payable == round(75_000.0 - (75_000.0 * 0.055), 2)

    @pytest.mark.asyncio
    async def test_bank_payment_passes_section_73(self, enable_all_intelligence_flags):
        res = await preflight_tax_compliance_audit(
            transaction_type="EXPENSE",
            payment_method="BANK_TRANSFER",
            total_amount=155_000.0,
            party_info={"name": "Furniture Haven", "is_filer": True, "is_corporate": False},
            is_fixed_asset=False,
        )
        assert res.section_73_compliant is True
        assert res.section_73_warning is None


class TestMasterPipelineEndToEndScenario:
    """Master Pipeline: Digital Creators studio acquisition end-to-end integration."""

    @pytest.mark.asyncio
    async def test_digital_creators_multi_item_purchase_full_pipeline(
        self, enable_all_intelligence_flags
    ):
        query = (
            "Digital Creators purchased 2 office chairs for Rs. 70,000 and 1 Dell editing monitor "
            "for Rs. 85,000 in cash from Apex Supplies"
        )
        # 1. Multi-item disaggregation
        disagg = await disaggregate_conversational_items(query)
        assert disagg.is_composite is True
        assert len(disagg.line_items) == 2
        assert disagg.total_amount == 155_000.0
        assert disagg.payment_method == "CASH"

        # 2. Contextual Nature Classification for Digital Creators (Agency)
        org_profile = {
            "name": "Digital Creators",
            "business_type": "SOFTWARE_HOUSE",
            "industry": "Media Production & Creative Services",
        }
        nature_res = await classify_contextual_nature(
            query=query,
            org_profile=org_profile,
            catalog_items=[],
            asset_items=[],
            preliminary={"amount": 155_000.0, "quantity": 3},
        )
        assert nature_res.nature == "FIXED_ASSET"
        assert nature_res.standard == "IAS 16"
        assert nature_res.is_capitalized is True

        # 3. Intelligent Chart of Accounts Mapping for each line
        chart = [
            {"id": "acc-1001", "account_code": "1001", "name": "Cash on Hand", "account_type": "ASSET"},
            {"id": "acc-1500", "account_code": "1500", "name": "Property, Plant & Equipment", "account_type": "ASSET", "is_group": True},
            {"id": "acc-1510", "account_code": "1510", "name": "Furniture & Fixtures", "account_type": "ASSET", "parent_account_id": "acc-1500"},
            {"id": "acc-1520", "account_code": "1520", "name": "Computer & IT Equipment", "account_type": "ASSET", "parent_account_id": "acc-1500"},
            {"id": "acc-1519", "account_code": "1519", "name": "Accumulated Depreciation - Furniture", "account_type": "ASSET", "parent_account_id": "acc-1500"},
            {"id": "acc-1529", "account_code": "1529", "name": "Accumulated Depreciation - Computers", "account_type": "ASSET", "parent_account_id": "acc-1500"},
        ]
        chair_coa = await resolve_or_propose_account(
            item_description=disagg.line_items[0].description,
            nature="FIXED_ASSET",
            chart_of_accounts=chart,
            org_context={"industry": "Media Production"},
        )
        monitor_coa = await resolve_or_propose_account(
            item_description=disagg.line_items[1].description,
            nature="FIXED_ASSET",
            chart_of_accounts=chart,
            org_context={"industry": "Media Production"},
        )
        assert chair_coa.account_name == "Furniture & Fixtures"
        assert "Computer" in monitor_coa.account_name

        # 4. Party Disambiguation for "Apex Supplies"
        payables = [{"id": "bill-apex", "supplier_name": "Apex Supplies", "balance": 0.0}]
        party_res = await disambiguate_party_role(
            party_name="Apex Supplies",
            money_direction="OUT",
            open_receivables=[],
            open_payables=payables,
            employees=[],
            org_officers=[],
        )
        assert party_res.role.lower() == "supplier"
        assert party_res.matched_record is not None
        assert party_res.matched_record.get("id") == "bill-apex"

        # 5. Pre-flight Statutory & Tax Compliance Audit (Section 73 Cash Limits & Section 153 WHT)
        tax_res = await preflight_tax_compliance_audit(
            transaction_type="PURCHASE",
            payment_method="CASH",
            total_amount=disagg.total_amount,
            party_info={"name": "Apex Supplies", "is_filer": True, "is_corporate": False},
            line_items=[l.model_dump() for l in disagg.line_items],
            is_fixed_asset=True,
        )
        # 155,000 is within Section 73(2) asset cash limit (250,000)
        assert tax_res.section_73_compliant is True
        assert tax_res.section_153_applicable is True
        assert tax_res.wht_rate_percent == 5.5
        assert tax_res.wht_amount == round(155_000.0 * 0.055, 2)
        assert tax_res.net_payable == round(155_000.0 - (155_000.0 * 0.055), 2)

        # But cash payment exceeding Section 73 asset threshold (250,000) triggers critical violation
        excess_tax_res = await preflight_tax_compliance_audit(
            transaction_type="PURCHASE",
            payment_method="CASH",
            total_amount=350_000.0,
            party_info={"name": "Apex Supplies", "is_filer": True, "is_corporate": False},
            line_items=[l.model_dump() for l in disagg.line_items],
            is_fixed_asset=True,
        )
        assert excess_tax_res.section_73_compliant is False
        assert excess_tax_res.section_73_violation is not None
        assert "Section 73(2) & 73(3)" in excess_tax_res.section_73_violation
