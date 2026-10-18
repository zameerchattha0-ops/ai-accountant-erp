"""Regression suite - analytics agent ("ask your books", READ-ONLY).

Pins the Odoo-style contract:
* the routing gate sends ONLY question-form messages (imperatives stay on
  the mutation pipeline) and only when the flag is on;
* the planner output is validated against the catalog - unknown sources/
  columns/ops are rejected (and retried ONCE), never executed;
* organization_id is injected by PYTHON - the model cannot widen scope;
* all arithmetic (sum/avg/min/max/count) happens in Python;
* the synthesizer's headline may only use numbers present in the data -
  otherwise the deterministic fallback answers; empty states are honest;
* flag off / provider down -> answer None, the normal turn continues.
Every DB/LLM boundary is stubbed (app/tests/conftest.py contract).
"""
from __future__ import annotations

import asyncio
import json
import uuid

from app.analytics_agent import (
    _aggregate,
    _headline_numbers_ok,
    analytics_gate,
    answer_analytics_question,
    render_markdown,
    validate_plan,
)

_ORG = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


class _StubClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def generate_text_light(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "{}"


def _settings(monkeypatch, **flags):
    from app.config import get_settings

    settings = get_settings()
    for key, value in flags.items():
        monkeypatch.setattr(settings, key, value)
    return settings


# ---------------------------------------------------------------------------
# 1 - ROUTING GATE
# ---------------------------------------------------------------------------

def test_gate_routes_question_forms(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=True)
    for q in ("How much did I buy from Shabbir this month?",
              "What is my cash balance?",
              "Show me my unpaid supplier bills",
              "List all stock products",
              "Total purchases this week",
              "how many invoices did I raise in October?"):
        assert analytics_gate(q) is True, q


def test_gate_rejects_imperatives_and_statements(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=True)
    for q in ("Record a purchase of 2 tables",
              "Create an invoice for Techno",
              "Pay Shabbir 50000",
              "bought 2 tables on credit",
              ""):
        assert analytics_gate(q) is False, q


def test_gate_closed_when_flag_off(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=False)
    assert analytics_gate("What is my cash balance?") is False


# ---------------------------------------------------------------------------
# 2 - PLAN VALIDATION (the catalog cage)
# ---------------------------------------------------------------------------

def _op(**overrides):
    op = {"source": "purchase_bills",
          "columns": ["bill_number", "total"],
          "filters": [{"col": "bill_date", "op": "gte",
                       "value": "2026-10-01"}],
          "limit": 50}
    op.update(overrides)
    return op


def test_valid_plan_passes():
    plan, errors = validate_plan({
        "operations": [_op(aggregate="sum", column="total")],
        "answer_shape": "single_value",
    })
    assert not errors
    assert plan["operations"][0]["aggregate"] == "sum"
    assert plan["answer_shape"] == "single_value"


def test_unknown_source_is_rejected():
    plan, errors = validate_plan({"operations": [_op(source="users passwords")]})
    assert plan is None and any("unknown source" in e for e in errors)


def test_unknown_column_is_rejected():
    plan, errors = validate_plan({"operations": [_op(columns=["secret"]) ]})
    assert plan is None and any("unknown columns" in e for e in errors)


def test_too_many_ops_is_rejected():
    plan, errors = validate_plan({"operations": [_op()] * 4})
    assert plan is None and any("too many" in e for e in errors)


# ---------------------------------------------------------------------------
# 3 - EXECUTOR: org scope injected, arithmetic in Python
# ---------------------------------------------------------------------------

def test_executor_injects_org_scope(monkeypatch):
    """The model can NEVER widen scope - organization_id is added by Python."""
    from app.analytics_agent import execute_plan
    import app.database as db

    captured = {}

    async def _fetch(table, *, filters, select="*", order=None, limit=100,
                     offset=0):
        captured["table"] = table
        captured["filters"] = filters
        return []

    monkeypatch.setattr(db, "fetch_many", _fetch)
    _run(execute_plan(organization_id=_ORG, plan={
        "operations": [{"source": "purchase_bills", "columns": ["total"],
                        "filters": [], "aggregate": None, "column": None,
                        "order": None, "limit": 10}],
        "answer_shape": "table",
    }))
    # fetch_many applies filters as PLAIN equality - the org id goes in
    # WITHOUT an operator prefix (production E2E contract, 2026-10-18).
    assert captured["filters"]["organization_id"] == str(_ORG)


def test_executor_normalizes_order_and_exposes_filter_columns(monkeypatch):
    """E2E catches (2026-10-18): planner says 'bill_date asc' but the seam
    wants 'bill_date.asc'; and filter columns must be SELECTed or the
    Python-side trim drops every row."""
    from app.analytics_agent import execute_plan
    import app.database as db

    captured = {}

    async def _fetch(table, *, filters, select="*", order=None, limit=100,
                     offset=0):
        captured["order"] = order
        captured["select"] = select
        return [{"total": 100.0, "bill_date": "2026-10-18"},
                {"total": 50.0, "bill_date": "2026-09-01"}]

    monkeypatch.setattr(db, "fetch_many", _fetch)
    results = _run(execute_plan(organization_id=_ORG, plan={
        "operations": [{
            "source": "purchase_bills", "columns": ["total"],
            "filters": [{"col": "bill_date", "op": "between",
                         "value": ["2026-10-01", "2026-10-31"]}],
            "aggregate": "sum", "column": "total",
            "order": "bill_date asc", "limit": 50,
        }],
        "answer_shape": "single_value",
    }))
    assert captured["order"] == "bill_date.asc"        # seam format
    assert "bill_date" in captured["select"]           # filter col visible
    assert results[0]["value"] == 100.0                # only October survived


def test_executor_between_window_and_python_trim(monkeypatch):
    from app.analytics_agent import execute_plan
    import app.database as db

    async def _fetch(table, *, filters, select="*", order=None, limit=100,
                     offset=0):
        return [{"total": 100, "bill_date": "2026-10-05"},
                {"total": 900, "bill_date": "2026-11-05"}]  # beyond high

    monkeypatch.setattr(db, "fetch_many", _fetch)
    results = _run(execute_plan(organization_id=_ORG, plan={
        "operations": [{"source": "purchase_bills",
                        "columns": ["total", "bill_date"],
                        "filters": [{"col": "bill_date", "op": "between",
                                     "value": ["2026-10-01", "2026-10-31"]}],
                        "aggregate": None, "column": None, "order": None,
                        "limit": 10}],
        "answer_shape": "table",
    }))
    assert results[0]["rows"] == [{"total": 100, "bill_date": "2026-10-05"}]


def test_aggregates_are_python_computed():
    rows = [{"total": 230000}, {"total": 12000}, {"total": "bad"}]
    assert _aggregate(rows, "sum", "total") == 242000.0
    assert _aggregate(rows, "count", None) == 3
    assert _aggregate(rows, "avg", "total") == 121000.0
    assert _aggregate([], "sum", "total") == 0


# ---------------------------------------------------------------------------
# 4 - SYNTHESIS GUARDS: numbers must come from the data
# ---------------------------------------------------------------------------

def test_headline_guard_accepts_data_numbers():
    allowed = {242000.0, 2.0}
    assert _headline_numbers_ok(
        "You purchased PKR 242,000 across 2 bills in October.", allowed)


def test_headline_guard_rejects_invented_numbers():
    allowed = {242000.0}
    assert not _headline_numbers_ok("Total is 999,999 this month", allowed)
    assert not _headline_numbers_ok("about 5 bills", allowed)


def test_headline_guard_exempts_iso_dates():
    assert _headline_numbers_ok("Bills from 2026-10-01 to 2026-10-18", {7.0})



# ---------------------------------------------------------------------------
# 5 - FULL ROUND TRIP (stubbed client + stubbed DB)
# ---------------------------------------------------------------------------

_PLAN = json.dumps({
    "operations": [{
        "source": "purchase_bills",
        "columns": ["bill_number", "total"],
        "filters": [],
        "aggregate": "sum", "column": "total", "limit": 50,
    }],
    "answer_shape": "single_value",
})


def _wire_db(monkeypatch, rows):
    import app.database as db

    async def _fetch(table, *, filters, select="*", order=None, limit=100,
                     offset=0):
        return list(rows)

    monkeypatch.setattr(db, "fetch_many", _fetch)


def test_flag_off_returns_none(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=False)
    out = _run(answer_analytics_question(
        organization_id=_ORG, question="What is my cash balance?",
        client=AssertionError("must not be called"),
    ))
    assert out["answer"] is None
    assert out["audit"]["llm"] == "skipped_disabled"


def test_happy_path_structured_answer(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=True)
    _wire_db(monkeypatch, [{"bill_number": "PUR-000008", "total": 230000.0},
                           {"bill_number": "PUR-000007", "total": 12000.0}])
    client = _StubClient([
        _PLAN,
        json.dumps({"headline": "Total purchases: 242000 across 2 bills",
                    "answer_type": "single_value", "caveats": []}),
    ])
    out = _run(answer_analytics_question(
        organization_id=_ORG,
        question="How much did I buy in total?", client=client,
    ))
    answer = out["answer"]
    assert answer and answer["synth"] == "llm"
    assert answer["results"][0]["value"] == 242000.0   # Python's number
    assert "242000" in answer["headline"]
    assert "data_as_of" in answer and "period" in answer
    md = render_markdown(answer)
    assert "242000" in md and "Data as of" in md


def test_invented_headline_falls_back_to_deterministic(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=True)
    _wire_db(monkeypatch, [{"total": 230000.0}])
    client = _StubClient([
        _PLAN,
        json.dumps({"headline": "Total is 999999 this month!",
                    "answer_type": "single_value", "caveats": []}),
    ])
    out = _run(answer_analytics_question(
        organization_id=_ORG, question="Total purchases?",
        client=client,
    ))
    assert out["answer"]["synth"] == "fallback"
    assert "230000.0" in out["answer"]["headline"]      # the REAL number


def test_plan_rejected_twice_returns_none(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=True)
    client = _StubClient(["not json", "also not json"])
    out = _run(answer_analytics_question(
        organization_id=_ORG, question="Total purchases?", client=client,
    ))
    assert out["answer"] is None
    assert out["audit"]["llm"] == "plan_rejected"


def test_provider_failure_degrades_to_none(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=True)

    class _Boom:
        async def generate_text_light(self, prompt):
            raise RuntimeError("provider down")

    out = _run(answer_analytics_question(
        organization_id=_ORG, question="Total purchases?", client=_Boom(),
    ))
    assert out["answer"] is None
    assert out["audit"]["llm"] == "failed"


def test_empty_state_is_honest(monkeypatch):
    _settings(monkeypatch, analytics_agent_enabled=True)
    _wire_db(monkeypatch, [])
    client = _StubClient([
        _PLAN,
        json.dumps({"headline": "No purchase bills found",
                    "answer_type": "table",
                    "caveats": ["no records in this period"]}),
    ])
    out = _run(answer_analytics_question(
        organization_id=_ORG, question="Total purchases?", client=client,
    ))
    assert out["answer"]["results"][0]["value"] == 0
    assert "No purchase bills" in out["answer"]["headline"]
    assert out["answer"]["caveats"]



# ---------------------------------------------------------------------------
# 6 - LLM-FIRST ROUTING (the model decides; gate is FALLBACK only)
# ---------------------------------------------------------------------------

def test_router_flag_off_uses_deterministic_gate(monkeypatch):
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=False)
    route, audit = _run(route_message(
        question="What is my cash balance?",
        client=AssertionError("must not be called"),
    ))
    assert route == "analytics" and audit["source"] == "fallback_gate"
    route, _ = _run(route_message(
        question="Record a purchase of 2 tables",
        client=AssertionError("must not be called"),
    ))
    assert route == "record"


