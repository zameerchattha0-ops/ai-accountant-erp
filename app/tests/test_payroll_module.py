"""Payroll module pins (Employees Phase 2) — salaries computed, never guessed.

The requirement: the agent can run salaries end to end —
``run_payroll`` (Dr Salaries / Cr Accrued Salaries, or Cr bank when paid) and
``pay_employee_salary`` (Dr Accrued Salaries / Cr bank).  The MODEL structures
the user's sentence; Python computes every amount from the employee records
(basic + active MONTHLY allowances − deductions) and posts the journal through
the accounting engine — it never takes a figure from the model, never pays a
ONE-TIME component in a recurring run, and never posts the same payroll twice.

Pinned here:
  * both tools are registered with argument contracts (pay_employee_salary
    requires ``employee``; run_payroll computes everything);
  * mutations stay capability-gated (payroll capability, migration 086) while
    the intent requires confirmation and a resolved transaction date;
  * the run's journal is balanced, per-run, and lands on the resolved accounts;
  * resigned / not-yet-joined employees are skipped AND disclosed;
  * ONE-TIME / ANNUAL components are deferred AND disclosed (no double pay);
  * a POSTED journal for the same event+date refuses a silent double-post;
  * missing ledgers raise MODEL-ACTIONABLE errors instead of guessing;
  * a failed journal is reported (journal_posted False) — never a silent
    success, and the tool handler surfaces it as a FAILED call.
"""

import uuid

import pytest

from app import planner
from app import tool_selector
from app.auth import AuthContext
from app.idempotency import FINANCIAL_WRITE_TOOLS, INTENT_ONLY_NAMES
from app.permissions import check_permission
from app.reasoning import DATE_REQUIRED_INTENTS
from app.services import payroll_service
from app.services.payroll_service import PayrollInputError

ORG = uuid.uuid4()

EMP1 = "11111111-1111-1111-1111-111111111111"
EMP2 = "22222222-2222-2222-2222-222222222222"
EMP3 = "33333333-3333-3333-3333-333333333333"
EMP4 = "44444444-4444-4444-4444-444444444444"

SALARIES_ACCOUNT = {"id": "aaaaaaaa-0000-0000-0000-000000000001", "code": "6010", "name": "Salaries"}
ACCRUED_ACCOUNT = {"id": "aaaaaaaa-0000-0000-0000-000000000002", "code": "2130", "name": "Accrued Salaries"}
BANK_ACCOUNT = {"id": "aaaaaaaa-0000-0000-0000-000000000003", "code": "1010", "name": "Bank — HBL"}


def _employee(employee_id, code, name, basic, status="ACTIVE", **extra):
    row = {
        "id": employee_id,
        "employee_code": code,
        "full_name": name,
        "basic_salary": basic,
        "status": status,
        "is_active": status not in ("RESIGNED", "TERMINATED"),
        "date_of_joining": "2026-01-01",
    }
    row.update(extra)
    return row


ROSTER = [
    _employee(EMP1, "EMP-000001", "Ayesha Khan", 50000, department="Finance"),
    _employee(EMP2, "EMP-000002", "Bilal Ahmed", 30000, status="PROBATION", department="Sales"),
    _employee(EMP3, "EMP-000003", "Former Employee", 40000, status="RESIGNED"),
    _employee(EMP4, "EMP-000004", "Future Joiner", 25000, date_of_joining="2026-10-15"),
]

ALLOWANCES = [
    {"employee_id": EMP1, "description": "House rent", "amount": 25000,
     "frequency": "MONTHLY", "component_kind": "ALLOWANCE",
     "effective_from": "2026-01-01", "effective_to": None},
    {"employee_id": EMP1, "description": "Health insurance", "amount": 5000,
     "frequency": "MONTHLY", "component_kind": "DEDUCTION",
     "effective_from": "2026-01-01", "effective_to": None},
    {"employee_id": EMP1, "description": "One-time medical", "amount": 30000,
     "frequency": "ONE_TIME", "component_kind": "ALLOWANCE",
     "effective_from": "2026-09-01", "effective_to": None},
    {"employee_id": EMP1, "description": "Old bonus", "amount": 9000,
     "frequency": "MONTHLY", "component_kind": "ALLOWANCE",
     "effective_from": "2026-01-01", "effective_to": "2026-03-31"},
    {"employee_id": EMP2, "description": "Transport", "amount": 5000,
     "frequency": "MONTHLY", "component_kind": "ALLOWANCE",
     "effective_from": "2026-01-01", "effective_to": None},
]


