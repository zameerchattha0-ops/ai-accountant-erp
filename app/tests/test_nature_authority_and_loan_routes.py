"""Nature authority + loan routing + merge-poison regression (fixes 1-6).

Verified production root causes pinned here:

* RC-1 (sessions 62bc94c0 / 49775d68): the learned
  ``transaction_nature=FIXED_ASSET`` preference was injected as an answered
  entity, re-routed "shoes"/"60 shoes" to ``register_fixed_asset`` and the
  nature question was never asked.  A learned nature is now a HINT only --
  the first LLM hit / the user's words / an explicit user answer (incl.
  SAME) own the nature.
* RC-2/RC-3 (conv 7f2ca22e): a model-failure summary persisted as a
  clarification question (field ``missing_details``, quoting
  "search_supplier") routed the user's INSTRUCTION "re-route it from
  expenses account" into ``supplier_name``.  Non-entity tags never reach
  the keyword chain and party answers must read like names.
* RC-4/RC-6: borrowings/lendings/repayments had NO vocabulary anywhere --
  they fell to the generic loop (FAILED, 0 tool calls) or leaked to
  ``customer_balance`` ("borrowed" contains "owe") / the sale nature ladder
  ("Received payment for loan repayment").  The understanding stage now
  classifies them (activities + whitelist intent delegation) and the sale
  family only claims requests whose object is actually a sale.
"""

import uuid

import pytest

from app.planner import (
    _SEMANTIC_INTENTS,
    intent_for_message,
    plan,
    text_understanding_gaps,
)
from app.reasoning import NATURE_DECISION_QUESTION, accepted_nature_values
from app.tool_selector import excluded_for_intent, intent_tools

PREF_FIXED_ASSET = {"transaction_nature": "FIXED_ASSET"}

# The exact production phrasings that took the FIXED_ASSET ladder.
PRODUCTION_SHOES = "bought 60 shoes from alpha traders for Rs.12000 cash today"
PRODUCTION_AD = "I want to buy 60 shoes and wear them"

SALE_FAMILY = {"record_sale", "record_cash_sale", "record_credit_sale", "create_invoice"}
LOAN_INTENTS = {"record_loan", "record_loan_repayment"}


# ---------------------------------------------------------------------------
# Fix 1 + 2: nature is never answered by a learned preference; the first
# LLM hit / user words / user answer own it.
# ---------------------------------------------------------------------------
class TestPreferenceNeverAnswersNature:
    @pytest.mark.parametrize(
        "message",
        [PRODUCTION_SHOES, PRODUCTION_AD, "bought 60 shoes"],
    )
    def test_fixed_asset_preference_never_reroutes_or_answers(self, message):
        p = plan(message, org_preferences=PREF_FIXED_ASSET)
        assert p.intent != "register_fixed_asset"
        assert p.transaction_nature != "FIXED_ASSET"
        assert p.transaction_nature_source != "PREFERENCE"
        assert "transaction_nature" in (p.missing_fields or [])

    def test_llm_prefilled_nature_beats_the_preference(self):
        p = plan(
            "I purchased a table for Rs.5,000",
            org_preferences=PREF_FIXED_ASSET,
            prefill_entities={"transaction_nature": "INVENTORY"},
        )
        assert p.transaction_nature == "INVENTORY"
        assert "transaction_nature" not in (p.missing_fields or [])

    def test_llm_prefilled_nature_beats_text_derivation(self):
        # the words say "service" (purchase-family derivation) but the
        # first LLM hit said INVENTORY -- the LLM's classification owns it.
        p = plan(
            "I purchased a service plan for Rs.5,000",
            prefill_entities={"transaction_nature": "INVENTORY"},
        )
        assert p.transaction_nature == "INVENTORY"

    def test_explicit_same_reuses_the_learned_value(self):
        p = plan(
            "I purchased a table for Rs.5,000",
            clarification_history=[{
                "question": NATURE_DECISION_QUESTION,
                "answer": "SAME",
            }],
            org_preferences={"transaction_nature": "INVENTORY"},
        )
        assert p.transaction_nature == "INVENTORY"
        assert p.transaction_nature_source == "USER_ANSWER"

    def test_unresolvable_same_is_never_guessed(self):
        p = plan(
            "I purchased a table for Rs.5,000",
            clarification_history=[{
                "question": NATURE_DECISION_QUESTION,
                "answer": "SAME",
            }],
            org_preferences={},
        )
        assert p.transaction_nature in (None, "")
        assert "transaction_nature" in (p.missing_fields or [])


