"""Depreciation posting: the PERIOD, the same-day collision, the cash/bank split.

Production 2026-10-03 (Zameer Labs, asset 'Car', Rs 3,260,000, 5-year life,
purchased 2026-10-03) — the three defects these tests pin:

1. ``POST /api/fixed-assets/<id>/depreciation`` answered **500 after the
   journal was posted** (JV-000031, 54,333.33) and after
   ``fixed_assets.accumulated_depreciation`` was updated.  Registration seeds a
   0-value schedule row dated the PURCHASE date,
   ``asset_depreciation_schedules`` is ``unique (asset_id, depreciation_date)``
   and the charge was dated that same day — so the schedule INSERT raised
   inside the request.  A first charge dated the acquisition date must UPDATE
   that seed row, and a second charge on an already-charged date must be
   refused BEFORE the journal exists.
2. The charge was a blind ``(cost − salvage) ÷ life ÷ 12`` — never the period
   from the ACQUISITION date to the charge date (IAS 16), and for later
   charges never from the LAST charge date to the charge date.
3. The acquisition was stated as CASH (``payment_method: "CASH"`` is in the
   audit row) yet credited ``1010 - Bank``: the settlement resolver ignored the
   treatment, so cash and bank were never segregated.
"""

from __future__ import annotations

import uuid

import pytest

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

ASSET_ACCOUNT = {
    "id": "a0000000-0000-0000-0000-000000000001",
    "code": "1520",
    "name": "Vehicle - Car",
    "account_type": "ASSET",
}
ACC_DEP_ACCOUNT = {
    "id": "a0000000-0000-0000-0000-000000000002",
    "code": "1510",
    "name": "Accumulated Depreciation - Vehicle",
    "account_type": "ASSET",
}
DEP_EXPENSE = {
    "id": "a0000000-0000-0000-0000-000000000003",
    "code": "6200",
    "name": "Depreciation Expense",
    "account_type": "EXPENSE",
}
CASH_ACCOUNT = {
    "id": "a0000000-0000-0000-0000-000000000004",
    "code": "1020",
    "name": "Cash",
    "account_type": "ASSET",
}
BANK_ACCOUNT = {
    "id": "a0000000-0000-0000-0000-000000000005",
    "code": "1010",
    "name": "Bank",
    "account_type": "ASSET",
}


def _asset(**over) -> dict:
    """The production Car, overridable per test."""
    base = {
        "id": "b0000000-0000-0000-0000-000000000001",
        "organization_id": str(ORG),
        "asset_code": "AST-000004",
        "name": "Car",
        "purchase_date": "2026-10-03",
        "purchase_cost": 3260000.0,
        "salvage_value": 0.0,
        "useful_life_years": 5,
        "depreciation_method": "STRAIGHT_LINE",
        "accumulated_depreciation": 0.0,
        "book_value": 3260000.0,
        "status": "ACTIVE",
        "gl_asset_account_id": ASSET_ACCOUNT["id"],
        "gl_depreciation_expense_account_id": DEP_EXPENSE["id"],
        "gl_accumulated_depreciation_account_id": ACC_DEP_ACCOUNT["id"],
    }
    base.update(over)
    return base


class _JournalCapture:
    """The accounting engine's prepare → validate → post trio, captured."""

    def __init__(self) -> None:
        self.lines: list = []
        self.description = ""
        self.posted = False

    async def prepare_journal(self, **kw):
        self.lines = kw.get("lines") or []
        self.description = str(kw.get("description") or "")
        entry = {"id": str(uuid.uuid4()), "reference": "JV-000031"}
        return {"entry": entry}

    async def validate_journal(self, *, entry_id):
        return {"success": True}

    async def post_journal(self, *, entry_id):
        self.posted = True
        return {"success": True}


def _patch_engine(monkeypatch, capture: _JournalCapture) -> None:
    from app.services import fixed_asset_service as fas

    monkeypatch.setattr(
        fas.accounting_service, "prepare_journal", capture.prepare_journal
    )
    monkeypatch.setattr(
        fas.accounting_service, "validate_journal", capture.validate_journal
    )
    monkeypatch.setattr(
        fas.accounting_service, "post_journal", capture.post_journal
    )



