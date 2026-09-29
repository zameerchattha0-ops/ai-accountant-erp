"""Stage 3 — two-call semantic runtime (candidate-only) tests.

Pinned invariants:
* Call 1 owns the semantic intake and NEVER the accounting decision
  (Contract A rejects every decision field; the runtime feeds violations back
  and never repairs them).
* Call 2 owns the accounting interpretation and NEVER authors questions
  (needs[] routes back through Call 1).
* Evidence uses the existing books layer + cache keying; clarification parks
  through the existing mechanism; CONFIG_PERIOD stops deterministically.
* Bounded: at most CALL1_MAX_ROUNDS intake rounds / CALL2_MAX_ATTEMPTS
  decision attempts — no unbounded C1↔C2 loop.
* CANDIDATE ONLY: no tool execution, no financial mutation, no fallback to
  the monolithic interpretation.
* The flag is fail-closed and separate from the observation flag.
"""

import json
import uuid

import pytest

import app.two_call_runtime as tcr
from app.books_evidence import EvidenceResult

ORG = uuid.UUID("66666666-6666-6666-6666-666666666666")
MSG = "record the credit purchase of 3 Dell laptops for 450,000 from FDS Labs Pvt"


class _Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.prompts = []

    async def generate_text(self, *, prompt: str = "", **kw):
        self.calls += 1
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("provider called more times than scripted")
        return self.replies.pop(0)


