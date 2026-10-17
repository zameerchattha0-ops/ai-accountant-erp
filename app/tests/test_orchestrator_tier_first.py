"""Provider candidate-order tests — TOKEN HARBOR ONLY (2026-10-17).

ORDER CONTRACT (operator direction 2026-10-17, evidence-backed):

    deepseek-v4.1-flash:free  (PRIMARY, thinking OFF)
      -> mimo-v2.6-flash:free
      -> mimo-v2.5:free
      -> (nothing else)

Qwen and Gemini are REMOVED from every request path:

* Qwen answers HTTP 403 ``AccessDenied.Unpurchased`` for EVERY model on
  this workspace (measured 2026-10-02);
* the Gemini hop produced the uncontrolled cloudflare-HTML-400 failure
  that killed production sale session 19b2c1c4 (2026-10-17, stage
  ``agent_execute``, APIError code 400) — the incident that motivated
  this removal.

``text_chain`` / ``tier_first`` remain accepted by the dispatch signature
for call-site compatibility but are IGNORED: the requested tier chains
name Qwen models and no request may ever reach them.
"""

from app.ai_orchestrator import AIOrchestrator
from app.config import get_settings


def _text_candidates(**kw):
    return AIOrchestrator()._candidate_providers(requires_vision=False, **kw)


def _order(candidates):
    return [(c["provider"], c["model"]) for c in candidates]


def test_default_text_order_is_the_harbor_chain_only():
    settings = get_settings()
    assert _order(_text_candidates()) == [
        ("token-harbor", m) for m in settings.th_text_chain_list
    ]


def test_the_primary_is_deepseek_and_thinking_is_off():
    settings = get_settings()
    first = _text_candidates()[0]
    assert first["provider"] == "token-harbor"
    assert first["model"] == "deepseek-v4.1-flash:free"
    assert settings.th_text_chain_list[1:3] == [
        "mimo-v2.6-flash:free",
        "mimo-v2.5:free",
    ]
    assert settings.th_thinking_off is True


def test_no_request_ever_reaches_qwen_or_gemini():
    """The removal contract: no mode, no requested chain, no tier flag may
    introduce a qwen or gemini candidate."""
    for kw in (
        {},
        {"text_chain": ["qwen3-max", "qwen-flash"], "tier_first": True},
        {"text_chain": ["qwen3-max"], "tier_first": False},
        {"tier_first": True},
    ):
        providers = {p for p, _ in _order(_text_candidates(**kw))}
        assert providers == {"token-harbor"}, (kw, providers)


def test_the_removed_builders_refuse_instead_of_resurrecting():
    """A stale caller fails honestly — never constructs a dead provider."""
    orch = AIOrchestrator()
    try:
        orch._get_qwen("qwen3-max")
        raise AssertionError("_get_qwen must refuse")
    except Exception as exc:  # noqa: BLE001 — ProviderError from qwen_client
        assert "Token Harbor" in str(exc)
    try:
        orch._get_gemini()
        raise AssertionError("_get_gemini must refuse")
    except RuntimeError as exc:
        assert "Token Harbor" in str(exc)


def test_vision_is_the_harbor_vision_chain_only():
    settings = get_settings()
    default = AIOrchestrator()._candidate_providers(requires_vision=True)
    assert _order(default) == [
        ("token-harbor", m) for m in settings.th_vision_chain_list
    ]
    # tier_first / requested chains never change the vision order either
    opted = AIOrchestrator()._candidate_providers(
        requires_vision=True, text_chain=["qwen-flash"], tier_first=True
    )
    assert [c["model"] for c in default] == [c["model"] for c in opted]


def test_an_unentitled_model_is_dropped_from_the_candidates():
    """A 403 AccessDenied model is remembered and never offered again
    (mechanism kept — Harbor models can be unentitled too)."""
    orch = AIOrchestrator()
    settings = get_settings()
    dead = settings.th_text_chain_list[0]
    orch._unentitled_models.add(("token-harbor", dead))
    offered = [m for p, m in _order(orch._candidate_providers(requires_vision=False))]
    assert dead not in offered
    assert settings.th_text_chain_list[1:], "the rest of the chain survives"
