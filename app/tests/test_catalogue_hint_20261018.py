"""Catalogue-hinted nature question (user rule 2026-10-18).

A PURCHASE whose item matches an existing STOCK-TRACKED product must ask
"record as INVENTORY (consistent with your stock), or is it a FIXED ASSET
this time?" — never decide silently either way; SALES of tracked stock keep
the silent INVENTORY path (selling tracked stock IS inventory).  Matching
is word-level so 'office chair' finds catalogue 'chairs' (the old
substring check missed it live and the LLM suggested FIXED ASSET).
"""
import uuid

import pytest

import app.classifier as classifier_mod
from app.classifier import _classification_question, _match_catalogue, classify_transaction
from app.reasoning import nature_question_with_hint


CHAIRS = {
    "id": str(uuid.uuid4()),
    "name": "chairs",
    "product_code": "PRD-000002",
    "is_stock_tracked": True,
    "revenue_account_id": None,
}
LAPTOPS = {
    "id": str(uuid.uuid4()),
    "name": "Laptops",
    "product_code": "PRD-000003",
    "is_stock_tracked": False,
    "revenue_account_id": None,
}


# --- word-level matcher ----------------------------------------------------
def test_match_catalogue_matches_across_plural_forms():
    assert _match_catalogue("office chair", [CHAIRS]) == CHAIRS


def test_match_catalogue_no_overlap_returns_none():
    assert _match_catalogue("office chair", [LAPTOPS]) is None


def test_match_catalogue_stock_tracked_wins_equal_overlap():
    plain = {"name": "chairs", "is_stock_tracked": False}
    assert _match_catalogue("chair", [plain, CHAIRS]) == CHAIRS


def test_match_catalogue_ignores_short_common_words():
    # 'ac' (<3 chars) must not match 'ac unit' style names spuriously
    noisy = {"name": "Ace cleaning", "is_stock_tracked": False}
    assert _match_catalogue("chair", [noisy]) is None


# --- SUBSET-CONTAINMENT GATE (2026-10-20, per-item tracking) ----------------
def test_distinct_items_sharing_one_generic_word_never_merge():
    """'office chair' must NOT match 'dining chair' — they share only the
    generic 'chair' but are different products.  The old any-overlap rule
    merged them into one row and corrupted per-item stock tracking."""
    dining = {"name": "dining chair", "is_stock_tracked": True}
    assert _match_catalogue("office chair", [dining]) is None


def test_distinct_products_with_a_shared_token_stay_separate():
    honda = {"name": "Honda bike", "is_stock_tracked": True}
    yamaha = {"name": "Yamaha bike", "is_stock_tracked": True}
    assert _match_catalogue("Honda bike", [yamaha]) is None
    assert _match_catalogue("Honda bike", [honda]) == honda


def test_subset_synonym_still_matches_both_directions():
    chairs = {"name": "chairs", "is_stock_tracked": True}
    # item longer than product (extra qualifier) -> product fully contained
    assert _match_catalogue("blue office chair", [chairs]) == chairs
    # product longer than item (item fully contained in product)
    office = {"name": "office chair", "is_stock_tracked": True}
    assert _match_catalogue("chair", [office]) == office


# --- question shaper -------------------------------------------------------
def test_shaped_question_is_inventory_first_with_fixed_asset_escape():
    hint = {"name": "chairs", "product_code": "PRD-000002", "is_stock_tracked": True}
    q = nature_question_with_hint("office chair", hint)
    assert q is not None
    assert "chairs (PRD-000002)" in q
    assert "INVENTORY purchase" in q
    assert "FIXED ASSET" in q
    assert q.index("INVENTORY purchase") < q.index("FIXED ASSET")  # inventory first


def test_shaped_question_requires_a_stock_tracked_hint():
    assert nature_question_with_hint("laptop", None) is None
    assert nature_question_with_hint(
        "laptop", {"name": "Laptops", "is_stock_tracked": False}
    ) is None


