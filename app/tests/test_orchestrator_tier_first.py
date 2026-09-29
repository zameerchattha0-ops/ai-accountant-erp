"""tier_first candidate-order tests (Stage 3 CALL 1 fast-tier lead).

`tier_first` is opt-in (default False): the shipped primary-first order
(Token Harbor / DeepSeek in front of every text turn) must remain the default
for every existing caller — these tests pin both behaviours.
"""

from app.ai_orchestrator import AIOrchestrator


def _text_candidates(**kw):
    return AIOrchestrator()._candidate_providers(requires_vision=False, **kw)


def test_default_text_order_keeps_the_thinking_primary_first():
    """No behaviour change for existing callers: TH primary leads."""
    candidates = _text_candidates()
    assert candidates, "expected candidates"
    assert candidates[0]["provider"] == "token-harbor"
    assert candidates[-1]["provider"] == "gemini"


def test_tier_first_with_a_chain_skips_the_primary_but_keeps_the_tail():
    """The Stage 3 opt-in: the requested chain LEADS; Gemini stays last."""
    chain = ["qwen3-30b-a3b-instruct-2507", "qwen-flash", "qwen-max"]
    candidates = _text_candidates(text_chain=chain, tier_first=True)
    providers = [c["provider"] for c in candidates]
    models = [c["model"] for c in candidates if c["provider"] == "qwen"]
    assert "token-harbor" not in providers
    assert models == chain
    assert candidates[-1]["provider"] == "gemini"


def test_tier_first_without_a_chain_is_a_no_op():
    """tier_first only applies to an explicitly requested tier chain."""
    candidates = _text_candidates(tier_first=True)
    assert candidates[0]["provider"] == "token-harbor"


def test_vision_candidates_are_untouched_by_tier_first():
    """tier_first is a text-path switch; vision order is unchanged."""
    default = AIOrchestrator()._candidate_providers(requires_vision=True)
    opted = AIOrchestrator()._candidate_providers(
        requires_vision=True, text_chain=["qwen-flash"], tier_first=True
    )
    assert [c["model"] for c in default] == [c["model"] for c in opted]