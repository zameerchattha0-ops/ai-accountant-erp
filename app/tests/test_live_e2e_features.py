"""Live End-to-End Feature Verification Tests.

Comprehensive E2E suite verifying the executed end results, ledger entries,
and statutory compliance across:
1. Organization Tax Profile & Registration Enforcement
2. Double-Entry Sales Tax Splitting (Exclusive 18% FBR)
3. Double-Entry Sales Tax Back-Calculation (Inclusive 18% FBR)
4. Provincial Sales Tax on Services (16% PRA, 15% SRB)
5. Unregistered Business Guard (No tax fabricated, 0% GST)
6. Supplier Bill Settlement with Section 153 Withholding Tax (5.5% Goods, 9% Services)
7. Multi-Employee Payroll Gross-to-Net Booking u/s 149 & IAS 19
8. Subsequent Accrued Salary Settlement on Disbursement Date
"""
import uuid
import pytest

from app.services import tax_service
from app.services import payroll_service
from app.services import payment_service
from app.services import preference_service
from app import accounting_engine as engine


# ---------------------------------------------------------------------------
# Feature 1: Org Tax Profile & Registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_organization_tax_profile_persistence(monkeypatch):
    """Verify durable tax profile setup and registration rules."""
    org_id = uuid.uuid4()
    mock_prefs = {}

    async def fake_get_all(org):
        return dict(mock_prefs)

    async def fake_set(org, key, val, **kwargs):
        mock_prefs[key] = str(val)
        return {"key": key, "value": str(val)}

    async def fake_get_org(organization_id=None):
        return {"id": str(org_id), "tax_number": "STRN-1234567"}

    monkeypatch.setattr(preference_service, "get_all_preferences", fake_get_all)
    monkeypatch.setattr(preference_service, "set_preference", fake_set)
    monkeypatch.setattr("app.repositories.organization_repository.get_organization", fake_get_org)

    # 1. Initially configure as registered with FBR
    profile = await tax_service.set_organization_tax_profile(
        org_id,
        is_sales_tax_registered=True,
        tax_authority="FBR",
        default_tax_pricing="EXCLUSIVE",
        sales_tax_rate=18.0,
    )
    assert profile["is_sales_tax_registered"] is True
    assert profile["tax_authority"] == "FBR"
    assert profile["default_tax_pricing"] == "EXCLUSIVE"
    assert profile["sales_tax_rate"] == 18.0

    # 2. Switch to unregistered entity
    unreg_profile = await tax_service.set_organization_tax_profile(
        org_id,
        is_sales_tax_registered=False,
    )
    assert unreg_profile["is_sales_tax_registered"] is False
    assert unreg_profile["sales_tax_rate"] == 0.0  # Unregistered businesses cannot charge GST


# ---------------------------------------------------------------------------
# Feature 2 & 3: Double-Entry Sales Tax Splitting (Exclusive & Inclusive)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_credit_sale_exclusive_fbr_18(monkeypatch):
    """E2E credit sale: Net PKR 250,000 + 18% FBR GST -> Total AR PKR 295,000.
    Asserts exact accounts and 3-line balanced entry:
    Dr AR 295,000 / Cr Sales 250,000 / Cr GST Output 45,000.
    """
    org_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    tax_gl = uuid.uuid4()

    captured_entry = {}

    async def fake_prepare_journal(**kwargs):
        captured_entry.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    monkeypatch.setattr("app.services.accounting_service.prepare_journal", fake_prepare_journal)

    result = await engine.record_credit_sale(
        organization_id=org_id,
        customer_id=cust_id,
        receivable_account_id=ar_id,
        revenue_account_id=rev_id,
        amount=250000.0,
        transaction_date="2026-11-01",
        description="Sale of surgical instruments",
        tax_pricing_mode="EXCLUSIVE",
        tax_rate_percent=18.0,
        tax_account_id=tax_gl,
    )

    lines = captured_entry["lines"]
    assert len(lines) == 3

    # Line 1: Dr AR for Gross (250k + 45k = 295k)
    assert lines[0]["account_id"] == str(ar_id)
    assert lines[0]["debit"] == 295000.0
    assert lines[0]["credit"] == 0.0

    # Line 2: Cr Revenue for Net (250k)
    assert lines[1]["account_id"] == str(rev_id)
    assert lines[1]["debit"] == 0.0
    assert lines[1]["credit"] == 250000.0

    # Line 3: Cr Sales Tax Output Payable for GST (45k)
    assert lines[2]["account_id"] == str(tax_gl)
    assert lines[2]["debit"] == 0.0
    assert lines[2]["credit"] == 45000.0

    # Mathematical Invariant
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 295000.0


