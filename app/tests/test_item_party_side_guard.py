"""The SOURCE/CUSTOMER side of a verb phrase must never become the item.

Observed (AES production, 2026-10-07):

    "bought from Dell"                          -> item_description "Dell"
    "Sold to Murkez Technologies pvt Limited"   -> item_description
                                                   "Murkez Technologies pvt Limited"

Root cause: the verb patterns captured from the first ``\\w`` after the
verb, so the preposition started the capture (``from Dell`` / ``to Murkez``);
``_extract_item``'s leading-preposition strip then removed ``from ``/``to ``
and the SUPPLIER/CUSTOMER was stored as ``item_description``.  From there
the product, catalog and revenue gates all named the PARTY as the item.

The fix: a standalone ``to``/``from`` right after the purchase/sale verb
means the sentence states no object — capture nothing, so the planner
ASKS for the item instead of guessing the party.

Pins:
1. a bare "bought/sold from|to X" extracts NO item and opens the
   ``item_description`` gap (the question is asked);
2. the party itself still extracts on both intents;
3. a real object before the preposition still extracts (no regression);
4. an item at end-of-string keeps its trailing "s" (``\\s*$``, not ``s*$``).
"""

from app.planner import _extract_item, plan, text_understanding_gaps


def _entities(message: str) -> dict:
    return plan(message).model_dump().get("extracted_entities", {})


class TestSourceSideIsNeverTheItem:
    """Fix 1 — the purchase verb must not capture its SOURCE."""

    def test_bought_from_supplier_extracts_no_item(self):
        assert _extract_item("bought from Dell") is None

    def test_purchased_from_supplier_extracts_no_item(self):
        assert _extract_item("purchased from Dell") is None

    def test_the_missing_item_is_asked_not_guessed(self):
        assert "item_description" in text_understanding_gaps("bought from Dell")

    def test_the_supplier_still_extracts(self):
        assert _entities("bought from Dell").get("supplier_name") == "Dell"

    def test_the_item_is_not_prefilled_from_the_party(self):
        assert _entities("bought from Dell").get("item_description") is None


class TestCustomerSideIsNeverTheItem:
    """Fix 2 — the sale verb must not capture its CUSTOMER."""

    def test_sold_to_customer_extracts_no_item(self):
        assert (
            _extract_item("Sold to Murkez Technologies pvt Limited") is None
        )

    def test_sold_to_bare_party_extracts_no_item(self):
        assert _extract_item("sold to Zameer Labs") is None

    def test_the_missing_item_is_asked_not_guessed(self):
        assert (
            "item_description"
            in text_understanding_gaps("Sold to Murkez Technologies pvt Limited")
        )

    def test_the_customer_still_extracts(self):
        assert (
            _entities("Sold to Murkez Technologies pvt Limited").get(
                "customer_name"
            )
            == "Murkez Technologies pvt Limited"
        )

    def test_the_item_is_not_prefilled_from_the_party(self):
        assert (
            _entities("Sold to Murkez Technologies pvt Limited").get(
                "item_description"
            )
            is None
        )


class TestAStatedObjectStillExtracts:
    """The guard must only fire when the sentence states NO object."""

    def test_object_before_from_still_extracts(self):
        assert _extract_item("purchased a chair from Dell") == "chair"

    def test_object_before_to_still_extracts(self):
        assert _extract_item("sold chairs to Alpha Associates") == "chairs"

    def test_a_counted_object_before_from_still_extracts(self):
        assert _extract_item("procured 5 laptops from Dell") == "laptops"

    def test_the_noun_phrasing_is_untouched(self):
        assert _extract_item("purchase of laptops from Dell") == "laptops"

    def test_the_end_to_end_sale_still_names_the_item(self):
        entities = _entities(
            "sold chairs to Alpha Associates for 34000"
        )
        assert entities["item_description"] == "chairs"
        assert entities["customer_name"] == "Alpha Associates"
        assert entities["amount"] == 34000.0


class TestTrailingSAtEndOfStringSurvives:
    """The lookahead terminator is ``\\s*$`` — rewriting it to ``s*$``
    makes the lazy capture stop one letter early on any item ending in
    "s" at end-of-string ("bought chairs" -> "chair")."""

    def test_bought_chairs_keeps_its_trailing_s(self):
        assert _extract_item("bought chairs") == "chairs"

    def test_sold_ovens_to_a_party_keeps_its_trailing_s(self):
        assert _extract_item("sold ovens to X") == "ovens"
