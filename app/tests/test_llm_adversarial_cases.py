"""Adversarial & exception suite — the LLM authority boundary (P0).

Proves that when the model is wrong, uncertain, unavailable or
manipulated, the ERP rejects the decision, keeps accounting authority in
Python, and never executes a financial mutation.  Every test states the
INVARIANT — what must NEVER happen.

Coverage map (vs the proposed suite):
  A. LLM failure/hallucination ......... THIS MODULE (validate/decide/execute)
  B. Unexpected user input ............. TestUserInputAdversarial (below)
  C. Accounting integrity (balance/tenant/duplicate/atomicity) — ALREADY
     PINNED by the engine suites (test_loan_service, test_payroll_module,
     test_cogs_missing_head_and_guard, test_created_by_router_ownership,
     test_cash_config_gate, test_db_transport_retry); not duplicated.
  D. Entity/ledger ambiguity ........... test_party_name_matching + the
     deterministic party/settlement gates (RC-2/RC-3 pins).
  E. Workflow/state transitions ........ TestPhase1ClassificationFlagOn
     (test_two_call_restructure.py): authoring-ok/decision-garbage pair.
"""

import pytest

from app.llm_classification import CandidateSet, decide, validate

_CANDIDATES = CandidateSet(
    accounts=[
        {"id": "a1", "code": "1100", "name": "Cash on Hand",
         "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "a2", "code": "1520", "name": "Vehicles",
         "account_type": "ASSET", "normal_balance": "DEBIT"},
        {"id": "a3", "code": "6160", "name": "Travel & Transport Expense",
         "account_type": "EXPENSE", "normal_balance": "DEBIT"},
    ],
    headings=[],
)


def _payload(**over):
    base = {
        "nature": "OPERATING_EXPENSE", "entity": "car", "fit": "EXACT",
        "account_id": "a3", "confidence": "HIGH",
        "needs_clarification": False, "question": "", "options": [],
        "propose_account": None, "rationale": "x",
    }
    base.update(over)
    return base


async def _cands_async(org):
    """MUST be async — decide() AWAITS gather_candidates; a sync stub
    short-circuits before the client and makes the test vacuous."""
    return _CANDIDATES


class TestValidateRejects:
    """INVARIANT: no classification object ever carries an unvalidated
    account, an unknown nature, or a self-contradictory decision."""

    def test_account_outside_the_candidate_set_is_rejected(self):
        # FAULT: the model invents an account id nobody validated.
        assert validate(_payload(account_id="ghost-999"),
                        candidates=_CANDIDATES) is None

    def test_vehicles_for_a_hinted_expense_is_rejected(self):
        # FAULT: model picks the Vehicles FIXED-ASSET ledger for a fuel-
        # style expense the user's own words already grounded as expense
        # (nature_hint) — combining "wrong account" + "contradicts an
        # explicit nature".  The hint forces the nature; the ASSET
        # account can no longer fit it and is rejected, never posted.
        assert validate(
            _payload(nature="FIXED_ASSET", account_id="a2"),
            candidates=_CANDIDATES, nature_hint="OPERATING_EXPENSE",
        ) is None

    def test_unknown_nature_enum_is_rejected(self):
        assert validate(_payload(nature="WIDGET_ASSET"),
                        candidates=_CANDIDATES) is None

    def test_undecided_nature_without_asking_is_rejected(self):
        # The model may be undecided only when it is ASKING.
        assert validate(_payload(nature="", account_id=None),
                        candidates=_CANDIDATES) is None

    def test_fit_none_contradicting_a_pick_is_rejected(self):
        assert validate(_payload(fit="NONE", account_id="a3"),
                        candidates=_CANDIDATES) is None

    def test_related_without_a_create_proposal_is_rejected(self):
        assert validate(_payload(fit="RELATED", account_id="a3",
                                 propose_account=None),
                        candidates=_CANDIDATES) is None