# --- LLM ITEM-NATURE ANALYST (2026-10-20) ----------------------------------
@pytest.mark.asyncio
async def test_analyst_routes_resale_to_inventory(monkeypatch):
    """INVENTORY_ONLY + stated resale purpose -> routes to INVENTORY, no ask."""
    from app.config import get_settings

    get_settings().llm_item_nature_enabled = True

    class _StubClient:
        async def generate_text_light(self, prompt):
            return ('{"location": "INVENTORY_ONLY", "inventory_index": 1, '
                    '"asset_index": null, "purpose": "RESALE", '
                    '"proposed_nature": "INVENTORY", "confidence": "HIGH", '
                    '"needs_question": false, "question": "", '
                    '"reasoning": "resale stock"}')

    import app.ai_orchestrator as orch
    monkeypatch.setattr(orch, "get_client", lambda: _StubClient())

    async def _products(*_a, **_k):
        return [CHAIRS]

    async def _assets(*_a, **_k):
        return []

    monkeypatch.setattr("app.database.fetch_many", _products)
    from app.repositories import fixed_asset_repository as far
    monkeypatch.setattr(far, "list_assets", _assets)

    cls = await classify_transaction(
        organization_id=uuid.uuid4(),
        intent="record_purchase",
        entities={"item_description": "office chair"},
        message="I bought office chairs to resell in our shop",
        resolve_account_hints=False,
    )
    assert cls.transaction_nature == "INVENTORY"
    assert cls.requires_clarification is False


@pytest.mark.asyncio
async def test_analyst_asks_when_item_is_in_both_registers(monkeypatch):
    """Same item in BOTH registers with no stated purpose -> genuinely
    ambiguous, so it ASKS (never guesses)."""
    from app.config import get_settings

    get_settings().llm_item_nature_enabled = True

    class _StubClient:
        async def generate_text_light(self, prompt):
            return ('{"location": "BOTH", "inventory_index": 1, '
                    '"asset_index": 1, "purpose": "UNKNOWN", '
                    '"proposed_nature": null, "confidence": "MEDIUM", '
                    '"needs_question": true, "question": "Is this bike for '
                    'resale or business use?", "reasoning": "in both"}')

    import app.ai_orchestrator as orch
    monkeypatch.setattr(orch, "get_client", lambda: _StubClient())

    async def _products(*_a, **_k):
        return [{"id": str(uuid.uuid4()), "name": "bike",
                 "product_code": "PRD-1", "is_stock_tracked": True}]

    async def _assets(*_a, **_k):
        return [{"id": str(uuid.uuid4()), "name": "Delivery Bike",
                 "asset_code": "FA-1", "status": "ACTIVE"}]

    monkeypatch.setattr("app.database.fetch_many", _products)
    from app.repositories import fixed_asset_repository as far
    monkeypatch.setattr(far, "list_assets", _assets)

    cls = await classify_transaction(
        organization_id=uuid.uuid4(),
        intent="record_purchase",
        entities={"item_description": "bike"},
        message="I bought a bike",
        resolve_account_hints=False,
    )
    assert cls.requires_clarification is True
    assert cls.transaction_nature is None
    assert "resale" in (cls.clarification_reason or "").lower()


@pytest.mark.asyncio
async def test_analyst_uses_purpose_to_disambiguate(monkeypatch):
    """Purpose-of-use in the query ('for business use') settles a BOTH-match:
    an item that is sometimes stock is treated as a FIXED ASSET here."""
    from app.config import get_settings

    get_settings().llm_item_nature_enabled = True

    class _StubClient:
        async def generate_text_light(self, prompt):
            return ('{"location": "BOTH", "inventory_index": 1, '
                    '"asset_index": 1, "purpose": "BUSINESS_USE", '
                    '"proposed_nature": "FIXED_ASSET", "confidence": "HIGH", '
                    '"needs_question": false, "question": "", '
                    '"reasoning": "business use stated"}')

    import app.ai_orchestrator as orch
    monkeypatch.setattr(orch, "get_client", lambda: _StubClient())

    async def _products(*_a, **_k):
        return [{"id": str(uuid.uuid4()), "name": "bike",
                 "product_code": "PRD-1", "is_stock_tracked": True}]

    async def _assets(*_a, **_k):
        return [{"id": str(uuid.uuid4()), "name": "Delivery Bike",
                 "asset_code": "FA-1", "status": "ACTIVE"}]

    monkeypatch.setattr("app.database.fetch_many", _products)
    from app.repositories import fixed_asset_repository as far
    monkeypatch.setattr(far, "list_assets", _assets)

    cls = await classify_transaction(
        organization_id=uuid.uuid4(),
        intent="record_purchase",
        entities={"item_description": "bike"},
        message="I bought a bike for business use",
        resolve_account_hints=False,
    )
    assert cls.transaction_nature == "FIXED_ASSET"  # purpose settled it
    assert cls.requires_clarification is False


