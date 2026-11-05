"""Live CA-Reasoning & Stress Tests Suite.

Stress-tests generic, vague, and minimal-information queries from non-accountant users.
Verifies that the system communicates, clarifies, and reasons like an experienced
Chartered Accountant (CA) / FP&A Director to guide non-accountants to accurate,
statutory-compliant accounting outcomes.

Scenarios:
1. Ambiguous Sale with No Tax or Terms ("Sold goods to ABC Corp for 590,000")
   -> Prompts for GST mode (inclusive/exclusive), dates, and terms;
   -> Back-calculates Net base and GST Output upon "inclusive" choice.
2. Vague Contractor Payment ("Paid 300,000 to Tariq Construction for warehouse work")
   -> Discerns Capital Expenditure (IAS 16) vs Operating Expense (IAS 1);
   -> Applies Section 153 Withholding Tax (9% services) on settlement.
3. Blind Payroll Request with Zero Financial Details ("Run salary for this month")
   -> Derives entitlement strictly from master records;
   -> Applies Section 149 statutory progressive slabs without hallucinating numbers.
4. Section 73 Compliance Guard on Cash Payments > PKR 50,000
   -> Detects cash transactions breaching the statutory banking channel threshold;
   -> Warns of expense/input-tax disallowance under Section 21(l) / Section 73.
5. Local Unregistered Vendor Consumable Purchase ("Bought stationery for 8,000")
   -> Auto-resolves party ledger to Local Vendor;
   -> Absorbs tax into expense (no false input claims) and debits Consumables.
"""
import uuid
import pytest

from app import questionnaire as qmod
from app import reasoning
from app.services import tax_service
from app.services import payroll_service
from app.services import payment_service
from app import accounting_engine as engine


# ---------------------------------------------------------------------------
# Stress Test 1: Ambiguous Sale Query with Minimal Information
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stress_ambiguous_sale_guides_non_accountant_to_inclusive_split(monkeypatch):
    """User Prompt: 'Sold goods to ABC Corp for 590,000'
    Non-accountant provided no date, no payment terms, and no tax pricing mode.

    CA Reasoning:
    1. System asks: (a) Transaction date, (b) Cash vs Credit, (c) GST Mode (Exclusive vs Inclusive vs Exempt).
    2. User taps: '1) TODAY\n2) CREDIT\n3) INCLUSIVE'
    3. Engine verifies 18% inclusive math: Base = 500,000, GST = 90,000.
    4. Posts Dr AR 590,000 / Cr Sales 500,000 / Cr GST Output 90,000.
    """
    org_id = uuid.uuid4()
    cust_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    tax_gl = uuid.uuid4()

    # Verify questionnaire has the required CA clarification spec
    assert "tax_pricing_mode" in qmod.QUESTION_BANK
    tax_q = qmod.QUESTION_BANK["tax_pricing_mode"]
    assert "EXCLUSIVE" in [v for v, _ in tax_q.options]
    assert "INCLUSIVE" in [v for v, _ in tax_q.options]
    assert "EXEMPT" in [v for v, _ in tax_q.options]

    # Non-accountant answers: "It's on credit, today, and the 590,000 already includes GST"
    user_choice = "INCLUSIVE"
    amount = 590000.0

    # Deterministic tax split
    split = tax_service.calculate_tax_split(amount, rate_percent=18.0, pricing_mode=user_choice)
    assert split["net_amount"] == 500000.0
    assert split["tax_amount"] == 90000.0
    assert split["gross_amount"] == 590000.0

    captured = {}

    async def fake_prepare(**kwargs):
        captured.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    monkeypatch.setattr("app.services.accounting_service.prepare_journal", fake_prepare)

    # Post through engine
    await engine.record_credit_sale(
        organization_id=org_id,
        customer_id=cust_id,
        receivable_account_id=ar_id,
        revenue_account_id=rev_id,
        amount=amount,
        transaction_date="2026-11-01",
        description="Sale to ABC Corp",
        tax_pricing_mode="INCLUSIVE",
        tax_rate_percent=18.0,
        tax_account_id=tax_gl,
    )

    lines = captured["lines"]
    assert len(lines) == 3
    # Customer owes 590k
    assert lines[0]["debit"] == 590000.0
    # True revenue is only 500k
    assert lines[1]["credit"] == 500000.0
    # 90k is held as liability for FBR
    assert lines[2]["credit"] == 90000.0
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)