def _patch_depreciation_repo(
    monkeypatch,
    *,
    asset: dict,
    last_charged: str | None = None,
    same_day_row: dict | None = None,
    chart: list | None = None,
    charged_total: float | None = None,
):
    """Stub every seam ``record_depreciation`` uses — no live database."""
    from app.repositories import fixed_asset_repository as repo
    from app.services import fixed_asset_service as fas

    calls: dict = {"schedule": [], "txn": [], "updates": []}

    async def fake_get_asset(org_id, *, asset_id):
        return dict(asset)

    async def fake_last_charged(org_id, *, asset_id):
        return {
            "last_charged_date": last_charged,
            "charged_total": (
                charged_total
                if charged_total is not None
                else float(asset.get("accumulated_depreciation") or 0)
            ),
            "rows": 1,
        }

    async def fake_row_for_date(*, organization_id, asset_id, depreciation_date):
        return dict(same_day_row) if same_day_row else None

    async def fake_update_asset(row_id, *, fields):
        calls["updates"].append(fields)
        return {"id": str(row_id), **fields}

    async def fake_schedule(**kw):
        calls["schedule"].append(kw)
        return {"id": str(uuid.uuid4()), **kw}

    async def fake_txn(**kw):
        calls["txn"].append(kw)
        return {"id": str(uuid.uuid4()), **kw}

    async def fake_chart(org_id, *, account_type=None, limit=100, **kw):
        accounts = chart or [ASSET_ACCOUNT, ACC_DEP_ACCOUNT, DEP_EXPENSE]
        if account_type:
            return [a for a in accounts if a["account_type"] == account_type]
        return list(accounts)

    by_id = {a["id"]: a for a in (chart or [ASSET_ACCOUNT, ACC_DEP_ACCOUNT, DEP_EXPENSE])}

    async def fake_get_account(org_id, *, account_id):
        return by_id.get(str(account_id))

    monkeypatch.setattr(fas.account_repo, "get_account", fake_get_account)
    monkeypatch.setattr(repo, "get_asset", fake_get_asset)
    monkeypatch.setattr(repo, "get_depreciation_trail", fake_last_charged)
    monkeypatch.setattr(repo, "get_schedule_row_for_date", fake_row_for_date)
    monkeypatch.setattr(repo, "update_asset_by_id", fake_update_asset)
    monkeypatch.setattr(repo, "record_depreciation_schedule", fake_schedule)
    monkeypatch.setattr(repo, "record_asset_transaction", fake_txn)
    monkeypatch.setattr(fas.account_repo, "get_chart_of_accounts", fake_chart)
    return calls


