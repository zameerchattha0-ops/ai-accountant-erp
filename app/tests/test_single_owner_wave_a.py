"""Wave A acceptance tests — AUDIT_REPORT §8 gate (a)–(d).

Wave A is observation-only: it unifies the nature vocabularies, removes the
silent ``_DEFAULT_SHAPE`` fallback, adds the optional ``decision`` /
``prerequisites`` contract block, and records MODEL_INTENT vs LEGACY_INTENT.

Pinned invariants:

* ``account_shape`` RAISES for any treatment without a determined shape —
  ``ASSET_DISPOSAL`` / ``OTHER`` / ``None`` must never become an expense;
* no ``_DEFAULT_SHAPE`` remains anywhere in the source;
* the two axes stay distinct (``SERVICE`` is their only overlap);
* ``CANONICAL_INTENTS`` never drifts from the planner's own intent table;
* the contract block is present in the prompt and creates NO violations
  (observation-only: an invented intent is recorded, not rejected);
* the divergence metric reports its five results and never mutates the plan;
* full suite still green (behavior unchanged) — see gate (d).
"""

import uuid

import pytest

from app.accounting_reasoning import (
    _outcome_from_parsed,
    build_reasoning_prompt,
    validate_outcome,
)
from app.accounting_vocabulary import (
    ACCOUNT_SHAPES,
    CANONICAL_INTENTS,
    DOCUMENT_NATURES,
    TREATMENTS,
    InvalidAccountingNature,
    account_shape,
    is_canonical_intent,
)
from app.tools import list_tools

_DIVERGENT_MODEL = {
    "intent": "record_credit_purchase",
    "treatment": "OPERATING_EXPENSE",
    "document_nature": "GOODS",
}


class TestVocabularySingleSource:
    """Gate (a): the silent fallback is gone."""

    @pytest.mark.parametrize(
        "bad",
        ["ASSET_DISPOSAL", "OTHER", "GOODS", "LIABILITY", "EQUITY", None, "", "  ", "x"],
    )
    def test_unknown_nature_raises_never_defaults(self, bad):
        with pytest.raises(InvalidAccountingNature):
            account_shape(bad)

    def test_no_default_shape_path_remains(self):
        import app.account_resolution as account_resolution
        import app.accounting_vocabulary as vocabulary

        assert not hasattr(account_resolution, "_DEFAULT_SHAPE")
        assert not hasattr(vocabulary, "_DEFAULT_SHAPE")

    def test_known_treatments_return_determined_shapes(self):
        shape = account_shape("OPERATING_EXPENSE")
        assert (shape.account_type, shape.base_code) == ("EXPENSE", "6100")
        # Old 4-tuple unpacking still holds (NamedTuple is a tuple).
        at, nb, code, ifrs = account_shape("FIXED_ASSET")
        assert (at, nb, code) == ("ASSET", "DEBIT", "1500")

    def test_case_and_whitespace_are_normalised_not_rejected(self):
        assert account_shape("  fixed_asset ") == account_shape("FIXED_ASSET")

    def test_axes_stay_distinct(self):
        """The whole point of Wave A: one field can no longer mean two axes."""
        assert DOCUMENT_NATURES & TREATMENTS == {"SERVICE"}
        assert "ASSET_DISPOSAL" in DOCUMENT_NATURES
        assert "ASSET_DISPOSAL" not in ACCOUNT_SHAPES
        # OTHER is a legal TREATMENT but has no determined shape on purpose.
        assert "OTHER" in TREATMENTS
        assert "OTHER" not in ACCOUNT_SHAPES


class TestCanonicalIntentDriftGuard:
    """Gate (b): the vocabulary and the planner can never drift apart."""

    def test_every_planner_keyword_intent_is_canonical(self):
        from app import planner

        keyword_intents = {intent for intent, _patterns in planner._INTENT_PATTERNS}
        missing = keyword_intents - CANONICAL_INTENTS
        assert not missing, (
            "planner intents missing from CANONICAL_INTENTS: " + str(sorted(missing))
        )

    def test_every_transaction_intent_is_canonical(self):
        from app import planner

        missing = set(planner._TRANSACTION_INTENTS) - CANONICAL_INTENTS
        assert not missing, str(sorted(missing))

    def test_unknown_is_deliberately_not_canonical(self):
        assert not is_canonical_intent("unknown")
        assert not is_canonical_intent(None)
        assert is_canonical_intent("record_credit_purchase")


