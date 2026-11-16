"""Unit tests for Semantic Catalog Reconciler (Task 4).

Tests packaging variant detection, distinguishing resale goods from services,
preventing one-off office expenses from bloating catalog, and semantic deduplication.
"""

from __future__ import annotations

import pytest

from app.catalog_reconciler import (
    CatalogReconciliationResult,
    compute_semantic_similarity,
    is_office_consumable_expense,
    parse_packaging_variant,
    reconcile_catalog_item,
)


@pytest.fixture
def sample_catalog_products():
    return [
        {
            "id": "prod-001",
            "name": "Logitech Mouse",
            "product_code": "PRD-0001",
            "is_stock_tracked": True,
        },
        {
            "id": "prod-002",
            "name": "A4 Paper",
            "product_code": "PRD-0002",
            "is_stock_tracked": True,
        },
        {
            "id": "prod-003",
            "name": "Pilot Pen",
            "product_code": "PRD-0003",
            "is_stock_tracked": True,
        },
        {
            "id": "prod-004",
            "name": "Dell Latitude 5420",
            "product_code": "PRD-0004",
            "is_stock_tracked": True,
        },
        {
            "id": "prod-005",
            "name": "Logitech Wireless Keyboard",
            "product_code": "PRD-0005",
            "is_stock_tracked": True,
        },
    ]


@pytest.fixture
def sample_catalog_services():
    return [
        {
            "id": "serv-001",
            "name": "Software Architecture Consulting",
            "service_code": "SRV-0001",
        },
        {
            "id": "serv-002",
            "name": "Monthly SEO & Marketing Retainer",
            "service_code": "SRV-0002",
        },
        {
            "id": "serv-003",
            "name": "HVAC Maintenance Service",
            "service_code": "SRV-0003",
        },
    ]


