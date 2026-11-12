"""Tests for idempotent fresh-organization prerequisites provisioning."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from app.services import org_prerequisites
from app.services.org_prerequisites import (
    ensure_org_prerequisites,
    ensure_org_prerequisites_safe,
)


class _FakeQuery:
    def __init__(self, store: Dict[str, List[Dict[str, Any]]], table: str) -> None:
        self._store = store
        self._table = table
        self._op = "select"
        self._filters: Dict[str, Any] = {}
        self._limit: int | None = None
        self._insert_data: Dict[str, Any] | None = None

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        self._op = "select"
        return self

    def insert(self, data: Dict[str, Any]) -> "_FakeQuery":
        self._op = "insert"
        self._insert_data = dict(data)
        return self

    def eq(self, key: str, value: Any) -> "_FakeQuery":
        self._filters[key] = value
        return self

    def limit(self, count: int) -> "_FakeQuery":
        self._limit = count
        return self

    def execute(self) -> SimpleNamespace:
        rows = self._store.setdefault(self._table, [])
        if self._op == "insert":
            assert self._insert_data is not None
            row = dict(self._insert_data)
            row.setdefault("id", str(uuid.uuid4()))
            rows.append(row)
            return SimpleNamespace(data=[row])

        matched = [
            r for r in rows
            if all(r.get(k) == v for k, v in self._filters.items())
        ]
        if self._limit is not None:
            matched = matched[: self._limit]
        return SimpleNamespace(data=[dict(r) for r in matched])


class FakeSupabaseClient:
    """Minimal in-memory Supabase-like client for org_prerequisites tests."""

    def __init__(self, initial: Dict[str, List[Dict[str, Any]]] | None = None) -> None:
        self.store: Dict[str, List[Dict[str, Any]]] = {
            "accounts": [],
            "bank_accounts": [],
            "cash_accounts": [],
            "financial_years": [],
            "accounting_periods": [],
        }
        if initial:
            for k, v in initial.items():
                self.store[k] = [dict(r) for r in v]

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self.store, name)


@pytest.mark.asyncio
async def test_ensure_org_prerequisites_provisions_fresh_org_with_client():
    org_id = str(uuid.uuid4())
    client = FakeSupabaseClient()

    res = await ensure_org_prerequisites(org_id, client=client)

    assert res["organization_id"] == org_id
    assert res["status"] == "ready"
    assert res["errors"] == {}

    expected_keys = {
        "cash_gl",
        "cash_account",
        "bank_gl",
        "bank_account",
        "accounts_receivable",
        "accounts_payable",
        "clearing_suspense",
        "gst_output_payable",
        "gst_input_claimable",
        "wht_payable_153",
        "accounting_period",
    }
    assert expected_keys.issubset(set(res["provisioned"]))
    assert res["already_present"] == []

    # Verify linked bank & cash records + open period
    assert len(client.store["bank_accounts"]) == 1
    assert client.store["bank_accounts"][0]["gl_account_id"] == res["bank_gl"]["id"]
    assert client.store["bank_accounts"][0]["is_default"] is True

    assert len(client.store["cash_accounts"]) == 1
    assert client.store["cash_accounts"][0]["gl_account_id"] == res["cash_gl"]["id"]

    assert len(client.store["financial_years"]) == 1
    assert len(client.store["accounting_periods"]) == 1
    assert client.store["accounting_periods"][0]["status"] == "OPEN"


@pytest.mark.asyncio
async def test_ensure_org_prerequisites_is_idempotent():
    org_id = str(uuid.uuid4())
    client = FakeSupabaseClient()

    first = await ensure_org_prerequisites(org_id, client=client)
    counts_after_first = {k: len(v) for k, v in client.store.items()}

    second = await ensure_org_prerequisites(org_id, client=client)
    counts_after_second = {k: len(v) for k, v in client.store.items()}

    assert first["provisioned"]
    assert second["provisioned"] == []
    assert set(second["already_present"]) == set(first["provisioned"])
    assert counts_after_second == counts_after_first


@pytest.mark.asyncio
async def test_ensure_org_prerequisites_fills_only_missing_items():
    org_id = str(uuid.uuid4())
    fy_id = str(uuid.uuid4())
    cash_gl_id = str(uuid.uuid4())
    ar_id = str(uuid.uuid4())
    ap_id = str(uuid.uuid4())

    client = FakeSupabaseClient(
        {
            "accounts": [
                {
                    "id": cash_gl_id,
                    "organization_id": org_id,
                    "code": "1110",
                    "name": "Cash in Hand",
                    "account_type": "ASSET",
                    "normal_balance": "DEBIT",
                    "is_active": True,
                },
                {
                    "id": ar_id,
                    "organization_id": org_id,
                    "code": "1100",
                    "name": "Accounts Receivable",
                    "account_type": "ASSET",
                    "normal_balance": "DEBIT",
                    "is_active": True,
                },
                {
                    "id": ap_id,
                    "organization_id": org_id,
                    "code": "2010",
                    "name": "Accounts Payable",
                    "account_type": "LIABILITY",
                    "normal_balance": "CREDIT",
                    "is_active": True,
                },
            ],
            "financial_years": [
                {
                    "id": fy_id,
                    "organization_id": org_id,
                    "name": "FY 2026",
                    "start_date": "2026-01-01",
                    "end_date": "2026-12-31",
                    "status": "OPEN",
                    "is_current": True,
                }
            ],
            "accounting_periods": [
                {
                    "id": str(uuid.uuid4()),
                    "organization_id": org_id,
                    "financial_year_id": fy_id,
                    "period_number": 11,
                    "name": "November 2026",
                    "start_date": "2026-11-01",
                    "end_date": "2026-11-30",
                    "status": "OPEN",
                }
            ],
            # 0 bank_accounts, 0 cash_accounts, missing clearing/GST/WHT
        }
    )

    res = await ensure_org_prerequisites(org_id, client=client)

    assert "cash_gl" in res["already_present"]
    assert "accounts_receivable" in res["already_present"]
    assert "accounts_payable" in res["already_present"]
    assert "accounting_period" in res["already_present"]

    assert "cash_account" in res["provisioned"]
    assert "bank_gl" in res["provisioned"]
    assert "bank_account" in res["provisioned"]
    assert "clearing_suspense" in res["provisioned"]
    assert "gst_output_payable" in res["provisioned"]
    assert "gst_input_claimable" in res["provisioned"]
    assert "wht_payable_153" in res["provisioned"]
    assert res["cash_account"]["gl_account_id"] == cash_gl_id


@pytest.mark.asyncio
async def test_ensure_org_prerequisites_repo_path_zero_bank_accounts(monkeypatch):
    org_id = uuid.uuid4()
    bank_gl_id = uuid.uuid4()
    cash_gl_id = uuid.uuid4()

    created_accounts: List[Dict[str, Any]] = []

    async def fake_get_coa(_org_id, **_kw):
        return [
            {
                "id": str(cash_gl_id),
                "code": "1110",
                "name": "Cash",
                "account_type": "ASSET",
                "is_active": True,
            },
            {
                "id": str(uuid.uuid4()),
                "code": "1100",
                "name": "Accounts Receivable",
                "account_type": "ASSET",
                "is_active": True,
            },
            {
                "id": str(uuid.uuid4()),
                "code": "2010",
                "name": "Accounts Payable",
                "account_type": "LIABILITY",
                "is_active": True,
            },
        ] + created_accounts

    async def fake_create_account(**kwargs):
        row = {
            "id": str(uuid.uuid4()),
            "code": kwargs["code"],
            "name": kwargs["name"],
            "account_type": kwargs["account_type"],
            "is_active": True,
        }
        created_accounts.append(row)
        return row

    async def fake_ensure_bank(_org_id, **_kw):
        return {
            "id": str(uuid.uuid4()),
            "account_name": "Primary Bank - Main",
            "gl_account_id": str(bank_gl_id),
            "bank_account_created": True,
        }

    monkeypatch.setattr(org_prerequisites.acct_repo, "get_chart_of_accounts", fake_get_coa)
    monkeypatch.setattr(
        org_prerequisites.acct_repo,
        "next_available_code",
        AsyncMock(side_effect=lambda _org, c: c),
    )
    monkeypatch.setattr(org_prerequisites.acct_repo, "create_account", fake_create_account)
    monkeypatch.setattr(
        org_prerequisites.acct_repo,
        "get_account",
        AsyncMock(return_value={"id": str(bank_gl_id), "code": "1010", "name": "Bank"}),
    )
    monkeypatch.setattr(
        org_prerequisites.bank_repo,
        "get_default_cash_account",
        AsyncMock(return_value={"id": str(uuid.uuid4()), "gl_account_id": str(cash_gl_id)}),
    )
    monkeypatch.setattr(
        org_prerequisites.bank_repo,
        "get_default_bank_account",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        org_prerequisites.bank_repo,
        "list_bank_accounts",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(org_prerequisites.engine, "ensure_bank_account", fake_ensure_bank)
    monkeypatch.setattr(
        org_prerequisites.engine,
        "ensure_tax_payable_account",
        AsyncMock(return_value={"id": str(uuid.uuid4()), "code": "2110", "tax_account_created": True}),
    )
    monkeypatch.setattr(
        org_prerequisites.engine,
        "ensure_tax_receivable_account",
        AsyncMock(return_value={"id": str(uuid.uuid4()), "code": "1310", "tax_account_created": True}),
    )
    monkeypatch.setattr(
        org_prerequisites.engine,
        "ensure_wht_payable_account",
        AsyncMock(return_value={"id": str(uuid.uuid4()), "code": "2120", "wht_account_created": True}),
    )
    monkeypatch.setattr(
        org_prerequisites.org_repo,
        "get_open_accounting_period",
        AsyncMock(return_value={"id": str(uuid.uuid4()), "name": "November 2026", "status": "OPEN"}),
    )

    res = await ensure_org_prerequisites(str(org_id))

    assert res["status"] == "ready"
    assert res["errors"] == {}
    assert "bank_account" in res["provisioned"]
    assert "clearing_suspense" in res["provisioned"]
    assert "cash_gl" in res["already_present"]
    assert "accounting_period" in res["already_present"]
    assert any(a["name"] == "Clearing & Suspense" for a in created_accounts)


@pytest.mark.asyncio
async def test_ensure_org_prerequisites_degrades_gracefully_when_db_blocked():
    org_id = str(uuid.uuid4())
    direct = await ensure_org_prerequisites(org_id)
    safe = await ensure_org_prerequisites_safe(org_id)

    assert direct["organization_id"] == org_id
    assert direct["status"] == "degraded"
    assert direct["errors"]

    assert safe["organization_id"] == org_id
    assert safe["status"] == "degraded"