def _stub_roster(monkeypatch, rows=ROSTER):
    async def fake_list(organization_id, *, limit=500):
        return list(rows)

    monkeypatch.setattr(payroll_service.repo, "list_employees", fake_list)


def _stub_org_allowances(monkeypatch, rows=ALLOWANCES):
    async def fake_list(organization_id, *, limit=2000):
        return list(rows)

    monkeypatch.setattr(
        payroll_service.repo, "list_allowances_for_organization", fake_list
    )


def _stub_employee_allowances(monkeypatch, rows=ALLOWANCES):
    async def fake_list(organization_id, *, employee_id, limit=50):
        return [r for r in rows if str(r.get("employee_id")) == str(employee_id)]

    monkeypatch.setattr(payroll_service.repo, "list_allowances", fake_list)


def _stub_existing_journals(monkeypatch, rows=()):
    async def fake_fetch(table, **kwargs):
        assert table == "journal_entries"
        return list(rows)

    monkeypatch.setattr(payroll_service, "fetch_many", fake_fetch)


def _stub_accounts(
    monkeypatch, *, expense=SALARIES_ACCOUNT, liability=ACCRUED_ACCOUNT,
    settlement=BANK_ACCOUNT,
):
    async def fake_resolve_gl(
        organization_id, *, account_type, keywords, explicit_id,
        exclude_keywords=(),
    ):
        if account_type == "EXPENSE":
            return expense
        if account_type == "LIABILITY":
            return liability
        return None

    async def fake_resolve_settlement(organization_id, *, payment_account_id):
        return settlement

    monkeypatch.setattr(payroll_service, "_resolve_gl_account", fake_resolve_gl)
    monkeypatch.setattr(
        payroll_service, "_resolve_settlement_account", fake_resolve_settlement
    )


def _stub_journal(monkeypatch, captured, *, fail=None):
    async def fake_post(**kwargs):
        if fail:
            raise RuntimeError(fail)
        captured.update(kwargs)
        return {
            "entry": {"id": "je-0001", "journal_number": "JV-0001", "status": "POSTED"},
            "lines": kwargs.get("lines"),
        }

    monkeypatch.setattr(payroll_service, "_post_journal", fake_post)


class TestRegistrationAndPermissions:
    def test_both_tools_registered_with_contracts(self):
        import app.tools as tools

        slugs = tools.list_tools()
        assert "run_payroll" in slugs
        assert "pay_employee_salary" in slugs
        contracts = tools.tool_contracts()
        # A run computes everything from the roster; a single payment needs
        # to know WHO is paid.
        assert contracts["run_payroll"]["required"] == ()
        assert contracts["pay_employee_salary"]["required"] == ("employee",)
        assert tools.get_handler("run_payroll")["read_only"] is False
        assert tools.get_handler("pay_employee_salary")["read_only"] is False

    def test_payroll_mutations_are_capability_gated(self):
        auth = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=ORG,
            role_code="ACCOUNTANT",
            role_permissions=["accounting:full"],
        )
        # unmapped → denied (the ai.permissions row is migration 086)
        assert not check_permission(
            "run_payroll", auth=auth, tool_capability_map={}, denied_tools=set()
        )
        mapped = {
            "run_payroll": {"payroll"},
            "pay_employee_salary": {"payroll"},
        }
        assert check_permission(
            "run_payroll", auth=auth, tool_capability_map=mapped, denied_tools=set()
        )
        assert check_permission(
            "pay_employee_salary",
            auth=auth,
            tool_capability_map=mapped,
            denied_tools=set(),
        )
        sales = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=ORG,
            role_code="SALES",
            role_permissions=["sales:manage"],
        )
        assert not check_permission(
            "run_payroll", auth=sales, tool_capability_map=mapped, denied_tools=set()
        )

    def test_payroll_tools_write_the_books(self):
        assert {"run_payroll", "pay_employee_salary"} <= FINANCIAL_WRITE_TOOLS
        assert not ({"run_payroll", "pay_employee_salary"} & INTENT_ONLY_NAMES)