# ---------------------------------------------------------------------------
# Fix 3: clarification answers may never poison entities with prose.
# ---------------------------------------------------------------------------
# The persisted plan-incomplete card (agent.py "Nothing has been recorded
# yet ... The steps I could prepare were: ..., search_supplier, ...").
FAILURE_CARD_QUESTION = (
    "Nothing has been recorded yet. I could not build the record expense "
    "from the details I have, so there is nothing for you to approve. The "
    "steps I could prepare were: search_account, search_supplier, "
    "create_expense. Please answer: the remaining details"
)
INSTRUCTION_ANSWER = (
    'Create new Account in COA for "Internet Bills" and Record it\'s '
    "Expense Paid"
)
PARTY_GATE_QUESTION = (
    "Party check: no supplier named 'Create new Account in COA' exists "
    "yet. Create 'Create new Account in COA' as a new supplier ledger?"
)


class TestClarificationPoisonNeverRoutes:
    def test_failure_card_answer_never_becomes_an_entity(self):
        p = plan(
            "record expense: internet 5000",
            clarification_history=[{
                "question": FAILURE_CARD_QUESTION,
                "answer": INSTRUCTION_ANSWER,
                "field": "missing_details",
            }],
        )
        ents = p.extracted_entities
        assert ents.get("supplier_name") != INSTRUCTION_ANSWER
        assert ents.get("customer_name") != INSTRUCTION_ANSWER
        assert "Account in COA" not in str(ents.get("supplier_name") or "")

    def test_instruction_answer_never_becomes_the_party(self):
        p = plan(
            "record expense: internet 5000",
            clarification_history=[{
                "question": PARTY_GATE_QUESTION,
                "answer": "re-route it from expenses account",
                "field": "supplier_name",
            }],
        )
        assert p.extracted_entities.get("supplier_name") is None

    def test_instruction_answer_never_confirms_party_creation(self):
        p = plan(
            "record expense: internet 5000",
            clarification_history=[{
                "question": PARTY_GATE_QUESTION,
                "answer": "re-route it from expenses account",
                "field": "supplier_name",
            }],
        )
        assert not p.extracted_entities.get("supplier_create_confirmed")

    def test_typed_party_name_still_merges(self):
        p = plan(
            "record expense: internet 5000",
            clarification_history=[{
                "question": "Who is the supplier?",
                "answer": "Beta Wears Pvt Ltd",
                "field": "supplier_name",
            }],
        )
        assert p.extracted_entities.get("supplier_name") == "Beta Wears Pvt Ltd"

    def test_party_check_pick_still_merges(self):
        p = plan(
            "record expense: internet 5000",
            clarification_history=[{
                "question": PARTY_GATE_QUESTION,
                "answer": "Flash Fibre",
                "field": "supplier_name",
            }],
        )
        assert p.extracted_entities.get("supplier_name") == "Flash Fibre"

    def test_party_check_yes_still_confirms(self):
        p = plan(
            "record expense: internet 5000",
            clarification_history=[{
                "question": PARTY_GATE_QUESTION,
                "answer": "Yes - create 'Flash Fibre'",
                "field": "supplier_name",
            }],
        )
        assert p.extracted_entities.get("supplier_create_confirmed") is True