def test_router_llm_decides_analytics_over_gate(monkeypatch):
    """The LLM overrides the gate: an imperative-looking phrasing that is
    really a report question goes to analytics."""
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)
    client = _StubClient([json.dumps(
        {"route": "analytics", "reason": "asking for a past total"})])
    route, audit = _run(route_message(
        question="How much did I pay Shabbir last week?", client=client))
    assert route == "analytics"
    assert audit == {"stage": "routing", "source": "llm",
                     "route": "analytics",
                     "reason": "asking for a past total"}


def test_router_llm_decides_record_over_gate(monkeypatch):
    """The LLM overrides the gate the other way: a question-form phrasing
    that is really a command to record goes to the mutation pipeline."""
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)
    client = _StubClient([json.dumps(
        {"route": "record", "reason": "wants a new bill recorded"})])
    route, audit = _run(route_message(
        question="Can you add the 12000 laptop bill from Nita?", client=client))
    assert route == "record" and audit["source"] == "llm"


def test_router_invalid_reply_falls_back_to_gate(monkeypatch):
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)
    client = _StubClient(["no json here"])
    route, audit = _run(route_message(
        question="Show me my unpaid bills", client=client))
    assert route == "analytics"
    assert audit["source"] == "fallback_gate_invalid_reply"


def test_router_provider_failure_falls_back_to_gate(monkeypatch):
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)

    class _Boom:
        async def generate_text_light(self, prompt):
            raise RuntimeError("provider down")

    route, audit = _run(route_message(
        question="Record an expense of 500", client=_Boom()))
    assert route == "record"
    assert audit["source"] == "fallback_gate_unavailable"


