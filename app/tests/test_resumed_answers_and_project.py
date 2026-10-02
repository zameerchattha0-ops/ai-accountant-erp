"""Post-mortem 2026-10-01: answered values survive a resumed round, a
lookup-only plan is finished instead of bounced, and a project has an intent.

Two production failures are pinned here:

* **Building purchase** (sessions 42fa39d2 → 6b78909c).  The user answered
  nature + useful life + method + salvage; round 3 merged them, rounds 4–5
  LOST them and asked the same three questions again, and NOTHING was ever
  recorded because the Phase-4 plan contained only lookups
  (``search_account, search_account, search_fixed_asset``) — the org HAD a
  chart of accounts, but the context carried none, so the model planned blind
  lookups that Phase 4 (no executor) could never complete.
* **Project setup** (sessions 500d0aa4 / 03221efb).  "Set up a project …" had
  no intent at all → intent=unknown → the model invented ``create_project``
  until Postgres refused the NOT NULL ``project_code``, and the run closed
  with no question ever asked.
"""

import uuid
from types import SimpleNamespace

import pytest

import app.agent as agent_mod
from app.models.schemas import AgentContext, ToolCall, ToolResult
from app.planner import plan


# --------------------------------------------------------------------------
# 1. Answers survive every resume (seed keeps the positional field tags)
# --------------------------------------------------------------------------


class TestResumedAnswersSurvive:
    def test_seeded_field_rows_still_merge(self):
        """The exact round-4 history shape: field-name question rows that were
        seeded with ``required_information: []`` (so the positional tagger had
        nothing to zip and the keyword chain could not read them)."""
        history = [
            {"question": "transaction_nature", "answer": "FIXED_ASSET"},
            {"question": "useful_life_years", "answer": "8"},
            {"question": "depreciation_method", "answer": "STRAIGHT_LINE"},
            {"question": "salvage_value", "answer": "500,000"},
            {
                "question": "Nothing has been recorded yet. Please answer: the "
                "remaining details",
                "answer": "You should record it as Fixed asset",
            },
        ]
        p = plan(
            "I purchase a Building of 5,000,000 on Cash, Yesterday",
            clarification_history=history,
        )
        ents = p.extracted_entities
        assert ents.get("useful_life_years") == 8
        assert ents.get("depreciation_method") == "STRAIGHT_LINE"
        assert ents.get("salvage_value") == 500000.0
        assert "useful_life_years" not in (p.missing_fields or [])
        assert "depreciation_method" not in (p.missing_fields or [])
        assert "salvage_value" not in (p.missing_fields or [])

    @pytest.mark.parametrize(
        "answer",
        [
            "1) 8\n2) STRAIGHT_LINE\n3) 500,000",
            "1: 8 years, Straight Line, 1,000,000 salvage value",
        ],
    )
    def test_consolidated_answers_merge_every_part(self, answer):
        history = [
            {"question": "What is the USEFUL LIFE of this asset in years?",
             "answer": "8", "required_information": ["useful_life_years"]},
            {
                "question": (
                    "To record this transaction I need a few things:\n"
                    "1. What is the USEFUL LIFE of this asset in years?\n"
                    "2. Which DEPRECIATION METHOD should I use?\n"
                    "3. What RESIDUAL / SALVAGE value will this asset have?"
                ),
                "answer": answer,
                "required_information": [
                    "useful_life_years",
                    "depreciation_method",
                    "salvage_value",
                ],
            },
        ]
        ents = plan(
            "I purchase a Building of 5,000,000 on Cash, Yesterday",
            clarification_history=history,
        ).extracted_entities
        assert ents.get("useful_life_years") == 8
        assert ents.get("depreciation_method") == "STRAIGHT_LINE"
        assert ents.get("salvage_value") in (500000.0, 1000000.0)

    def test_decline_settles_the_whole_policy(self):
        ents = plan(
            "I purchase a Building of 5,000,000 on Cash, Yesterday",
            clarification_history=[
                {"question": "useful_life_years", "answer": "NONE"},
            ],
        ).extracted_entities
        assert ents.get("depreciation_declined") is True

    @pytest.mark.asyncio
    async def test_seed_keeps_required_information(self, monkeypatch):
        """seed_clarification_history must not blank the field tags."""
        import app.database as database

        captured = {}

        async def fake_insert_many(table, data):
            captured["table"] = table
            captured["data"] = data

        monkeypatch.setattr(database, "insert_many", fake_insert_many)
        await database.seed_clarification_history(
            uuid.uuid4(),
            [
                {
                    "question": "Which DEPRECIATION METHOD should I use?",
                    "answer": "STRAIGHT_LINE",
                    "required_information": ["depreciation_method"],
                },
                {"question": "useful_life_years", "answer": "8", "field": "useful_life_years"},
            ],
        )
        rows = captured["data"]
        assert rows[0]["required_information"] == ["depreciation_method"]
        # A field-shaped row stores its FIELD as required information, so the
        # positional tagger (and the bare-field router) both work next round.
        assert rows[1]["required_information"] == ["useful_life_years"]