@pytest.mark.asyncio
async def test_e2e_cash_sale_inclusive_back_calculation(monkeypatch):
    """E2E cash sale: Gross sticker price PKR 59,000 (GST inclusive at 18%).
    Base Net = 59,000 / 1.18 = 50,000.
    GST = 9,000.
    Dr Cash 59,000 / Cr Sales 50,000 / Cr GST Output 9,000.
    """
    org_id = uuid.uuid4()
    cash_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    tax_gl = uuid.uuid4()

    captured_entry = {}

    async def fake_prepare_journal(**kwargs):
        captured_entry.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    monkeypatch.setattr("app.services.accounting_service.prepare_journal", fake_prepare_journal)

    result = await engine.record_cash_sale(
        organization_id=org_id,
        cash_account_id=cash_id,
        revenue_account_id=rev_id,
        amount=59000.0,
        transaction_date="2026-11-01",
        description="Over-the-counter retail sale",
        tax_pricing_mode="INCLUSIVE",
        tax_rate_percent=18.0,
        tax_account_id=tax_gl,
    )

    lines = captured_entry["lines"]
    assert len(lines) == 3

    assert lines[0]["account_id"] == str(cash_id)
    assert lines[0]["debit"] == 59000.0
    assert lines[0]["credit"] == 0.0

    assert lines[1]["account_id"] == str(rev_id)
    assert lines[1]["debit"] == 0.0
    assert lines[1]["credit"] == 50000.0

    assert lines[2]["account_id"] == str(tax_gl)
    assert lines[2]["debit"] == 0.0
    assert lines[2]["credit"] == 9000.0

    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 59000.0


# ---------------------------------------------------------------------------
# Feature 4 & 5: Provincial Services (PRA/SRB) & Unregistered Businesses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_provincial_services_pra_16_percent(monkeypatch):
    """E2E IT consulting services in Punjab: 16% PRA sales tax on services.
    Base PKR 100,000 -> Tax PKR 16,000 -> Total PKR 116,000.
    """
    org_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    tax_gl = uuid.uuid4()

    captured_entry = {}

    async def fake_prepare_journal(**kwargs):
        captured_entry.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    monkeypatch.setattr("app.services.accounting_service.prepare_journal", fake_prepare_journal)

    await engine.record_credit_sale(
        organization_id=org_id,
        customer_id=cust_id,
        receivable_account_id=ar_id,
        revenue_account_id=rev_id,
        amount=100000.0,
        transaction_date="2026-11-01",
        description="Software development services (Lahore)",
        tax_pricing_mode="EXCLUSIVE",
        tax_rate_percent=16.0,
        tax_account_id=tax_gl,
    )

    lines = captured_entry["lines"]
    assert lines[0]["debit"] == 116000.0
    assert lines[1]["credit"] == 100000.0
    assert lines[2]["credit"] == 16000.0
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)


