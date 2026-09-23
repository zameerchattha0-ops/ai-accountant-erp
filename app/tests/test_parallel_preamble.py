"""P0-④ (forensic latency report ④): parallel preamble + bulk history seed.

Finding: after session insert the preamble ran FOUR sequential round-trips
before any thinking — close-superseded (query), history seed (ONE insert
per Q&A: O(N) per turn, O(N²) per conversation), preference capture
(write) and, later still, org-preferences (query) — measured preamble
~4.2s (11% of the 39s T1).

Pinned invariants:
* seed_clarification_history = ONE insert_many for the whole history,
  identical row shape; empty history → zero writes;
* _preamble_side_effects runs all side-effects CONCURRENTLY (4×50ms
  serial ≥ 200ms vs parallel < 150ms) and returns the org preferences;
* preference capture runs ONLY when prior_qa is present;
* execute() no longer loads org preferences sequentially after document
  extraction (source-pinned).
"""

import asyncio
import time
import uuid
from pathlib import Path

import pytest

import app.agent as agent_mod
import app.database as db

AGENT_PY = Path(__file__).resolve().parents[1] / "agent.py"
SID = uuid.UUID("99999999-9999-9999-9999-999999999999")


class TestBulkHistorySeed:
    @pytest.mark.asyncio
    async def test_three_qa_single_bulk_insert(self, monkeypatch):
        captured: list = []

        async def fake_insert_many(table_name, *, data):
            captured.append((table_name, data))
            return data

        monkeypatch.setattr(db, "insert_many", fake_insert_many)

        async def boom_insert_one(*a, **k):
            raise AssertionError("per-row insert must be gone (P0-④)")

        monkeypatch.setattr(db, "insert_one", boom_insert_one)

        await db.seed_clarification_history(
            SID,
            [
                {"question": "q1", "answer": "a1"},
                {"question": "q2", "answer": "a2"},
                {"question": "q3", "answer": "a3"},
            ],
        )
        assert len(captured) == 1  # ONE round-trip, not three
        table, rows = captured[0]
        assert table == "ai_clarifications"
        assert len(rows) == 3
        assert rows[0]["question"] == "q1"
        assert rows[0]["user_response"] == "a1"
        assert rows[0]["status"] == "COMPLETED"
        assert rows[0]["execution_session_id"] == str(SID)
        assert all(
            r["required_information"] == [] and r["options"] == [] for r in rows
        )

    @pytest.mark.asyncio
    async def test_empty_history_writes_nothing(self, monkeypatch):
        calls = {"n": 0}

        async def fake_insert_many(*a, **k):
            calls["n"] += 1
            return []

        monkeypatch.setattr(db, "insert_many", fake_insert_many)
        await db.seed_clarification_history(SID, [])
        assert calls["n"] == 0


class TestPreambleGather:
    @pytest.mark.asyncio
    async def test_four_side_effects_run_concurrently(self, monkeypatch):
        calls = {"close": 0, "seed": 0, "prefs": 0, "capture": 0}

        async def close(*a, **k):
            await asyncio.sleep(0.05)
            calls["close"] += 1

        async def seed(*a, **k):
            await asyncio.sleep(0.05)
            calls["seed"] += 1

        async def load_prefs(*a, **k):
            await asyncio.sleep(0.05)
            calls["prefs"] += 1
            return {"payment_terms": "CREDIT"}

        async def capture(*a, **k):
            await asyncio.sleep(0.05)
            calls["capture"] += 1

        monkeypatch.setattr(agent_mod, "_close_superseded_sessions", close)
        monkeypatch.setattr(agent_mod, "seed_clarification_history", seed)
        monkeypatch.setattr(agent_mod, "_load_org_preferences", load_prefs)
        monkeypatch.setattr(
            "app.services.preference_service.record_answer_preference", capture
        )

        start = time.monotonic()
        org_prefs = await agent_mod._preamble_side_effects(
            session_id=SID,
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            prior_qa=[{"question": "q", "answer": "a"}],
        )
        elapsed = time.monotonic() - start

        assert calls == {"close": 1, "seed": 1, "prefs": 1, "capture": 1}
        assert org_prefs == {"payment_terms": "CREDIT"}
        # Serial would be >= 0.20s (4 × 50ms); concurrent ~0.05-0.10s.
        assert elapsed < 0.15, f"preamble side-effects serialized ({elapsed:.3f}s)"

    @pytest.mark.asyncio
    async def test_no_prior_qa_skips_preference_capture(self, monkeypatch):
        async def noop(*a, **k):
            return {}

        async def load_prefs(*a, **k):
            return {"k": "v"}

        monkeypatch.setattr(agent_mod, "_close_superseded_sessions", noop)
        monkeypatch.setattr(agent_mod, "seed_clarification_history", noop)
        monkeypatch.setattr(agent_mod, "_load_org_preferences", load_prefs)

        async def boom(*a, **k):
            raise AssertionError("preference capture must not run without prior_qa")

        monkeypatch.setattr(
            "app.services.preference_service.record_answer_preference", boom
        )
        out = await agent_mod._preamble_side_effects(
            session_id=SID,
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            prior_qa=[],
        )
        assert out == {"k": "v"}

    def test_execute_no_longer_loads_org_prefs_sequentially(self):
        src = AGENT_PY.read_text(encoding="utf-8")
        # The old phase-2 sequential load is gone — org_prefs now comes
        # from the preamble gather (exactly one assignment site: helper).
        assert (
            "org_prefs = await _load_org_preferences(organization_id)" not in src
        )
        assert src.count("org_prefs = await _preamble_side_effects(") == 1
