"""Guard: a learned preference must never read as standing org policy.

Incident (2026-09-25): "i purchased 2 office chairs for 38000 yesterday" was
confirmed as "paid in cash (per org policy)" though the user never said cash.
Root cause: the learned ``payment_method=CASH`` row in ``ai.org_preferences``
(captured from ONE past clarification answer) was rendered into the
accounting-reasoning prompt under "ORGANIZATION POLICIES (defaults the user
established)", and the rules carried no prohibition against assuming
settlement — so the model cited the learned row as an org policy.

Instruction-layer fix pinned here (deliberately NOT a Python template):
* the block renders as LEARNED ANSWERS ... NOT standing policy, with an
  explicit "never a standing default" note;
* HARD PROHIBITIONS forbid assuming settlement / any unstated fact;
* the shared provider instructions carry the same rule;
* evidence rows carry kind=learned_answer (never "policy_preference").
"""

from app.accounting_reasoning import (
    _SYSTEM_RULES,
    ReasoningFacts,
    build_reasoning_prompt,
)
from app.prompts import (
    build_primary_reasoning_instructions,
    build_system_instructions,
)


def test_system_rules_forbid_assuming_settlement():
    assert "Never assume HOW this transaction was settled" in _SYSTEM_RULES
    assert '"per org policy" disclosure' in _SYSTEM_RULES


def test_learned_prefs_render_as_context_not_policy():
    prompt = build_reasoning_prompt(
        ReasoningFacts(
            user_request="i purchased 2 office chairs for 38000 yesterday",
            org_policies={
                "payment_method": "CASH",
                "transaction_nature": "FIXED_ASSET",
            },
            today="2026-09-25",
        ),
        offered_tools=[],
    )
    assert "ORGANIZATION POLICIES" not in prompt
    assert (
        "LEARNED ANSWERS FROM PAST SESSIONS (context only — NOT standing policy)"
        in prompt
    )
    assert "never a standing default" in prompt
    # The learned rows stay visible as context (they may inform an offer the
    # user confirms — never a silent default into the proposal).
    assert "payment_method" in prompt and "CASH" in prompt


def test_shared_provider_instructions_forbid_settlement_assumptions():
    primary = build_primary_reasoning_instructions()
    assert "Never assume how a transaction was settled" in primary
    system = build_system_instructions()
    assert "Never assume how a transaction was settled" in system


def test_evidence_rows_are_learned_answers_not_policies():
    import inspect

    from app import books_evidence

    src = inspect.getsource(books_evidence)
    assert '"kind": "learned_answer"' in src
    assert '"kind": "policy_preference"' not in src
