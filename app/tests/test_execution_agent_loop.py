"""Execution-agent loop: resolve-or-create account pattern (any activity).

Incident (2026-09-25 screenshot-2): a confirmed register_fixed_asset plan
died DEEP in execution — "No fixed-asset account could be determined for
this acquisition. Specify the asset account (or add one to the chart of
accounts, e.g. 'Computer Equipment')" — because account-hint/config-gap
resolution is skipped on proposal/approved paths (P1-⑧).  This suite pins
the generic loop instead of a per-activity template:

* PRE-FLIGHT (agent PHASE 4c): planned calls' account REQUIREMENTS and
  NAME references resolve against the live chart before confirmation;
  a missing ledger → the account-creation clarification.
* TEXT CONTRACT: the question satisfies the existing answer-merge
  ("should i create" + ``no '<name>' account`` → entities["create_account"]).
* CLASSIFIER: a confirmed creation classifies for EVERY intent family
  (create_account_confirmed + proposed name/code, USER_ANSWER).
* SHORTLIST: create_account is offerable for every intent when planned.
* RESCUE: account-DETERMINATION execution failures become the same
  clarification — one-shot, never re-running a posted mutation.
* ORDERING: the confirmed create_account executes FIRST.
"""

import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.planner as planner_mod
from app.account_resolution import (
    collect_account_refs,
    ensure_create_account_first,
    gap_already_asked,
    gap_for_nature,
    gap_from_execution_failure,
    is_account_resolution_error,
    options_for_gap,
    question_for_gap,
)
from app.models.schemas import ExecutionStatus, ToolCall

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

FIXED_ASSET_ERROR = (
    "No fixed-asset account could be determined for this acquisition. "
    "Specify the asset account (or add one to the chart of accounts, "
    "e.g. 'Computer Equipment')."
)


def _asset_gap():
    return gap_for_nature("Office Chairs", "FIXED_ASSET", "fixed_asset_nature")


class TestQuestionContract:
    def test_question_satisfies_planner_answer_merge(self):
        q = question_for_gap(_asset_gap())
        assert "should i create" in q.lower()
        m = re.search(r"no '(.+?)' account", q)
        assert m is not None, q
        assert m.group(1) == "Office Chairs"

    def test_yes_option_is_first_and_tappable(self):
        opts = options_for_gap(_asset_gap())
        assert opts[0].lower().startswith("yes")
        assert opts[1].lower().startswith("use")

    def test_apostrophe_names_stay_extractable(self):
        q = question_for_gap(gap_for_nature("Chair's", "FIXED_ASSET", "t"))
        m = re.search(r"no '(.+?)' account", q)
        assert m is not None and "'" not in m.group(1)

    def test_ambiguous_candidates_listed_without_breaking_contract(self):
        gap = _asset_gap()
        gap.candidates = ["Furniture", "Equipment"]
        q = question_for_gap(gap)
        assert "'Furniture'" in q and "'Equipment'" in q
        assert re.search(r"no '(.+?)' account", q).group(1) == "Office Chairs"

    def test_gap_already_asked_one_shot_guard(self):
        assert gap_already_asked([{"question": question_for_gap(_asset_gap())}])
        assert not gap_already_asked([{"question": "What is the transaction date?"}])
        # the legacy config-gap question (no quoted name) is NOT this contract
        assert not gap_already_asked(
            [{"question": "There is no fixed asset account. Should I create one?"}]
        )


class TestAnswerMergeRoundTrip:
    """Our question + user answer → entities the loop continues on."""

    def test_yes_folds_confirmed_name(self):
        q = question_for_gap(_asset_gap())
        merged = planner_mod._merge_clarification_answers(
            {}, [{"question": q, "answer": "Yes, create it"}]
        )
        assert merged.get("create_account") == "Office Chairs"

    def test_named_existing_account_instead(self):
        q = question_for_gap(_asset_gap())
        merged = planner_mod._merge_clarification_answers(
            {}, [{"question": q, "answer": "use Furniture"}]
        )
        assert merged.get("account_name") == "furniture"
        assert not merged.get("create_account")