# --------------------------------------------------------------------------
# 2. A project has a real intent, a real field ladder and a derived code
# --------------------------------------------------------------------------

PROJECT_MSG = (
    "Set up a project called Mobile App for XYZ Client with a budget of "
    "Rs. 2,000,000"
)


class TestProjectIntent:
    def test_project_setup_routes_and_extracts(self):
        p = plan(PROJECT_MSG)
        assert p.intent == "create_project"
        assert p.extracted_entities.get("project_name") == "Mobile App"
        assert p.extracted_entities.get("amount") == 2000000.0
        # project_code is derived, never asked.
        assert "project_code" not in (p.missing_fields or [])

    def test_query_phrasings_are_never_a_mutation(self):
        assert plan("show the project budget for Mobile App").intent != "create_project"

    def test_tools_and_context_are_offered(self):
        from app.planner import _context_for_intent, _tools_for_intent
        from app.tool_selector import tools_for_intent

        assert "create_project" in _tools_for_intent("create_project")
        assert "projects" in _context_for_intent("create_project")
        assert "create_project" in tools_for_intent(
            "create_project", _tools_for_intent("create_project")
        )

    @pytest.mark.asyncio
    async def test_repository_derives_a_free_code(self, monkeypatch):
        import app.repositories.project_repository as repo

        async def fake_fetch_many(table, **kwargs):
            assert table == "projects"
            return [{"project_code": "MOB-001"}, {"project_code": "MOB-002"}]

        captured = {}

        async def fake_insert_one(table, data):
            captured["data"] = data
            return {"id": "p1", **data}

        monkeypatch.setattr(repo, "fetch_many", fake_fetch_many)
        monkeypatch.setattr(repo, "insert_one", fake_insert_one)

        await repo.create_project(organization_id=uuid.uuid4(), name="Mobile App")
        assert captured["data"]["project_code"] == "MOB-003"

        captured.clear()
        await repo.create_project(
            organization_id=uuid.uuid4(), name="Mobile App", project_code="mob-099"
        )
        assert captured["data"]["project_code"] == "MOB-099"


# --------------------------------------------------------------------------
# 3. A refusal that demands a USER value becomes a question
# --------------------------------------------------------------------------


class TestUserInputRequiredQuestion:
    def test_not_null_refusal_becomes_a_question(self):
        failed = [
            ToolResult(
                tool_name="create_project",
                success=False,
                error=(
                    "Required project field 'project_code' is missing. This "
                    "value must be supplied by the user — do not guess or use a "
                    "default."
                ),
            )
        ]
        question = agent_mod._user_input_required_question(failed)
        assert question and "project_code" in question

    def test_other_failures_are_not_questions(self):
        failed = [
            ToolResult(
                tool_name="search_account",
                success=False,
                error="An unexpected error occurred while executing this operation.",
            )
        ]
        assert agent_mod._user_input_required_question(failed) is None
        assert agent_mod._user_input_required_question([]) is None


