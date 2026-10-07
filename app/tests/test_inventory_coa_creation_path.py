"""The missing INVENTORY ledger must be PROPOSED — and a YES approval must
fold into ``create_account`` even for model-authored questions.

Production (Zameer Labs PVT Ltd, session afcfecae-124e-4baf-bb9a-7873b8bb5cee,
2026-10-07): "We Purchase Two Bikes, for resale on cash today" classified
INVENTORY (PKR 450,000, qty 2) against a 46-account chart with NO inventory
account.  Two defects met:

1. ``preflight_account_gaps`` had no INVENTORY probe (only explicit refs /
   fixed-asset / expense), so the canonical ``question_for_gap`` question was
   never asked — the execution model asked its OWN free-form question instead.
2. A model-authored question cannot satisfy the answer-merge TEXT CONTRACT
   (``no '<name>' account``), so the owner's "1) Yes, Create Inventory
   Account" folded NOTHING: ``entities["create_account"]`` stayed empty, the
   planner never appended the ``create_account`` tool, and the run ended
   informational with zero mutations — "There is no ``create_account`` tool
   available to me."

Pins:
1. the shape-backed Inventory gap is proposed for the purchase family when
   the chart has no inventory ledger (and only then);
2. an existing inventory ledger, a confirmed choice, the nature-probe budget
   flag and a chart read failure all keep the probe silent;
3. a model-authored question + YES folds the approval (answer wording first,
   nature's canonical name second);
4. refusals and bare NOs never become a creation;
5. the canonical contract question still wins when it carries the name;
6. the planner's plan now OFFERS ``create_account`` for the reported request.
"""

import uuid

import pytest

from app.account_resolution import (
    gap_for_nature,
    inventory_gap_from_chart,
    preflight_account_gaps,
    question_for_gap,
)
from app.planner import _merge_clarification_answers, plan

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

# The chart Zameer Labs actually held (assets only, from the session's
# get_chart_of_accounts tool call): no inventory ledger among them.
PRODUCTION_ASSETS = [
    {"name": "Bank", "account_type": "ASSET"},
    {"name": "Cash", "account_type": "ASSET"},
    {"name": "Accounts Receivable", "account_type": "ASSET"},
    {"name": "Prepaid Expenses", "account_type": "ASSET"},
    {"name": "Computer Equipment", "account_type": "ASSET"},
    {"name": "Vehicle - Car", "account_type": "ASSET"},
]

# The model's own clarification as persisted in ai.clarifications — numbered,
# double-quoted, no `no '<name>' account` anywhere.
MODEL_QUESTION = (
    "I need your decision on how to proceed:\n\n"
    "1. Should I create a new inventory account (e.g. \"Inventory\" or "
    "\"Merchandise Inventory\") to record this purchase correctly? This "
    "requires your explicit approval since new accounts need owner sign-off.\n\n"
    "2. Or is there an existing account you want me to use that I may have "
    "missed?"
)
MODEL_ANSWER = "1) Yes, Create Inventory Account\n2) No"


class TestInventoryGapFromChart:
    """The pure chart decision — no I/O, no repository."""

    def test_the_production_chart_proposes_the_gap(self):
        gap = inventory_gap_from_chart(PRODUCTION_ASSETS)
        assert gap is not None
        assert gap.name == "Inventory"
        assert gap.account_type == "ASSET"
        assert gap.base_code == "1200"

    def test_an_existing_inventory_ledger_proposes_nothing(self):
        chart = [*PRODUCTION_ASSETS, {"name": "Merchandise Inventory",
                                      "account_type": "ASSET"}]
        assert inventory_gap_from_chart(chart) is None

    @pytest.mark.parametrize(
        "name",
        ["Inventory", "Stock in Trade", "Finished Goods", "inventory"],
    )
    def test_standard_ledger_wording_satisfies_the_probe(self, name):
        chart = [*PRODUCTION_ASSETS, {"name": name, "account_type": "ASSET"}]
        assert inventory_gap_from_chart(chart) is None

    def test_the_pnl_side_never_satisfies_the_balance_sheet_debit(self):
        # "Cost of Goods Sold" is EXPENSE — it cannot take the inventory
        # debit this nature posts, so the gap must still be proposed.
        chart = [*PRODUCTION_ASSETS,
                 {"name": "Cost of Goods Sold", "account_type": "EXPENSE"}]
        assert inventory_gap_from_chart(chart) is not None

    def test_an_inactive_inventory_ledger_does_not_satisfy_the_probe(self):
        chart = [*PRODUCTION_ASSETS,
                 {"name": "Inventory", "account_type": "ASSET",
                  "is_active": False}]
        assert inventory_gap_from_chart(chart) is not None

    def test_the_proposed_gap_round_trips_through_the_merge_contract(self):
        # The whole point: the question this gap generates must let a YES
        # fold into entities["create_account"].
        q = question_for_gap(inventory_gap_from_chart(PRODUCTION_ASSETS))
        merged = _merge_clarification_answers(
            {}, [{"question": q, "answer": "Yes, create it"}]
        )
        assert merged.get("create_account") == "Inventory"


