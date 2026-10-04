"""AI Activity — the read-only API behind the AI Activity page.

A ``/api/ai/sessions`` endpoint already existed, but it returned raw rows with
no counts, no filtering and no truncation signal; the detail endpoint never
resolved ``tool_id`` to a tool NAME and never returned ``ai.execution_results``.

These tests pin the contract the page now depends on:

* LIST: items + REGISTER-WIDE counts + total + truncated in ONE request.
  ``query``/``status`` narrow ``items`` only — a filter can never make the
  counts beside it lie — and the feed is read in PAGES (a single PostgREST
  response caps at ~1000 rows, which would silently truncate both).
* DETAIL: tool calls carry a NAME plus ``read_only`` (the page's read-vs-write
  distinction), and ``results`` says what actually changed.
"""

import uuid

import pytest

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
SESSION = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _auth():
    from types import SimpleNamespace

    return SimpleNamespace(organization_id=ORG, user_id=USER)


def _row(**over) -> dict:
    base = {
        "id": str(SESSION),
        "organization_id": str(ORG),
        "user_id": str(USER),
        "user_request": "Create an invoice for Zameer Labs",
        "status": "COMPLETED",
        "current_phase": "COMPLETED",
        "created_at": "2026-10-01T10:00:00Z",
        "started_at": "2026-10-01T10:00:00Z",
        "completed_at": "2026-10-01T10:00:12Z",
    }
    base.update(over)
    return base


def _patch_feed(monkeypatch, rows: list) -> None:
    from app import main as main_mod

    async def fake_paged(org_id, user_id, *, limit):
        return list(rows)

    monkeypatch.setattr(main_mod, "_read_sessions_paged", fake_paged)


class TestListActivity:
    @pytest.mark.asyncio
    async def test_one_request_carries_items_counts_and_status(self, monkeypatch):
        _patch_feed(
            monkeypatch,
            [
                _row(),
                _row(
                    id=str(uuid.uuid4()),
                    status="FAILED",
                    user_request="Reconcile the bank account",
                ),
            ],
        )
        from app import main as main_mod

        out = await main_mod.list_sessions(auth=_auth())

        assert out["total"] == 2
        assert out["counts"] == {
            "ALL": 2,
            "PENDING": 0,
            "PLANNING": 0,
            "WAITING_FOR_USER": 0,
            "EXECUTING": 0,
            "COMPLETED": 1,
            "FAILED": 1,
            "CANCELLED": 0,
        }
        assert out["truncated"] is False
        assert out["status"] == "ALL"
        assert len(out["items"]) == 2

    @pytest.mark.asyncio
    async def test_the_filter_narrows_items_but_never_the_counts(self, monkeypatch):
        _patch_feed(
            monkeypatch,
            [
                _row(),
                _row(
                    id=str(uuid.uuid4()),
                    status="FAILED",
                    user_request="Reconcile the bank account",
                ),
            ],
        )
        from app import main as main_mod

        out = await main_mod.list_sessions(
            query="bank", status="FAILED", auth=_auth()
        )
        assert [row["user_request"] for row in out["items"]] == [
            "Reconcile the bank account"
        ]
        # the counts still describe the WHOLE feed
        assert out["counts"]["ALL"] == 2
        assert out["counts"]["COMPLETED"] == 1

    @pytest.mark.asyncio
    async def test_an_unknown_status_is_normalised_not_an_empty_lie(
        self, monkeypatch
    ):
        _patch_feed(monkeypatch, [_row(), _row(id=str(uuid.uuid4()))])
        from app import main as main_mod

        out = await main_mod.list_sessions(status="WHATEVER", auth=_auth())
        assert out["status"] == "ALL"
        assert len(out["items"]) == 2

    @pytest.mark.asyncio
    async def test_a_full_feed_is_reported_truncated(self, monkeypatch):
        """When the read ceiling is hit, the page must be told — otherwise the
        feed and its counts would imply completeness they do not have."""
        _patch_feed(monkeypatch, [_row(), _row(id=str(uuid.uuid4()))])
        from app import main as main_mod

        out = await main_mod.list_sessions(limit=2, auth=_auth())
        assert out["truncated"] is True
        assert out["total"] == 2


