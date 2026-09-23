"""P1-⑧ (forensic latency report ⑧): classifier short-circuit.

Finding: classify_transaction paid up to ~6 DB round-trips (account-by-
nature searches, product fetch, propose/candidate expense accounts) whose
outputs have NO consumer on proposal/approved paths (traced):
  * account hints  → deterministic fast path (else-branch, not called),
                     Phase-4 prompt (skipped), accounting-engine hints only
                     arrive as tool ARGUMENTS (proposal-supplied);
  * config-gap question → suppressed by the `_reasoning_calls is None and
                     approved_tool_calls is None` guard;
  * open_questions (analyze_requirements) → logs only.
NATURE consumers were traced too: build_event_profile consumes
transaction_nature for the executor's prohibited-tools guard — so nature-
affecting lookups (products mapping, 4b COA) are KEPT.

Pinned invariants:
* resolve_account_hints=False → ZERO account-hint lookups, gap branches
  never fire, nature decision unchanged, requires_clarification False;
* default (True) keeps the original resolved-hint behaviour.
"""

import uuid

import pytest

import app.classifier as clf
from app.classifier import classify_transaction

ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _bomb(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("account-hint lookup ran on a short-circuited path")

    monkeypatch.setattr(clf, "_search_account_by_nature", boom)


class TestHintsSkipped:
    @pytest.mark.asyncio
    async def test_explicit_nature_skips_hint_lookup(self, monkeypatch):
        _bomb(monkeypatch)
        result = await classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={
                "item_description": "office chairs",
                "transaction_nature": "OPERATING_EXPENSE",
            },
            message="expense for office chairs",
            resolve_account_hints=False,
        )
        assert result.transaction_nature == "OPERATING_EXPENSE"
        assert result.source == "USER_ANSWER"
        assert result.account_hint_id is None
        assert result.requires_clarification is False

    @pytest.mark.asyncio
    async def test_asset_lifecycle_nature_without_db(self, monkeypatch):
        _bomb(monkeypatch)
        result = await classify_transaction(
            organization_id=ORG,
            intent="register_fixed_asset",
            entities={"item_description": "laptop"},
            message="register the laptop as an asset",
            resolve_account_hints=False,
        )
        assert result.transaction_nature == "FIXED_ASSET"
        assert result.account_hint_id is None
        assert result.requires_clarification is False

    @pytest.mark.asyncio
    async def test_rule_based_nature_still_resolved(self, monkeypatch):
        _bomb(monkeypatch)

        async def no_products(*a, **k):
            return []

        monkeypatch.setattr("app.database.fetch_many", no_products)
        result = await classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={"item_description": "Facebook advertising campaign"},
            message=(
                "I spent 15,000 PKR cash on a Facebook advertising campaign"
            ),
            resolve_account_hints=False,
        )
        # Nature from DETERMINISTIC_RULES (DB-free) — the guard of ⑧.
        assert result.transaction_nature == "OPERATING_EXPENSE"
        assert result.account_hint_id is None
        assert result.requires_clarification is False


class TestDefaultUnchanged:
    @pytest.mark.asyncio
    async def test_default_path_still_resolves_hints(self, monkeypatch):
        calls = {"n": 0}

        async def fake_search(organization_id, nature, item=None):
            calls["n"] += 1
            return {"id": "a-1", "code": "6151", "name": "Advertising & Marketing"}

        monkeypatch.setattr(clf, "_search_account_by_nature", fake_search)
        result = await classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={
                "item_description": "office chairs",
                "transaction_nature": "OPERATING_EXPENSE",
            },
            message="expense for office chairs",
        )
        assert calls["n"] == 1
        assert result.account_hint_id == "a-1"
        assert result.requires_clarification is False
