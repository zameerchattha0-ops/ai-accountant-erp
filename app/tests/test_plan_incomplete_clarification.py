"""The plan_incomplete clarification loop — pinned fixes.

Three defects made one acquisition cost three (or endless) clarifying rounds:

* ``_missing_fields`` asked the depreciation policy piecemeal: useful life
  first, then — after that answer — the method, then salvage.  The whole
  point of the consolidated questionnaire is ONE round, so all three are
  asked together now.
* ``_merge_field_answer`` returned True even when it had NOT stored
  anything (unparseable life/method/salvage/amount).  The planner then
  believed the field was handled while it was still missing, and the same
  question came back forever.  No-match now returns False — the keyword
  chain gets its say and the gap stays visible.
* the plan-incomplete card printed RAW field names (``useful_life_years,
  depreciation_method …``), which told the user nothing.  It now renders the
  QUESTION_BANK's human text, capped.
"""

import uuid

import pytest

from app.planner import (
    _merge_field_answer,
    _missing_fields,
    human_questions_for_missing,
)
from app.questionnaire import QUESTION_BANK


class TestDepreciationAsksAreConsolidated:
    def test_the_whole_policy_is_asked_in_one_round(self):
        missing = _missing_fields("register_fixed_asset", {})
        # The trio lands together as ONE contiguous block (in policy order) —
        # no drip-feeding across turns.  Other acquisition facts (asset name,
        # payment, amount, date) may surround it; the policy is never split.
        trio = ["useful_life_years", "depreciation_method", "salvage_value"]
        assert all(field in missing for field in trio)
        idx = [missing.index(field) for field in trio]
        assert idx == [idx[0], idx[0] + 1, idx[0] + 2]

    def test_answering_the_life_still_asks_method_and_salvage(self):
        missing = _missing_fields(
            "register_fixed_asset", {"useful_life_years": 5}
        )
        assert "useful_life_years" not in missing
        assert "depreciation_method" in missing
        assert "salvage_value" in missing

    def test_a_complete_policy_is_never_asked_again(self):
        missing = _missing_fields(
            "register_fixed_asset",
            {
                "useful_life_years": 5,
                "depreciation_method": "STRAIGHT_LINE",
                "salvage_value": 0.0,
            },
        )
        assert "useful_life_years" not in missing
        assert "depreciation_method" not in missing
        assert "salvage_value" not in missing

    def test_an_explicit_decline_ends_the_ask(self):
        missing = _missing_fields(
            "register_fixed_asset", {"depreciation_declined": True}
        )
        assert "useful_life_years" not in missing
        assert "depreciation_method" not in missing
        assert "salvage_value" not in missing


class TestFieldAnswerNoMatchIsNotHandled:
    """A swallowed answer kept the same question coming back forever."""

    def test_unparseable_life_is_not_claimed(self):
        merged: dict = {}
        assert _merge_field_answer(merged, "useful_life_years", "soon") is False
        assert "useful_life_years" not in merged

    def test_parseable_life_is_stored(self):
        merged: dict = {}
        assert _merge_field_answer(merged, "useful_life_years", "5") is True
        assert merged["useful_life_years"] == 5

    def test_decline_still_ends_the_life_ask(self):
        merged: dict = {}
        assert (
            _merge_field_answer(merged, "useful_life_years", "none for now")
            is True
        )
        assert merged["depreciation_declined"] is True

    def test_unrecognised_method_is_not_claimed(self):
        merged: dict = {}
        assert _merge_field_answer(merged, "depreciation_method", "quickly") is False
        assert "depreciation_method" not in merged

    @pytest.mark.parametrize(
        "answer,expected",
        [("straight line", "STRAIGHT_LINE"),
         ("reducing balance", "REDUCING_BALANCE"),
         ("a", "STRAIGHT_LINE"), ("b", "REDUCING_BALANCE")],
    )
    def test_known_methods_are_stored(self, answer, expected):
        merged: dict = {}
        assert _merge_field_answer(merged, "depreciation_method", answer) is True
        assert merged["depreciation_method"] == expected

    def test_unparseable_salvage_amount_and_quantity_are_not_claimed(self):
        assert _merge_field_answer({}, "salvage_value", "lots") is False
        assert _merge_field_answer({}, "amount", "some money") is False
        assert _merge_field_answer({}, "quantity", "several") is False

    def test_parseable_values_are_stored(self):
        salvage: dict = {}
        amount: dict = {}
        quantity: dict = {}
        assert _merge_field_answer(salvage, "salvage_value", "0") is True
        assert salvage["salvage_value"] == 0.0
        assert _merge_field_answer(amount, "amount", "150000") is True
        assert amount["amount"] == 150000.0
        assert _merge_field_answer(quantity, "quantity", "3") is True
        assert quantity["quantity"] == 3