@pytest.mark.asyncio
async def test_analyst_out_of_range_index_is_never_trusted(monkeypatch):
    """A grounding violation (index beyond the fetched list) is impossible
    evidence — treated as no match, never a phantom-product hint."""
    from app.config import get_settings

    get_settings().llm_item_nature_enabled = True

    class _StubClient:
        async def generate_text_light(self, prompt):
            return ('{"location": "INVENTORY_ONLY", "inventory_index": 99, '
                    '"asset_index": null, "purpose": "RESALE", '
                    '"proposed_nature": "INVENTORY", "confidence": "LOW", '
                    '"needs_question": false, "question": "", '
                    '"reasoning": "phantom index"}')

    import app.ai_orchestrator as orch
    monkeypatch.setattr(orch, "get_client", lambda: _StubClient())

    async def _products(*_a, **_k):
        return [{"id": str(uuid.uuid4()), "name": "chair",
                 "product_code": "PRD-1", "is_stock_tracked": True}]

    async def _assets(*_a, **_k):
        return []

    monkeypatch.setattr("app.database.fetch_many", _products)
    from app.repositories import fixed_asset_repository as far
    monkeypatch.setattr(far, "list_assets", _assets)

    cls = await classify_transaction(
        organization_id=uuid.uuid4(),
        intent="record_purchase",
        entities={"item_description": "chair"},
        message="I bought a chair for resale",
        resolve_account_hints=False,
    )
    # the phantom index is discarded -> no hint may reference a product the
    # analyst did not actually ground.
    assert cls.catalogue_hint is None


# --- classifier behaviour --------------------------------------------------
@pytest.mark.asyncio
async def test_purchase_of_stock_matched_item_asks_inventory_or_fixed_asset(monkeypatch):
    async def _fake(*_a, **_k):
        return [CHAIRS]

    monkeypatch.setattr("app.database.fetch_many", _fake)
    cls = await classify_transaction(
        organization_id=uuid.uuid4(),
        intent="record_purchase",
        entities={"item_description": "office chair"},
        resolve_account_hints=False,
    )
    assert cls.requires_clarification is True
    assert cls.transaction_nature is None  # never decided silently
    assert cls.catalogue_hint and cls.catalogue_hint["is_stock_tracked"] is True
    assert "chairs" in (cls.clarification_reason or "")
    assert "INVENTORY purchase" in (cls.clarification_reason or "")
    question = _classification_question(cls)
    assert "office chair" in question and "chairs (PRD-000002)" in question
    assert "FIXED ASSET" in question


@pytest.mark.asyncio
async def test_sale_of_tracked_stock_stays_silent_inventory(monkeypatch):
    async def _fake(*_a, **_k):
        return [CHAIRS]

    monkeypatch.setattr("app.database.fetch_many", _fake)
    cls = await classify_transaction(
        organization_id=uuid.uuid4(),
        intent="record_sale",
        entities={"item_description": "chairs"},
        resolve_account_hints=False,
    )
    assert cls.transaction_nature == "INVENTORY"
    assert cls.requires_clarification is False  # selling stock is not ambiguous


@pytest.mark.asyncio
async def test_non_stock_durable_keeps_the_generic_decision_tree(monkeypatch):
    async def _fake(*_a, **_k):
        return [LAPTOPS]

    monkeypatch.setattr("app.database.fetch_many", _fake)
    cls = await classify_transaction(
        organization_id=uuid.uuid4(),
        intent="record_purchase",
        entities={"item_description": "office laptops"},
        resolve_account_hints=False,
    )
    assert cls.requires_clarification is True
    assert cls.transaction_nature is None
    assert "Is this item" in (cls.clarification_reason or "")
    # hint attached but NOT stock-tracked → generic tree, not the shaped one
    question = _classification_question(cls)
    assert "Is this item" in question and "INVENTORY purchase" not in question
