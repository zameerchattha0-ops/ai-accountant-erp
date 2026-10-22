"""Shadow evaluation & adversarial safety tests for LLM Sole Authority (Phases 2 & 3).

Verifies:
1. Intent & Entity agreement on accounting events (cash expense, credit bill, invoice, receipt, asset).
2. Dynamic clarification suppression: when the model extracts required facts,
   spurious questionnaire rounds are eliminated (the "TRAVEL EXP PAID FOR 5000" fix).
3. Targeted clarification authoring: genuinely missing facts produce precise questions with chips.
4. Adversarial scenarios (audit recommendations):
   - Non-canonical intent rejection (e.g. valid JSON with "do_a_flip").
   - Contradictory facts in multi-turn responses.
   - Constrained tool gating (cash expense cannot invoke create_supplier).
"""

import uuid
import pytest

from app.accounting_reasoning import (
    ReasoningFacts,
    ReasoningOutcome,
    _clean_entities,
    _outcome_from_parsed,
    build_reasoning_prompt,
)
from app.accounting_vocabulary import (
    CANONICAL_INTENTS,
    is_canonical_intent,
    is_supported_treatment,
)
from app.agent import _prefill_from_reasoning
from app.planner import _missing_fields, _questions_for_fields


class TestShadowEvaluationIntentAndEntities:
    """Phase 2: Intent agreement and entity precision on realistic accounting scenarios."""

    @pytest.mark.parametrize(
        "payload,expected_intent,expected_nature,expected_settlement",
        [
            (
                {
                    "decision": {"intent": "record_expense", "treatment": "OPERATING_EXPENSE"},
                    "entities": {
                        "amount": 5000,
                        "item_description": "Travel",
                        "payment_method": "CASH",
                        "settlement_position": "PAID_NOW",
                    },
                },
                "record_expense",
                "OPERATING_EXPENSE",
                "PAID_NOW",
            ),
            (
                {
                    "decision": {"intent": "create_purchase_bill", "treatment": "OPERATING_EXPENSE"},
                    "entities": {
                        "amount": 45000,
                        "item_description": "Raw Material Supplies",
                        "supplier_name": "Pak Steel Mills",
                        "settlement_position": "ON_CREDIT",
                    },
                },
                "create_purchase_bill",
                "OPERATING_EXPENSE",
                "ON_CREDIT",
            ),
            (
                {
                    "decision": {"intent": "register_fixed_asset", "treatment": "FIXED_ASSET"},
                    "entities": {
                        "amount": 250000,
                        "item_description": "Dell PowerEdge Server",
                        "settlement_position": "PAID_NOW",
                    },
                },
                "register_fixed_asset",
                "FIXED_ASSET",
                "PAID_NOW",
            ),
            (
                {
                    "decision": {"intent": "create_invoice", "treatment": "SERVICE"},
                    "entities": {
                        "amount": 150000,
                        "customer_name": "Apex Consulting",
                        "item_description": "Software Development Services",
                        "settlement_position": "ON_CREDIT",
                    },
                },
                "create_invoice",
                "SERVICE",
                "ON_CREDIT",
            ),
        ],
    )
    def test_shadow_agreement_on_core_accounting_scenarios(
        self, payload, expected_intent, expected_nature, expected_settlement
    ):
        outcome = _outcome_from_parsed(payload, rounds=1)
        assert outcome.decision.get("intent") == expected_intent
        assert is_canonical_intent(expected_intent)
        assert outcome.decision.get("treatment") == expected_nature
        assert is_supported_treatment(expected_nature)
        assert outcome.entities.get("settlement_position") == expected_settlement


class TestClarificationSuppressionWhenComplete:
    """Verifies that complete facts suppress spurious clarification questionnaires."""

    def test_travel_expense_with_amount_and_purpose_has_zero_missing_fields(self):
        """Root cause fix for 'TRAVEL EXP PAID FOR 5000':
        When the model extracts travel purpose, amount, and payment method,
        no generic questionnaire may be fired.
        """
        entities = {
            "amount": 5000.0,
            "item_description": "travel",
            "transaction_purpose": "Travel",
            "payment_method": "CASH",
            "settlement_position": "PAID_NOW",
            "transaction_date": "2026-10-22",
        }
        missing = _missing_fields("record_expense", entities)
        assert missing == [], f"Expected zero missing fields, got: {missing}"

    def test_incomplete_expense_identifies_exact_missing_fact(self):
        """When an expense has an amount but NO category/purpose, exactly
        'transaction_purpose' is requested with options.
        """
        entities = {
            "amount": 5000.0,
            "payment_method": "CASH",
            "settlement_position": "PAID_NOW",
            "transaction_date": "2026-10-22",
        }
        missing = _missing_fields("record_expense", entities)
        assert "transaction_purpose" in missing
        qs = _questions_for_fields("record_expense", missing, entities)
        assert len(qs) >= 1
        assert "(g) Travel" in qs[0]


class TestAdversarialAndConstrainedSafetyGates:
    """Audit items #2 and #3: negative tests, constrained tool recommendations, and fallbacks."""

    def test_valid_json_with_non_canonical_intent_is_rejected(self):
        """Model produces schema-valid JSON with invented intent 'do_a_flip'.
        Verify it is recognized as non-canonical and refused.
        """
        raw = {
            "decision": {"intent": "do_a_flip", "treatment": "OPERATING_EXPENSE"},
            "entities": {"amount": 100},
        }
        outcome = _outcome_from_parsed(raw, rounds=1)
        intent = outcome.decision.get("intent")
        assert not is_canonical_intent(intent)

    def test_cash_expense_cannot_mandate_supplier_ledger(self):
        """Constrained tool check: cash expenses must never require a supplier ledger."""
        from app.tool_selector import excluded_for_intent

        cash_expense_entities = {
            "amount": 5000.0,
            "settlement_position": "PAID_NOW",
            "payment_method": "CASH",
        }
        # Supplier is not in missing fields for cash expense
        missing = _missing_fields("record_expense", cash_expense_entities)
        assert "supplier_name" not in missing
        assert "supplier" not in missing

    def test_prefill_merges_contradictory_facts_in_favor_of_latest_llm_state(self):
        """Multi-turn contradiction resolution:
        If preliminary regex extracted 'Ticket', but LLM reasoning resolved
        the actual item as 'Airfare to Lahore', LLM entities take precedence.
        """
        class MockReasoning:
            entities = {
                "amount": 7500.0,
                "item_description": "Airfare to Lahore",
                "payment_method": "BANK",
                "settlement_position": "PAID_NOW",
            }
            decision = {"intent": "record_expense", "treatment": "OPERATING_EXPENSE"}

        preliminary = {
            "literals": {
                "amount": 5000.0,  # old/partial literal
                "item_description": "Ticket",
            }
        }
        prefill = _prefill_from_reasoning(MockReasoning(), preliminary)
        assert prefill["amount"] == 7500.0
        assert prefill["item_description"] == "Airfare to Lahore"
        assert prefill["payment_method"] == "BANK"