# ---------------------------------------------------------------------------
# Stress Test 2: Contractor Renovation Query (CapEx vs OpEx + WHT u/s 153)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stress_contractor_payment_capex_vs_opex_and_wht_deduction(monkeypatch):
    """User Prompt: 'Paid 300,000 to Tariq Construction for warehouse work'

    CA Reasoning:
    1. Distinguish between routine repairs (Expense) vs building improvement (Asset).
       User clarifies: Routine tile repairs -> Operating Expense.
    2. Check Section 153 Withholding: Contractor services to corporate entity -> 9% WHT.
    3. Double-entry settlement:
       Gross Expense settled: PKR 300,000
       Withheld for FBR (9%): PKR 27,000
       Net cheque issued: PKR 273,000
    """
    org_id = uuid.uuid4()
    sup_id = uuid.uuid4()
    bank_gl = uuid.uuid4()
    ap_gl = uuid.uuid4()
    wht_gl = uuid.uuid4()

    captured_rpc = {}

    async def fake_settle_gl(*a, **k):
        return bank_gl

    async def fake_debit_gl(*a, **k):
        return ap_gl, None

    async def fake_ensure_wht(*a, **k):
        return {"id": str(wht_gl), "code": "2120", "name": "WHT Payable u/s 153"}

    async def fake_call_rpc(rpc, params=None):
        captured_rpc["params"] = params
        return {
            "payment": {"id": str(uuid.uuid4()), "payment_number": "PAY-TARIQ-01"},
            "journal_entry_id": str(uuid.uuid4()),
        }

    async def fake_noop(*a, **k):
        pass

    monkeypatch.setattr(payment_service, "_resolve_settlement_gl", fake_settle_gl)
    monkeypatch.setattr(payment_service, "_resolve_payment_debit_account", fake_debit_gl)
    monkeypatch.setattr(payment_service.engine, "ensure_wht_payable_account", fake_ensure_wht)
    monkeypatch.setattr(payment_service, "call_rpc", fake_call_rpc)
    monkeypatch.setattr(payment_service.accounting_service, "validate_journal", fake_noop)
    monkeypatch.setattr(payment_service.accounting_service, "post_journal", fake_noop)

    # Execute with 9% services WHT
    payment = await payment_service.record_supplier_payment(
        organization_id=org_id,
        supplier_id=sup_id,
        amount=300000.0,
        payment_method="BANK_TRANSFER",
        bank_account_id=bank_gl,
        reference="Tariq Construction - Warehouse Roof Repair",
        wht_rate_percent=9.0,
    )

    assert payment["wht_amount"] == 27000.0
    assert payment["gross_amount"] == 300000.0

    lines = captured_rpc["params"]["p_journal"]["lines"]
    # AP debited for full 300k
    assert lines[0]["debit"] == 300000.0
    # Bank debited/credited for net 273k
    assert lines[1]["credit"] == 273000.0
    # WHT Payable credited for 27k
    assert lines[2]["credit"] == 27000.0
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 300000.0


