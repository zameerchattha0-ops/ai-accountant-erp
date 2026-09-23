"""P1-⑤ (forensic latency report): cross-turn evidence memo + resolution reuse.

Finding: every clarification turn (T2) re-fetched all evidence from scratch
(ReasoningFacts carries no prior rows; only a one-line compact summary was
persisted), and the approval turn re-searched parties during materialization
even though this conversation already resolved them.

Report §7 spec implemented:
* key = (kind, canonical args), scoped by conversation+org queries;
* carrier = the DATABASE (serverless-safe: an in-process cache dies between
  invocations);
* invalidation = reuse ONLY from the latest prior session that PARKED at a
  clarification (parking precedes Phase 6 — structurally mutation-free) and
  carries NO mutation marker (COMPLETED/FAILED included conservatively);
  anything unexpected -> [] = plain refetch (fail-toward-miss);
* party half = substitute declared name-aliases with canonical ids already
  in THIS request's evidence at snapshot time — zero new queries; exact
  single match only; otherwise materialization resolves as before.

Pinned invariants:
* a seeded re-request performs ZERO gather/loader invocations;
* serialize/deserialize round-trips kind+args+records; error rows never
  memoized; corrupt payloads fail soft to [];
* freshness: parked+snapshot -> reuse; mutation marker -> refetch; no park
  -> refetch; only-current-session -> refetch (no step query);
* step writer: payloads with `evidence_full` survive (>2000 chars, valid
  JSON); every other step keeps the original 2000-char cap;
* alias substitution: exact+role -> id (alias popped); missing/ambiguous/
  wrong-role/invoice-role untouched.
"""

import json
import uuid

import pytest

import app.agent as agent_mod
import app.database as db
from app.accounting_reasoning import (
    PROPOSAL,
    ReasoningFacts,
    deserialize_evidence_memo,
    preliminary_extraction,
    run_reasoning_loop,
    serialize_evidence_memo,
)
from app.books_evidence import EvidenceResult
from app.models.schemas import ToolCall

ORG = uuid.UUID("44444444-4444-4444-4444-444444444444")
MSG = "check the books before deciding"


def _needs(kind: str, args: dict | None = None) -> str:
    return json.dumps(
        {"evidence_requests": [{"kind": kind, "why": "need it", "args": args or {}}]}
    )


def _proposal() -> str:
    return json.dumps(
        {
            "understanding": {"economic_event": "party registration", "basis": "t"},
            "proposal": {
                "interpretation": "Create the FDS Labs customer ledger.",
                "affected_records": ["customer"],
                "accounting_impact": [
                    {"account": "Receivable", "debit": 0, "credit": 0, "reason": "x"}
                ],
                "not_affected": [],
                "unresolved_uncertainty": [],
                "tools": [
                    {"tool_name": "create_customer", "arguments": {"name": "FDS Labs Pvt"}}
                ],
                "confirmation": "Create customer FDS Labs Pvt?",
            },
        }
    )


class _Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def generate_text(self, *, prompt: str = ""):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _make_gather():
    calls: list = []

    async def fake(requests, **kw):
        calls.append([r.kind for r in requests])
        return [
            EvidenceResult(
                kind=r.kind, title=f"{r.kind} title", why=r.why,
                records=[{"fetch_call": len(calls)}], source=r.kind,
            )
            for r in requests
        ]

    return fake, calls


def _seeded_row(kind: str = "bank_accounts", args: dict | None = None) -> EvidenceResult:
    row = EvidenceResult(
        kind=kind, title=f"{kind} title", why="from earlier turn",
        records=[{"fetch_call": 0, "kind": kind}], source=kind,
    )
    row.args = dict(args or {})
    return row