class TestPackagingVariantDetection:
    """Test parsing and matching packaging variants against base catalog items."""

    def test_parse_packaging_variant_patterns(self):
        unit, mult, base = parse_packaging_variant("Box of 10 Logitech Mice")
        assert unit == "Box"
        assert mult == 10
        assert base == "Logitech Mouse"

        unit, mult, base = parse_packaging_variant("Carton of 25 A4 Paper Reams")
        assert unit == "Carton"
        assert mult == 25
        assert "A4 Paper" in base

        unit, mult, base = parse_packaging_variant("Pack of 12 Pilot Pens")
        assert unit == "Pack"
        assert mult == 12
        assert base == "Pilot Pen"

        unit, mult, base = parse_packaging_variant("Dozen Coffee Mugs")
        assert unit == "Dozen"
        assert mult == 12
        assert base == "Coffee Mug"

        unit, mult, base = parse_packaging_variant("Logitech Mouse (Box of 10)")
        assert mult == 10
        assert base == "Logitech Mouse"

    @pytest.mark.asyncio
    async def test_reconcile_packaging_variant_to_existing_product(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="Box of 10 Logitech Mice",
            is_inventory=True,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert isinstance(res, CatalogReconciliationResult)
        assert res.action == "match_product"
        assert res.matched_id == "prod-001"
        assert res.matched_name == "Logitech Mouse"
        assert res.matched_type == "product"
        assert res.packaging_multiplier == 10
        assert res.packaging_unit == "Box"
        assert res.is_inventory is True
        assert res.is_stock_tracked is True

    @pytest.mark.asyncio
    async def test_reconcile_carton_variant(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="Carton of 25 A4 Paper",
            is_inventory=True,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert res.action == "match_product"
        assert res.matched_id == "prod-002"
        assert res.packaging_multiplier == 25
        assert res.packaging_unit == "Carton"


class TestOfficeConsumableGuard:
    """Test prevention of one-off office consumables from bloating the product catalog."""

    def test_consumable_pattern_detection(self):
        assert is_office_consumable_expense("HP LaserJet printer toner cartridge") is True
        assert is_office_consumable_expense("2 packs of AAA batteries for remotes") is True
        assert is_office_consumable_expense("1 kg Coffee beans and milk for office") is True
        assert is_office_consumable_expense("Whiteboard markers and sticky notes") is True
        assert is_office_consumable_expense("Cleaning detergent and trash bags") is True
        assert is_office_consumable_expense("Dell XPS 15 Laptop") is False
        assert is_office_consumable_expense("Logitech Mouse") is False

    @pytest.mark.asyncio
    async def test_consumable_marked_as_expense_only(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="Black toner cartridge for office printer",
            is_inventory=False,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert res.action == "expense_only"
        assert res.matched_id is None
        assert res.is_inventory is False
        assert res.is_stock_tracked is False
        assert "IAS 1" in res.reasoning or "Account 6190" in res.reasoning

    @pytest.mark.asyncio
    async def test_pantry_coffee_marked_as_expense_only(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="2 jars of instant coffee and tea bags for office pantry",
            is_inventory=False,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert res.action == "expense_only"
        assert res.is_stock_tracked is False


class TestProductVsServiceDisambiguation:
    """Test distinguishing physical inventory resale goods from service offerings."""

    @pytest.mark.asyncio
    async def test_match_existing_service(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="Monthly Software Architecture Consulting",
            is_inventory=False,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert res.action == "match_service"
        assert res.matched_id == "serv-001"
        assert res.matched_name == "Software Architecture Consulting"
        assert res.matched_type == "service"
        assert res.is_inventory is False

    @pytest.mark.asyncio
    async def test_create_new_service_when_no_match(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="Quarterly Cybersecurity Penetration Testing Service",
            is_inventory=False,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert res.action == "create_service"
        assert res.matched_id is None
        assert res.matched_type == "service"
        assert res.is_inventory is False
        assert res.is_stock_tracked is False

    @pytest.mark.asyncio
    async def test_create_new_product_for_inventory(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="Mechanical Gaming Keyboards RGB",
            is_inventory=True,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert res.action == "create_product"
        assert res.matched_id is None
        assert res.matched_type == "product"
        assert res.is_inventory is True
        assert res.is_stock_tracked is True


class TestSemanticSimilarityThreshold:
    """Test semantic similarity matching (>= 0.90 threshold vs conflicts)."""

    def test_semantic_similarity_scores(self):
        # High similarity (minor phrasing / extra brand descriptors)
        sim_high = compute_semantic_similarity("Dell Latitude 5420 Laptop", "Dell Latitude 5420")
        assert sim_high >= 0.90

        # Conflicting items must NOT match
        sim_conflict = compute_semantic_similarity("Logitech Mouse", "Logitech Keyboard")
        assert sim_conflict < 0.50

        sim_brands = compute_semantic_similarity("Honda 125 Bike", "Yamaha 125 Bike")
        assert sim_brands < 0.50

    @pytest.mark.asyncio
    async def test_match_high_similarity_product(
        self, sample_catalog_products, sample_catalog_services
    ):
        res = await reconcile_catalog_item(
            item_description="Dell Latitude 5420 Laptop i7",
            is_inventory=True,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        assert res.action == "match_product"
        assert res.matched_id == "prod-004"
        assert res.confidence >= 0.90

    @pytest.mark.asyncio
    async def test_conflicting_product_does_not_match(
        self, sample_catalog_products, sample_catalog_services
    ):
        # Logitech Keyboard must NOT match Logitech Mouse (prod-001)
        res = await reconcile_catalog_item(
            item_description="Logitech Wireless Mouse M185",
            is_inventory=True,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
        )
        # Should match Logitech Mouse (prod-001), NOT Logitech Keyboard (prod-005)
        assert res.action == "match_product"
        assert res.matched_id == "prod-001"
        assert res.matched_id != "prod-005"


class TestLLMReconciliationAndGrounding:
    """Test LLM grounding and fallback execution."""

    @pytest.mark.asyncio
    async def test_llm_grounded_match(self, sample_catalog_products, sample_catalog_services):
        class StubClient:
            async def generate_text_light(self, prompt: str) -> str:
                return (
                    '{"action": "match_product", "matched_product_index": 1, '
                    '"packaging_multiplier": 10, "packaging_unit": "Box", '
                    '"confidence": 0.98, "reasoning": "Bulk pack of Logitech Mice"}'
                )

        res = await reconcile_catalog_item(
            item_description="Pack of 10 Logitech Mice",
            is_inventory=True,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
            client=StubClient(),
        )
        assert res.action == "match_product"
        assert res.matched_id == "prod-001"
        assert res.packaging_multiplier == 10
        assert res.packaging_unit == "Box"

    @pytest.mark.asyncio
    async def test_llm_grounding_guard_rejects_out_of_bounds_index(
        self, sample_catalog_products, sample_catalog_services
    ):
        class HallucinatingClient:
            async def generate_text_light(self, prompt: str) -> str:
                # 99 is impossible index
                return '{"action": "match_product", "matched_product_index": 99}'

        # Should safely discard out-of-bounds index and fallback to deterministic
        res = await reconcile_catalog_item(
            item_description="Logitech Mouse",
            is_inventory=True,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
            client=HallucinatingClient(),
        )
        assert res.action == "match_product"
        assert res.matched_id == "prod-001"

    @pytest.mark.asyncio
    async def test_llm_fallback_on_network_failure(
        self, sample_catalog_products, sample_catalog_services
    ):
        class FailingClient:
            async def generate_text_light(self, prompt: str) -> str:
                raise ConnectionError("LLM API endpoint unreachable")

        res = await reconcile_catalog_item(
            item_description="Toner cartridge for office printer",
            is_inventory=False,
            catalog_products=sample_catalog_products,
            catalog_services=sample_catalog_services,
            client=FailingClient(),
        )
        # Successfully falls back to deterministic check
        assert res.action == "expense_only"