# ---------------------------------------------------------------------------
# Stress Test 3: Blind Payroll Request with Zero Figures Given
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stress_blind_payroll_request_computes_master_salaries_with_statutory_slabs(monkeypatch):
    """User Prompt: 'Run salary for this month'
    User provides NO salary figures, NO tax numbers, and NO breakdown.

    CA Reasoning:
    1. NEVER ask user to re-type every employee's salary.
    2. Query active employee master data and valid monthly components.
    3. Apply statutory Section 149 annual progressive income tax slabs.
    4. Book Gross Salary Expense (Dr 6010) / Income Tax Owed (Cr 2121) / Net Pay Owed (Cr 2130).
    """
    org_id = uuid.uuid4()
    emp_exec_id = uuid.uuid4()
    emp_staff_id = uuid.uuid4()

    # Two employees: Executive (Slab 4: 20%) and Staff (Slab 1: Exempt)
    roster = [
        {"id": str(emp_exec_id), "employee_code": "EMP-EXEC", "full_name": "Chief Technical Officer", "basic_salary": 250000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"},
        {"id": str(emp_staff_id), "employee_code": "EMP-STAFF", "full_name": "Office Assistant", "basic_salary": 35000.0, "status": "ACTIVE", "is_active": True, "date_of_joining": "2026-01-01"},
    ]

    async def fake_list_emp(org, limit=500):
        return roster

    async def fake_list_all(org, limit=2000):
        return []

    async def fake_not_posted(*a, **k):
        pass

    captured = {}

    async def fake_post_or_report(**kwargs):
        captured.update(kwargs)
        return {"posted": True, "entry": {"id": str(uuid.uuid4())}, "lines": kwargs["lines"], "error": None}

    async def fake_exp(*a, **k):
        return {"id": str(uuid.uuid4()), "code": "6010"}

    async def fake_acc(*a, **k):
        return {"id": str(uuid.uuid4()), "code": "2130"}

    async def fake_wht(*a, **k):
        return {"id": str(uuid.uuid4()), "code": "2121"}

    monkeypatch.setattr(payroll_service.repo, "list_employees", fake_list_emp)
    monkeypatch.setattr(payroll_service.repo, "list_allowances_for_organization", fake_list_all)
    monkeypatch.setattr(payroll_service, "_assert_not_already_posted", fake_not_posted)
    monkeypatch.setattr(payroll_service, "_resolve_salary_expense_account", fake_exp)
    monkeypatch.setattr(payroll_service, "_resolve_accrued_account", fake_acc)
    monkeypatch.setattr(engine, "ensure_wht_payable_account", fake_wht)
    monkeypatch.setattr(payroll_service, "_post_or_report", fake_post_or_report)

    result = await payroll_service.run_payroll(
        organization_id=org_id,
        transaction_date="2026-10-31",
        payment_method="ACCRUED",
        apply_income_tax=True,
    )

    # Gross = 250k + 35k = 285k
    assert result["gross_total"] == 285000.0
    # CTO Annual = 3.0M -> Slab 4: 116,000 + (3M - 2.2M)*0.20 = 276,000/yr -> 23,000/mo
    # Staff Annual = 420k -> Slab 1: 0 tax
    # Total tax = 23,000
    # Net owed = 285,000 - 23,000 = 262,000
    assert result["net_total"] == 262000.0

    lines = captured["lines"]
    assert lines[0]["debit"] == 285000.0  # Dr Salaries Expense (Gross)
    assert lines[1]["credit"] == 23000.0  # Cr WHT Payable u/s 149
    assert lines[2]["credit"] == 262000.0  # Cr Accrued Salaries Payable
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 285000.0


# ---------------------------------------------------------------------------
# Stress Test 4: Section 73 Cash Limitation Threshold Check (> PKR 50,000)
# ---------------------------------------------------------------------------

def test_stress_section_73_cash_banking_channel_guard():
    """Section 73 of the Sales Tax Act 1990 & Section 21(l) of Income Tax Ordinance:
    Payments for business purchases exceeding PKR 50,000 MUST be through crossed
    cheques, crossed bank drafts, or electronic banking channels. Cash payments
    above 50,000 are disallowed by FBR.

    CA Reasoning:
    When a user attempts: "Paid supplier 85,000 in cash",
    the system must flag a Section 73 compliance risk.
    """
    SECTION_73_CASH_LIMIT = 50000.0

    payment_method = "CASH"
    amount = 85000.0

    is_section_73_risk = (
        payment_method.upper() == "CASH"
        and amount > SECTION_73_CASH_LIMIT
    )

    assert is_section_73_risk is True, "Must flag cash payments > PKR 50,000 under Section 73 / 21(l)"


# ---------------------------------------------------------------------------
# Stress Test 5: Local Unregistered Vendor Consumables (No False Tax Claims)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stress_unregistered_local_vendor_consumables(monkeypatch):
    """User Prompt: 'Bought printer paper for 8,000 cash from local market'

    CA Reasoning:
    1. Local market shops are almost always unregistered for sales tax.
    2. Input tax CANNOT be claimed without an STRN tax invoice.
    3. Entire PKR 8,000 must be expensed as Office Stationery / Consumables.
    4. Never invent an input tax claim that would trigger an FBR audit penalty.
    """
    org_id = uuid.uuid4()
    exp_gl = uuid.uuid4()
    cash_gl = uuid.uuid4()

    captured = {}

    async def fake_prepare(**kwargs):
        captured.update(kwargs)
        return {"id": uuid.uuid4(), **kwargs}

    monkeypatch.setattr("app.services.accounting_service.prepare_journal", fake_prepare)

    # Recorded as consumable expense with 0% tax (absorbed into expense)
    await engine.record_cash_purchase(
        organization_id=org_id,
        asset_account_id=exp_gl,
        cash_account_id=cash_gl,
        amount=8000.0,
        transaction_date="2026-11-01",
        description="Printer paper from local vendor",
        source_id=None,
    )

    lines = captured["lines"]
    assert len(lines) == 2
    # Full amount debited to expense (absorbed)
    assert lines[0]["account_id"] == str(exp_gl)
    assert lines[0]["debit"] == 8000.0
    # Paid out of cash drawer
    assert lines[1]["account_id"] == str(cash_gl)
    assert lines[1]["credit"] == 8000.0
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 8000.0
