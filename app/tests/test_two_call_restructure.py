"""Live-path two-call restructure (Fix A + Fix B) — regression pins.

CALL 1 = SEMANTIC INTAKE (``app/entity_segregation.py``): grounded fact
extraction now includes ``transaction_purpose``, and its prompt must never
grow decision/ledger rules.  Production case behind the fix: "23000 Paid
for Travelling" — the ladder could not classify it and the purpose question
re-asked what the message had already said.

CALL 2 = ACCOUNTING DECISION (``classify_transaction``): the account-to-hit
is identified BEFORE the PHASE 2b clarification gate.  Before the hoist a
questionnaire turn returned at agent.py PHASE 2b and never classified at
all — the account call was unreachable on exactly the turns that most need
a grounded question.
"""

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock as _AM

import pytest

import app.agent as agent_mod
from app.accounting_reasoning import ReasoningOutcome
from app.agent import execute
from app.models.schemas import ExecutionPlan, ExecutionStatus, TransactionClassification

ORG = uuid.UUID("77777777-4777-4777-4777-777777777777")
USER = uuid.UUID("88888888-8888-8888-8888-888888888888")
TRAVELLING = "23000 Paid for Travelling"


# ---------------------------------------------------------------------------
# CALL 1 — the intake call reads purpose from the user's own wording
# ---------------------------------------------------------------------------
class TestCall1PurposeIntake:
    def test_free_wording_grounds_the_purpose(self):
        from app.entity_segregation import _ground_fields, _norm

        raw = TRAVELLING
        grounded = _ground_fields(
            {"transaction_purpose": "TRAVEL"}, _norm(raw), raw.lower(), date.today()
        )
        assert grounded == {"transaction_purpose": "TRAVEL"}
        # The model's own casing is canonicalised to the taxonomy's value.
        grounded = _ground_fields(
            {"transaction_purpose": "travel"}, _norm(raw), raw.lower(), date.today()
        )
        assert grounded == {"transaction_purpose": "TRAVEL"}

    def test_a_purpose_absent_from_the_text_is_dropped(self):
        from app.entity_segregation import _ground_fields, _norm

        raw = TRAVELLING  # no utilities/electricity/... keyword anywhere
        grounded = _ground_fields(
            {"transaction_purpose": "ELECTRICITY"},
            _norm(raw), raw.lower(), date.today(),
        )
        assert grounded == {}, (
            "a purpose whose keyword pattern is absent from the request is a "
            "hallucination — dropped, never repaired (the deterministic "
            "purpose question still owns that decision)"
        )

    def test_other_can_never_be_grounded(self):
        from app.entity_segregation import _ground_fields, _norm

        raw = TRAVELLING
        grounded = _ground_fields(
            {"transaction_purpose": "OTHER"}, _norm(raw), raw.lower(), date.today()
        )
        assert grounded == {}, (
            "OTHER carries no keyword pattern — free text may never enter "
            "through the LLM; the purpose question asks it instead"
        )

    def test_the_call1_prompt_carries_intake_rules_only(self):
        """Prompt-scope pin: CALL 1 must never grow CALL 2's instructions."""
        import asyncio

        from app.entity_segregation import extract_request_facts

        class _Capture:
            def __init__(self):
                self.prompt = None

            async def generate_text(self, *, prompt=None, **kwargs):
                self.prompt = prompt
                return "{}"

        cap = _Capture()
        asyncio.run(
            extract_request_facts(
                TRAVELLING,
                orchestrator=cap,
                thinking_off=True,
                max_output_tokens=600,
                timeout_seconds=5,
                nature_values=["OPERATING_EXPENSE"],
                intent_values=["record_expense"],
            )
        )
        prompt = cap.prompt or ""
        assert "transaction_purpose" in prompt, "the purpose rule must reach CALL 1"
        assert "TRAVEL" in prompt, "purpose values are reused from the taxonomy"
        for leaked in ("propose_account", "parent_code", "CANDIDATES",
                       "needs_clarification", "treatment ladder"):
            assert leaked not in prompt, (
                f"CALL 2 vocabulary ({leaked!r}) leaked into the CALL 1 prompt"
            )

    def test_the_stated_purpose_fills_the_plan_and_the_question_disappears(self):
        from app.planner import plan

        p = plan(
            TRAVELLING,
            prefill_entities={
                "semantic_intent": "record_expense",
                "transaction_purpose": "TRAVEL",
                "amount": 23000.0,
            },
        )
        assert p.intent == "record_expense"
        assert p.extracted_entities.get("transaction_purpose") == "TRAVEL"
        assert p.extracted_entities.get("transaction_nature") == "OPERATING_EXPENSE"
        assert "transaction_purpose" not in p.missing_fields, (
            "a purpose the request already stated must never be re-asked"
        )
        # Only the genuinely-absent fields remain (date here) — targeted asks.
        assert p.missing_fields
        assert not any("expense for" in q for q in p.clarification_questions)

    def test_purpose_prefill_never_leaks_into_another_route(self):
        from app.planner import plan

        p = plan(
            "Create an Invoice for 45000 against sale of tax services",
            prefill_entities={"transaction_purpose": "TRAVEL"},
        )
        assert p.extracted_entities.get("transaction_purpose") is None, (
            "the purpose ladder belongs to record_expense only"
        )

    def test_without_the_llm_the_deterministic_floor_still_asks(self):
        from app.planner import plan

        p = plan(
            TRAVELLING,
            prefill_entities={"semantic_intent": "record_expense", "amount": 23000.0},
        )
        assert "transaction_purpose" in p.missing_fields, (
            "provider-down must degrade to exactly the previous behaviour"
        )