# ---------------------------------------------------------------------------
# 1. The 500-after-posting: same-day charge over the registration seed row
# ---------------------------------------------------------------------------
class TestSameDayCharge:
    @pytest.mark.asyncio
    async def test_first_charge_on_the_purchase_date_is_not_a_500(self, monkeypatch):
        """The exact production failure: a 0-value seed row already exists for
        the purchase date, so the charge must UPDATE it — journal, asset totals
        and audit trail all land."""
        from app.services import fixed_asset_service as fas

        asset = _asset()
        seed = {"id": "c0000000-0000-0000-0000-000000000001",
                "depreciation_amount": 0.0}
        calls = _patch_depreciation_repo(
            monkeypatch, asset=asset, last_charged=None, same_day_row=seed
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        result = await fas.record_depreciation(
            ORG,
            asset_id=asset["id"],
            depreciation_amount=54333.33,
            transaction_date="2026-10-03",
        )

        assert capture.posted is True
        assert result["depreciation_amount"] == 54333.33
        assert result["depreciation_period"]["to"] == "2026-10-03"
        # one row for that date, written through the collision-safe writer
        assert [c["depreciation_date"] for c in calls["schedule"]] == ["2026-10-03"]
        assert calls["schedule"][0]["depreciation_amount"] == 54333.33
        # the DEPRECIATION audit row is written too (it never was in production)
        assert [c["transaction_type"] for c in calls["txn"]] == ["DEPRECIATION"]
        assert calls["updates"][0]["accumulated_depreciation"] == 54333.33
        assert result["bookkeeping_warning"] is None

    @pytest.mark.asyncio
    async def test_second_charge_on_a_charged_date_is_refused_before_posting(
        self, monkeypatch
    ):
        from app.services import fixed_asset_service as fas

        asset = _asset(accumulated_depreciation=54333.33, book_value=3205666.67)
        _patch_depreciation_repo(
            monkeypatch,
            asset=asset,
            last_charged="2026-10-03",
            same_day_row={"id": "c1", "depreciation_amount": 54333.33},
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        with pytest.raises(ValueError, match="already been posted for 2026-10-03"):
            await fas.record_depreciation(
                ORG, asset_id=asset["id"], transaction_date="2026-10-03"
            )
        # nothing was posted — the refusal happens BEFORE the journal exists
        assert capture.posted is False


    @pytest.mark.asyncio
    async def test_a_failed_audit_write_never_fails_a_posted_journal(self, monkeypatch):
        """The bookkeeping rows are a trail, not the accounting truth: when they
        cannot be written the caller gets the POSTED charge plus a warning —
        never a 500 that hides a real journal entry."""
        from app.repositories import fixed_asset_repository as repo
        from app.services import fixed_asset_service as fas

        asset = _asset()
        calls = _patch_depreciation_repo(
            monkeypatch, asset=asset, last_charged=None, same_day_row=None
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        async def boom(**kw):
            raise RuntimeError("duplicate key value violates unique constraint")

        monkeypatch.setattr(repo, "record_depreciation_schedule", boom)

        result = await fas.record_depreciation(
            ORG,
            asset_id=asset["id"],
            depreciation_amount=1000.0,
            transaction_date="2026-11-03",
        )

        assert capture.posted is True
        assert result["depreciation_amount"] == 1000.0
        assert "schedule row" in str(result["bookkeeping_warning"])
        # the transaction audit row is still attempted (a separate write)
        assert calls["txn"][0]["transaction_type"] == "DEPRECIATION"

    @pytest.mark.asyncio
    async def test_asset_update_failure_says_the_journal_was_posted(self, monkeypatch):
        from app.repositories import fixed_asset_repository as repo
        from app.services import fixed_asset_service as fas

        asset = _asset()
        _patch_depreciation_repo(
            monkeypatch, asset=asset, last_charged=None, same_day_row=None
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        async def boom(row_id, *, fields):
            raise RuntimeError("permission denied for table fixed_assets")

        monkeypatch.setattr(repo, "update_asset_by_id", boom)

        with pytest.raises(ValueError) as exc:
            await fas.record_depreciation(
                ORG,
                asset_id=asset["id"],
                depreciation_amount=1000.0,
                transaction_date="2026-11-03",
            )
        text = str(exc.value)
        assert "WAS POSTED" in text and "do NOT repost" in text
        assert "1000.0" in text  # the accumulated depreciation to set by hand


# ---------------------------------------------------------------------------
# 2. The PERIOD: acquisition → charge date, then last charge → charge date
# ---------------------------------------------------------------------------
class TestDepreciationPeriod:
    @pytest.mark.asyncio
    async def test_first_charge_runs_from_the_acquisition_date(self, monkeypatch):
        """Bought 2026-01-01, charged 2026-04-01 ⇒ 90 days of a 365-day year
        (3,650,000 ÷ 5 years = 730,000/yr ⇒ 180,000)."""
        from app.services import fixed_asset_service as fas

        asset = _asset(
            purchase_date="2026-01-01",
            purchase_cost=3650000.0,
            book_value=3650000.0,
        )
        calls = _patch_depreciation_repo(
            monkeypatch, asset=asset, last_charged=None, same_day_row=None
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        result = await fas.record_depreciation(
            ORG, asset_id=asset["id"], transaction_date="2026-04-01"
        )

        assert result["depreciation_amount"] == 180000.0
        assert result["depreciation_period"] == {
            "from": "2026-01-01",
            "to": "2026-04-01",
            "days": 90,
            "basis": "prorated_straight_line",
        }
        assert calls["txn"][0]["details"]["period_days"] == 90
        assert calls["schedule"][0]["opening_book_value"] == 3650000.0

    @pytest.mark.asyncio
    async def test_later_charge_runs_from_the_last_charge_date(self, monkeypatch):
        """The register's schedule rows are the trail: after a 2026-04-01 charge
        the next charge starts THERE, not at the purchase date again."""
        from app.services import fixed_asset_service as fas

        asset = _asset(
            purchase_date="2026-01-01",
            purchase_cost=3650000.0,
            accumulated_depreciation=180000.0,
            book_value=3470000.0,
        )
        _patch_depreciation_repo(
            monkeypatch,
            asset=asset,
            last_charged="2026-04-01",
            same_day_row=None,
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        result = await fas.record_depreciation(
            ORG, asset_id=asset["id"], transaction_date="2026-05-01"
        )

        assert result["depreciation_amount"] == 60000.0  # 30 days
        assert result["depreciation_period"]["from"] == "2026-04-01"
        assert result["depreciation_period"]["days"] == 30



    @pytest.mark.asyncio
    async def test_zero_day_default_charge_is_refused_with_the_reference_date(
        self, monkeypatch
    ):
        from app.services import fixed_asset_service as fas

        asset = _asset()  # purchased 2026-10-03
        _patch_depreciation_repo(
            monkeypatch, asset=asset, last_charged=None, same_day_row=None
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        with pytest.raises(ValueError, match="No depreciation period has elapsed"):
            await fas.record_depreciation(
                ORG, asset_id=asset["id"], transaction_date="2026-10-03"
            )
        assert capture.posted is False

    @pytest.mark.asyncio
    async def test_a_charge_dated_before_the_last_charge_is_refused(self, monkeypatch):
        from app.services import fixed_asset_service as fas

        asset = _asset(purchase_date="2026-01-01")
        _patch_depreciation_repo(
            monkeypatch, asset=asset, last_charged="2026-04-01", same_day_row=None
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        with pytest.raises(ValueError, match="already depreciated through"):
            await fas.record_depreciation(
                ORG, asset_id=asset["id"], transaction_date="2026-03-01"
            )
        assert capture.posted is False

    @pytest.mark.asyncio
    async def test_explicit_amount_still_wins_over_the_period(self, monkeypatch):
        from app.services import fixed_asset_service as fas

        asset = _asset(purchase_date="2026-01-01")
        _patch_depreciation_repo(
            monkeypatch, asset=asset, last_charged=None, same_day_row=None
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        result = await fas.record_depreciation(
            ORG,
            asset_id=asset["id"],
            depreciation_amount=2500.0,
            transaction_date="2026-01-02",
        )
        assert result["depreciation_amount"] == 2500.0
        assert result["depreciation_period"]["basis"] == "explicit_amount"


# ---------------------------------------------------------------------------
# 3. Cash vs Bank: the settlement ledger follows the payment treatment
# ---------------------------------------------------------------------------
class TestSettlementAccountSegregation:
    async def _resolve(self, monkeypatch, *, method: str, chart: list, banks: list):
        from app.repositories import organization_repository as org_repo
        from app.services import fixed_asset_service as fas

        async def fake_chart(org_id, *, account_type=None, limit=100, **kw):
            return list(chart)

        async def fake_banks(org_id):
            return list(banks)

        by_id = {a["id"]: a for a in chart}

        async def fake_get_account(org_id, *, account_id):
            return by_id.get(str(account_id))

        monkeypatch.setattr(fas.account_repo, "get_chart_of_accounts", fake_chart)
        monkeypatch.setattr(fas.account_repo, "get_account", fake_get_account)
        monkeypatch.setattr(org_repo, "get_bank_accounts", fake_banks)
        return await fas._resolve_settlement_account(
            ORG, payment_account_id=None, payment_method=method
        )

    @pytest.mark.asyncio
    async def test_cash_treatment_credits_cash_on_hand(self, monkeypatch):
        account = await self._resolve(
            monkeypatch,
            method="CASH",
            chart=[ASSET_ACCOUNT, ACC_DEP_ACCOUNT, CASH_ACCOUNT, BANK_ACCOUNT],
            banks=[{"is_default": True, "gl_account_id": BANK_ACCOUNT["id"]}],
        )
        assert account["id"] == CASH_ACCOUNT["id"]

    @pytest.mark.asyncio
    async def test_bank_treatment_credits_the_configured_bank_account(self, monkeypatch):
        account = await self._resolve(
            monkeypatch,
            method="BANK_TRANSFER",
            chart=[ASSET_ACCOUNT, ACC_DEP_ACCOUNT, CASH_ACCOUNT, BANK_ACCOUNT],
            banks=[{"is_default": True, "gl_account_id": BANK_ACCOUNT["id"]}],
        )
        assert account["id"] == BANK_ACCOUNT["id"]

    @pytest.mark.asyncio
    async def test_an_ambiguous_cash_chart_falls_back_to_the_bank_default(
        self, monkeypatch
    ):
        """Two cash-ish ledgers is not a decision the resolver may make."""
        petty = {**CASH_ACCOUNT, "id": "a0000000-0000-0000-0000-000000000099",
                 "name": "Petty Cash"}
        account = await self._resolve(
            monkeypatch,
            method="CASH",
            chart=[ASSET_ACCOUNT, ACC_DEP_ACCOUNT, CASH_ACCOUNT, petty, BANK_ACCOUNT],
            banks=[{"is_default": True, "gl_account_id": BANK_ACCOUNT["id"]}],
        )
        assert account["id"] == BANK_ACCOUNT["id"]



class TestAcquisitionCreditsTheStatedLedger:
    """End-to-end through ``register_asset`` — the segregation regression."""

    async def _register(self, monkeypatch, *, method: str, banks: list):
        from app.repositories import fixed_asset_repository as repo
        from app.repositories import organization_repository as org_repo
        from app.services import fixed_asset_service as fas

        chart = [
            ASSET_ACCOUNT, ACC_DEP_ACCOUNT, CASH_ACCOUNT, BANK_ACCOUNT,
            DEP_EXPENSE,
            {"id": "x0000000-0000-0000-0000-000000000001", "code": "2000",
             "name": "Accounts Payable", "account_type": "LIABILITY"},
        ]
        by_id = {a["id"]: a for a in chart}

        async def fake_chart(org_id, *, account_type=None, limit=100, **kw):
            if account_type:
                return [a for a in chart if a["account_type"] == account_type]
            return list(chart)

        async def fake_get_account(org_id, *, account_id):
            return by_id.get(str(account_id))

        async def fake_create_asset(**kw):
            return {"id": "b0000000-0000-0000-0000-000000000009", **kw}

        async def noop(*args, **kw):
            return None

        async def fake_banks(org_id):
            return list(banks)

        monkeypatch.setattr(fas.account_repo, "get_chart_of_accounts", fake_chart)
        monkeypatch.setattr(fas.account_repo, "get_account", fake_get_account)
        monkeypatch.setattr(org_repo, "get_bank_accounts", fake_banks)
        monkeypatch.setattr(repo, "create_asset", fake_create_asset)
        monkeypatch.setattr(repo, "update_asset_by_id", noop)
        monkeypatch.setattr(repo, "record_asset_transaction", noop)
        monkeypatch.setattr(repo, "record_depreciation_schedule", noop)

        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        await fas.register_asset(
            ORG,
            name="Car",
            purchase_cost=3260000.0,
            transaction_date="2026-10-03",
            payment_method=method,
            asset_account_id=uuid.UUID(ASSET_ACCOUNT["id"]),
            useful_life_years=5,
        )
        return capture

    @pytest.mark.asyncio
    async def test_on_cash_credits_cash_not_bank(self, monkeypatch):
        capture = await self._register(
            monkeypatch,
            method="CASH",
            banks=[{"is_default": True, "gl_account_id": BANK_ACCOUNT["id"]}],
        )
        assert capture.lines[0]["account_id"] == ASSET_ACCOUNT["id"]
        assert capture.lines[0]["debit"] == 3260000.0
        assert capture.lines[1]["account_id"] == CASH_ACCOUNT["id"]
        assert capture.lines[1]["credit"] == 3260000.0

    @pytest.mark.asyncio
    async def test_a_bank_treatment_still_credits_the_bank_account(self, monkeypatch):
        capture = await self._register(
            monkeypatch,
            method="BANK_TRANSFER",
            banks=[{"is_default": True, "gl_account_id": BANK_ACCOUNT["id"]}],
        )
        assert capture.lines[1]["account_id"] == BANK_ACCOUNT["id"]


class TestDepreciationTrailGap:
    @pytest.mark.asyncio
    async def test_a_charge_missing_from_the_trail_is_reported(self, monkeypatch):
        """The production Car exactly: accumulated depreciation 54,333.33 with
        NOTHING in the schedule (the charge posted, the schedule write died).
        The next charge must say so instead of silently overlapping it."""
        from app.services import fixed_asset_service as fas

        asset = _asset(accumulated_depreciation=54333.33, book_value=3205666.67)
        _patch_depreciation_repo(
            monkeypatch,
            asset=asset,
            last_charged=None,
            same_day_row=None,
            charged_total=0.0,
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        result = await fas.record_depreciation(
            ORG, asset_id=asset["id"], transaction_date="2026-11-03"
        )

        warning = str(result["trail_warning"])
        assert "depreciation trail" in warning
        assert "54,333.33" in warning
        # the trail gap is a warning, never a refusal: the charge still posts
        assert capture.posted is True

    @pytest.mark.asyncio
    async def test_a_consistent_trail_raises_no_warning(self, monkeypatch):
        from app.services import fixed_asset_service as fas

        asset = _asset(accumulated_depreciation=54333.33, book_value=3205666.67)
        _patch_depreciation_repo(
            monkeypatch,
            asset=asset,
            last_charged="2026-10-03",
            same_day_row=None,
            charged_total=54333.33,
        )
        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        result = await fas.record_depreciation(
            ORG, asset_id=asset["id"], transaction_date="2026-11-03"
        )
        assert result["trail_warning"] is None
        assert result["depreciation_period"]["from"] == "2026-10-03"

# ---------------------------------------------------------------------------
# 4. Disposal: the entry the register must post (IAS 16 / IFRS 16 practice)
# ---------------------------------------------------------------------------
LOSS_ACCOUNT = {
    "id": "a0000000-0000-0000-0000-000000000006",
    "code": "6910",
    "name": "Loss on Disposal",
    "account_type": "EXPENSE",
}
GAIN_ACCOUNT = {
    "id": "a0000000-0000-0000-0000-000000000007",
    "code": "4910",
    "name": "Gain on Disposal",
    "account_type": "REVENUE",
}


class TestDisposalJournal:
    async def _dispose(self, monkeypatch, *, proceeds: float):
        from app.repositories import fixed_asset_repository as repo
        from app.repositories import organization_repository as org_repo
        from app.services import fixed_asset_service as fas

        chart = [
            ASSET_ACCOUNT, ACC_DEP_ACCOUNT, CASH_ACCOUNT, BANK_ACCOUNT,
            DEP_EXPENSE, LOSS_ACCOUNT, GAIN_ACCOUNT,
        ]
        by_id = {a["id"]: a for a in chart}

        async def fake_chart(org_id, *, account_type=None, limit=100, **kw):
            if account_type:
                return [a for a in chart if a["account_type"] == account_type]
            return list(chart)

        async def fake_get_account(org_id, *, account_id):
            return by_id.get(str(account_id))

        async def fake_banks(org_id):
            return [{"is_default": True, "gl_account_id": BANK_ACCOUNT["id"]}]

        async def noop(*args, **kw):
            return None

        async def fake_get_asset(org_id, *, asset_id):
            # The Car AFTER one 54,333.33 charge: book value 3,205,666.67.
            return dict(
                _asset(accumulated_depreciation=54333.33, book_value=3205666.67)
            )

        monkeypatch.setattr(fas.account_repo, "get_chart_of_accounts", fake_chart)
        monkeypatch.setattr(fas.account_repo, "get_account", fake_get_account)
        monkeypatch.setattr(org_repo, "get_bank_accounts", fake_banks)
        monkeypatch.setattr(repo, "get_asset", fake_get_asset)
        monkeypatch.setattr(repo, "update_asset_by_id", noop)
        monkeypatch.setattr(repo, "record_asset_transaction", noop)

        capture = _JournalCapture()
        _patch_engine(monkeypatch, capture)

        result = await fas.dispose_asset(
            ORG,
            asset_id=_asset()["id"],
            disposal_amount=proceeds,
            transaction_date="2026-12-01",
            disposal_type="SALE",
        )
        return capture, result

    @pytest.mark.asyncio
    async def test_loss_is_booked_and_the_asset_credits_at_cost(self, monkeypatch):
        """Proceeds 3,000,000 vs book value 3,205,666.67 ⇒
        Dr proceeds + Dr accumulated depreciation + Dr loss / Cr asset cost."""
        capture, result = await self._dispose(monkeypatch, proceeds=3000000.0)

        debits = {
            line["account_id"]: line["debit"] for line in capture.lines if line["debit"]
        }
        credits = {
            line["account_id"]: line["credit"]
            for line in capture.lines
            if line["credit"]
        }
        assert debits[BANK_ACCOUNT["id"]] == 3000000.0        # cash/bank
        assert debits[ACC_DEP_ACCOUNT["id"]] == 54333.33       # accumulated dep
        assert debits[LOSS_ACCOUNT["id"]] == 205666.67         # P&L loss
        assert credits[ASSET_ACCOUNT["id"]] == 3260000.0       # cost removed
        assert result["loss_on_disposal"] == 205666.67
        assert result["gain_on_disposal"] == 0.0
        # balanced by construction
        assert round(sum(debits.values()), 2) == round(sum(credits.values()), 2)

    @pytest.mark.asyncio
    async def test_gain_is_credited_to_pl_when_proceeds_exceed_book_value(
        self, monkeypatch
    ):
        capture, result = await self._dispose(monkeypatch, proceeds=3500000.0)

        credits = {
            line["account_id"]: line["credit"]
            for line in capture.lines
            if line["credit"]
        }
        assert credits[GAIN_ACCOUNT["id"]] == 294333.33
        assert credits[ASSET_ACCOUNT["id"]] == 3260000.0
        assert result["gain_on_disposal"] == 294333.33
