"""Tier 1 Statutory & Legal Exposure Tests — Pakistan IFRS & Tax Regimes.

Verifies:
1. Sales Tax splitting (Exclusive, Inclusive back-calculation, Exempt) u/s Sales Tax Act 1990.
2. Section 149 progressive salary income tax deduction across all 8 statutory slabs.
3. Double-entry tax splitting in accounting engine (Dr AR / Cr Net Revenue & Cr GST Output Payable).
4. Withholding Tax deduction u/s 153 in supplier payments (Dr AP / Cr Net Cash & Cr WHT Payable).
5. Payroll Gross-to-Net accounting u/s 149 & IAS 19 (Dr Gross Expense / Cr WHT Payable & Cr Accrued Salaries).
6. Organization tax profile & preference persistence.
7. Fixed-format Questionnaire contract for tax options.
"""
import uuid
import pytest

from app.services import tax_service
from app.services import payroll_service
from app.services import payment_service
from app import accounting_engine as engine
from app.questionnaire import QUESTION_BANK


# ---------------------------------------------------------------------------
# 1. Tax Calculation & Slabs Tests
# ---------------------------------------------------------------------------

def test_exclusive_sales_tax_split():
    """Exclusive GST: 18% added on top of net PKR 100,000 -> Tax 18,000, Gross 118,000."""
    res = tax_service.calculate_tax_split(100000.0, rate_percent=18.0, pricing_mode="EXCLUSIVE")
    assert res["net_amount"] == 100000.0
    assert res["tax_amount"] == 18000.0
    assert res["gross_amount"] == 118000.0
    assert res["pricing_mode"] == "EXCLUSIVE"


def test_inclusive_sales_tax_split():
    """Inclusive GST: Price PKR 118,000 includes 18% -> Net 100,000, Tax 18,000."""
    res = tax_service.calculate_tax_split(118000.0, rate_percent=18.0, pricing_mode="INCLUSIVE")
    assert res["net_amount"] == 100000.0
    assert res["tax_amount"] == 18000.0
    assert res["gross_amount"] == 118000.0
    assert res["pricing_mode"] == "INCLUSIVE"


def test_exempt_sales_tax_split():
    """Exempt GST: 0% tax -> Net = Gross, Tax = 0."""
    res = tax_service.calculate_tax_split(50000.0, rate_percent=18.0, pricing_mode="EXEMPT")
    assert res["net_amount"] == 50000.0
    assert res["tax_amount"] == 0.0
    assert res["gross_amount"] == 50000.0


def test_provincial_services_rates():
    """PRA (16%) and SRB (15%) provincial services sales tax rates."""
    pra = tax_service.calculate_tax_split(10000.0, rate_percent=16.0, pricing_mode="EXCLUSIVE")
    assert pra["tax_amount"] == 1600.0
    assert pra["gross_amount"] == 11600.0

    srb = tax_service.calculate_tax_split(10000.0, rate_percent=15.0, pricing_mode="EXCLUSIVE")
    assert srb["tax_amount"] == 1500.0
    assert srb["gross_amount"] == 11500.0