class TestIntentRouting:
    @pytest.mark.parametrize(
        "phrase",
        [
            "run payroll for September",
            "pay salaries today",
            "pay Ahmad his salary",
            "process the payroll",
            "record the salaries payment",
        ],
    )
    def test_action_phrasings_route_to_run_payroll(self, phrase):
        assert planner._identify_intent(phrase) == "run_payroll"

    def test_query_phrasing_is_not_dragged_into_the_mutation(self):
        assert planner._identify_intent("show me payroll details") != "run_payroll"

    def test_confirmation_and_date_required_amount_is_computed(self):
        assert planner.intent_requires_confirmation("run_payroll")
        assert "run_payroll" in DATE_REQUIRED_INTENTS
        # the amount is COMPUTED from the records — never asked for
        assert "run_payroll" not in planner._TRANSACTION_INTENTS
        missing = planner._missing_fields("run_payroll", {})
        assert "transaction_date" in missing
        assert "amount" not in missing
        assert planner._missing_fields(
            "run_payroll", {"transaction_date": "2026-09-30"}
        ) == []

    def test_shortlist_and_fix5_reconcile(self):
        shortlist = tool_selector.tools_for_intent(
            "run_payroll", planner._tools_for_intent("run_payroll")
        )
        assert {
            "run_payroll", "pay_employee_salary", "search_employee",
            "get_employee", "list_bank_accounts",
        } <= shortlist
        # a plan naming the single-employee tool under another intent is
        # reconciled to the payroll intent (and inherits its confirmation gate)
        assert tool_selector.reconcile_intent_with_tools(
            "record_expense", ["pay_employee_salary"]
        ) == ("run_payroll", set())
        assert tool_selector.reconcile_intent_with_tools(
            "run_payroll", ["run_payroll"]
        ) == ("run_payroll", set())