class TestClassifierConfirmedCreation:
    """entities['create_account'] classifies for EVERY intent family."""

    @pytest.mark.asyncio
    async def test_missing_account_marks_confirmed_for_asset_intent(self, monkeypatch):
        from app import account_resolution, classifier

        async def _missing(org, name):
            return None

        async def _code(org, nature, name):
            return "1500"

        monkeypatch.setattr(account_resolution, "account_exists", _missing)
        monkeypatch.setattr(classifier, "_confirmed_account_code", _code)

        res = await classifier.classify_transaction(
            organization_id=ORG,
            intent="register_fixed_asset",
            entities={
                "create_account": "Office Chairs",
                "item_description": "office chairs",
            },
            resolve_account_hints=False,
        )
        assert res.create_account_confirmed is True
        assert res.proposed_account_name == "Office Chairs"
        assert res.proposed_account_code == "1500"
        assert res.transaction_nature == "FIXED_ASSET"
        assert res.source == "USER_ANSWER"
        assert res.requires_clarification is False

    @pytest.mark.asyncio
    async def test_existing_confirmed_name_degrades_to_hint(self, monkeypatch):
        from app import account_resolution, classifier

        async def _exists(org, name):
            return {"id": str(ORG), "code": "1500", "name": "Office Chairs"}

        async def _boom(org, nature, name):  # pragma: no cover — must not run
            raise AssertionError("code helper must not run for an existing name")

        monkeypatch.setattr(account_resolution, "account_exists", _exists)
        monkeypatch.setattr(classifier, "_confirmed_account_code", _boom)

        res = await classifier.classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={"create_account": "Office Chairs"},
            resolve_account_hints=False,
        )
        assert res.create_account_confirmed is False
        assert res.account_hint_code == "1500"
        assert res.transaction_nature is None or res.transaction_nature == "OPERATING_EXPENSE"

    @pytest.mark.asyncio
    async def test_confirmed_creation_for_expense_intent(self, monkeypatch):
        from app import account_resolution, classifier

        async def _missing(org, name):
            return None

        async def _code(org, nature, name):
            return "6130"

        monkeypatch.setattr(account_resolution, "account_exists", _missing)
        monkeypatch.setattr(classifier, "_confirmed_account_code", _code)

        res = await classifier.classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={"create_account": "Utilities Expense"},
            resolve_account_hints=False,
        )
        assert res.create_account_confirmed is True
        assert res.proposed_account_code == "6130"
        assert res.transaction_nature in ("OPERATING_EXPENSE", "CONSUMABLE", "OTHER")


class TestShortlistAllowsConfirmedCreation:
    def test_create_account_allowed_when_planner_lists_it(self):
        from app.tool_selector import excluded_for_intent, tools_for_intent

        potential = [
            "search_fixed_asset", "search_supplier", "search_account",
            "register_fixed_asset", "create_account",
        ]
        allowed = tools_for_intent("register_fixed_asset", potential)
        assert "create_account" in allowed
        all_tools = {*allowed, "create_invoice", "create_expense"}
        excluded = excluded_for_intent(
            "register_fixed_asset", potential, sorted(all_tools)
        )
        assert "create_account" not in excluded

    def test_planner_appends_confirmed_creation_to_every_intent(self):
        src = Path(planner_mod.__file__).read_text(encoding="utf-8")
        assert 'tools = [*tools, "create_account"]' in src