# --------------------------------------------------------------------------
# 4. A lookup-only plan is FINISHED, not bounced (Phase-5 continuation)
# --------------------------------------------------------------------------


class _StubClient:
    def __init__(self, calls):
        self._calls = calls
        self.kwargs = None

    async def generate_with_tools(self, **kwargs):
        self.kwargs = kwargs
        return {"text": "", "tool_calls": self._calls, "tool_results": []}


def _plan_with_intent(intent):
    return SimpleNamespace(intent=intent, required_context=[])


class TestLookupOnlyPlanContinuation:
    @pytest.mark.asyncio
    async def test_read_only_plan_runs_and_the_model_finishes_it(
        self, monkeypatch
    ):
        import app.tool_execution as tool_exec

        executed = []

        async def fake_execute_planned(calls, executor):
            for call in calls:
                executed.append(call.tool_name)
            # Production contract (app/tool_execution.py): PLAIN DICTS aligned
            # with the calls — never ToolResults.  This stub used to return
            # ToolResult objects, which hid the AttributeError that killed
            # session b64467c0 in production.
            return [
                {"success": True, "error": None, "data": [{"id": "a1"}]}
                for c in calls
            ]

        monkeypatch.setattr(tool_exec, "is_read_only_tool", lambda name: True)
        monkeypatch.setattr(
            tool_exec, "execute_planned_tool_calls", fake_execute_planned
        )

        async def fake_log_step(*args, **kwargs):
            return None

        monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

        mutation = ToolCall(
            tool_name="register_fixed_asset", arguments={"name": "Building"}
        )
        client = _StubClient([mutation])
        context = AgentContext(organization={}, user={})

        calls, _text, evidence = await agent_mod._continue_lookup_only_plan(
            client=client,
            session_id=uuid.uuid4(),
            execution_plan=_plan_with_intent("register_fixed_asset"),
            planned_tool_calls=[
                ToolCall(tool_name="search_account", arguments={"query": "building"}),
                ToolCall(tool_name="search_fixed_asset", arguments={"query": "building"}),
            ],
            context=context,
            user_message=PROJECT_MSG,
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
        )

        assert executed == ["search_account", "search_fixed_asset"]
        assert calls and calls[0].tool_name == "register_fixed_asset"
        # the lookups' results were attached for the planning prompt
        assert context.live_evidence
        assert client.kwargs["executor"] is None
        assert client.kwargs["thinking_off"] is True
        assert len(evidence) == 2
        assert evidence[0]["records"] == [{"id": "a1"}]
        assert evidence[0]["error"] is None

    @pytest.mark.asyncio
    async def test_a_plan_with_a_mutation_is_left_alone(self):
        calls, _text, evidence = await agent_mod._continue_lookup_only_plan(
            client=_StubClient([]),
            session_id=uuid.uuid4(),
            execution_plan=_plan_with_intent("register_fixed_asset"),
            planned_tool_calls=[
                ToolCall(tool_name="register_fixed_asset", arguments={})
            ],
            context=AgentContext(organization={}, user={}),
            user_message="x",
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
        )
        assert calls is None and evidence == []

    @pytest.mark.asyncio
    async def test_deterministic_plan_never_calls_a_provider(self):
        calls, _text, _evidence = await agent_mod._continue_lookup_only_plan(
            client=None,
            session_id=uuid.uuid4(),
            execution_plan=_plan_with_intent("record_expense"),
            planned_tool_calls=[
                ToolCall(tool_name="search_account", arguments={})
            ],
            context=AgentContext(organization={}, user={}),
            user_message="x",
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
        )
        assert calls is None

    @pytest.mark.asyncio
    async def test_the_real_executor_returns_dicts_and_never_crashes(
        self, monkeypatch
    ):
        """Regression: production 2026-10-01, plant session b64467c0.

        The REAL execute_planned_tool_calls returns plain dicts, but the
        evidence loop read ``result.data`` / ``r.tool_name`` as if they were
        ToolResults — every lookup-only plan died with
        ``AttributeError: 'dict' object has no attribute 'data'`` before
        LOOKUP_PREP was ever logged.  This runs the gate through the real
        executor (only route_tool_call is faked) so the dict contract cannot
        drift away from production again.
        """
        import app.tool_execution as tool_exec

        async def fake_route(call, **kwargs):
            return ToolResult(
                tool_name=call.tool_name,
                success=True,
                data=[{"id": "acc-1", "code": "1200", "name": "Plant"}],
            )

        monkeypatch.setattr(agent_mod, "route_tool_call", fake_route)
        monkeypatch.setattr(tool_exec, "is_read_only_tool", lambda name: True)

        logged = []

        async def fake_log_step(session_id, step_type, data):
            logged.append((step_type, data))

        monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

        client = _StubClient([
            ToolCall(tool_name="register_fixed_asset", arguments={"name": "Plant"})
        ])
        context = AgentContext(organization={}, user={})

        calls, _text, evidence = await agent_mod._continue_lookup_only_plan(
            client=client,
            session_id=uuid.uuid4(),
            execution_plan=_plan_with_intent("register_fixed_asset"),
            planned_tool_calls=[
                ToolCall(tool_name="search_account", arguments={"query": "plant"}),
                ToolCall(tool_name="get_chart_of_accounts", arguments={}),
            ],
            context=context,
            user_message="We Buy a Plant for 6,700,000 on cash, yesterday",
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
        )

        # the plan was finished by the model instead of bounced to the user
        assert calls and calls[0].tool_name == "register_fixed_asset"
        assert len(evidence) == 2
        assert evidence[0]["kind"] == "search_account"
        assert evidence[0]["records"] == [
            {"id": "acc-1", "code": "1200", "name": "Plant"}
        ]
        assert evidence[0]["error"] is None
        assert context.live_evidence
        # the pre-gate lookups are visible in the trail
        prep = [d for s, d in logged if s == "LOOKUP_PREP"]
        assert prep and prep[0]["succeeded"] == [
            "search_account",
            "get_chart_of_accounts",
        ]

    @pytest.mark.asyncio
    async def test_a_failed_lookup_reports_its_error_as_evidence(self, monkeypatch):
        """A refused lookup is evidence TOO — it must not crash the gate."""
        import app.tool_execution as tool_exec

        async def fake_execute_planned(calls, executor):
            return [{"success": False, "error": "connection refused"} for c in calls]

        monkeypatch.setattr(tool_exec, "is_read_only_tool", lambda name: True)
        monkeypatch.setattr(
            tool_exec, "execute_planned_tool_calls", fake_execute_planned
        )

        async def fake_log_step(*args, **kwargs):
            return None

        monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

        client = _StubClient([
            ToolCall(tool_name="register_fixed_asset", arguments={})
        ])
        context = AgentContext(organization={}, user={})

        calls, _text, evidence = await agent_mod._continue_lookup_only_plan(
            client=client,
            session_id=uuid.uuid4(),
            execution_plan=_plan_with_intent("register_fixed_asset"),
            planned_tool_calls=[
                ToolCall(tool_name="search_account", arguments={"query": "plant"}),
            ],
            context=context,
            user_message="x",
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
        )

        assert evidence[0]["records"] == []
        assert evidence[0]["error"] == "connection refused"
        assert calls is not None  # the model still got its bounded round


