"""
ERP AI Agent — AI Provider Orchestrator
========================================
Routes runtime LLM traffic for the ERP Agent:

    User → ERP Agent (app/agent.py) → AI Orchestrator (this module)
         → Token Harbor  (PRIMARY — DeepSeek V4.1 text/tools, Mimo 2.6 vision;
                          OpenAI-compatible gateway, ':free' models, $0)
              deepseek-v4.1-flash:free / mimo-v2.6-flash:free
         → Qwen chain    (SECONDARY — Alibaba Model Studio, verified models)
              qwen3.6-plus → qwen3.5-plus → qwen-max → qwen-plus
         → Gemini        (FALLBACK — used only after both chains exhaust)

Capability-aware routing:
* Text/tool ERP requests  → the text/tool chain (models verified live for
  tool-calling capability).
* Vision/document requests → the vision chain (qwen3-vl-*). A model that
  cannot satisfy the request's capability is SKIPPED, never tried blindly.
* Banned models (qwen3.7-plus) are NEVER constructed or selected.

Safety rules:
* Fallback happens ONLY for genuine AI-provider failures (network,
  auth, HTTP 5xx — raised as ProviderError by qwen_client).
* If ANY tool was already executed for this request, the request is
  NEVER replayed against the fallback provider — execution state must
  be verified instead (idempotency / duplicate-execution protection).
* Business/validation errors travel inside ToolResult and never
  trigger a fallback.
* Bounded retries: QwenClient performs a small internal retry
  (3 attempts) for transient transport errors; the orchestrator itself
  performs NO extra retries — one attempt per model, then move on.
* Provider initialisation is lazy and fails gracefully — a missing or
  broken provider NEVER blocks FastAPI startup.

The orchestrator exposes the same client interface the ERP Agent
already used (``generate_with_tools`` / ``generate_text``), so the
agent itself is provider-agnostic.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Dict, List, Optional

import structlog

from app.config import get_settings
from app.models.schemas import AgentContext

log = structlog.get_logger(__name__)

# reduced output budget for simple lookup
# intents that still need the model (the deterministic fast-path handles
# the unambiguous ones without any LLM at all).
_LIGHT_OUTPUT_BUDGET_TOKENS = 600

# Module-level singleton
_orchestrator: Optional["AIOrchestrator"] = None


class AllProvidersRateLimited(RuntimeError):
    """EVERY provider that was actually called refused: it is RATE LIMITED.

    Raised instead of the generic "All AI providers failed" RuntimeError when
    throttling is the whole story, so the agent can report the REAL reason
    (the AI is rate limited / busy, nothing was recorded) instead of the
    timeout or empty-answer wording, which sends the user hunting for a
    problem that does not exist (production 2026-09-28 documented the primary
    free-tier daily cap; 2026-10-02 the plant purchase parked on an unanswerable
    question while the provider was throttled).

    A RuntimeError subclass, so every existing handler keeps working.
    """


def _is_rate_limited(exc: Exception) -> bool:
    """True when *exc* means the provider was THROTTLED (busy), not broken.

    Recognises the shared ``ProviderRateLimited`` type, a status/code attribute
    of 429 or a quota-bearing 4xx, and the wording the gateways actually send —
    so the classification does not depend on which transport raised it.
    """
    from app.qwen_client import ProviderRateLimited, is_rate_limited_error

    if isinstance(exc, ProviderRateLimited):
        return True
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if is_rate_limited_error(status, str(exc)):
        return True
    low = str(exc).lower()
    return "429" in str(exc) or "resource_exhausted" in low or "rate limit" in low


def _is_unentitled(exc: Exception) -> bool:
    """True when the provider says the KEY/ACCOUNT may not use this model.

    Permanent (unlike throttling): the model is never retried and is dropped
    from the candidate list for the life of the process.
    """
    from app.qwen_client import ProviderNotEntitled, is_entitlement_error

    if isinstance(exc, ProviderNotEntitled):
        return True
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if is_entitlement_error(status, str(exc)):
        return True
    low = str(exc).lower()
    return (
        "accessdenied.unpurchased" in low
        or "access to model denied" in low
        or "not eligible for using the model" in low
    )


class AIOrchestrator:
    """Dispatches agent LLM calls across the Token Harbor chain ONLY.

    Operator direction 2026-10-17: Qwen and Gemini are REMOVED from every
    request path — Qwen answers HTTP 403 AccessDenied.Unpurchased on this
    workspace (measured 2026-10-02), and the Gemini hop produced the
    uncontrolled cloudflare-HTML-400 failure that killed production sale
    session 19b2c1c4 (2026-10-17).  Every text/tool/vision request runs
    deepseek-v4.1-flash:free (thinking OFF) -> mimo-v2.6-flash:free ->
    mimo-v2.5:free on Token Harbor; no other provider is ever constructed.
    """

    def __init__(self) -> None:
        self._harbor_clients: Dict[str, Any] = {}  # model -> QwenClient (Token Harbor)
        self._harbor_unavailable: Dict[str, str] = {}  # model -> cached reason
        # (provider, model) pairs that answered HTTP 403 AccessDenied — dead
        # for the life of this process, never offered again.
        self._unentitled_models: set = set()
        self._health_cache: Dict[str, Any] = {}
        self._health_cached_at: float = 0.0

    # -------------------------------------------------------------------
    # Provider construction (lazy, graceful)
    # -------------------------------------------------------------------

    def _get_harbor(self, model: str) -> Any:
        """Build (once) an OpenAI-compatible client for Token Harbor *model*.

        The gateway speaks the OpenAI chat protocol, so the proven
        ``QwenClient`` transport is reused verbatim with the Harbor base URL
        and key.  Key resolution: env ``TH_API_KEY`` first, Supabase Vault
        second (migration 083 — same service-role-only pattern as Gemini).
        When neither is configured a ProviderError is raised AND CACHED, so
        an unconfigured environment fails honestly with one cheap miss
        instead of re-probing the Vault on every request — there is no
        downstream fallback chain any more (2026-10-17: Qwen and Gemini
        removed from dispatch).
        """
        settings = get_settings()
        if model in self._harbor_clients:
            return self._harbor_clients[model]
        if model in self._harbor_unavailable:
            from app.qwen_client import ProviderError

            raise ProviderError(self._harbor_unavailable[model])

        from app.qwen_client import ProviderError, QwenClient

        api_key = settings.th_api_key
        if not api_key:
            try:
                from app.database import get_th_api_key

                api_key = get_th_api_key()
            except Exception as exc:  # noqa: BLE001 — vault missing/unreachable
                reason = f"Token Harbor key unavailable (env TH_API_KEY / Vault): {str(exc)[:160]}"
                self._harbor_unavailable[model] = reason
                raise ProviderError(reason) from exc
        if not api_key:
            reason = "Token Harbor key is empty (set TH_API_KEY or Vault TH_API_KEY)"
            self._harbor_unavailable[model] = reason
            raise ProviderError(reason)

        self._harbor_clients[model] = QwenClient(
            api_key=api_key,
            base_url=settings.th_base_url,
            model=model,
            temperature=settings.qwen_temperature,
            max_output_tokens=settings.qwen_max_output_tokens,
            timeout_seconds=settings.th_timeout_seconds,
        )
        return self._harbor_clients[model]

    def _get_qwen(self, model: Optional[str] = None) -> Any:
        """REMOVED PATH — Qwen is never dispatched (operator direction
        2026-10-17).  Kept as an unconditional refusal so a stale caller or
        cached reference fails honestly instead of resurrecting the chain."""
        from app.qwen_client import ProviderError

        raise ProviderError(
            "Qwen is removed from dispatch (2026-10-17): every request goes "
            "to Token Harbor. Set nothing — the Harbor chain is the chain."
        )

    def _get_gemini(self) -> Any:
        """REMOVED PATH — Gemini is never dispatched (operator direction
        2026-10-17); the live Gemini hop failed with an uncontrolled
        cloudflare-HTML-400 (production session 19b2c1c4)."""
        raise RuntimeError(
            "Gemini is removed from dispatch (2026-10-17): every request "
            "goes to Token Harbor."
        )

    # -------------------------------------------------------------------
    # Chain construction (capability-aware)
    # -------------------------------------------------------------------

    def _candidate_providers(
        self,
        *,
        requires_vision: bool = False,
        text_chain: Optional[List[str]] = None,
        tier_first: bool = False,
    ) -> List[Dict[str, Any]]:
        """Ordered candidate list — TOKEN HARBOR ONLY (2026-10-17).

        Operator direction: Qwen and Gemini are REMOVED from every request
        path.  Evidence: the Qwen workspace answers HTTP 403
        AccessDenied.Unpurchased for every model (measured 2026-10-02), and
        the Gemini hop produced the uncontrolled cloudflare-HTML-400 that
        killed production sale session 19b2c1c4 (2026-10-17, stage
        agent_execute, APIError code 400).  Every text/tool request
        therefore traverses ``th_text_chain_list`` and every vision request
        ``th_vision_chain_list`` — nothing else is ever constructed.

        ``text_chain`` / ``tier_first`` are accepted for call-site
        compatibility and deliberately IGNORED: the requested tier chains
        name Qwen models, and no request may reach them — the measured
        Harbor chain (deepseek primary with thinking OFF, then mimo) serves
        every tier.
        """
        settings = get_settings()
        candidates: List[Dict[str, Any]] = []

        if requires_vision:
            for model in settings.th_vision_chain_list:
                candidates.append(
                    {
                        "provider": "token-harbor",
                        "model": model,
                        "capability": "vision",
                        "factory": (lambda m=model: self._get_harbor(m)),
                    }
                )
        else:
            for model in settings.th_text_chain_list:
                self._offer(candidates, self._harbor_candidate(model))
        return candidates

    # -------------------------------------------------------------------
    # Candidate builders (single source of truth for the order above)
    # -------------------------------------------------------------------

    def _harbor_candidate(self, model: str) -> Dict[str, Any]:
        return {
            "provider": "token-harbor",
            "model": model,
            "capability": "text_tools",
            "factory": (lambda m=model: self._get_harbor(m)),
        }

    def _offer(
        self, candidates: List[Dict[str, Any]], cand: Dict[str, Any]
    ) -> None:
        """Append *cand* unless already offered or known UNENTITLED.

        A model that answered HTTP 403 ``AccessDenied.Unpurchased`` is dead
        for the life of the process, so it is never offered again (measured
        2026-10-02: EVERY Qwen model on that workspace).  Duplicate keys are
        dropped so a requested tier chain can overlap the standard chain.
        """
        key = (cand["provider"], cand["model"])
        if key in self._unentitled_models:
            return
        if any((c["provider"], c["model"]) == key for c in candidates):
            return
        candidates.append(cand)

    # -------------------------------------------------------------------
    # Core dispatch
    # -------------------------------------------------------------------

    async def generate_with_tools(
        self,
        *,
        user_message: str,
        context: AgentContext,
        max_tool_iterations: int = 10,
        executor: Optional[Any] = None,
        requires_vision: bool = False,
        excluded_tools: Optional[set] = None,
        light_budget: bool = False,
        thinking_off: bool = False,
    ) -> Dict[str, Any]:
        """Same contract as GeminiClient.generate_with_tools, with a
        multi-model fallback chain.

        Providers are tried in capability-compatible order (Qwen chain,
        then Gemini for text requests). Fallback is attempted ONLY when
        no tool has executed yet for this request — after any tool
        execution a provider failure is re-raised so the agent can mark
        the session FAILED instead of risking a duplicate mutation on
        replay.

        ``light_budget``: when True the
        request gets a reduced max_output_tokens — used for simple lookup
        intents that still need the model (e.g. ambiguous phrasing) after
        the deterministic fast-path did not apply.

        ``thinking_off``: forwarded to the client when it supports it (the
        Qwen TRANSPORT does, and Token Harbor reuses that transport with its
        own base URL — so the thinking DeepSeek primary honours it too;
        Gemini does not take it and is skipped).  Used by the agent's
        iterative EXECUTION loop, which must fit several round-trips inside a
        fixed wall-clock budget and therefore asks for speed, not hidden
        reasoning.
        """
        tool_executed = {"any": False}

        async def _counting_executor(tool_name: str, args: dict) -> dict:
            tool_executed["any"] = True
            return await executor(tool_name, args)  # type: ignore[misc]

        wrapped_executor = _counting_executor if executor else None

        candidates = self._candidate_providers(requires_vision=requires_vision)
        provider_errors: List[str] = []
        # Distinguishes "the provider is BUSY" (rate limited) from "the
        # provider is BROKEN": when EVERY provider that was actually called
        # refused on throttling, the honest reason is reported (see
        # AllProvidersRateLimited) instead of a generic outage.
        attempted: List[str] = []
        rate_limited: List[str] = []
        for candidate in candidates:
            name = candidate["provider"]
            model = candidate["model"]
            attempt_started = time.monotonic()
            try:
                client = candidate["factory"]()
            except Exception as exc:  # noqa: BLE001 — config/vault failures
                provider_errors.append(f"{name}/{model}: unavailable ({exc})")
                log.warning(
                    "orchestrator.provider_unavailable",
                    provider=name,
                    model=model,
                    capability=candidate["capability"],
                    error=str(exc)[:200],
                )
                continue

            try:
                # Pass the exclusion set through ONLY when non-empty —
                # keeps the provider contract backwards-compatible.
                extra_kwargs = (
                    {"excluded_tools": excluded_tools} if excluded_tools else {}
                )
                if light_budget:
                    # Tiered routing: simple lookups that still need the
                    # model get a reduced output budget.
                    extra_kwargs["max_output_tokens"] = _LIGHT_OUTPUT_BUDGET_TOKENS
                # THINKING OFF for the Token Harbor chain by default
                # (operator direction 2026-10-02): the DeepSeek primary is a
                # THINKING model — measured 2026-09-29 it burned 20.4s of
                # hidden reasoning and returned 0 answer chars
                # (finish_reason=length) on a mechanical prompt.
                _want_thinking_off = thinking_off or (
                    name == "token-harbor" and get_settings().th_thinking_off
                )
                if _want_thinking_off:
                    # OPTIONAL per-client capability — passed ONLY when the
                    # client's signature accepts it (Qwen/Harbor do, Gemini
                    # does not), mirroring generate_text's contract.
                    try:
                        _accepted = inspect.signature(
                            client.generate_with_tools
                        ).parameters
                    except (TypeError, ValueError):  # pragma: no cover
                        _accepted = {}
                    if "thinking_off" in _accepted or any(
                        p.kind is inspect.Parameter.VAR_KEYWORD
                        for p in _accepted.values()
                    ):
                        extra_kwargs["thinking_off"] = True
                result = await client.generate_with_tools(
                    user_message=user_message,
                    context=context,
                    max_tool_iterations=max_tool_iterations,
                    executor=wrapped_executor,
                    **extra_kwargs,
                )
                result["provider"] = name
                result["model"] = model or getattr(client, "model_name", None)
                log.info(
                    "orchestrator.provider_used",
                    provider=name,
                    model=result.get("model"),
                    capability=candidate["capability"],
                    attempts=len(provider_errors) + 1,
                    elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
                    tool_calls=len(result.get("tool_calls", [])),
                    iterations=result.get("iteration_count"),
                )
                return result
            except Exception as exc:  # noqa: BLE001
                if tool_executed["any"]:
                    # A tool (possibly a mutation) already ran — NEVER
                    # replay this request against another provider.
                    log.error(
                        "orchestrator.failure_after_execution_no_fallback",
                        provider=name,
                        model=model,
                        error=str(exc)[:200],
                    )
                    raise RuntimeError(
                        f"AI provider '{name}/{model}' failed AFTER tools "
                        f"executed ({exc}). Execution state must be verified "
                        "before any retry — no automatic fallback was attempted."
                    ) from exc

                provider_errors.append(f"{name}/{model}: {exc}")
                attempted.append(f"{name}/{model}")
                if _is_unentitled(exc):
                    # PERMANENT: the account may not use this model.  Remember
                    # it so _offer() never proposes it again this process, and
                    # never retry it within this call either.
                    self._unentitled_models.add((name, model))
                    log.error(
                        "orchestrator.provider_not_entitled_skipping",
                        provider=name,
                        model=model,
                        detail=str(exc)[:200],
                    )
                elif _is_rate_limited(exc):
                    # BUSY, not broken.  The transports no longer retry a rate
                    # limit, so the NEXT provider is reached within the request
                    # budget and a plan is still produced.
                    rate_limited.append(f"{name}/{model}")
                    log.warning(
                        "orchestrator.provider_rate_limited_falling_back",
                        provider=name,
                        model=model,
                        attempt=len(provider_errors),
                        elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
                        detail=str(exc)[:200],
                    )
                else:
                    log.warning(
                        "orchestrator.provider_failed_falling_back",
                        provider=name,
                        model=model,
                        attempt=len(provider_errors),
                        elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
                        fallback_reason=str(exc)[:200],
                    )
                # Invalidate the cached client for the failed candidate so
                # the next call rebuilds it (bad model config, etc.).
                if name == "qwen" and model:
                    self._qwen_clients.pop(model, None)
                else:
                    self._gemini = None

        if attempted and len(rate_limited) == len(attempted):
            # Nothing was recorded and no provider was broken — every provider
            # that answered said "too many requests".  Say exactly that.
            raise AllProvidersRateLimited(
                "Every AI provider is rate limited right now "
                f"({', '.join(rate_limited)}). Nothing was recorded; retry shortly."
            )
        raise RuntimeError(
            "All AI providers failed. "
            + "; ".join(provider_errors)
        )

    async def generate_text(
        self,
        *,
        prompt: str,
        context: Optional[AgentContext] = None,
        model_chain: Optional[List[str]] = None,
        tier_first: bool = False,
        thinking_off: bool = False,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """Plain text generation across the same capability chain.

        ``model_chain`` restricts/orders the Qwen candidates for THIS call — the
        accounting-reasoning stage names the deep model chain and the mechanical
        extraction stages name the fast one. The chain IS the candidate list, so
        a tier that names a model outside the standard chain is honoured instead
        of silently reverting to the standard chain. A model the provider does
        not serve fails its own candidate only: the rest of the requested chain,
        then Gemini, still run (Gemini is the transport's last resort for text).
        """
        accepts_chain = False
        try:
            params = inspect.signature(self._candidate_providers).parameters
            accepts_chain = "text_chain" in params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
        except (TypeError, ValueError):  # pragma: no cover - exotic callables
            accepts_chain = False
        if model_chain and accepts_chain:
            candidates = self._candidate_providers(
                requires_vision=False,
                text_chain=model_chain,
                tier_first=tier_first,
            )
        else:
            candidates = self._candidate_providers(
                requires_vision=False, tier_first=tier_first
            )
        attempted: List[str] = []
        rate_limited: List[str] = []
        for candidate in candidates:
            name = candidate["provider"]
            model = candidate["model"]
            try:
                client = candidate["factory"]()
                # `thinking_off` / `max_output_tokens` are OPTIONAL per-client
                # capabilities (the Qwen client honours them; Gemini and
                # others simply do not take them).
                _accepted = inspect.signature(client.generate_text).parameters
                _kwargs: Dict[str, Any] = {"prompt": prompt, "context": context}
                if (
                    thinking_off
                    or (name == "token-harbor" and get_settings().th_thinking_off)
                ) and "thinking_off" in _accepted:
                    _kwargs["thinking_off"] = True
                if max_output_tokens and "max_output_tokens" in _accepted:
                    _kwargs["max_output_tokens"] = max_output_tokens
                return await client.generate_text(**_kwargs)
            except Exception as exc:  # noqa: BLE001
                attempted.append(f"{name}/{model}")
                if _is_unentitled(exc):
                    self._unentitled_models.add((name, model))
                    log.error(
                        "orchestrator.text_provider_not_entitled_skipping",
                        provider=name,
                        model=model,
                        detail=str(exc)[:200],
                    )
                elif _is_rate_limited(exc):
                    # BUSY, not broken: never retried, never reported as an
                    # outage.  The next provider is tried immediately.
                    rate_limited.append(f"{name}/{model}")
                    log.warning(
                        "orchestrator.text_provider_rate_limited",
                        provider=name,
                        model=model,
                        detail=str(exc)[:200],
                    )
                else:
                    log.warning(
                        "orchestrator.text_provider_failed",
                        provider=name,
                        model=model,
                        fallback_reason=str(exc)[:200],
                    )
                if name == "qwen" and model:
                    self._qwen_clients.pop(model, None)
                else:
                    self._gemini = None
        if attempted and len(rate_limited) == len(attempted):
            # Returning "" here would be read as an EMPTY ANSWER (the
            # documented empty-answer wording blames the model's reasoning
            # budget), sending the user after a problem that does not exist.
            # Say what actually happened instead.
            raise AllProvidersRateLimited(
                "Every AI provider is rate limited right now "
                f"({', '.join(rate_limited)}). Nothing was recorded; retry shortly."
            )
        return ""

    async def generate_text_light(
        self,
        *,
        prompt: str,
        context: Optional[AgentContext] = None,
        tier_first: bool = False,
    ) -> str:
        """Text generation on the FAST tier — MECHANICAL work only.

        This is the entry point for stages that EXTRACT or NORMALISE rather
        than decide accounting: semantic fact extraction, entity perception,
        classification, formatting. It must never be used for the accounting
        reasoning rounds, whose model chain is chosen for judgement quality
        (``settings.accounting_reasoning_model_chain``).

        Tiering is measurement-driven, not cosmetic. On the live workspace:
        the same 10.9 KB accounting text took 9.8s on qwen3-30b-a3b-instruct
        and 57.8s on qwen3.6-plus, and the same 2-tool request took 3.5s vs
        8.1s — the difference is reasoning tokens the mechanical stages never
        use. ``ACCOUNTING_FAST_MODEL_CHAIN=standard`` disables the tier (the
        standard chain is used), so behaviour can be reverted by config alone.

        ``tier_first=True`` additionally skips the Token Harbor primary so the
        fast chain actually LEADS the call (see ``_candidate_providers``);
        default False keeps the shipped primary-first order.
        """
        chain = get_settings().accounting_fast_chain_list
        return await self.generate_text(
            prompt=prompt,
            context=context,
            model_chain=chain,
            tier_first=tier_first,
        )

    # -------------------------------------------------------------------
    # Health / status
    # -------------------------------------------------------------------

    async def get_providers_status(self, force: bool = False) -> Dict[str, Any]:
        """Return availability info for each provider. Never raises.

        Results are cached for ``provider_health_ttl_seconds`` so the ERP
        can poll this endpoint without hammering the providers.
        """
        settings = get_settings()
        now = time.monotonic()
        if (
            not force
            and self._health_cache
            and (now - self._health_cached_at) < settings.provider_health_ttl_seconds
        ):
            return self._health_cache

        status: Dict[str, Any] = {
            "primary": "token-harbor",
            "fallback": "none",
            "text_chain": settings.th_text_chain_list,
            "vision_chain": settings.th_vision_chain_list,
            "providers": {},
        }

        # Token Harbor (DeepSeek text + Mimo vision) — THE chain (operator
        # direction 2026-10-17: Qwen and Gemini are removed from dispatch;
        # neither is probed nor reported here).
        harbor_models = list(dict.fromkeys(
            [settings.th_text_model, *settings.th_vision_chain_list]
        ))
        harbor_providers = []
        for model in harbor_models:
            try:
                harbor = self._get_harbor(model)
                harbor_health = await harbor.health_check()
                harbor_providers.append(
                    {
                        "role": "primary",
                        "configured": True,
                        "available": harbor_health["ok"],
                        "model": model,
                        "endpoint": harbor.base_url,
                        "detail": harbor_health["detail"],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                harbor_providers.append(
                    {
                        "role": "primary",
                        "configured": False,
                        "available": False,
                        "model": model,
                        "detail": str(exc)[:200],
                    }
                )
        status["providers"]["token-harbor"] = harbor_providers
        if any(e["configured"] for e in harbor_providers):
            status["primary"] = "token-harbor"
            status["primary_models"] = harbor_models

        self._health_cache = status
        self._health_cached_at = now
        return status


def get_client() -> AIOrchestrator:
    """Return the singleton orchestrator (drop-in for gemini_client.get_client)."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AIOrchestrator()
    return _orchestrator
