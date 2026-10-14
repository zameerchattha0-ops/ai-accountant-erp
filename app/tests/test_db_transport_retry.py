"""A dropped Supabase HTTP/2 connection is a classified, recoverable event.

Production 2026-10-14 (session 7fdd9860): postgrest 2.x builds its pooled
client with ``http2=True``, so a warm Vercel instance reuses ONE multiplexed
connection.  Supabase's gateway killed stream 17 mid-request
(``httpx.RemoteProtocolError: ConnectionTerminated``) and the raw exception
escaped to ``agent.execute``'s catch-all as the uncontrolled "Something went
wrong" card.  Two layers now absorb it:

* ``app.database._execute`` replays a READ once on a transport fault
  (httpcore discards the dead connection; the retry rides a fresh one) and
  NEVER retries a WRITE (it may have reached Postgres before the drop);
* the agent catch-all renders the honest "connection interrupted, nothing
  recorded, resend" story and marks the FAILED step ``controlled``.
"""

import uuid

import httpx
import pytest

import app.agent as agent_mod
from app import database as db
from app.agent import execute
from app.models.schemas import ExecutionStatus

#: The EXACT error production recorded (session 7fdd9860, step 12) —
#: ``<ConnectionTerminated error_code:1, last_stream_id:17, additional_data:None>``.
_PROD_ERROR = httpx.RemoteProtocolError(
    "<ConnectionTerminated error_code:1, last_stream_id:17, additional_data:None>"
)


class _ScriptedQuery:
    """A query builder stand-in whose execute() plays a script of outcomes."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def execute(self):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _ScriptedSelect(_ScriptedQuery):
    """Marker subclass the retry recognises as a READ (see _SELECT_BUILDERS)."""


@pytest.fixture
def _select_builders(monkeypatch):
    monkeypatch.setattr(db, "_SELECT_BUILDERS", (_ScriptedSelect,))


class TestReadsAreReplayedOnce:
    @pytest.mark.asyncio
    async def test_a_dropped_connection_is_retried_and_succeeds(self, _select_builders):
        expected = object()
        q = _ScriptedSelect(_PROD_ERROR, expected)
        result = await db._execute(q)
        assert result is expected
        assert q.calls == 2

    @pytest.mark.asyncio
    async def test_a_second_strike_still_surfaces(self, _select_builders):
        q = _ScriptedSelect(_PROD_ERROR, _PROD_ERROR)
        with pytest.raises(httpx.RemoteProtocolError):
            await db._execute(q)
        assert q.calls == 2

    @pytest.mark.asyncio
    async def test_a_non_transport_error_is_never_retried(self, _select_builders):
        q = _ScriptedSelect(ValueError("bad request"), object())
        with pytest.raises(ValueError):
            await db._execute(q)
        assert q.calls == 1


class TestWritesAreNeverReplayed:
    @pytest.mark.asyncio
    async def test_a_dropped_write_surfaces_immediately(self, monkeypatch):
        # A WRITE may have reached Postgres before the drop — replaying it
        # could duplicate a row, so it must NOT be retried even though the
        # error is transient.
        monkeypatch.setattr(db, "_SELECT_BUILDERS", (_ScriptedSelect,))
        q = _ScriptedQuery(_PROD_ERROR, object())
        with pytest.raises(httpx.RemoteProtocolError):
            await db._execute(q)
        assert q.calls == 1


class TestTheProductionErrorIsRecognised:
    def test_it_is_a_transport_error(self):
        # The classifier keys off httpx.TransportError; prove the exact
        # recorded instance is one (RemoteProtocolError -> ProtocolError ->
        # TransportError), so neither layer can silently miss this shape.
        assert isinstance(_PROD_ERROR, httpx.TransportError)
        assert db._is_retryable_transport(_PROD_ERROR)

    def test_an_application_error_is_not(self):
        assert not db._is_retryable_transport(ValueError("boom"))
        assert not db._is_retryable_transport(RuntimeError("context exploded"))


def _am(return_value=None):
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=return_value)


class TestTheCatchAllTellsTheTruth:
    """A transport error escaping to execute()'s catch-all is CONTROLLED."""

    def _harness(self, monkeypatch, *, boom):
        session = {
            "id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "user_request": (
                "create invoice for zeta pvt ltd for selling them 2 laptops"
            ),
            "conversation_id": "conv-transport",
            "status": "RUNNING",
            "current_phase": "RUNNING",
        }
        recorded = {"steps": [], "results": []}

        async def fake_log_step(session_id, step_type, data):
            recorded["steps"].append((session_id, step_type, data))

        async def fake_create_result(**kw):
            recorded["results"].append(kw)
            return {"id": "res-1"}

        async def fake_seed(*a, **k):
            raise boom

        monkeypatch.setattr(
            agent_mod, "create_execution_session", _am(return_value=session)
        )
        monkeypatch.setattr(
            agent_mod, "_close_superseded_sessions", _am(return_value=0)
        )
        monkeypatch.setattr(agent_mod, "seed_clarification_history", fake_seed)
        monkeypatch.setattr(agent_mod, "_load_org_preferences", _am(return_value={}))
        monkeypatch.setattr(agent_mod, "_update_status", _am())
        monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)
        monkeypatch.setattr(agent_mod, "create_execution_result", fake_create_result)
        return session, recorded

    @pytest.mark.asyncio
    async def test_a_dropped_connection_is_controlled_and_honest(self, monkeypatch):
        session, recorded = self._harness(monkeypatch, boom=_PROD_ERROR)
        response = await execute(
            user_message=session["user_request"],
            user_id=uuid.UUID(session["user_id"]),
            organization_id=uuid.UUID(session["organization_id"]),
        )
        assert response.status == ExecutionStatus.FAILED
        # Honest infrastructure wording — never the generic unexpected-error card.
        assert "interrupted" in response.summary.lower()
        assert "nothing was recorded" in response.summary.lower()
        assert "unexpected error" not in response.summary.lower()
        failed = [d for _, t, d in recorded["steps"] if t == "FAILED"]
        assert failed, "the FAILED step must still be durably recorded"
        assert failed[-1]["stage"] == "agent_execute"
        assert failed[-1]["error_type"] == "RemoteProtocolError"
        assert failed[-1]["controlled"] is True
        assert failed[-1]["category"] == "INFRASTRUCTURE_ERROR"

    @pytest.mark.asyncio
    async def test_a_genuine_bug_keeps_the_generic_card(self, monkeypatch):
        session, recorded = self._harness(
            monkeypatch, boom=RuntimeError("context exploded")
        )
        response = await execute(
            user_message=session["user_request"],
            user_id=uuid.UUID(session["user_id"]),
            organization_id=uuid.UUID(session["organization_id"]),
        )
        assert response.status == ExecutionStatus.FAILED
        assert response.summary == "An unexpected error occurred. Please try again."
        failed = [d for _, t, d in recorded["steps"] if t == "FAILED"]
        assert failed[-1]["controlled"] is False
        assert failed[-1]["category"] == "UNKNOWN_ERROR"