class TestHumanQuestionsForMissing:
    def test_renders_the_question_bank_text_not_field_names(self):
        fields = ["useful_life_years", "depreciation_method", "salvage_value"]
        questions = human_questions_for_missing("register_fixed_asset", fields)

        assert len(questions) == 3
        joined = " ".join(questions)
        assert "useful_life_years" not in joined
        assert "depreciation_method" not in joined
        assert "salvage_value" not in joined
        # the same human text the questionnaire shows
        assert QUESTION_BANK["useful_life_years"].question in questions
        assert QUESTION_BANK["depreciation_method"].question in questions

    def test_the_list_is_capped_and_the_count_is_reportable(self):
        fields = [
            "amount", "transaction_date", "customer_name",
            "item_description", "quantity",
        ]
        questions = human_questions_for_missing("create_invoice", fields, limit=3)
        assert len(questions) == 3
        # the caller can report the remainder honestly
        assert len(fields) - len(questions) == 2

    def test_empty_input_is_never_rendered(self):
        assert human_questions_for_missing("register_fixed_asset", []) == []
        assert human_questions_for_missing("register_fixed_asset", None) == []


# ---------------------------------------------------------------------------
# THE POLICY GATE — why "it never asked for depreciation questions".
#
# The completeness card (plan_incomplete) only fires for plans with NO
# financial mutation, so a RESOLVED register_fixed_asset — exactly what the
# R5 fast path builds — used to sail to confirmation with useful life /
# method / salvage unanswered and register_asset silently applied its own
# defaults.  The tables to record the policy all exist (migration 011:
# fixed_assets / asset_depreciation_schedules / asset_transactions); the ask
# was simply never raised on this path.
# ---------------------------------------------------------------------------
_TRIO = ["useful_life_years", "depreciation_method", "salvage_value"]


class _Plan:
    def __init__(self, *, intent="register_fixed_asset", entities=None,
                 missing=None):
        self.intent = intent
        self.extracted_entities = entities or {}
        self.missing_fields = missing


@pytest.mark.asyncio
class TestDepreciationPolicyGate:
    @staticmethod
    async def _stub(monkeypatch):
        import app.agent as agent_mod

        seen: dict = {}

        async def fake_clarification(*, session_id, question,
                                     required_fields=None, **kw):
            seen["question"] = question
            seen["fields"] = required_fields
            return {"question": question}

        async def fake_step(session_id, name, data=None, **kw):
            seen["step"] = (name, data)

        monkeypatch.setattr(agent_mod, "create_clarification", fake_clarification)
        monkeypatch.setattr(agent_mod, "_log_step", fake_step)
        return agent_mod, seen

    async def test_an_unanswered_policy_is_asked_before_confirmation(self, monkeypatch):
        agent_mod, seen = await self._stub(monkeypatch)
        resp = await agent_mod._depreciation_policy_gate(
            session_id=uuid.uuid4(),
            execution_plan=_Plan(missing=list(_TRIO)),
        )
        assert resp is not None
        assert resp.status == agent_mod.ExecutionStatus.AWAITING_CLARIFICATION
        assert resp.required_information == _TRIO
        # human question text, never raw field names
        assert "useful_life_years" not in resp.question
        assert QUESTION_BANK["useful_life_years"].question in resp.question
        assert seen["fields"] == _TRIO
        assert seen["step"][0] == "AWAITING_CLARIFICATION"
        assert seen["step"][1]["source"] == "asset_depreciation_policy"

    async def test_a_complete_policy_never_blocks(self, monkeypatch):
        agent_mod, _ = await self._stub(monkeypatch)
        resp = await agent_mod._depreciation_policy_gate(
            session_id=uuid.uuid4(),
            execution_plan=_Plan(missing=[]),
        )
        assert resp is None

    async def test_an_explicit_decline_never_blocks(self, monkeypatch):
        agent_mod, _ = await self._stub(monkeypatch)
        resp = await agent_mod._depreciation_policy_gate(
            session_id=uuid.uuid4(),
            execution_plan=_Plan(
                entities={"depreciation_declined": True},
                missing=list(_TRIO),
            ),
        )
        assert resp is None

    async def test_other_intents_never_reach_it(self, monkeypatch):
        agent_mod, _ = await self._stub(monkeypatch)
        resp = await agent_mod._depreciation_policy_gate(
            session_id=uuid.uuid4(),
            execution_plan=_Plan(intent="record_expense", missing=list(_TRIO)),
        )
        assert resp is None

    async def test_only_the_depreciation_part_of_a_long_gap_list_is_asked(
        self, monkeypatch
    ):
        agent_mod, seen = await self._stub(monkeypatch)
        resp = await agent_mod._depreciation_policy_gate(
            session_id=uuid.uuid4(),
            execution_plan=_Plan(
                missing=["amount", "salvage_value", "supplier_name"],
            ),
        )
        assert resp is not None
        assert resp.required_information == ["salvage_value"]
