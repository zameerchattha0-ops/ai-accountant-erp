"""Evidence-request overflow — §7 of the Stage 3 audit.

Invariant (AUDIT_REPORT §7):

> Every model-requested evidence item must either be preserved, explicitly
> rejected, or explicitly deferred. It must never disappear silently.

The shipped cap ``MAX_REQUESTS_PER_ROUND = 6`` stays at 6 (it bounds one
round's database work and the rendered evidence block); what must change is
that anything requested beyond it is NAMED back to the model.

Regression basis: the §12 study observed a live reply requesting SEVEN kinds
(``account_search, chart_of_accounts, fixed_assets, documents, parties,
bank_accounts, periods``) — the seventh, ``periods``, was dropped with no
trace, and `periods` is the prerequisite that has no resolution path.
"""

import json
import uuid

import pytest

import app.accounting_reasoning as ar
from app.books_evidence import (
    MAX_REQUESTS_PER_ROUND,
    deferred_evidence_requests,
    parse_evidence_requests,
)

ORG = uuid.UUID("66666666-6666-6666-6666-666666666666")
MSG = "record the credit purchase of 3 Dell laptops for 450,000 from FDS Labs Pvt"

#: The exact seven-kind request observed live in the §12 study.
SEVEN_REQUESTS = [
    {"kind": "account_search", "why": "which asset ledgers exist", "args": {"terms": ["computer equipment"]}},
    {"kind": "chart_of_accounts", "why": "ledger structure", "args": {"terms": ["computer"]}},
    {"kind": "fixed_assets", "why": "already registered?", "args": {"terms": ["laptop"]}},
    {"kind": "documents", "why": "already recorded?", "args": {"terms": ["laptop"]}},
    {"kind": "parties", "why": "vendor exists?", "args": {"terms": ["fds labs"]}},
    {"kind": "bank_accounts", "why": "settlement channel", "args": {}},
    {"kind": "periods", "why": "open accounting period", "args": {}},
]


# ---------------------------------------------------------------------------
# The shared helpers (books_evidence)
# ---------------------------------------------------------------------------


def test_seventh_request_is_named_not_dropped():
    """The exact §12 case: the 7th kind must be reported by name."""
    deferred = deferred_evidence_requests(SEVEN_REQUESTS)
    assert deferred == ["periods"], deferred


def test_cap_is_unchanged_fetches_exactly_six():
    """The cap is a bound on work — it must NOT be silently widened."""
    accepted = parse_evidence_requests(SEVEN_REQUESTS)
    assert len(accepted) == MAX_REQUESTS_PER_ROUND == 6
    # the two views are complementary: nothing is counted twice
    assert len(accepted) + len(deferred_evidence_requests(SEVEN_REQUESTS)) == 7


def test_deferred_is_empty_when_within_the_cap():
    assert deferred_evidence_requests(SEVEN_REQUESTS[:6]) == []
    assert deferred_evidence_requests(None) == []
    assert deferred_evidence_requests("not a list") == []


def test_deferred_handles_string_and_kindless_entries():
    filler = [{"kind": f"kind_{i}"} for i in range(MAX_REQUESTS_PER_ROUND)]
    raw = [*filler, {"kind": "periods"}, "PARTIES", {"no_kind": 1}, 42]
    # only entries BEYOND the cap are deferred, each normalised for reporting
    assert deferred_evidence_requests(raw) == [
        "periods", "parties", "(unnamed)", "(unnamed)",
    ]


# ---------------------------------------------------------------------------
# Stage 3 runtime — overflow reaches the model as feedback
# ---------------------------------------------------------------------------


def _intake_with_evidence() -> str:
    payload = {
        "understanding": {
            "economic_event": "Credit purchase of laptops",
            "what_user_wants": "Record the purchase",
            "basis": "Supplier, amount and terms are stated.",
            "event_type": "new_event",
        },
        "facts": [{"name": "amount", "value": 450000, "state": "EXPLICIT"}],
        "missing_material_facts": [],
        "questionnaire": None,
        "evidence_requests": SEVEN_REQUESTS,
    }
    return json.dumps(payload)


@pytest.mark.asyncio
async def test_stage3_reports_the_deferred_seventh_request(monkeypatch):
    """Call 1's 7-request round must not lose `periods` silently."""
    import app.two_call_runtime as tcr
    from test_two_call_runtime import _Scripted, decision_reply

    fetched = []

    async def _gather(requests, **kw):
        from app.books_evidence import EvidenceResult

        fetched.extend(list(requests))
        return [
            EvidenceResult(
                kind=r.kind, title=f"{r.kind} title", why=r.why,
                records=[{"n": 1}], source=r.kind,
            )
            for r in requests
        ]

    provider = _Scripted([
        _intake_with_evidence(),      # round 1: 7 requests
        "not json",                   # round 2: unparseable → honest stop
    ])
    outcome = await tcr.run_two_call_runtime(
        user_request=MSG,
        organization_id=ORG,
        orchestrator=provider,
        gather=_gather,
    )

    # Only the cap's worth of work ran …
    assert len(fetched) == MAX_REQUESTS_PER_ROUND
    assert "periods" not in {r.kind for r in fetched}
    # … and the deferral is EXPLICIT in the next Call 1 prompt.
    assert len(provider.prompts) >= 2
    second_call1 = provider.prompts[1]
    assert "DEFERRED" in second_call1
    assert "periods" in second_call1
    # the runtime stays honest about the unparseable CALL 1 reply (no fabrication)
    assert outcome.status == tcr.PROVIDER_FAILED
    assert outcome.reason == "call1_unparseable"


# ---------------------------------------------------------------------------
# The MONOLITHIC path — where the §12 study actually observed the 7th request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_reasoning_loop_names_deferred_evidence(monkeypatch):
    """Same invariant in ``run_reasoning_loop`` (AUDIT_REPORT §7)."""
    from app.books_evidence import EvidenceResult

    fetched = []

    async def _gather(requests, **kw):
        fetched.extend(list(requests))
        return [
            EvidenceResult(
                kind=r.kind, title=f"{r.kind} title", why=r.why,
                records=[{"n": 1}], source=r.kind,
            )
            for r in requests
        ]

    monkeypatch.setattr(ar, "gather_evidence", _gather)

    prompts = []

    class _Provider:
        async def generate_text(self, *, prompt: str = "", **kw):
            prompts.append(prompt)
            if len(prompts) == 1:
                return json.dumps({"evidence_requests": SEVEN_REQUESTS})
            return json.dumps({"refusal": {"reason": "stop after the books"}})

    outcome = await ar.run_reasoning_loop(
        ar.ReasoningFacts(user_request=MSG, today="2026-09-29"),
        organization_id=ORG,
        orchestrator=_Provider(),
        prefetch_enabled=False,
    )

    # the cap still bounds the round's work …
    assert len(fetched) == MAX_REQUESTS_PER_ROUND
    assert "periods" not in {r.kind for r in fetched}
    # … but round 2 is TOLD about the deferral: nothing vanished silently.
    assert len(prompts) >= 2, "the loop must reassess after gathering"
    assert "DEFERRED" in prompts[1]
    assert "periods" in prompts[1]
    assert outcome is not None and outcome.rounds >= 2
