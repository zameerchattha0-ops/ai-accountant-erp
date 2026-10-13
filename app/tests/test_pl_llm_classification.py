"""AI-assisted P&L section classification (app/pl_llm_classification.py).

Contract under test (mirrors the deployed llm_classification.decide()):
  * flag OFF (the default)  -> no client call, deterministic buckets returned;
  * flag ON + valid reply   -> ambiguous rows MOVE (amounts never change);
  * flag ON + bad reply     -> ignored piecewise, never an exception;
  * any provider failure    -> deterministic buckets returned untouched;
  * AssertionError          -> propagates (no-LLM guards stay loud).

All calls are sync wrappers over asyncio.run() so the suite needs no
async plugin and stays deterministic — no live provider, no live DB.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

import app.pl_structure as pl
from app.config import get_settings
from app.pl_llm_classification import refine_buckets

_settings = get_settings()


def _rows():
    """Three leaves: one revenue, one confidently-classified expense,
    one expense the deterministic pass could only GUESS at ("Rent" has
    no matching phrase → catch-all ``other_operating``)."""
    return [
        {"account_id": "a1", "account_code": "4010",
         "account_name": "Services Revenue", "account_type": "REVENUE",
         "net_amount": -60000.0, "is_group": False},
        {"account_id": "a2", "account_code": "6540",
         "account_name": "Marketing & Advertising", "account_type": "EXPENSE",
         "net_amount": 50000.0, "is_group": False},
        {"account_id": "a3", "account_code": "6210",
         "account_name": "Rent", "account_type": "EXPENSE",
         "net_amount": 25000.0, "is_group": False},
    ]


class _StubClient:
    """Provider stub: canned light-tier reply (or an error to raise)."""

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.prompts = []

    async def generate_text_light(self, *, prompt):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


def _run(buckets, **kw):
    return asyncio.run(refine_buckets(buckets, **kw))


def _total(buckets):
    return round(
        sum(r["amount"] for rows in buckets.values() for r in rows), 2
    )


def _codes(buckets, section):
    return [r["code"] for r in buckets.get(section, [])]


# ---------------------------------------------------------------- flag off

def test_flag_off_never_calls_the_model(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", False)
    buckets = pl.classify_rows(_rows())
    before = json.dumps(buckets, sort_keys=True)
    client = _StubClient(reply='{"assignments": []}')
    out = _run(buckets, client=client)
    assert out is buckets
    assert client.prompts == []
    assert json.dumps(out, sort_keys=True) == before


def test_flag_on_with_no_candidates_makes_no_call(monkeypatch):
    """A chart with only confidently-classified rows → nothing to ask."""
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    rows = [_rows()[1]]  # only "Marketing & Advertising" → selling
    buckets = pl.classify_rows(rows)
    client = _StubClient(reply='{"assignments": []}')
    out = _run(buckets, client=client)
    assert client.prompts == []
    assert _codes(out, "selling_marketing") == ["6540"]


# ------------------------------------------------------------- valid moves

def test_moves_catch_all_expense_and_conserves_amounts(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    before_total = _total(buckets)
    client = _StubClient(reply=(
        '{"assignments": [{"code": "6210", "section": "administrative"}]}'
    ))
    out = _run(buckets, client=client)
    assert _codes(out, "administrative") == ["6210"]
    assert "6210" not in _codes(out, "other_operating")
    # untouched rows stay where they were
    assert _codes(out, "selling_marketing") == ["6540"]
    assert _codes(out, "operating_revenue") == ["4010"]
    # a move can never change a total
    assert _total(out) == before_total
    # the prompt carried the candidates, not the whole chart
    assert "6210" in client.prompts[0]
    assert "6540" not in client.prompts[0]


def test_statement_subtotals_follow_the_moved_row(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    client = _StubClient(reply=(
        '{"assignments": [{"code": "6210", "section": "administrative"}]}'
    ))
    out = _run(buckets, client=client)
    st = pl.build_statement(out)
    # moving between OPERATING categories changes category totals only —
    # gross profit, operating profit and net profit are untouched
    assert st["operating_revenue"] == 60000.0
    assert st["gross_profit"] == 60000.0
    assert st["operating_expenses"]["total"] == 75000.0
    assert st["operating_profit"] == -15000.0
    assert st["net_profit"] == -15000.0


def test_revenue_moved_to_other_income_leaves_gross_profit(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    client = _StubClient(reply=(
        '{"assignments": [{"code": "4010", "section": "other_income"}]}'
    ))
    out = _run(buckets, client=client)
    st = pl.build_statement(out)
    assert _codes(out, "other_income") == ["4010"]
    assert st["operating_revenue"] == 0
    assert st["gross_profit"] == 0
    assert st["other_income"] == 60000.0
    assert st["net_profit"] == -15000.0  # 0 op profit + 60k − 75k opex


# ----------------------------------------------------------- hostile reply

def test_hallucinated_section_is_ignored(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    out = _run(buckets, client=_StubClient(reply=(
        '{"assignments": [{"code": "6210", "section": "ebitda"}]}'
    )))
    assert _codes(out, "other_operating") == ["6210"]


def test_invented_code_is_ignored(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    out = _run(buckets, client=_StubClient(reply=(
        '{"assignments": [{"code": "9999", "section": "administrative"}]}'
    )))
    assert _codes(out, "other_operating") == ["6210"]
    assert _codes(out, "administrative") == []


def test_type_crossing_is_ignored(monkeypatch):
    """An expense can never be pushed ABOVE gross profit, nor a revenue
    line below it."""
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    out = _run(buckets, client=_StubClient(reply=json.dumps(
        {"assignments": [
            {"code": "6210", "section": "operating_revenue"},
            {"code": "4010", "section": "cost_of_sales"},
        ]}
    )))
    assert _codes(out, "other_operating") == ["6210"]
    assert _codes(out, "operating_revenue") == ["4010"]
    assert _codes(out, "cost_of_sales") == []


def test_unparseable_reply_degrades_to_deterministic(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    before = json.dumps(buckets, sort_keys=True)
    out = _run(buckets, client=_StubClient(
        reply="Sorry, I cannot classify these accounts."
    ))
    assert json.dumps(out, sort_keys=True) == before


def test_provider_error_degrades_to_deterministic(monkeypatch):
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    before = json.dumps(buckets, sort_keys=True)
    out = _run(buckets, client=_StubClient(error=RuntimeError("provider down")))
    assert json.dumps(out, sort_keys=True) == before


def test_assertion_error_propagates(monkeypatch):
    """A test's no-LLM guard must never be swallowed (parity with the
    deployed decide())."""
    monkeypatch.setattr(_settings, "llm_pl_enabled", True)
    buckets = pl.classify_rows(_rows())
    with pytest.raises(AssertionError, match="no-LLM guard"):
        _run(buckets, client=_StubClient(error=AssertionError("no-LLM guard")))


# ---------------------------------------------------------- service wiring

def test_service_builds_statement_through_the_refine_seam(monkeypatch):
    """get_profit_loss_statement always returns {rows, statement} — the
    flag being OFF in tests, refine is a pass-through."""
    from app.repositories import report_repository as report_repo
    from app.services import reporting_service

    async def _fake_rows(organization_id, *, limit=500):
        return _rows()

    monkeypatch.setattr(report_repo, "get_income_statement", _fake_rows)
    monkeypatch.setattr(_settings, "llm_pl_enabled", False)
    out = asyncio.run(
        reporting_service.get_profit_loss_statement(uuid.uuid4())
    )
    assert set(out) == {"rows", "statement"}
    st = out["statement"]
    assert st["operating_revenue"] == 60000.0
    assert st["gross_profit"] == 60000.0
    assert st["net_profit"] == -15000.0
    assert st["is_loss"] is True
