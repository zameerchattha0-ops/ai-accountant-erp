"""Regression tests for the expense-fix trio.

1. Party capture - a party named in the first query is surfaced as ``party``.
2. Payment-method gating - "Paid" sets settlement_position=PAID_NOW but never
   derives payment_method=CASH.
3. Account-id injection - create_expense receives a resolved account_id.
"""

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