class TestContractSupersetIsObservationOnly:
    """Gate (b): the block is prompted for, parses, and rejects NOTHING."""

    def test_prompt_carries_the_wave_a_block(self):
        from app.accounting_reasoning import ReasoningFacts, preliminary_extraction

        msg = "We bought a laptop"
        facts = ReasoningFacts(user_request=msg, preliminary=preliminary_extraction(msg))
        prompt = build_reasoning_prompt(facts, offered_tools=list(list_tools()))
        assert '"decision"' in prompt
        assert '"prerequisites"' in prompt
        assert "observation metadata" in prompt

    def test_decision_block_adds_no_violations(self):
        """Wave A records an invented value; it never rejects the proposal."""
        proposal = {
            "interpretation": "Settle the open receivable.",
            "affected_records": ["customer receipt"],
            "accounting_impact": [
                {"account": "Bank", "debit": 1, "credit": 1, "reason": "cash in"}
            ],
            "not_affected": [],
            "unresolved_uncertainty": [],
            "tools": [{"tool_name": "record_customer_receipt", "arguments": {}}],
            "confirmation": "Record the receipt?",
        }
        base = _outcome_from_parsed(
            {"understanding": {"economic_event": "receipt"}, "proposal": proposal},
            rounds=1,
        )
        with_block = _outcome_from_parsed(
            {
                "understanding": {"economic_event": "receipt"},
                "proposal": proposal,
                "decision": {
                    "intent": "totally_not_an_intent",
                    "treatment": "BANANA",
                    "document_nature": "NOPE",
                },
            },
            rounds=1,
        )
        kwargs = {"offered_tools": ("record_customer_receipt",)}
        assert with_block.decision == {
            "intent": "totally_not_an_intent",
            "treatment": "BANANA",
            "document_nature": "NOPE",
        }
        # Identical violations with and without the block ⇒ the block is inert.
        assert validate_outcome(with_block, **kwargs) == validate_outcome(base, **kwargs)

    def test_prerequisites_parse_is_bounded_and_inert(self):
        outcome = _outcome_from_parsed(
            {
                "understanding": {"economic_event": "invoice"},
                "evidence_requests": [{"kind": "parties", "why": "check"}],
                "prerequisites": [
                    {"name": "customer", "status": "MISSING", "resolution": "CREATE"},
                    {"name": "", "status": "missing"},
                    "not-a-dict",
                    {"name": "x" * 500, "status": "M" * 500},
                ],
            },
            rounds=1,
        )
        assert [p["name"] for p in outcome.prerequisites] == ["customer", "x" * 80]
        assert outcome.prerequisites[0]["status"] == "missing"
        assert outcome.prerequisites[0]["resolution"] == "create"
        # status is lowercased and bounded to 24 chars — never truncated to a
        # value that could be mistaken for a different status.
        assert outcome.prerequisites[1]["status"] == "m" * 24


class _FakeReasoning:
    def __init__(self, decision, prerequisites=None):
        self.decision = decision
        self.prerequisites = prerequisites or []