class TestPreflightInventoryProbe:
    """The gate in ``preflight_account_gaps`` — intent/nature/confirmation."""

    @pytest.fixture
    def chart_calls(self, monkeypatch):
        """Recorder seam for the only DB hop this probe makes."""
        from app.repositories import account_repository as acct_repo

        state = {"calls": 0, "chart": []}

        async def _record(organization_id, **kwargs):
            state["calls"] += 1
            return state["chart"]

        monkeypatch.setattr(acct_repo, "get_chart_of_accounts", _record)
        return state

    @pytest.mark.asyncio
    async def test_a_cash_purchase_with_no_inventory_ledger_proposes_the_gap(
        self, chart_calls
    ):
        chart_calls["chart"] = PRODUCTION_ASSETS
        gaps = await preflight_account_gaps(
            ORG,
            tool_calls=[],
            entities={"transaction_nature": "INVENTORY"},
            intent="record_cash_purchase",
        )
        assert [g.name for g in gaps] == ["Inventory"]
        assert chart_calls["calls"] == 1

    @pytest.mark.asyncio
    async def test_an_existing_inventory_ledger_proposes_nothing(
        self, chart_calls
    ):
        chart_calls["chart"] = [
            *PRODUCTION_ASSETS,
            {"name": "Merchandise Inventory", "account_type": "ASSET"},
        ]
        gaps = await preflight_account_gaps(
            ORG,
            tool_calls=[],
            entities={"transaction_nature": "INVENTORY"},
            intent="record_cash_purchase",
        )
        assert gaps == []

    @pytest.mark.asyncio
    async def test_a_confirmed_choice_suppresses_the_probe(self, chart_calls):
        # create_account: the owner approved a (possibly differently named)
        # creation; account_name: they named an existing ledger.  Either is
        # authoritative — the probe must not ask again.
        for confirmed in ({"create_account": "Inventory"},
                          {"account_name": "Cash"}):
            gaps = await preflight_account_gaps(
                ORG,
                tool_calls=[],
                entities={"transaction_nature": "INVENTORY", **confirmed},
                intent="record_cash_purchase",
            )
            assert gaps == []
        assert chart_calls["calls"] == 0

    @pytest.mark.asyncio
    async def test_a_non_purchase_intent_never_asks(self, chart_calls):
        gaps = await preflight_account_gaps(
            ORG,
            tool_calls=[],
            entities={"transaction_nature": "INVENTORY"},
            intent="record_receipt",
        )
        assert gaps == []
        assert chart_calls["calls"] == 0

    @pytest.mark.asyncio
    async def test_a_non_inventory_nature_never_asks(self, chart_calls):
        gaps = await preflight_account_gaps(
            ORG,
            tool_calls=[],
            entities={"transaction_nature": "OPERATING_EXPENSE"},
            intent="record_cash_purchase",
        )
        assert gaps == []
        assert chart_calls["calls"] == 0

    @pytest.mark.asyncio
    async def test_the_nature_probe_budget_flag_is_respected(
        self, chart_calls
    ):
        # Proposal/approved paths keep their zero-extra-DB budget (P1-⑧).
        gaps = await preflight_account_gaps(
            ORG,
            tool_calls=[],
            entities={"transaction_nature": "INVENTORY"},
            intent="record_cash_purchase",
            include_nature_probes=False,
        )
        assert gaps == []
        assert chart_calls["calls"] == 0

    @pytest.mark.asyncio
    async def test_a_chart_read_failure_fails_open(self, monkeypatch):
        from app.repositories import account_repository as acct_repo

        async def _boom(*args, **kwargs):
            raise RuntimeError("chart unavailable")

        monkeypatch.setattr(acct_repo, "get_chart_of_accounts", _boom)
        gaps = await preflight_account_gaps(
            ORG,
            tool_calls=[],
            entities={"transaction_nature": "INVENTORY"},
            intent="record_cash_purchase",
        )
        assert gaps == []


