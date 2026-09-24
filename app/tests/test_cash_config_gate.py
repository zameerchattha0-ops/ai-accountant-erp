"""Cash-configuration gate (P5 pattern applied to the cash ledger).

Production incident: a cash receipt/payment for an org with ZERO
cash_accounts rows raised ValueError("No cash account specified and no cash
account configured …") out of payment_service._resolve_cash_gl_account and
dead-ended at agent L3952 as "Operation failed: …" ("Something went wrong")
— unlike the bank path, which parks with a guided bank_accounts_configuration
question.  Verified root cause (live DB): Zameer Labs PVT Ltd had 0
cash_accounts rows (and 0 bank_accounts) while its chart HAS an active Cash
ASSET (code 1020).  The guard pre-existed prod commit c8fecbe — NOT a
latency-stack regression; the real gap was that no product path (UI or tool)
could ever create a cash drawer.

Fix (fail-toward-existing-behaviour):
* choke converts ONLY the exact cash-config error into an ask-once
  cash_accounts_configuration clarification (second miss → genuine FAILED);
* an explicit YES + _cash_drawer_creation_pending creates the default drawer
  via ensure_default_cash_account (idempotent; links the EXISTING cash GL —
  never invents a GL, never falls back to the bank ledger);
* payment_service's ValueError itself is untouched (services fail closed).

Pinned invariants:
* question text always carries "cash ledger" (creation trigger) AND "cash
  account" (ask-once marker);
* affirmative detection is a tight whitelist (no guessing);
* ensure_default_cash_account: existing drawer → returned as-is (no insert);
  no cash GL → None (no insert).
(The choke branch itself is a thin composition of these tested helpers —
the parallel P5 bank gate carries no execute-level test either.)
"""

import uuid
from types import SimpleNamespace

import pytest

import app.services.bank_service as bank_svc
from app.agent import (
    _cash_config_already_asked,
    _cash_configuration_question,
    _cash_drawer_creation_pending,
    _is_affirmative_answer,
    _is_cash_config_error,
)
from app.services.bank_service import (
    ensure_default_cash_account,
    find_cash_gl_account,
    pick_cash_gl_account,
)

ORG = uuid.UUID("4f20f43c-bb3b-4747-abe1-02d9380884df")
GL_ID = uuid.UUID("a5e4808a-9eac-4349-aa98-7143d0ee7e72")

CASH_GL = {
    "id": str(GL_ID),
    "code": "1020",
    "name": "Cash",
    "account_type": "ASSET",
    "is_active": True,
}
BANK_GL = {
    "id": "b1000000-0000-0000-0000-000000000001",
    "code": "1010",
    "name": "HBL Operations",
    "account_type": "ASSET",
    "is_active": True,
}
CASH_ERROR = (
    "No cash account specified and no cash account configured "
    "(a cash transaction must hit the cash ledger, never the bank ledger)"
)


class TestErrorDetection:
    def test_exact_cash_error_matches(self):
        assert _is_cash_config_error(CASH_ERROR) is True

    def test_bank_error_does_not_match(self):
        assert (
            _is_cash_config_error(
                "No bank account specified and no default bank account configured"
            )
            is False
        )

    def test_empty_and_none_do_not_match(self):
        assert _is_cash_config_error("") is False
        assert _is_cash_config_error(None) is False


class TestQuestion:
    def test_with_cash_gl_offers_creation(self):
        q = _cash_configuration_question(CASH_GL)
        assert "cash ledger" in q.lower()
        assert "cash account" in q.lower()
        assert "Reply YES" in q
        assert "'Cash'" in q
        assert "(1020)" in q

    def test_without_cash_gl_points_to_chart(self):
        q = _cash_configuration_question(None)
        assert "cash ledger" in q.lower()
        assert "cash account" in q.lower()
        assert "Chart of Accounts" in q
        assert "Reply YES" not in q


class TestAffirmativeWhitelist:
    @pytest.mark.parametrize(
        "answer", ["yes", "YES", "y", "Yes!", "sure.", "ok", "create it", "go ahead"]
    )
    def test_clear_yes(self, answer):
        assert _is_affirmative_answer(answer) is True

    @pytest.mark.parametrize(
        "answer",
        ["no", "nope", "N", "", None, "yes, but later", "maybe", "y/n?"],
    )
    def test_not_clear_yes(self, answer):
        assert _is_affirmative_answer(answer) is False