class TestPreflight:
    @pytest.mark.asyncio
    async def test_missing_explicit_reference_becomes_gap(self, monkeypatch):
        from app import account_resolution as ar

        async def _none(org, name):
            return None

        monkeypatch.setattr(ar, "account_exists", _none)
        gaps = await ar.preflight_account_gaps(
            ORG,
            tool_calls=[ToolCall(
                tool_name="prepare_journal",
                arguments={"lines": [{"account": "Utilities"}]},
            )],
            entities={},
            intent="prepare_journal",
        )
        assert [g.name for g in gaps] == ["Utilities"]

    @pytest.mark.asyncio
    async def test_existing_reference_resolves(self, monkeypatch):
        from app import account_resolution as ar

        async def _exists(org, name):
            return {"id": "x", "name": name, "code": "6100"}

        monkeypatch.setattr(ar, "account_exists", _exists)
        gaps = await ar.preflight_account_gaps(
            ORG,
            tool_calls=[ToolCall(
                tool_name="prepare_journal",
                arguments={"lines": [{"account": "Utilities"}]},
            )],
            entities={},
            intent="prepare_journal",
        )
        assert gaps == []

    @pytest.mark.asyncio
    async def test_register_fixed_asset_probe_spawns_asset_gap(self, monkeypatch):
        from app import account_resolution as ar
        from app.repositories import account_repository as a_repo
        from app.services import fixed_asset_service

        async def _no_account(*a, **k):
            return None

        async def _no_chart(*a, **k):
            return []

        monkeypatch.setattr(fixed_asset_service, "_resolve_gl_account", _no_account)
        monkeypatch.setattr(a_repo, "get_chart_of_accounts", _no_chart)
        gaps = await ar.preflight_account_gaps(
            ORG,
            tool_calls=[ToolCall(
                tool_name="register_fixed_asset",
                arguments={"name": "office chairs", "purchase_cost": 38000},
            )],
            entities={"item_description": "office chairs"},
            intent="register_fixed_asset",
        )
        assert len(gaps) == 1
        assert gaps[0].account_type == "ASSET"
        assert gaps[0].normal_balance == "DEBIT"

    @pytest.mark.asyncio
    async def test_explicit_account_id_skips_the_probe(self, monkeypatch):
        from app import account_resolution as ar
        from app.services import fixed_asset_service

        async def _boom(*a, **k):
            raise AssertionError("probe must not run with an explicit id")

        monkeypatch.setattr(fixed_asset_service, "_resolve_gl_account", _boom)
        gaps = await ar.preflight_account_gaps(
            ORG,
            tool_calls=[ToolCall(
                tool_name="register_fixed_asset",
                arguments={"asset_account_id": str(ORG)},
            )],
            entities={},
            intent="register_fixed_asset",
        )
        assert gaps == []

    @pytest.mark.asyncio
    async def test_nature_probes_gated_for_proposal_paths(self, monkeypatch):
        from app import account_resolution as ar
        from app.services import fixed_asset_service

        async def _boom(*a, **k):
            raise AssertionError("nature probe must not run when gated off")

        monkeypatch.setattr(fixed_asset_service, "_resolve_gl_account", _boom)
        gaps = await ar.preflight_account_gaps(
            ORG,
            tool_calls=[ToolCall(
                tool_name="register_fixed_asset",
                arguments={"name": "office chairs"},
            )],
            entities={"item_description": "office chairs"},
            intent="register_fixed_asset",
            include_nature_probes=False,
        )
        assert gaps == []


