"""Provider candidate-order tests (Token Harbor chain -> Gemini -> Qwen last).

ORDER CONTRACT (2026-10-02 operator direction, backed by measurement):

    deepseek-v4.1-flash:free  (PRIMARY, thinking OFF)
      -> mimo-v2.6-flash:free
      -> mimo-v2.5:free
      -> gemini
      -> qwen chain LAST

The Qwen workspace answers HTTP 403 ``AccessDenied.Unpurchased`` for EVERY
model (measured 2026-10-02), so it must never sit ahead of a working provider.
``tier_first`` used to skip the TH primary for mechanical calls; that need is
now met at the source (``th_thinking_off``), and the requested tier chain is
appended at the Qwen tail instead of leading — otherwise a mechanical call
would front a dead provider.
"""

from app.ai_orchestrator import AIOrchestrator
from app.config import get_settings


def _text_candidates(**kw):
    return AIOrchestrator()._candidate_providers(requires_vision=False, **kw)


def _order(candidates):
    return [(c["provider"], c["model"]) for c in candidates]


def test_default_text_order_is_harbor_chain_then_gemini_then_qwen():
    settings = get_settings()
    assert _order(_text_candidates()) == [
        *[("token-harbor", m) for m in settings.th_text_chain_list],
        ("gemini", None),
        *[("qwen", m) for m in settings.qwen_chain_list],
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


def test_qwen_is_never_ahead_of_a_working_provider():
    settings = get_settings()
    order = _order(_text_candidates())
    qwen_at = [i for i, (p, _) in enumerate(order) if p == "qwen"]
    assert qwen_at, "the qwen chain is still the documented last resort"
    assert min(qwen_at) > order.index(("gemini", None))


def test_tier_first_appends_the_requested_chain_at_the_qwen_tail():
    """The requested tier chain no longer LEADS — it is the tail it always
    ends up being, so a mechanical call cannot front a dead provider."""
    settings = get_settings()
    chain = ["qwen3-30b-a3b-instruct-2507", "qwen-flash", "qwen-max"]
    candidates = _text_candidates(text_chain=chain, tier_first=True)
    order = _order(candidates)
    assert order[: len(settings.th_text_chain_list)] == [
        ("token-harbor", m) for m in settings.th_text_chain_list
    ]
    assert order[len(settings.th_text_chain_list)] == ("gemini", None)
    assert [m for p, m in order if p == "qwen"] == chain


def test_tier_first_without_a_chain_is_a_no_op():
    """tier_first only renames the qwen tail; the head is unchanged."""
    candidates = _text_candidates(tier_first=True)
    assert candidates[0]["provider"] == "token-harbor"
    assert candidates[0]["model"] == "deepseek-v4.1-flash:free"


def test_an_unentitled_model_is_dropped_from_the_candidates():
    """A 403 AccessDenied model is remembered and never offered again."""
    orch = AIOrchestrator()
    settings = get_settings()
    dead = settings.qwen_chain_list[0]
    orch._unentitled_models.add(("qwen", dead))
    offered = [m for p, m in _order(orch._candidate_providers(requires_vision=False))]
    assert dead not in offered
    # the rest of the chain survives
    assert settings.qwen_chain_list[1:]


def test_vision_candidates_are_untouched_by_tier_first():
    """tier_first is a text-path switch; vision order is unchanged."""
    default = AIOrchestrator()._candidate_providers(requires_vision=True)
    opted = AIOrchestrator()._candidate_providers(
        requires_vision=True, text_chain=["qwen-flash"], tier_first=True
    )
    assert [c["model"] for c in default] == [c["model"] for c in opted]


def test_vision_candidates_are_untouched_by_tier_first():
    """tier_first is a text-path switch; vision order is unchanged."""
    default = AIOrchestrator()._candidate_providers(requires_vision=True)
    opted = AIOrchestrator()._candidate_providers(
        requires_vision=True, text_chain=["qwen-flash"], tier_first=True
    )
    assert [c["model"] for c in default] == [c["model"] for c in opted]