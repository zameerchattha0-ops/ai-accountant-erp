import uuid
import pytest
from unittest.mock import AsyncMock, patch
from app.models.schemas import ExecutionStatus, AgentResponse
from app.agent import execute


@pytest.mark.asyncio
async def test_analytics_execution_sets_session_completed_and_saves_result():
    """Verify that an analytics inquiry marks the session COMPLETED in the database

    and logs COMPLETED step, preventing the frontend from getting stuck in PLANNING reattach loop.
    """
    dummy_session_id = uuid.uuid4()
    dummy_org_id = uuid.uuid4()
    dummy_user_id = uuid.uuid4()

    mock_answer = {
        "answer_type": "journal_entries",
        "synth": "The two most recent journal entries are JV-000078 and JV-000076.",
        "results": [{"journalnumber": "JV-000078"}, {"journalnumber": "JV-000076"}],
    }
    mock_audit = {
        "stage": "analytics",
        "llm": "mock",
    }

    with patch("app.agent.create_execution_session", new_callable=AsyncMock) as mock_create_sess, \
         patch("app.analytics_agent.route_message", new_callable=AsyncMock) as mock_route, \
         patch("app.analytics_agent.answer_analytics_question", new_callable=AsyncMock) as mock_analytics_ans, \
         patch("app.agent._update_status", new_callable=AsyncMock) as mock_update_status, \
         patch("app.agent._log_step", new_callable=AsyncMock) as mock_log_step, \
         patch("app.agent.create_execution_result", new_callable=AsyncMock) as mock_create_res:

        mock_create_sess.return_value = {"id": str(dummy_session_id)}
        mock_route.return_value = ("analytics", {"source": "llm_router", "route": "analytics"})
        mock_analytics_ans.return_value = {"answer": mock_answer, "audit": mock_audit}

        resp = await execute(
            user_message="last 2 entries?",
            user_id=dummy_user_id,
            organization_id=dummy_org_id,
        )

        assert resp.status == ExecutionStatus.COMPLETED
        # Must update session status to COMPLETED
        mock_update_status.assert_any_call(dummy_session_id, ExecutionStatus.COMPLETED)
        # Must log COMPLETED step
        mock_log_step.assert_any_call(
            dummy_session_id,
            "COMPLETED",
            {"route": "analytics", "answer_type": "journal_entries"},
        )
        # Must persist to execution_results table so details page renders
        mock_create_res.assert_called_once()
        call_kwargs = mock_create_res.call_args.kwargs
        assert call_kwargs["session_id"] == dummy_session_id
        assert call_kwargs["status"] == "COMPLETED"
        assert call_kwargs["action_type"] == "journal_entries"


@pytest.mark.asyncio
async def test_analytics_failure_updates_session_failed_and_saves_result():
    """Verify that an analytics error marks the session FAILED in the database

    and logs FAILED step, so it never falls through to the recording pipeline or leaves a live run.
    """
    dummy_session_id = uuid.uuid4()
    dummy_org_id = uuid.uuid4()
    dummy_user_id = uuid.uuid4()

    mock_audit = {
        "stage": "analytics",
        "error": "database connection timeout",
    }

    with patch("app.agent.create_execution_session", new_callable=AsyncMock) as mock_create_sess, \
         patch("app.analytics_agent.route_message", new_callable=AsyncMock) as mock_route, \
         patch("app.analytics_agent.answer_analytics_question", new_callable=AsyncMock) as mock_analytics_ans, \
         patch("app.agent._update_status", new_callable=AsyncMock) as mock_update_status, \
         patch("app.agent._log_step", new_callable=AsyncMock) as mock_log_step, \
         patch("app.agent.create_execution_result", new_callable=AsyncMock) as mock_create_res:

        mock_create_sess.return_value = {"id": str(dummy_session_id)}
        mock_route.return_value = ("analytics", {"source": "llm_router", "route": "analytics"})
        mock_analytics_ans.return_value = {"answer": None, "audit": mock_audit}

        resp = await execute(
            user_message="show me trial balance",
            user_id=dummy_user_id,
            organization_id=dummy_org_id,
        )

        assert resp.status == ExecutionStatus.FAILED
        mock_update_status.assert_any_call(dummy_session_id, ExecutionStatus.FAILED)
        mock_log_step.assert_any_call(
            dummy_session_id,
            "FAILED",
            {"route": "analytics", "reason": "database connection timeout"},
        )
        mock_create_res.assert_called_once()
        call_kwargs = mock_create_res.call_args.kwargs
        assert call_kwargs["session_id"] == dummy_session_id
        assert call_kwargs["status"] == "FAILED"


@pytest.mark.asyncio
async def test_router_clarification_updates_session_awaiting_clarification():
    """Verify that router clarification sets AWAITING_CLARIFICATION phase in the session."""
    dummy_session_id = uuid.uuid4()
    dummy_org_id = uuid.uuid4()
    dummy_user_id = uuid.uuid4()

    with patch("app.agent.create_execution_session", new_callable=AsyncMock) as mock_create_sess, \
         patch("app.analytics_agent.route_message", new_callable=AsyncMock) as mock_route, \
         patch("app.agent.create_clarification", new_callable=AsyncMock) as mock_create_clar, \
         patch("app.agent._update_status", new_callable=AsyncMock) as mock_update_status, \
         patch("app.agent._log_step", new_callable=AsyncMock) as mock_log_step:

        mock_create_sess.return_value = {"id": str(dummy_session_id)}
        mock_route.return_value = (
            "clarify",
            {"source": "llm_router", "route": "clarify", "question": "Do you want to record an entry or view a report?"},
        )
        mock_create_clar.return_value = {"id": str(uuid.uuid4())}

        resp = await execute(
            user_message="check entries",
            user_id=dummy_user_id,
            organization_id=dummy_org_id,
        )

        assert resp.status == ExecutionStatus.AWAITING_CLARIFICATION
        mock_update_status.assert_any_call(dummy_session_id, ExecutionStatus.AWAITING_CLARIFICATION)
        mock_log_step.assert_any_call(
            dummy_session_id,
            "AWAITING_CLARIFICATION",
            {"question": "Do you want to record an entry or view a report?", "source": "router"},
        )