# ---------------------------------------------------------------------------
# Fix 4/5/6: loan vocabulary, LLM route delegation, and the sale-family
# guard.
# ---------------------------------------------------------------------------
LOAN_PHRASINGS = [
    "borrow loan from mcb bank of 300000",
    "Record a new borrowed loan. Narration: Loan - HBL - Vehicle. Amount: 500000",
    "we have borrowed 250000 from HBL",
    "I need a loan of 150000 from Meezan bank",
    "give a loan of 50000 to my cousin",
    "we lent Ali 40000 last week",
    "I have to pay loan EMI of 50000",
    "paid the 3rd installment of the HBL loan",
    "repaying 20000 of the borrowed amount today",
    "received payment for loan repayment",
    "loan repayment of Rs.15,000 received",
]


class TestLoanRequestsNeverTakeTheWrongFamily:
    @pytest.mark.parametrize("message", LOAN_PHRASINGS)
    def test_keyword_ladder_never_claims_sale_or_customer_balance(self, message):
        intent = intent_for_message(message)
        assert intent not in SALE_FAMILY
        assert intent != "customer_balance"
        assert intent != "record_expense"

    def test_repayment_is_a_settlement_not_a_sale(self):
        p = plan("Received payment for loan repayment")
        assert p.intent == "record_receipt"  # settlement family, not sale
        assert p.intent not in SALE_FAMILY
        joined = "\n".join(p.clarification_questions or []).lower()
        assert "nature of this sale" not in joined
        # the user's own words ("loan repayment") settle the operation via
        # the settlement taxonomy -- never the sale ladder.
        assert p.transaction_nature == "LOAN_OR_SETTLEMENT"

    def test_received_payment_for_a_sale_still_claims_the_sale(self):
        assert (
            intent_for_message("received payment for the sale of 2 chairs")
            == "record_cash_sale"
        )
        assert (
            intent_for_message("received payment for invoice INV-7 of Rs.20,000")
            == "record_cash_sale"
        )

    def test_borrowed_is_not_the_owe_report(self):
        assert (
            intent_for_message("we borrowed 50000 from the bank")
            != "customer_balance"
        )

    def test_owe_phrasing_still_routes_to_the_report(self):
        assert intent_for_message("How much do we owe them?") == "customer_balance"
        assert intent_for_message("how much does ABC owe us") == "customer_balance"


class TestFirstLlmHitOwnsNatureAndRoute:
    @pytest.mark.parametrize(
        "message",
        [
            "borrow loan from mcb bank of 300000",
            "Record a new borrowed loan. Narration: Loan - HBL. Amount: 500000",
            "I have to pay loan EMI of 50000",
        ],
    )
    def test_unclassified_material_requests_open_the_understanding_hit(self, message):
        assert intent_for_message(message) == "unknown"
        assert text_understanding_gaps(message)  # the first LLM hit runs

    def test_report_wording_never_spends_the_call(self):
        assert text_understanding_gaps("show me my loans") == []
        assert text_understanding_gaps("list all loans we have") == []

    def test_whitelisted_intent_delegates_the_route(self):
        p = plan(
            "borrow loan from mcb bank of 300000",
            prefill_entities={"semantic_intent": "record_loan"},
        )
        assert p.intent == "record_loan"
        assert "record_loan" in p.potential_tools
        assert p.requires_confirmation
        # amount + direction (BORROWED) + counterparty (mcb bank) were read
        # from the words; the loan floor asks the schedule terms the request
        # did NOT state, in one round, plus the transaction date.
        assert "loan_direction" not in p.missing_fields
        assert "counterparty" not in p.missing_fields
        assert "first_payment_date" in p.missing_fields
        assert "tenure_months" in p.missing_fields
        assert "frequency" in p.missing_fields
        assert "transaction_date" in p.missing_fields

    def test_repayment_route_delegation(self):
        p = plan(
            "I have to pay loan EMI of 50000",
            prefill_entities={"semantic_intent": "record_loan_repayment"},
        )
        assert p.intent == "record_loan_repayment"
        assert "record_loan_repayment" in p.potential_tools
        assert p.requires_confirmation

    def test_out_of_whitelist_intent_is_ignored(self):
        p = plan(
            "borrow loan from mcb bank of 300000",
            prefill_entities={"semantic_intent": "delete_all_ledgers"},
        )
        assert p.intent == "unknown"

    def test_no_sale_menu_for_a_delegated_loan_route(self):
        p = plan(
            "I have to pay loan EMI of 50000",
            prefill_entities={"semantic_intent": "record_loan_repayment"},
        )
        joined = "\n".join(p.clarification_questions or []).lower()
        assert "nature of this sale" not in joined


