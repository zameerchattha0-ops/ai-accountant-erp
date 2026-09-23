"""P2-⑪/⑬/⑭/⑮ (forensic latency report P2): persisted instrumentation,
bounded flush, SSE poll, warm hook.

Pinned invariants:
* phase markers mirror into SQL-friendly scalars (``_record_phase_timing``)
  and every execution result carries ``result_payload.timings`` (unset
  ContextVar → untouched payload);
* every step row gets ``elapsed_ms`` stamped SYNCHRONOUSLY in _log_step,
  durable rows included;
* flush policy: 0.25s ONLY for AWAITING_* (audit-loss review — durable
  rows are awaited inline and can never be lost); terminal/unknown keep
  the FULL drain; a capped flush DETACHES leftovers with a reaper;
* SSE poll is 250ms (source-pinned); /api/ai/warm imports the heavy stack;
* CLIENT_TTFB persists org-scoped and never raises at the client edge.
"""

import asyncio
import time
import uuid
from pathlib import Path

import pytest

import app.agent as agent_mod
import app.database as db

SID = uuid.UUID("77777777-7777-7777-7777-777777777777")
MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"


class TestPhaseTimingsMirror:
    def test_record_phase_timing_scalars_and_bounds(self):
        store: dict = {}
        t0 = time.monotonic() - 1.5
        agent_mod._record_phase_timing(
            store, t0, "planner.done",
            {"intent": "record_receipt", "rounds": 2, "ok": True,
             "missing": None, "big": "x" * 500},
        )
        entry = store["planner.done"]
        assert entry["elapsed_ms"] >= 1400
        assert entry["intent"] == "record_receipt"
        assert entry["rounds"] == 2 and entry["ok"] is True
        assert entry["missing"] is None
        assert len(entry["big"]) == 120  # bounded strings only

    @pytest.mark.asyncio
    async def test_result_row_carries_timings(self, monkeypatch):
        captured: dict = {}

        async def fake_insert(table, *, data):
            captured.update(data)
            return data

        monkeypatch.setattr(db, "insert_one", fake_insert)
        token = db.REQUEST_TIMINGS.set({"context.built": {"elapsed_ms": 1234}})
        try:
            await db.create_execution_result(
                session_id=SID, result_data={"status": "ok"}
            )
        finally:
            db.REQUEST_TIMINGS.reset(token)
        assert captured["result_payload"]["timings"] == {
            "context.built": {"elapsed_ms": 1234}
        }
        assert captured["result_payload"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_result_row_without_timings_unchanged(self, monkeypatch):
        captured: dict = {}

        async def fake_insert(table, *, data):
            captured.update(data)
            return data

        monkeypatch.setattr(db, "insert_one", fake_insert)
        token = db.REQUEST_TIMINGS.set(None)
        try:
            await db.create_execution_result(
                session_id=SID, result_data={"a": 1}
            )
        finally:
            db.REQUEST_TIMINGS.reset(token)
        assert captured["result_payload"] == {"a": 1}
        assert "timings" not in captured["result_payload"]


class TestStepElapsed:
    @pytest.mark.asyncio
    async def test_log_step_stamps_elapsed_ms(self, monkeypatch):
        captured: list = []

        async def fake_create(*, session_id, step_type, step_data,
                              status="COMPLETED"):
            captured.append((step_type, step_data))
            return {}

        monkeypatch.setattr(agent_mod, "create_execution_step", fake_create)
        agent_mod._STEP_START[str(SID)] = time.monotonic() - 2.0
        try:
            await agent_mod._log_step(SID, "RECEIVED", {"message": "hi"})
            await agent_mod.flush_step_logs()  # spawned queue → drain
        finally:
            agent_mod._STEP_START.pop(str(SID), None)
        step_type, data = captured[0]
        assert step_type == "RECEIVED"
        assert data["message"] == "hi"
        assert data["elapsed_ms"] >= 1900  # int, ms since session start

    @pytest.mark.asyncio
    async def test_durable_close_marker_recorded(self, monkeypatch):
        async def fake_create(*, session_id, step_type, step_data,
                              status="COMPLETED"):
            return {}

        monkeypatch.setattr(agent_mod, "create_execution_step", fake_create)
        agent_mod._STEP_START[str(SID)] = time.monotonic()
        try:
            # Durable type → awaited inline (never queued), marker recorded.
            await agent_mod._log_step(
                SID, "AWAITING_CLARIFICATION", {"question": "q"}
            )
            assert (
                agent_mod._CLOSE_MARKERS[str(SID)]
                == "AWAITING_CLARIFICATION"
            )
        finally:
            agent_mod._STEP_START.pop(str(SID), None)
            agent_mod._CLOSE_MARKERS.pop(str(SID), None)


class TestBoundedFlushPolicy:
    def test_policy_matrix(self):
        assert agent_mod._flush_cap_for("AWAITING_CLARIFICATION") == 0.25
        assert agent_mod._flush_cap_for("AWAITING_CONFIRMATION") == 0.25
        # Terminal + unknown → leave-as-is FULL drain (report ⑮ default).
        assert agent_mod._flush_cap_for("COMPLETED") is None
        assert agent_mod._flush_cap_for("FAILED") is None
        assert agent_mod._flush_cap_for(None) is None

    @pytest.mark.asyncio
    async def test_cap_detaches_slow_writes(self):
        slow = asyncio.get_running_loop().create_task(asyncio.sleep(0.5))
        agent_mod._pending_step_tasks.append(slow)
        start = time.monotonic()
        await agent_mod.flush_step_logs(cap_seconds=0.05)
        elapsed = time.monotonic() - start
        assert elapsed < 0.4  # bounded wait honoured
        assert not slow.done()
        # Detached with reaper — never 'Task exception was never retrieved'.
        assert slow not in agent_mod._pending_step_tasks
        slow.cancel()
        await asyncio.gather(slow, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_full_drain_waits_for_writes(self):
        done = {"n": 0}

        async def _quick():
            done["n"] += 1

        for _ in range(3):
            agent_mod._pending_step_tasks.append(
                asyncio.get_running_loop().create_task(_quick())
            )
        await agent_mod.flush_step_logs()  # cap None → full drain
        assert done["n"] == 3
        assert not agent_mod._pending_step_tasks


class TestClientTtfb:
    @pytest.mark.asyncio
    async def test_org_scoped_and_persists(self, monkeypatch):
        async def fake_fetch_one(table, *, filters, **kw):
            return {"id": filters.get("id")}

        captured: list = []

        async def fake_create(*, session_id, step_type, step_data,
                              status="COMPLETED"):
            captured.append((step_type, step_data))
            return {}

        monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(agent_mod, "create_execution_step", fake_create)
        ok = await agent_mod._attach_client_ttfb(
            session_id=SID,
            ttfb_ms=1234.7,
            transport="sse",
            organization_id=uuid.uuid4(),
        )
        assert ok is True
        assert captured == [
            ("CLIENT_TTFB", {"ttfb_ms": 1234, "transport": "sse"})
        ]

    @pytest.mark.asyncio
    async def test_foreign_org_denied_and_never_raises(self, monkeypatch):
        async def no_session(table, *, filters, **kw):
            return None

        async def boom_create(**kw):
            raise AssertionError("must not write for a foreign org")

        monkeypatch.setattr(agent_mod, "fetch_one", no_session)
        monkeypatch.setattr(agent_mod, "create_execution_step", boom_create)
        ok = await agent_mod._attach_client_ttfb(
            session_id=SID,
            ttfb_ms=10,
            transport="sse",
            organization_id=uuid.uuid4(),
        )
        assert ok is False


class TestSsePollAndWarmHook:
    def test_sse_poll_is_250ms(self):
        src = MAIN_PY.read_text(encoding="utf-8")
        assert "asyncio.sleep(0.25)" in src
        assert "asyncio.sleep(0.15)" not in src
        assert "execution_id" in src  # TTFB attach point on step events

    @pytest.mark.asyncio
    async def test_warm_endpoint_imports_heavy_stack(self):
        main = pytest.importorskip("app.main")
        result = await main.ai_warm()
        assert result["status"] == "ok"
        assert "app.agent" in result["warmed"]
        assert result["elapsed_ms"] >= 0

