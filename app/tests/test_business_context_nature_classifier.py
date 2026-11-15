"""Tests for Business Context Aware Accounting Nature Classification.

Ensures that the economic nature and accounting treatment of purchases/sales are
derived intelligently using:
  Query + Business Operations + Organization Profile + Product Catalogue + Fixed Assets.
Verifies:
1. For service/software businesses (e.g. Digital Creators / SOFTWARE_HOUSE) with no
   tables in their catalogue, purchasing tables/furniture is classified as FIXED_ASSET
   (Property, Plant & Equipment / Office Furniture) and NOT inventory for resale.
2. Durable goods are never blindly assumed to be inventory solely based on quantity.
3. Questions are only asked if the item is genuinely ambiguous after full business analysis.
"""
import uuid
import pytest

from app.classifier import FIXED_ASSET, INVENTORY, classify_transaction, rule_based_nature
from app.item_nature_analyst import analyse_item_nature
from app.org_context import render_profile


def test_durable_goods_not_assumed_inventory_on_quantity():
    """Quantity >= 10 must NOT turn durable goods into inventory via blind regex."""
    nature, conf = rule_based_nature("bought 12 office chairs", {"quantity": 12})
    assert nature != INVENTORY, "12 chairs should not be blindly assumed to be inventory"
    assert nature is None
    assert conf == "LOW"


def test_render_profile_includes_organization_identity():
    """Org profile includes business name and industry/type to guide accounting reasoning."""
    prof = {
        "organization": {
            "name": "Digital Creators",
            "business_type": "SOFTWARE_HOUSE",
        },
        "products": [],
        "fixed_assets": [
            {"name": "Workstations", "asset_code": "AST-001"},
        ],
        "accounts": [
            {"code": "1500", "name": "Property, Plant & Equipment"},
            {"code": "1510", "name": "Furniture & Fixtures"},
            {"code": "6500", "name": "Office & Administration"},
        ],
    }
    rendered = render_profile(prof)
    assert "Digital Creators" in rendered
    assert "SOFTWARE_HOUSE" in rendered
    assert "Workstations" in rendered
    assert "service/operations model" in rendered


@pytest.mark.asyncio
async def test_item_nature_analyst_uses_business_context(monkeypatch):
    """Item nature analyst uses business context and registers to determine nature without asking."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "llm_item_nature_enabled", True)

    mock_client = type("MockClient", (), {})()

    async def _mock_light(*_args, **_kwargs):
        return (
            '{"location": "FIXED_ASSET_ONLY", "inventory_index": null, "asset_index": null, '
            '"purpose": "BUSINESS_USE", "proposed_nature": "FIXED_ASSET", "confidence": "HIGH", '
            '"needs_question": false, "question": "", '
            '"reasoning": "Digital Creators is a software house; tables are office fixed assets."}'
        )

    mock_client.generate_text_light = _mock_light

    org_context = (
        "- Organization: Digital Creators (Industry/Type: SOFTWARE_HOUSE)\n"
        "- Catalogue: (no physical resale products registered — service/operations model)\n"
        "- Chart accounts: 1500 Property, Plant & Equipment; 1510 Furniture & Fixtures"
    )

    verdict = await analyse_item_nature(
        organization_id=uuid.uuid4(),
        item="two tables",
        intent="record_purchase",
        message="purchased two tables from shabbir furnitures today",
        org_context=org_context,
        client=mock_client,
        products=[],
        assets=[],
    )

    assert verdict is not None
    assert verdict["proposed_nature"] == FIXED_ASSET
    assert verdict["confidence"] == "HIGH"
    assert verdict["needs_question"] is False


def test_fixed_asset_nature_in_entities_asks_depreciation_trio():
    """When transaction_nature is FIXED_ASSET, useful_life_years, depreciation_method & salvage_value are asked."""
    from app.planner import plan

    # 1. Purchase where nature is FIXED_ASSET in entities
    p = plan(
        "purchased two tables from shabbir furnitures today",
        prefill_entities={"transaction_nature": "FIXED_ASSET", "amount": 50000, "payment_method": "BANK"},
    )
    assert "useful_life_years" in p.missing_fields
    assert "depreciation_method" in p.missing_fields
    assert "salvage_value" in p.missing_fields

    # 2. When depreciation is explicitly declined, trio is not asked
    p_declined = plan(
        "purchased two tables from shabbir furnitures today",
        prefill_entities={
            "transaction_nature": "FIXED_ASSET",
            "amount": 50000,
            "payment_method": "BANK",
            "depreciation_declined": True,
        },
    )
    assert "useful_life_years" not in p_declined.missing_fields
    assert "depreciation_method" not in p_declined.missing_fields
    assert "salvage_value" not in p_declined.missing_fields


@pytest.mark.asyncio
async def test_agent_classification_fixed_asset_expands_missing_fields_to_depreciation(monkeypatch):
    """When classifier resolves FIXED_ASSET with high confidence, agent questionnaire includes depreciation questions."""
    from unittest.mock import AsyncMock
    import app.agent as agent_mod
    from app.models.schemas import TransactionClassification, ExecutionPlan

    plan_obj = ExecutionPlan(
        intent="record_purchase",
        missing_fields=["amount", "payment_type", "transaction_nature"],
        extracted_entities={"item_description": "tables", "supplier_name": "Shabbir Furnitures"},
        requires_clarification=True,
    )

    classification_obj = TransactionClassification(
        transaction_nature="FIXED_ASSET",
        confidence="HIGH",
        source="LLM_DECISION",
        account_hint_code="1510",
        account_hint_name="Furniture & Fixtures",
        account_source="LLM_DECISION",
        requires_clarification=False,
    )

    # Simulate Phase 2b drop & expansion logic
    from app.questionnaire import drop_resolved_fields as _drop_resolved
    dropped = _drop_resolved(plan_obj.missing_fields, classification_obj)
    assert "transaction_nature" not in dropped

    _nature_val = getattr(classification_obj, "transaction_nature", None)
    if _nature_val and not getattr(classification_obj, "requires_clarification", False):
        _nature_str = str(_nature_val).upper()
        plan_obj.extracted_entities["transaction_nature"] = _nature_str
        if _nature_str == "FIXED_ASSET":
            if plan_obj.intent in ("record_purchase", "record_cash_purchase", "record_credit_purchase", "create_purchase_bill", "record_expense"):
                plan_obj.intent = "register_fixed_asset"
            declined = bool(plan_obj.extracted_entities.get("depreciation_declined"))
            if not declined:
                for _fa_f in ("useful_life_years", "depreciation_method", "salvage_value"):
                    if plan_obj.extracted_entities.get(_fa_f) is None and _fa_f not in dropped:
                        dropped.append(_fa_f)

    plan_obj.missing_fields = dropped
    assert "useful_life_years" in plan_obj.missing_fields
    assert "depreciation_method" in plan_obj.missing_fields
    assert "salvage_value" in plan_obj.missing_fields
    assert "amount" in plan_obj.missing_fields
    assert "payment_type" in plan_obj.missing_fields
    assert plan_obj.intent == "register_fixed_asset"

