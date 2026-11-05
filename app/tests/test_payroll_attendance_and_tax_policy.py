"""Unit & Integration Tests for Employee Precomputed Tax & Attendance Leave Policy.

Verifies:
1. Organization Leave Policy configuration (monthly 2 days, annual 27 days, standard 30 working days).
2. Auto-calculation of Section 149 statutory income tax on employee master records.
3. Attendance within allowed quota (e.g. 2 days leave with 2 allowed) -> 100% full month salary paid.
4. Attendance exceeding allowed quota (e.g. 5 days absent with 2 allowed) -> Pro-rated 1/30th deduction for 3 excess days.
5. Automatic Section 149 WHT application on every payroll run without manual flags.
6. Multi-employee payroll run with mixed attendance.
7. Fixed-format Questionnaire chips for payroll attendance and leave clarification.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.services import payroll_service
from app.services import employee_service
from app.services import preference_service
from app.services import tax_service
from app import questionnaire as qmod


@pytest.mark.asyncio
async def test_organization_leave_policy_defaults_and_updates():
    """Verify default leave policy and custom updates in organization preferences."""
    org_id = uuid.uuid4()
    mock_prefs = {}

    async def fake_get_all(org):
        return dict(mock_prefs)

    async def fake_set(org, key, val, **kw):
        mock_prefs[key] = str(val)
        return {"key": key, "value": str(val)}

    with patch("app.services.preference_service.get_all_preferences", side_effect=fake_get_all), \
         patch("app.services.preference_service.set_preference", side_effect=fake_set):

        # 1. Default policy check
        policy = await payroll_service.get_organization_leave_policy(org_id)
        assert policy["monthly_allowed_leaves"] == 2
        assert policy["annual_allowed_leaves"] == 27
        assert policy["standard_working_days"] == 30
        assert "2 paid leaves allowed per month" in policy["policy_summary"]

        # 2. Update leave policy (e.g. tech firm allowing 3 monthly leaves, 30 annual leaves)
        updated = await payroll_service.set_organization_leave_policy(
            org_id,
            monthly_allowed_leaves=3,
            annual_allowed_leaves=30,
            standard_working_days=26,
        )
        assert updated["monthly_allowed_leaves"] == 3
        assert updated["annual_allowed_leaves"] == 30
        assert updated["standard_working_days"] == 26
        assert "3 paid leaves allowed per month" in updated["policy_summary"]


@pytest.mark.asyncio
async def test_employee_information_auto_calculates_section_149_tax():
    """Verify that employee records automatically attach monthly_tax and tax_slab."""
    emp = {
        "id": str(uuid.uuid4()),
        "employee_code": "EMP-LEAD-01",
        "full_name": "Hamza Tariq",
        "basic_salary": 250000.0, # Annual 3,000,000 (Slab 4: 116k + 20% on excess over 2.2M)
    }
    tagged = employee_service._attach_tax_profile(emp)
    assert tagged["monthly_tax"] == 23000.0
    assert tagged["annual_tax"] == 276000.0
    assert tagged["tax_slab"] == 4

    # Low income employee (under 600,000/yr -> Slab 1: Exempt)
    emp_junior = {
        "id": str(uuid.uuid4()),
        "employee_code": "EMP-JUN-01",
        "full_name": "Ayesha Bilal",
        "basic_salary": 45000.0, # Annual 540,000
    }
    tagged_junior = employee_service._attach_tax_profile(emp_junior)
    assert tagged_junior["monthly_tax"] == 0.0
    assert tagged_junior["tax_slab"] == 1


def test_compute_pay_within_allowed_leaves_pays_full_month_salary():
    """If employee takes 2 days leave and 2 are allowed by organization policy,
    employee must receive 100% full month salary with zero deduction.
    """
    emp = {
        "id": str(uuid.uuid4()),
        "employee_code": "EMP-001",
        "full_name": "Zahid Khan",
        "basic_salary": 300000.0,
        "monthly_tax": 33000.0, # Precomputed Slab 4
        "tax_slab": 4,
    }

    # Absent for 2 days, organization allows 2 leaves per month
    pay = payroll_service._compute_pay(
        emp,
        components=[],
        as_of="2026-10-31",
        days_absent=2,
        monthly_allowed_leaves=2,
        standard_working_days=30,
    )

    # Invariants: No leave deduction, full gross and net paid
    assert pay["days_absent"] == 2
    assert pay["monthly_allowed_leaves"] == 2
    assert pay["excess_absent_days"] == 0
    assert pay["leave_deduction"] == 0.0
    assert pay["gross_pay"] == 300000.0
    assert pay["taxable_gross"] == 300000.0
    assert pay["tax_withheld"] == 33000.0
    assert pay["net_pay"] == 267000.0 # 300,000 - 33,000 tax


def test_compute_pay_exceeding_allowed_leaves_deducts_pro_rated_excess_days():
    """If employee takes 5 days leave and 2 are allowed by policy,
    excess 3 days (5 - 2) must be deducted at 1/30th per day.
    """
    emp = {
        "id": str(uuid.uuid4()),
        "employee_code": "EMP-002",
        "full_name": "Kamran Akram",
        "basic_salary": 300000.0, # Daily rate = 300,000 / 30 = 10,000/day
    }
    emp = employee_service._attach_tax_profile(emp)

    # Absent for 5 days, policy allows 2 leaves
    pay = payroll_service._compute_pay(
        emp,
        components=[],
        as_of="2026-10-31",
        days_absent=5,
        monthly_allowed_leaves=2,
        standard_working_days=30,
    )

    # 3 excess days * 10,000 = 30,000 deduction
    assert pay["days_absent"] == 5
    assert pay["monthly_allowed_leaves"] == 2
    assert pay["excess_absent_days"] == 3
    assert pay["daily_rate"] == 10000.0
    assert pay["leave_deduction"] == 30000.0
    assert pay["gross_pay"] == 300000.0
    assert pay["taxable_gross"] == 270000.0 # 300,000 - 30,000

    # Section 149 tax calculated on taxable gross of 270,000 (Annual: 3,240,000 -> Slab 5)
    tax_info = tax_service.calculate_salary_tax_withholding(270000.0)
    assert pay["tax_withheld"] == tax_info["monthly_tax"]
    assert pay["net_pay"] == round(300000.0 - 30000.0 - pay["tax_withheld"], 2)


@pytest.mark.allows_db
@pytest.mark.asyncio
async def test_run_payroll_with_mixed_attendance_and_auto_wht(monkeypatch):
    """Multi-employee payroll run with mixed attendance:
    Emp 1: 0 days absent -> Full month salary.
    Emp 2: 2 days absent (within allowed 2) -> Full month salary.
    Emp 3: 5 days absent (3 excess days) -> Pro-rated leave deduction.
    """
    org_id = uuid.uuid4()
    emp1_id = uuid.uuid4()
    emp2_id = uuid.uuid4()
    emp3_id = uuid.uuid4()

    exp_acct = {"id": str(uuid.uuid4()), "code": "5000", "name": "Salaries Expense"}
    accrued_acct = {"id": str(uuid.uuid4()), "code": "2130", "name": "Accrued Salaries Payable"}
    wht_acct = {"id": str(uuid.uuid4()), "code": "2121", "name": "WHT Payable u/s 149"}

    roster = [
        {"id": str(emp1_id), "employee_code": "EMP-001", "full_name": "Full Attendance", "basic_salary": 100000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"},
        {"id": str(emp2_id), "employee_code": "EMP-002", "full_name": "Allowed Leaves", "basic_salary": 100000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"},
        {"id": str(emp3_id), "employee_code": "EMP-003", "full_name": "Excess Absences", "basic_salary": 120000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"}, # 120k / 30 = 4k/day
    ]

    async def fake_list_employees(org, limit=500):
        return list(roster)

    async def fake_list_allowances(org, *args, **kwargs):
        return []

    async def fake_post_or_report(**kwargs):
        return {"posted": True, "entry": {"id": str(uuid.uuid4())}, "lines": kwargs["lines"], "error": None}

    monkeypatch.setattr(payroll_service.repo, "list_employees", fake_list_employees)
    monkeypatch.setattr(payroll_service.repo, "list_allowances_for_organization", fake_list_allowances)
    monkeypatch.setattr(payroll_service, "_assert_not_already_posted", AsyncMock(return_value=None))
    monkeypatch.setattr(payroll_service, "_resolve_salary_expense_account", AsyncMock(return_value=exp_acct))
    monkeypatch.setattr(payroll_service, "_resolve_accrued_account", AsyncMock(return_value=accrued_acct))
    monkeypatch.setattr("app.accounting_engine.ensure_wht_payable_account", AsyncMock(return_value=wht_acct))
    monkeypatch.setattr(payroll_service, "_post_or_report", fake_post_or_report)

    # Execute payroll with employee absences mapping
    res = await payroll_service.run_payroll(
        organization_id=org_id,
        transaction_date="2026-10-31",
        employee_absences={
            "EMP-001": 0,
            "EMP-002": 2, # Within allowed 2 leaves -> 0 deduction
            "EMP-003": 5, # 3 excess days -> 3 * 4,000 = 12,000 deduction
        },
        # Notice: apply_income_tax defaults to True automatically!
    )

    assert res["journal_posted"] is True
    assert res["employee_count"] == 3

    # Check employee breakdowns
    employees = {e["employee_code"]: e for e in res["employees"]}
    assert employees["EMP-001"]["leave_deduction"] == 0.0
    assert employees["EMP-002"]["leave_deduction"] == 0.0 # 2 days within policy -> 0 deduction
    assert employees["EMP-003"]["leave_deduction"] == 12000.0 # 3 excess days deducted
    assert employees["EMP-003"]["taxable_gross"] == 108000.0 # 120,000 - 12,000

    # Verify double entry balancing
    lines = res["journal_lines"]
    tot_dr = sum(float(l["debit"]) for l in lines)
    tot_cr = sum(float(l["credit"]) for l in lines)
    assert round(tot_dr, 2) == round(tot_cr, 2)


def test_questionnaire_attendance_spec():
    """Verify that QuestionSpecs exist for leave attendance and absent days."""
    spec_absent = qmod.spec_for("days_absent")
    assert spec_absent.kind == qmod.KIND_CHOICE
    assert "2 days per month" in spec_absent.question
    assert any(opt[0] == "FULL_MONTH" for opt in spec_absent.options)

    spec_attendance = qmod.spec_for("payroll_attendance")
    assert spec_attendance.kind == qmod.KIND_CHOICE
    assert any(opt[0] == "ALL_PRESENT" for opt in spec_attendance.options)
