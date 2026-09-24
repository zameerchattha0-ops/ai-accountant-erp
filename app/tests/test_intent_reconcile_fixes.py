"""RC-1..RC-5 — the production "3 computers" incident fixes (P0/P1/P2).

Root causes pinned here (session ``fda87b21``, 2026-09-24 — "i purchased
3 computers from techno it ltd" -> FAILED with a fabricated party-duplicate
message for a party that never existed):

  FIX-1 (P0)  frozen-plan tools are never self-blocked by the shortlist
  FIX-2 (P0)  accurate, tool-scoped refusal text (no fabricated party story)
  FIX-3 (P1)  ``fixed_asset_capitalization`` maps to its actual tool
  FIX-4a(P1)  classifier provenance is honest (PREFERENCE != USER_ANSWER)
  FIX-4b(P1)  a learned nature preference never answers AT/ABOVE the
              capitalization threshold (the expense-vs-asset question)
  FIX-5 (P1)  intent reconciled with the planned tools before confirmation
  FIX-6 (P2)  fail closed before freezing a plan execution would refuse

Everything here is PURE/unit level; the wired end-to-end flows are pinned
by ``test_computers_capitalization_regression.py``.
"""

import uuid

import pytest

from app.agent import event_prohibited_tools, excluded_tool_refusal, plan_conflict_tools
from app.classifier import classify_transaction
from app.planner import intent_requires_confirmation, plan
from app.reasoning import (
    NATURE_DECISION_QUESTION,
    _ACTION_TOOLS,
    build_event_profile,
    prohibited_tool_names,
)
from app.tool_selector import excluded_for_intent, reconcile_intent_with_tools, tools_for_intent
from app.tools import list_tools
from app.models.schemas import TransactionClassification

ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")


# ---------------------------------------------------------------- FIX-5 ----
class TestReconcileIntentWithTools:
    """The intent follows the PLANNED TOOLS when they uniquely identify one
    other intent — generic, table-driven, never event-specific."""

    def test_incident_shape_switches_to_the_asset_intent(self):
        intent, unpermitted = reconcile_intent_with_tools(
            "record_expense", ["register_fixed_asset"],
            ["create_expense", "classify_expense"],
        )
        assert intent == "register_fixed_asset"
        assert unpermitted == set()

    def test_permitted_tools_never_change_the_intent(self):
        intent, unpermitted = reconcile_intent_with_tools(
            "record_expense", ["create_expense", "classify_expense"],
            ["create_expense", "classify_expense"],
        )
        assert intent == "record_expense"
        assert unpermitted == set()

    def test_lookups_and_journal_helpers_are_universally_exempt(self):
        intent, unpermitted = reconcile_intent_with_tools(
            "record_receipt",
            ["record_customer_receipt", "post_journal", "validate_journal",
             "search_customer", "get_chart_of_accounts", "list_bank_accounts"],
            [],
        )
        assert intent == "record_receipt"
        assert unpermitted == set()

    def test_planner_listed_tools_are_authoritative_no_switch(self):
        # potential_tools (planner) already listed the tool — trust it.
        intent, unpermitted = reconcile_intent_with_tools(
            "record_expense", ["register_fixed_asset"],
            ["register_fixed_asset"],
        )
        assert intent == "record_expense"
        assert unpermitted == set()

    def test_ambiguous_multi_intent_plan_returns_unpermitted(self):
        intent, unpermitted = reconcile_intent_with_tools(
            "record_receipt",
            ["register_fixed_asset", "create_invoice"],
            [],
        )
        # No single intent owns both -> keep the intent, RETURN the tools
        # (never silently executed, never silently dropped).
        assert intent == "record_receipt"
        assert unpermitted == {"register_fixed_asset", "create_invoice"}

    def test_unknown_tool_is_returned_not_reconciled(self):
        intent, unpermitted = reconcile_intent_with_tools(
            "record_expense", ["totally_bogus_tool"], [],
        )
        assert intent == "record_expense"
        assert unpermitted == {"totally_bogus_tool"}

    def test_empty_plan_is_a_noop(self):
        assert reconcile_intent_with_tools("record_expense", [], []) == (
            "record_expense", set(),
        )

    def test_reconciled_intent_reports_tools_outside_itself(self):
        # A switch happens (unique candidate), and the ORIGINAL intent's own
        # mutation tool stays unpermitted under the new intent — returned,
        # never silently executed or dropped.
        intent, unpermitted = reconcile_intent_with_tools(
            "record_receipt",
            ["register_fixed_asset", "record_customer_receipt"],
            [],
        )
        assert intent == "register_fixed_asset"
        assert "record_customer_receipt" in unpermitted
        assert "register_fixed_asset" not in unpermitted

    def test_reconcile_agrees_with_the_shortlist_it_reseeds(self):
        # The tools that survive reconciliation are exactly what the
        # re-seeded shortlist permits — guards can never refuse them.
        intent, unpermitted = reconcile_intent_with_tools(
            "record_expense", ["register_fixed_asset"],
            ["create_expense"],
        )
        allowed = tools_for_intent(intent, ["create_expense"])
        assert {"register_fixed_asset"} - unpermitted <= allowed


