"""Regression tests for the expense-fix trio.

1. Party capture - a party named in the first query is surfaced as ``party``.
2. Payment-method gating - "Paid" sets settlement_position=PAID_NOW but never
   derives payment_method=CASH.
3. Account-id injection - create_expense receives a resolved account_id.
"""

import pytest
from app.planner import _extract_entities, plan


class TestPartyCapture:
    def test_paid_to_party_captures_party(self):
        ents = _extract_entities("Paid to Acme Traders 5000")
        assert ents.get("party") == "Acme Traders"

    def test_payment_to_party_captures_party(self):
        ents = _extract_entities("payment to Zameer Labs")
        assert ents.get("party") == "Zameer Labs"

    def test_received_from_party_captures_party(self):
        ents = _extract_entities("received from Delta Corp")
        assert ents.get("party") == "Delta Corp"

    def test_paid_party_before_amount_captures_party(self):
        ents = _extract_entities("paid Acme Traders 5000")
        assert ents.get("party") == "Acme Traders"

    def test_plan_surfaces_party_on_initial_call(self):
        p = plan("Paid to Acme Traders 5000 for travel expense")
        assert p.extracted_entities.get("party") == "Acme Traders"

    def test_party_does_not_clobber_supplier_or_customer(self):
        ents = _extract_entities("bought laptops from Dell 50000")
        assert ents.get("supplier_name") == "Dell"


class TestPaymentMethodNotDerivedFromPaid:
    def test_paid_sets_settlement_position_not_payment_method(self):
        p = plan("Paid 5000 for travel expense")
        assert p.extracted_entities.get("payment_method") is None
        assert p.extracted_entities.get("settlement_position") == "PAID_NOW"

    def test_paid_now_sets_settlement_position_not_payment_method(self):
        p = plan("Paid now 5000 for travel expense")
        assert p.extracted_entities.get("payment_method") is None
        assert p.extracted_entities.get("settlement_position") == "PAID_NOW"

    def test_settled_now_sets_settlement_position_not_payment_method(self):
        p = plan("Settled now 5000 for travel expense")
        assert p.extracted_entities.get("payment_method") is None
        assert p.extracted_entities.get("settlement_position") == "PAID_NOW"

    def test_will_pay_sets_credit_and_outstanding(self):
        p = plan("will pay 5000 next month for travel expense")
        assert p.extracted_entities.get("payment_method") == "CREDIT"
        assert p.extracted_entities.get("settlement_position") == "OUTSTANDING"

    def test_explicit_cash_still_works(self):
        p = plan("paid 5000 in cash for travel expense")
        assert p.extracted_entities.get("payment_method") == "CASH"

    def test_explicit_bank_still_works(self):
        p = plan("paid 5000 by bank transfer for travel expense")
        assert p.extracted_entities.get("payment_method") == "BANK_TRANSFER"


class TestAccountIdInjection:
    def test_entity_account_id_wins_over_classifier_hint(self):
        from types import SimpleNamespace

        entities = {
            "amount": 5000.0,
            "transaction_date": "2026-01-15",
            "transaction_purpose": "travel",
            "transaction_nature": "OPERATING_EXPENSE",
            "payment_method": "CASH",
            "settlement_position": "PAID_NOW",
            "account_id": "acct-123",
        }
        classification = SimpleNamespace(account_hint_id="acct-456")

        from app.agent import _expense_fast_path_call
        calls = _expense_fast_path_call(entities, classification)
        assert calls is not None
        assert len(calls) == 1
        assert calls[0].tool_name == "create_expense"
        assert calls[0].arguments["account_id"] == "acct-123"

    def test_classifier_hint_used_when_no_entity_account_id(self):
        from types import SimpleNamespace

        entities = {
            "amount": 5000.0,
            "transaction_date": "2026-01-15",
            "transaction_purpose": "travel",
            "transaction_nature": "OPERATING_EXPENSE",
            "payment_method": "CASH",
            "settlement_position": "PAID_NOW",
        }
        classification = SimpleNamespace(account_hint_id="acct-456")

        from app.agent import _expense_fast_path_call
        calls = _expense_fast_path_call(entities, classification)
        assert calls is not None
        assert calls[0].arguments["account_id"] == "acct-456"

    def test_no_account_id_when_neither_source_has_it(self):
        from types import SimpleNamespace

        entities = {
            "amount": 5000.0,
            "transaction_date": "2026-01-15",
            "transaction_purpose": "travel",
            "transaction_nature": "OPERATING_EXPENSE",
            "payment_method": "CASH",
            "settlement_position": "PAID_NOW",
        }
        classification = SimpleNamespace(account_hint_id=None)

        from app.agent import _expense_fast_path_call
        calls = _expense_fast_path_call(entities, classification)
        assert calls is not None
        assert "account_id" not in calls[0].arguments


class TestPaidExpenseClarificationOptions:
    def test_paid_expense_asks_payment_type_cash_vs_bank(self):
        p = plan("Paid 5000 for travel expense")
        assert "payment_type" in p.missing_fields
        assert "settlement_position" not in p.missing_fields
        q_text = " ".join(p.clarification_questions)
        assert "cash" in q_text.lower() and "bank" in q_text.lower()

    @pytest.mark.asyncio
    async def test_authored_questionnaire_for_paid_expense(self):
        import json
        from app.questionnaire import author_questionnaire

        class StubClient:
            async def generate_text_light(self, prompt: str) -> str:
                return json.dumps({
                    "intro": "Please clarify payment channel.",
                    "questions": [{
                        "field": "payment_type",
                        "kind": "choice",
                        "question": "Was the 5000 travel expense paid in cash or through the bank?",
                        "options": [{"value": "CASH", "label": "Cash"}, {"value": "BANK", "label": "Bank transfer"}],
                        "why": "to credit cash or bank ledger"
                    }]
                })

        q = await author_questionnaire(
            client=StubClient(),
            user_request="TRAVEL EXP PAID FOR 5000",
            intent="record_expense",
            missing_fields=["payment_type"],
            entities={"amount": 5000.0, "settlement_position": "PAID_NOW", "item_description": "travel"},
        )
        assert q is not None
        assert not q.is_empty()
        assert q.questions[0].field == "payment_type"
        assert q.questions[0].options == (("CASH", "Cash"), ("BANK", "Bank transfer"))

    def test_field_merge_payment_and_settlement(self):
        from app.planner import _merge_field_answer

        m = {}
        assert _merge_field_answer(m, "payment_type", "BANK")
        assert m["payment_method"] == "BANK_TRANSFER"

        m2 = {}
        assert _merge_field_answer(m2, "settlement_position", "PAID_NOW")
        assert m2["settlement_position"] == "PAID_NOW"

        m3 = {}
        assert _merge_field_answer(m3, "settlement_position", "OUTSTANDING")
        assert m3["settlement_position"] == "OUTSTANDING"
        assert m3["payment_method"] == "CREDIT"
