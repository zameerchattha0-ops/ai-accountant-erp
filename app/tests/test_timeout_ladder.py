"""The timeout ladder: no stage may cut a generation the provider could finish.

Platform ceiling (verified 2026-09-29 from vercel.com/docs/functions/limits):
Hobby + Fluid compute = 300s default AND maximum function duration. Production
has NO env overrides for these keys, so code defaults ARE production.

Regression being pinned: session a9b81e3e (2026-09-29 17:44) failed with
"provider did not answer in time" because accounting_reasoning_total_timeout
was 45s and cut round 2 mid-generation (~22s in) AFTER round 1 had answered
fine in 20.5s and evidence had returned in 3.1s. The provider was healthy;
only the clock was the hurdle.
"""

from app.agent import _LLM_EXECUTION_BUDGET_SECONDS, _LLM_PLANNING_BUDGET_SECONDS
from app.config import get_settings

PLATFORM_CEILING_SECONDS = 300  # Vercel Hobby, Fluid compute (docs)


def test_one_honest_attempt_fits_inside_a_round():
    s = get_settings()
    assert s.qwen_timeout_seconds <= s.accounting_reasoning_timeout
    assert s.th_timeout_seconds <= s.accounting_reasoning_timeout


def test_round_fits_inside_the_stage_total():
    s = get_settings()
    assert s.accounting_reasoning_timeout <= s.accounting_reasoning_total_timeout


def test_worst_stacked_path_fits_the_platform_ceiling():
    """reasoning + classification + execution + preamble must stay under 300s.

    Otherwise a worst-case turn would be killed by the PLATFORM (a raw 504)
    instead of closing honestly with the app's own resumable message.
    """
    s = get_settings()
    worst = (
        s.accounting_reasoning_total_timeout
        + s.llm_classification_timeout
        + _LLM_EXECUTION_BUDGET_SECONDS
        + 15  # preamble, evidence prefetch, context load, deterministic stages
    )
    assert worst <= PLATFORM_CEILING_SECONDS, worst


def test_reasoning_budgets_cover_a_slow_thinking_generation():
    """The measured need: round 1 ~20s + evidence ~3s + a 40-64s thinking
    round 2. The stage total must leave round 2 a full generation window."""
    s = get_settings()
    after_round_one = 20.5 + 3.1  # production trace, session a9b81e3e
    remaining_for_round_two = s.accounting_reasoning_total_timeout - after_round_one
    assert remaining_for_round_two >= s.accounting_reasoning_timeout