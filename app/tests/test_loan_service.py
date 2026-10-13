"""Loans & Financing subsystem — offline tests (no database).

The schedule is the SOURCE OF TRUTH: these tests pin the amortization math
(the spec's own 1.2M / 12% / 3-year / bi-annual example), the
principal-vs-interest SEGREGATION on payment (only interest reaches the
P&L), the mirror borrow/lend symmetry, and the unique-narration identity
rule.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest

from app.services import loan_service


# ---------------------------------------------------------------------------
# build_schedule — pure math
# ---------------------------------------------------------------------------

def test_spec_example_1200000_biannual_reducing():
    """Rs. 1,200,000, 3 years, bi-annual, 12% -> 6 installments."""
    rows = loan_service.build_schedule(
        principal=1_200_000, annual_rate=12, tenure_months=36,
        frequency="SEMI_ANNUAL", custom_interval_months=None,
        first_payment_date=date(2027, 6, 30),
    )
    assert len(rows) == 6
    assert rows[0]["interest_component"] == 72_000.00       # 1.2M x 6%
    # Constant EMI (total_due) across amortizing installments.
    totals = [r["total_due"] for r in rows[:-1]]
    assert len(set(totals)) == 1
    # Interest each period = 6% of that period's OPENING principal.
    for r in rows[:-1]:
        assert abs(r["interest_component"] - round(r["opening_principal"] * 0.06, 2)) < 0.01
    # Loan closes at exactly zero; due dates are 6 months apart.
    assert rows[-1]["closing_principal"] == 0
    assert rows[1]["due_date"] == "2027-12-30"
    assert rows[-1]["due_date"] == "2029-12-30"


def test_zero_rate_amortizes_principal_evenly():
    rows = loan_service.build_schedule(
        principal=120_000, annual_rate=0, tenure_months=12,
        frequency="MONTHLY", custom_interval_months=None,
        first_payment_date=date(2027, 1, 15),
    )
    assert len(rows) == 12
    assert all(r["interest_component"] == 0 for r in rows)
    assert abs(sum(r["principal_component"] for r in rows) - 120_000) < 0.01
    assert rows[-1]["closing_principal"] == 0


def test_flat_method_total_interest_is_p_rate_years():
    rows = loan_service.build_schedule(
        principal=600_000, annual_rate=10, tenure_months=24,
        frequency="MONTHLY", custom_interval_months=None,
        first_payment_date=date(2027, 1, 1), interest_method="FLAT",
    )
    assert len(rows) == 24
    total_interest = sum(r["interest_component"] for r in rows)
    assert abs(total_interest - 600_000 * 0.10 * 2) < 0.05   # 120,000
    assert rows[-1]["closing_principal"] == 0


def test_grace_periods_are_interest_only():
    rows = loan_service.build_schedule(
        principal=1_000_000, annual_rate=12, tenure_months=18,
        frequency="MONTHLY", custom_interval_months=None,
        first_payment_date=date(2027, 1, 1), grace_months=3,
    )
    grace = rows[:3]
    assert all(r["principal_component"] == 0 for r in grace)
    assert grace[0]["interest_component"] == 10_000.00      # 1M x 1%
    assert rows[-1]["closing_principal"] == 0


def test_balloon_lands_on_the_final_installment():
    rows = loan_service.build_schedule(
        principal=1_000_000, annual_rate=8, tenure_months=24,
        frequency="MONTHLY", custom_interval_months=None,
        first_payment_date=date(2027, 1, 1), balloon_amount=200_000,
    )
    assert rows[-1]["closing_principal"] == 0
    # Final principal carries the unpaid balance INCLUDING the balloon.
    assert rows[-1]["principal_component"] >= 200_000
    assert sum(r["principal_component"] for r in rows) == pytest.approx(1_000_000, abs=0.05)

# ---------------------------------------------------------------------------
# record_installment_payment — principal/interest segregation + mirror
# ---------------------------------------------------------------------------

ORG = uuid.UUID("00000000-0000-4000-8000-000000000077")


def _loan_row(direction: str) -> dict:
    return {
        "id": str(uuid.uuid4()), "organization_id": str(ORG),
        "direction": direction, "narration": f"Loan - Test - {direction}",
        "loan_account_id": str(uuid.uuid4()),
        "interest_account_id": str(uuid.uuid4()),
        "cash_account_id": str(uuid.uuid4()),
        "currency_code": "PKR", "status": "ACTIVE",
    }


def _installment(principal: float, interest: float, status: str = "DUE") -> dict:
    return {
        "id": str(uuid.uuid4()), "installment_no": 1,
        "principal_component": principal, "interest_component": interest,
        "total_due": round(principal + interest, 2),
        "paid_amount": 0, "status": status,
    }


def _wire(monkeypatch, loan: dict, inst: dict, all_installments: list):
    """Fake the DB seams + journal pipeline; capture the prepared lines."""
    captured: dict = {"lines": None, "updates": []}

    async def _fetch_many(table, filters=None, **kw):
        if table == "loans":
            return [loan]
        if table == "loan_installments":
            if filters and "installment_no" in filters:
                return [inst]
            return all_installments
        return []

    async def _prepare_journal(**kwargs):
        captured["lines"] = kwargs.get("lines")
        return {"entry": {"id": str(uuid.uuid4())}}

    async def _noop(*args, **kwargs):
        return {}

    async def _update(table, filters=None, data=None, **kw):
        captured["updates"].append((table, data))

    monkeypatch.setattr(loan_service, "fetch_many", _fetch_many)
    monkeypatch.setattr(loan_service.accounting_service, "prepare_journal", _prepare_journal)
    monkeypatch.setattr(loan_service.accounting_service, "validate_journal", _noop)
    monkeypatch.setattr(loan_service.accounting_service, "post_journal", _noop)
    monkeypatch.setattr(loan_service, "update_one", _update)
    return captured


def test_borrowed_installment_splits_principal_and_interest(monkeypatch):
    loan = _loan_row("BORROWED")
    inst = _installment(180_000, 72_000)
    cap = _wire(monkeypatch, loan, inst, [inst])
    res = asyncio.run(loan_service.record_installment_payment(
        ORG, loan_id=uuid.UUID(loan["id"]), installment_no=1))
    lines = cap["lines"]
    assert res["principal_component"] == 180_000
    assert res["interest_component"] == 72_000
    # Dr Loan ledger 180k, Dr Interest Expense 72k, Cr Bank 252k.
    by_role = {str(l["account_id"]): (l["debit"], l["credit"]) for l in lines}
    assert by_role[loan["loan_account_id"]] == (180_000, 0)
    assert by_role[loan["interest_account_id"]] == (72_000, 0)
    assert by_role[loan["cash_account_id"]] == (0, 252_000)
    assert res["status"] == "PAID"


def test_given_installment_mirrors_to_interest_income(monkeypatch):
    loan, inst = _loan_row("GIVEN"), _installment(80_000, 10_000)
    cap = _wire(monkeypatch, loan, inst, [inst])
    res = asyncio.run(loan_service.record_installment_payment(
        ORG, loan_id=uuid.UUID(loan["id"]), installment_no=1))
    lines = cap["lines"]
    by_role = {str(l["account_id"]): (l["debit"], l["credit"]) for l in lines}
    assert by_role[loan["cash_account_id"]] == (90_000, 0)   # Dr Bank 90k
    assert by_role[loan["loan_account_id"]] == (0, 80_000)   # Cr Receivable
    assert by_role[loan["interest_account_id"]] == (0, 10_000)  # Cr Interest Income
    assert res["status"] == "PAID"


def test_partial_payment_splits_by_schedule_proportions(monkeypatch):
    loan = _loan_row("BORROWED")
    inst = _installment(180_000, 72_000)
    cap = _wire(monkeypatch, loan, inst, [inst])
    res = asyncio.run(loan_service.record_installment_payment(
        ORG, loan_id=uuid.UUID(loan["id"]), installment_no=1, amount_paid=126_000))
    assert res["status"] == "PARTIAL"
    # 126k of 252k = 50%: interest first-half protected at 36k, principal 90k.
    assert res["interest_component"] == 36_000
    assert res["principal_component"] == 90_000
    # The cash split PERSISTS on the installment (migration 095): later
    # outstanding/write-off math reads real numbers, never approximations.
    inst_updates = [d for (t, d) in cap["updates"] if t == "loan_installments"]
    assert inst_updates[0]["principal_paid"] == 90_000
    assert inst_updates[0]["interest_paid"] == 36_000


def test_already_paid_installment_is_refused(monkeypatch):
    loan = _loan_row("BORROWED")
    inst = _installment(100_000, 5_000, status="PAID")
    _wire(monkeypatch, loan, inst, [inst])
    with pytest.raises(ValueError, match="already PAID"):
        asyncio.run(loan_service.record_installment_payment(
            ORG, loan_id=uuid.UUID(loan["id"]), installment_no=1))


def test_duplicate_narration_is_refused():
    async def _dup(*a, **k):
        return {"id": "x"}
    orig = loan_service.fetch_one
    loan_service.fetch_one = _dup
    try:
        with pytest.raises(ValueError, match="unique"):
            asyncio.run(loan_service.create_loan(
                ORG, direction="BORROWED", narration="Loan - HBL - X",
                counterparty="HBL", principal=1000, loan_date="2027-01-01",
                first_payment_date="2027-02-01", tenure_months=12,
                frequency="MONTHLY"))
    finally:
        loan_service.fetch_one = orig


# ---------------------------------------------------------------------------
# run_due_installment_sweep — the worker's cron (due != paid)
# ---------------------------------------------------------------------------

def _sched_row(no: int, live: str, stored: str, due: str) -> dict:
    return {
        "id": str(uuid.uuid4()), "loan_id": str(uuid.uuid4()),
        "narration": "Loan - Sweep - Test", "direction": "BORROWED",
        "installment_no": no, "due_date": due,
        "principal_component": 50000, "interest_component": 6000,
        "total_due": 56000, "status": stored, "live_status": live,
    }


def test_sweep_marks_due_and_creates_pending_events_exactly_once(monkeypatch):
    due_row = _sched_row(1, "DUE", "SCHEDULED", "2026-10-13")
    future_row = _sched_row(2, "SCHEDULED", "SCHEDULED", "2027-04-13")
    seen_events: list = []
    captured: dict = {"inserted": [], "updated": []}

    async def _fetch_many(table, filters=None, **kw):
        if table == "loans":
            return [{"id": str(uuid.uuid4()),
                     "organization_id": str(ORG), "status": "ACTIVE"}]
        if table == "v_loan_installment_schedule":
            return [due_row, future_row]
        if table == "loan_payment_events":
            return list(seen_events)
        return []

    async def _insert_one(table, data=None, **kw):
        captured["inserted"].append((table, data))
        seen_events.append({"installment_id": data["installment_id"]})
        return {"id": str(uuid.uuid4())}

    async def _update_one(table, filters=None, data=None, **kw):
        captured["updated"].append((table, filters, data))
        # Model persistence: the real table reflects the status write, so the
        # second run must see DUE and skip re-marking.
        if table == "loan_installments" and filters and data:
            if filters.get("id") == due_row["id"] and "status" in data:
                due_row["status"] = data["status"]

    monkeypatch.setattr(loan_service, "fetch_many", _fetch_many)
    monkeypatch.setattr(loan_service, "insert_one", _insert_one)
    monkeypatch.setattr(loan_service, "update_one", _update_one)

    first = asyncio.run(loan_service.run_due_installment_sweep(as_of="2026-10-13"))
    assert first["marked_due"] == 1 and first["events_created"] == 1
    event_rows = [d for (t, d) in captured["inserted"] if t == "loan_payment_events"]
    assert event_rows[0]["status"] == "PENDING"
    assert event_rows[0]["proposed"]["principal"] == 50000
    assert event_rows[0]["proposed"]["interest"] == 6000
    # The future installment was NOT touched.
    assert not any(f and f.get("id") == future_row["id"]
                   for (_t, f, _d) in captured["updated"])

    # Second run: idempotent — no duplicate events, nothing re-marked.
    second = asyncio.run(loan_service.run_due_installment_sweep(as_of="2026-10-13"))
    assert second["events_created"] == 0
    assert second["marked_due"] == 0


def test_sweep_flags_past_due_as_overdue(monkeypatch):
    late_row = _sched_row(1, "OVERDUE", "SCHEDULED", "2026-09-01")
    captured: dict = {"updated": []}

    async def _fetch_many(table, filters=None, **kw):
        if table == "loans":
            return [{"id": str(uuid.uuid4()),
                     "organization_id": str(ORG), "status": "ACTIVE"}]
        if table == "v_loan_installment_schedule":
            return [late_row]
        if table == "loan_payment_events":
            return []
        return []

    async def _insert_one(table, data=None, **kw):
        return {"id": str(uuid.uuid4())}

    async def _update_one(table, filters=None, data=None, **kw):
        captured["updated"].append((table, filters, data))

    monkeypatch.setattr(loan_service, "fetch_many", _fetch_many)
    monkeypatch.setattr(loan_service, "insert_one", _insert_one)
    monkeypatch.setattr(loan_service, "update_one", _update_one)

    res = asyncio.run(loan_service.run_due_installment_sweep(as_of="2026-10-13"))
    assert res["marked_overdue"] == 1
    statuses = [d.get("status") for (t, _f, d) in captured["updated"]
                if t == "loan_installments"]
    assert statuses == ["OVERDUE"]


# ---------------------------------------------------------------------------
# restructure_loan / write_off_loan
# ---------------------------------------------------------------------------

def _wire_restructure(monkeypatch, loan: dict, installments: list) -> dict:
    captured: dict = {"inserted": [], "updated": []}

    async def _fetch_many(table, filters=None, **kw):
        if table == "loan_installments":
            return list(installments)
        if table == "loans":
            return [loan]
        return []

    async def _insert_one(table, data=None, **kw):
        captured["inserted"].append((table, data))
        return {"id": str(uuid.uuid4())}

    async def _update_one(table, filters=None, data=None, **kw):
        captured["updated"].append((table, filters, data))

    monkeypatch.setattr(loan_service, "fetch_many", _fetch_many)
    monkeypatch.setattr(loan_service, "insert_one", _insert_one)
    monkeypatch.setattr(loan_service, "update_one", _update_one)
    return captured


def test_restructure_keeps_paid_rebuilds_rest_and_audits(monkeypatch):
    loan = {**_loan_row("BORROWED"), "principal": 1000000,
            "tenure_months": 12, "frequency": "MONTHLY",
            "interest_rate": 12.0, "interest_method": "REDUCING",
            "first_payment_date": "2027-01-01", "maturity_date": "2027-12-01",
            "grace_months": 0, "balloon_amount": 0}
    paid = {"id": str(uuid.uuid4()), "installment_no": 1, "status": "PAID",
            "principal_component": 90000, "interest_component": 12000,
            "paid_amount": 102000, "principal_paid": 90000, "interest_paid": 12000,
            "due_date": "2027-01-01"}
    future = [
        {"id": str(uuid.uuid4()), "installment_no": n, "status": "SCHEDULED",
         "principal_component": 80000, "interest_component": 10000,
         "paid_amount": 0, "principal_paid": 0, "interest_paid": 0,
         "due_date": f"2027-0{n}-01"}
        for n in (2, 3, 4)
    ]
    cap = _wire_restructure(monkeypatch, loan, [paid, *future])

    res = asyncio.run(loan_service.restructure_loan(
        ORG, loan_id=uuid.UUID(loan["id"]), first_payment_date="2027-08-01",
        tenure_months=12, frequency="MONTHLY", interest_rate=6.0,
        reason="Rate renegotiated with lender"))

    # REAL outstanding = 1,000,000 - 90,000 persisted principal_paid.
    assert res["outstanding"] == 910000
    assert res["waived"] == 3 and res["kept"] == 1
    # New schedule closes at zero and numbering continues after the kept row.
    assert res["new_schedule"][0]["installment_no"] == 2
    assert res["new_schedule"][-1]["closing_principal"] == 0
    # The PAID row was never updated; only the three SCHEDULED rows were waived.
    waived_ids = {f.get("id") for (t, f, d) in cap["updated"]
                  if t == "loan_installments" and d.get("status") == "WAIVED"}
    assert waived_ids == {r["id"] for r in future}
    assert paid["id"] not in waived_ids
    # Audit row captured old terms + new terms + reason.
    audits = [d for (t, d) in cap["inserted"] if t == "loan_restructurings"]
    assert audits and audits[0]["old_terms"]["interest_rate"] == 12.0
    assert audits[0]["new_terms"]["interest_rate"] == 6.0
    assert audits[0]["reason"] == "Rate renegotiated with lender"


def test_restructure_refuses_fully_paid_loan(monkeypatch):
    loan = {**_loan_row("BORROWED"), "principal": 100000}
    paid = {"id": str(uuid.uuid4()), "installment_no": 1, "status": "PAID",
            "principal_component": 100000, "paid_amount": 100000,
            "principal_paid": 100000, "interest_paid": 0}
    _wire_restructure(monkeypatch, loan, [paid])
    with pytest.raises(ValueError, match="no outstanding"):
        asyncio.run(loan_service.restructure_loan(
            ORG, loan_id=uuid.UUID(loan["id"]), first_payment_date="2027-08-01",
            tenure_months=6, frequency="MONTHLY", interest_rate=5.0))


def _wire_writeoff(monkeypatch, loan: dict, installments: list) -> dict:
    captured: dict = {"lines": None, "inserted": [], "updated": []}

    async def _fetch_many(table, filters=None, **kw):
        if table == "loan_installments":
            return list(installments)
        if table == "loans":
            return [loan]
        return []

    async def _update_one(table, filters=None, data=None, **kw):
        captured["updated"].append((table, filters, data))

    async def _insert_one(table, data=None, **kw):
        captured["inserted"].append((table, data))
        return {"id": str(uuid.uuid4())}

    async def _prepare_journal(**kwargs):
        captured["lines"] = kwargs.get("lines")
        return {"entry": {"id": str(uuid.uuid4())}}

    async def _noop(*a, **k):
        return {}

    async def _fake_heading(org, name, atype, nb, code_base, parent=None):
        return {"id": str(uuid.uuid4()), "name": name, "account_type": atype}

    monkeypatch.setattr(loan_service, "fetch_many", _fetch_many)
    monkeypatch.setattr(loan_service, "update_one", _update_one)
    monkeypatch.setattr(loan_service, "insert_one", _insert_one)
    monkeypatch.setattr(loan_service, "_ensure_heading", _fake_heading)
    monkeypatch.setattr(loan_service.accounting_service, "prepare_journal", _prepare_journal)
    monkeypatch.setattr(loan_service.accounting_service, "validate_journal", _noop)
    monkeypatch.setattr(loan_service.accounting_service, "post_journal", _noop)
    return captured


def test_write_off_borrowed_posts_forgiveness_gain(monkeypatch):
    loan = {**_loan_row("BORROWED"), "principal": 500000}
    rows = [
        {"id": str(uuid.uuid4()), "installment_no": 1, "status": "PAID",
         "principal_component": 100000, "paid_amount": 100000,
         "principal_paid": 100000, "interest_paid": 12000},
        {"id": str(uuid.uuid4()), "installment_no": 2, "status": "SCHEDULED",
         "principal_component": 150000, "paid_amount": 0,
         "principal_paid": 0, "interest_paid": 0},
        {"id": str(uuid.uuid4()), "installment_no": 3, "status": "SCHEDULED",
         "principal_component": 250000, "paid_amount": 0,
         "principal_paid": 0, "interest_paid": 0},
    ]
    cap = _wire_writeoff(monkeypatch, loan, rows)

    res = asyncio.run(loan_service.write_off_loan(
        ORG, loan_id=uuid.UUID(loan["id"]), write_off_date="2026-10-13",
        reason="Lender granted hardship forgiveness"))

    assert res["amount_written_off"] == 400000  # 500k - 100k real paid
    lines = cap["lines"]
    by_acct = {str(l["account_id"]): (l["debit"], l["credit"]) for l in lines}
    assert by_acct[loan["loan_account_id"]] == (400000, 0)   # Dr Loan ledger
    gain_line = next(l for l in lines if str(l["account_id"]) != loan["loan_account_id"])
    assert (gain_line["debit"], gain_line["credit"]) == (0, 400000)  # Cr Gain
    assert res["journal"]["posted"] is True
    # Unpaid installments waived; loan flagged WRITTEN_OFF.
    waived = [d for (t, f, d) in cap["updated"]
              if t == "loan_installments" and d.get("status") == "WAIVED"]
    assert len(waived) == 2
    status_updates = [d for (t, f, d) in cap["updated"] if t == "loans"]
    assert status_updates[0]["status"] == "WRITTEN_OFF"


def test_write_off_given_posts_impairment_loss(monkeypatch):
    loan = {**_loan_row("GIVEN"), "principal": 500000}
    rows = [{"id": str(uuid.uuid4()), "installment_no": 1, "status": "SCHEDULED",
             "principal_component": 500000, "paid_amount": 0,
             "principal_paid": 0, "interest_paid": 0}]
    cap = _wire_writeoff(monkeypatch, loan, rows)

    res = asyncio.run(loan_service.write_off_loan(
        ORG, loan_id=uuid.UUID(loan["id"]), write_off_date="2026-10-13",
        reason="Customer insolvent"))

    assert res["amount_written_off"] == 500000
    lines = cap["lines"]
    loss_line = lines[0]
    assert (loss_line["debit"], loss_line["credit"]) == (500000, 0)  # Dr Loss
    receivable = next(l for l in lines if str(l["account_id"]) == loan["loan_account_id"])
    assert (receivable["debit"], receivable["credit"]) == (0, 500000)  # Cr Receivable
    assert res["journal"]["posted"] is True


def test_write_off_refuses_fully_repaid_loan(monkeypatch):
    loan = {**_loan_row("BORROWED"), "principal": 100000}
    rows = [{"id": str(uuid.uuid4()), "installment_no": 1, "status": "PAID",
             "principal_component": 100000, "paid_amount": 100000,
             "principal_paid": 100000, "interest_paid": 5000}]
    _wire_writeoff(monkeypatch, loan, rows)
    with pytest.raises(ValueError, match="no outstanding"):
        asyncio.run(loan_service.write_off_loan(
            ORG, loan_id=uuid.UUID(loan["id"]), write_off_date="2026-10-13"))

