"""Unit tests for Intelligent Chart of Accounts (COA) & Category Mapper (Task 2).

Tests compliance with IFRS 4-tier COA structure, modern categories,
Statement-Section invariant, contra-asset guard, and LLM offline mocking.
"""

from __future__ import annotations

import pytest

from app.intelligent_coa import (
    COAResolutionResult,
    _is_contra_account,
    _next_free_code,
    resolve_or_propose_account,
)


@pytest.fixture
def sample_chart():
    """A realistic IFRS Chart of Accounts."""
    return [
        # Current Assets
        {"id": "acc-1010", "account_code": "1010", "name": "Cash in Hand", "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "acc-1020", "account_code": "1020", "name": "Meezan Bank Ltd", "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "acc-1060", "account_code": "1060", "name": "Sales Tax Recoverable", "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "acc-1110", "account_code": "1110", "name": "Accounts Receivable", "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "acc-1200", "account_code": "1200", "name": "Merchandise Inventory", "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "acc-1410", "account_code": "1410", "name": "Advances & Deposits", "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "acc-1420", "account_code": "1420", "name": "Prepaid Expenses", "account_type": "ASSET", "normal_balance": "DEBIT"},

        # PPE / Non-Current Assets Heading
        {"id": "acc-1500", "account_code": "1500", "name": "Property, Plant & Equipment", "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "acc-1510", "account_code": "1510", "name": "Furniture & Fixtures", "account_type": "ASSET", "normal_balance": "DEBIT", "parent_account_id": "acc-1500"},
        {"id": "acc-1520", "account_code": "1520", "name": "Computer & IT Equipment", "account_type": "ASSET", "normal_balance": "DEBIT", "parent_account_id": "acc-1500"},
        {"id": "acc-1580", "account_code": "1580", "name": "Accumulated Depreciation - IT Equipment", "account_type": "ASSET", "normal_balance": "CREDIT"},

        # Liabilities
        {"id": "acc-2010", "account_code": "2010", "name": "Accounts Payable", "account_type": "LIABILITY", "normal_balance": "CREDIT"},

        # COGS
        {"id": "acc-5000", "account_code": "5000", "name": "Cost of Goods Sold", "account_type": "EXPENSE", "normal_balance": "DEBIT"},
        {"id": "acc-5010", "account_code": "5010", "name": "Raw Materials Consumed", "account_type": "EXPENSE", "normal_balance": "DEBIT", "parent_account_id": "acc-5000"},

        # Administrative / Operating Expenses Heading
        {"id": "acc-6000", "account_code": "6000", "name": "Administrative Expenses", "account_type": "EXPENSE", "normal_balance": "DEBIT"},
        {"id": "acc-6110", "account_code": "6110", "name": "Rent Expense", "account_type": "EXPENSE", "normal_balance": "DEBIT", "parent_account_id": "acc-6000"},
        {"id": "acc-6120", "account_code": "6120", "name": "Utilities Expense", "account_type": "EXPENSE", "normal_balance": "DEBIT", "parent_account_id": "acc-6000"},
    ]


@pytest.fixture
def org_context():
    return {
        "organization_id": "org-test-uuid",
        "name": "Digital Creators Studio",
        "business_type": "SOFTWARE_HOUSE",
        "industry": "Information Technology",
    }


class TestModernCategoryResolution:
    """Test resolution of modern expense and asset categories."""

    @pytest.mark.asyncio
    async def test_cloud_infrastructure_proposed_when_missing(self, sample_chart, org_context):
        res = await resolve_or_propose_account(
            item_description="AWS Cloud Hosting bill for August",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert isinstance(res, COAResolutionResult)
        assert res.action == "create"
        assert res.is_new is True
        assert res.account_type == "EXPENSE"
        assert res.normal_balance == "DEBIT"
        assert res.account_code == "6210"
        assert "Cloud" in res.account_name
        assert res.category == "Cloud Infrastructure"
        assert res.parent_account_id == "acc-6000"

    @pytest.mark.asyncio
    async def test_cloud_infrastructure_reused_when_existing(self, sample_chart, org_context):
        chart_with_cloud = list(sample_chart) + [{
            "id": "acc-6210",
            "account_code": "6210",
            "name": "Cloud & Hosting Infrastructure",
            "account_type": "EXPENSE",
            "normal_balance": "DEBIT",
            "parent_account_id": "acc-6000",
        }]
        res = await resolve_or_propose_account(
            item_description="DigitalOcean Droplets server compute",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=chart_with_cloud,
            org_context=org_context,
        )
        assert res.action == "reuse"
        assert res.is_new is False
        assert res.account_id == "acc-6210"
        assert res.account_code == "6210"
        assert res.category == "Cloud Infrastructure"

    @pytest.mark.asyncio
    async def test_saas_subscriptions_resolution(self, sample_chart, org_context):
        res = await resolve_or_propose_account(
            item_description="Monthly Figma design team seats & Slack subscription",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res.action == "create"
        assert res.account_type == "EXPENSE"
        assert res.account_code == "6220"
        assert "Software Subscriptions" in res.account_name
        assert res.category == "Software Subscriptions"

    @pytest.mark.asyncio
    async def test_legal_and_professional_fees(self, sample_chart, org_context):
        res = await resolve_or_propose_account(
            item_description="Legal retainer fee paid to advocate for corporate filing",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res.action == "create"
        assert res.account_type == "EXPENSE"
        assert res.account_code == "6310"
        assert "Legal" in res.account_name
        assert res.category == "Legal & Professional"

    @pytest.mark.asyncio
    async def test_statutory_audit_fees(self, sample_chart, org_context):
        res = await resolve_or_propose_account(
            item_description="Statutory audit fee for annual accounts audit",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res.action == "create"
        assert res.account_type == "EXPENSE"
        assert res.account_code == "6320"
        assert "Audit" in res.account_name
        assert res.category == "Audit & Tax Consultancy"

    @pytest.mark.asyncio
    async def test_inbound_freight_inventoriable_ias_2(self, sample_chart, org_context):
        res = await resolve_or_propose_account(
            item_description="Inbound freight charges & customs clearance on imported goods",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res.action == "create"
        assert res.account_type == "EXPENSE"
        assert res.account_code == "5120"
        assert res.category == "Inbound Freight"
        assert res.parent_account_id == "acc-5000"

    @pytest.mark.asyncio
    async def test_annual_insurance_prepayments_vs_expense(self, sample_chart, org_context):
        # When 1420 already exists as Prepaid Expenses, proposes next code (1421) for Prepaid Insurance
        res_prepaid = await resolve_or_propose_account(
            item_description="Annual fire insurance policy for head office",
            nature="PREPAYMENT",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res_prepaid.action == "create"
        assert res_prepaid.account_type == "ASSET"
        assert res_prepaid.account_code in ("1420", "1421")
        assert "Prepaid Insurance" in res_prepaid.account_name

        # When 1420 is absent, proposes 1420 directly
        chart_no_1420 = [a for a in sample_chart if a.get("account_code") != "1420"]
        res_clean = await resolve_or_propose_account(
            item_description="Annual fire insurance policy for head office",
            nature="PREPAYMENT",
            chart_of_accounts=chart_no_1420,
            org_context=org_context,
        )
        assert res_clean.account_code == "1420"

        # When monthly / operating expense -> Insurance Expense (6410)
        res_exp = await resolve_or_propose_account(
            item_description="Monthly health insurance premium",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res_exp.action == "create"
        assert res_exp.account_type == "EXPENSE"
        assert res_exp.account_code == "6410"
        assert "Insurance Expense" in res_exp.account_name


class TestPPEEquipmentAndVehicles:
    """Test resolution of PPE capital acquisitions under IAS 16."""

    @pytest.mark.asyncio
    async def test_reuse_existing_ppe_ledger(self, sample_chart, org_context):
        # sample_chart already has acc-1520 "Computer & IT Equipment"
        res = await resolve_or_propose_account(
            item_description="5 Dell XPS laptops for development staff",
            nature="FIXED_ASSET",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res.action == "reuse"
        assert res.is_new is False
        assert res.account_id == "acc-1520"
        assert res.account_code == "1520"
        assert res.account_type == "ASSET"
        assert res.normal_balance == "DEBIT"

    @pytest.mark.asyncio
    async def test_propose_new_vehicle_ledger_under_ppe(self, sample_chart, org_context):
        # Vehicles (1540) is not in sample_chart
        res = await resolve_or_propose_account(
            item_description="Toyota Hilux pickup truck for deliveries",
            nature="FIXED_ASSET",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res.action == "create"
        assert res.is_new is True
        assert res.account_code == "1540"
        assert res.account_name == "Motor Vehicles"
        assert res.account_type == "ASSET"
        assert res.normal_balance == "DEBIT"
        # Statement-section invariant: Must be parented under PPE heading (1500)
        assert res.parent_account_id == "acc-1500"
        assert res.parent_account_name == "Property, Plant & Equipment"

    @pytest.mark.asyncio
    async def test_machinery_and_generators(self, sample_chart, org_context):
        res = await resolve_or_propose_account(
            item_description="50kVA Perkins Diesel Generator for factory backup",
            nature="FIXED_ASSET",
            chart_of_accounts=sample_chart,
            org_context=org_context,
        )
        assert res.action == "create"
        assert res.account_code == "1530"
        assert "Plant, Machinery & Generators" in res.account_name
        assert res.parent_account_id == "acc-1500"


class TestStatementSectionAndContraGuards:
    """Test strict enforcement of statement-section invariant and contra guard."""

    def test_contra_account_detection(self):
        contra_1 = {"name": "Accumulated Depreciation - Vehicles", "account_type": "ASSET", "normal_balance": "CREDIT"}
        contra_2 = {"name": "Contra Asset Account", "account_type": "ASSET", "normal_balance": "CREDIT"}
        regular = {"name": "Motor Vehicles", "account_type": "ASSET", "normal_balance": "DEBIT"}

        assert _is_contra_account(contra_1) is True
        assert _is_contra_account(contra_2) is True
        assert _is_contra_account(regular) is False

    @pytest.mark.asyncio
    async def test_contra_account_never_debited_for_asset_cost(self, org_context):
        """Even if chart contains accumulated depreciation for IT, it is never reused for purchase."""
        chart_with_only_contra = [
            {"id": "acc-1010", "name": "Cash in Hand", "account_type": "ASSET", "normal_balance": "DEBIT"},
            {"id": "acc-1580", "name": "Accumulated Depreciation - Computer Equipment", "account_type": "ASSET", "normal_balance": "CREDIT"},
        ]
        res = await resolve_or_propose_account(
            item_description="MacBook Pro for lead developer",
            nature="FIXED_ASSET",
            chart_of_accounts=chart_with_only_contra,
            org_context=org_context,
        )
        # Must NOT reuse the contra account!
        assert res.action == "create"
        assert res.account_id != "acc-1580"
        assert res.account_type == "ASSET"
        assert res.normal_balance == "DEBIT"
        assert res.account_code == "1520"

    @pytest.mark.asyncio
    async def test_statement_section_invariant_rejects_current_assets_as_parent(self, org_context):
        """When chart has only Current Assets (AR, Bank, Cash), PPE is NEVER parented under them."""
        current_assets_only_chart = [
            {"id": "acc-1010", "name": "Cash in Hand", "account_type": "ASSET", "normal_balance": "DEBIT"},
            {"id": "acc-1020", "name": "Meezan Bank Ltd", "account_type": "ASSET", "normal_balance": "DEBIT"},
            {"id": "acc-1110", "name": "Accounts Receivable", "account_type": "ASSET", "normal_balance": "DEBIT"},
            {"id": "acc-1060", "name": "Sales Tax Recoverable", "account_type": "ASSET", "normal_balance": "DEBIT"},
        ]
        res = await resolve_or_propose_account(
            item_description="Honda Civic Delivery Car",
            nature="FIXED_ASSET",
            chart_of_accounts=current_assets_only_chart,
            org_context=org_context,
        )
        assert res.action == "create"
        assert res.account_type == "ASSET"
        # Must be top-level (None), NEVER parented under AR, Bank, Cash, or Tax!
        assert res.parent_account_id is None
        assert res.parent_account_name is None


class TestCodeAllocationIncrement:
    """Test account code allocation and incrementing rules (§3.3)."""

    def test_next_free_code_when_base_code_absent(self):
        chart = [{"account_code": "1010"}, {"account_code": "2010"}]
        assert _next_free_code("6210", chart) == "6210"

    def test_next_free_code_increments_when_base_present(self):
        chart = [
            {"account_code": "6210"},
            {"account_code": "6211"},
        ]
        # Next under 621x should be 6212
        assert _next_free_code("6210", chart) == "6212"

    def test_next_free_code_with_gap(self):
        chart = [
            {"account_code": "6210"},
            {"account_code": "6213"},
        ]
        assert _next_free_code("6210", chart) == "6214"


class TestLLMMappingAndFallback:
    """Test LLM integration and graceful fallback."""

    @pytest.mark.asyncio
    async def test_llm_mock_success(self, sample_chart, org_context):
        class StubClient:
            async def generate_text_light(self, prompt: str) -> str:
                return (
                    '{"action": "create", "account_name": "Custom Cloud Compute Ledger", '
                    '"account_code": "6215", "account_type": "EXPENSE", "normal_balance": "DEBIT", '
                    '"category": "Cloud Infrastructure", "reasoning": "Specialized cloud workload"}'
                )

        res = await resolve_or_propose_account(
            item_description="Custom AI training compute on Kubernetes cluster",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
            client=StubClient(),
        )
        assert res.action == "create"
        assert res.account_name == "Custom Cloud Compute Ledger"
        assert res.account_code == "6215"
        assert res.account_type == "EXPENSE"

    @pytest.mark.asyncio
    async def test_llm_fallback_on_exception(self, sample_chart, org_context):
        class FailingClient:
            async def generate_text_light(self, prompt: str) -> str:
                raise RuntimeError("LLM provider timeout")

        # Graceful fallback to deterministic resolution
        res = await resolve_or_propose_account(
            item_description="AWS S3 storage bills",
            nature="OPERATING_EXPENSE",
            chart_of_accounts=sample_chart,
            org_context=org_context,
            client=FailingClient(),
        )
        assert res.action == "create"
        assert res.account_code == "6210"
        assert "Cloud" in res.account_name
