"""P1-⑦ (forensic latency report ⑦): lightweight build_context.

Finding (report §2/§4): org preferences were fetched TWICE per turn (agent
+ build_context wave 2); static context rules were re-queried every turn
(1+N rows); the seven domain fetches ran even when a validated reasoning
proposal owned the plan (Phase 4 — their only heavy consumer — was skipped;
production CONTEXT_LOADING logged customers=0 suppliers=0 accounts=0 for
queries that ran for nothing).

Pinned invariants:
* caller-passed org_preferences → preference query NEVER runs;
* domain_fetches=False → domain helpers NEVER called (empty structure);
* rules cache: first call queries, second call is zero-I/O (peek hit);
* cold path (empty cache) keeps the original two-wave behaviour.
"""

import uuid

import pytest

import app.context_manager as cm
from app.database import (
    clear_context_rules_cache,
    get_context_sources_for_intent,
    peek_context_rules_cache,
)

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture(autouse=True)
def _fresh_rules_cache():
    clear_context_rules_cache()
    yield
    clear_context_rules_cache()


def _patch_org_repos(monkeypatch):
    async def get_org(**kw):
        return {"name": "Test Org"}

    async def get_fy(*a, **kw):
        return {"year": 2026}

    async def get_period(*a, **kw):
        return {"label": "Sep 2026"}

    monkeypatch.setattr(
        "app.repositories.organization_repository.get_organization", get_org
    )
    monkeypatch.setattr(
        "app.repositories.organization_repository.get_current_financial_year",
        get_fy,
    )
    monkeypatch.setattr(
        "app.repositories.organization_repository.get_open_accounting_period",
        get_period,
    )


async def _warm_rules(monkeypatch, intent="record_expense", required=None):
    calls = {"n": 0}

    async def fake_fetch_one(table, filters=None, **kw):
        calls["n"] += 1
        if table == "ai_context_rules":
            return {
                "intent": intent,
                "status": "ACTIVE",
                "required_sources": list(required or []),
                "optional_sources": [],
            }
        return {"slug": (filters or {}).get("slug"), "status": "ACTIVE"}

    monkeypatch.setattr("app.database.fetch_one", fake_fetch_one)
    await get_context_sources_for_intent(intent)
    return calls


class TestOrgPreferencesPassthrough:
    @pytest.mark.asyncio
    async def test_passed_preferences_skip_the_query(self, monkeypatch):
        _patch_org_repos(monkeypatch)
        await _warm_rules(monkeypatch)

        async def boom(*a, **k):
            raise AssertionError("duplicate org-preferences query ran")

        monkeypatch.setattr(
            "app.services.preference_service.get_all_preferences", boom
        )

        context = await cm.build_context(
            organization_id=ORG,
            user_id=USER,
            intent="record_expense",
            org_preferences={"payment_terms": "CREDIT"},
        )
        assert context.org_preferences == {"payment_terms": "CREDIT"}
        assert context.organization.get("name") == "Test Org"


class TestDeferredDomainFetches:
    @pytest.mark.asyncio
    async def test_domain_helpers_never_called_when_disabled(self, monkeypatch):
        _patch_org_repos(monkeypatch)
        await _warm_rules(monkeypatch, required=["customer_master"])
        calls = {"n": 0}

        async def counted(*a, **k):
            calls["n"] += 1
            return [{"id": "c-1"}]

        monkeypatch.setattr(cm, "_fetch_customers", counted)

        context = await cm.build_context(
            organization_id=ORG,
            user_id=USER,
            intent="record_expense",
            entity_hints={"customer_name": "FDS Labs Pvt"},  # would fetch
            org_preferences={},
            domain_fetches=False,
        )
        assert calls["n"] == 0  # the report's wave-2 skip, pinned
        assert context.relevant_customers == []
        assert context.relevant_accounts == []


class TestContextRulesCache:
    @pytest.mark.asyncio
    async def test_warm_second_call_is_zero_io(self, monkeypatch):
        calls = {"n": 0}

        async def fake_fetch_one(table, filters=None, **kw):
            calls["n"] += 1
            if table == "ai_context_rules":
                return {
                    "intent": "record_receipt",
                    "status": "ACTIVE",
                    "required_sources": ["bank_accounts"],
                    "optional_sources": [],
                }
            return {"slug": (filters or {}).get("slug"), "status": "ACTIVE"}

        monkeypatch.setattr("app.database.fetch_one", fake_fetch_one)
        first = await get_context_sources_for_intent("record_receipt")
        after_first = calls["n"]
        assert after_first > 0
        assert peek_context_rules_cache("record_receipt") is first

        second = await get_context_sources_for_intent("record_receipt")
        assert second is first
        assert calls["n"] == after_first  # zero I/O on the warm hit

        clear_context_rules_cache()
        assert peek_context_rules_cache("record_receipt") is None