def test_router_prompt_is_bounded_and_carries_only_the_message(monkeypatch):
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)
    client = _StubClient([json.dumps({"route": "record", "reason": "x"})])
    _run(route_message(question="Record 2 tables", client=client))
    prompt = client.prompts[0]
    assert "MESSAGE: Record 2 tables" in prompt
    assert "ONLY JSON" in prompt
    assert len(prompt) < 3000          # short call: rules + message only



# ---------------------------------------------------------------------------
# 7 - CLARIFY ROUTE: uncertainty never guesses - ONE targeted question
# ---------------------------------------------------------------------------

def test_router_clarify_carries_targeted_question(monkeypatch):
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)
    target = ("Are you asking how much was paid to Shabbir so far (a "
              "report), or do you want me to record a new payment to "
              "Shabbir?")
    client = _StubClient([json.dumps(
        {"route": "clarify", "reason": "torn between report and payment",
         "question": target})])
    route, audit = _run(route_message(
        question="shabbir payment", client=client))
    assert route == "clarify"
    assert audit["question"] == target
    assert audit["source"] == "llm" and audit["route"] == "clarify"


def test_router_clarify_without_question_falls_back(monkeypatch):
    """A clarify WITHOUT a usable question can never stall the turn."""
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)
    client = _StubClient([json.dumps(
        {"route": "clarify", "reason": "torn", "question": "?"})])
    route, audit = _run(route_message(
        question="Show me my unpaid bills", client=client))
    assert route == "analytics"                      # deterministic fallback
    assert audit["source"] == "fallback_gate_invalid_reply"


def test_router_clarify_rejects_oversized_question(monkeypatch):
    from app.analytics_agent import route_message

    _settings(monkeypatch, llm_router_enabled=True)
    client = _StubClient([json.dumps(
        {"route": "clarify", "reason": "x", "question": "y" * 600})])
    route, audit = _run(route_message(
        question="Record an expense", client=client))
    assert route == "record"                         # deterministic fallback
    assert audit["source"] == "fallback_gate_invalid_reply"