class TestModelAuthoredApprovalNowFolds:
    """The merge fallback — defect 2 of the reported session."""

    def test_the_production_answer_folds_the_creation(self):
        merged = _merge_clarification_answers(
            {"transaction_nature": "INVENTORY"},
            [{"question": MODEL_QUESTION, "answer": MODEL_ANSWER}],
        )
        assert merged.get("create_account") == "Inventory"
        assert not merged.get("account_name")

    def test_a_bare_yes_falls_back_to_the_nature_name(self):
        merged = _merge_clarification_answers(
            {"transaction_nature": "INVENTORY"},
            [{"question": MODEL_QUESTION, "answer": "Yes"}],
        )
        assert merged.get("create_account") == "Inventory"

    def test_the_answer_can_name_a_different_ledger(self):
        # Numbered like the model's options, so the splitter keeps each part
        # with its own question and the approval half carries the name.
        merged = _merge_clarification_answers(
            {},
            [{"question": MODEL_QUESTION,
              "answer": "1) Yes, Create Merchandise Inventory\n2) No"}],
        )
        assert merged.get("create_account") == "Merchandise Inventory"

    def test_a_refusal_never_creates(self):
        # Single-part reply (no comma for the splitter to pair off): the
        # answer NAMES an existing account instead of approving creation.
        merged = _merge_clarification_answers(
            {"transaction_nature": "INVENTORY"},
            [{"question": MODEL_QUESTION,
              "answer": "use an existing account instead"}],
        )
        assert not merged.get("create_account")
        assert not merged.get("account_name")

    def test_a_no_answer_never_creates(self):
        merged = _merge_clarification_answers(
            {"transaction_nature": "INVENTORY"},
            [{"question": MODEL_QUESTION, "answer": "No"}],
        )
        assert not merged.get("create_account")
        assert not merged.get("account_name")

    def test_without_a_nature_or_a_name_the_gap_stays_open(self):
        # Status quo preserved: nothing is invented when neither the answer
        # nor the entities can name the ledger.
        merged = _merge_clarification_answers(
            {},
            [{"question": MODEL_QUESTION, "answer": "Yes"}],
        )
        assert not merged.get("create_account")

    def test_the_canonical_contract_still_wins_when_the_question_names_it(
        self,
    ):
        # Regex path first: the question's own name ("Office Chairs") beats
        # both fallbacks — the fallback only runs when the regex fails.
        q = question_for_gap(
            gap_for_nature("Office Chairs", "FIXED_ASSET", "t")
        )
        merged = _merge_clarification_answers(
            {"transaction_nature": "INVENTORY"},
            [{"question": q, "answer": "Yes, create it"}],
        )
        assert merged.get("create_account") == "Office Chairs"


class TestPlannerOffersTheTool:
    """End to end: the reported request's plan now carries the tool."""

    def test_the_plan_offers_create_account_after_the_approval(self):
        p = plan(
            "We Purchase Two Bikes, for resale on cash today",
            clarification_history=[
                {"question": MODEL_QUESTION, "answer": MODEL_ANSWER}
            ],
        )
        assert p.extracted_entities.get("create_account") == "Inventory"
        assert "create_account" in p.potential_tools

    def test_without_the_approval_the_tool_is_not_offered(self):
        p = plan("We Purchase Two Bikes, for resale on cash today")
        assert "create_account" not in p.potential_tools