class TestSeededLoop:
    @pytest.mark.asyncio
    async def test_seeded_turn_never_touches_the_database(self, monkeypatch):
        """T2 re-asks the same (kind, args) -> ZERO gather invocations."""
        gather_fake, calls = _make_gather()
        monkeypatch.setattr("app.accounting_reasoning.gather_evidence", gather_fake)
        events: list = []
        provider = _Scripted([_needs("bank_accounts"), _proposal()])

        outcome = await run_reasoning_loop(
            ReasoningFacts(user_request=MSG, preliminary=preliminary_extraction(MSG)),
            organization_id=ORG,
            orchestrator=provider,
            offered_tools=["create_customer"],
            tool_contracts={},
            max_rounds=2,
            prior_evidence=[_seeded_row()],
            step_logger=lambda ev, payload: events.append((ev, payload)),
        )

        assert calls == []  # THE metric: no loader/database work at all
        seeded_events = [p for e, p in events if e == "EVIDENCE_SEEDED"]
        assert seeded_events == [{"kinds": ["bank_accounts"]}]
        assert outcome.status == PROPOSAL
        assert outcome.rounds == 2
        assert [r.kind for r in outcome.evidence_results] == ["bank_accounts"]
        # Round-1 prompt has no evidence yet; round-2 (after the cache-hit
        # request) shows the seeded rows AND the same-request note.
        assert "bank_accounts title" not in provider.prompts[0]
        assert "bank_accounts title" in provider.prompts[1]
        assert "served from THIS request's own fetch" in provider.prompts[1]
        # Durable split on the hit round: served, nothing fetched.
        returned = [p for e, p in events if e == "EVIDENCE_RETURNED"]
        assert returned[0]["cached_kinds"] == ["bank_accounts"]
        assert returned[0]["fetched_kinds"] == []

    @pytest.mark.asyncio
    async def test_unseeded_turn_still_fetches_normally(self, monkeypatch):
        """No memo -> behaviour identical to before P1-⑤."""
        gather_fake, calls = _make_gather()
        monkeypatch.setattr("app.accounting_reasoning.gather_evidence", gather_fake)
        events: list = []
        provider = _Scripted([_needs("parties"), _proposal()])

        outcome = await run_reasoning_loop(
            ReasoningFacts(user_request=MSG, preliminary=preliminary_extraction(MSG)),
            organization_id=ORG,
            orchestrator=provider,
            offered_tools=["create_customer"],
            tool_contracts={},
            max_rounds=2,
            step_logger=lambda ev, payload: events.append((ev, payload)),
        )

        assert calls == [["parties"]]
        assert not [e for e, _ in events if e == "EVIDENCE_SEEDED"]
        assert outcome.status == PROPOSAL


class TestMemoSerialization:
    def test_round_trip_preserves_kind_args_and_records(self):
        res = _seeded_row("parties", {"terms": ["FDS"]})
        res.records = [{"id": "c-1", "name": "FDS Labs Pvt", "role": "customer"}]
        # The step writer stores json.dumps(step_data) — mirror that shape.
        payload = json.dumps(
            {"status": "UNSUPPORTED", "rounds": 3,
             "evidence_full": serialize_evidence_memo([res])}
        )
        back = deserialize_evidence_memo(payload)
        assert len(back) == 1
        assert back[0].kind == "parties"
        assert back[0].args == {"terms": ["FDS"]}
        assert back[0].records[0]["id"] == "c-1"
        assert back[0].error is None

    def test_error_rows_never_memoized_and_corruption_fails_soft(self):
        bad = EvidenceResult(kind="x", title="t", error="Lookup failed: boom")
        assert serialize_evidence_memo([bad]) == []
        assert deserialize_evidence_memo("{sheared mid-recor") == []
        assert deserialize_evidence_memo({"unrelated": 1}) == []

    def test_memo_is_bounded(self):
        rows = []
        for i in range(20):
            r = _seeded_row(f"kind_{i}")
            r.records = [{"pad": "x" * 500}]
            rows.append(r)
        out = serialize_evidence_memo(rows)
        assert len(out) <= 12
        assert len(json.dumps({"evidence_full": out}, default=str)) <= 90_000


