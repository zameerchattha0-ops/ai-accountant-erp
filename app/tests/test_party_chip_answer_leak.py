"""The party-gate chip "Yes - create 'X'" must never become the party name.

Observed (production turn, invoice INV-000009, 2026-10-04):

    BILL TO: Yes - create 'ABC Autos'

Root cause: the field-routed merge stored the chip VERBATIM into
``customer_name`` (``_merge_field_answer_tail``) and ``continue``d, so the
keyword chain's "party check:" branch never ran — the answer both poisoned
the name AND skipped ``customer_create_confirmed``.

Pins:
1. the chip is recognised as a control answer (including "Create new party");
2. the keyword branch still runs and sets the confirmation flags;
3. the extracted/earlier name survives untouched;
4. a genuine pick from the similar-party list still stores verbatim.
"""

from app.planner import _is_control_answer, _merge_clarification_answers

PARTY_Q = (
    "Party check: no customer named 'ABC Autos' exists yet. "
    "Create 'ABC Autos' as a new customer ledger?"
)
SIMILAR_Q = (
    "Party check: I found similar customers for 'ABC Auto'. "
    "Which one is the real party for this transaction? "
    "(Or create a new party ledger instead.)"
)


class TestChipsAreControlAnswers:
    def test_party_gate_chip_shapes(self):
        assert _is_control_answer("Yes - create 'ABC Autos'")
        assert _is_control_answer("Create new party 'ABC Autos'")
        assert _is_control_answer("No - cancel")

    def test_a_real_party_name_is_content(self):
        assert not _is_control_answer("ABC Autos Trading")
        assert not _is_control_answer("Yes, invoice the whole lot")  # real content


class TestChipNeverBecomesTheName:
    def test_yes_chip_never_overwrites_the_extracted_name(self):
        merged = _merge_clarification_answers(
            {"customer_name": "ABC Autos"},
            [{"question": PARTY_Q, "answer": "Yes - create 'ABC Autos'",
              "field": "customer_name"}],
        )
        assert merged["customer_name"] == "ABC Autos"
        # ... and the keyword branch still recorded the CONFIRMATION
        assert merged.get("customer_create_confirmed") is True
        assert merged.get("supplier_create_confirmed") is True

    def test_create_new_party_chip_never_becomes_the_name(self):
        merged = _merge_clarification_answers(
            {"customer_name": "ABC Autos"},
            [{"question": PARTY_Q, "answer": "Create new party 'ABC Autos'",
              "field": "customer_name"}],
        )
        assert merged["customer_name"] == "ABC Autos"
        assert merged.get("customer_create_confirmed") is True

    def test_chip_cannot_inject_a_name_when_none_was_extracted(self):
        merged = _merge_clarification_answers(
            {},
            [{"question": PARTY_Q, "answer": "Yes - create 'ABC Autos'",
              "field": "customer_name"}],
        )
        assert "customer_name" not in merged
        assert merged.get("customer_create_confirmed") is True

    def test_typed_yes_still_confirms_without_storing_it(self):
        merged = _merge_clarification_answers(
            {"customer_name": "ABC Autos"},
            [{"question": PARTY_Q, "answer": "yes", "field": "customer_name"}],
        )
        assert merged["customer_name"] == "ABC Autos"
        assert merged.get("customer_create_confirmed") is True


class TestGenuinePicksStillStore:
    def test_a_similar_party_pick_is_stored_verbatim(self):
        merged = _merge_clarification_answers(
            {"customer_name": "ABC Auto"},
            [{"question": SIMILAR_Q, "answer": "ABC Autos Trading",
              "field": "customer_name"}],
        )
        assert merged["customer_name"] == "ABC Autos Trading"
