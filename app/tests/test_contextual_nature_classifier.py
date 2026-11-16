"""Unit tests for Contextual Accounting Nature Classifier (Task 1).

Specifications tested:
- 4-Dimensional Convergence Engine (Query, OrgProfile, ProductCatalog, AssetRegister).
- Digital Creators case study: Service/Software firm buying office furniture/computers
  classifies as FIXED_ASSET (IAS 16) or OPERATING_EXPENSE (IAS 1 if < 50k and non-bulk).
  NEVER asks "what is the intended use?".
- Trading/Retail org matching catalog classifies as INVENTORY (IAS 2).
- Explicit purpose in query ("for resale" -> INVENTORY, "for office use" -> FIXED_ASSET/EXPENSE).
- Genuinely ambiguous items (e.g. IT reseller buying laptops without purpose) return
  confidence < 0.65 and requires_clarification=True.
- Offline execution with zero database calls (conftest _no_live_database invariant).
- Fail-safe degradation when LLM is unavailable or raises errors.
"""

import pytest
from app.contextual_nature import (
    ContextualNatureResult,
    classify_contextual_nature,
    CAPITALIZATION_SINGLE_ITEM_THRESHOLD_PKR,
    CAPITALIZATION_BULK_THRESHOLD_PKR,
)
from app.config import get_settings


@pytest.mark.asyncio
async def test_digital_creators_five_tables_fixed_asset():
    """Digital Creators (Software House) buying 5 tables for Rs. 150,000.

    Must classify as FIXED_ASSET (IAS 16) via IAS 16.9 aggregate block principle.
    Must NOT classify as INVENTORY (IAS 2).
    Must NOT ask clarification (confidence >= 0.90, requires_clarification=False).
    """
    org_profile = {
        "name": "Digital Creators",
        "business_type": "SOFTWARE_HOUSE",
        "industry": "software and media consultancy",
    }
    catalog_items = []  # No furniture in sales catalog
    asset_items = [
        {"name": "Workstations & Studio Furniture", "asset_code": "AST-001", "category": "Furniture & Fixtures"}
    ]
    query = "Purchasing 5 tables from Shabbir Furniture for Rs. 150,000"
    preliminary = {"item_name": "tables", "quantity": 5, "amount": 150000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=catalog_items,
        asset_items=asset_items,
        preliminary=preliminary,
    )

    assert isinstance(result, ContextualNatureResult)
    assert result.nature == "FIXED_ASSET"
    assert result.standard == "IAS 16"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert result.clarification_question is None
    assert result.is_capitalized is True
    assert result.capitalization_threshold_applied == "BULK_GE_100K"
    assert "Digital Creators" in result.reasoning or "service" in result.reasoning.lower()


@pytest.mark.asyncio
async def test_service_firm_single_expensive_laptop_capitalized():
    """Service firm buying 1 executive laptop for Rs. 75,000 (>= 50k threshold)."""
    org_profile = {
        "name": "Apex Legal Chambers",
        "business_type": "LEGAL_FIRM",
        "industry": "corporate legal consultancy",
    }
    catalog_items = []
    asset_items = [
        {"name": "Computer & IT Equipment", "asset_code": "AST-002", "category": "IT Equipment"}
    ]
    query = "Purchased 1 executive laptop from Dell Store for Rs. 75,000"
    preliminary = {"item_name": "executive laptop", "quantity": 1, "amount": 75000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=catalog_items,
        asset_items=asset_items,
        preliminary=preliminary,
    )

    assert result.nature == "FIXED_ASSET"
    assert result.standard == "IAS 16"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert result.is_capitalized is True
    assert result.capitalization_threshold_applied == "SINGLE_ITEM_GE_50K"


@pytest.mark.asyncio
async def test_service_firm_low_value_chair_expensed():
    """Service firm buying 1 office chair for Rs. 15,000 (< 50k single item, < 100k non-bulk)."""
    org_profile = {
        "name": "Pixel Studio",
        "business_type": "MARKETING_AGENCY",
    }
    query = "Bought 1 office chair for Rs. 15,000"
    preliminary = {"item_name": "office chair", "quantity": 1, "amount": 15000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=[],
        asset_items=[],
        preliminary=preliminary,
    )

    assert result.nature == "OPERATING_EXPENSE"
    assert result.standard == "IAS 1"
    assert result.confidence >= 0.85
    assert result.requires_clarification is False
    assert result.is_capitalized is False
    assert result.capitalization_threshold_applied == "DIRECT_EXPENSE_LT_50K"


@pytest.mark.asyncio
async def test_consumable_supplies_expensed_regardless_of_bulk():
    """Consumable supplies (A4 paper) are expensed under IAS 1 (useful life < 12 months)."""
    org_profile = {
        "name": "CloudNine Technologies",
        "business_type": "SOFTWARE_HOUSE",
    }
    query = "Purchased 20 cartons of A4 paper for Rs. 120,000"
    preliminary = {"item_name": "A4 paper", "quantity": 20, "amount": 120000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=[],
        asset_items=[],
        preliminary=preliminary,
    )

    assert result.nature == "OPERATING_EXPENSE"
    assert result.standard == "IAS 1"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert result.is_capitalized is False
    assert result.capitalization_threshold_applied == "CONSUMABLE_EXPENSE"


