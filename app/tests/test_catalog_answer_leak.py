"""The 'Yes - add to catalog Sales' account proposal — root cause + fixes.

Observed (production turn): "Create an Invoice for 45000 to Charlie Traders
against the sale of consultancy charges" led to

    Revenue ledger check: nothing is recorded against 'Yes - add to catalog
    Sales' yet. Create a dedicated ledger 'Yes - add to catalog Sales' …

INSPECTION of the path, step by step:

1. the catalog gate was persisted with ``required_fields=["item_description"]``
   (a DECISION question carrying an item tag);
2. the tapped chip "Yes - add to catalog" was therefore stored verbatim as
   ``item_description`` — destroying "consultancy charges";
3. the field-routed merge ``continue``d, so the ``"catalog check:"`` branch
   never set ``catalog_create_confirmed`` either;
4. the next turn's revenue gate derived its label from the destroyed item and
   proposed a ledger named after a button.

Fixes pinned here: decision questions carry a decision tag; a control answer
can never become content; and the revenue chips parse into decision + name.
"""

from app.planner import _merge_clarification_answers, _is_control_answer
from app.planner import _extract_item, plan
from app.services.revenue_ledger_service import stream_label, suggest_ledger_name

REQUEST = "Create an Invoice for 45000 to Charlie Traders against the sale of consultancy charges"
CATALOG_Q = (
    "Catalog check: 'consultancy charges' is not in your service catalog yet. "
    "Add it to the catalog (with the unit prices from this invoice)? Reply YES "
    "to add, or NO to invoice as one-off free-text lines."
)
REVENUE_Q = (
    "Revenue ledger check: nothing is recorded against 'Consultancy Charges' yet. "
    "Create a dedicated ledger 'Consultancy Charges Sales' under 'Revenue' ..."
)


class TestControlAnswersAreNeverContent:
    def test_the_reported_chips_are_control_answers(self):
        assert _is_control_answer("Yes - add to catalog")
        assert _is_control_answer("No - one-off lines only")
        assert _is_control_answer("Create 'Consultancy Charges Sales' under Revenue")
        assert _is_control_answer("Use the existing 'Revenue' account")
        assert not _is_control_answer("consultancy charges")
        assert not _is_control_answer("Yes, audit services for Q1")  # real content

    def test_the_chip_cannot_overwrite_the_stated_item(self):
        merged = _merge_clarification_answers(
            {"item_description": "consultancy charges"},
            [{"question": CATALOG_Q, "answer": "Yes - add to catalog",
              "field": "item_description"}],
        )
        assert merged["item_description"] == "consultancy charges"
        # ... and the DECISION still reaches its own branch
        assert merged["catalog_create_confirmed"] is True

    def test_a_later_control_reply_does_not_replace_content(self):
        merged = _merge_clarification_answers(
            {},
            [{"question": "What item or service is being invoiced?",
              "answer": "No - one-off lines only", "field": "item_description"}],
        )
        assert "item_description" not in merged


class TestRevenueChipsParseInsteadOfStore:
    def test_use_existing_chip_yields_decision_plus_clean_name(self):
        merged = _merge_clarification_answers(
            {"item_description": "consultancy charges"},
            [{"question": REVENUE_Q, "answer": "Use the existing 'Revenue' account"}],
        )
        assert merged["revenue_ledger_decision"] == "USE_EXISTING"
        assert merged["revenue_account_name"] == "Revenue"
        assert "Use the existing" not in merged["revenue_account_name"]

    def test_create_chip_yields_create_with_no_garbage_name(self):
        merged = _merge_clarification_answers(
            {"item_description": "consultancy charges"},
            [{"question": REVENUE_Q,
              "answer": "Create 'Consultancy Charges Sales' under Revenue"}],
        )
        assert merged["revenue_ledger_decision"] == "CREATE"
        assert "revenue_account_name" not in merged


class TestProposedNameComesFromTheRealItem:
    def test_the_request_states_its_item(self):
        assert _extract_item(REQUEST) == "consultancy charges"

    def test_the_label_and_proposal_read_like_an_account(self):
        label = stream_label("consultancy charges")
        assert label and "yes - add to catalog" not in label.lower()
        proposal = suggest_ledger_name(label)
        assert "yes - add" not in proposal.lower()
        assert "consultancy" in proposal.lower()

    def test_the_whole_turn_no_longer_proposes_the_button(self):
        merged = _merge_clarification_answers(
            {"item_description": "consultancy charges"},
            [{"question": CATALOG_Q, "answer": "Yes - add to catalog",
              "field": "item_description"}],
        )
        proposal = suggest_ledger_name(stream_label(merged["item_description"]))
        assert "catalog" not in proposal.lower()
        p = plan(REQUEST)
        assert p.missing_fields is not None