# ---------------------------------------------------------------------------
# CALL 2 — the account call runs (once) BEFORE the question
# ---------------------------------------------------------------------------
def _clarifying_plan():
    return ExecutionPlan(
        intent="record_expense",
        potential_tools=["create_expense"],
        requires_validation=False,
        requires_accounting_engine=False,
        requires_confirmation=False,
        requires_clarification=True,
        missing_fields=["transaction_purpose"],
        clarification_questions=["What is this expense for?"],
        expected_outcome="Record the travel expense",
        extracted_entities={"amount": 23000.0},
        economic_event="DOCUMENT",
        impact_map={},
        prohibited_actions=[],
        transaction_nature=None,
        transaction_nature_source=None,
        batch_items=None,
    )


class _Ctx:
    def __init__(self, entities):
        self.extracted_entities = dict(entities)
        self.relevant_customers = []
        self.relevant_suppliers = []
        self.relevant_bank_accounts = []
        self.relevant_accounts = []
        self.relevant_products = []
        self.live_evidence = []
        self.organization = {}
        self.classification = None
        self.economic_event = "DOCUMENT"
        self.impact_map = {}
        self.prohibited_actions = []


class _NoLLM:
    async def generate_text(self, *a, **k):
        raise AssertionError("LLM text call in a deterministic test path")

    async def generate_with_tools(self, *a, **k):
        raise AssertionError("LLM planning call in a deterministic test path")


def _step_names(recorded):
    return [s[1] for s in recorded["steps"]]