class TestLoanVocabularyAndShortlist:
    def test_planner_whitelist_carries_the_loan_intents(self):
        assert LOAN_INTENTS <= set(_SEMANTIC_INTENTS)

    def test_shortlist_offers_the_loan_tools_only(self):
        allowed = intent_tools("record_loan")
        assert {"record_loan", "list_loans", "get_loan_schedule"} <= allowed
        excluded = excluded_for_intent(
            "record_loan", [], ["record_loan", "create_invoice", "create_expense"]
        )
        assert "record_loan" not in excluded
        assert "create_invoice" in excluded
        assert "create_expense" in excluded

    def test_semantic_activities_know_borrowing_lending_repayment(self):
        from app.semantic_contract import ACTIVITIES
        from app.semantic_layer import intent_for_activity

        assert {"borrowing", "lending", "loan_repayment"} <= set(ACTIVITIES)
        assert intent_for_activity("borrowing", None) == "record_loan"
        assert intent_for_activity("lending", None) == "record_loan"
        assert intent_for_activity("loan_repayment", None) == "record_loan_repayment"

    @pytest.mark.asyncio
    async def test_classifier_never_quizzes_a_loan_as_an_item(self):
        from app.classifier import classify_transaction

        classification = await classify_transaction(
            organization_id=uuid.uuid4(),
            intent="record_loan",
            # 'bank' used to surface as the purchase item on loan requests.
            entities={"item_description": "bank", "amount": 300000.0},
            message="borrow loan from mcb bank of 300000",
            resolve_account_hints=False,
        )
        # the agent only asks the 4-way item question when the classifier
        # reports a MATERIAL ambiguity -- a loan has no classifiable item.
        assert classification.requires_clarification is False


# ---------------------------------------------------------------------------
# entity_segregation: the first hit classifies nature and delegates the
# route -- whitelist-validated, never invented.
# ---------------------------------------------------------------------------
class _StubSettings:
    entity_llm_fallback = False
    bounded_understanding_enabled = True
    entity_llm_timeout_seconds = 5.0


class _Orchestrator:
    def __init__(self, payload: str = "", *, boom: bool = False):
        self.payload = payload
        self.boom = boom
        self.calls = []

    async def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("provider down")
        return self.payload


