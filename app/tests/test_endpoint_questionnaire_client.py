"""API-boundary pins: the endpoints must RESOLVE ``get_client`` (c1f3faf).

Production incident (deployment dpl_TDRkupqAAnsq22GrSnzR3YqwtYpT, session
ac299810-c36b-4d57-bdb2-da626e6913a8): every POST /api/ai/clarify returned a
bare ``500 Internal Server Error`` because

    questionnaire_client=get_client(),

was evaluated without a local/imported ``get_client`` in scope.  Python
raises ``NameError`` while building the keyword arguments — BEFORE
``resume_with_clarification`` runs — so the answer never reached the
clarification row (``user_response`` stayed NULL, session stuck
WAITING_FOR_USER) and no agent step was recorded.

The hermetic agent suite never imports ``app.main``'s endpoint bodies, so
only a test that calls the ENDPOINT function itself can catch a missing
name.  These pins do exactly that with the agent/orchestrator stubbed.
"""

import uuid

import pytest

from app.auth import AuthContext
from app.models.schemas import (
    AgentResponse,
    ClarificationAnswer,
    ExecutionStatus,
    UserRequest,
)


class _SentinelClient:
    """Stands in for AIOrchestrator; identity is what the pins assert on."""


@pytest.mark.asyncio
async def test_ai_clarify_resolves_get_client_and_injects_it(monkeypatch):
    """ai_clarify must not raise NameError and must pass the client through."""
    import app.agent as agent_mod
    import app.ai_orchestrator as orch
    import app.main as main_mod

    captured: dict = {}

    async def fake_resume(**kwargs):
        captured.update(kwargs)
        return AgentResponse(
            status=ExecutionStatus.AWAITING_CLARIFICATION,
            execution_id=kwargs["session_id"],
        )

    sentinel = _SentinelClient()
    monkeypatch.setattr(agent_mod, "resume_with_clarification", fake_resume)
    monkeypatch.setattr(orch, "get_client", lambda: sentinel)

    session_id = uuid.uuid4()
    answer = ClarificationAnswer(
        session_id=session_id, answer="1) FIXED_ASSET\n2) CASH"
    )
    auth = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4())

    # Raises NameError (the incident) when the import is missing.
    resp = await main_mod.ai_clarify(answer, auth=auth)

    assert resp.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert resp.execution_id == session_id
    assert captured["questionnaire_client"] is sentinel
    assert captured["session_id"] == session_id
    assert captured["user_answer"] == "1) FIXED_ASSET\n2) CASH"


@pytest.mark.asyncio
async def test_ai_execute_resolves_get_client_and_injects_it(monkeypatch):
    """The plain POST /api/ai/execute had the identical missing-name bug."""
    import app.agent as agent_mod
    import app.ai_orchestrator as orch
    import app.main as main_mod

    captured: dict = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return AgentResponse(status=ExecutionStatus.AWAITING_CLARIFICATION)

    sentinel = _SentinelClient()
    monkeypatch.setattr(agent_mod, "execute", fake_execute)
    monkeypatch.setattr(orch, "get_client", lambda: sentinel)

    request = UserRequest(message="I Purchased A Car for 1360000")
    auth = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4())

    resp = await main_mod.ai_execute(request, auth=auth)

    assert resp.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert captured["questionnaire_client"] is sentinel
    assert captured["user_message"] == "I Purchased A Car for 1360000"


@pytest.mark.asyncio
async def test_ai_execute_stream_injects_the_client_on_the_primary_path(monkeypatch):
    """The SSE endpoint is the PRIMARY prod path — it must inject too."""
    import app.ai_orchestrator as orch
    import app.main as main_mod

    captured: dict = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return AgentResponse(status=ExecutionStatus.AWAITING_CLARIFICATION)

    sentinel = _SentinelClient()
    monkeypatch.setattr(main_mod, "fetch_one", _async_none)
    monkeypatch.setattr(main_mod, "fetch_many", _async_empty_list)
    # The generator imports execute/get_client lazily from their modules.
    import app.agent as agent_mod

    monkeypatch.setattr(agent_mod, "execute", fake_execute)
    monkeypatch.setattr(orch, "get_client", lambda: sentinel)

    request = UserRequest(message="I Purchased A Car for 1360000")
    auth = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4())

    stream = await main_mod.ai_execute_stream(request, auth=auth)
    chunks = []
    async for chunk in stream.body_iterator:
        chunks.append(chunk)

    payload = "".join(chunks)
    assert "event: final" in payload
    assert captured["questionnaire_client"] is sentinel


async def _async_none(*args, **kwargs):
    return None


async def _async_empty_list(*args, **kwargs):
    return []
