"""P2-⑫ (forensic latency report ⑫): prompt token diet + stable block
ordering + org/period facts populated from data already loaded.

Pinned invariants:
* STATIC PREFIX contract — the prompt head (rules → request → history →
  preliminary → org → period → policies → hints → prohibitions → tools →
  contracts → catalog → TODAY) is BYTE-identical across rounds; the first
  dynamic byte is the LIVE BOOKS evidence block; violations follow in the
  dynamic tail; _RESPONSE_SHAPE stays last (recency, by design);
* ORGANIZATION PROFILE / ACCOUNTING PERIOD render real rows when provided
  (they used to say "(none provided)" — risking a wasted evidence round);
* evidence rendering dedupes IDENTICAL snapshots only (different args are
  different reads and both render);
* org/period facts load in the background at execute() entry (failure →
  None×3 → every consumer falls back exactly as before); build_context
  reuses passed rows and never fetches them.
"""

import uuid

import pytest

import app.agent as agent_mod
import app.context_manager as cm
from app.accounting_reasoning import (
    _RESPONSE_SHAPE,
    ReasoningFacts,
    build_reasoning_prompt,
)
from app.books_evidence import EvidenceResult, render_evidence, render_evidence_compact

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _facts(**over) -> ReasoningFacts:
    base = dict(
        user_request="record a receipt from FDS Labs",
        conversation_history=[],
        preliminary={},
        org_policies={},
        today="2026-09-24",
        organization={},
        accounting_period={},
    )
    base.update(over)
    return ReasoningFacts(**base)


class TestStaticPrefixOrdering:
    def test_static_head_byte_identical_across_rounds(self):
        p1 = build_reasoning_prompt(
            _facts(), evidence_block="", violations=(),
            offered_tools=["create_customer"],
        )
        p2 = build_reasoning_prompt(
            _facts(),
            evidence_block="LIVE BOOKS EVIDENCE:\n  [parties] rows",
            violations=["'invoice_no' is not a parameter of this tool"],
            offered_tools=["create_customer"],
        )
        head1 = p1[: p1.index(_RESPONSE_SHAPE)]
        # The entire static head (through TODAY) is a byte-identical prefix
        # of the round-2 prompt → prefix/KV caches reuse it wholesale.
        assert p2.startswith(head1)
        # Dynamic tail order: TODAY (static) < evidence < violations < SHAPE.
        assert p2.index("TODAY:") < p2.index("LIVE BOOKS EVIDENCE:")
        assert (
            p2.index("LIVE BOOKS EVIDENCE:")
            < p2.index("REJECTED BY THE EXECUTION LAYER")
            < p2.index(_RESPONSE_SHAPE)
        )

    def test_org_and_period_blocks_render_real_rows(self):
        prompt = build_reasoning_prompt(
            _facts(
                organization={"name": "Acme Traders", "currency": "PKR"},
                accounting_period={"fy_label": "FY2026", "period_label": "Sep 2026"},
            ),
            offered_tools=[],
        )
        org_idx = prompt.index("ORGANIZATION PROFILE:")
        period_idx = prompt.index("ACCOUNTING PERIOD:")
        assert org_idx < period_idx
        assert "Acme Traders" in prompt[org_idx:period_idx]
        assert "FY2026" in prompt[period_idx:]


class TestEvidenceRenderDedupe:
    @staticmethod
    def _row(records):
        return EvidenceResult(
            kind="parties", title="Parties", records=records, source="parties"
        )

    def test_identical_snapshot_renders_once(self):
        out = render_evidence([self._row([{"id": "c1"}]), self._row([{"id": "c1"}])])
        assert out.count("[parties]") == 1

    def test_different_args_rows_both_render(self):
        out = render_evidence([self._row([{"id": "c1"}]), self._row([{"id": "c2"}])])
        assert out.count("[parties]") == 2

    def test_compact_dedupes_identical_lines(self):
        line = render_evidence_compact(
            [self._row([{"id": "c1"}]), self._row([{"id": "c1"}])]
        )
        assert line == "parties=1 row(s)"


class TestOrgPeriodFacts:
    @pytest.mark.asyncio
    async def test_load_gathers_rows_and_failure_is_soft(self, monkeypatch):
        from app.repositories import organization_repository as repo

        async def get_org(*, organization_id):
            return {"name": "Acme Traders", "created_at": "x"}

        async def get_fy(*a, **kw):
            return {"label": "FY2026"}

        async def get_period(*a, **kw):
            return {"label": "Sep 2026"}

        monkeypatch.setattr(repo, "get_organization", get_org)
        monkeypatch.setattr(repo, "get_current_financial_year", get_fy)
        monkeypatch.setattr(repo, "get_open_accounting_period", get_period)
        org, fy, period = await agent_mod._load_org_facts(uuid.uuid4())
        assert org["name"] == "Acme Traders"
        assert fy["label"] == "FY2026"
        assert period["label"] == "Sep 2026"

        async def boom(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(repo, "get_organization", boom)
        assert await agent_mod._load_org_facts(uuid.uuid4()) == (None, None, None)

    def test_slim_row_and_flatten_period(self):
        slim = agent_mod._slim_row(
            {"name": "A", "currency": "PKR", "created_at": "x", "id": "1"},
            agent_mod._ORG_PROFILE_FIELDS,
        )
        assert slim == {"name": "A", "currency": "PKR"}  # whitelist only
        assert agent_mod._slim_row(None, agent_mod._ORG_PROFILE_FIELDS) == {}
        flat = agent_mod._flatten_period({"label": "FY"}, {"label": "Sep"})
        assert flat == {"fy_label": "FY", "period_label": "Sep"}

    @pytest.mark.asyncio
    async def test_build_context_reuses_provided_rows(self, monkeypatch):
        async def boom_repo(*a, **kw):
            raise AssertionError("provided row must skip its fetch")

        from app.repositories import organization_repository as repo

        for fn in (
            "get_organization",
            "get_current_financial_year",
            "get_open_accounting_period",
        ):
            monkeypatch.setattr(repo, fn, boom_repo)

        async def boom_prefs(*a, **kw):
            raise AssertionError("provided prefs must skip their fetch")

        monkeypatch.setattr(
            "app.services.preference_service.get_all_preferences", boom_prefs
        )

        async def fake_fetch_one(table, filters=None, **kw):
            # Cold rules lookup only (org/fy/period/prefs all provided).
            if table == "ai_context_rules":
                return {"intent": "record_expense", "status": "ACTIVE",
                        "required_sources": [], "optional_sources": []}
            return {"slug": (filters or {}).get("slug"), "status": "ACTIVE"}

        monkeypatch.setattr("app.database.fetch_one", fake_fetch_one)

        context = await cm.build_context(
            organization_id=ORG,
            user_id=USER,
            intent="record_expense",
            org_preferences={"payment_terms": "CREDIT"},
            organization={"name": "Provided Org"},
            financial_year={"label": "FY2026"},
            accounting_period={"label": "Sep 2026"},
        )
        assert context.organization == {"name": "Provided Org"}
        assert context.financial_year == {"label": "FY2026"}
        assert context.accounting_period == {"label": "Sep 2026"}
        assert context.org_preferences == {"payment_terms": "CREDIT"}