def test_section_149_all_eight_slabs():
    """Verify Section 149 salary tax withholding against all 8 statutory slabs:

    Slab 1: Up to 600,000 -> 0%
    Slab 2: 600,001 to 1,200,000 -> 1% of excess over 600k
    Slab 3: 1,200,001 to 2,200,000 -> 6,000 + 11% of excess over 1.2M
    Slab 4: 2,200,001 to 3,200,000 -> 116,000 + 20% of excess over 2.2M
    Slab 5: 3,200,001 to 4,100,000 -> 316,000 + 25% of excess over 3.2M
    Slab 6: 4,100,001 to 5,600,000 -> 541,000 + 29% of excess over 4.1M
    Slab 7: 5,600,001 to 7,000,000 -> 976,000 + 32% of excess over 5.6M
    Slab 8: Exceeding 7,000,000 -> 1,424,000 + 35% of excess over 7.0M
    """
    # Slab 1: Monthly 40,000 -> Annual 480,000 <= 600k -> Tax = 0
    s1 = tax_service.calculate_salary_tax_withholding(40000.0)
    assert s1["slab"] == 1
    assert s1["annual_tax"] == 0.0
    assert s1["monthly_tax"] == 0.0

    # Slab 2: Monthly 80,000 -> Annual 960,000
    # Annual Tax = (960,000 - 600,000) * 0.01 = 360,000 * 0.01 = 3,600
    # Monthly Tax = 3,600 / 12 = 300
    s2 = tax_service.calculate_salary_tax_withholding(80000.0)
    assert s2["slab"] == 2
    assert s2["annual_tax"] == 3600.0
    assert s2["monthly_tax"] == 300.0

    # Slab 3: Monthly 150,000 -> Annual 1,800,000
    # Annual Tax = 6,000 + (1,800,000 - 1,200,000) * 0.11 = 6,000 + 66,000 = 72,000
    # Monthly Tax = 72,000 / 12 = 6,000
    s3 = tax_service.calculate_salary_tax_withholding(150000.0)
    assert s3["slab"] == 3
    assert s3["annual_tax"] == 72000.0
    assert s3["monthly_tax"] == 6000.0

    # Slab 4: Monthly 250,000 -> Annual 3,000,000
    # Annual Tax = 116,000 + (3,000,000 - 2,200,000) * 0.20 = 116,000 + 160,000 = 276,000
    # Monthly Tax = 276,000 / 12 = 23,000
    s4 = tax_service.calculate_salary_tax_withholding(250000.0)
    assert s4["slab"] == 4
    assert s4["annual_tax"] == 276000.0
    assert s4["monthly_tax"] == 23000.0

    # Slab 5: Monthly 300,000 -> Annual 3,600,000
    # Annual Tax = 316,000 + (3,600,000 - 3,200,000) * 0.25 = 316,000 + 100,000 = 416,000
    # Monthly Tax = 416,000 / 12 = 34,666.67
    s5 = tax_service.calculate_salary_tax_withholding(300000.0)
    assert s5["slab"] == 5
    assert s5["annual_tax"] == 416000.0
    assert s5["monthly_tax"] == 34666.67

    # Slab 6: Monthly 400,000 -> Annual 4,800,000
    # Annual Tax = 541,000 + (4,800,000 - 4,100,000) * 0.29 = 541,000 + 203,000 = 744,000
    # Monthly Tax = 744,000 / 12 = 62,000
    s6 = tax_service.calculate_salary_tax_withholding(40000.0)
    assert s6["slab"] == 1

    s6_high = tax_service.calculate_salary_tax_withholding(400000.0)
    assert s6_high["slab"] == 6
    assert s6_high["annual_tax"] == 744000.0
    assert s6_high["monthly_tax"] == 62000.0

    # Slab 7: Monthly 500,000 -> Annual 6,000,000
    # Annual Tax = 976,000 + (6,000,000 - 5,600,000) * 0.32 = 976,000 + 128,000 = 1,104,000
    # Monthly Tax = 1,104,000 / 12 = 92,000
    s7 = tax_service.calculate_salary_tax_withholding(500000.0)
    assert s7["slab"] == 7
    assert s7["annual_tax"] == 1104000.0
    assert s7["monthly_tax"] == 92000.0

    # Slab 8: Monthly 700,000 -> Annual 8,400,000
    # Annual Tax = 1,424,000 + (8,400,000 - 7,000,000) * 0.35 = 1,424,000 + 490,000 = 1,914,000
    # Monthly Tax = 1,914,000 / 12 = 159,500
    s8 = tax_service.calculate_salary_tax_withholding(700000.0)
    assert s8["slab"] == 8
    assert s8["annual_tax"] == 1914000.0
    assert s8["monthly_tax"] == 159500.0


# ---------------------------------------------------------------------------
# 2. Questionnaire Specs
# ---------------------------------------------------------------------------

def test_questionnaire_tax_specs():
    """Verify Questionnaire Bank contains statutory tax & withholding choice cards."""
    assert "tax_pricing_mode" in QUESTION_BANK
    spec = QUESTION_BANK["tax_pricing_mode"]
    assert spec.kind == "choice"
    option_values = [v for v, _ in spec.options]
    assert "EXCLUSIVE" in option_values
    assert "INCLUSIVE" in option_values
    assert "EXEMPT" in option_values
    assert "PRA_16" in option_values
    assert "SRB_15" in option_values

    assert "withholding_tax_rate" in QUESTION_BANK
    wht_spec = QUESTION_BANK["withholding_tax_rate"]
    assert wht_spec.kind == "choice"
    wht_options = [v for v, _ in wht_spec.options]
    assert "NONE" in wht_options
    assert "GOODS_CORP" in wht_options
    assert "SERVICES_CORP" in wht_options