class TestRunPayroll:
    @pytest.mark.asyncio
    async def test_accrued_run_posts_one_balanced_journal_from_records(
        self, monkeypatch
    ):
        captured: dict = {}
        _stub_roster(monkeypatch)
        _stub_org_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured)

        result = await payroll_service.run_payroll(
            ORG, transaction_date="2026-09-30"
        )

        assert result["journal_posted"] is True
        assert result["period"] == "September 2026"
        assert result["payment_method"] == "ACCRUED"
        assert result["employee_count"] == 2
        # Ayesha: 50,000 + 25,000 rent − 5,000 insurance = 70,000
        # Bilal:  30,000 + 5,000 transport            = 35,000
        assert result["gross_total"] == 110000.0
        assert result["deductions_total"] == 5000.0
        assert result["net_total"] == 105000.0
        # resigned + not-yet-joined are skipped AND disclosed (never silent)
        assert {row["employee_code"] for row in result["skipped_employees"]} == {
            "EMP-000003", "EMP-000004",
        }
        # ONE_TIME (and expired) components never enter a recurring run
        assert [c["description"] for c in result["deferred_components"]] == [
            "One-time medical"
        ]
        lines = captured["lines"]
        assert len(lines) == 2
        assert lines[0]["account_id"] == SALARIES_ACCOUNT["id"]
        assert lines[0]["debit"] == 105000.0
        assert lines[1]["account_id"] == ACCRUED_ACCOUNT["id"]
        assert lines[1]["credit"] == 105000.0
        assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)
        assert captured["source_type"] == "payroll_run"
        assert captured["transaction_date"] == "2026-09-30"

    @pytest.mark.asyncio
    async def test_paid_run_credits_the_bank(self, monkeypatch):
        captured: dict = {}
        _stub_roster(monkeypatch)
        _stub_org_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured)

        result = await payroll_service.run_payroll(
            ORG, transaction_date="2026-09-30", payment_method="paid out"
        )

        assert result["payment_method"] == "PAID"
        assert captured["lines"][1]["account_id"] == BANK_ACCOUNT["id"]
        assert captured["lines"][1]["credit"] == 105000.0

    @pytest.mark.asyncio
    async def test_department_filter_narrows_the_roster(self, monkeypatch):
        captured: dict = {}
        _stub_roster(monkeypatch)
        _stub_org_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured)

        result = await payroll_service.run_payroll(
            ORG, transaction_date="2026-09-30", department="sales"
        )

        assert result["employee_count"] == 1
        assert result["net_total"] == 35000.0

    @pytest.mark.asyncio
    async def test_unknown_settlement_is_a_model_actionable_error(
        self, monkeypatch
    ):
        _stub_roster(monkeypatch)
        _stub_org_allowances(monkeypatch)
        with pytest.raises(PayrollInputError) as exc:
            await payroll_service.run_payroll(
                ORG, transaction_date="2026-09-30", payment_method="maybe"
            )
        assert "ACCRUED" in str(exc.value) and "PAID" in str(exc.value)

    @pytest.mark.asyncio
    async def test_missing_accrual_ledger_asks_instead_of_guessing(
        self, monkeypatch
    ):
        captured: dict = {}
        _stub_roster(monkeypatch)
        _stub_org_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch, liability=None)
        _stub_journal(monkeypatch, captured)

        with pytest.raises(PayrollInputError) as exc:
            await payroll_service.run_payroll(ORG, transaction_date="2026-09-30")

        assert "Accrued Salaries" in str(exc.value)
        assert captured == {}  # nothing was posted

    @pytest.mark.asyncio
    async def test_no_eligible_employee_raises(self, monkeypatch):
        _stub_roster(
            monkeypatch,
            rows=[_employee(EMP3, "EMP-000003", "Former", 1000, status="RESIGNED")],
        )
        with pytest.raises(PayrollInputError) as exc:
            await payroll_service.run_payroll(ORG, transaction_date="2026-09-30")
        assert "No pay-eligible employee" in str(exc.value)

    @pytest.mark.asyncio
    async def test_posted_duplicate_is_refused_draft_does_not_block(
        self, monkeypatch
    ):
        captured: dict = {}
        _stub_roster(monkeypatch)
        _stub_org_allowances(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured)
        _stub_existing_journals(
            monkeypatch,
            rows=[{
                "id": "je-9", "journal_number": "JV-0009",
                "status": "POSTED", "description": "Salaries — September 2026",
            }],
        )
        with pytest.raises(PayrollInputError) as exc:
            await payroll_service.run_payroll(ORG, transaction_date="2026-09-30")
        assert "ALREADY posted" in str(exc.value)
        assert captured == {}

        # a DRAFT leftover (an aborted attempt) must not wedge the retry
        _stub_existing_journals(
            monkeypatch,
            rows=[{"id": "je-9", "journal_number": "JV-0009", "status": "DRAFT"}],
        )
        result = await payroll_service.run_payroll(
            ORG, transaction_date="2026-09-30"
        )
        assert result["journal_posted"] is True

    @pytest.mark.asyncio
    async def test_journal_failure_is_reported_never_silent(self, monkeypatch):
        captured: dict = {}
        _stub_roster(monkeypatch)
        _stub_org_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured, fail="accounting period closed")

        result = await payroll_service.run_payroll(
            ORG, transaction_date="2026-09-30"
        )

        assert result["journal_posted"] is False
        assert "accounting period closed" in result["journal_error"]
        assert result["net_total"] == 105000.0  # the computation survives


