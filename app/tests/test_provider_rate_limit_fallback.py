"""Rate limits must move the plan to a DIFFERENT LLM, not burn the budget.

Production history this pins:

* 2026-09-28 — the primary provider returned HTTP 429 (free-tier daily cap)
  for a whole working day (recorded in test_contract_primed_prompt), so 429
  handling is a recurring reality here, not a hypothetical;
* 2026-10-01/02 — while diagnosing the stalled fixed-asset requests the retry
  policy was found to MULTIPLY: ``generate_with_tools`` and
  ``_chat_completion`` are BOTH decorated with ``stop_after_attempt(3)`` +
  ``wait_exponential(min=2, max=10)`` — up to 9 HTTP calls and ~20 s of
  sleeping PER CANDIDATE against the agent's 75 s planning budget.  A cap
  that cannot clear inside a backoff window therefore consumed the whole
  request, so the fallback chain (Token Harbor → Qwen → Gemini) was never
  reached in time and the user got generic timeout wording.

Invariants:

* a 429 raises ``ProviderRateLimited`` after ONE call (no storm) while a 5xx
  IS still retried (retrying a transient fault is right);
* the orchestrator falls through to the next candidate on throttling and
  raises ``AllProvidersRateLimited`` only when EVERY provider it called was
  throttled (mixed causes keep the generic RuntimeError);
* the user-facing wording says "rate limited", never "did not answer in time";
* every fixed-asset tool carries a contract, so the contract-primed reasoning
  prompt advertises its real parameter vocabulary.
"""

from __future__ import annotations

import pytest
from tenacity import wait_none

import app.qwen_client as qwen_mod
from app.ai_orchestrator import (
    AIOrchestrator,
    AllProvidersRateLimited,
    _is_rate_limited,
)
from app.gemini_client import _provider_error_from_sdk
from app.models.schemas import AgentContext
from app.qwen_client import (
    ProviderError,
    ProviderRateLimited,
    QwenClient,
    is_rate_limited_error,
)


def _client(monkeypatch) -> QwenClient:
    """A client built hermetically (no settings/env/DB lookup)."""
    monkeypatch.setattr(qwen_mod, "load_constitution", lambda: "")
    return QwenClient(
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        model="qwen-test",
    )


class _Resp:
    def __init__(self, status_code: int, text: str = "", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def _stub_http(monkeypatch, resp: _Resp) -> dict:
    """Replace the transport with a counter; returns the call counter."""
    calls = {"n": 0}

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **kw):
            calls["n"] += 1
            return resp

    monkeypatch.setattr(qwen_mod.httpx, "AsyncClient", _FakeAsyncClient)
    return calls


async def _no_tool_defs():
    return []


class TestRateLimitFailsFast:
    @pytest.mark.asyncio
    async def test_a_429_is_raised_after_exactly_one_http_call(self, monkeypatch):
        """NO retry storm: one call, one ProviderRateLimited, no sleeping.

        Both stacked decorators (outer generate_with_tools + inner
        _chat_completion) carry the fail-fast predicate, so the old 3x3 = 9
        call / ~20 s pattern cannot recur.
        """
        client = _client(monkeypatch)
        calls = _stub_http(
            monkeypatch,
            _Resp(429, "rate limit exceeded, try in 60s", {"retry-after": "60"}),
        )
        monkeypatch.setattr(qwen_mod, "get_gemini_tool_definitions", _no_tool_defs)

        with pytest.raises(ProviderRateLimited) as excinfo:
            await client.generate_with_tools(
                user_message="We Buy a Plant for 6,700,000 on cash, yesterday",
                context=AgentContext(organization={}, user={}),
            )

        assert calls["n"] == 1, "a rate limit must NOT be retried"
        assert excinfo.value.status == 429
        assert excinfo.value.retry_after == "60"
        # it IS a ProviderError, so every existing handler keeps working
        assert isinstance(excinfo.value, ProviderError)

    @pytest.mark.asyncio
    async def test_a_transient_5xx_is_still_retried_three_times(self, monkeypatch):
        """Fail fast ONLY for throttling — retrying a broken endpoint is right.

        The count below (9 = 3 outer attempts x 3 inner attempts) is the
        STACKED retry measured live: it is acceptable for a rare 5xx, and is
        exactly why a daily-cap 429 had to be cut down to ONE call above.
        """
        client = _client(monkeypatch)
        monkeypatch.setattr(qwen_mod, "get_gemini_tool_definitions", _no_tool_defs)
        # assert the retry COUNT, not the backoff duration (6s of sleeping)
        monkeypatch.setattr(QwenClient._chat_completion.retry, "wait", wait_none())
        monkeypatch.setattr(QwenClient.generate_with_tools.retry, "wait", wait_none())
        calls = _stub_http(monkeypatch, _Resp(503, "upstream unavailable"))

        with pytest.raises(ProviderError) as excinfo:
            await client.generate_with_tools(
                user_message="x", context=AgentContext(organization={}, user={})
            )

        assert calls["n"] == 9, "transient faults must still be retried (3 x 3)"
        assert not isinstance(excinfo.value, ProviderRateLimited)
        assert "503" in str(excinfo.value)

    def test_both_decorators_carry_the_fail_fast_predicate(self):
        for entry in (QwenClient.generate_with_tools, QwenClient._chat_completion):
            assert type(entry.retry.retry).__name__ == "retry_if_not_exception_type"


