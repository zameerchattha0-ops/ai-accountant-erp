"""Employees module pins — quick entry, LLM-structured allowances, no templates.

The requirement: a full Employees module with ONLY three mandatory fields
(full_name, date_of_joining, basic_salary).  If the user ticks "gets
allowances", the natural-language sentence goes to the AI pipeline — the
MODEL structures it, Python validates and executes.  Python never parses
the sentence, never invents defaults, and never repairs a wrong entry.

Pinned here:
  * the four tools are registered with argument contracts (exact mandatory set);
  * reads are always allowed; mutations stay capability-gated (master_data);
  * create() enforces the three mandatory fields with MODEL-ACTIONABLE errors,
    resolves dates mechanically and drops invented optional keys;
  * set_allowances() takes ONLY structured components — a raw sentence alone
    is never parsed (the LLM does that upstream);
  * invalid amounts / frequencies / descriptions are rejected with a message
    naming what to ask the user;
  * ambiguity RAISES for the agent to ask (codes listed) instead of guessing.
"""

import uuid

import pytest

from app import tool_selector
from app.auth import AuthContext
from app.permissions import check_permission
from app.services import employee_service
from app.services.employee_service import EmployeeInputError

ORG = uuid.uuid4()


def _stub_search(monkeypatch, rows=()):
    async def fake_search(organization_id, *, query, limit=25):
        return list(rows)

    monkeypatch.setattr(employee_service.repo, "search_employees", fake_search)


def _stub_capture_create(monkeypatch, captured):
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {"id": "emp-1", "employee_code": "EMP-000001", "full_name": kwargs["full_name"]}

    monkeypatch.setattr(employee_service.repo, "create_employee", fake_create)


def _stub_employee_by_code(monkeypatch, row):
    async def fake_by_code(organization_id, *, code):
        return dict(row) if row else None

    monkeypatch.setattr(employee_service.repo, "get_employee_by_code", fake_by_code)


def _stub_capture_allowances(monkeypatch, captured):
    async def fake_insert(organization_id, *, employee_id, rows):
        captured["employee_id"] = employee_id
        captured["rows"] = rows
        return rows

    monkeypatch.setattr(employee_service.repo, "insert_allowances", fake_insert)


_EMPLOYEE_ROW = {
    "id": "11111111-1111-1111-1111-111111111111",
    "employee_code": "EMP-000007",
    "full_name": "Ayesha Khan",
    "phone": None,
}


class TestRegistrationAndPermissions:
    def test_four_employee_tools_registered_with_contracts(self):
        import app.tools as tools

        slugs = tools.list_tools()
        for slug in (
            "search_employee",
            "get_employee",
            "create_employee",
            "set_employee_allowances",
        ):
            assert slug in slugs, slug
        contracts = tools.tool_contracts()
        assert contracts["create_employee"]["required"] == (
            "full_name", "date_of_joining", "basic_salary",
        )
        assert contracts["set_employee_allowances"]["required"] == (
            "employee", "allowances",
        )
        assert tools.get_handler("search_employee")["read_only"] is True
        assert tools.get_handler("create_employee")["read_only"] is False
        assert tools.get_handler("set_employee_allowances")["read_only"] is False

    def test_reads_always_allowed_mutations_capability_gated(self):
        auth = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=ORG,
            role_code="ACCOUNTANT",
            role_permissions=["accounting:full"],
        )
        # reads: always allowed (no capability row needed)
        assert check_permission(
            "search_employee", auth=auth, tool_capability_map={}, denied_tools=set()
        )
        assert check_permission(
            "get_employee", auth=auth, tool_capability_map={}, denied_tools=set()
        )
        # mutations: denied until ai.permissions maps them (migration 085)
        assert not check_permission(
            "create_employee", auth=auth, tool_capability_map={}, denied_tools=set()
        )
        mapped = {
            "create_employee": {"master_data"},
            "set_employee_allowances": {"master_data"},
        }
        assert check_permission(
            "create_employee", auth=auth, tool_capability_map=mapped, denied_tools=set()
        )
        assert check_permission(
            "set_employee_allowances",
            auth=auth,
            tool_capability_map=mapped,
            denied_tools=set(),
        )

    def test_unknown_intent_excludes_nothing_and_lookups_are_universal(self):
        assert tool_selector.excluded_for_intent(
            "employee_setup", (), ("create_employee", "search_employee")
        ) == set()
        assert {"search_employee", "get_employee"} <= set(
            tool_selector._LOOKUP_UNIVERSE
        )