@pytest.mark.asyncio
async def test_e2e_unregistered_business_sale_remains_two_lines(monkeypatch):
    """When exempt or unregistered: standard 2-line entry with 0% tax."""
    org_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    rev_id = uuid.uuid4()

    captured_entry = {}

    async def fake_prepare_journal(**kwargs):
        captured_entry.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    monkeypatch.setattr("app.services.accounting_service.prepare_journal", fake_prepare_journal)

    await engine.record_credit_sale(
        organization_id=org_id,
        customer_id=cust_id,
        receivable_account_id=ar_id,
        revenue_account_id=rev_id,
        amount=80000.0,
        transaction_date="2026-11-01",
        description="Exempt agricultural goods sale",
        tax_pricing_mode="EXEMPT",
    )

    lines = captured_entry["lines"]
    assert len(lines) == 2
    assert lines[0]["debit"] == 80000.0
    assert lines[1]["credit"] == 80000.0


# ---------------------------------------------------------------------------
# Feature 6: Supplier Bill Settlement with WHT u/s 153
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_supplier_bill_settlement_with_wht_section_153(monkeypatch):
    """Settling supplier bill PKR 500,000 with 5.5% corporate goods WHT u/s 153.
    Deducted WHT = 27,500.
    Net Cash Disbursed = 472,500.
    Bill extinguished = 500,000.
    Journal: Dr AP 500k / Cr Bank 472.5k / Cr WHT Payable 27.5k.
    """
    org_id = uuid.uuid4()
    sup_id = uuid.uuid4()
    bill_id = uuid.uuid4()
    bank_gl = uuid.uuid4()
    ap_gl = uuid.uuid4()
    wht_gl = uuid.uuid4()

    captured_rpc = {}
    allocated = {}

    async def fake_resolve_settlement_gl(*args, **kwargs):
        return bank_gl

    async def fake_resolve_payment_debit_account(*args, **kwargs):
        return ap_gl, None

    async def fake_ensure_wht(*args, **kwargs):
        return {"id": str(wht_gl), "code": "2120", "name": "Withholding Tax Payable u/s 153"}

    async def fake_call_rpc(rpc_name, params=None):
        captured_rpc["params"] = params
        return {
            "payment": {"id": str(uuid.uuid4()), "payment_number": "PAY-00042"},
            "journal_entry_id": str(uuid.uuid4()),
        }

    async def fake_allocate(organization_id, payment_id, bill_id, amount_allocated):
        allocated["bill_id"] = bill_id
        allocated["amount"] = amount_allocated

    async def fake_noop(*args, **kwargs):
        pass

    monkeypatch.setattr(payment_service, "_resolve_settlement_gl", fake_resolve_settlement_gl)
    monkeypatch.setattr(payment_service, "_resolve_payment_debit_account", fake_resolve_payment_debit_account)
    monkeypatch.setattr(payment_service.engine, "ensure_wht_payable_account", fake_ensure_wht)
    monkeypatch.setattr(payment_service, "call_rpc", fake_call_rpc)
    monkeypatch.setattr(payment_service.accounting_service, "validate_journal", fake_noop)
    monkeypatch.setattr(payment_service.accounting_service, "post_journal", fake_noop)
    monkeypatch.setattr(payment_service.repo, "create_payment_allocation", fake_allocate)
    monkeypatch.setattr(payment_service, "_update_bill_paid", fake_noop)

    payment = await payment_service.record_supplier_payment(
        organization_id=org_id,
        supplier_id=sup_id,
        amount=500000.0,
        payment_method="BANK_TRANSFER",
        bank_account_id=bank_gl,
        bill_id=bill_id,
        wht_rate_percent=5.5,
    )

    # Verification of returned payment metadata
    assert payment["wht_amount"] == 27500.0
    assert payment["gross_amount"] == 500000.0

    # Verification of database payment record (net disbursement for bank reconciliation)
    p_payment = captured_rpc["params"]["p_payment"]
    assert p_payment["amount"] == 472500.0

    # Verification of bill allocation (full settlement of payable)
    assert allocated["bill_id"] == bill_id
    assert allocated["amount"] == 500000.0

    # Verification of double-entry ledger lines
    lines = captured_rpc["params"]["p_journal"]["lines"]
    assert len(lines) == 3

    assert lines[0]["account_id"] == str(ap_gl)
    assert lines[0]["debit"] == 500000.0
    assert lines[0]["credit"] == 0.0

    assert lines[1]["account_id"] == str(bank_gl)
    assert lines[1]["debit"] == 0.0
    assert lines[1]["credit"] == 472500.0

    assert lines[2]["account_id"] == str(wht_gl)
    assert lines[2]["debit"] == 0.0
    assert lines[2]["credit"] == 27500.0

    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 500000.0


