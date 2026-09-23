"""P0-③ (forensic latency report): cross-round evidence cache.

Finding: ``run_reasoning_loop`` re-ran every evidence request each round
(``gathered.extend`` with no dedupe).  Production session 3ea794a0
re-requested ``bank_accounts`` in round 3 that round 1 already fetched — a
duplicate database read (+2-4s evidence round) whose rows were then
re-rendered into EVERY later prompt (bloat + model confusion).

Pinned invariants:
* identical (kind, args) requested again in a later round -> ZERO new
  gather/loader invocations; the durable EVIDENCE_RETURNED step carries the
  requested/fetched/cached split (the report's dedupe metric);
* distinct args are NEVER deduped (different reads stay different);
* results carrying an error are never cached — transient failures and
  permission denials retry next round;
* duplicates within ONE round collapse to a single load;
* the served rows are the ORIGINAL fetch's rows (one immutable snapshot per
  request — no mutation can run inside the loop);
* the prompt tells the model a repeated kind came from this request's own
  fetch (no new database read).
"""

import json
import uuid

import pytest

import app.accounting_reasoning as ar
from app.books_evidence import EvidenceResult

ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")
MSG = "check the books before deciding"


def _needs(kind: str, args: dict | None = None) -> str:
    return json.dumps(
        {"evidence_requests": [{"kind": kind, "why": "need it", "args": args or {}}]}
    )


def _needs_twice_same(kind: str) -> str:
    return json.dumps(
        {
            "evidence_requests": [
                {"kind": kind, "why": "need it", "args": {}},
                {"kind": kind, "why": "need it again", "args": {}},
            ]
        }
    )


def _proposal() -> str:
    """A structurally complete PROPOSAL so only the evidence path is judged."""
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


def _make_gather(fail_first: bool = False):
    """Fake gather_evidence recording invocations; rows tagged with the
    fetch call number so a served row provably comes from the first load."""
    calls: list = []

    async def fake(requests, **kw):
        call_no = len(calls) + 1
        calls.append([r.kind for r in requests])
        out = []
        for r in requests:
            if fail_first and call_no == 1:
                out.append(
                    EvidenceResult(
                        kind=r.kind, title=f"{r.kind} title",
                        error="Lookup failed: boom", source=r.kind,
                    )
                )
            else:
                out.append(
                    EvidenceResult(
                        kind=r.kind, title=f"{r.kind} title", why=r.why,
                        records=[{"fetch_call": call_no, "kind": r.kind}],
                        source=r.kind,
                    )
                )
        return out

    return fake, calls


async def _run(monkeypatch, replies, gather_fake, *, max_rounds=3):
    events: list = []
    monkeypatch.setattr("app.accounting_reasoning.gather_evidence", gather_fake)
    provider = _Scripted(replies)
    outcome = await ar.run_reasoning_loop(
        ar.ReasoningFacts(user_request=MSG, preliminary=ar.preliminary_extraction(MSG)),
        organization_id=ORG,
        orchestrator=provider,
        offered_tools=["create_customer"],
        tool_contracts={},
        max_rounds=max_rounds,
        step_logger=lambda ev, payload: events.append((ev, payload)),
    )
    returned = [p for e, p in events if e == "EVIDENCE_RETURNED"]
    return outcome, provider, events, returned


class TestEvidenceRoundCache:
    @pytest.mark.asyncio
    async def test_repeat_request_served_from_cache_without_second_read(self, monkeypatch):
        """The production shape: same (kind, args) asked twice -> ONE load."""
        gather_fake, calls = _make_gather()
        outcome, provider, _, returned = await _run(
            monkeypatch, [_needs("bank_accounts"), _needs("bank_accounts"), _proposal()],
            gather_fake,
        )

        # THE metric: 2 identical requests -> 1 loader invocation.
        assert calls == [["bank_accounts"]]
        assert outcome.status == ar.PROPOSAL
        assert outcome.rounds == 3
        # One snapshot in the accumulated evidence — no duplicate rows.
        assert len(outcome.evidence_results) == 1
        # Durable observability: the requested/fetched/cached split.
        assert returned[0]["fetched_kinds"] == ["bank_accounts"]
        assert returned[0]["cached_kinds"] == []
        assert returned[1]["requested_kinds"] == ["bank_accounts"]
        assert returned[1]["fetched_kinds"] == []
        assert returned[1]["cached_kinds"] == ["bank_accounts"]
        # The prompt labels the repeat as same-request (no new DB read) and
        # renders the kind exactly ONCE in the final round.
        final_prompt = provider.prompts[2]
        assert "served from THIS request's own fetch" in final_prompt
        assert final_prompt.count("bank_accounts title") == 1
        assert "served from THIS request's own fetch" not in provider.prompts[1]

    @pytest.mark.asyncio
    async def test_distinct_args_are_never_deduped(self, monkeypatch):
        """Different reads stay different: same kind, different args."""
        gather_fake, calls = _make_gather()
        outcome, _, _, returned = await _run(
            monkeypatch,
            [
                _needs("parties"),
                _needs("parties", {"terms": ["FDS"]}),
                _proposal(),
            ],
            gather_fake,
        )

        assert calls == [["parties"], ["parties"]]
        assert len(outcome.evidence_results) == 2
        assert returned[1]["fetched_kinds"] == ["parties"]
        assert returned[1]["cached_kinds"] == []

    @pytest.mark.asyncio
    async def test_error_results_are_retried_not_cached(self, monkeypatch):
        """A transient loader failure must NOT be served from cache next
        round — the retry gets a fresh read (and can succeed)."""
        gather_fake, calls = _make_gather(fail_first=True)
        outcome, _, _, returned = await _run(
            monkeypatch,
            [_needs("bank_accounts"), _needs("bank_accounts"), _proposal()],
            gather_fake,
        )

        assert len(calls) == 2  # error was not cached -> round 2 re-fetched
        assert returned[0]["cached_kinds"] == []
        assert returned[1]["fetched_kinds"] == ["bank_accounts"]
        assert returned[1]["cached_kinds"] == []
        assert outcome.status == ar.PROPOSAL

    @pytest.mark.asyncio
    async def test_within_round_duplicates_collapse_to_one_load(self, monkeypatch):
        """Two identical requests in ONE payload -> one load, one snapshot."""
        gather_fake, calls = _make_gather()
        outcome, _, _, _ = await _run(
            monkeypatch,
            [_needs_twice_same("bank_accounts"), _proposal()],
            gather_fake,
            max_rounds=2,
        )

        assert calls == [["bank_accounts"]]
        assert len(outcome.evidence_results) == 1
        assert outcome.status == ar.PROPOSAL


