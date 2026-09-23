"""P1-⑨ (forensic latency report §5): parallel gate lookups.

Finding: party → settlement → catalog → revenue gates ran sequentially,
each paying its own read-only DB round-trip before the ask-check (−0.1-0.3s
recoverable).

Pinned invariants:
* all four lookups run CONCURRENTLY (4×50ms ≈ 50ms wall, not 200ms);
* the returned tuple keeps the deterministic order the ask-chain in
  execute() consumes: (party, settlement, catalog, review) — so WHICH
  question the user sees is unchanged.
"""

import asyncio
import time
import uuid

import pytest

import app.agent as agent_mod


class TestGateLookupConcurrency:
    @pytest.mark.asyncio
    async def test_four_lookups_run_concurrently_in_order(self, monkeypatch):
        async def _delayed(name, result):
            async def _gate(**kw):
                await asyncio.sleep(0.05)
                return result
            _gate.__name__ = name
            return _gate

        monkeypatch.setattr(
            agent_mod, "_party_resolution_question",
            await _delayed("party", {"question": "Which party?"}),
        )
        monkeypatch.setattr(
            agent_mod, "_settlement_check_question",
            await _delayed("settlement", None),
        )
        monkeypatch.setattr(
            agent_mod, "_catalog_check_question",
            await _delayed("catalog", None),
        )
        monkeypatch.setattr(
            agent_mod, "_revenue_ledger_review_gate",
            await _delayed("revenue", None),
        )

        start = time.monotonic()
        party, settlement, catalog, review = await agent_mod._resolve_gate_questions(
            organization_id=uuid.uuid4(),
            execution_plan=object(),
        )
        elapsed = time.monotonic() - start

        # Serial would be >= 0.20s; concurrent ~0.05s.
        assert elapsed < 0.15, f"gate lookups were serialized ({elapsed:.3f}s)"
        assert party == {"question": "Which party?"}
        assert settlement is None
        assert catalog is None
        assert review is None

    @pytest.mark.asyncio
    async def test_all_four_results_flow_through_in_position(self, monkeypatch):
        async def _gate(value):
            async def _run(**kw):
                await asyncio.sleep(0.01)
                return value
            return _run

        monkeypatch.setattr(agent_mod, "_party_resolution_question", await _gate("P"))
        monkeypatch.setattr(agent_mod, "_settlement_check_question", await _gate("S"))
        monkeypatch.setattr(agent_mod, "_catalog_check_question", await _gate("C"))
        monkeypatch.setattr(agent_mod, "_revenue_ledger_review_gate", await _gate("R"))

        out = await agent_mod._resolve_gate_questions(
            organization_id=uuid.uuid4(),
            execution_plan=object(),
        )
        assert tuple(out) == ("P", "S", "C", "R")