def _world(monkeypatch):
    """Hermetic world for a CLARIFYING turn (approved-harness pattern)."""
    from app.repositories import account_repository

    session = {
        "id": str(uuid.uuid4()),
        "organization_id": str(ORG),
        "user_id": str(USER),
        "user_request": TRAVELLING,
        "conversation_id": "conv-fixb",
        "status": "RUNNING",
        "current_phase": "RUNNING",
    }
    recorded = {"steps": [], "clarifications": [], "classify_kwargs": []}

    async def fake_log_step(session_id, step_type, data):
        recorded["steps"].append((session_id, step_type, data))

    async def fake_create_clarification(**kw):
        recorded["clarifications"].append(kw)
        # Order marker: emitted when the question is actually authored, so
        # the test can place CLASSIFICATION against it in the same list.
        recorded["steps"].append(("s", "QUESTION_ASKED", dict(kw)))
        return {"id": "cl-1", "question": kw.get("question", "")}

    async def fake_classify(**kw):
        recorded["classify_kwargs"].append(kw)
        return TransactionClassification(
            transaction_nature="OPERATING_EXPENSE",
            confidence="HIGH",
            source="TEST_FIX_B",
            account_hint_name="Travel & Transport Expense",
            account_hint_code="6160",
            requires_clarification=False,
        )

    async def _rows(*a, **k):
        return []

    async def _boom(*a, **k):
        raise AssertionError("nothing may execute on a clarifying turn")

    async def fake_create_confirmation(**kw):
        return {"id": "conf-1"}

    async def fake_create_result(**kw):
        return {"id": "res-1"}

    monkeypatch.setattr(agent_mod, "fetch_one", _AM(return_value=session))
    monkeypatch.setattr(agent_mod, "fetch_many", _AM(return_value=[]))
    monkeypatch.setattr(agent_mod, "create_execution_session", _AM(return_value=session))
    monkeypatch.setattr(agent_mod, "_close_superseded_sessions", _AM(return_value=0))
    monkeypatch.setattr(agent_mod, "seed_clarification_history", _AM())
    monkeypatch.setattr(agent_mod, "_load_org_preferences", _AM(return_value={}))
    monkeypatch.setattr(agent_mod, "resolve_confirmation", _AM(return_value={}))
    monkeypatch.setattr(agent_mod, "get_clarification_history", _AM(return_value=[]))
    monkeypatch.setattr(agent_mod, "_update_status", _AM())
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)
    monkeypatch.setattr(agent_mod, "flush_step_logs", _AM())
    monkeypatch.setattr(agent_mod, "log_tool_call", _AM(return_value={"id": "tc"}))
    monkeypatch.setattr(agent_mod, "create_clarification", fake_create_clarification)
    monkeypatch.setattr(agent_mod, "create_confirmation", fake_create_confirmation)
    monkeypatch.setattr(agent_mod, "create_execution_result", fake_create_result)
    monkeypatch.setattr(agent_mod, "execute_planned_tool_calls", _boom)
    monkeypatch.setattr(agent_mod, "get_client", lambda: _NoLLM())
    monkeypatch.setattr(agent_mod, "run_planner", lambda *a, **k: _clarifying_plan())
    monkeypatch.setattr(agent_mod, "build_context", _AM(return_value=_Ctx({})))
    monkeypatch.setattr(agent_mod, "_depreciation_policy_gate", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_revenue_ledger_review_gate", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_catalog_check_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_party_resolution_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_settlement_check_question", _AM(return_value=None))
    monkeypatch.setattr(account_repository, "get_chart_of_accounts", _rows)
    monkeypatch.setattr(account_repository, "search_accounts", _rows)
    monkeypatch.setattr("app.classifier.classify_transaction", fake_classify)
    monkeypatch.setattr(
        "app.entity_segregation.extract_request_facts", _AM(return_value={})
    )
    monkeypatch.setattr(
        "app.accounting_reasoning.run_reasoning_loop",
        _AM(return_value=ReasoningOutcome(status="UNSUPPORTED", understanding={}, rounds=1)),
    )
    monkeypatch.setattr(
        "app.services.preference_service.record_answer_preference", _AM()
    )
    return recorded


