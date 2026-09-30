"""Verify the PRESENTATION PROFILE: deterministic-first flags + the selective,
iterative questionnaire loop. No provider, no database, no writes.
"""

import sys

sys.path.insert(0, ".")


def main() -> int:
    from app.config import get_settings

    s = get_settings()
    print("— flags —")
    print("  semantic_llm_enabled        =", s.semantic_llm_enabled)
    print("  accounting_reasoning_enabled=", s.accounting_reasoning_enabled)
    print("  llm_classification_enabled  =", s.llm_classification_enabled)
    print("  two_call_runtime_enabled    =", s.two_call_runtime_enabled)
    print("  two_call_observation_enabled=", s.two_call_observation_enabled)

    from app.planner import _merge_clarification_answers, _missing_fields, _questions_for_fields
    from app import questionnaire as qmod

    print("\n— round 1: user gave only part of the facts —")
    entities = {"amount": 4000000.0, "item_description": "Car"}
    missing = _missing_fields("record_cash_purchase", entities)
    print("  request    : Purchased Car on cash for 4000000")
    print("  missing    :", missing)
    qs = _questions_for_fields("record_cash_purchase", missing, entities)
    questionnaire = qmod.build_questionnaire(
        missing, qs, entities, "record_cash_purchase"
    )
    asked_text = questionnaire.render_text() or ""
    print("  asked      :", asked_text.replace("\n", " | ")[:300])

    print("\n— round 2: the user's answers are merged, gaps recomputed —")
    merged = _merge_clarification_answers(
        dict(entities),
        [{"question": asked_text, "answer": "1) CASH\n2) 2026-09-29"}],
    )
    print("  merged     :", {k: merged[k] for k in sorted(merged)})
    print("  missing now:", _missing_fields("record_cash_purchase", merged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