class TestRateLimitClassification:
    @pytest.mark.parametrize(
        "status,body,expected",
        [
            (429, "", True),
            (429, "whatever the body says", True),
            (403, "You have exceeded your current quota", True),
            (400, "rate limit exceeded", True),
            (500, "internal error", False),
            (400, "purchase_cost must be positive", False),
            (404, "not found", False),
        ],
    )
    def test_is_rate_limited_error(self, status, body, expected):
        assert is_rate_limited_error(status, body) is expected

    def test_the_shared_classifier_recognises_every_shape(self):
        assert _is_rate_limited(ProviderRateLimited("busy", status=429))
        assert _is_rate_limited(Exception("HTTP 429 too many requests"))
        assert _is_rate_limited(Exception("RESOURCE_EXHAUSTED: quota exceeded"))
        assert _is_rate_limited(Exception("Qwen API rate limit HTTP 429: ..."))

        class _WithStatus(Exception):
            status = 429

        assert _is_rate_limited(_WithStatus("throttled"))
        assert not _is_rate_limited(Exception("connection refused"))
        assert not _is_rate_limited(ValueError("purchase_cost must be positive"))


# --------------------------------------------------------------------------
# The orchestrator MOVES to the next provider on throttling
# --------------------------------------------------------------------------


class _Throttled:
    async def generate_with_tools(self, **kwargs):
        raise ProviderRateLimited("HTTP 429: rate limit exceeded", status=429)


class _Broken:
    async def generate_with_tools(self, **kwargs):
        raise RuntimeError("connection refused")


class _Good:
    async def generate_with_tools(self, **kwargs):
        return {"text": "planned", "tool_calls": [], "iteration_count": 1}


def _candidates(*clients):
    return [
        {
            "provider": f"p{index}",
            "model": f"m{index}",
            "capability": "text_tools",
            "factory": lambda c=client: c,
        }
        for index, client in enumerate(clients)
    ]