class TestCall2ClassifiesBeforeTheQuestion:
    @pytest.mark.asyncio
    async def test_a_clarifying_turn_classifies_once_before_the_question(
        self, monkeypatch
    ):
        recorded = _world(monkeypatch)
        response = await execute(
            user_message=TRAVELLING,
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-fixb",
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        names = _step_names(recorded)
        assert recorded["clarifications"], "the questionnaire gate must fire"
        assert "transaction_purpose" in (
            recorded["clarifications"][0].get("required_fields") or []
        )
        assert names.count("CLASSIFICATION") == 1, (
            "the account call must run exactly once per turn — a second run "
            "at the old PHASE 3b site would double the DB lookups and the trail"
        )
        assert names.index("CLASSIFICATION") < names.index("QUESTION_ASKED"), (
            "Fix B: the account must be identified BEFORE the question is "
            "asked, so the question is grounded in a classified event"
        )

    def test_the_account_call_is_wired_exactly_once(self):
        src = Path(agent_mod.__file__).read_text(encoding="utf-8")
        assert src.count("await classify_transaction(") == 1, (
            "one call site only — hoist above PHASE 2b, no duplicate at 3b"
        )


# ---------------------------------------------------------------------------
# Prompt scope both ways: each call carries only its own instructions
# ---------------------------------------------------------------------------
class TestPromptScopeBothWays:
    def test_the_decision_prompt_carries_no_intake_instructions(self):
        from app.llm_classification import CandidateSet, build_prompt

        prompt = build_prompt(
            intent="record_expense",
            entities={"amount": 23000.0},
            message=TRAVELLING,
            nature_hint=None,
            candidates=CandidateSet(),
        )
        assert "account_id" in prompt, "the decision contract must be present"
        for leaked in ("MISSING_MATERIAL_FACTS", "ANSWERED_HISTORY",
                       "questionnaire", "transaction_purpose"):
            assert leaked not in prompt, (
                f"CALL 1 vocabulary ({leaked!r}) leaked into the CALL 2 prompt"
            )


# ---------------------------------------------------------------------------
# Option 3 — the question is the CONSUMER of the account hint, and the
# deterministic filter removes KNOWN / DEFAULTED / NOT_APPLICABLE asks.
# ---------------------------------------------------------------------------
class TestQuestionGroundingAndFiltering:
    def test_applicable_filter_drops_fields_outside_the_open_gaps(self):
        from app.questionnaire import validate_authored_questions

        entries = [
            {"field": "useful_life_years", "kind": "number",
             "question": "How many years of useful life?"},
            {"field": "transaction_date", "kind": "date",
             "question": "What date did this happen?"},
        ]
        kept = validate_authored_questions(
            entries, {}, applicable=["transaction_date"]
        )
        assert [q.field for q in kept] == ["transaction_date"], (
            "a vocabulary-valid field outside the plan's open gaps is "
            "NOT_APPLICABLE this round and must be dropped"
        )
        # Backward compatible: without the filter, vocabulary-only as before.
        kept2 = validate_authored_questions(entries, {})
        assert {q.field for q in kept2} == {"useful_life_years", "transaction_date"}

    @pytest.mark.asyncio
    async def test_identified_ledger_reaches_the_prompt_never_a_question(self):
        import json
        from types import SimpleNamespace

        from app import questionnaire as qmod

        captured = {}
        reply = json.dumps({
            "intro": "One date.",
            "questions": [
                # decided-ledger ask + outside the open gaps → dropped twice over
                {"field": "account_name", "kind": "text",
                 "question": "Which account should this hit?"},
                {"field": "transaction_date", "kind": "date",
                 "question": "What date did this happen?"},
            ],
        })

        class _Client:
            async def generate_text_light(self, prompt):
                captured["prompt"] = prompt
                return reply

        q = await qmod.author_questionnaire(
            client=_Client(),
            user_request=TRAVELLING,
            intent="record_expense",
            missing_fields=["transaction_date"],
            entities={"amount": 23000.0},
            classification=SimpleNamespace(
                transaction_nature="OPERATING_EXPENSE",
                account_hint_name="Travel & Transport Expense",
                account_hint_code="6160",
            ),
        )
        assert q is not None
        assert [x.field for x in q.questions] == ["transaction_date"]
        prompt = captured["prompt"]
        # payload (JSON form), not just the rule text — the VALUE rides along
        assert '"IDENTIFIED_LEDGER": "Travel & Transport Expense (6160)"' in prompt, (
            "the CALL 2 account decision must ride WITH the question"
        )
        assert "SYSTEM_CONTEXT" in prompt and "IDENTIFIED_LEDGER" in prompt

    @pytest.mark.asyncio
    async def test_without_classification_no_ledger_is_invented(self):
        from app import questionnaire as qmod

        captured = {}
        reply = (
            '{"intro": "One date.", "questions": [{"field": "transaction_date",'
            ' "kind": "date", "question": "What date did this happen?"}]}'
        )

        class _Client:
            async def generate_text_light(self, prompt):
                captured["prompt"] = prompt
                return reply

        q = await qmod.author_questionnaire(
            client=_Client(),
            user_request=TRAVELLING,
            intent="record_expense",
            missing_fields=["transaction_date"],
            entities={"amount": 23000.0},
        )
        assert q is not None
        assert '"IDENTIFIED_LEDGER":' not in captured["prompt"], (
            "no classification → no ledger payload; the model must never "
            "hallucinate an identified account"
        )


class TestHintGateAndLivingClassification:
    @pytest.mark.asyncio
    async def test_floor_clarifying_turn_skips_the_hint_lookups(self, monkeypatch):
        """No authoring client → neither hint consumer exists → skipped."""
        recorded = _world(monkeypatch)
        await execute(
            user_message=TRAVELLING,
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-gate-floor",
        )
        kw = recorded["classify_kwargs"][0]
        assert kw.get("resolve_account_hints") is False, (
            "a floor clarifying turn must not pay the ~6 hint round-trips "
            "for a trail entry nothing consumes"
        )
        cls_step = [d for _, s, d in recorded["steps"] if s == "CLASSIFICATION"][0]
        assert cls_step["hints_resolved"] is False

    @pytest.mark.asyncio
    async def test_with_an_authoring_client_the_hint_is_resolved_and_cited(
        self, monkeypatch
    ):
        import json

        recorded = _world(monkeypatch)
        reply = json.dumps({
            "intro": "One detail.",
            "questions": [{
                "field": "transaction_purpose",
                "kind": "choice",
                "question": (
                    "For Travel & Transport Expense — what was this "
                    "expense for?"
                ),
                "options": [
                    {"value": "TRAVEL", "label": "Travel"},
                    {"value": "RENT", "label": "Rent"},
                ],
            }],
        })

        class _AuthorClient:
            async def generate_text_light(self, prompt):
                return reply

        response = await execute(
            user_message=TRAVELLING,
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-gate-live",
            questionnaire_client=_AuthorClient(),
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        kw = recorded["classify_kwargs"][0]
        assert kw.get("resolve_account_hints") is True, (
            "an authoring client IS a hint consumer — the question is "
            "grounded in the identified ledger"
        )
        q_step = [d for _, s, d in recorded["steps"] if s == "QUESTIONNAIRE"][0]
        assert q_step["account_hint_present"] is True
        assert q_step["account_hint_cited"] is True, (
            "the rendered question must actually name the identified ledger"
        )

    @pytest.mark.asyncio
    async def test_the_next_classification_sees_the_merged_answer(
        self, monkeypatch
    ):
        """A classification is LIVING: rebuilt each turn from merged state."""
        recorded = _world(monkeypatch)
        answered = [{
            "question": "What is this expense for?",
            "answer": "TRAVEL",
            "required_information": ["transaction_purpose"],
        }]
        monkeypatch.setattr(
            agent_mod, "get_clarification_history", _AM(return_value=answered)
        )
        complete = _clarifying_plan()
        complete.requires_clarification = False
        complete.requires_confirmation = True
        complete.missing_fields = []
        complete.clarification_questions = []
        complete.extracted_entities = {
            "amount": 23000.0,
            "transaction_purpose": "TRAVEL",
        }
        monkeypatch.setattr(agent_mod, "run_planner", lambda *a, **k: complete)

        class _TC:
            def __init__(self, tool_name, arguments):
                self.tool_name = tool_name
                self.arguments = dict(arguments)

        async def _det(*, organization_id, execution_plan, classification):
            return [_TC("create_expense", {
                "amount": 23000.0, "account_id": "acct-1",
            })]

        monkeypatch.setattr(agent_mod, "_deterministic_mutation_calls", _det)
        monkeypatch.setattr(
            "app.account_resolution.preflight_account_gaps", _AM(return_value=[])
        )
        monkeypatch.setattr(
            agent_mod, "verify_journal", _AM(return_value={"verified": True})
        )
        monkeypatch.setattr(
            agent_mod, "_make_account_label_resolver", lambda org: (lambda *a, **k: None)
        )

        response = await execute(
            user_message=TRAVELLING,
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-fixb-round2",
        )
        kw = recorded["classify_kwargs"][0]
        assert kw["entities"].get("transaction_purpose") == "TRAVEL", (
            "the new turn's classification must see the merged answer"
        )
        assert not recorded["clarifications"], (
            "an answered field must never be re-asked"
        )
        assert response.status == ExecutionStatus.AWAITING_CONFIRMATION
        names = _step_names(recorded)
        assert names.count("CLASSIFICATION") == 1
        assert "QUESTIONNAIRE" not in names


# ---------------------------------------------------------------------------
# clarification.v1 — every parked turn names its OWNER (and branch), so the
# production fire-rate per source can be measured before any consolidation.
# ---------------------------------------------------------------------------
class TestClarificationTelemetryV1:
    @staticmethod
    def _awaiting(recorded):
        return [
            d for _, s, d in recorded["steps"] if s == "AWAITING_CLARIFICATION"
        ]

    @staticmethod
    def _complete_plan():
        p = _clarifying_plan()
        p.requires_clarification = False
        p.missing_fields = []
        p.clarification_questions = []
        p.extracted_entities = {"amount": 23000.0, "transaction_purpose": "TRAVEL"}
        return p

    def test_helper_stamps_source_branch_and_version(self):
        from app.agent import (
            CLARIFICATION_TELEMETRY_VERSION,
            _clarification_telemetry,
        )

        t = _clarification_telemetry("classifier_gate", branch="nature_4way")
        assert t == {
            "source": "classifier_gate",
            "branch": "nature_4way",
            "telemetry": CLARIFICATION_TELEMETRY_VERSION,
        }
        # absent branch is stamped None, never dropped
        t2 = _clarification_telemetry("account_creation_gap")
        assert t2["branch"] is None
        assert t2["telemetry"] == CLARIFICATION_TELEMETRY_VERSION

    @pytest.mark.asyncio
    async def test_planner_questionnaire_parks_with_its_owner_label(
        self, monkeypatch
    ):
        recorded = _world(monkeypatch)
        await execute(
            user_message=TRAVELLING,
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-tel-planner",
        )
        rows = self._awaiting(recorded)
        assert len(rows) == 1, "the questionnaire turn must park with a marker"
        assert rows[0]["source"] == "planner_questionnaire"
        assert rows[0]["branch"] is None
        assert rows[0]["telemetry"] == "clarification.v1"
        assert rows[0]["required_fields"] == ["transaction_purpose"]

    @pytest.mark.asyncio
    async def test_classifier_nature_4way_is_labelled(self, monkeypatch):
        from app.models.schemas import TransactionClassification

        recorded = _world(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "run_planner", lambda *a, **k: self._complete_plan()
        )

        async def _ambiguous(**kw):
            recorded["classify_kwargs"].append(kw)
            return TransactionClassification(
                transaction_nature=None, confidence="LOW", source="INFERENCE",
                entity="laptop", requires_clarification=True,
            )

        monkeypatch.setattr("app.classifier.classify_transaction", _ambiguous)
        response = await execute(
            user_message="Bought a laptop for PKR 180000",
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-tel-4way",
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        rows = self._awaiting(recorded)
        assert rows[-1]["source"] == "classifier_gate"
        assert rows[-1]["branch"] == "nature_4way"
        assert rows[-1]["telemetry"] == "clarification.v1"
        assert rows[-1]["required_fields"] == ["transaction_nature"]

    @pytest.mark.asyncio
    async def test_classifier_config_gap_is_labelled(self, monkeypatch):
        from app.models.schemas import TransactionClassification

        recorded = _world(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "run_planner", lambda *a, **k: self._complete_plan()
        )

        async def _config_gap(**kw):
            recorded["classify_kwargs"].append(kw)
            return TransactionClassification(
                transaction_nature="OPERATING_EXPENSE", confidence="HIGH",
                source="USER_ANSWER", requires_clarification=True,
            )

        monkeypatch.setattr("app.classifier.classify_transaction", _config_gap)
        response = await execute(
            user_message=TRAVELLING,
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-tel-config",
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        rows = self._awaiting(recorded)
        assert rows[-1]["source"] == "classifier_gate"
        assert rows[-1]["branch"] == "config_gap"
        assert rows[-1]["required_fields"] == ["account_configuration"]

    @pytest.mark.asyncio
    async def test_classifier_treatment_round_is_labelled(self, monkeypatch):
        from app.models.schemas import TransactionClassification

        recorded = _world(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "run_planner", lambda *a, **k: self._complete_plan()
        )

        async def _treatment(**kw):
            recorded["classify_kwargs"].append(kw)
            return TransactionClassification(
                transaction_nature="FIXED_ASSET", confidence="HIGH",
                source="USER_ANSWER", entity="laptop",
                account_hint_id="acct-1", account_hint_name="Office Equipment",
                proposed_account_name="Computer Equipment",
                clarification_reason=(
                    "Should I create 'Computer Equipment'? no 'Computer "
                    "Equipment' account exists under 'Property, Plant & "
                    "Equipment'."
                ),
                requires_clarification=True,
            )

        monkeypatch.setattr("app.classifier.classify_transaction", _treatment)
        response = await execute(
            user_message="Bought a laptop for PKR 180000",
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-tel-treatment",
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        rows = self._awaiting(recorded)
        assert rows[-1]["source"] == "classifier_gate"
        assert rows[-1]["branch"] == "treatment", (
            "the create/use contract round is the TREATMENT branch — its "
            "verbatim wording is a planner-merge contract"
        )

    @pytest.mark.asyncio
    async def test_execution_preflight_gap_keeps_its_stable_label(
        self, monkeypatch
    ):
        from types import SimpleNamespace

        recorded = _world(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "run_planner", lambda *a, **k: self._complete_plan()
        )

        class _TC:
            def __init__(self, tool_name, arguments):
                self.tool_name = tool_name
                self.arguments = dict(arguments)

        async def _det(*, organization_id, execution_plan, classification):
            return [_TC("create_expense", {
                "amount": 23000.0, "account_id": "acct-1",
            })]

        gap = SimpleNamespace(
            name="Utilities Expense", account_type="EXPENSE",
            source="expense_category", ifrs_hint="Operating costs",
            candidates=[],
        )
        monkeypatch.setattr(agent_mod, "_deterministic_mutation_calls", _det)
        monkeypatch.setattr(
            "app.account_resolution.preflight_account_gaps",
            _AM(return_value=[gap]),
        )
        monkeypatch.setattr(
            agent_mod, "_make_account_label_resolver",
            lambda org: (lambda *a, **k: None),
        )
        monkeypatch.setattr(
            agent_mod, "verify_journal", _AM(return_value={"verified": True})
        )
        response = await execute(
            user_message=TRAVELLING,
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-tel-preflight",
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        rows = self._awaiting(recorded)
        assert rows[-1]["source"] == "account_creation_gap", (
            "the execution-preflight label is an existing consumed value — "
            "a stability contract, never renamed"
        )
        assert rows[-1]["telemetry"] == "clarification.v1"
        assert rows[-1]["gap"]["name"] == "Utilities Expense"


# ---------------------------------------------------------------------------
# Phase 1 (checked plan): the LLM DECISION layer behind its existing flag —
# no default change; the opt-in journey pins that the flag-on path decides,
# grounds the question, and degrades to the deterministic chain on garbage.
# ---------------------------------------------------------------------------
class TestPhase1ClassificationFlagOn:
    @staticmethod
    def _awaiting(recorded):
        return [
            d for _, s, d in recorded["steps"] if s == "AWAITING_CLARIFICATION"
        ]

    @staticmethod
    def _classify_step(recorded):
        return [d for _, s, d in recorded["steps"] if s == "CLASSIFICATION"][0]

    @staticmethod
    def _author_client():
        import json as _json

        class _Client:
            async def generate_text_light(self, prompt):
                return _json.dumps({
                    "intro": "One detail.",
                    "questions": [{
                        "field": "transaction_purpose",
                        "kind": "choice",
                        "question": "For Vehicles — what was this expense for?",
                        "options": [
                            {"value": "TRAVEL", "label": "Travel"},
                            {"value": "RENT", "label": "Rent"},
                        ],
                    }],
                })

        return _Client()

    @pytest.mark.asyncio
    async def test_llm_decision_rides_the_hoist_and_grounded_question(
        self, monkeypatch
    ):
        import json as _json

        from app.config import get_settings
        from app.llm_classification import CandidateSet
        from app.classifier import classify_transaction as _real_classify

        recorded = _world(monkeypatch)
        # _world stubs classify_transaction; the flag-on journey needs the
        # REAL classifier so its judgment-zone LLM consult actually runs.
        monkeypatch.setattr(
            "app.classifier.classify_transaction", _real_classify
        )
        monkeypatch.setattr(
            get_settings(), "llm_classification_enabled", True
        )

        async def _cands(org):
            return CandidateSet(accounts=[{
                "id": "a1", "code": "1520", "name": "Vehicles",
                "account_type": "ASSET",
            }], headings=[])

        monkeypatch.setattr("app.llm_classification.gather_candidates", _cands)

        class _Decider:
            async def generate_text_light(self, prompt):
                return _json.dumps({
                    "nature": "FIXED_ASSET", "entity": "car", "fit": "EXACT",
                    "account_id": "a1", "confidence": "HIGH",
                    "needs_clarification": False, "question": "", "options": [],
                    "propose_account": None,
                    "rationale": "a car is a vehicle",
                })

        monkeypatch.setattr(
            "app.ai_orchestrator.get_client", lambda: _Decider()
        )

        response = await execute(
            user_message="23000 Paid for Travelling",
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-p1-llm",
            questionnaire_client=self._author_client(),
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        cls = self._classify_step(recorded)
        assert cls["source"] == "LLM_DECISION", (
            "with the flag ON the model decides nature+account — ahead of "
            "any question (Fix B hoist)"
        )
        assert cls["account_hint"] == "1520"
        q_rows = [
            d for _, s, d in recorded["steps"] if s == "QUESTIONNAIRE"
        ]
        assert q_rows and q_rows[0]["account_hint_present"] is True
        assert self._awaiting(recorded)[-1]["source"] == "planner_questionnaire"

    @pytest.mark.asyncio
    async def test_garbage_decision_degrades_to_the_rule_chain(
        self, monkeypatch
    ):
        from app.config import get_settings
        from app.classifier import classify_transaction as _real_classify

        recorded = _world(monkeypatch)
        # real classifier, so the garbage decision must degrade through ITS
        # deterministic chain — not around a stub.
        monkeypatch.setattr(
            "app.classifier.classify_transaction", _real_classify
        )
        monkeypatch.setattr(
            get_settings(), "llm_classification_enabled", True
        )

        class _Garbage:
            async def generate_text_light(self, prompt):
                return "not json at all"

        monkeypatch.setattr(
            "app.ai_orchestrator.get_client", lambda: _Garbage()
        )

        response = await execute(
            user_message="23000 Paid for Travelling",
            user_id=USER,
            organization_id=ORG,
            conversation_id="conv-p1-fallback",
            questionnaire_client=self._author_client(),
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        cls = self._classify_step(recorded)
        assert cls["source"] != "LLM_DECISION", (
            "an unparseable decision must degrade to the deterministic "
            "chain — never block, never half-apply"
        )