class TestFreshnessRules:
    """_load_prior_evidence: reuse only a parked, mutation-free snapshot."""

    CURRENT = uuid.UUID("55555555-5555-5555-5555-555555555555")
    CONV = "conv-fresh"

    @staticmethod
    def _memo_payload() -> str:
        return json.dumps(
            {"status": "UNSUPPORTED", "rounds": 3,
             "evidence_full": serialize_evidence_memo([_seeded_row("parties")])}
        )

    def _patch_fetch(self, monkeypatch, *, steps, sessions=None):
        queried: list = []
        _sessions = sessions if sessions is not None else [
            {"id": str(self.CURRENT)}, {"id": "sess-prior"}
        ]

        async def fake_fetch_many(table, filters=None, **kw):
            queried.append(table)
            if table == "ai_execution_sessions":
                return _sessions
            if table == "ai_execution_steps":
                return steps
            return []

        monkeypatch.setattr(agent_mod, "fetch_many", fake_fetch_many)
        return queried

    @pytest.mark.asyncio
    async def test_parked_snapshot_is_reused(self, monkeypatch):
        queried = self._patch_fetch(
            monkeypatch,
            steps=[
                {"description": "RECEIVED", "input_summary": None},
                {"description": "ACCOUNTING_REASONING",
                 "input_summary": self._memo_payload()},
                {"description": "AWAITING_CLARIFICATION", "input_summary": "{}"},
            ],
        )
        out = await agent_mod._load_prior_evidence(
            conversation_id=self.CONV, organization_id=ORG,
            current_session_id=self.CURRENT,
        )
        assert [r.kind for r in out] == ["parties"]
        assert queried == ["ai_execution_sessions", "ai_execution_steps"]

    @pytest.mark.asyncio
    async def test_mutation_marker_invalidates_the_memo(self, monkeypatch):
        """Report §7: invalidated on any mutation — COMPLETED counts."""
        self._patch_fetch(
            monkeypatch,
            steps=[
                {"description": "ACCOUNTING_REASONING",
                 "input_summary": self._memo_payload()},
                {"description": "AWAITING_CLARIFICATION", "input_summary": "{}"},
                {"description": "COMPLETED", "input_summary": "{}"},
            ],
        )
        out = await agent_mod._load_prior_evidence(
            conversation_id=self.CONV, organization_id=ORG,
            current_session_id=self.CURRENT,
        )
        assert out == []

    @pytest.mark.asyncio
    async def test_non_parked_session_yields_no_memo(self, monkeypatch):
        self._patch_fetch(
            monkeypatch,
            steps=[
                {"description": "ACCOUNTING_REASONING",
                 "input_summary": self._memo_payload()},
            ],
        )
        out = await agent_mod._load_prior_evidence(
            conversation_id=self.CONV, organization_id=ORG,
            current_session_id=self.CURRENT,
        )
        assert out == []

    @pytest.mark.asyncio
    async def test_first_turn_skips_step_query_entirely(self, monkeypatch):
        queried = self._patch_fetch(monkeypatch, steps=[], sessions=[
            {"id": str(self.CURRENT)}
        ])
        out = await agent_mod._load_prior_evidence(
            conversation_id=self.CONV, organization_id=ORG,
            current_session_id=self.CURRENT,
        )
        assert out == []
        assert queried == ["ai_execution_sessions"]  # no wasted step query

    @pytest.mark.asyncio
    async def test_corrupt_memo_fails_soft(self, monkeypatch):
        self._patch_fetch(
            monkeypatch,
            steps=[
                {"description": "ACCOUNTING_REASONING",
                 "input_summary": '{"evidence_full": [ BROKEN'},
                {"description": "AWAITING_CLARIFICATION", "input_summary": "{}"},
            ],
        )
        out = await agent_mod._load_prior_evidence(
            conversation_id=self.CONV, organization_id=ORG,
            current_session_id=self.CURRENT,
        )
        assert out == []