class TestDivergenceMetric:
    """Gate (c): INTENT_COMPARISON is recorded, accurately and only once."""

    @staticmethod
    async def _run(monkeypatch, reasoning, legacy_intent):
        captured = {}

        async def _fake_log_step(session_id, step_type, data):
            captured["step_type"] = step_type
            captured["data"] = data

        monkeypatch.setattr("app.agent._log_step", _fake_log_step)
        from app.agent import _log_intent_comparison

        await _log_intent_comparison(uuid.uuid4(), reasoning, legacy_intent)
        return captured

    @pytest.mark.asyncio
    async def test_agreement(self, monkeypatch):
        got = await self._run(
            monkeypatch, _FakeReasoning({"intent": "record_purchase"}), "record_purchase"
        )
        assert got["data"]["result"] == "AGREEMENT"

    @pytest.mark.asyncio
    async def test_divergent_intent(self, monkeypatch):
        got = await self._run(
            monkeypatch,
            _FakeReasoning({"intent": "record_credit_purchase"}),
            "record_purchase",
        )
        assert got["data"]["result"] == "DIVERGENT_INTENT"

    @pytest.mark.asyncio
    async def test_model_absent(self, monkeypatch):
        got = await self._run(monkeypatch, _FakeReasoning({}), "record_purchase")
        assert got["data"]["result"] == "MODEL_ABSENT"

    @pytest.mark.asyncio
    async def test_non_canonical_is_recorded_not_accepted(self, monkeypatch):
        got = await self._run(
            monkeypatch, _FakeReasoning({"intent": "do_a_flip"}), "record_purchase"
        )
        assert got["data"]["result"] == "MODEL_NONCANONICAL"

    @pytest.mark.asyncio
    async def test_legacy_absent(self, monkeypatch):
        got = await self._run(
            monkeypatch, _FakeReasoning({"intent": "record_purchase"}), ""
        )
        assert got["data"]["result"] == "LEGACY_ABSENT"

    @pytest.mark.asyncio
    async def test_payload_carries_intents_only_never_chain_of_thought(
        self, monkeypatch
    ):
        got = await self._run(
            monkeypatch,
            _FakeReasoning(
                {"intent": "record_purchase", "treatment": "OPERATING_EXPENSE"},
                prerequisites=[{"name": "customer"}],
            ),
            "record_purchase",
        )
        assert got["step_type"] == "INTENT_COMPARISON"
        assert set(got["data"]) == {
            "result",
            "model_intent",
            "legacy_intent",
            "treatment",
            "document_nature",
            "prerequisites",
        }

    @pytest.mark.asyncio
    async def test_both_sides_recorded_without_reconciliation(self, monkeypatch):
        """The metric OBSERVES the disagreement — it never resolves it (§7)."""
        from app.agent import _log_intent_comparison
        from app.planner import plan as run_planner

        captured = {}

        async def _fake_log_step(session_id, step_type, data):
            captured.update(data)

        monkeypatch.setattr("app.agent._log_step", _fake_log_step)
        legacy_plan = run_planner("We bought a laptop")
        before = legacy_plan.intent
        assert before == "record_purchase"  # today's deterministic answer

        await _log_intent_comparison(
            uuid.uuid4(), _FakeReasoning({"intent": "record_credit_purchase"}), before
        )

        assert captured["model_intent"] == "record_credit_purchase"
        assert captured["legacy_intent"] == "record_purchase"
        assert captured["result"] == "DIVERGENT_INTENT"
        # The legacy plan is untouched: observation only.
        assert legacy_plan.intent == before

    def test_only_the_two_known_sites_write_the_plan_intent(self):
        """Wave A must not add a THIRD writer — that is Wave B's job (§8)."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "agent.py").read_text(
            encoding="utf-8"
        )
        writers = [
            line.strip()
            for line in source.splitlines()
            if "execution_plan.intent = " in line and "==" not in line
        ]
        # confirmed_intent re-application + FIX-5 reconciliation (both deleted
        # in Wave D); nothing else may author the plan's intent.
        assert len(writers) == 2, writers


class TestRejectionAtTheShapeBoundary:
    """Gate (a) end-to-end: callers turn the rejection into no-answer."""

    def test_gap_for_nature_returns_none_for_undetermined_treatment(self):
        from app.account_resolution import gap_for_nature

        assert gap_for_nature("Ledger", "ASSET_DISPOSAL", "test") is None
        assert gap_for_nature("Ledger", "OTHER", "test") is None
        assert gap_for_nature("Ledger", None, "test") is None
        assert gap_for_nature("Ledger", "FIXED_ASSET", "test") is not None

    @pytest.mark.asyncio
    async def test_confirmed_account_code_refuses_an_invented_series(self):
        """No seed ⇒ no code, not an invented 6100 expense series."""
        from app.classifier import _confirmed_account_code

        code = await _confirmed_account_code(uuid.uuid4(), "OTHER", "Mystery Ledger")
        assert code == ""


class TestEventTypeDefiniteness:
    """AUDIT_REPORT §12.8 — the study is BLOCKED until this class is green.

    Invariant: every ``event_type`` the reasoning contract offers must have at
    least one canonical intent capable of representing it.  Otherwise a correct
    model answer is miscounted as ``MODEL_NONCANONICAL`` (model error) when the
    real cause is a contract/vocabulary defect.
    """

    @staticmethod
    def _offered_event_types() -> set:
        import re

        from app.accounting_reasoning import _RESPONSE_SHAPE

        match = re.search(r'"event_type":\s*"([^"]+)"', _RESPONSE_SHAPE)
        assert match, "event_type enum missing from the reasoning contract"
        return {value.strip() for value in match.group(1).split("|")}

    def test_every_offered_event_type_has_expressible_coverage(self):
        from app.accounting_vocabulary import EVENT_TYPE_INTENT_COVERAGE

        offered = self._offered_event_types()
        covered = set(EVENT_TYPE_INTENT_COVERAGE)
        assert offered == covered, (
            f"UNCOVERED event_types={sorted(offered - covered)}; "
            f"STALE coverage entries={sorted(covered - offered)}"
        )

    def test_every_coverage_entry_resolves_to_a_canonical_intent(self):
        from app.accounting_vocabulary import (
            EVENT_TYPE_INTENT_COVERAGE,
            is_canonical_intent,
        )

        for event_type, intents in EVENT_TYPE_INTENT_COVERAGE.items():
            assert intents, f"{event_type} has no covering intent"
            for intent in intents:
                assert is_canonical_intent(intent), (event_type, intent)

    def test_model_only_intents_are_canonical_but_not_planner_routable(self):
        """Expressible to the model; NOT wired into the deterministic planner.

        When Wave B/D gives them planner routing, this test fails on purpose —
        the intent must then be reclassified from MODEL_ONLY to COVERED.
        """
        from app import planner
        from app.accounting_vocabulary import CANONICAL_INTENTS, MODEL_ONLY_INTENTS

        assert MODEL_ONLY_INTENTS <= CANONICAL_INTENTS
        planner_intents = {intent for intent, _ in planner._INTENT_PATTERNS}
        overlap = MODEL_ONLY_INTENTS & planner_intents
        assert not overlap, (
            "model-only intents gained planner routing — reclassify as COVERED: "
            + str(sorted(overlap))
        )

    def test_undefined_event_type_is_not_offered(self):
        """``continuation`` existed only in the enum; it must not return."""
        assert "continuation" not in self._offered_event_types()