class TestCreate:
    @pytest.mark.asyncio
    async def test_minimal_three_fields_are_enough(self, monkeypatch):
        captured: dict = {}
        _stub_capture_create(monkeypatch, captured)
        _stub_search(monkeypatch, rows=[])
        row = await employee_service.create(
            ORG,
            full_name="Ayesha Khan",
            date_of_joining="2026-01-15",
            basic_salary="1,25,000",
        )
        assert captured["date_of_joining"] == "2026-01-15"
        assert captured["basic_salary"] == 125000.0
        assert row["employee_code"] == "EMP-000001"

    @pytest.mark.asyncio
    async def test_dates_resolve_mechanically_and_invented_keys_are_dropped(
        self, monkeypatch
    ):
        captured: dict = {}
        _stub_capture_create(monkeypatch, captured)
        _stub_search(monkeypatch, rows=[])
        await employee_service.create(
            ORG,
            full_name="Ali Raza",
            date_of_joining="yesterday",
            basic_salary=50000,
            iban="PK00INVENTED",
            salary_hack=999,
            designation="Driver",
        )
        import re

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured["date_of_joining"])
        assert "iban" not in captured and "salary_hack" not in captured
        assert captured["designation"] == "Driver"

    @pytest.mark.asyncio
    async def test_mandatory_rejections_name_what_to_ask(self, monkeypatch):
        _stub_capture_create(monkeypatch, {})
        _stub_search(monkeypatch, rows=[])
        with pytest.raises(EmployeeInputError) as err:
            await employee_service.create(
                ORG, full_name="A", date_of_joining="2026-01-01", basic_salary=100
            )
        assert "ask the user" in str(err.value)
        with pytest.raises(EmployeeInputError) as err:
            await employee_service.create(
                ORG, full_name="Ali", date_of_joining="whenever", basic_salary=100
            )
        assert "ask the user" in str(err.value).lower()
        with pytest.raises(EmployeeInputError):
            await employee_service.create(
                ORG, full_name="Ali", date_of_joining="2026-01-01", basic_salary="a lot"
            )
        with pytest.raises(EmployeeInputError):
            await employee_service.create(
                ORG, full_name="Ali", date_of_joining="2026-01-01", basic_salary=0
            )

    @pytest.mark.asyncio
    async def test_exact_name_match_is_reused_not_duplicated(self, monkeypatch):
        _stub_search(
            monkeypatch,
            rows=[{"id": "e1", "employee_code": "EMP-000009",
                   "full_name": "Ayesha Khan", "phone": None}],
        )

        async def boom(**kwargs):  # noqa: D401 - must never run
            raise AssertionError("a duplicate insert was attempted")

        monkeypatch.setattr(employee_service.repo, "create_employee", boom)
        row = await employee_service.create(
            ORG,
            full_name="  ayesha khan ",
            date_of_joining="2026-02-01",
            basic_salary=90000,
        )
        assert row["reused_existing"] is True
        assert row["employee_code"] == "EMP-000009"


def _stub_get_by_id_none(monkeypatch):
    async def fake_get(organization_id, *, employee_id):
        return None

    monkeypatch.setattr(employee_service.repo, "get_employee", fake_get)