# ---------------------------------------------------------------------------
# 3. Accounting Engine Sales Tax Splitting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_credit_sale_with_tax_split(monkeypatch):
    """Credit sale with GST split: Dr AR (Gross 118k) / Cr Sales (Net 100k) / Cr Output Tax (18k)."""
    org_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    tax_id = uuid.uuid4()

    captured_journal = {}

    async def fake_prepare_journal(**kwargs):
        captured_journal.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    from app.services import accounting_service
    monkeypatch.setattr(accounting_service, "prepare_journal", fake_prepare_journal)

    # Exclusive pricing mode test
    await engine.record_credit_sale(
        organization_id=org_id,
        customer_id=cust_id,
        receivable_account_id=ar_id,
        revenue_account_id=rev_id,
        amount=100000.0,
        transaction_date="2026-10-31",
        description="Sale of goods",
        tax_pricing_mode="EXCLUSIVE",
        tax_rate_percent=18.0,
        tax_account_id=tax_id,
    )

    lines = captured_journal["lines"]
    assert len(lines) == 3
    # Dr Receivable: 118,000
    assert lines[0]["account_id"] == str(ar_id)
    assert lines[0]["debit"] == 118000.0
    assert lines[0]["credit"] == 0
    # Cr Revenue: 100,000
    assert lines[1]["account_id"] == str(rev_id)
    assert lines[1]["debit"] == 0
    assert lines[1]["credit"] == 100000.0
    # Cr Sales Tax Output Payable: 18,000
    assert lines[2]["account_id"] == str(tax_id)
    assert lines[2]["debit"] == 0
    assert lines[2]["credit"] == 18000.0
    # Invariant: debits == credits
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)


@pytest.mark.asyncio
async def test_record_credit_sale_inclusive_back_calculation(monkeypatch):
    """Credit sale with GST Inclusive: Dr AR (118k) / Cr Sales (100k) / Cr Output Tax (18k)."""
    org_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    tax_id = uuid.uuid4()

    captured_journal = {}

    async def fake_prepare_journal(**kwargs):
        captured_journal.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    from app.services import accounting_service
    monkeypatch.setattr(accounting_service, "prepare_journal", fake_prepare_journal)

    await engine.record_credit_sale(
        organization_id=org_id,
        customer_id=cust_id,
        receivable_account_id=ar_id,
        revenue_account_id=rev_id,
        amount=118000.0,
        transaction_date="2026-10-31",
        description="Inclusive sale",
        tax_pricing_mode="INCLUSIVE",
        tax_rate_percent=18.0,
        tax_account_id=tax_id,
    )

    lines = captured_journal["lines"]
    assert len(lines) == 3
    assert lines[0]["debit"] == 118000.0
    assert lines[1]["credit"] == 100000.0
    assert lines[2]["credit"] == 18000.0
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)


# ---------------------------------------------------------------------------
# 4. Supplier Payment Withholding Tax u/s 153 Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_supplier_payment_with_wht(monkeypatch):
    """Supplier bill settlement PKR 100k subject to 5.5% WHT u/s 153:
    Debit: Accounts Payable 100,000
    Credit: Bank 94,500
    Credit: WHT Payable u/s 153 5,500
    Total Debits == Total Credits == 100,000.
    """
    org_id = uuid.uuid4()
    sup_id = uuid.uuid4()
    bill_id = uuid.uuid4()
    bank_id = uuid.uuid4()
    wht_acc_id = uuid.uuid4()

    captured_rpc = {}

    async def fake_resolve_settlement_gl(*args, **kwargs):
        return uuid.uuid4()

    async def fake_resolve_payment_debit_account(*args, **kwargs):
        return uuid.uuid4(), None

    async def fake_ensure_wht(*args, **kwargs):
        return {"id": str(wht_acc_id), "code": "2120", "name": "Withholding Tax Payable u/s 153"}

    async def fake_call_rpc(rpc_name, params=None):
        captured_rpc["name"] = rpc_name
        captured_rpc["params"] = params
        return {
            "payment": {"id": str(uuid.uuid4()), "payment_number": "PAY-001"},
            "journal_entry_id": str(uuid.uuid4()),
        }

    async def fake_noop(*args, **kwargs):
        pass

    async def fake_get_bill(*args, **kwargs):
        return {"id": str(bill_id), "total": 100000.0, "amount_paid": 0.0, "status": "OPEN", "bill_number": "PUR-001"}

    monkeypatch.setattr(payment_service.pur_repo, "get_purchase_bill", fake_get_bill)
    monkeypatch.setattr(payment_service, "_resolve_settlement_gl", fake_resolve_settlement_gl)
    monkeypatch.setattr(payment_service, "_resolve_payment_debit_account", fake_resolve_payment_debit_account)
    monkeypatch.setattr(payment_service.engine, "ensure_wht_payable_account", fake_ensure_wht)
    monkeypatch.setattr(payment_service, "call_rpc", fake_call_rpc)
    monkeypatch.setattr(payment_service.accounting_service, "validate_journal", fake_noop)
    monkeypatch.setattr(payment_service.accounting_service, "post_journal", fake_noop)
    monkeypatch.setattr(payment_service.repo, "create_payment_allocation", fake_noop)
    monkeypatch.setattr(payment_service, "_update_bill_paid", fake_noop)

    # Explicit WHT rate 5.5%
    payment = await payment_service.record_supplier_payment(
        organization_id=org_id,
        supplier_id=sup_id,
        amount=100000.0,
        payment_method="BANK_TRANSFER",
        bank_account_id=bank_id,
        bill_id=bill_id,
        wht_rate_percent=5.5,
    )

    assert payment["wht_amount"] == 5500.0
    assert payment["gross_amount"] == 100000.0

    lines = captured_rpc["params"]["p_journal"]["lines"]
    assert len(lines) == 3
    # AP debited for full 100k
    assert lines[0]["debit"] == 100000.0
    assert lines[0]["credit"] == 0
    # Bank credited for net 94.5k
    assert lines[1]["debit"] == 0
    assert lines[1]["credit"] == 94500.0
    # WHT Payable credited for 5.5k
    assert lines[2]["debit"] == 0
    assert lines[2]["credit"] == 5500.0
    assert lines[2]["account_id"] == str(wht_acc_id)
    # Total debits == total credits
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)