class TestPendingAndAskOnce:
    def test_pending_when_ledger_question_answered_yes(self):
        qa = [{
            "question": "No cash account is configured as the cash ledger…",
            "answer": "yes",
        }]
        assert _cash_drawer_creation_pending(qa) is True

    def test_not_pending_on_decline(self):
        qa = [{"question": "…cash ledger…", "answer": "no"}]
        assert _cash_drawer_creation_pending(qa) is False

    def test_not_pending_without_ledger_marker(self):
        qa = [{"question": "Which cash account should receive this?", "answer": "yes"}]
        assert _cash_drawer_creation_pending(qa) is False

    def test_empty_history_never_pending(self):
        assert _cash_drawer_creation_pending([]) is False
        assert _cash_drawer_creation_pending(None) is False

    def test_already_asked_on_any_cash_account_question(self):
        qa = [{"question": "Which cash account should I use?", "answer": "1020"}]
        assert _cash_config_already_asked(qa) is True

    def test_not_asked_for_bank_only_history(self):
        qa = [{"question": "No bank accounts are configured…", "answer": "ok"}]
        assert _cash_config_already_asked(qa) is False


class TestPickCashGl:
    def test_prefers_cash_in_hand_then_cash_then_substring(self):
        cash_in_hand = {**CASH_GL, "code": "1050", "name": "Cash in Hand"}
        assert pick_cash_gl_account([BANK_GL, CASH_GL, cash_in_hand]) is cash_in_hand
        assert pick_cash_gl_account([BANK_GL, CASH_GL]) is CASH_GL
        petty = {**CASH_GL, "code": "1060", "name": "Petty Cash Drawer"}
        assert pick_cash_gl_account([BANK_GL, petty]) is petty
        assert pick_cash_gl_account([BANK_GL]) is None
        assert pick_cash_gl_account([]) is None

    def test_inactive_rows_ignored(self):
        inactive = {**CASH_GL, "is_active": False}
        assert pick_cash_gl_account([inactive]) is None


class TestEnsureDefaultDrawer:
    @pytest.mark.asyncio
    async def test_creates_drawer_linked_to_existing_cash_gl(self, monkeypatch):
        inserted = {}

        async def no_default(org):
            return None

        async def chart(org, *, account_type=None, limit=500):
            assert account_type == "ASSET"
            return [BANK_GL, CASH_GL]

        async def fake_insert(table, *, data):
            assert table == "cash_accounts"
            inserted.update(data)
            return {"id": "c1000000-0000-0000-0000-000000000001", **data}

        monkeypatch.setattr(
            bank_svc, "repo", SimpleNamespace(get_default_cash_account=no_default)
        )
        monkeypatch.setattr(
            bank_svc, "acct_repo", SimpleNamespace(get_chart_of_accounts=chart)
        )
        monkeypatch.setattr(bank_svc, "insert_one", fake_insert)

        drawer = await ensure_default_cash_account(ORG)
        assert inserted == {
            "organization_id": str(ORG),
            "name": "Cash",
            "gl_account_id": str(GL_ID),
            "is_active": True,
        }
        assert drawer["name"] == "Cash"

    @pytest.mark.asyncio
    async def test_idempotent_when_drawer_exists(self, monkeypatch):
        existing = {"id": "c1000000-0000-0000-0000-000000000009", "name": "Cash"}

        async def has_default(org):
            return existing

        async def boom(*a, **k):
            raise AssertionError("insert must not run when a drawer exists")

        monkeypatch.setattr(
            bank_svc, "repo", SimpleNamespace(get_default_cash_account=has_default)
        )
        monkeypatch.setattr(bank_svc, "insert_one", boom)

        assert await ensure_default_cash_account(ORG) is existing

    @pytest.mark.asyncio
    async def test_no_cash_gl_returns_none_without_insert(self, monkeypatch):
        async def no_default(org):
            return None

        async def chart(org, *, account_type=None, limit=500):
            return [BANK_GL]

        async def boom(*a, **k):
            raise AssertionError("insert must not run without a cash GL account")

        monkeypatch.setattr(
            bank_svc, "repo", SimpleNamespace(get_default_cash_account=no_default)
        )
        monkeypatch.setattr(
            bank_svc, "acct_repo", SimpleNamespace(get_chart_of_accounts=chart)
        )
        monkeypatch.setattr(bank_svc, "insert_one", boom)

        assert await ensure_default_cash_account(ORG) is None

    @pytest.mark.asyncio
    async def test_find_cash_gl_scopes_to_assets(self, monkeypatch):
        seen = {}

        async def chart(org, *, account_type=None, limit=500):
            seen["account_type"] = account_type
            return [CASH_GL]

        monkeypatch.setattr(
            bank_svc, "acct_repo", SimpleNamespace(get_chart_of_accounts=chart)
        )
        gl = await find_cash_gl_account(ORG)
        assert gl is CASH_GL
        assert seen["account_type"] == "ASSET"
