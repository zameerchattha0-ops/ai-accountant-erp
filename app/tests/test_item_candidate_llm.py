"""Item-candidate ownership: the first LLM hit proposes the REAL product.

Production 2026-10-14: ``create invoice for zeta pvt ltd for selling them 2
laptops`` produced revenue stream ``them Sales``.  Three defects compounded:
the sale-verb pattern captured the pronoun ("them"), the ``invoice for …``
pattern captured the CUSTOMER ("zeta pvt ltd") as the item, and — because
the regex "found" an item — the bounded understanding call was never made,
so nothing could correct it.  The fix layers:

1. ``_extract_item`` drops pronoun captures (party-plausibility guard) and
   PARTY ECHOES (a capture that IS the message's counterparty).
2. The opened ``item_description`` gap fires the bounded understanding call,
   whose prompt now defines an item (product/service — never a party, never
   a pronoun) and whose grounding rejects generic items and party echoes.
3. ``plan(prefill_entities=…)`` honours the grounded proposal, so the
   revenue ledger names the product ("Laptops Sales").
"""

import pytest

from app.entity_segregation import _ground_fields, _SYSTEM_PROMPT
from app.planner import _extract_item, plan, text_understanding_gaps

MSG = "create invoice for zeta pvt ltd for selling them 2 laptops"


class TestRegexItemNeverAPronounOrParty:
    """The deterministic extractor drops pronouns and party echoes."""

    def test_the_pronoun_is_never_the_item(self):
        assert _extract_item("create an invoice for selling them 2 laptops") is None

    def test_the_customer_is_never_the_item(self):
        # The "invoice for <item>" pattern used to capture "zeta pvt ltd",
        # which then named the revenue stream after the PARTY.
        assert _extract_item(MSG) is None

    def test_a_genuine_product_still_extracts(self):
        assert _extract_item("sold 2 ovens to Zeta Pvt Ltd") == "ovens"
        assert _extract_item("bought chairs") == "chairs"
        assert _extract_item("procured 5 laptops from Dell") == "laptops"

    def test_the_party_itself_still_extracts(self):
        p = plan(MSG)
        assert p.extracted_entities.get("customer_name") == "zeta pvt ltd"

    def test_the_missing_item_opens_the_understanding_gap(self):
        assert "item_description" in text_understanding_gaps(MSG)


class TestGroundingRejectsBadItemCandidates:
    """The understanding call's grounding keeps only a real product."""

    @staticmethod
    def _ground(parsed):
        return _ground_fields(
            parsed,
            "create invoice for zeta pvt ltd for selling them 2 laptops",
            "create invoice for zeta pvt ltd for selling them 2 laptops",
            None,
        )

    def test_a_pronoun_candidate_is_dropped(self):
        assert "item_description" not in self._ground({"item_description": "them"})

    def test_a_party_echo_candidate_is_dropped(self):
        grounded = self._ground({
            "customer_name": "zeta pvt ltd",
            "item_description": "zeta pvt ltd",
        })
        assert "item_description" not in grounded

    def test_the_real_product_is_kept(self):
        grounded = self._ground({
            "customer_name": "zeta pvt ltd",
            "item_description": "laptops",
            "item_quantity": 2,
        })
        assert grounded["item_description"] == "laptops"
        assert grounded["item_quantity"] == 2.0


class TestThePromptDefinesAnItem:
    def test_the_rule_forbids_parties_and_pronouns(self):
        assert "laptops" in _SYSTEM_PROMPT
        assert "NEVER a person or company name" in _SYSTEM_PROMPT
        assert "NEVER a pronoun" in _SYSTEM_PROMPT


class TestThePlanHonoursTheGroundedProposal:
    def test_the_real_product_reaches_the_plan(self):
        p = plan(MSG, prefill_entities={
            "customer_name": "zeta pvt ltd",
            "item_description": "laptops",
            "item_quantity": 2.0,
        })
        assert p.extracted_entities["item_description"] == "laptops"
        assert p.extracted_entities["quantity"] == 2.0

    def test_the_item_question_is_not_reasked(self):
        p = plan(MSG, prefill_entities={
            "item_description": "laptops",
            "item_quantity": 2.0,
        })
        assert "item_description" not in p.missing_fields
        assert not any(
            "item or service" in q.lower() for q in p.clarification_questions
        )

    def test_without_the_proposal_the_item_is_asked_not_invented(self):
        p = plan(MSG)
        assert "item_description" in p.missing_fields
        assert p.extracted_entities.get("item_description") in (None, "")