# ---------------------------------------------------------------------------
# Feature 7 & 8: Payroll Gross-to-Net Booking & Settlement Pair
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_payroll_multi_employee_gross_to_net_cycle(monkeypatch):
    """E2E Multi-Employee Payroll Run:
    Employee 1 (Junior): Basic 45,000 -> Annual 540,000 (Slab 1: Exempt, 0 tax).
    Employee 2 (Manager): Basic 120,000 + 30,000 Allowance = 150,000/mo -> Annual 1.8M (Slab 3: 6,000 tax).
    Employee 3 (Director): Basic 250,000 -> Annual 3.0M (Slab 4: 23,000 tax).

    Total Gross: 45k + 150k + 250k = 445,000.
    Total WHT u/s 149: 0 + 6,000 + 23,000 = 29,000.
    Total Net Accrued: 416,000.

    1. run_payroll accrues:
       Dr Salaries Expense 445,000
       Cr WHT Payable u/s 149 29,000
       Cr Accrued Salaries Payable 416,000
    2. pay_employee_salary disburses net salary on payment date:
       Dr Accrued Salaries Payable 144,000
       Cr Bank 144,000
    """
    org_id = uuid.uuid4()
    emp1_id = uuid.uuid4()
    emp2_id = uuid.uuid4()
    emp3_id = uuid.uuid4()

    exp_gl = uuid.uuid4()
    accrued_gl = uuid.uuid4()
    wht_gl = uuid.uuid4()
    bank_gl = uuid.uuid4()

    roster = [
        {"id": str(emp1_id), "employee_code": "EMP-001", "full_name": "Junior Analyst", "basic_salary": 45000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"},
        {"id": str(emp2_id), "employee_code": "EMP-002", "full_name": "Finance Manager", "basic_salary": 120000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"},
        {"id": str(emp3_id), "employee_code": "EMP-003", "full_name": "Managing Director", "basic_salary": 250000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"},
    ]

    allowances = [
        {"employee_id": str(emp2_id), "description": "Fuel allowance", "amount": 30000.0, "frequency": "MONTHLY", "component_kind": "ALLOWANCE", "effective_from": "2026-01-01", "effective_to": None},
    ]

    captured_run_posting = {}

    async def fake_list_employees(org, limit=500):
        return list(roster)

    async def fake_list_allowances(org, limit=2000):
        return list(allowances)

    async def fake_assert_not_posted(*a, **k):
        pass

    async def fake_resolve_exp(*a, **k):
        return {"id": str(exp_gl), "code": "6010", "name": "Salaries & Wages Expense"}

    async def fake_resolve_acc(*a, **k):
        return {"id": str(accrued_gl), "code": "2130", "name": "Accrued Salaries Payable"}

    async def fake_ensure_wht(*a, **k):
        return {"id": str(wht_gl), "code": "2121", "name": "Withholding Tax Payable u/s 149"}

    async def fake_resolve_bank(*a, **k):
        return {"id": str(bank_gl), "code": "1010", "name": "Meezan Bank Operations"}

    async def fake_post_or_report(**kwargs):
        captured_run_posting.update(kwargs)
        return {"posted": True, "entry": {"id": str(uuid.uuid4())}, "lines": kwargs["lines"], "error": None}

    from app import accounting_engine as test_engine
    monkeypatch.setattr(payroll_service.repo, "list_employees", fake_list_employees)
    monkeypatch.setattr(payroll_service.repo, "list_allowances_for_organization", fake_list_allowances)
    monkeypatch.setattr(payroll_service, "_assert_not_already_posted", fake_assert_not_posted)
    monkeypatch.setattr(payroll_service, "_resolve_salary_expense_account", fake_resolve_exp)
    monkeypatch.setattr(payroll_service, "_resolve_accrued_account", fake_resolve_acc)
    monkeypatch.setattr(test_engine, "ensure_wht_payable_account", fake_ensure_wht)
    monkeypatch.setattr(payroll_service, "_post_or_report", fake_post_or_report)

    # 1. Execute Month-End Payroll Run
    run_result = await payroll_service.run_payroll(
        organization_id=org_id,
        transaction_date="2026-10-31",
        payment_method="ACCRUED",
        apply_income_tax=True,
    )

    assert run_result["gross_total"] == 445000.0
    assert run_result["net_total"] == 416000.0

    # Verify each employee's exact calculation
    emp_map = {e["employee_code"]: e for e in run_result["employees"]}
    assert emp_map["EMP-001"]["gross_pay"] == 45000.0
    assert emp_map["EMP-001"]["tax_withheld"] == 0.0
    assert emp_map["EMP-001"]["net_pay"] == 45000.0

    assert emp_map["EMP-002"]["gross_pay"] == 150000.0
    assert emp_map["EMP-002"]["tax_withheld"] == 6000.0
    assert emp_map["EMP-002"]["net_pay"] == 144000.0

    assert emp_map["EMP-003"]["gross_pay"] == 250000.0
    assert emp_map["EMP-003"]["tax_withheld"] == 23000.0
    assert emp_map["EMP-003"]["net_pay"] == 227000.0

    # Verify Month-End Accrual Lines
    lines = captured_run_posting["lines"]
    assert len(lines) == 3
    # Dr Gross Expense
    assert lines[0]["account_id"] == str(exp_gl)
    assert lines[0]["debit"] == 445000.0
    assert lines[0]["credit"] == 0.0
    # Cr WHT Payable u/s 149
    assert lines[1]["account_id"] == str(wht_gl)
    assert lines[1]["debit"] == 0.0
    assert lines[1]["credit"] == 29000.0
    # Cr Accrued Salaries Payable
    assert lines[2]["account_id"] == str(accrued_gl)
    assert lines[2]["debit"] == 0.0
    assert lines[2]["credit"] == 416000.0
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 445000.0

    # 2. Settle Employee 2's Net Salary on the 5th of Next Month
    captured_pay_posting = {}

    async def fake_post_or_report_pay(**kwargs):
        captured_pay_posting.update(kwargs)
        return {"posted": True, "entry": {"id": str(uuid.uuid4())}, "lines": kwargs["lines"], "error": None}

    async def fake_resolve_emp(org, ref):
        return roster[1]

    async def fake_list_emp_allowances(org, employee_id=None):
        return list(allowances)

    monkeypatch.setattr("app.services.employee_service.resolve", fake_resolve_emp)
    monkeypatch.setattr(payroll_service.repo, "list_allowances", fake_list_emp_allowances)
    monkeypatch.setattr(payroll_service, "_resolve_bank_account", fake_resolve_bank)
    monkeypatch.setattr(payroll_service, "_post_or_report", fake_post_or_report_pay)

    pay_result = await payroll_service.pay_employee_salary(
        organization_id=org_id,
        employee="EMP-002",
        transaction_date="2026-11-05",
        payment_account_id=bank_gl,
        apply_income_tax=True,
    )

    pay_lines = captured_pay_posting["lines"]
    assert len(pay_lines) == 2
    # Dr Accrued Salaries (extinguishes liability)
    assert pay_lines[0]["account_id"] == str(accrued_gl)
    assert pay_lines[0]["debit"] == 144000.0
    assert pay_lines[0]["credit"] == 0.0
    # Cr Bank (money disbursed)
    assert pay_lines[1]["account_id"] == str(bank_gl)
    assert pay_lines[1]["debit"] == 0.0
    assert pay_lines[1]["credit"] == 144000.0
    assert sum(l["debit"] for l in pay_lines) == sum(l["credit"] for l in pay_lines) == 144000.0
