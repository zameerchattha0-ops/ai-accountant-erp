"""Nature from the user's OWN words — wording and typo tolerant.

The intent family's keyword rules existed but were only used to interpret an
ANSWER, so a request that SAID its nature still got asked:

    "Create an Invoice for 45000 against sale of tax services to Beta Traders"
    → "What is the nature of this sale: (a) GOODS (b) SERVICE …?"

These tests pin the fix: the request text is read with the SAME rules (one
source of truth), typos included, and the item is captured from noun phrasing
("sale OF tax services") that the verb-only patterns missed.
"""

import pytest

from app.account_resolution import category_for_item
from app.classifier import INVENTORY, SERVICE as SERVICE_NATURE
from app.classifier import rule_based_nature
from app.planner import _extract_item, plan
from app.reasoning import (
    derive_nature_from_text,
    fuzzy_word_match,
    nature_keyword_vocabulary,
)


class TestDeriveNatureFromText:
    def test_the_reported_request_is_answered_by_its_own_words(self):
        assert (
            derive_nature_from_text(
                "create_invoice",
                "Create an Invoice for 45000 against sale of tax services "
                "to Beta Traders",
            )
            == "SERVICE"
        )

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("sale of tax servcies", "SERVICE"),          # transposed letters
            ("sale of servies", "SERVICE"),               # missing letter
            ("invoice for invetory stock", "GOODS"),      # typo + stock
            ("sold goods to X", "GOODS"),
            ("sale of other income commission", "OTHER_INCOME"),
            ("disposal of an old asset", "ASSET_DISPOSAL"),
        ],
    )
    def test_sale_family_wording_and_typos(self, text, expected):
        assert derive_nature_from_text("create_invoice", text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("purchased inventory for resale", "INVENTORY"),
            ("purchased invetory for resale", "INVENTORY"),
            ("paid for consultancy services", "SERVICE"),
            ("paid for consultany servcies", "SERVICE"),
            ("bought machinery to capitalise", "FIXED_ASSET"),
        ],
    )
    def test_purchase_family_wording_and_typos(self, text, expected):
        assert derive_nature_from_text("record_purchase", text) == expected

    def test_silence_stays_silent(self):
        """No nature word ⇒ None ⇒ the question is still asked, never guessed."""
        assert (
            derive_nature_from_text(
                "create_invoice", "create an invoice for 45000 to Beta Traders"
            )
            is None
        )
        assert derive_nature_from_text("create_invoice", "") is None
        # an intent with no nature family never invents one
        assert derive_nature_from_text("record_bank_transfer", "moved 50000") is None


class TestFuzzyGuard:
    def test_typos_resolve_and_unrelated_words_do_not(self):
        sale_vocabulary = nature_keyword_vocabulary("create_invoice")
        purchase_vocabulary = nature_keyword_vocabulary("record_purchase")
        assert fuzzy_word_match("servcies", sale_vocabulary) == "service"
        assert fuzzy_word_match("invetory", purchase_vocabulary) == "inventory"
        # tiny words are never fuzzy-matched, and unrelated words stay None
        assert fuzzy_word_match("item", sale_vocabulary) is None
        assert fuzzy_word_match("banana", sale_vocabulary) is None


class TestPlannerUsesTheRequestWording:
    def test_nature_and_item_questions_disappear(self):
        p = plan(
            "Create an Invoice for 45000 against sale of tax services "
            "to Beta Traders"
        )
        assert p.transaction_nature == "SERVICE"
        assert p.transaction_nature_source == "TEXT_INFERENCE"
        # the nature and the item are ANSWERED — no question for either
        assert "transaction_nature" not in (p.missing_fields or [])
        assert "item_description" not in (p.missing_fields or [])
        assert not any(
            "nature of this sale" in q.lower()
            for q in (p.clarification_questions or [])
        )
        assert not any(
            "what item or service is being invoiced" in q.lower()
            for q in (p.clarification_questions or [])
        )

    def test_the_typo_variant_behaves_identically(self):
        p = plan(
            "Create an invoice for 45000 against sale of tax servcies "
            "to Beta Traders"
        )
        assert p.transaction_nature == "SERVICE"
        assert "transaction_nature" not in (p.missing_fields or [])


class TestItemNounPhrasing:
    @pytest.mark.parametrize(
        "message,expected",
        [
            (
                "Create an Invoice for 45000 against sale of tax services "
                "to Beta Traders",
                "tax services",
            ),
            ("supply of cement to Khan Traders", "cement"),
            ("purchase of laptops from Dell", "laptops"),
            ("invoice for inventory stock of 50000 to X", "inventory stock"),
            ("sold 2 ovens to ljk pvt limited", "ovens"),
        ],
    )
    def test_noun_phrasing_is_captured(self, message, expected):
        assert _extract_item(message) == expected

    def test_an_amount_is_never_mistaken_for_the_item(self):
        assert _extract_item("Create an Invoice for 45000 to Beta Traders") is None


class TestCategoryAndClassifierTypoParity:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("a new vehcile", "Vehicles"),
            ("a new vehicle", "Vehicles"),
            ("3 lapotps", "Computer Equipment"),
            ("office chari", "Furniture & Fixtures"),
        ],
    )
    def test_category_survives_the_typo(self, text, expected):
        assert category_for_item(text) == expected

    def test_unrelated_text_stays_in_the_generic_bucket(self):
        assert category_for_item("somethign random") == "Other Equipment & Fixtures"

    def test_classifier_typo_prints_the_expected_nature(self):
        # a durable good stays materially ambiguous — typo or not
        assert rule_based_nature("vehcile", {}) == rule_based_nature("vehicle", {})
        assert rule_based_nature("invetory", {})[0] == INVENTORY
        assert rule_based_nature("consultancy", {})[0] == SERVICE_NATURE