# ---------------------------------------------------------------------------
# 5. Payroll Gross-to-Net Accounting u/s 149 & IAS 19
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payroll_gross_to_net_with_section_149(monkeypatch):
    """Payroll run with Section 149 progressive tax deduction:
    Gross = 150,000 / month -> Annual 1,800,000 -> Slab 3 (PKR 6,000/mo tax).
    Debit: Salaries Gross Expense 150,000
    Credit: WHT Payable u/s 149 6,000
    Credit: Accrued Salaries Payable 144,000
    Balanced journal: 150,000 debits == 150,000 credits.
    """
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    wht_acc_id = uuid.uuid4()

    employee = {
        "id": str(emp_id),
        "employee_code": "EMP-999",
        "full_name": "Senior Accountant",
        "basic_salary": 150000.0,
        "status": "ACTIVE",
        "is_active": True,
        "date_of_joining": "2026-01-01",
    }

    async def fake_list_employees(org, limit=500):
        return [employee]

    async def fake_list_allowances(org, limit=2000):
        return []

    async def fake_assert_not_posted(*a, **k):
        pass

    async def fake_resolve_exp(*a, **k):
        return {"id": str(uuid.uuid4()), "code": "6010"}

    async def fake_resolve_acc(*a, **k):
        return {"id": str(uuid.uuid4()), "code": "2130"}

    async def fake_ensure_wht(*a, **k):
        return {"id": str(wht_acc_id), "code": "2121"}

    captured_posting = {}

    async def fake_post_or_report(**kwargs):
        captured_posting.update(kwargs)
        return {"posted": True, "entry": {"id": str(uuid.uuid4())}, "lines": kwargs["lines"]}

    from app import accounting_engine as test_engine
    monkeypatch.setattr(payroll_service.repo, "list_employees", fake_list_employees)
    monkeypatch.setattr(payroll_service.repo, "list_allowances_for_organization", fake_list_allowances)
    monkeypatch.setattr(payroll_service, "_assert_not_already_posted", fake_assert_not_posted)
    monkeypatch.setattr(payroll_service, "_resolve_salary_expense_account", fake_resolve_exp)
    monkeypatch.setattr(payroll_service, "_resolve_accrued_account", fake_resolve_acc)
    monkeypatch.setattr(test_engine, "ensure_wht_payable_account", fake_ensure_wht)
    monkeypatch.setattr(payroll_service, "_post_or_report", fake_post_or_report)

    result = await payroll_service.run_payroll(
        organization_id=org_id,
        transaction_date="2026-10-31",
        payment_method="ACCRUED",
        apply_income_tax=True,
    )

    pays = result["employees"]
    assert len(pays) == 1
    p = pays[0]
    assert p["gross_pay"] == 150000.0
    assert p["tax_withheld"] == 6000.0
    assert p["net_pay"] == 144000.0

    lines = captured_posting["lines"]
    assert len(lines) == 3
    # Dr Salaries Gross Expense: 150k
    assert lines[0]["debit"] == 150000.0
    assert lines[0]["credit"] == 0
    # Cr WHT Payable u/s 149: 6k
    assert lines[1]["debit"] == 0
    assert lines[1]["credit"] == 6000.0
    # Cr Accrued Salaries Payable: 144k
    assert lines[2]["debit"] == 0
    assert lines[2]["credit"] == 144000.0

    # Strict invariant: Debits == Credits
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)
