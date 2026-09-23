"""P1-⑩ (forensic latency report §5): speculative evidence prefetch ∥ R1.

Finding: round 1 always waits out the full model call (measured 7.3s) and
THEN fetches evidence — the common settlement/receipt flow pays model+DB
serially and needs 2 rounds.

Design (report §5): start read-only loaders hinted by preliminary
candidate_subject_areas IN PARALLEL with the round-1 model call; serve them
to the model's round-1 request as LABELLED live evidence; flag-controlled
(`accounting_reasoning_prefetch`, default True in settings; the loop
parameter defaults False so direct/library callers are unchanged).

Pinned invariants:
* round-1 ask of a prefetched kind → EXACTLY one gather invocation (the
  prefetch) — zero extra DB work for the ask, labelled in the prompt and
  as `prefetched_kinds` on EVIDENCE_RETURNED;
* flag off → no EVIDENCE_PREFETCH, ask served by a normal gather;
* mapping is hint-only: registered kinds, ≤3, seeded kinds excluded;
* proposal-in-round-1 → background task completes and is reaped, never
  rendered.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from app.accounting_reasoning import (
    PROPOSAL,
    ReasoningFacts,
    _evidence_cache_key,
    _prefetch_requests,
    run_reasoning_loop,
)
from app.books_evidence import EvidenceRequest, EvidenceResult
from app.config import get_settings

MSG = "check the books"
ORG = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _needs(kind: str) -> str:
    return json.dumps(
        {"evidence_requests": [{"kind": kind, "why": "need it", "args": {}}]}
    )


def _proposal() -> str:
    return json.dumps(
        {
            "understanding": {"economic_event": "party registration", "basis": "t"},
            "proposal": {
                "interpretation": "Create the customer ledger.",
                "affected_records": ["customer"],
                "accounting_impact": [
                    {"account": "Receivable", "debit": 0, "credit": 0, "reason": "x"}
                ],
                "not_affected": [],
                "unresolved_uncertainty": [],
                "tools": [
                    {"tool_name": "create_customer", "arguments": {"name": "FDS"}}
                ],
                "confirmation": "Create customer FDS?",
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


def _fake_gather():
    calls: list = []

    async def fake(requests, **kw):
        calls.append([r.kind for r in requests])
        return [
            EvidenceResult(
                kind=r.kind, title=f"{r.kind} title", why=r.why,
                records=[{"fetch_call": 1}], source=r.kind,
            )
            for r in requests
        ]

    return fake, calls


def test_config_flag_defaults_on():
    assert bool(getattr(get_settings(), "accounting_reasoning_prefetch", False))


def test_mapping_is_capped_registered_and_seed_aware():
    facts = SimpleNamespace(
        preliminary={
            "candidate_subject_areas": [
                "receivables", "payables", "bank", "tax", "loans", "cash",
            ]
        }
    )
    reqs = _prefetch_requests(facts, {})
    # cap 3; unmapped (tax/loans) skipped; bank/cash dedupe to bank_accounts.
    assert [r.kind for r in reqs] == [
        "open_receivables", "open_payables", "bank_accounts",
    ]
    seeded = {
        _evidence_cache_key(EvidenceRequest(kind="open_receivables", why="x")): "x"
    }
    reqs2 = _prefetch_requests(facts, seeded)
    assert [r.kind for r in reqs2] == ["open_payables", "bank_accounts"]


@pytest.mark.asyncio
async def test_round1_ask_served_from_prefetch_with_one_gather(monkeypatch):
    gather_fake, calls = _fake_gather()
    monkeypatch.setattr("app.accounting_reasoning.gather_evidence", gather_fake)
    events: list = []
    provider = _Scripted([_needs("open_receivables"), _proposal()])

    outcome = await run_reasoning_loop(
        ReasoningFacts(
            user_request=MSG,
            preliminary={"candidate_subject_areas": ["receivables"], "literals": {}},
        ),
        organization_id=ORG,
        orchestrator=provider,
        offered_tools=["create_customer"],
        tool_contracts={},
        max_rounds=2,
        prefetch_enabled=True,
        step_logger=lambda ev, payload: events.append((ev, payload)),
    )

    assert outcome.status == PROPOSAL
    # THE metric: one gather total — the prefetch; the ask was free.
    assert calls == [["open_receivables"]]
    assert [p for e, p in events if e == "EVIDENCE_PREFETCH"] == [
        {"kinds": ["open_receivables"]}
    ]
    returned = [p for e, p in events if e == "EVIDENCE_RETURNED"]
    assert returned[0]["prefetched_kinds"] == ["open_receivables"]
    assert returned[0]["fetched_kinds"] == []
    assert "prefetched in parallel" in provider.prompts[1]


@pytest.mark.asyncio
async def test_flag_off_restores_plain_fetch(monkeypatch):
    gather_fake, calls = _fake_gather()
    monkeypatch.setattr("app.accounting_reasoning.gather_evidence", gather_fake)
    events: list = []
    provider = _Scripted([_needs("open_receivables"), _proposal()])

    outcome = await run_reasoning_loop(
        ReasoningFacts(
            user_request=MSG,
            preliminary={"candidate_subject_areas": ["receivables"], "literals": {}},
        ),
        organization_id=ORG,
        orchestrator=provider,
        offered_tools=["create_customer"],
        tool_contracts={},
        max_rounds=2,
        # prefetch_enabled defaults False → library behaviour unchanged
        step_logger=lambda ev, payload: events.append((ev, payload)),
    )

    assert outcome.status == PROPOSAL
    assert not [e for e, _ in events if e == "EVIDENCE_PREFETCH"]
    assert calls == [["open_receivables"]]  # plain miss-path fetch
    returned = [p for e, p in events if e == "EVIDENCE_RETURNED"]
    assert returned[0]["prefetched_kinds"] == []


@pytest.mark.asyncio
async def test_proposal_first_round_reaps_unused_prefetch(monkeypatch):
    gather_fake, calls = _fake_gather()
    monkeypatch.setattr("app.accounting_reasoning.gather_evidence", gather_fake)
    events: list = []
    provider = _Scripted([_proposal()])

    outcome = await run_reasoning_loop(
        ReasoningFacts(
            user_request=MSG,
            preliminary={"candidate_subject_areas": ["receivables"], "literals": {}},
        ),
        organization_id=ORG,
        orchestrator=provider,
        offered_tools=["create_customer"],
        tool_contracts={},
        max_rounds=2,
        prefetch_enabled=True,
        step_logger=lambda ev, payload: events.append((ev, payload)),
    )

    assert outcome.status == PROPOSAL
    assert [e for e, _ in events if e == "EVIDENCE_PREFETCH"]
    # The speculative task completes in the background and is reaped —
    # never rendered, never awaited by the proposal path.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert calls == [["open_receivables"]]

