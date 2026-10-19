"""A plain "yes, create it" to the Party-check gate must CONFIRM, never name.

Observed (live E2E, ALPHA TRADERS, 2026-10-19):

    QUESTION: Party check: no supplier named 'ALPHA TRADERS' exists yet.
              Create 'ALPHA TRADERS' as a new supplier ledger?
    ANSWER:   "yes, create it"
    RESULT:   a supplier literally named "yes, create it" was created —
              the field-routed merge stored the reply verbatim because
              ``_is_control_answer`` only knew the formal chips
              ("Yes - ...") and bare "yes", while the first-word ban in
              ``_is_party_name_answer`` has no "yes".

Pins (mirrors test_party_chip_answer_leak):
1. decision-shaped plain replies are control answers;
2. the merge keeps the EXTRACTED name and sets the create-confirmation;
3. genuine names starting with a decision word ("Yes Bank") still pass.
"""
from app.planner import (
    _is_control_answer,
    _is_party_name_answer,
    _merge_clarification_answers,
)

SUPPLIER_Q = (
    "Party check: no supplier named 'ALPHA TRADERS' exists yet. "
    "Create 'ALPHA TRADERS' as a new supplier ledger?"
)
CUSTOMER_Q = (
    "Party check: no customer named 'ABC Autos' exists yet. "
    "Create 'ABC Autos' as a new customer ledger?"
)


class TestPlainAffirmationsAreControlAnswers:
    def test_yes_create_it_is_a_decision_not_content(self):
        assert _is_control_answer("yes, create it")
        assert _is_control_answer("Yes, create it")
        assert _is_control_answer("yes create it")
        assert _is_control_answer("yes please")
        assert _is_control_answer("ok, confirm it")
        assert _is_control_answer("no, dont create")

    def test_decision_words_do_not_swallow_real_names_or_content(self):
        assert not _is_control_answer("Yes Bank")          # a genuine name
        assert not _is_control_answer("Sure Traders")       # a genuine name
        assert not _is_control_answer("Yes, invoice the whole lot")  # content

    def test_party_name_answer_rejects_the_affirmation(self):
        assert not _is_party_name_answer("yes, create it")
        assert _is_party_name_answer("Yes Bank")            # still name-shaped


class TestAffirmationConfirmsInsteadOfNaming:
    def test_supplier_yes_create_it_keeps_the_extracted_name(self):
        merged = _merge_clarification_answers(
            {"supplier_name": "ALPHA TRADERS"},
            [{"question": SUPPLIER_Q, "answer": "yes, create it",
              "field": "supplier_name"}],
        )
        assert merged["supplier_name"] == "ALPHA TRADERS"   # never the reply
        assert merged.get("supplier_create_confirmed") is True

    def test_customer_yes_create_it_keeps_the_extracted_name(self):
        merged = _merge_clarification_answers(
            {"customer_name": "ABC Autos"},
            [{"question": CUSTOMER_Q, "answer": "yes, create it",
              "field": "customer_name"}],
        )
        assert merged["customer_name"] == "ABC Autos"
        assert merged.get("customer_create_confirmed") is True
        # the reply itself must exist NOWHERE as a party name
        assert "yes, create it" not in {
            str(v) for v in merged.values()
            if isinstance(v, str)
        }