class TestOrchestratorMovesToAnotherLlm:
    @pytest.mark.asyncio
    async def test_a_throttled_provider_falls_through_to_the_next(self, monkeypatch):
        """The whole point: rate limit -> the NEXT LLM answers the plan."""
        orch = AIOrchestrator()
        monkeypatch.setattr(
            orch,
            "_candidate_providers",
            lambda **kw: _candidates(_Throttled(), _Good()),
        )
        result = await orch.generate_with_tools(
            user_message="We Buy a Plant for 6,700,000 on cash, yesterday",
            context=AgentContext(organization={}, user={}),
        )
        assert result["provider"] == "p1"
        assert result["text"] == "planned"

    @pytest.mark.asyncio
    async def test_every_provider_throttled_raises_the_specific_error(
        self, monkeypatch
    ):
        orch = AIOrchestrator()
        monkeypatch.setattr(
            orch,
            "_candidate_providers",
            lambda **kw: _candidates(_Throttled(), _Throttled()),
        )
        with pytest.raises(AllProvidersRateLimited) as excinfo:
            await orch.generate_with_tools(
                user_message="x", context=AgentContext(organization={}, user={})
            )
        # the reason must survive so the agent can report it honestly
        assert "rate limited" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_mixed_causes_keep_the_generic_error(self, monkeypatch):
        """Only THROTTLING alone earns the specific error — a broken provider
        is still a provider outage, never mislabelled as a rate limit."""
        orch = AIOrchestrator()
        monkeypatch.setattr(
            orch,
            "_candidate_providers",
            lambda **kw: _candidates(_Throttled(), _Broken()),
        )
        with pytest.raises(RuntimeError) as excinfo:
            await orch.generate_with_tools(
                user_message="x", context=AgentContext(organization={}, user={})
            )
        assert not isinstance(excinfo.value, AllProvidersRateLimited)

    @pytest.mark.asyncio
    async def test_text_generation_raises_instead_of_returning_empty(
        self, monkeypatch
    ):
        """generate_text used to swallow this into "" — which the reasoning
        stage reads as an EMPTY ANSWER and blames the model's reasoning budget."""

        class _ThrottledText:
            async def generate_text(self, prompt, context=None):
                raise ProviderRateLimited("HTTP 429", status=429)

        orch = AIOrchestrator()
        monkeypatch.setattr(
            orch,
            "_candidate_providers",
            lambda **kw: _candidates(_ThrottledText(), _ThrottledText()),
        )
        with pytest.raises(AllProvidersRateLimited):
            await orch.generate_text(prompt="extract", context=None)

    @pytest.mark.asyncio
    async def test_text_generation_still_falls_through_to_the_next(self, monkeypatch):
        class _ThrottledText:
            async def generate_text(self, prompt, context=None):
                raise ProviderRateLimited("HTTP 429", status=429)

        class _GoodText:
            async def generate_text(self, prompt, context=None):
                return "extracted facts"

        orch = AIOrchestrator()
        monkeypatch.setattr(
            orch,
            "_candidate_providers",
            lambda **kw: _candidates(_ThrottledText(), _GoodText()),
        )
        assert await orch.generate_text(prompt="extract", context=None) == "extracted facts"


# --------------------------------------------------------------------------
# What the USER sees, and what Gemini's SDK errors become
# --------------------------------------------------------------------------


class TestRateLimitIsReportedHonestly:
    def test_the_user_is_told_it_is_rate_limited_not_timeout(self):
        from app.agent import _provider_down_summary, _provider_stall_summary

        summary = _provider_down_summary("rate_limited")
        assert "rate limited" in summary
        assert "nothing was recorded" in summary
        # the stall path (planning / execution / lookup continuation) uses the
        # same wording instead of interpolating the raw sentinel
        assert _provider_stall_summary("rate_limited") == summary
        # non-rate-limit stalls keep the previous wording
        plain = _provider_stall_summary(
            "The AI provider stopped responding (planning took longer than 75s)."
        )
        assert plain.startswith(
            "The AI provider stopped responding (planning took longer than 75s)."
        )
        assert "Nothing was recorded yet" in plain
        assert "rate limited" not in plain

    def test_gemini_sdk_throttling_is_normalised(self):
        throttled = _provider_error_from_sdk(
            Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric")
        )
        assert isinstance(throttled, ProviderRateLimited)

        # a genuine provider error passes through untouched
        other = ValueError("bad argument")
        assert _provider_error_from_sdk(other) is other


# --------------------------------------------------------------------------
# Every fixed-asset tool carries a contract (Copilot review 2026-10-02)
# --------------------------------------------------------------------------


def test_every_fixed_asset_tool_carries_a_contract():
    """``dispose_fixed_asset`` and ``record_asset_depreciation`` were
    registered WITHOUT ``contract=``; without it ``tool_contracts()`` omits
    them from the contract-primed reasoning prompt, so the model had no
    parameter vocabulary for them at all."""
    from app.tools import get_handler

    for slug in (
        "register_fixed_asset",
        "dispose_fixed_asset",
        "record_asset_depreciation",
    ):
        contract = (get_handler(slug) or {}).get("contract")
        assert contract, f"{slug} has no contract"
        accepted = contract.get("accepted") or []
        assert "asset_id" in accepted or "name" in accepted, slug
        assert "organization_id" not in accepted, slug  # injected by the router

    # the contract-primed prompt actually sees them now
    from app.tools import tool_contracts

    contracts = tool_contracts()
    for slug in ("dispose_fixed_asset", "record_asset_depreciation"):
        assert slug in contracts, f"{slug} missing from tool_contracts()"