# ---------------------------------------------------------------- FIX-2 ----
class TestExcludedToolRefusal:
    """Accurate, tool-scoped refusal text — the incident's core user-facing
    defect was a fabricated party-duplicate story."""

    def test_party_tools_keep_the_historical_wording(self):
        for tool in ("create_supplier", "create_customer"):
            refusal = excluded_tool_refusal(tool, "record_receipt")
            assert refusal["success"] is False
            assert refusal["error_category"] == "BUSINESS_RULE_VIOLATION"
            assert "already found for this party" in refusal["error"]

    def test_non_party_tool_gets_an_honest_refusal(self):
        refusal = excluded_tool_refusal("register_fixed_asset", "record_expense")
        assert refusal["success"] is False
        assert refusal["error_category"] == "BUSINESS_RULE_VIOLATION"
        # names the tool AND the intent, and NEVER tells a party story.
        assert "register_fixed_asset" in refusal["error"]
        assert "'record_expense'" in refusal["error"]
        assert "already found for this party" not in refusal["error"]

    def test_excluded_set_membership_matches_the_guard(self):
        # the guard's precondition: an intent-excluded tool really is absent
        # from the shortlist, while the intent's own tools never are.
        all_tools = list_tools()
        excluded = excluded_for_intent(
            "record_expense", ["create_expense"], all_tools,
        )
        assert "register_fixed_asset" in excluded
        assert "create_expense" not in excluded


# ---------------------------------------------------------------- FIX-3 ----
class TestFixedAssetProhibition:
    """The prohibited ACTION now owns its tool — negative reasoning fires."""

    def test_action_maps_to_the_asset_tool(self):
        assert _ACTION_TOOLS["fixed_asset_capitalization"] == {
            "register_fixed_asset",
        }

    def test_event_prohibited_tools_refuses_capitalisation(self):
        blocked = event_prohibited_tools([{
            "action": "fixed_asset_capitalization",
            "reason": "an ordinary operating expense must NOT be capitalised",
        }])
        assert "register_fixed_asset" in blocked

    def test_expense_profile_prohibits_capitalisation(self):
        cls = TransactionClassification(
            transaction_nature="OPERATING_EXPENSE",
            confidence="HIGH", source="USER_ANSWER",
        )
        profile = build_event_profile("record_expense", classification=cls)
        assert any(
            p.action == "fixed_asset_capitalization" for p in profile.prohibited
        )
        assert "register_fixed_asset" in prohibited_tool_names(profile)

    def test_asset_profile_never_blocks_its_own_tool(self):
        cls = TransactionClassification(
            transaction_nature="FIXED_ASSET",
            confidence="HIGH", source="DETERMINISTIC_RULE",
        )
        profile = build_event_profile("register_fixed_asset", classification=cls)
        assert "register_fixed_asset" not in prohibited_tool_names(profile)

    def test_unknown_nature_blocks_nothing(self):
        profile = build_event_profile("unknown", classification=None)
        assert "register_fixed_asset" not in prohibited_tool_names(profile)


# ------------------------------------------------------- FIX-6 ------------
class TestPlanConflictTools:
    """FIX-6's pure decision: fail closed ONLY when nothing executable
    remains (partial tolerance = today's executor-gate semantics)."""

    _EXPENSE_CAP_BLOCK = [{
        "action": "fixed_asset_capitalization",
        "reason": "an ordinary operating expense/consumable must NOT be "
                  "capitalised as a fixed asset",
    }]

    def test_incident_shape_fails_closed(self):
        blocked = plan_conflict_tools(
            planned_names=["register_fixed_asset"],
            prohibited_actions=self._EXPENSE_CAP_BLOCK,
        )
        assert blocked == {"register_fixed_asset"}

    def test_partial_plan_is_tolerated(self):
        assert plan_conflict_tools(
            planned_names=["create_expense", "register_fixed_asset"],
            prohibited_actions=self._EXPENSE_CAP_BLOCK,
        ) == set()

    def test_unpermitted_only_plan_fails_closed(self):
        assert plan_conflict_tools(
            planned_names=["bogus_tool"],
            prohibited_actions=[],
            unpermitted={"bogus_tool"},
        ) == {"bogus_tool"}

    def test_unpermitted_partial_is_tolerated(self):
        assert plan_conflict_tools(
            planned_names=["create_expense", "bogus_tool"],
            prohibited_actions=[],
            unpermitted={"bogus_tool"},
        ) == set()

    def test_batch_plans_are_never_flagged(self):
        assert plan_conflict_tools(
            planned_names=["register_fixed_asset"],
            prohibited_actions=self._EXPENSE_CAP_BLOCK,
            batch=True,
        ) == set()

    def test_no_prohibitions_no_conflict(self):
        assert plan_conflict_tools(
            planned_names=["register_fixed_asset"], prohibited_actions=[],
        ) == set()

    def test_empty_plan_no_conflict(self):
        assert plan_conflict_tools(
            planned_names=[], prohibited_actions=self._EXPENSE_CAP_BLOCK,
        ) == set()


