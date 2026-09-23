"""P1-⑥ (forensic latency report ⑥): skip the semantic layer when the
reasoning stage already produced understanding.

Finding (report §3): on UNSUPPORTED / rejected reasoning turns the pipeline
re-ran a full semantic LLM interpretation of the SAME sentence (1-8s) that
the 30s reasoning stage had already performed.

Pinned invariants:
* interpretation is "already produced" only when the loop ran, the provider
  did not fail, and ``understanding`` is non-empty — every other path
  (provider-down, reasoning-skipped, understanding-less) keeps semantic
  exactly as before (traced: those fall out of the original condition);
* the derived planner prefill carries ONLY traceable literals (amount /
  date / item) and never ``semantic_intent`` — traced consumers: the
  AI_PERCEPTION log and planner.py's whitelist, which falls back to its
  regex intent exactly as existing no-prefill paths do.
"""

from types import SimpleNamespace

from app.agent import _prefill_from_reasoning, _reasoning_produced_interpretation


class TestInterpretationGate:
    def test_requires_ran_loop_with_nonempty_understanding(self):
        assert _reasoning_produced_interpretation(None) is False
        assert (
            _reasoning_produced_interpretation(
                SimpleNamespace(provider_failed=True, understanding={"e": "sale"})
            )
            is False
        )
        assert (
            _reasoning_produced_interpretation(
                SimpleNamespace(provider_failed=False, understanding={})
            )
            is False
        )
        assert (
            _reasoning_produced_interpretation(
                SimpleNamespace(
                    provider_failed=False, understanding={"economic_event": "sale"}
                )
            )
            is True
        )


class TestPrefillFromReasoning:
    def test_only_traceable_literals_never_semantic_intent(self):
        preliminary = {
            "literals": {
                "amount": 150000.0,
                "transaction_date": "2026-09-20",
                "item_description": "laptop",
                "payment_channel": "cash",
                "document_reference": "INV-000005",
            }
        }
        prefill = _prefill_from_reasoning(
            SimpleNamespace(understanding={"economic_event": "sale"}), preliminary
        )
        # Exact whitelist: nothing invented from prose, no semantic_intent.
        assert prefill == {
            "amount": 150000.0,
            "transaction_date": "2026-09-20",
            "item_description": "laptop",
        }
        assert "semantic_intent" not in prefill

    def test_empty_inputs_yield_empty_prefill(self):
        assert _prefill_from_reasoning(None, {}) == {}
        assert (
            _prefill_from_reasoning(
                SimpleNamespace(understanding={"a": 1}), {"literals": {}}
            )
            == {}
        )