@pytest.mark.asyncio
async def test_trading_retail_catalog_match_inventory():
    """Retail company buying items matching active product catalog -> INVENTORY (IAS 2)."""
    org_profile = {
        "name": "Karachi Furnishers",
        "business_type": "RETAIL",
        "industry": "furniture retail",
    }
    catalog_items = [
        {"id": "p-1", "name": "Executive Wooden Desk", "product_code": "FUR-001"}
    ]
    query = "Purchased 10 executive wooden desks from Master Craft for Rs. 350,000"
    preliminary = {"item_name": "Executive Wooden Desk", "quantity": 10, "amount": 350000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=catalog_items,
        asset_items=[],
        preliminary=preliminary,
    )

    assert result.nature == "INVENTORY"
    assert result.standard == "IAS 2"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert result.matched_catalog_item is not None
    assert result.matched_catalog_item["product_code"] == "FUR-001"


@pytest.mark.asyncio
async def test_explicit_purpose_for_resale():
    """Explicit purpose 'for resale' in query overrides and classifies as INVENTORY (IAS 2)."""
    org_profile = {
        "name": "Global Tech Consulting",
        "business_type": "CONSULTING",
    }
    query = "Purchased 5 tablets for resale to client for Rs. 150,000"
    preliminary = {"item_name": "tablets", "quantity": 5, "amount": 150000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=[],
        asset_items=[],
        preliminary=preliminary,
    )

    assert result.nature == "INVENTORY"
    assert result.standard == "IAS 2"
    assert result.confidence == 1.0
    assert result.requires_clarification is False


@pytest.mark.asyncio
async def test_explicit_purpose_for_office_use():
    """Explicit purpose 'for office use' in query capitalizes as FIXED_ASSET if >= threshold."""
    org_profile = {
        "name": "Metro Retail Store",
        "business_type": "RETAIL",
    }
    query = "Purchased 2 laptops for office use for Rs. 160,000"
    preliminary = {"item_name": "laptops", "quantity": 2, "amount": 160000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=[],
        asset_items=[],
        preliminary=preliminary,
    )

    assert result.nature == "FIXED_ASSET"
    assert result.standard == "IAS 16"
    assert result.confidence == 1.0
    assert result.requires_clarification is False
    assert result.is_capitalized is True


@pytest.mark.asyncio
async def test_hybrid_it_reseller_requires_clarification():
    """IT Reseller buying laptops without stating purpose is ambiguous -> requires_clarification=True (conf < 0.65)."""
    org_profile = {
        "name": "ByteZone Systems",
        "business_type": "IT_RESELLER",
        "industry": "computer reseller and retail hardware",
    }
    query = "Purchased 10 Dell laptops for Rs. 850,000"
    preliminary = {"item_name": "Dell laptops", "quantity": 10, "amount": 850000.0}

    result = await classify_contextual_nature(
        query=query,
        org_profile=org_profile,
        catalog_items=[],
        asset_items=[],
        preliminary=preliminary,
    )

    assert result.confidence < 0.65
    assert result.requires_clarification is True
    assert result.clarification_question is not None
    assert "resale" in result.clarification_question.lower() or "fixed asset" in result.clarification_question.lower()


@pytest.mark.asyncio
async def test_llm_mode_with_mock_client(monkeypatch):
    """Verify LLM client pathway when enabled with mock response."""
    class MockClient:
        async def generate_text_light(self, prompt: str):
            return (
                '{\n'
                '  "nature": "FIXED_ASSET",\n'
                '  "standard": "IAS 16",\n'
                '  "confidence": 0.98,\n'
                '  "requires_clarification": false,\n'
                '  "clarification_question": null,\n'
                '  "is_capitalized": true,\n'
                '  "capitalization_threshold_applied": "SINGLE_ITEM_GE_50K",\n'
                '  "reasoning": "High-end development workstation for software development team."\n'
                '}'
            )

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_contextual_nature_enabled", True)

    result = await classify_contextual_nature(
        query="Purchased Apple Mac Studio for Rs. 650,000",
        org_profile={"name": "DevStudio", "business_type": "SOFTWARE_HOUSE"},
        catalog_items=[],
        asset_items=[],
        preliminary={"item_name": "Apple Mac Studio", "amount": 650000.0},
        client=MockClient(),
    )

    assert result.decision_source == "llm"
    assert result.nature == "FIXED_ASSET"
    assert result.standard == "IAS 16"
    assert result.confidence == 0.98
    assert result.requires_clarification is False


@pytest.mark.asyncio
async def test_llm_failure_degrades_gracefully(monkeypatch):
    """When LLM raises exception, degrades gracefully to deterministic fail-safe."""
    class FailingClient:
        async def generate_text_light(self, prompt: str):
            raise TimeoutError("LLM upstream timeout")

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_contextual_nature_enabled", True)

    result = await classify_contextual_nature(
        query="Purchased 5 tables from Shabbir Furniture for Rs. 150,000",
        org_profile={"name": "Digital Creators", "business_type": "SOFTWARE_HOUSE"},
        catalog_items=[],
        asset_items=[],
        preliminary={"item_name": "tables", "quantity": 5, "amount": 150000.0},
        client=FailingClient(),
    )

    assert result.decision_source == "deterministic_fallback"
    assert result.nature == "FIXED_ASSET"
    assert result.standard == "IAS 16"
    assert result.requires_clarification is False
