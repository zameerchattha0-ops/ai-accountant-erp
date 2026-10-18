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
