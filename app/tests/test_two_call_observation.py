"""Stage 2 — two-call OBSERVATION wiring (diagnostic only, flag-gated).

Pinned invariants (§1–§16 of the Stage 2 spec):

* OFF (the default) → ZERO observation; today's runtime is unchanged;
* ON → exactly one TWO_CALL_OBSERVATION event per parsed authoritative
  response, derived from THAT response — no second provider call;
* the observation never repairs, defaults or propagates anything: an invalid
  projection is RECORDED and the runtime outcome stays byte-identical;
* failures inside the observation boundary are contained — the transaction
  path continues exactly as it was;
* the payload is metadata only (no prompts, no raw completion, no user text).
"""

import json
import uuid
from types import SimpleNamespace

import pytest

import app.accounting_reasoning as ar
import app.two_call_observation as obs
from app.config import Settings, get_settings

ORG = uuid.UUID("88888888-8888-8888-8888-888888888888")
SESSION = uuid.UUID("99999999-9999-9999-9999-999999999999")
MSG = "record the credit purchase of 3 Dell laptops for 450,000 from FDS Labs Pvt"


class _Scripted:
    """Scripted provider — counts calls so 'no extra provider call' is proven."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.prompts = []

    async def generate_text(self, *, prompt: str = "", **kw):
        self.calls += 1
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "{}"


def _proposal_response(intent="record_credit_purchase", nature=None, treatment=None,
                       with_intent=True) -> str:
    decision = {
        "activity": "purchase",
        "document_nature": nature,
        "treatment": treatment,
        "payment_terms": "CREDIT",
        "ledger": {"fit": "NONE", "account_id": None},
        "confidence": "HIGH",
    }
    if with_intent:
        decision["intent"] = intent
    return json.dumps({
        "understanding": {
            "economic_event": "Credit purchase of 3 Dell laptops",
            "what_user_wants": "Record the purchase",
            "basis": "User message states supplier, amount and credit terms.",
            "event_type": "new_event",
        },
        "facts": [{"name": "amount", "value": 450000, "state": "EXPLICIT"}],
        "missing_material_facts": [],
        "question": None,
        "decision": decision,
        "prerequisites": [],
        "proposal": {
            "interpretation": "Record the supplier bill for 3 Dell laptops.",
            "affected_records": ["purchase_bill"],
            "accounting_impact": [
                {"account": "Computer equipment", "debit": 450000, "credit": 0,
                 "reason": "asset acquired"},
            ],
            "not_affected": [],
            "unresolved_uncertainty": [],
            "tools": [{"tool_name": "create_purchase_bill", "arguments": {
                "supplier_name": "FDS Labs Pvt", "amount": 450000}}],
            "confirmation": "Create the supplier bill for 450,000 from FDS Labs Pvt?",
        },
        "rationale": "The user described a credit purchase.",
        "refusal": None,
        "complete": False,
    })


def _question_response() -> str:
    return json.dumps({
        "understanding": {"economic_event": "purchase", "event_type": "new_event"},
        "facts": [],
        "missing_material_facts": [
            {"name": "purpose_of_purchase",
             "why_required": "capital vs operating", "state": "MISSING"}],
        "question": {"text": "One detail is missing.", "questions": [
            {"field": "purpose_of_purchase", "kind": "choice",
             "question": "Business use?", "options": ["Business", "Personal"]}]},
        "decision": {"intent": "record_credit_purchase",
                     "document_nature": None, "treatment": None},
        "prerequisites": [], "proposal": None, "rationale": None,
        "refusal": None, "complete": False,
    })


def _a_only_response() -> str:
    return json.dumps({
        "understanding": {"economic_event": "x", "event_type": "settlement"},
        "facts": [],
        "missing_material_facts": [],
    })


def _bad_evidence_response() -> str:
    return json.dumps({
        "understanding": {"event_type": "settlement"},
        "evidence_requests": [
            {"kind": "check_bank_balance", "why": "peek", "args": {}}],
    })


async def _run(replies, *, offered=("create_purchase_bill",), max_rounds=2,
               step_logger=None):
    events: list = []
    provider = _Scripted(replies)
    outcome = await ar.run_reasoning_loop(
        ar.ReasoningFacts(user_request=MSG, preliminary=ar.preliminary_extraction(MSG)),
        organization_id=ORG,
        orchestrator=provider,
        offered_tools=list(offered),
        tool_contracts={},
        max_rounds=max_rounds,
        step_logger=step_logger or (lambda ev, payload: events.append((ev, payload))),
    )
    return outcome, provider, events


def _observations(events):
    return [p for e, p in events if e == obs.OBSERVATION_TYPE]


@pytest.fixture
def flag(monkeypatch):
    """Toggle the Stage 2 flag on the cached settings object (conftest style)."""
    def _set(value: bool):
        monkeypatch.setattr(get_settings(), "two_call_observation_enabled", value)
    return _set


# ---------------------------------------------------------------------------
# §3 — the flag: default OFF, fail-closed
# ---------------------------------------------------------------------------


def test_flag_default_is_off_fail_closed():
    assert Settings.model_fields["two_call_observation_enabled"].default is False
    assert get_settings().two_call_observation_enabled is False


@pytest.mark.asyncio
async def test_flag_off_records_no_observation(flag):
    flag(False)
    outcome, provider, events = await _run([_proposal_response()])
    assert outcome.status == ar.PROPOSAL
    assert provider.calls == 1
    assert [e for e, _ in events] == ["REASONING_DECISION"]
    assert _observations(events) == []


@pytest.mark.asyncio
async def test_missing_flag_attribute_is_disabled(monkeypatch):
    # fail-closed: no attribute -> disabled (as if the setting never existed)
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace())
    outcome, provider, events = await _run([_proposal_response()])
    assert outcome.status == ar.PROPOSAL
    assert provider.calls == 1
    assert _observations(events) == []


@pytest.mark.asyncio
async def test_flag_on_records_observation_without_extra_provider_call(flag):
    flag(False)
    _, prov_off, _ = await _run([_proposal_response()])
    flag(True)
    on, prov_on, events = await _run([_proposal_response()])

    payloads = _observations(events)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["observation_type"] == obs.OBSERVATION_TYPE
    assert payload["round"] == 1
    assert isinstance(payload["elapsed_ms"], int) and payload["elapsed_ms"] >= 0
    assert payload["category"] == "A_AND_B_VALID"
    assert payload["a_status"] == "VALID"
    assert payload["b_status"] == "VALID"
    assert payload["intent_result"] == "AGREEMENT"
    assert payload["intent"] == "record_credit_purchase"
    assert payload["event_type"] == "new_event"
    assert payload["violation_count"] == 0
    # NO ADDITIONAL LLM CALL — identical provider call counts and prompts
    assert prov_on.calls == 1 == prov_off.calls
    assert prov_on.prompts == prov_off.prompts


@pytest.mark.asyncio
async def test_runtime_equivalence_off_vs_on(flag):
    """§16 — the ONLY permitted difference is observation telemetry."""
    flag(False)
    off, prov_off, _ = await _run([_proposal_response()])
    flag(True)
    on, prov_on, events = await _run([_proposal_response()])

    assert on.as_dict() == off.as_dict()
    assert ar.proposed_mutation_tools(on) == ar.proposed_mutation_tools(off) != []
    assert on.proposal == off.proposal
    assert on.question == off.question
    assert on.status == off.status
    assert prov_on.calls == prov_off.calls == 1
    assert _observations(events)  # telemetry present on the ON run only


@pytest.mark.asyncio
async def test_observation_failure_is_contained(flag, monkeypatch):
    flag(False)
    baseline, _, _ = await _run([_proposal_response()])
    flag(True)

    def boom(*a, **k):
        raise RuntimeError("projection exploded")

    monkeypatch.setattr(obs, "build_two_call_observation", boom)
    outcome, provider, events = await _run([_proposal_response()])
    assert outcome.status == ar.PROPOSAL
    assert outcome.as_dict() == baseline.as_dict()
    assert provider.calls == 1
    assert _observations(events) == []


@pytest.mark.asyncio
async def test_observation_notify_failure_is_contained_and_later_events_survive(flag):
    """§4 — an exception while emitting the observation must not change the run."""
    flag(True)
    seen: list = []

    def selective_logger(ev, payload):
        if ev == obs.OBSERVATION_TYPE:
            raise RuntimeError("observation sink down")
        seen.append(ev)

    outcome, provider, _ = await _run([_proposal_response()], step_logger=selective_logger)
    assert outcome.status == ar.PROPOSAL
    assert provider.calls == 1
    assert seen == ["REASONING_DECISION"]  # the normal audit trail is intact
    assert outcome.decision.get("intent") == "record_credit_purchase"


@pytest.mark.asyncio
async def test_step_logger_failure_adds_no_new_surface(flag):
    """A step_logger that raises behaves IDENTICALLY with the flag off and on.

    NOTE (reported, not fixed here): ``_notify``'s own containment handler calls
    ``log.warning(..., event=event)``, which collides with structlog's ``event``
    parameter and therefore raises too — a PRE-EXISTING latent defect outside
    Stage 2's scope.  Stage 2 must simply not add a new failure surface: the ON
    propagation must be byte-identical to the OFF propagation.
    """
    def boom_logger(ev, payload):
        raise RuntimeError("audit sink down")

    flag(False)
    with pytest.raises(Exception) as off_exc:
        await _run([_proposal_response()], step_logger=boom_logger)
    flag(True)
    with pytest.raises(Exception) as on_exc:
        await _run([_proposal_response()], step_logger=boom_logger)
    assert type(on_exc.value) is type(off_exc.value)
    assert str(on_exc.value) == str(off_exc.value)



# ---------------------------------------------------------------------------
# §7–§11 — projection is not normalization: recorded, never repaired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noncanonical_intent_observed_not_enforced(flag):
    fixture = _proposal_response(intent="verify_existing_purchase")
    flag(False)
    off, _, _ = await _run([fixture])
    flag(True)
    on, _, events = await _run([fixture])

    payload = _observations(events)[0]
    assert payload["intent_result"] == "MODEL_NONCANONICAL"
    assert payload["intent"] == "verify_existing_purchase"
    assert payload["b_status"] == "INVALID"
    assert any("canonical" in v for v in payload["b_violations"])
    # the runtime intent is untouched — observation never rewrites it
    assert on.decision.get("intent") == "verify_existing_purchase"
    assert on.as_dict() == off.as_dict()
    assert ar.proposed_mutation_tools(on) == ar.proposed_mutation_tools(off)


@pytest.mark.asyncio
async def test_invalid_nature_no_repair_observation_only(flag):
    fixture = _proposal_response(nature="GADGET", treatment="OPERATING_EXPENSE_MAYBE")
    flag(False)
    off, _, _ = await _run([fixture])
    flag(True)
    on, _, events = await _run([fixture])

    payload = _observations(events)[0]
    assert payload["nature_valid"] is False
    assert payload["treatment_valid"] is False
    assert payload["document_nature"] == "GADGET"
    assert payload["treatment"] == "OPERATING_EXPENSE_MAYBE"
    # no fallback: the values stay verbatim in the runtime decision too
    assert on.decision.get("document_nature") == "GADGET"
    assert on.decision.get("treatment") == "OPERATING_EXPENSE_MAYBE"
    assert on.as_dict() == off.as_dict()


@pytest.mark.asyncio
async def test_proposal_without_intent_observation_only(flag):
    fixture = _proposal_response(with_intent=False)
    flag(False)
    off, _, _ = await _run([fixture])
    flag(True)
    on, provider, events = await _run([fixture])

    payload = _observations(events)[0]
    assert payload["intent_result"] == "MODEL_ABSENT"
    assert payload["b_status"] == "INVALID"
    assert any("never implied" in v for v in payload["b_violations"])
    # today's runtime still produces the proposal — observation is diagnostic
    assert on.status == ar.PROPOSAL
    assert on.as_dict() == off.as_dict()
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_invalid_evidence_kind_observed_no_retrieval(flag, monkeypatch):
    async def gather_boom(*a, **k):
        raise AssertionError("evidence retrieval must not run for an invalid kind")

    monkeypatch.setattr(ar, "gather_evidence", gather_boom)
    flag(True)
    outcome, provider, events = await _run(
        [_bad_evidence_response(), _proposal_response()], max_rounds=2
    )

    payloads = _observations(events)
    assert len(payloads) == 2  # one per parsed response
    first = payloads[0]
    assert first["category"] == "A_INVALID"
    assert first["b_status"] == "MODEL_ABSENT"
    assert any("Unknown evidence kind" in v for v in first["evidence_invalid"])
    # the loop rejected the request exactly as it always has and moved on
    assert outcome.status == ar.PROPOSAL
    assert outcome.rounds == 2
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_absent_side_is_model_absent_not_manufactured(flag):
    flag(True)
    outcome, _, events = await _run([_a_only_response()])
    payload = _observations(events)[0]
    assert payload["category"] == "A_VALID"
    assert payload["a_status"] == "VALID"
    assert payload["b_status"] == "MODEL_ABSENT"
    assert payload["b_fields"] == []
    assert payload["intent_result"] == "MODEL_ABSENT"
    assert outcome.status == ar.UNSUPPORTED  # unchanged runtime status


@pytest.mark.asyncio
async def test_question_observation_is_metadata_only(flag):
    flag(True)
    outcome, _, events = await _run([_question_response()])
    payload = _observations(events)[0]
    assert payload["question_present"] is True
    assert payload["question_valid"] is True
    assert payload["question_fields"] == ["purpose_of_purchase"]
    assert payload["question_kinds"] == ["choice"]
    assert payload["question_options_provided"] is True
    # the runtime question is untouched
    assert outcome.question["text"] == "One detail is missing."
    # metadata only: no question text, no user message, no prompt, no secrets
    blob = json.dumps(payload)
    assert "Business use?" not in blob
    assert MSG not in blob
    assert "3 Dell laptops" not in blob
    for forbidden_key in ("prompt", "raw", "content", "confirmation",
                          "rationale", "api_key", "organization_id"):
        assert forbidden_key not in payload
    assert len(blob) < 3000


@pytest.mark.asyncio
async def test_telemetry_marker_persists_like_intent_comparison(monkeypatch):
    """The marker rides the existing _log_step mechanism (free-form style)."""
    import app.agent as agent_mod
    import app.database as db

    assert obs.OBSERVATION_TYPE not in db._STEP_TYPE_MAP  # free-form marker
    assert obs.OBSERVATION_TYPE not in agent_mod._MUTATION_STEP_MARKERS

    captured: list = []

    async def fake_create(*, session_id, step_type, step_data, status="COMPLETED"):
        captured.append((step_type, step_data))
        return {}

    monkeypatch.setattr(agent_mod, "create_execution_step", fake_create)
    await agent_mod._log_step(
        SESSION, obs.OBSERVATION_TYPE, {"category": "A_AND_B_VALID"}
    )
    await agent_mod.flush_step_logs()

    assert captured and captured[0][0] == obs.OBSERVATION_TYPE
    assert captured[0][1]["category"] == "A_AND_B_VALID"


def test_observation_payload_stays_under_the_step_cap():
    """The payload must never be sheared by create_execution_step (2000 chars).

    A sheared payload is invalid JSON and the SQL shear-guard drops the row, so
    the builder deterministically trims violation ARRAYS (counts keep the full
    truth) until it fits.
    """
    junk = {("junk_%d" % i): i for i in range(8)}
    fixture = {
        **junk,
        "understanding": {"event_type": "settlement"},
        "facts": "not-a-list",
        "missing_material_facts": 7,
        "question": 123,
        "decision": {
            "intent": "verify_existing_purchase",
            "document_nature": "N" * 120,
            "treatment": "T" * 120,
            "ledger": {"fit": "WEIRD"},
            "confidence": "CERTAIN",
            "bad_extra": 1,
        },
        "prerequisites": [{"resolution": "ask_or_create"}],
        "proposal": {"tools": [{"tool_name": "x", "arguments": {}}]},
        "rationale": "r",
        "complete": "yes",
        "needs": [{"kind": "USER_FACT", "name": "treatment",
                   "why_required": "supply it"}],
    }
    payload = obs.build_two_call_observation(fixture)
    blob = json.dumps(payload, default=str)
    assert len(blob) <= 2000
    json.loads(blob)  # valid JSON by construction
    assert payload["violation_count"] == (
        payload["a_violation_count"] + payload["b_violation_count"]
    )
    assert payload["violation_count"] > 4  # counts keep the full truth
    assert len(payload["a_violations"]) <= 8
    assert len(payload["b_violations"]) <= 8