class TestSetAllowances:
    @pytest.mark.asyncio
    async def test_llm_structured_components_validate_and_write_rows(
        self, monkeypatch
    ):
        _stub_get_by_id_none(monkeypatch)
        _stub_employee_by_code(monkeypatch, _EMPLOYEE_ROW)
        _stub_search(monkeypatch, rows=[])
        captured: dict = {}
        _stub_capture_allowances(monkeypatch, captured)
        execution_id = uuid.uuid4()

        result = await employee_service.set_allowances(
            ORG,
            employee="EMP-000007",
            allowances=[
                {"description": "House rent", "amount": "25,000",
                 "frequency": "monthly"},
                {"description": "Fuel allowance", "amount": 10000,
                 "frequency": "MONTHLY", "allowance_type": "transport"},
                {"description": "Medical", "amount": 30000,
                 "frequency": "one-time"},
                {"description": "Late-arrival deduction", "amount": 2000,
                 "frequency": "MONTHLY", "component_kind": "deduction"},
            ],
            raw_text="house rent 25k monthly, fuel 10k, medical 30k one time",
            ai_execution_id=execution_id,
        )
        rows = captured["rows"]
        assert [r["frequency"] for r in rows] == [
            "MONTHLY", "MONTHLY", "ONE_TIME", "MONTHLY",
        ]
        assert rows[0]["amount"] == 25000.0
        assert rows[0]["source"] == "AI"
        assert rows[0]["raw_text"].startswith("house rent 25k")
        assert rows[0]["allowance_type"] == "HOUSE_RENT"
        assert rows[1]["allowance_type"] == "TRANSPORT"
        assert rows[3]["component_kind"] == "DEDUCTION"
        assert str(execution_id) == rows[0]["ai_execution_id"]
        # totals: monthly = rent + fuel (deduction excluded), one-time = medical
        assert result["monthly_total"] == 35000.0
        assert result["one_time_total"] == 30000.0
        assert result["employee"]["employee_code"] == "EMP-000007"
        assert captured["employee_id"] == uuid.UUID(_EMPLOYEE_ROW["id"])

    @pytest.mark.asyncio
    async def test_a_raw_sentence_alone_is_never_parsed_by_python(
        self, monkeypatch
    ):
        _stub_get_by_id_none(monkeypatch)
        _stub_employee_by_code(monkeypatch, _EMPLOYEE_ROW)
        with pytest.raises(EmployeeInputError) as err:
            await employee_service.set_allowances(
                ORG,
                employee="EMP-000007",
                allowances=[],
                raw_text="house rent 25,000 per month and fuel 10,000",
            )
        # the LLM structures the sentence upstream; Python only validates
        assert "structure the user's sentence" in str(err.value)

    @pytest.mark.asyncio
    async def test_invalid_components_are_rejected_with_model_actionable_text(
        self, monkeypatch
    ):
        _stub_get_by_id_none(monkeypatch)
        _stub_employee_by_code(monkeypatch, _EMPLOYEE_ROW)
        base = {"employee": "EMP-000007"}
        with pytest.raises(EmployeeInputError) as err:
            await employee_service.set_allowances(
                ORG, **base, allowances=[{"amount": 5000}]
            )
        assert "ask the user" in str(err.value)
        with pytest.raises(EmployeeInputError) as err:
            await employee_service.set_allowances(
                ORG, **base, allowances=[{"description": "Rent", "amount": "a lot"}]
            )
        assert "not a number" in str(err.value)
        with pytest.raises(EmployeeInputError) as err:
            await employee_service.set_allowances(
                ORG, **base,
                allowances=[{"description": "Rent", "amount": 100, "frequency": "weekly"}],
            )
        assert "MONTHLY, ONE_TIME, ANNUAL" in str(err.value)
        with pytest.raises(EmployeeInputError):
            await employee_service.set_allowances(
                ORG, **base, allowances=["house rent 25000"]
            )

    @pytest.mark.asyncio
    async def test_ambiguous_name_raises_for_the_agent_to_ask(self, monkeypatch):
        _stub_get_by_id_none(monkeypatch)
        _stub_employee_by_code(monkeypatch, None)
        _stub_search(
            monkeypatch,
            rows=[
                {"id": "a", "employee_code": "EMP-000001", "full_name": "Ayesha Khan"},
                {"id": "b", "employee_code": "EMP-000002", "full_name": "Ayesha Khan"},
            ],
        )
        with pytest.raises(EmployeeInputError) as err:
            await employee_service.set_allowances(
                ORG,
                employee="Ayesha Khan",
                allowances=[{"description": "Rent", "amount": 1000}],
            )
        text = str(err.value)
        assert "More than one employee matches" in text
        assert "EMP-000001" in text and "EMP-000002" in text