class TestAliasSubstitutionFromEvidence:
    """Approval-turn search eliminated: ids come from this turn's evidence."""

    def test_exact_role_match_becomes_canonical_id(self):
        ev = EvidenceResult(
            kind="parties", title="t", source="parties",
            records=[
                {"id": "c-1", "name": "FDS Labs Pvt", "role": "customer"},
                {"id": "c-2", "name": "Acme Corp", "role": "customer"},
            ],
        )
        call = ToolCall(
            tool_name="create_invoice",
            arguments={
                "customer_name": "FDS Labs Pvt",
                "invoice_date": "2026-09-20",
                "items": [],
            },
        )
        fixes = agent_mod._resolve_declared_aliases_from_evidence([call], [ev])
        assert call.arguments.get("customer_id") == "c-1"
        assert "customer_name" not in call.arguments
        assert fixes and fixes[0]["alias"] == "customer_name"
        assert fixes[0]["resolved_id"] == "c-1"

    def test_missing_ambiguous_or_wrong_role_stay_untouched(self):
        ev = EvidenceResult(
            kind="parties", title="t", source="parties",
            records=[
                {"id": "s-1", "name": "FDS Labs Pvt", "role": "supplier"},
                {"id": "c-9", "name": "Dup", "role": "customer"},
                {"id": "c-10", "name": "Dup", "role": "customer"},
            ],
        )
        ghost = ToolCall(tool_name="create_invoice",
                         arguments={"customer_name": "Ghost Co"})
        wrong_role = ToolCall(tool_name="create_invoice",
                              arguments={"customer_name": "FDS Labs Pvt"})
        ambiguous = ToolCall(tool_name="create_invoice",
                             arguments={"customer_name": "Dup"})
        fixes = agent_mod._resolve_declared_aliases_from_evidence(
            [ghost, wrong_role, ambiguous], [ev]
        )
        assert fixes == []
        for c in (ghost, wrong_role, ambiguous):
            assert "customer_id" not in c.arguments
            assert "customer_name" in c.arguments

    def test_invoice_role_and_existing_ids_are_never_touched(self):
        ev = EvidenceResult(kind="parties", title="t", source="parties",
                            records=[{"id": "c-1", "name": "X", "role": "customer"}])
        receipt = ToolCall(
            tool_name="record_customer_receipt",
            arguments={"customer_id": "c-1", "invoice_number": "INV-000005"},
        )
        fixes = agent_mod._resolve_declared_aliases_from_evidence([receipt], [ev])
        assert fixes == []
        assert receipt.arguments["invoice_number"] == "INV-000005"  # role=invoice
        assert receipt.arguments["customer_id"] == "c-1"  # id present -> skip


class TestStepWriterCap:
    @pytest.mark.asyncio
    async def test_memo_payload_survives_but_normal_steps_stay_capped(
        self, monkeypatch
    ):
        captured: list = []

        async def fake_fetch_many(*a, **kw):
            return []

        async def fake_insert_one(table, data=None, **kw):
            captured.append((table, data))
            return data

        monkeypatch.setattr(db, "fetch_many", fake_fetch_many)
        monkeypatch.setattr(db, "insert_one", fake_insert_one)

        big_memo = {"evidence_full": serialize_evidence_memo([_seeded_row()])}
        # Force the memo well past the old 2000-char ceiling.
        big_memo["evidence_full"][0]["result"]["records"] = [{"pad": "y" * 4000}]
        await db.create_execution_step(
            session_id=uuid.uuid4(), step_type="ACCOUNTING_REASONING",
            step_data=big_memo,
        )
        stored = captured[-1][1]["input_summary"]
        assert len(stored) > 2000
        assert json.loads(stored)["evidence_full"]  # valid JSON, memo intact

        await db.create_execution_step(
            session_id=uuid.uuid4(), step_type="RECEIVED",
            step_data={"message": "z" * 5000},
        )
        plain = captured[-1][1]["input_summary"]
        assert len(plain) == 2000  # every other step: original behaviour



