"""Empty-answer retry + honest wording (fixes 1 and 3 of the root-cause doc).

Measured failure (docs/EMPTY_ANSWER_ROOT_CAUSE.md): a thinking model whose
hidden reasoning consumed the whole shared output cap returned
``finish_reason=length`` with ZERO content — the provider HAD answered, but
the run closed with "The AI provider did not answer in time", which is
factually wrong and misdirected the user.

Pinned here:

* ONE bounded retry of the same round with thinking disabled (the measured
  remedy: valid JSON in ~5.7s instead of an empty answer in ~20s);
* the retry never becomes a loop — a second empty answer fails with
  ``failure_reason="empty_answer"``;
* ``failure_reason`` distinguishes that case from a real timeout, and the
  user-facing wording keys off it.
"""

import uuid

import pytest

from app.accounting_reasoning import (
    ReasoningFacts,
    ReasoningOutcome,
    run_reasoning_loop,
)


class _Recorder:
    """Orchestrator double: records every call, replays canned responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def generate_text(
        self,
        *,
        prompt,
        context=None,
        model_chain=None,
        tier_first=False,
        thinking_off=False,
    ):
        self.calls.append({"thinking_off": thinking_off, "prompt": prompt})
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0] if self._responses else ""


async def _loop(orch, *, max_rounds=3):
    return await run_reasoning_loop(
        ReasoningFacts(user_request="Prchased Car on cash for 4000000"),
        organization_id=uuid.uuid4(),
        orchestrator=orch,
        max_rounds=max_rounds,
        timeout_seconds=5,
    )


class TestBoundedEmptyAnswerRetry:
    @pytest.mark.asyncio
    async def test_one_retry_runs_with_thinking_disabled(self):
        orch = _Recorder(["", '{"decision": {"kind": "noop"}}'])
        outcome = await _loop(orch)

        assert len(orch.calls) == 2
        assert orch.calls[0]["thinking_off"] is False  # first attempt as usual
        assert orch.calls[1]["thinking_off"] is True  # the measured remedy
        assert outcome.failure_reason is None
        assert outcome.rounds == 2

    @pytest.mark.asyncio
    async def test_a_second_empty_answer_fails_honestly(self):
        orch = _Recorder([""])
        outcome = await _loop(orch)

        assert len(orch.calls) == 2  # exactly one retry — never a loop
        assert orch.calls[1]["thinking_off"] is True
        assert outcome.provider_failed is True
        assert outcome.failure_reason == "empty_answer"
        assert outcome.rounds == 2

    @pytest.mark.asyncio
    async def test_no_retry_when_the_round_budget_is_one(self):
        orch = _Recorder([""])
        outcome = await _loop(orch, max_rounds=1)

        assert len(orch.calls) == 1
        assert outcome.failure_reason == "empty_answer"


class TestHonestWording:
    def test_failure_reason_defaults_to_none(self):
        assert ReasoningOutcome(status="UNSUPPORTED").failure_reason is None

    def test_empty_answer_is_never_called_a_timeout(self):
        from app.agent import _provider_down_summary

        message = _provider_down_summary("empty_answer")
        assert "did not answer in time" not in message
        assert "no usable answer" in message
        assert "nothing was recorded" in message.lower()
        assert "send your request again" in message.lower()

    @pytest.mark.parametrize(
        "reason", ["timeout", "provider_error", "total_budget", "", None]
    )
    def test_real_outages_keep_the_classic_wording(self, reason):
        from app.agent import _provider_down_summary

        message = _provider_down_summary(reason)
        assert "did not answer in time" in message
        assert "nothing was recorded" in message.lower()
        assert "send your request again" in message.lower()
