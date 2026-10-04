"""The count a user WRITES must reach ``quantity`` — not trigger a question.

Reported: "Create an Invoice for ABC Autos for the sale of two motorbikes for
367,000 to be received within default credit limit" produced
``missing_fields = ['quantity', 'transaction_date']`` — so the agent asked
"How many units are you invoicing?" for a count the user had already given.

Root cause: the quantity extractor matched DIGITS only (``_ITEM_QTY_RE``) and
``_extract_item`` KEEPS a written count inside the item it returns
("two motorbikes"), so the count landed in the item DESCRIPTION while
``quantity`` stayed empty.  The bounded-understanding perception call — whose
prompt does say "two -> 2" — was never invoked, because
``text_understanding_gaps`` reports no quantity gap once the item is found.

These tests pin the fix: written counts are read, the count comes OUT of the
description, the digit path is untouched, and a request with NO count still
asks for one.
"""

from app.planner import (
    _ITEM_QTY_RE,
    _extract_item_quantity,
    _split_leading_count,
    plan,
    text_understanding_gaps,
)

REPORTED = (
    "Create an Invoice for ABC Autos for the sale of two motorbikes for "
    "367,000 to be received within default credit limit"
)


def _entities(message: str) -> dict:
    return plan(message).model_dump().get("extracted_entities", {})


def _missing(message: str) -> list:
    return list(plan(message).missing_fields)


class TestReportedRequest:
    def test_the_written_count_becomes_the_quantity(self):
        assert _entities(REPORTED)["quantity"] == 2.0

    def test_the_count_leaves_the_description(self):
        assert _entities(REPORTED)["item_description"] == "motorbikes"

    def test_quantity_is_no_longer_asked(self):
        assert "quantity" not in _missing(REPORTED)

    def test_the_amount_is_untouched(self):
        assert _entities(REPORTED)["amount"] == 367000.0

    def test_the_customer_is_untouched(self):
        assert _entities(REPORTED)["customer_name"] == "ABC Autos"


class TestWrittenCounts:
    def test_the_digit_form_is_unchanged(self):
        message = (
            "Create an invoice for selling 2 ovens to lkj pvt limited for 5000"
        )
        entities = _entities(message)
        assert entities["quantity"] == 2.0
        assert entities["item_description"] == "ovens"
        assert "quantity" not in _missing(message)

    def test_a_couple_of(self):
        assert _entities(
            "Create an invoice for a couple of bikes to Zameer Labs for 100000"
        )["quantity"] == 2.0

    def test_a_dozen(self):
        assert _entities(
            "Create an invoice for selling a dozen pens to ABC Autos for 1200"
        )["quantity"] == 12.0

    def test_a_teen_word_is_never_read_as_its_prefix(self):
        # "seventeen" must not be parsed as "seven" (longest-first alternation).
        assert _extract_item_quantity("sold seventeen bikes", "seventeen bikes") == 17.0

    def test_a_request_with_no_count_still_asks(self):
        # The fix must not invent a quantity out of nothing.
        assert "quantity" in _missing("Create an invoice for ABC Autos for 50000")

    def test_a_number_that_is_not_the_item_count_is_ignored(self):
        # The count only counts when the word after it IS the extracted item.
        assert (
            _extract_item_quantity(
                "Create an invoice for 3 consultants to ABC Autos for "
                "motorbikes at 50000",
                "motorbikes",
            )
            is None
        )


class TestSplitLeadingCount:
    def test_splits_a_written_count(self):
        assert _split_leading_count("two motorbikes") == ("motorbikes", 2.0)

    def test_splits_the_a_couple_of_form(self):
        assert _split_leading_count("a couple of bikes") == ("bikes", 2.0)

    def test_leaves_text_without_a_count_alone(self):
        assert _split_leading_count("motorbikes") == ("motorbikes", None)

    def test_leaves_a_non_count_word_alone(self):
        # "once" is not "one"; a bare non-count must pass straight through.
        assert _split_leading_count("once off service") == (
            "once off service",
            None,
        )


class TestThousandsSeparatorGuard:
    """An AMOUNT must never be chopped into a count.

    "for 367,000 to be received..." used to yield the fragment "000" as a
    count, paired with the trailing clause as its item.
    """

    def test_a_comma_truncated_amount_yields_no_count(self):
        assert list(_ITEM_QTY_RE.finditer("for 367,000 to be received")) == []

    def test_a_plain_count_still_reads(self):
        counts = [m.group("qty") for m in _ITEM_QTY_RE.finditer("selling 2 ovens to lkj")]
        assert counts == ["2"]

    def test_the_reported_amount_and_count_coexist(self):
        # amount still parses; count still comes from the WORD
        entities = plan(
            "Create an Invoice for ABC Autos for the sale of two motorbikes "
            "for 367,000 to be received within default credit limit"
        ).model_dump()["extracted_entities"]
        assert entities["amount"] == 367000.0
        assert entities["quantity"] == 2.0


class TestUnreadCountWordingOpensTheUnderstandingGap:
    """Finding 2: wording the deterministic reader cannot take must reach the
    bounded-understanding call — instead of being re-asked of the user."""

    def test_a_hyphenated_count_is_not_read_as_its_tail(self):
        # "twenty-five" must NOT become 5.
        assert _extract_item_quantity("sold twenty-five bikes", "twenty-five bikes") is None

    def test_a_hyphenated_count_opens_the_quantity_gap(self):
        assert "quantity" in text_understanding_gaps("sold twenty-five bikes to X")

    def test_half_a_dozen_is_not_read_as_twelve(self):
        assert _extract_item_quantity(
            "sold half a dozen pens to X", "half a dozen pens"
        ) is None

    def test_half_a_dozen_opens_the_quantity_gap(self):
        assert "quantity" in text_understanding_gaps("sold half a dozen pens to X")

    def test_a_count_we_did_read_opens_no_gap(self):
        assert "quantity" not in text_understanding_gaps(
            "sale of two motorbikes for 367,000"
        )

    def test_a_request_without_any_count_opens_no_gap(self):
        # A toll on every turn is not acceptable — only unread wording calls.
        assert "quantity" not in text_understanding_gaps(
            "Create an invoice for ABC Autos for 50000"
        )
