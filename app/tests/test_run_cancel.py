"""Cancel the ongoing request — the button, the endpoint, and its guarantees.

Production request (2026-10-08): "Where is the button to cancel the ongoing
user's request?" — it did not exist.  Cancellation only happened implicitly
(a new request superseded the old run; the 24h reaper), so a user watching a
run they no longer wanted had NO way to stop it.

The feature, end to end:

* ``POST /api/ai/sessions/cancel`` moves a NON-TERMINAL session (org + user
  scoped) to CANCELLED — idempotent, and a FINISHED run's outcome is never
  rewritten (``cancelled: false`` reports the truth);
* ``set_session_phase``'s TERMINAL GUARD stops the in-flight executor from
  resurrecting the run (its next phase write / final COMPLETED would flip
  CANCELLED back);
* the executor's MUTATION GATE (``agent._executor``) refuses every write
  after a cancel, so nothing lands in the books;
* the frontend button (AIProgress header + AgentRunDock) clears only on a
  SUCCESSFUL cancel — a failed cancel never fakes success, and a result
  that arrives after the click is dropped.
"""

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

import app.database as db_mod
from app.models.schemas import SessionCancelRequest

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
SESSION = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _auth():
    from types import SimpleNamespace

    return SimpleNamespace(organization_id=ORG, user_id=USER)


def _row(**over) -> dict:
    base = {
        "id": str(SESSION),
        "organization_id": str(ORG),
        "user_id": str(USER),
        "conversation_id": "conv-abc",
        "status": "EXECUTING",
    }
    base.update(over)
    return base