def intake_reply(*, question=None, evidence=None, event_type="new_event",
                 extra=None) -> str:
    payload = {
        "understanding": {
            "economic_event": "Credit purchase of 3 Dell laptops",
            "what_user_wants": "Record the purchase",
            "basis": "The user's message states supplier, amount and terms.",
            "event_type": event_type,
        },
        "facts": [{"name": "amount", "value": 450000, "state": "EXPLICIT"}],
        "missing_material_facts": [],
        "questionnaire": question,
        "evidence_requests": evidence or [],
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def decision_reply(*, intent="record_credit_purchase", needs=None,
                   proposal=True, refusal=None, complete=False,
                   nature=None, treatment=None, tools=None,
                   extra=None) -> str:
    payload = {
        "decision": {
            "intent": intent,
            "activity": "purchase",
            "document_nature": nature,
            "treatment": treatment,
            "payment_terms": "CREDIT",
            "ledger": {"fit": "NONE", "account_id": None},
            "confidence": "HIGH",
        },
        "prerequisites": [{
            "name": "supplier", "status": "present", "resolution": "reuse",
            "why": "FDS Labs Pvt already exists.",
        }],
        "proposal": None,
        "rationale": "The user described a purchase on credit.",
        "refusal": refusal,
        "complete": complete,
        "needs": needs or [],
    }
    if extra:
        payload.update(extra)
    if proposal and refusal is None and not complete:
        payload["proposal"] = {
            "interpretation": "Record the supplier bill for the laptops.",
            "affected_records": ["purchase_bill"],
            "accounting_impact": [{"account": "Computer equipment",
                                   "debit": 450000, "credit": 0,
                                   "reason": "asset acquired"}],
            "not_affected": [],
            "unresolved_uncertainty": [],
            "tools": tools or [{
                "tool_name": "create_purchase_bill",
                "arguments": {"supplier_name": "FDS Labs Pvt", "total": 450000},
            }],
            "confirmation": "Create the supplier bill for 450,000?",
        }
    return json.dumps(payload)


async def _run(replies, **kw):
    events = []
    provider = _Scripted(replies)
    outcome = await tcr.run_two_call_runtime(
        user_request=MSG,
        organization_id=ORG,
        orchestrator=provider,
        step_logger=lambda event, payload: events.append((event, payload)),
        **kw,
    )
    return outcome, provider, events


def _observations(events):
    return [p for e, p in events if e == tcr.RUNTIME_STEP]


async def _gather_fake(requests, **kw):
    """Read-only stand-in for books_evidence.gather_evidence (no DB)."""
    return [
        EvidenceResult(kind=r.kind, title=f"{r.kind} title", why=r.why,
                       records=[{"n": 1}], source=r.kind)
        for r in requests
    ]


# ---------------------------------------------------------------------------
# Call 1 — semantic intake boundaries (runtime-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call1_decision_field_rejected_then_recovered():
    bad = intake_reply(extra={"decision": {"intent": "record_credit_purchase"}})
    outcome, provider, _ = await _run([bad, intake_reply(), decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 3
    assert "Contract A violations" in provider.prompts[1]
    assert outcome.call1 is not None and "decision" not in outcome.call1


@pytest.mark.asyncio
async def test_call1_forbidden_ledger_rejected_then_recovered():
    bad = intake_reply(extra={"ledger": {"fit": "EXACT"}})
    outcome, provider, _ = await _run([bad, intake_reply(), decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert "forbidden field 'ledger'" in provider.prompts[1]


@pytest.mark.asyncio
async def test_call1_noncanonical_event_type_fed_back():
    bad = intake_reply(event_type="purchase_now")
    outcome, provider, _ = await _run([bad, intake_reply(), decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert "unknown event_type" in provider.prompts[1]


@pytest.mark.asyncio
async def test_call1_invalid_evidence_kind_fed_back_without_retrieval():
    async def gather_boom(*a, **k):
        raise AssertionError("no retrieval for a refused evidence kind")

    bad = intake_reply(evidence=[{"kind": "check_bank_balance", "why": "peek",
                                  "args": {}}])
    outcome, provider, _ = await _run(
        [bad, intake_reply(), decision_reply()], gather=gather_boom
    )
    assert outcome.status == tcr.CANDIDATE_READY
    # Contract A refuses the kind against the closed catalogue — the refusal
    # text is fed back and the books are never queried (gather_boom would
    # have raised and failed the run).
    assert "unknown evidence kind" in provider.prompts[1].lower()


@pytest.mark.asyncio
async def test_call1_parse_failure_fabricates_nothing():
    outcome, provider, _ = await _run(["not json at all"])
    assert outcome.status == tcr.PROVIDER_FAILED
    assert outcome.reason == "call1_unparseable"
    assert outcome.call1 is None and outcome.call2 is None
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_call1_questionnaire_parks_before_call2():
    """A Call-1 fact question parks the turn — Call 2 never runs (§9)."""
    outcome, provider, _ = await _run([
        intake_reply(question={
            "text": "Was this paid on receipt?",
            "questions": [{"field": "payment_type", "kind": "choice",
                           "question": "Paid on receipt?",
                           "options": ["Yes", "No"]}],
        }),
    ])
    assert outcome.status == tcr.AWAITING_CLARIFICATION
    assert provider.calls == 1          # Call 2 never ran
    assert outcome.call2 is None
    assert outcome.required_fields == ["payment_type"]


@pytest.mark.asyncio
async def test_call1_evidence_request_gathers_then_redecides():
    """Call-1 evidence → existing books layer → Call 1 again with the books."""
    wants_evidence = intake_reply(evidence=[{
        "kind": "open_receivables", "why": "find the invoice", "args": {}}])
    outcome, provider, _ = await _run(
        [wants_evidence, intake_reply(), decision_reply()], gather=_gather_fake
    )
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 3          # C1(books) → C1(+evidence) → C2
    assert "open_receivables title" in provider.prompts[1]


# ---------------------------------------------------------------------------
# Call 2 — accounting-decision boundaries (runtime-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call2_noncanonical_intent_fed_back_then_recovered():
    bad = decision_reply(intent="verify_existing_purchase")
    outcome, provider, _ = await _run([intake_reply(), bad, decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 3
    assert "not a canonical intent" in provider.prompts[2]


@pytest.mark.asyncio
async def test_call2_cross_axis_nature_rejected():
    bad = decision_reply(nature="GADGET")
    outcome, provider, _ = await _run([intake_reply(), bad, decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert "Axis-A value" in provider.prompts[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden", ["question", "facts", "evidence_requests"])
async def test_call2_forbidden_intake_fields_rejected(forbidden):
    extra = {forbidden: [] if forbidden == "facts" else {"x": 1}}
    bad = decision_reply(extra=extra)
    outcome, provider, _ = await _run([intake_reply(), bad, decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert f"forbidden field '{forbidden}'" in provider.prompts[2]


@pytest.mark.asyncio
async def test_call2_needs_cannot_name_decision_fields():
    bad = decision_reply(proposal=False, needs=[{
        "kind": "USER_FACT", "name": "treatment",
        "why_required": "The user must supply this.",
    }])
    outcome, provider, _ = await _run([intake_reply(), bad, decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert "decision field" in provider.prompts[2]


@pytest.mark.asyncio
async def test_call2_invalid_prerequisite_resolution_rejected():
    bad = decision_reply(extra={"prerequisites": [{
        "name": "supplier", "status": "missing", "resolution": "ask_or_create",
        "why": "unknown supplier",
    }]})
    outcome, provider, _ = await _run([intake_reply(), bad, decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert "ask_or_create" in provider.prompts[2]


@pytest.mark.asyncio
async def test_call2_proposal_without_intent_rejected():
    payload = json.loads(decision_reply())
    payload["decision"].pop("intent")
    outcome, provider, _ = await _run(
        [intake_reply(), json.dumps(payload), decision_reply()]
    )
    assert outcome.status == tcr.CANDIDATE_READY
    assert "never implied" in provider.prompts[2]


@pytest.mark.asyncio
async def test_proposal_tool_arguments_must_bind():
    bad = decision_reply(tools=[{
        "tool_name": "create_purchase_bill",
        "arguments": {"supplier_name": "FDS", "amount": 450000},  # no such param
    }])
    outcome, provider, _ = await _run([intake_reply(), bad, decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert "is not a parameter of this tool" in provider.prompts[2]


@pytest.mark.asyncio
async def test_ambiguous_ledger_never_takes_a_first_match():
    bad = decision_reply(extra={"decision": {
        **json.loads(decision_reply())["decision"], "ledger": {"fit": "FIRST_MATCH"}}
    })
    outcome, provider, _ = await _run([intake_reply(), bad, decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert "ledger" in provider.prompts[2]


# ---------------------------------------------------------------------------
# needs[] routing (§14) + bounded loop (§15)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_needs_evidence_uses_books_then_call1_again():
    asked = decision_reply(proposal=False, needs=[{
        "kind": "EVIDENCE", "name": "open_receivables",
        "why_required": "Find which invoice the payment settles.",
        "evidence_request": {"kind": "open_receivables",
                             "why": "identify the invoice",
                             "args": {"party_name": "ABC"}},
    }])
    outcome, provider, _ = await _run(
        [intake_reply(), asked, intake_reply(), decision_reply()],
        gather=_gather_fake,
    )
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 4  # C1, C2(need), C1(+books), C2
    assert "open_receivables title" in provider.prompts[2]


@pytest.mark.asyncio
async def test_needs_user_fact_routes_through_call1_questionnaire():
    asked = decision_reply(proposal=False, needs=[{
        "kind": "USER_FACT", "name": "transaction_purpose",
        "why_required": "capital vs operating",
    }])
    questionnaire = {"text": "Are the laptops for business use?",
                     "questions": [{"field": "transaction_purpose",
                                    "kind": "choice",
                                    "question": "Business use?",
                                    "options": ["Business", "Personal"]}]}
    outcome, provider, _ = await _run(
        [intake_reply(), asked, intake_reply(question=questionnaire)]
    )
    assert outcome.status == tcr.AWAITING_CLARIFICATION
    assert provider.calls == 3
    # The wording is CALL 1's — Call 2 never authors questions (§13).
    assert "Are the laptops for business use?" in outcome.question["text"]
    assert outcome.required_fields == ["transaction_purpose"]
    assert outcome.call2 is not None and "question" not in outcome.call2


@pytest.mark.asyncio
async def test_needs_config_period_stops_deterministically():
    asked = decision_reply(proposal=False, needs=[{
        "kind": "CONFIG_PERIOD", "name": "fiscal_period",
        "why_required": "No open period is configured.",
    }])
    outcome, provider, _ = await _run([intake_reply(), asked])
    assert outcome.status == tcr.FAILED
    assert outcome.reason.startswith("config_period_required")
    assert provider.calls == 2
    assert outcome.question is None  # never invented


@pytest.mark.asyncio
async def test_decision_attempts_are_bounded_and_park_honestly():
    fact_need = [{"kind": "USER_FACT", "name": "payment_nature",
                  "why_required": "settlement vs advance"}]
    outcome, provider, _ = await _run([
        intake_reply(),                                    # C1 round 1
        decision_reply(proposal=False, needs=fact_need),   # C2 attempt 1
        intake_reply(),                                    # C1 round 2
        decision_reply(proposal=False, needs=fact_need),   # C2 attempt 2
        intake_reply(),                                    # C1 round 3
    ])
    assert outcome.status == tcr.AWAITING_CLARIFICATION
    assert outcome.decision_attempts == tcr.CALL2_MAX_ATTEMPTS
    assert provider.calls == 5  # nothing was called a sixth time
    assert outcome.required_fields == ["payment_nature"]
    assert "payment_nature" in outcome.question["text"]


@pytest.mark.asyncio
async def test_persistent_contract_violations_fail_honestly():
    bad = decision_reply(intent="verify_existing_purchase")
    outcome, provider, _ = await _run([intake_reply(), bad, bad])
    assert outcome.status == tcr.FAILED
    assert outcome.reason == "decision_attempts_exhausted"
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_intake_rounds_are_bounded():
    intake_with_evidence = intake_reply(evidence=[{
        "kind": "bank_accounts", "why": "check the bank", "args": {}}])
    outcome, provider, _ = await _run(
        [intake_with_evidence] * 3, gather=_gather_fake
    )
    assert outcome.status == tcr.FAILED
    assert outcome.reason == "intake_rounds_exhausted"
    assert provider.calls == tcr.CALL1_MAX_ROUNDS


# ---------------------------------------------------------------------------
# failure philosophy (§22)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call2_parse_failure_executes_nothing():
    outcome, provider, _ = await _run([intake_reply(), "totally not json"])
    assert outcome.status == tcr.PROVIDER_FAILED
    assert outcome.reason == "call2_unparseable"
    assert outcome.candidate is None
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_transport_failure_is_honest():
    class _Boom:
        calls = 0

        async def generate_text(self, *, prompt: str = "", **kw):
            _Boom.calls += 1
            raise RuntimeError("HTTP 503")

    outcome = await tcr.run_two_call_runtime(
        user_request=MSG, organization_id=ORG, orchestrator=_Boom()
    )
    assert outcome.status == tcr.PROVIDER_FAILED
    assert outcome.reason == "call1_transport:RuntimeError"
    assert _Boom.calls == 1  # provider unavailable -> never reinterpreted


@pytest.mark.asyncio
async def test_runtime_error_is_contained(monkeypatch):
    def boom(**kw):
        raise RuntimeError("prompt exploded")

    monkeypatch.setattr(tcr, "build_intake_prompt", boom)
    outcome, provider, _ = await _run([intake_reply()])
    assert outcome.status == tcr.FAILED
    assert outcome.reason == "runtime_error:RuntimeError"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_no_provider_is_fail_closed():
    outcome = await tcr.run_two_call_runtime(
        user_request=MSG, organization_id=ORG, orchestrator=None
    )
    assert outcome.status == tcr.PROVIDER_FAILED
    assert outcome.reason == "no_provider_or_empty_request"


# ---------------------------------------------------------------------------
# observation (§19) — metadata only, never breaking the runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observation_is_metadata_only():
    outcome, _, events = await _run([intake_reply(), decision_reply()])
    payloads = _observations(events)
    assert len(payloads) == 1
    payload = payloads[0]
    for key in ("call_1_status", "call_2_status", "call_1_elapsed_ms",
                "call_2_elapsed_ms", "python_acquisition_ms", "total_elapsed_ms",
                "call_1_field_validity", "call_2_field_validity", "event_type",
                "intent", "document_nature", "treatment", "payment_terms",
                "prerequisite_count", "need_count", "proposal_status"):
        assert key in payload
    assert payload["call_1_status"] == "VALID"
    assert payload["call_2_status"] == "VALID"
    assert payload["proposal_status"] == "VALIDATED"
    assert payload["intent"] == "record_credit_purchase"
    blob = json.dumps(payload)
    assert MSG not in blob and "FDS Labs Pvt" not in blob
    assert len(blob) < 2000
    assert [e for e, _ in events] == [tcr.RUNTIME_STEP, tcr.CANDIDATE_STEP]
    assert "nothing was executed" in dict(events)[tcr.CANDIDATE_STEP]["note"]
    assert outcome.candidate["intent"] == "record_credit_purchase"


@pytest.mark.asyncio
async def test_observation_failure_cannot_break_the_runtime():
    def boom_logger(event, payload):
        raise RuntimeError("audit sink down")

    provider = _Scripted([intake_reply(), decision_reply()])
    outcome = await tcr.run_two_call_runtime(
        user_request=MSG, organization_id=ORG, orchestrator=provider,
        step_logger=boom_logger,
    )
    assert outcome.status == tcr.CANDIDATE_READY  # observation is diagnostic
    assert outcome.candidate["intent"] == "record_credit_purchase"


@pytest.mark.asyncio
async def test_observation_statuses_for_park_and_failure():
    _, _, park_events = await _run([
        intake_reply(question={"text": "Which invoice?",
                               "questions": [{"field": "description",
                                              "kind": "text",
                                              "question": "Which invoice?"}]})
    ])
    park = _observations(park_events)[0]
    assert park["call_1_status"] == "VALID"
    assert park["call_2_status"] == "NOT_REACHED"
    assert park["proposal_status"] == "NONE"

    _, _, fail_events = await _run(["not json"])
    fail = _observations(fail_events)[0]
    assert fail["call_1_status"] == "MODEL_ABSENT"
    assert fail["call_2_status"] == "NOT_REACHED"


# ---------------------------------------------------------------------------
# Validation gaps closed by this audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unregistered_tool_name_rejected_before_the_candidate():
    """The proposal gate must judge the OFFERED tool set, not an empty one.

    ``validate_outcome(offered_tools=())`` skipped the membership check, and
    ``validate_arguments`` cannot judge an unregistered name — so an invented
    tool would have reached the candidate unchallenged.
    """
    invented = decision_reply(tools=[
        {"tool_name": "definitely_not_a_registered_tool", "arguments": {}}
    ])
    outcome, _, _ = await _run([
        intake_reply(),
        invented,          # rejected → fed back
        decision_reply(),  # corrected → candidate
    ])
    assert outcome.status == tcr.CANDIDATE_READY
    assert any("not in the offered tool list" in v for v in outcome.violations)
    assert outcome.decision_attempts == 2


@pytest.mark.asyncio
async def test_empty_provider_reply_is_labelled_truthfully():
    """HTTP 200 with no content is a provider problem, not a JSON problem."""
    # Call 1
    outcome1, _, _ = await _run([""])
    assert outcome1.status == tcr.PROVIDER_FAILED
    assert outcome1.reason == "call1_no_provider_content"

    # Call 2
    outcome2, _, _ = await _run([intake_reply(), ""])
    assert outcome2.status == tcr.PROVIDER_FAILED
    assert outcome2.reason == "call2_no_provider_content"

    # malformed-but-non-empty stays labelled as a parse failure
    outcome3, _, _ = await _run(["not json"])
    assert outcome3.reason == "call1_unparseable"


@pytest.mark.asyncio
async def test_whole_turn_budget_stops_a_chain_of_slow_calls(monkeypatch):
    """§M1: a per-call cap alone let 6 calls chain into ~3 minutes."""
    import asyncio as _aio

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "two_call_runtime_total_timeout", 1.0)
    calls = {"n": 0}

    class _Slow:
        async def generate_text(self, *, prompt: str = "", **kw):
            calls["n"] += 1
            await _aio.sleep(0.8)          # one slow round
            return intake_reply()          # admissible → would run CALL 2 next

    outcome = await tcr.run_two_call_runtime(
        user_request=MSG,
        organization_id=ORG,
        orchestrator=_Slow(),
    )

    assert outcome.status == tcr.FAILED
    assert outcome.reason == "turn_budget_exhausted"
    # it stopped instead of chaining the remaining cycles
    assert calls["n"] == 1
    assert outcome.timings.get("total_ms", 0) > 0


def test_turn_budget_defaults_are_declared_and_bounded():
    from app.config import Settings

    field = Settings.model_fields["two_call_runtime_total_timeout"]
    assert field.default == 60.0


# ---------------------------------------------------------------------------
# §13 — evidence caching inside one turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_prompt_teaches_the_questionnaire_entry_schema():
    """Regression: prompt must name every key Contract A requires.

    Live evidence (Stage 3 audit): the model answered with `name` / `prompt`
    for three consecutive rounds — the prompt never said `field` + `question`
    were required, while ``_validate_questionnaire`` enforces them, so every
    round was rejected and the turn died at ``intake_rounds_exhausted`` after
    34 s of provider time.
    """
    prompt = tcr.build_intake_prompt(user_request=MSG)
    # the required keys are named in the prompt …
    assert '"field"' in prompt
    assert '"question"' in prompt
    # … and the disallowed aliases are called out explicitly
    assert "'name' or 'prompt'" in prompt
    # the accounting-decision guard from Call 2's job is still there
    assert "accounting-decision question" in prompt
    # and the skeleton itself carries an exemplar entry, not an empty list
    assert tcr._CALL1_REPLY_SKELETON["questionnaire"]["questions"][0]["field"]
    assert tcr._CALL1_REPLY_SKELETON["questionnaire"]["questions"][0]["question"]


def test_call1_uses_the_mechanical_fast_tier_and_call2_the_deep_one():
    """The measured fix: CALL 1 must not be sent to a thinking model.

    Live evidence: `generate_text` starts with Token Harbor's thinking model,
    whose reasoning_content consumed the whole 2,048-token cap and returned
    EMPTY content (finish_reason 'length', 8,466 chars of reasoning, 0 chars of
    answer, 20.4 s).  CALL 1 is mechanical intake, so it uses the shipped
    fast-tier entry (`generate_text_light`) AND asks for `tier_first=True` so
    the fast chain actually leads; CALL 2 keeps the deep entry.
    """
    import asyncio

    seen = []

    class _Tiered:
        async def generate_text_light(self, *, prompt: str = "", **kw):
            seen.append(("light", kw.get("tier_first")))
            return intake_reply()

        async def generate_text(self, *, prompt: str = "", **kw):
            seen.append(("deep", kw.get("tier_first")))
            return decision_reply()

    outcome = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        tcr.run_two_call_runtime(
            user_request=MSG, organization_id=ORG, orchestrator=_Tiered()
        )
    )
    assert outcome.status == tcr.CANDIDATE_READY
    # intake on the fast tier with the chain first; decision deep, default order
    assert seen == [("light", True), ("deep", None)], seen


def test_intake_entry_tolerates_a_strict_signature_without_tier_first():
    """An entry with no `tier_first` and no `**kw` still works (older
    orchestrators / strict doubles): the wrapper falls back to the plain call."""
    import asyncio

    class _Strict:
        async def generate_text_light(self, *, prompt: str):
            return intake_reply()

        async def generate_text(self, *, prompt: str):
            return decision_reply()

    outcome = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        tcr.run_two_call_runtime(
            user_request=MSG, organization_id=ORG, orchestrator=_Strict()
        )
    )
    assert outcome.status == tcr.CANDIDATE_READY


@pytest.mark.asyncio
async def test_call1_falls_back_to_the_deep_entry_when_no_light_tier():
    """Every existing orchestrator/test double keeps working unchanged."""
    outcome, provider, _ = await _run([intake_reply(), decision_reply()])
    assert outcome.status == tcr.CANDIDATE_READY
    assert provider.calls == 2


def test_intake_prompt_requires_questionnaire_text_and_forbids_reasking():
    """Live evidence (2026-09-29): round-1 replies were rejected with
    `contract A: questionnaire.text is required` twice, and Call 1 re-asked
    dates/GST the request already stated. The prompt must teach both."""
    intake = tcr.build_intake_prompt(
        user_request=MSG,
        conversation_history=[{"question": "q1", "answer": "a1"}],
    )
    # the required top-level block key
    assert '"text" key' in intake
    # never re-ask what the request or the Q/A history already answers
    assert "NEVER ask for a fact the user request already states" in intake
    assert "Question/answer history already answered" in intake
    # GL codes come from the books, not from the user (live turn 6 asked for
    # five account codes instead of using chart_of_accounts evidence)
    assert "Account and GL-code lookups are BOOKS lookups" in intake
    # accounting-policy asks belong to CALL 2's needs[] (live turns 7-19
    # spiralled on depreciation/code/classification questions)
    assert "Do NOT ask for accounting-POLICY detail" in intake


def test_intake_questionnaire_uses_the_shipped_question_floor():
    """Live 2026-09-29: Call 1 asked unknown fields (asset_capitalization,
    gl_account_code) and re-asked stated facts (supplier_name), spiralling
    12 turns. The shipped validate_authored_questions floor — field
    vocabulary + never-re-ask-known — must run before any park."""
    payload = {
        "understanding": {"economic_event": "x"},
        "facts": [
            {"name": "supplier_name", "value": "FDS Labs Pvt", "state": "EXPLICIT"},
        ],
        "questionnaire": {
            "text": "confirm",
            "questions": [
                {"field": "supplier_name", "kind": "text", "question": "Supplier?"},
                {"field": "gl_account_code", "kind": "text", "question": "GL?"},
                {"field": "transaction_date", "kind": "date", "question": "Date?"},
            ],
        },
    }
    tcr._filter_intake_questionnaire(payload)
    fields = [q["field"] for q in payload["questionnaire"]["questions"]]
    # already-known fact dropped; unknown field dropped; valid gap kept —
    # exactly once even when the model repeats it (live: asset_code x3)
    assert fields == ["transaction_date"], fields


def test_duplicate_model_questions_collapse_to_one_entry():
    payload = {
        "understanding": {"economic_event": "x"},
        "questionnaire": {
            "text": "code?",
            "questions": [
                {"field": "asset_code", "kind": "text", "question": "Code?"},
                {"field": "asset_code", "kind": "text", "question": "Code?"},
                {"field": "asset_code", "kind": "text", "question": "Code?"},
            ],
        },
    }
    tcr._filter_intake_questionnaire(payload)
    assert [q["field"] for q in payload["questionnaire"]["questions"]] == [
        "asset_code"
    ]


def test_all_known_questionnaire_disappears_and_intake_is_admitted():
    """A question Python already knows the answer to never parks the turn."""
    payload = {
        "understanding": {"economic_event": "x"},
        "facts": [
            {"name": "supplier_name", "value": "FDS Labs", "state": "EXPLICIT"},
        ],
        "questionnaire": {
            "text": "confirm supplier",
            "questions": [
                {"field": "supplier_name", "kind": "text", "question": "Supplier?"},
            ],
        },
    }
    tcr._filter_intake_questionnaire(payload)
    assert "questionnaire" not in payload
    assert tcr._intake_admissible(payload)


def test_history_field_answers_are_never_re_asked():
    """Answered fields (history carries field+answer) are filtered out."""
    payload = {
        "understanding": {"economic_event": "x"},
        "questionnaire": {
            "text": "again",
            "questions": [
                {"field": "supplier_name", "kind": "text", "question": "Supplier?"},
                {"field": "payment_type", "kind": "choice", "question": "Pay type?",
                 "options": ["CASH", "CREDIT"]},
            ],
        },
    }
    tcr._filter_intake_questionnaire(
        payload,
        conversation_history=[{"field": "payment_type", "answer": "CREDIT"}],
    )
    fields = [q["field"] for q in payload["questionnaire"]["questions"]]
    assert fields == ["supplier_name"], fields


def test_intake_prompt_names_the_allowed_field_vocabulary():
    """The model can only use field names it has been shown."""
    intake = tcr.build_intake_prompt(user_request=MSG)
    assert "field names: " in intake
    assert "supplier_name" in intake and "capitalization_decision" in intake


def test_both_prompts_state_the_brevity_bounds():
    """Only controlled, precise output: prose costs tokens nobody reads."""
    intake = tcr.build_intake_prompt(user_request=MSG)
    decision = tcr.build_decision_prompt(
        user_request=MSG,
        intake_packet={"understanding": {"economic_event": "x"}},
    )
    assert "BREVITY" in intake and "BREVITY" in decision
    assert "MACHINE-READ" in intake
    assert "ONE sentence" in decision


def test_both_prompts_teach_the_evidence_argument_schema():
    """Regression: the live model used `query`/`topic`/`party` as evidence args.

    The catalogue validator enforces each kind's declared arguments, but the
    prompts listed only KIND NAMES — three rounds of rejections in two separate
    live runs. Both prompts now carry the shipped catalogue text
    (``evidence_catalog_text()``), which names each kind's args.
    """
    intake = tcr.build_intake_prompt(user_request=MSG)
    decision = tcr.build_decision_prompt(
        user_request=MSG,
        intake_packet={"understanding": {"economic_event": "x"}},
    )
    for prompt in (intake, decision):
        # declared argument names are visible …
        assert "terms" in prompt
        # … and the undeclared-argument consequence is stated
        assert "declared argument" in prompt or "declares" in prompt
        # every closed kind is still advertised
    assert "parties" in intake and "chart_of_accounts" in intake


def test_questionnaire_contract_still_requires_field_and_question():
    """The fix taught the prompt; it did NOT weaken the validator."""
    from app.two_call_contracts import validate_semantic_intake_response

    bad = {
        "understanding": {"economic_event": "x", "what_user_wants": "y",
                          "basis": "z", "event_type": "new_event"},
        "facts": [],
        "missing_material_facts": [],
        "evidence_requests": [],
        "questionnaire": {
            "text": "One detail?",
            "questions": [{"name": "amount", "prompt": "How much?"}],
        },
    }
    violations = validate_semantic_intake_response(bad)
    assert any("'field' is required" in v for v in violations)
    assert any("'question' is required" in v for v in violations)


@pytest.mark.asyncio
async def test_repeated_evidence_request_is_served_from_the_turn_cache():
    """§13: an identical re-request must NOT trigger a second fetch.

    The cache is the turn's own dict keyed by ``_evidence_cache_key`` — no
    global ledger cache, and no invalidation is introduced by Stage 3.
    """
    fetched = []

    async def _gather(requests, **kw):
        from app.books_evidence import EvidenceResult

        fetched.append(list(requests))
        return [
            EvidenceResult(
                kind=r.kind, title=f"{r.kind} title", why=r.why,
                records=[{"n": 1}], source=r.kind,
            )
            for r in requests
        ]

    wants = intake_reply(evidence=[
        {"kind": "parties", "why": "vendor exists?", "args": {"terms": ["fds labs"]}},
    ])
    outcome, provider, _ = await _run(
        [wants, wants, intake_reply(), decision_reply()],
        gather=_gather,
    )

    assert outcome.status == tcr.CANDIDATE_READY
    # two identical requests → ONE fetch
    assert len(fetched) == 1, f"cache missed: gather ran {len(fetched)} times"
    assert [r.kind for r in fetched[0]] == ["parties"]
    # and the books were only needed on the first intake round
    assert provider.calls == 4



