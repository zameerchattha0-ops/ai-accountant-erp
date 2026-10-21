import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app, _clean_plain_text_reply, _FOUNDER_RL

def test_clean_plain_text_reply():
    dirty = "### Heading 3\nHello world!\n```python\nprint('bad')\n```\n<script>alert(1)</script><p>Paragraph</p>"
    cleaned = _clean_plain_text_reply(dirty)
    assert "###" not in cleaned
    assert "```" not in cleaned
    assert "<script>" not in cleaned
    assert "alert(1)" not in cleaned
    assert "<p>" not in cleaned
    assert "Hello world!" in cleaned
    assert "Paragraph" in cleaned

    # Length clamping
    huge = "word " * 500
    clamped = _clean_plain_text_reply(huge)
    assert len(clamped.split()) <= 251 # 250 words + "..."

@pytest.mark.asyncio
async def test_founder_chat_endpoints_and_rate_limiting(monkeypatch):
    from unittest.mock import AsyncMock

    mock_client = AsyncMock()
    mock_client.generate_text.return_value = "### Hi there!\nThis is Zameer's assistant."

    monkeypatch.setattr("app.ai_orchestrator.get_client", lambda: mock_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Reset IP bucket
        _FOUNDER_RL.clear()

        # Both endpoints work
        r1 = await ac.post("/api/public/founder-chat", json={"message": "Who is the founder?"})
        assert r1.status_code == 200
        assert "###" not in r1.json()["reply"]
        assert "Hi there!" in r1.json()["reply"]

        r2 = await ac.post("/api/founder-chat", json={"message": "What is AI Accountant?"})
        assert r2.status_code == 200

        # Rapid requests triggering rate limit (max 10)
        for _ in range(8):
            await ac.post("/api/founder-chat", json={"message": "Hello"})

        # 11th request should be rate limited
        r_limited = await ac.post("/api/founder-chat", json={"message": "Hello again"})
        assert "sending messages a little too quickly" in r_limited.json()["reply"]