# --------------------------------------------------------------------------
# 5. The planner's own context sources reach the context (no blind model)
# --------------------------------------------------------------------------


class TestPlannerDeclaredContextSources:
    @pytest.mark.asyncio
    async def test_chart_of_accounts_loads_without_a_db_rule(self, monkeypatch):
        import app.context_manager as cm
        from app.repositories import account_repository

        monkeypatch.setattr(cm, "peek_context_rules_cache", lambda intent: None)

        async def no_rule(intent):
            return {"rule": None, "sources": []}

        async def chart(org_id, **kwargs):
            return [{"id": "a1", "code": "1500", "name": "Computer Equipment"}]

        monkeypatch.setattr(cm, "get_context_sources_for_intent", no_rule)
        monkeypatch.setattr(account_repository, "get_chart_of_accounts", chart)

        context = await cm.build_context(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            intent="register_fixed_asset",
            entity_hints={"item_description": "Building"},
            org_preferences={},
            required_context=["chart_of_accounts"],
            organization={},
            financial_year={},
            accounting_period={},
        )
        assert [a["name"] for a in context.relevant_accounts] == [
            "Computer Equipment"
        ]


# --------------------------------------------------------------------------
# 7. A resolved fixed-asset acquisition is planned WITHOUT the model (R5)
# --------------------------------------------------------------------------