class TestRescue:
    async def _rescue(self, monkeypatch, *, entities, failures, prior_qa=(),
                      **kw):
        import app.agent as agent_mod

        captured = {}

        async def _clar(**call):
            captured.update(call)
            return {"question": call["question"]}

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(agent_mod, "create_clarification", _clar)
        monkeypatch.setattr(agent_mod, "_update_status", _noop)
        monkeypatch.setattr(agent_mod, "_log_step", _noop)
        plan = SimpleNamespace(
            extracted_entities=entities, intent="register_fixed_asset",
        )
        resp = await agent_mod._account_rescue_question(
            session_id=uuid.uuid4(),
            organization_id=ORG,
            execution_plan=plan,
            failures=failures,
            prior_qa=list(prior_qa),
            **kw,
        )
        return resp, captured

    @pytest.mark.asyncio
    async def test_account_failure_becomes_clarification(self, monkeypatch):
        resp, captured = await self._rescue(
            monkeypatch,
            entities={"item_description": "office chairs"},
            failures=[SimpleNamespace(error=FIXED_ASSET_ERROR)],
        )
        assert resp is not None
        assert resp.status == ExecutionStatus.AWAITING_CLARIFICATION
        assert "Computer Equipment" in resp.question
        assert captured.get("required_fields") == ["account_configuration"]

    @pytest.mark.asyncio
    async def test_non_account_error_never_rescues(self, monkeypatch):
        resp, _ = await self._rescue(
            monkeypatch,
            entities={},
            failures=[SimpleNamespace(error="Supplier not found: Alph")],
        )
        assert resp is None

    @pytest.mark.asyncio
    async def test_rescue_never_reruns_a_write(self, monkeypatch):
        resp, _ = await self._rescue(
            monkeypatch,
            entities={"item_description": "office chairs"},
            failures=[SimpleNamespace(error=FIXED_ASSET_ERROR)],
            require_no_successful_writes=False,
        )
        assert resp is None

    @pytest.mark.asyncio
    async def test_rescue_is_one_shot(self, monkeypatch):
        resp, _ = await self._rescue(
            monkeypatch,
            entities={"item_description": "office chairs"},
            failures=[SimpleNamespace(error=FIXED_ASSET_ERROR)],
            prior_qa=[{"question": question_for_gap(_asset_gap())}],
        )
        assert resp is None

    @pytest.mark.asyncio
    async def test_rescue_refuses_when_creation_already_confirmed(self, monkeypatch):
        resp, _ = await self._rescue(
            monkeypatch,
            entities={
                "item_description": "office chairs",
                "create_account": "Office Chairs",
            },
            failures=[SimpleNamespace(error=FIXED_ASSET_ERROR)],
        )
        assert resp is None


class TestOrderingAndErrorClassification:
    def test_collect_account_refs_names_and_paths(self):
        calls = [
            ToolCall(tool_name="prepare_journal", arguments={"lines": [
                {"account": "Admin Expense > Utilities"},
                {"account": "Cash"},
            ]}),
            ToolCall(tool_name="register_fixed_asset",
                     arguments={"asset_account_id": str(ORG)}),
        ]
        assert collect_account_refs(calls) == ["Utilities", "Cash"]

    def test_confirmed_creation_runs_first(self):
        calls = ensure_create_account_first(
            [ToolCall(tool_name="register_fixed_asset", arguments={"name": "x"})],
            arguments={"name": "Office Chairs", "code": "1500"},
        )
        assert [c.tool_name for c in calls] == [
            "create_account", "register_fixed_asset",
        ]
        assert calls[0].arguments["name"] == "Office Chairs"

    def test_model_added_creation_is_moved_not_duplicated(self):
        calls = ensure_create_account_first(
            [ToolCall(tool_name="register_fixed_asset"),
             ToolCall(tool_name="create_account", arguments={"name": "Y"})],
            arguments={"name": "Y"},
        )
        assert [c.tool_name for c in calls] == [
            "create_account", "register_fixed_asset",
        ]
        assert len(calls) == 2

    def test_failure_classification_is_conservative(self):
        assert is_account_resolution_error(FIXED_ASSET_ERROR)
        assert not is_account_resolution_error("Supplier not found: Alph")
        assert not is_account_resolution_error(
            "'invoice_no' is not a parameter of this tool"
        )
        gap = gap_from_execution_failure(
            [FIXED_ASSET_ERROR], entities={}, intent="register_fixed_asset",
        )
        assert gap is not None
        assert gap.name == "Computer Equipment"
        assert gap.account_type == "ASSET"
        assert gap_from_execution_failure(
            ["something odd"], entities={}, intent="x"
        ) is None