class TestActivityPaging:
    @pytest.mark.asyncio
    async def test_a_short_page_ends_the_read(self, monkeypatch):
        from app import main as main_mod

        offsets: list[int] = []

        async def fake_fetch(table, *, filters, select="*", order=None,
                             limit=100, offset=0):
            offsets.append(offset)
            if offset == 0:
                return [_row() for _ in range(limit)]  # a FULL page
            return [_row() for _ in range(3)]  # a SHORT page

        monkeypatch.setattr(main_mod, "fetch_many", fake_fetch)

        rows = await main_mod._read_sessions_paged(ORG, USER, limit=2000)
        assert len(rows) == 503  # 500 + 3, then the short page ends the read
        assert offsets == [0, 500]


def _patch_detail(monkeypatch, *, tools: dict, steps=None, tool_calls=None,
                  clarifications=None, confirmations=None, results=None) -> None:
    """Stub the four trail reads, the session read and the tool catalog."""
    from app import main as main_mod

    async def fake_fetch(table, *, filters, select="*", order=None, limit=100,
                         offset=0):
        if table == "ai_execution_steps":
            return list(steps or [])
        if table == "ai_tool_calls":
            return list(tool_calls or [])
        if table == "ai_clarifications":
            return list(clarifications or [])
        if table == "ai_confirmations":
            return list(confirmations or [])
        raise AssertionError(f"unexpected table {table}")

    async def fake_one(table, *, filters, select="*"):
        if table == "ai_execution_sessions":
            return _row()
        if table == "ai_execution_results":
            return results
        raise AssertionError(f"unexpected table {table}")

    async def fake_catalog():
        return dict(tools)

    monkeypatch.setattr(main_mod, "fetch_many", fake_fetch)
    monkeypatch.setattr(main_mod, "fetch_one", fake_one)
    monkeypatch.setattr(main_mod, "_tool_catalog", fake_catalog)


class TestSessionDetail:
    @pytest.mark.asyncio
    async def test_a_tool_call_resolves_to_a_name_and_a_write_flag(
        self, monkeypatch
    ):
        """Without the catalog join the page could only show an opaque UUID —
        and ``read_only`` is the ONLY way it can tell a read from a write."""
        _patch_detail(
            monkeypatch,
            tools={
                "9999": {
                    "tool_name": "create_invoice",
                    "tool_read_only": False,
                    "tool_risk_level": "HIGH",
                }
            },
            steps=[{"id": "st1", "step_order": 1, "step_type": "REASON",
                    "status": "COMPLETED"}],
            tool_calls=[{"id": "tc1", "tool_id": "9999", "call_order": 1,
                         "status": "SUCCESS"}],
        )
        from app import main as main_mod

        out = await main_mod.get_session(SESSION, auth=_auth())

        assert out["tool_calls"][0]["tool_name"] == "create_invoice"
        assert out["tool_calls"][0]["tool_read_only"] is False
        assert out["tool_calls"][0]["tool_risk_level"] == "HIGH"
        assert out["steps"][0]["step_type"] == "REASON"

    @pytest.mark.asyncio
    async def test_an_unresolvable_tool_degrades_to_a_null_name(self, monkeypatch):
        """A missing catalog row is reported as unknown — never a fabricated
        name, and never a crash that hides the whole trail."""
        _patch_detail(
            monkeypatch,
            tools={},
            tool_calls=[{"id": "tc1", "tool_id": "9999", "call_order": 1,
                         "status": "FAILED"}],
        )
        from app import main as main_mod

        out = await main_mod.get_session(SESSION, auth=_auth())
        assert out["tool_calls"][0]["tool_name"] is None
        assert out["tool_calls"][0]["tool_read_only"] is None

    @pytest.mark.asyncio
    async def test_the_outcome_row_is_returned(self, monkeypatch):
        _patch_detail(
            monkeypatch,
            tools={},
            results={
                "status": "COMPLETED",
                "summary": "Invoice INV-0007 posted",
                "action_type": "CREATE_INVOICE",
                "verification_status": "VERIFIED",
                "affected_entities": [{"type": "invoice"}],
            },
        )
        from app import main as main_mod

        out = await main_mod.get_session(SESSION, auth=_auth())
        assert out["results"]["verification_status"] == "VERIFIED"
        assert out["results"]["summary"] == "Invoice INV-0007 posted"

    @pytest.mark.asyncio
    async def test_a_run_without_an_outcome_reads_none_not_a_broken_trail(
        self, monkeypatch
    ):
        """No result row is a real state (still running, or finished without
        one) — the page reports it; the endpoint must not invent it or fail."""
        _patch_detail(monkeypatch, tools={}, results=None)
        from app import main as main_mod

        out = await main_mod.get_session(SESSION, auth=_auth())
        assert out["results"] is None
        assert out["tool_calls"] == []
        assert out["clarifications"] == []
        assert out["confirmations"] == []