class TestUnderstandingOwnsNatureAndRoute:
    @pytest.mark.asyncio
    async def test_whitelisted_intent_is_surfaced_for_the_planner(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        orch = _Orchestrator('{"intent": "record_loan", "amount": 300000}')
        facts = await entity_segregation.extract_request_facts(
            "borrow loan from mcb bank of 300000",
            orchestrator=orch,
            thinking_off=True,
            intent_values=sorted(_SEMANTIC_INTENTS),
        )
        assert facts.get("semantic_intent") == "record_loan"
        assert facts.get("amount") == 300000.0
        # the prompt offered the planner's own whitelist.
        assert "record_loan" in orch.calls[0]["prompt"]

    @pytest.mark.asyncio
    async def test_invented_intent_is_dropped(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        orch = _Orchestrator('{"intent": "wire_money_to_my_friend"}')
        facts = await entity_segregation.extract_request_facts(
            "borrow loan from mcb bank of 300000",
            orchestrator=orch,
            thinking_off=True,
            intent_values=sorted(_SEMANTIC_INTENTS),
        )
        assert "semantic_intent" not in facts

    @pytest.mark.asyncio
    async def test_full_taxonomy_nature_when_the_route_is_unknown(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        orch = _Orchestrator('{"transaction_nature": "LOAN_OR_SETTLEMENT"}')
        facts = await entity_segregation.extract_request_facts(
            "we received the settlement of the facility",
            orchestrator=orch,
            thinking_off=True,
        )
        assert facts.get("transaction_nature") == "LOAN_OR_SETTLEMENT"

    @pytest.mark.asyncio
    async def test_family_nature_still_scoped_when_the_route_is_known(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        orch = _Orchestrator(
            '{"transaction_nature": "OPERATING_EXPENSE", '
            '"item_description": "tax services"}'
        )
        facts = await entity_segregation.extract_request_facts(
            "Create an Invoice for 45000 against sale of tax services",
            orchestrator=orch,
            thinking_off=True,
            nature_values=accepted_nature_values("create_invoice"),
            intent_values=sorted(_SEMANTIC_INTENTS),
        )
        # a nature outside the intent's family is dropped, never translated.
        assert "transaction_nature" not in facts
        assert facts.get("item_description") == "tax services"
        # a nature outside the intent's family is dropped, never translated.
        assert "transaction_nature" not in facts
        assert facts.get("item_description") == "tax services"


# ---------------------------------------------------------------------------
# The first LLM hit owns loan nature + route AND the stated contract terms.
# A lending phrase ("give a loan") contains a report verb ("give") but is a
# mutation — the read gate must not starve the call, and once it fires the
# model reads loan_direction/counterparty from the words so the second-run
# questionnaire asks only what is genuinely missing (never facts the user gave).
# ---------------------------------------------------------------------------
class TestLoanFirstHitOwnsRouteAndTerms:
    GIVE = "give a loan of 50000 to my cousin"
    READ = "give me the loan balance"

    def test_lending_phrase_opens_the_understanding_hit(self):
        # "give a loan" is a mutation, not a report — the first LLM hit runs.
        assert intent_for_message(self.GIVE) == "unknown"
        assert text_understanding_gaps(self.GIVE)

    def test_a_read_of_a_loan_still_costs_no_call(self):
        assert text_understanding_gaps(self.READ) == []

    @pytest.mark.asyncio
    async def test_first_hit_reads_direction_and_counterparty(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        orch = _Orchestrator(
            '{"intent": "record_loan", "loan_direction": "GIVEN", '
            '"counterparty": "cousin", "amount": 50000}'
        )
        facts = await entity_segregation.extract_request_facts(
            self.GIVE,
            orchestrator=orch,
            thinking_off=True,
            intent_values=sorted(_SEMANTIC_INTENTS),
        )
        assert facts.get("semantic_intent") == "record_loan"
        assert facts.get("loan_direction") == "GIVEN"
        assert facts.get("counterparty") == "cousin"
        assert facts.get("amount") == 50000.0

    @pytest.mark.asyncio
    async def test_direction_the_words_do_not_support_is_dropped(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        # A BORROWED direction on a give-a-loan message is a hallucination.
        orch = _Orchestrator('{"intent": "record_loan", "loan_direction": "BORROWED"}')
        facts = await entity_segregation.extract_request_facts(
            self.GIVE,
            orchestrator=orch,
            thinking_off=True,
            intent_values=sorted(_SEMANTIC_INTENTS),
        )
        assert "loan_direction" not in facts

    def test_floor_asks_only_genuinely_missing_terms(self):
        # Simulate the first-hit facts the agent prefills into the planner.
        facts = {
            "semantic_intent": "record_loan",
            "loan_direction": "GIVEN",
            "counterparty": "cousin",
            "amount": 50000.0,
        }
        p = plan(self.GIVE, prefill_entities=facts)
        assert p.intent == "record_loan"
        # Stated facts are never re-asked…
        assert "loan_direction" not in p.missing_fields
        assert "counterparty" not in p.missing_fields
        assert "amount" not in p.missing_fields
        # …only the genuinely-missing schedule terms are, in one round.
        assert "first_payment_date" in p.missing_fields
        assert "tenure_months" in p.missing_fields
        assert "frequency" in p.missing_fields


# ---------------------------------------------------------------------------
# Expense vs purchase vs settlement — the LLM decides the route, never a
# Python keyword (production 2026-10-14: `paid.*bill` claimed "Paid 3000
# against monthly internet bill of flash fibre" for the payables-settlement
# family, demanded a supplier lookup, and dead-ended the whole app).
# ---------------------------------------------------------------------------

# "paid <amount> ... bill/expense" phrasings that are NEW expenses until the
# understanding stage says otherwise — the keyword ladder must NOT claim them.
NEW_EXPENSE_PAID_NOW = [
    "Paid 3000 for monthly internet.",
    "Paid 3000 against monthly internet bill of flash fibre",
    "Paid 3000 for electricity to Flash Fibre",
    "Paid 5000 for office rent",
    "Paid 2000 for the phone bill",
]

SETTLEMENT_FAMILY = {"record_expense_payment", "record_payment", "record_receipt"}
PURCHASE_FAMILY = {
    "record_purchase", "record_credit_purchase", "record_cash_purchase",
    "create_purchase_bill",
}


class TestPaidBillIsNeverClaimedByPython:
    @pytest.mark.parametrize("message", NEW_EXPENSE_PAID_NOW)
    def test_keyword_ladder_never_claims_a_paid_bill(self, message):
        # Python must NOT decide expense-vs-purchase-vs-settlement: the
        # request stays unclassified and opens the LLM understanding gate.
        intent = intent_for_message(message.lower())
        assert intent not in SETTLEMENT_FAMILY
        assert intent not in PURCHASE_FAMILY
        assert intent != "record_expense"

    @pytest.mark.parametrize("message", NEW_EXPENSE_PAID_NOW)
    def test_understanding_gate_opens_for_the_llm(self, message):
        assert text_understanding_gaps(message)


class TestLlmDelegationCarriesTheRoute:
    """The LLM's identification is carried to its workflow — never dropped
    to ``unknown`` (which would dead-end the decision the model just made)."""

    @pytest.mark.parametrize(
        "delegated,intent",
        [
            ("record_expense", "record_expense"),
            ("record_expense_payment", "record_expense_payment"),
            ("record_payment", "record_payment"),
            ("record_cash_purchase", "record_cash_purchase"),
        ],
    )
    def test_delegated_intent_is_honoured(self, delegated, intent):
        p = plan(
            "Paid 3000 against monthly internet bill of flash fibre",
            prefill_entities={"semantic_intent": delegated},
        )
        assert p.intent == intent
        assert p.intent != "unknown"


class TestSettlementWordingStillClaims:
    @pytest.mark.parametrize(
        "message",
        [
            "settled the bill of 5000",
            "Record expense payment of 3000",
        ],
    )
    def test_unmistakable_settlement_wording_is_deterministic(self, message):
        # Cases C/E: wording that explicitly says "settled"/"expense payment"
        # IS the settlement decision — Python may read the user's own words.
        assert intent_for_message(message.lower()) == "record_expense_payment"


class TestPurchaseRulesIntact:
    @pytest.mark.parametrize(
        "message,entity",
        [
            ("Purchased inventory on credit from ABC Traders", "ABC Traders"),
            ("bought 10 laptops from Techno IT on credit", "Techno IT"),
        ],
    )
    def test_credit_purchase_keeps_supplier_tracking(self, message, entity):
        p = plan(message)
        assert p.intent == "record_credit_purchase"
        # the party is captured as the supplier (not dropped as an expense
        # provider) and the purchase workflow keeps supplier tools.
        assert p.extracted_entities.get("supplier_name") == entity
        tools = set(p.potential_tools)
        assert "create_purchase_bill" in tools
        assert "search_supplier" in tools or "get_supplier" in tools

    def test_unnamed_credit_purchase_asks_for_the_supplier(self):
        p = plan("Purchased inventory on credit")
        assert p.intent == "record_credit_purchase"
        assert "supplier_name" in p.missing_fields


class TestDelegatedExpenseNeedsNoParty:
    def test_expense_route_has_no_supplier_dependency(self):
        p = plan(
            "Paid 3000 for monthly internet",
            prefill_entities={"semantic_intent": "record_expense"},
        )
        assert p.intent == "record_expense"
        assert "supplier_name" not in (p.missing_fields or [])
        # the expense ladder asks purpose + settlement, never a party.
        assert "transaction_purpose" in p.missing_fields