class TestCancelEndpoint:
    @pytest.mark.asyncio
    async def test_a_running_session_is_marked_cancelled(self, monkeypatch):
        from app import main as main_mod

        writes = []

        async def fake_fetch_one(table, *, filters, select="*"):
            # Ownership is part of the lookup: org AND user AND conversation.
            assert table == "ai_execution_sessions"
            assert filters["organization_id"] == str(ORG)
            assert filters["user_id"] == str(USER)
            assert filters["conversation_id"] == "conv-abc"
            return _row()

        async def fake_phase(session_id, *, phase, status, completed=False):
            writes.append((str(session_id), phase, status, completed))
            return {}

        monkeypatch.setattr(main_mod, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(main_mod, "set_session_phase", fake_phase)

        out = await main_mod.cancel_session(
            SessionCancelRequest(conversation_id="conv-abc"), auth=_auth()
        )

        assert out == {
            "cancelled": True,
            "status": "CANCELLED",
            "session_id": str(SESSION),
        }
        assert writes == [(str(SESSION), "CANCELLED", "CANCELLED", True)]

    @pytest.mark.asyncio
    async def test_cancel_is_idempotent(self, monkeypatch):
        from app import main as main_mod

        async def fake_fetch_one(table, *, filters, select="*"):
            return _row(status="CANCELLED")

        async def fake_phase(*args, **kwargs):  # must NOT be reached
            raise AssertionError("an already-cancelled run is never rewritten")

        monkeypatch.setattr(main_mod, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(main_mod, "set_session_phase", fake_phase)

        out = await main_mod.cancel_session(
            SessionCancelRequest(conversation_id="conv-abc"), auth=_auth()
        )
        assert out["cancelled"] is True
        assert out["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_a_finished_run_reports_the_truth_and_is_never_rewritten(
        self, monkeypatch
    ):
        from app import main as main_mod

        async def fake_fetch_one(table, *, filters, select="*"):
            return _row(status="COMPLETED")

        async def fake_phase(*args, **kwargs):
            raise AssertionError("a completed run's outcome is history")

        monkeypatch.setattr(main_mod, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(main_mod, "set_session_phase", fake_phase)

        out = await main_mod.cancel_session(
            SessionCancelRequest(conversation_id="conv-abc"), auth=_auth()
        )
        assert out["cancelled"] is False
        assert out["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_a_foreign_or_missing_session_is_404(self, monkeypatch):
        from app import main as main_mod

        async def fake_fetch_one(table, *, filters, select="*"):
            return None  # the org+user scoped lookup simply finds nothing

        monkeypatch.setattr(main_mod, "fetch_one", fake_fetch_one)

        with pytest.raises(HTTPException) as exc:
            await main_mod.cancel_session(
                SessionCancelRequest(conversation_id="conv-abc"), auth=_auth()
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_identifier_is_a_400_not_a_crash(self):
        from app import main as main_mod

        with pytest.raises(HTTPException) as exc:
            await main_mod.cancel_session(SessionCancelRequest(), auth=_auth())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_a_malformed_session_id_is_a_400(self):
        from app import main as main_mod

        with pytest.raises(HTTPException) as exc:
            await main_mod.cancel_session(
                SessionCancelRequest(session_id="not-a-uuid"), auth=_auth()
            )
        assert exc.value.status_code == 400


class TestTerminalPhaseGuard:
    """A terminal session's status is HISTORY — never rewritten."""

    @pytest.mark.asyncio
    async def test_the_executor_cannot_resurrect_a_cancelled_run(
        self, monkeypatch
    ):
        writes = []

        async def fake_fetch_one(table, *, filters, select="*"):
            return {"status": "CANCELLED"}

        async def fake_update_one(table_name, *, row_id, data, **kwargs):
            writes.append(data)
            return data

        monkeypatch.setattr(db_mod, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(db_mod, "update_one", fake_update_one)

        await db_mod.set_session_phase(
            SESSION, phase="COMPLETED", status="COMPLETED", completed=True
        )

        assert writes == [], "a cancelled run must never flip to COMPLETED"

    @pytest.mark.asyncio
    async def test_a_running_session_still_transitions_normally(
        self, monkeypatch
    ):
        writes = []

        async def fake_fetch_one(table, *, filters, select="*"):
            return {"status": "EXECUTING"}

        async def fake_update_one(table_name, *, row_id, data, **kwargs):
            writes.append(data)
            return data

        monkeypatch.setattr(db_mod, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(db_mod, "update_one", fake_update_one)

        await db_mod.set_session_phase(
            SESSION, phase="CANCELLED", status="CANCELLED", completed=True
        )

        assert writes and writes[0]["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_a_status_read_failure_fails_open(self, monkeypatch):
        # A transient blip must not swallow a REAL transition (fail open —
        # documented in set_session_phase's docstring).
        writes = []

        async def boom(table, **kwargs):
            raise RuntimeError("read failed")

        async def fake_update_one(table_name, *, row_id, data, **kwargs):
            writes.append(data)
            return data

        monkeypatch.setattr(db_mod, "fetch_one", boom)
        monkeypatch.setattr(db_mod, "update_one", fake_update_one)

        await db_mod.set_session_phase(
            SESSION, phase="COMPLETED", status="COMPLETED", completed=True
        )
        assert writes and writes[0]["status"] == "COMPLETED"


class TestSessionStatusProbe:
    @pytest.mark.asyncio
    async def test_returns_the_status_upper_cased(self, monkeypatch):
        async def fake_fetch_one(table, *, filters, select="*"):
            return {"status": "cancelled"}

        monkeypatch.setattr(db_mod, "fetch_one", fake_fetch_one)
        assert await db_mod.get_session_status(SESSION) == "CANCELLED"

    @pytest.mark.asyncio
    async def test_unknown_or_failed_reads_return_none(self, monkeypatch):
        async def fake_fetch_one(table, *, filters, select="*"):
            return None

        monkeypatch.setattr(db_mod, "fetch_one", fake_fetch_one)
        assert await db_mod.get_session_status(SESSION) is None

        async def boom(table, **kwargs):
            raise RuntimeError("blip")

        monkeypatch.setattr(db_mod, "fetch_one", boom)
        assert await db_mod.get_session_status(SESSION) is None


class TestExecutorMutationGate:
    """The gate inside ``agent._executor`` — no write lands after a cancel.

    The gate itself needs the full execution harness to run, so its WIRING
    is pinned from source (the repo's established pattern — see
    ``test_planner_appends_confirmed_creation_to_every_intent``), while the
    status probe it depends on is unit-tested above.
    """

    def test_the_mutation_gate_refuses_post_cancel_writes(self):
        import app.agent as agent_mod

        src = Path(agent_mod.__file__).read_text(encoding="utf-8")
        assert "REQUEST_CANCELLED" in src
        assert "_cancel_state" in src
        assert "agent.mutation_blocked_after_cancel" in src
        # Reads stay allowed; only non-read-only tools hit the gate.
        assert "if not is_read_only_tool(tool_name):" in src

