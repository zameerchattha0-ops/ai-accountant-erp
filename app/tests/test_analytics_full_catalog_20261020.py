"""Full-module analytics catalog + profit capability (2026-10-20).

Verifies the LIVE-VERIFIED schema contract: every business module in the
catalog; the profit recipe (2 journal_lines aggregates, account_type
pseudo-filters, answer_shape computed); pseudo-col joins; Python-only
arithmetic with honest fallbacks.
"""
import asyncio
import json
import uuid

from app.analytics_agent import (
    CATALOG,
    _computed_answer,
    answer_analytics_question,
    execute_plan,
    validate_plan,
)

_ORG = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


def _settings(monkeypatch, **flags):
    from app.config import get_settings

    settings = get_settings()
    for key, value in flags.items():
        monkeypatch.setattr(settings, key, value)
    return settings


class _StubClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def generate_text_light(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "{}"


def _profit_plan():
    return {
        "operations": [
            {"source": "journal_lines", "columns": ["credit", "account_type"],
             "filters": [{"col": "account_type", "op": "eq", "value": "REVENUE"},
                         {"col": "created_at", "op": "gte",
                          "value": "2026-10-01"}],
             "aggregate": "sum", "column": "credit", "order": None,
             "limit": 200},
            {"source": "journal_lines", "columns": ["debit", "account_type"],
             "filters": [{"col": "account_type", "op": "eq", "value": "EXPENSE"},
                         {"col": "created_at", "op": "gte",
                          "value": "2026-10-01"}],
             "aggregate": "sum", "column": "debit", "order": None,
             "limit": 200},
        ],
        "answer_shape": "computed",
        "formula": "op1_minus_op2",
    }


def test_catalog_covers_every_business_module():
    for source in ("invoices", "invoice_items", "credit_notes",
                   "credit_note_items", "purchase_bills",
                   "purchase_bill_items", "purchase_returns",
                   "purchase_return_items", "inventory_movements",
                   "products", "payments", "journal_entries",
                   "journal_lines", "accounts", "customers", "suppliers"):
        assert source in CATALOG, f"module source missing: {source}"
        assert CATALOG[source]["cols"], source


def test_profit_plan_validates():
    plan, errors = validate_plan(_profit_plan())
    assert not errors, errors
    assert plan["answer_shape"] == "computed"
    assert plan["formula"] == "op1_minus_op2"
    assert len(plan["operations"]) == 2


def test_computed_needs_exactly_two_aggregates():
    plan, errors = validate_plan({
        "operations": [{"source": "journal_lines", "columns": ["credit"],
                        "filters": [], "aggregate": "sum", "column": "credit",
                        "order": None, "limit": 10}] * 3,
        "answer_shape": "computed",
    })
    assert plan is None and any("exactly 2" in e for e in errors)


def test_computed_rejects_non_aggregate_and_unknown_formula():
    bad = _profit_plan()
    bad["operations"][0]["aggregate"] = None
    plan, errors = validate_plan(bad)
    assert plan is None and any("aggregate" in e for e in errors)
    bad2 = _profit_plan()
    bad2["formula"] = "op1_times_op2"
    plan2, errors2 = validate_plan(bad2)
    assert plan2 is None and any("unknown formula" in e for e in errors2)


def test_computed_requires_account_type_pins():
    """Live catch 2026-10-20: the model summed ALL credits vs ALL debits
    (balance identity = 0). The guard forces the recipe's filters."""
    bad = _profit_plan()
    bad["operations"][0]["filters"] = [
        {"col": "created_at", "op": "gte", "value": "2026-10-01"}]
    plan, errors = validate_plan(bad)
    assert plan is None and any("account_type" in e for e in errors)


def test_pseudo_cols_accepted_real_columns_still_gated():
    plan, errors = validate_plan({
        "operations": [{"source": "journal_lines",
                        "columns": ["account_code", "account_type", "debit"],
                        "filters": [], "aggregate": None, "column": None,
                        "order": None, "limit": 10}],
        "answer_shape": "table",
    })
    assert not errors, errors
    plan2, errors2 = validate_plan({
        "operations": [{"source": "journal_lines", "columns": ["bogus_col"],
                        "filters": [], "aggregate": None, "column": None,
                        "order": None, "limit": 10}],
        "answer_shape": "table",
    })
    assert plan2 is None and any("unknown columns" in e for e in errors2)


def test_pseudo_join_enriches_and_filters_in_python(monkeypatch):
    import app.database as db

    captured = {}

    async def _fetch(table, *, filters, select="*", order=None, limit=100,
                     offset=0):
        captured.setdefault(table, []).append(
            {"filters": dict(filters), "select": select})
        if table == "journal_lines":
            # The expense row carries a small credit so a BROKEN filter
            # (ignoring account_type) would change the sum (32500 != 32000)
            # and the test could not pass by coincidence (live catch
            # 2026-10-20: the missing eq branch was invisible with
            # zero-credit expense rows).
            rows = [
                {"entry_id": "e1", "account_id": "A-REV", "credit": 24000,
                 "debit": 0, "created_at": "2026-10-10"},
                {"entry_id": "e2", "account_id": "A-EXP", "credit": 500,
                 "debit": 9000, "created_at": "2026-10-12"},
                {"entry_id": "e3", "account_id": "A-REV", "credit": 8000,
                 "debit": 0, "created_at": "2026-10-15"},
            ]
            # HONOR THE SELECT like the real seam does: a row without the
            # requested columns breaks the join (production catch 2026-10-20
            # - account_id was not selected and the profit query returned
            # 0 rows). The unit test must model that faithfully.
            if select != "*":
                wanted = set(select.split(","))
                rows = [{k: v for k, v in r.items() if k in wanted}
                        for r in rows]
            return rows
        if table == "accounts":
            return [
                {"id": "A-REV", "code": "4001", "account_type": "REVENUE"},
                {"id": "A-EXP", "code": "6000", "account_type": "EXPENSE"},
            ]
        return []

    monkeypatch.setattr(db, "fetch_many", _fetch)
    plan, errors = validate_plan(_profit_plan())
    assert not errors
    results = _run(execute_plan(organization_id=_ORG, plan=plan))

    # DB select never contains pseudo-cols; org scope injected by Python.
    for call in captured["journal_lines"]:
        select_cols = call["select"].split(",")
        assert "account_type" not in select_cols
        assert "account_code" not in select_cols
        assert call["filters"]["organization_id"] == str(_ORG)

    # Python-side pseudo filter + aggregation: REVENUE credits 32000,
    # EXPENSE debits 9000.
    assert results[0]["value"] == 32000
    assert results[1]["value"] == 9000


def _agg(value, column, source="journal_lines"):
    return {"aggregate": "sum", "column": column, "value": value,
            "row_count": 3, "source": source}


def test_computed_answer_profit_and_loss():
    profit = _computed_answer(
        question="profit?", results=[_agg(32000, "credit"),
                                     _agg(9000, "debit")])
    assert profit["synth"] == "computed"
    # Business language + formatted money, no raw float / column jargon.
    assert profit["headline"].startswith("Profit of 23,000.00")
    assert "32,000.00" in profit["headline"] and "9,000.00" in profit["headline"]
    # The provenance caveat speaks to the owner, not the developer.
    assert all("Python" not in c and "model" not in c
               for c in profit["caveats"])
    loss = _computed_answer(
        question="profit?", results=[_agg(1000, "credit"),
                                     _agg(9000, "debit")])
    assert loss["headline"].startswith("Loss of 8,000.00")


def test_computed_answer_uses_plan_labels_not_columns():
    """The plan's account_type pins (REVENUE/EXPENSE) become the user-facing
    labels - 'Revenue'/'Expenses', never 'credit'/'debit'."""
    out = _computed_answer(
        question="profit?", results=[_agg(32000, "credit"), _agg(9000, "debit")],
        labels=["Revenue", "Expenses"])
    assert out["headline"] == (
        "Profit of 23,000.00 - Revenue 32,000.00 minus Expenses 9,000.00")


def test_computed_answer_wrong_shape_falls_back():
    r = _computed_answer(question="profit?", results=[_agg(5, "credit")])
    assert r["synth"] == "fallback"
    r2 = _computed_answer(question="profit?",
                          results=[{"source": "x", "rows": [], "row_count": 0},
                                   {"source": "y", "rows": [], "row_count": 0}])
    assert r2["synth"] == "fallback"


def test_answer_pipeline_computed_path_uses_no_synth_call(monkeypatch):
    """End-to-end profit answer: planner stub returns the profit recipe,
    DB stubbed, arithmetic deterministic - the synth LLM call is NEVER
    made (one prompt = the planner only)."""
    import app.database as db

    _settings(monkeypatch, analytics_agent_enabled=True)

    async def _fetch(table, *, filters, select="*", order=None, limit=100,
                     offset=0):
        if table == "journal_lines":
            # Discriminating fixture (see executor test): a broken
            # account_type filter would shift the sums (32500 vs 32000).
            rows = [
                {"entry_id": "1", "account_id": "A-REV", "credit": 24000,
                 "debit": 0, "created_at": "2026-10-10"},
                {"entry_id": "2", "account_id": "A-EXP", "credit": 500,
                 "debit": 9000, "created_at": "2026-10-12"},
                {"entry_id": "3", "account_id": "A-REV", "credit": 8000,
                 "debit": 0, "created_at": "2026-10-15"},
            ]
            if select != "*":  # model the real seam's select projection
                wanted = set(select.split(","))
                rows = [{k: v for k, v in r.items() if k in wanted}
                        for r in rows]
            return rows
        if table == "accounts":
            return [
                {"id": "A-REV", "code": "4001", "account_type": "REVENUE"},
                {"id": "A-EXP", "code": "6000", "account_type": "EXPENSE"},
            ]
        return []

    monkeypatch.setattr(db, "fetch_many", _fetch)
    client = _StubClient([json.dumps({
        "operations": _profit_plan()["operations"],
        "answer_shape": "computed", "formula": "op1_minus_op2",
    })])
    out = _run(answer_analytics_question(
        organization_id=_ORG, question="show me this month profit",
        client=client, timeout=5.0))
    answer = out["answer"]
    assert answer is not None
    assert answer["synth"] == "computed"
    # End-to-end: the plan's REVENUE/EXPENSE pins become the user-facing
    # labels and the money is formatted - no column jargon, no raw floats.
    assert answer["headline"] == (
        "Profit of 23,000.00 - Revenue 32,000.00 minus Expenses 9,000.00")
    assert out["audit"]["llm"] == "computed"
    assert len(client.prompts) == 1
    # The chat summary is MARKDOWN-FREE display text (the card has no
    # markdown engine - live complaint 2026-10-20).
    from app.analytics_agent import render_markdown
    md = render_markdown(answer)
    assert "**" not in md and "`" not in md and "Data as of" in md
    assert "Revenue: 32,000.00 across 2 entries" in md