class TestConfirmationIntentReconciliation:
    """FIX-5's safety net: a reconciled confirmation-class intent always
    re-enables the PHASE 5 gate (never silently executed)."""

    def test_confirmation_class_members(self):
        assert intent_requires_confirmation("register_fixed_asset") is True
        assert intent_requires_confirmation("create_invoice") is True
        assert intent_requires_confirmation("record_receipt") is True

    def test_non_confirmation_members(self):
        assert intent_requires_confirmation("record_expense") is False
        assert intent_requires_confirmation("unknown") is False


# ---------------------------------------------------------------- FIX-4a ---
class TestClassifierProvenance:
    """A learned org preference must never be reported as USER_ANSWER."""

    async def _classify(self, **kw):
        return await classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={"transaction_nature": "OPERATING_EXPENSE",
                      "item_description": "computers"},
            message="i purchased 3 computers",
            resolve_account_hints=False,   # P1-⑧: no DB in this test
            **kw,
        )

    @pytest.mark.asyncio
    async def test_preference_source_is_honest(self):
        result = await self._classify(explicit_nature_source="PREFERENCE")
        assert result.transaction_nature == "OPERATING_EXPENSE"
        assert result.source == "PREFERENCE"          # NOT "USER_ANSWER"
        assert result.requires_clarification is False

    @pytest.mark.asyncio
    async def test_user_answer_source_preserved(self):
        result = await self._classify(explicit_nature_source="USER_ANSWER")
        assert result.source == "USER_ANSWER"

    @pytest.mark.asyncio
    async def test_legacy_default_without_param_unchanged(self):
        # every existing caller (tests + old plan rows) keeps the old label.
        result = await self._classify()
        assert result.source == "USER_ANSWER"

    @pytest.mark.asyncio
    async def test_unknown_provenance_falls_back_safely(self):
        result = await self._classify(explicit_nature_source="semantic_prefill")
        assert result.source == "USER_ANSWER"


# ---------------------------------------------------------------- FIX-4b ---
class TestPreferenceNatureThreshold:
    """A LEARNED nature default may only answer BELOW the capitalization
    threshold; at/above it the expense-vs-asset question must be asked."""

    def test_above_threshold_preference_never_injects(self):
        p = plan(
            "i purchased 3 computers from techno it ltd for Rs.67,000",
            org_preferences={"transaction_nature": "OPERATING_EXPENSE"},
        )
        # the guard fired — not some unrelated intent miss (control below).
        assert p.extracted_entities.get("transaction_nature") in (None, "")
        assert p.transaction_nature in (None, "")
        assert p.transaction_nature_source != "PREFERENCE"
        # and the nature question is genuinely asked again.
        assert "transaction_nature" in p.missing_fields

    def test_below_threshold_preference_still_answers(self):
        # CONTROL: same preference, same intent family, amount under the
        # default 50,000 threshold — legacy injection preserved.
        p = plan(
            "i purchased printer paper for Rs.5,000",
            org_preferences={"transaction_nature": "CONSUMABLE"},
        )
        assert p.extracted_entities["transaction_nature"] == "CONSUMABLE"
        assert p.transaction_nature_source == "PREFERENCE"
        assert "transaction_nature" not in p.missing_fields

    def test_unknown_amount_keeps_legacy_injection(self):
        # no amount in the sentence -> the threshold cannot apply; the
        # legacy behavior (and the archived pin) is preserved.
        p = plan(
            "I purchased a table",
            org_preferences={"transaction_nature": "INVENTORY"},
        )
        assert p.extracted_entities["transaction_nature"] == "INVENTORY"
        assert p.transaction_nature_source == "PREFERENCE"

    def test_explicit_user_nature_still_wins_everywhere(self):
        p = plan(
            "i purchased 3 computers from techno it ltd for Rs.67,000",
            clarification_history=[{
                "question": NATURE_DECISION_QUESTION,
                "answer": "a",          # fixed asset (purchase family)
            }],
            org_preferences={"transaction_nature": "OPERATING_EXPENSE"},
        )
        # a real USER ANSWER always beats the threshold guard.
        assert p.transaction_nature == "FIXED_ASSET"
        assert p.transaction_nature_source == "USER_ANSWER"

