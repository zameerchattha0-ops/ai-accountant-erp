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


class AIOrchestrator:
    """Dispatches agent LLM calls across an ordered, capability-aware
    provider chain: Token Harbor (DeepSeek/Mimo, primary) → Qwen → Gemini."""

    def __init__(self) -> None:
        self._qwen_clients: Dict[str, Any] = {}  # model -> QwenClient
        self._harbor_clients: Dict[str, Any] = {}  # model -> QwenClient (Token Harbor)
        self._harbor_unavailable: Dict[str, str] = {}  # model -> cached reason
        self._gemini: Optional[Any] = None
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
        an unconfigured environment falls through to the Qwen chain with one
        cheap miss instead of re-probing the Vault on every request.
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
        """Build (once) a QwenClient for *model*. Raises ProviderError
        if unconfigured. Banned models are refused unconditionally."""
        settings = get_settings()
        model = model or settings.qwen_model
        if model in settings.qwen_banned_set:
            raise ValueError(f"Model '{model}' is banned from the runtime chain")
        if model not in self._qwen_clients:
            from app.qwen_client import QwenClient

            self._qwen_clients[model] = QwenClient(
                api_key=settings.qwen_api_key,
                base_url=settings.qwen_base_url,
                model=model,
                temperature=settings.qwen_temperature,
                max_output_tokens=settings.qwen_max_output_tokens,
                timeout_seconds=settings.qwen_timeout_seconds,
            )
        return self._qwen_clients[model]

    def _get_gemini(self) -> Any:
        """Build (once) the GeminiClient. Raises on Vault/config failure."""
        if self._gemini is None:
            from app.gemini_client import get_client as get_gemini_client

            self._gemini = get_gemini_client()
        return self._gemini

    # -------------------------------------------------------------------
    # Chain construction (capability-aware)
    # -------------------------------------------------------------------

    def _candidate_providers(
        self,
        *,
        requires_vision: bool = False,
        text_chain: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Ordered candidate list for the request's capability needs.

        Each candidate: {"provider", "model", "factory", "capability"}.
        Text requests traverse the requested Qwen text chain (the standard
        chain when none is given) then Gemini; vision requests traverse ONLY
        vision-capable models (an image must never be sent to a text-only
        model — capability, not fallback).

        ``text_chain`` is how the MODEL TIERS reach the transport: the
        accounting-reasoning stage names the deep chain, the mechanical
        extraction stages name the fast chain. An unknown model name simply
        produces no candidate for it — the rest of the requested chain, then
        Gemini, still run.
        """
        settings = get_settings()
        candidates: List[Dict[str, Any]] = []

        if requires_vision:
            # Token Harbor vision chain — Mimo leads image turns (the user's
            # image mandate), DeepSeek V4.1's native-multimodal flash follows.
            # Appended unconditionally: an unconfigured key raises a cached
            # ProviderError at construction and the chain continues below.
            for model in settings.th_vision_chain_list:
                candidates.append(
                    {
                        "provider": "token-harbor",
                        "model": model,
                        "capability": "vision",
                        "factory": (lambda m=model: self._get_harbor(m)),
                    }
                )
            for model in settings.qwen_vision_chain_list:
                candidates.append(
                    {
                        "provider": "qwen",
                        "model": model,
                        "capability": "vision",
                        "factory": (lambda m=model: self._get_qwen(m)),
                    }
                )
            # Gemini is NOT a vision candidate: GeminiClient.generate_with_tools
            # does not accept image parts. Document requests must be handled
            # by the verified vision-capable chain.
        else:
            # Token Harbor / DeepSeek V4.1 — PRIMARY for every text/tool turn
            # (all model tiers: the tier chains below become the ordered
            # fallback behind it).
            candidates.append(
                {
                    "provider": "token-harbor",
                    "model": settings.th_text_model,
                    "capability": "text_tools",
                    "factory": (lambda m=settings.th_text_model: self._get_harbor(m)),
                }
            )
            chain = [m for m in (text_chain or []) if m] or settings.qwen_chain_list
            for model in chain:
                candidates.append(
                    {
                        "provider": "qwen",
                        "model": model,
                        "capability": "text_tools",
                        "factory": (lambda m=model: self._get_qwen(m)),
                    }
                )
            candidates.append(
                {
                    "provider": "gemini",
                    "model": None,
                    "capability": "text_tools",
                    "factory": self._get_gemini,
                }
            )
        return candidates

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
        """
        tool_executed = {"any": False}

        async def _counting_executor(tool_name: str, args: dict) -> dict:
            tool_executed["any"] = True
            return await executor(tool_name, args)  # type: ignore[misc]

        wrapped_executor = _counting_executor if executor else None

        candidates = self._candidate_providers(requires_vision=requires_vision)
        provider_errors: List[str] = []

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
                requires_vision=False, text_chain=model_chain
            )
        else:
            candidates = self._candidate_providers(requires_vision=False)
        for candidate in candidates:
            name = candidate["provider"]
            model = candidate["model"]
            try:
                client = candidate["factory"]()
                return await client.generate_text(prompt=prompt, context=context)
            except Exception as exc:  # noqa: BLE001
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
        return ""

    async def generate_text_light(
        self,
        *,
        prompt: str,
        context: Optional[AgentContext] = None,
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
        """
        chain = get_settings().accounting_fast_chain_list
        return await self.generate_text(
            prompt=prompt, context=context, model_chain=chain
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
            "primary": settings.ai_primary_provider,
            "fallback": settings.ai_fallback_provider,
            "text_chain": settings.qwen_chain_list,
            "vision_chain": settings.qwen_vision_chain_list,
            "banned_models": sorted(settings.qwen_banned_set),
            "providers": {},
        }

        # Token Harbor (DeepSeek text + Mimo vision) — PRIMARY when the key
        # resolves (env TH_API_KEY, else Supabase Vault).  Both models probed
        # independently, mirroring the Qwen block below.
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

        # Qwen text chain — each member probed independently.
        qwen_providers = []
        for model in settings.qwen_chain_list:
            try:
                qwen = self._get_qwen(model)
                qwen_health = await qwen.health_check()
                qwen_providers.append(
                    {
                        "role": "primary",
                        "configured": True,
                        "available": qwen_health["ok"],
                        "model": model,
                        "endpoint": qwen.base_url,
                        "detail": qwen_health["detail"],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                qwen_providers.append(
                    {
                        "role": "primary",
                        "configured": False,
                        "available": False,
                        "model": model,
                        "detail": str(exc)[:200],
                    }
                )
        status["providers"]["qwen"] = qwen_providers

        # Gemini (fallback)
        try:
            gemini = self._get_gemini()
            status["providers"]["gemini"] = {
                "role": "fallback",
                "configured": True,
                "available": True,
                "model": gemini.model_name,
                "detail": "client initialised (Vault key loaded)",
            }
        except Exception as exc:  # noqa: BLE001
            status["providers"]["gemini"] = {
                "role": "fallback",
                "configured": False,
                "available": False,
                "detail": str(exc)[:200],
            }

        self._health_cache = status
        self._health_cached_at = now
        return status


def get_client() -> AIOrchestrator:
    """Return the singleton orchestrator (drop-in for gemini_client.get_client)."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AIOrchestrator()
    return _orchestrator