class TestDecideDegrades:
    """INVARIANT: a broken provider reply degrades to ``None`` (the
    deterministic chain decides) — it never half-applies, and a test
    guard (AssertionError) is never swallowed."""

    @staticmethod
    def _enable(monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "llm_classification_enabled", True)

    @pytest.mark.parametrize("reply", [
        "",                       # empty content
        "not json at all",        # garbage
        "[1, 2, 3]",              # valid JSON, wrong shape
        '{"fit": "MAYBE"}',       # unknown enum
    ])
    @pytest.mark.asyncio
    async def test_broken_replies_return_none(self, monkeypatch, reply):
        self._enable(monkeypatch)
        monkeypatch.setattr(
            "app.llm_classification.gather_candidates",
            lambda org: _cands_async(org),
        )

        class _Client:
            async def generate_text_light(self, prompt):
                return reply

        result = await decide(
            organization_id=__import__("uuid").uuid4(),
            intent="record_expense",
            entities={"amount": 50000.0},
            message="Paid 50000 for travel",
            client=_Client(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, monkeypatch):
        import asyncio as _aio

        self._enable(monkeypatch)
        monkeypatch.setattr(
            "app.llm_classification.gather_candidates",
            lambda org: _cands_async(org),
        )

        class _Slow:
            async def generate_text_light(self, prompt):
                raise _aio.TimeoutError()

        result = await decide(
            organization_id=__import__("uuid").uuid4(),
            intent="record_expense",
            entities={"amount": 50000.0},
            message="Paid 50000 for travel",
            client=_Slow(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_ghost_account_reply_is_rejected_end_to_end(
        self, monkeypatch
    ):
        import json as _json
        import uuid as _uuid

        self._enable(monkeypatch)
        monkeypatch.setattr(
            "app.llm_classification.gather_candidates",
            lambda org: _cands_async(org),
        )

        class _Liar:
            async def generate_text_light(self, prompt):
                return _json.dumps(_payload(account_id="ghost-999"))

        result = await decide(
            organization_id=_uuid.uuid4(), intent="record_expense",
            entities={"amount": 50000.0}, message="Paid 50000 for travel",
            client=_Liar(),
        )
        assert result is None, (
            "a reply naming an account outside the validated candidate "
            "set must be rejected end-to-end, not merely in isolation"
        )

    @pytest.mark.asyncio
    async def test_test_guards_stay_loud(self, monkeypatch):
        self._enable(monkeypatch)
        monkeypatch.setattr(
            "app.llm_classification.gather_candidates",
            lambda org: _cands_async(org),
        )

        class _GuardTripped:
            async def generate_text_light(self, prompt):
                raise AssertionError("no-LLM guard")

        with pytest.raises(AssertionError):
            await decide(
                organization_id=__import__("uuid").uuid4(),
                intent="record_expense", entities={},
                message="x", client=_GuardTripped(),
            )




class TestExecuteNeverWritesOnReject:
    """INVARIANT: a rejected LLM decision is REACHED (proven by spy), then
    discarded — the turn parks via the deterministic floor and the
    execution bomb in the harness never fires, so no financial write
    occurs on an invalid proposal."""

    @pytest.mark.asyncio
    async def test_ghost_decision_reached_then_falls_back_with_no_execution(
        self, monkeypatch
    ):
        import json as _json

        from app import classifier as clf
        from app.agent import execute
        from app.classifier import classify_transaction as _real_classify
        from app.config import get_settings
        from app.models.schemas import ExecutionStatus
        from test_two_call_restructure import ORG, TRAVELLING, USER, _world

        recorded = _world(monkeypatch)
        monkeypatch.setattr(
            "app.classifier.classify_transaction", _real_classify
        )
        monkeypatch.setattr(
            get_settings(), "llm_classification_enabled", True
        )
        monkeypatch.setattr(
            "app.llm_classification.gather_candidates", _cands_async
        )

        reached = []
        _real_decision = clf._llm_decision

        async def _spy(*a, **k):
            reached.append(True)
            return await _real_decision(*a, **k)

        monkeypatch.setattr(clf, "_llm_decision", _spy)

        class _Liar:
            async def generate_text_light(self, prompt):
                return _json.dumps(_payload(account_id="ghost-999"))

        monkeypatch.setattr("app.ai_orchestrator.get_client", lambda: _Liar())

        class _Author:
            async def generate_text_light(self, prompt):
                return _json.dumps({
                    "intro": "One detail.",
                    "questions": [{
                        "field": "transaction_purpose", "kind": "choice",
                        "question": "What was this for?",
                        "options": [{"value": "TRAVEL", "label": "Travel"}],
                    }],
                })

        response = await execute(
            user_message=TRAVELLING, user_id=USER, organization_id=ORG,
            conversation_id="conv-adv-exec",
            questionnaire_client=_Author(),
        )
        assert reached == [True], (
            "the REAL LLM decision path must have been invoked — a stub "
            "shadowing it would make this test vacuous (fake_classify lesson)"
        )
        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        cls = [d for _, s, d in recorded["steps"] if s == "CLASSIFICATION"][0]
        assert cls["source"] != "LLM_DECISION"
        # The harness bomb ("nothing may execute on a clarifying turn")
        # never fired: reaching here proves no financial write occurred.


class TestUserInputAdversarial:
    def test_cash_and_credit_contradiction_never_invents_and_still_asks(self):
        from app.planner import plan

        p = plan("Purchased a laptop for cash on credit")
        # exactly one treatment is chosen (never both, never invented)…
        assert p.extracted_entities.get("payment_method") in ("CASH", "CREDIT")
        # …and the genuinely-unreadable facts are still asked, never faked.
        assert "transaction_date" in p.missing_fields
        assert "amount" in p.missing_fields
        assert "supplier_name" in p.missing_fields

    @pytest.mark.parametrize("msg", ["Paid 50000", "pay him again"])
    def test_vague_requests_trigger_the_understanding_gate_not_a_guess(
        self, msg
    ):
        from app.planner import plan, text_understanding_gaps

        assert text_understanding_gaps(msg), (
            "an unreadable request must open the bounded-understanding call"
        )
        p = plan(msg)
        assert p.intent == "unknown"
        assert not p.potential_tools, (
            "an unreadable request must never be routed to tools by the "
            "deterministic ladder"
        )


class TestHealthFlagEcho:
    """Safeguard 1 verification surface: /api/health must expose the
    EFFECTIVE AI-stage flags of the running deployment (env edits bind to
    new deployments — only the live process can prove its own state)."""

    @pytest.mark.asyncio
    async def test_health_echoes_the_five_effective_flags(self):
        from app.main import health_check

        body = await health_check()
        # STRICTLY configuration-safe: the response carries exactly these
        # keys — no settings dump, no URLs, no tokens can ride along.
        assert set(body) == {"status", "version", "config_ok", "flags"}
        flags = body.get("flags") or {}
        assert set(flags) == {
            "llm_classification_enabled",
            "accounting_reasoning_enabled",
            "semantic_llm_enabled",
            "two_call_runtime_enabled",
            "bounded_understanding_enabled",
        }
        # pre-activation baseline (hermetic settings): all AI stages off,
        # the bounded intake floor on.
        assert flags["llm_classification_enabled"] is False
        assert flags["accounting_reasoning_enabled"] is False
        assert flags["semantic_llm_enabled"] is False
        assert flags["two_call_runtime_enabled"] is False
        assert flags["bounded_understanding_enabled"] is True
        assert isinstance(body.get("config_ok"), bool)