class TestPayEmployeeSalary:
    def _stub_resolution(self, monkeypatch, row=ROSTER[0], error=None):
        async def fake_resolve(organization_id, reference):
            if error:
                raise payroll_service.employee_service.EmployeeInputError(error)
            return dict(row)

        monkeypatch.setattr(
            payroll_service.employee_service, "resolve", fake_resolve
        )

    @pytest.mark.asyncio
    async def test_settles_the_accrual_with_the_computed_amount(self, monkeypatch):
        captured: dict = {}
        _stub_employee_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured)
        self._stub_resolution(monkeypatch)

        result = await payroll_service.pay_employee_salary(
            ORG, employee="Ayesha Khan", transaction_date="2026-09-30"
        )

        # 50,000 + 25,000 rent − 5,000 insurance = 70,000
        assert result["amount"] == 70000.0
        assert result["amount_source"] == "EMPLOYEE_RECORDS"
        assert result["journal_posted"] is True
        lines = captured["lines"]
        assert lines[0]["account_id"] == ACCRUED_ACCOUNT["id"]
        assert lines[0]["debit"] == 70000.0
        assert lines[1]["account_id"] == BANK_ACCOUNT["id"]
        assert lines[1]["credit"] == 70000.0
        assert captured["source_type"] == "salary_payment"
        assert captured["source_id"] == uuid.UUID(EMP1)

    @pytest.mark.asyncio
    async def test_user_stated_amount_wins_over_the_records(self, monkeypatch):
        captured: dict = {}
        _stub_employee_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured)
        self._stub_resolution(monkeypatch)

        result = await payroll_service.pay_employee_salary(
            ORG, employee="EMP-000001", amount="45,000",
            transaction_date="2026-09-30",
        )

        assert result["amount"] == 45000.0
        assert result["amount_source"] == "USER_STATED"
        assert captured["lines"][0]["debit"] == 45000.0

    @pytest.mark.asyncio
    async def test_unknown_employee_raises_the_question(self, monkeypatch):
        self._stub_resolution(
            monkeypatch,
            error="No employee matches 'Nobody' — ask the user for the exact name.",
        )
        with pytest.raises(PayrollInputError) as exc:
            await payroll_service.pay_employee_salary(ORG, employee="Nobody")
        assert "No employee matches" in str(exc.value)

    @pytest.mark.asyncio
    async def test_blank_employee_asks_which_employee(self, monkeypatch):
        with pytest.raises(PayrollInputError) as exc:
            await payroll_service.pay_employee_salary(ORG, employee="   ")
        assert "Which employee" in str(exc.value)

    @pytest.mark.asyncio
    async def test_no_accrual_ledger_books_the_expense_directly(self, monkeypatch):
        captured: dict = {}
        _stub_employee_allowances(monkeypatch)
        _stub_existing_journals(monkeypatch)
        _stub_accounts(monkeypatch, liability=None)
        _stub_journal(monkeypatch, captured)
        self._stub_resolution(monkeypatch)

        result = await payroll_service.pay_employee_salary(
            ORG, employee="Ayesha Khan", transaction_date="2026-09-30"
        )

        assert captured["lines"][0]["account_id"] == SALARIES_ACCOUNT["id"]
        assert result["debit_account"]["id"] == SALARIES_ACCOUNT["id"]

    @pytest.mark.asyncio
    async def test_same_day_double_payment_is_refused(self, monkeypatch):
        captured: dict = {}
        _stub_employee_allowances(monkeypatch)
        _stub_accounts(monkeypatch)
        _stub_journal(monkeypatch, captured)
        self._stub_resolution(monkeypatch)
        _stub_existing_journals(
            monkeypatch,
            rows=[{"id": "je-7", "journal_number": "JV-0007", "status": "POSTED"}],
        )

        with pytest.raises(PayrollInputError) as exc:
            await payroll_service.pay_employee_salary(
                ORG, employee="Ayesha Khan", transaction_date="2026-09-30"
            )
        assert "ALREADY posted" in str(exc.value)
        assert captured == {}


class TestToolHandlers:
    @pytest.mark.asyncio
    async def test_input_error_becomes_a_failed_call(self, monkeypatch):
        import app.tools as tools

        handler = tools.get_handler("run_payroll")["handler"]

        async def boom(organization_id, **kw):
            raise PayrollInputError("No pay-eligible employee found")

        monkeypatch.setattr(payroll_service, "run_payroll", boom)
        result = await handler(ORG)
        assert result.success is False
        assert "No pay-eligible employee" in result.error

    @pytest.mark.asyncio
    async def test_unposted_journal_becomes_a_failed_call(self, monkeypatch):
        import app.tools as tools

        handler = tools.get_handler("pay_employee_salary")["handler"]

        async def fake(organization_id, **kw):
            return {
                "journal_posted": False,
                "journal_error": "accounting period closed",
                "amount": 1.0,
            }

        monkeypatch.setattr(payroll_service, "pay_employee_salary", fake)
        result = await handler(ORG, employee="EMP-000001")
        assert result.success is False
        assert "NOT recorded" in result.error
        assert "accounting period closed" in result.error




