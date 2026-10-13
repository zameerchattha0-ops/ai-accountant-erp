"""Live-E2E-caught regressions (run 2026-10-13) — pinned offline, no database.

1. A chart with NO Cost of Sales head failed cost recognition ("ask the
   user to create it") instead of CREATING the missing head — the missing
   prerequisite must be engine-created (ensure_cogs_account).
2. Valuations WITHOUT a prepared journal STILL issued stock: quantity left
   the ledger while the GL never moved (GL/ledger divergence — the one
   failure a perpetual system cannot survive).  _post_cogs_and_issue_stock
   must hard-block the issue unless the COGS journal POSTED.
"""

from __future__ import annotations

import asyncio
import uuid

from app import accounting_engine
from app import tools as app_tools
from app.services import accounting_service, inventory_service

ORG = uuid.UUID("00000000-0000-4000-8000-000000000099")


def _patch_empty_chart(monkeypatch) -> None:
    """resolve_cogs_account sees no CoS ledger anywhere in the chart."""
    from app.repositories import account_repository as a_repo

    async def _no_groups(_org):
        return set()

    async def _no_rows(*_args, **_kwargs):
        return []

    monkeypatch.setattr(a_repo, "get_grouping_account_ids", _no_groups)
    monkeypatch.setattr(a_repo, "search_accounts", _no_rows)


# ---------------------------------------------------------------------------
# ensure_cogs_account — missing-head creation
# ---------------------------------------------------------------------------

def test_ensure_creates_missing_cost_of_sales_head(monkeypatch):
    _patch_empty_chart(monkeypatch)
    from app.repositories import account_repository as a_repo

    created: dict = {}

    async def _code(_org, _base, **_kw):
        return "6010"

    async def _create(**kwargs):
        created.update(kwargs)
        return {
            "id": str(uuid.uuid4()),
            "code": kwargs["code"],
            "name": kwargs["name"],
            "account_type": kwargs["account_type"],
        }

    monkeypatch.setattr(a_repo, "next_available_code", _code)
    monkeypatch.setattr(a_repo, "create_account", _create)

    row = asyncio.run(accounting_engine.ensure_cogs_account(ORG))
    assert row is not None and row["name"] == "Cost of Sales"
    assert created["account_type"] == "EXPENSE"
    assert created["normal_balance"] == "DEBIT"
    # Top-level: no parent invented (and a childless account is postable).
    assert created["parent_account_id"] is None


def test_ensure_returns_existing_ledger_without_creating(monkeypatch):
    from app.repositories import account_repository as a_repo

    existing = {
        "id": str(uuid.uuid4()),
        "account_type": "EXPENSE",
        "name": "Cost of Sales - Goods",
        "is_active": True,
    }

    async def _no_groups(_org):
        return set()

    async def _search(_org, query=None, limit=10):
        return [dict(existing)]

    async def _must_not_create(**_kwargs):
        raise AssertionError("ensure must NOT create when a ledger exists")

    monkeypatch.setattr(a_repo, "get_grouping_account_ids", _no_groups)
    monkeypatch.setattr(a_repo, "search_accounts", _search)
    monkeypatch.setattr(a_repo, "create_account", _must_not_create)

    row = asyncio.run(accounting_engine.ensure_cogs_account(ORG))
    assert row is not None and row["id"] == existing["id"]


def test_ensure_returns_none_when_chart_write_fails(monkeypatch):
    """Creation failure → honest None (caller keeps its warning), never a raise."""
    _patch_empty_chart(monkeypatch)
    from app.repositories import account_repository as a_repo

    async def _code(_org, _base, **_kw):
        return "6010"

    async def _boom(**_kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(a_repo, "next_available_code", _code)
    monkeypatch.setattr(a_repo, "create_account", _boom)

    assert asyncio.run(accounting_engine.ensure_cogs_account(ORG)) is None

# ---------------------------------------------------------------------------
# _post_cogs_and_issue_stock — GL/ledger divergence guard
# ---------------------------------------------------------------------------

def _cogs_lines(n: int = 1) -> list:
    return [
        {"product_id": str(uuid.uuid4()), "quantity": 4, "unit_cost": 1000.0}
        for _ in range(n)
    ]


def test_guard_never_issues_stock_without_prepared_journal(monkeypatch):
    """Valuations but NO journal (the live-caught divergence) → no issue."""
    issued: list = []

    async def _must_not_issue(*_args, **_kwargs):
        raise AssertionError("stock must NOT be relieved without a journal")

    monkeypatch.setattr(inventory_service, "issue_stock", _must_not_issue)

    data = {"cogs_lines": _cogs_lines()}  # no cogs_entry at all
    asyncio.run(
        app_tools._post_cogs_and_issue_stock(ORG, data, source_type="invoice")
    )
    assert issued == []
    assert data["cogs_journal_posted"] is False
    assert data.get("cogs_warning"), "an honest warning must surface"


def test_guard_issues_exactly_once_after_posted_journal(monkeypatch):
    posted: list = []
    issued: list = []

    async def _validate(entry_id):
        posted.append(("validate", entry_id))

    async def _post(entry_id):
        posted.append(("post", entry_id))

    async def _issue(_org, **kwargs):
        issued.append(kwargs)

    monkeypatch.setattr(accounting_service, "validate_journal", _validate)
    monkeypatch.setattr(accounting_service, "post_journal", _post)
    monkeypatch.setattr(inventory_service, "issue_stock", _issue)

    jid = uuid.uuid4()
    data = {
        "id": str(uuid.uuid4()),
        "cogs_entry": {"entry": {"id": str(jid)}},
        "cogs_lines": _cogs_lines(),
    }
    asyncio.run(
        app_tools._post_cogs_and_issue_stock(ORG, data, source_type="invoice")
    )
    assert data["cogs_journal_posted"] is True
    assert ("post", jid) in posted
    assert len(issued) == 1
    assert issued[0]["quantity"] == 4 and issued[0]["unit_cost"] == 1000.0
    assert not data.get("cogs_warning")


def test_guard_blocks_issue_when_post_fails(monkeypatch):
    async def _validate(entry_id):
        return None

    async def _post(entry_id):
        raise RuntimeError("journal is unbalanced")

    async def _must_not_issue(*_args, **_kwargs):
        raise AssertionError("a failed post must never relieve stock")

    monkeypatch.setattr(accounting_service, "validate_journal", _validate)
    monkeypatch.setattr(accounting_service, "post_journal", _post)
    monkeypatch.setattr(inventory_service, "issue_stock", _must_not_issue)

    data = {
        "id": str(uuid.uuid4()),
        "cogs_entry": {"entry": {"id": str(uuid.uuid4())}},
        "cogs_lines": _cogs_lines(),
    }
    asyncio.run(
        app_tools._post_cogs_and_issue_stock(ORG, data, source_type="invoice")
    )
    assert data["cogs_journal_posted"] is False
    assert "could NOT be posted" in str(data.get("cogs_warning", ""))

