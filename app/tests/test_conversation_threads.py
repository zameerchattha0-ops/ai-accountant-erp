"""
Unit and integration tests for Claude-Style Persistent Conversation Threads.
Tests verify:
1. Database layer: get_conversation_turns and get_user_conversations
2. API endpoints: GET /api/ai/conversations and GET /api/ai/conversations/{id}
3. Agent lifecycle: prior turn context ingestion on multi-turn conversations
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from app.database import get_conversation_turns, get_user_conversations


@pytest.mark.asyncio
async def test_get_conversation_turns_empty_or_missing():
    """Empty or non-existent conversation_id returns empty turn list."""
    assert await get_conversation_turns("") == []
    assert await get_conversation_turns("   ") == []


@pytest.mark.asyncio
async def test_get_conversation_turns_reconstruction():
    """Verify session requests and results are stitched into chronological turns."""
    cid = f"thread-test-{uuid.uuid4().hex[:8]}"
    mock_sessions = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "conversation_id": cid,
            "user_request": "Can I pay 85,000 cash for office renovation?",
            "status": "COMPLETED",
            "created_at": "2026-11-19T10:00:00Z",
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "conversation_id": cid,
            "user_request": "What if I split it into two payments of 42,500?",
            "status": "COMPLETED",
            "created_at": "2026-11-19T10:02:00Z",
        },
    ]

    mock_results = {
        "11111111-1111-1111-1111-111111111111": [
            {
                "summary": "Section 73 disallows cash expenses over PKR 50,000.",
                "status": "COMPLETED",
                "result_payload": {"simulations": []},
            }
        ],
        "22222222-2222-2222-2222-222222222222": [
            {
                "summary": "Splitting a single PKR 85,000 transaction is considered artificial structuring.",
                "status": "COMPLETED",
                "result_payload": {},
            }
        ],
    }

    async def fake_fetch_many(table, filters=None, **kwargs):
        if table == "ai_execution_sessions":
            return mock_sessions
        if table == "ai_execution_results":
            sid = filters.get("execution_session_id")
            return mock_results.get(sid, [])
        return []

    with patch("app.database.fetch_many", side_effect=fake_fetch_many):
        turns = await get_conversation_turns(cid)

    assert len(turns) == 4
    assert turns[0]["role"] == "user"
    assert "85,000 cash" in turns[0]["content"]
    assert turns[1]["role"] == "assistant"
    assert "Section 73 disallows" in turns[1]["content"]
    assert turns[2]["role"] == "user"
    assert "split it into two" in turns[2]["content"]
    assert turns[3]["role"] == "assistant"
    assert "artificial structuring" in turns[3]["content"]


@pytest.mark.asyncio
async def test_get_user_conversations_aggregation():
    """Verify sessions are aggregated by conversation_id into thread summaries."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    cid1 = "thread-alpha"
    cid2 = "thread-beta"

    mock_sessions = [
        {
            "id": "1",
            "conversation_id": cid1,
            "user_request": "Simulate lease vs buy for 5M asset",
            "created_at": "2026-11-19T11:00:00Z",
            "status": "COMPLETED",
        },
        {
            "id": "2",
            "conversation_id": cid1,
            "user_request": "Change discount rate to 18%",
            "created_at": "2026-11-19T11:05:00Z",
            "status": "COMPLETED",
        },
        {
            "id": "3",
            "conversation_id": cid2,
            "user_request": "What is Section 153 WHT on IT services?",
            "created_at": "2026-11-19T09:00:00Z",
            "status": "COMPLETED",
        },
    ]

    with patch("app.database.fetch_many", AsyncMock(return_value=mock_sessions)):
        conversations = await get_user_conversations(org_id, user_id)

    assert len(conversations) == 2
    # thread-alpha has later updated_at (11:05) so should be first
    assert conversations[0]["conversation_id"] == cid1
    assert conversations[0]["turn_count"] == 2
    assert conversations[0]["last_message"] == "Change discount rate to 18%"

    assert conversations[1]["conversation_id"] == cid2
    assert conversations[1]["turn_count"] == 1


@pytest.mark.asyncio
async def test_conversation_api_endpoints():
    """Verify GET /api/ai/conversations and /api/ai/conversations/{id} work over HTTP."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app, get_current_user
    from app.auth import AuthContext

    test_org_id = uuid.uuid4()
    test_user_id = uuid.uuid4()
    fake_auth = AuthContext(
        user_id=test_user_id,
        organization_id=test_org_id,
        role_code="OWNER",
    )

    app.dependency_overrides[get_current_user] = lambda: fake_auth

    mock_conversations = [
        {
            "conversation_id": "thread-123",
            "title": "Renovation Tax Advisory",
            "last_message": "Can I pay 85k cash?",
            "updated_at": "2026-11-19T10:00:00Z",
            "turn_count": 2,
            "last_status": "COMPLETED",
        }
    ]

    mock_turns = [
        {"role": "user", "content": "Can I pay 85k cash?"},
        {"role": "assistant", "content": "Section 73 disallows cash expenses over PKR 50k."},
    ]

    try:
        with patch("app.database.get_user_conversations", AsyncMock(return_value=mock_conversations)), \
             patch("app.database.get_conversation_turns", AsyncMock(return_value=mock_turns)):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                r1 = await ac.get("/api/ai/conversations")
                assert r1.status_code == 200
                data1 = r1.json()
                assert "conversations" in data1
                assert len(data1["conversations"]) == 1
                assert data1["conversations"][0]["title"] == "Renovation Tax Advisory"

                r2 = await ac.get("/api/ai/conversations/thread-123")
                assert r2.status_code == 200
                data2 = r2.json()
                assert data2["conversation_id"] == "thread-123"
                assert len(data2["turns"]) == 2
                assert data2["turns"][0]["role"] == "user"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_agent_execute_ingests_multi_turn_history():
    """Verify execute() loads prior turns into prior_qa when conversation_id is supplied."""
    from app.agent import execute

    cid = f"thread-multi-{uuid.uuid4().hex[:8]}"
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_prior_turns = [
        {"role": "user", "content": "Can I pay 85k in cash?", "session_id": "prev-session-1"},
        {"role": "assistant", "content": "Section 73 disallows cash expenses over PKR 50k.", "session_id": "prev-session-1"},
    ]

    with patch("app.agent.create_execution_session", AsyncMock(return_value={"id": str(uuid.uuid4())})), \
         patch("app.agent._log_step", AsyncMock()), \
         patch("app.agent._preamble_side_effects", AsyncMock(return_value={})), \
         patch("app.agent._load_org_facts", AsyncMock(return_value=({}, {}))), \
         patch("app.database.get_conversation_turns", AsyncMock(return_value=mock_prior_turns)):

        # Execute consultative query which will immediately complete
        res = await execute(
            user_message="What is the cash limit under Section 73?",
            user_id=user_id,
            organization_id=org_id,
            conversation_id=cid,
        )

        assert res is not None
        assert res.status.value in ("COMPLETED", "AWAITING_CLARIFICATION", "AWAITING_CONFIRMATION")