#: The entities the production plant request resolved to (session 5939bf30).
PLANT_ENTITIES = {
    "amount": 6700000.0,
    "transaction_date": "2026-10-01",
    "item_description": "Plant",
    "asset_name": "Plant",
    "transaction_nature": "FIXED_ASSET",
    "payment_method": "CASH",
    "useful_life_years": 4,
    "depreciation_method": "STRAIGHT_LINE",
    "salvage_value": 2300000.0,
    "capitalization_threshold": 50000.0,
}


def _fixed_asset_plan(entities):
    return SimpleNamespace(
        intent="register_fixed_asset",
        batch_items=[],
        extracted_entities=dict(entities),
    )


class TestFixedAssetAcquisitionFastPath:
    """Production 2026-10-01/02 (sessions 5939bf30 / f3609d50 / 0debc91f).

    "We Buy a Plant for 6,700,000 on cash, yesterday" carried EVERY value
    register_fixed_asset needs, yet the model planned only read-only lookups
    in BOTH the plan round and the lookup-continuation round, so the
    completeness gate parked the run on a question although nothing was
    missing.  A fully-resolved acquisition is now built in Python (the tool
    resolves the asset/depreciation/cash-bank accounts itself), so the model
    round-trip — and that stall — cannot happen for it.
    """

    @pytest.mark.asyncio
    async def test_the_plant_request_is_planned_without_the_model(self):
        calls = await agent_mod._deterministic_mutation_calls(
            organization_id=uuid.uuid4(),
            execution_plan=_fixed_asset_plan(PLANT_ENTITIES),
            classification=None,
        )
        assert calls and len(calls) == 1
        args = calls[0].arguments
        assert calls[0].tool_name == "register_fixed_asset"
        assert args["name"] == "Plant"
        assert args["purchase_cost"] == 6700000.0
        assert args["transaction_date"] == "2026-10-01"
        assert args["payment_method"] == "CASH"
        # the depreciation answers the user already gave ride along
        assert args["useful_life_years"] == 4
        assert args["salvage_value"] == 2300000.0
        assert args["depreciation_method"] == "STRAIGHT_LINE"
        # the plan now CONTAINS a financial mutation, so the completeness gate
        # can never bounce it back to the user as "unfinished"
        assert not agent_mod._plan_performs_no_financial_mutation(
            intent="register_fixed_asset", calls=calls
        )

    @pytest.mark.asyncio
    async def test_an_unstated_payment_treatment_is_never_assumed_cash(self):
        entities = dict(PLANT_ENTITIES)
        entities.pop("payment_method")
        assert (
            await agent_mod._deterministic_mutation_calls(
                organization_id=uuid.uuid4(),
                execution_plan=_fixed_asset_plan(entities),
                classification=None,
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_an_inferred_nature_is_never_capitalised(self):
        entities = dict(PLANT_ENTITIES, transaction_nature="OPERATING_EXPENSE")
        assert (
            await agent_mod._deterministic_mutation_calls(
                organization_id=uuid.uuid4(),
                execution_plan=_fixed_asset_plan(entities),
                classification=None,
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_a_credit_acquisition_without_a_supplier_waits_for_the_model(self):
        entities = dict(PLANT_ENTITIES, payment_method="CREDIT")
        assert (
            await agent_mod._deterministic_mutation_calls(
                organization_id=uuid.uuid4(),
                execution_plan=_fixed_asset_plan(entities),
                classification=None,
            )
            is None
        )
        entities["supplier_name"] = "Plant World"
        calls = await agent_mod._deterministic_mutation_calls(
            organization_id=uuid.uuid4(),
            execution_plan=_fixed_asset_plan(entities),
            classification=None,
        )
        assert calls and calls[0].arguments["payment_method"] == "CREDIT"
        assert calls[0].arguments["supplier_name"] == "Plant World"


# --------------------------------------------------------------------------
# 8. The lookup-continuation tells the model its lookups ALREADY RAN
# --------------------------------------------------------------------------


class TestLookupContinuationAnnouncesTheCompletedLookups:
    """The continuation is a PLANNING call (executor=None), and the planner's
    own rules ("search before creating", "search → create → document") made it
    re-plan the SAME read-only calls — production 2026-10-02 (plant session
    5939bf30) returned ``search_account, search_account, search_account,
    get_chart_of_accounts`` again instead of the write.  The context now names
    the completed calls so the model finishes the plan instead of looping."""

    @pytest.mark.asyncio
    async def test_the_completed_lookups_are_recorded_on_the_context(
        self, monkeypatch
    ):
        import app.tool_execution as tool_exec

        async def fake_execute_planned(calls, executor):
            return [
                {"success": True, "error": None, "data": [{"id": "a1"}]}
                for c in calls
            ]

        monkeypatch.setattr(tool_exec, "is_read_only_tool", lambda name: True)
        monkeypatch.setattr(
            tool_exec, "execute_planned_tool_calls", fake_execute_planned
        )

        async def fake_log_step(*args, **kwargs):
            return None

        monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

        client = _StubClient([
            ToolCall(tool_name="register_fixed_asset", arguments={"name": "Plant"})
        ])
        context = AgentContext(organization={}, user={})

        await agent_mod._continue_lookup_only_plan(
            client=client,
            session_id=uuid.uuid4(),
            execution_plan=_plan_with_intent("register_fixed_asset"),
            planned_tool_calls=[
                ToolCall(tool_name="search_account", arguments={"query": "plant"}),
                ToolCall(tool_name="get_chart_of_accounts", arguments={}),
            ],
            context=context,
            user_message="We Buy a Plant for 6,700,000 on cash, yesterday",
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            auth=None,
            excluded_tools=set(),
        )

        # every completed call is named, with what it returned
        assert [item["tool"] for item in context.pre_executed_lookups] == [
            "search_account",
            "get_chart_of_accounts",
        ]
        assert context.pre_executed_lookups[0]["records"] == [{"id": "a1"}]
        assert context.pre_executed_lookups[0]["error"] is None

    def test_the_prompt_forbids_repeating_them_and_asks_for_the_write(self):
        from app.prompts import build_user_content

        context = AgentContext(organization={}, user={})
        context.pre_executed_lookups = [
            {"tool": "search_account", "records": [{"id": "a1"}], "error": None},
            {"tool": "get_chart_of_accounts", "records": None, "error": "denied"},
        ]
        content = build_user_content("We Buy a Plant", context)
        assert "READ-ONLY CALLS ALREADY EXECUTED" in content
        assert "search_account: returned 1 row(s)" in content
        assert "get_chart_of_accounts: FAILED" in content
        assert "Do NOT call any of these again" in content
        # the model is told to finish with the WRITE call, not another lookup
        assert "emit the WRITE tool" in content

    def test_a_run_without_lookups_renders_nothing_extra(self):
        from app.prompts import build_user_content

        content = build_user_content(
            "We Buy a Plant", AgentContext(organization={}, user={})
        )
        assert "READ-ONLY CALLS ALREADY EXECUTED" not in content
