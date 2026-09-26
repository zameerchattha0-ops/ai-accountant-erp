"""Credit Note + Debit Note module: journals, tools, endpoints, questionnaire.

Pinned invariants:
* ENGINE: ``record_credit_note`` posts Dr Revenue / Cr Receivable
  (source_type=credit_note) and ``record_purchase_return`` posts Dr
  Payable / Cr Expense (source_type=purchase_return) — the exact mirrors
  of the invoice/bill entries, built deterministically.
* AUTO-JOURNAL: ``auto_journal`` supports credit_note / purchase_return
  with the invoice/bill account-resolution conventions (party ledger
  first, control-account fallback).
* TOOLS: create_credit_note / create_purchase_return auto-validate,
  auto-post, source-tie the journal and leave DRAFT (ISSUED / OPEN) —
  the same discipline as create_invoice.  Never an LLM decision.
* ENDPOINTS: /api/sales/credit-notes and /api/purchases/debit-notes
  (list/detail/create/status) with org scoping and 409 validations.
* QUESTIONNAIRE: the consolidated-questionnaire instruction and the
  options_per_part cleaning survive in the reasoning layer.
* CATEGORIES: items never become accounts (Furniture & Fixtures for
  chairs/beds/tables, Fixtures & Fittings, ...) and ASSET categories
  hang under the chart's PPE heading when one exists.
"""

import uuid
from types import SimpleNamespace

import pytest

import app.accounting_engine as engine
import app.services.accounting_service as accounting_service
from app.account_resolution import category_for_item, heading_account_id
from app.models.schemas import ToolResult

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
REV = uuid.UUID("22222222-2222-2222-2222-222222222222")
AR = uuid.UUID("33333333-3333-3333-3333-333333333333")
AP = uuid.UUID("44444444-4444-4444-4444-444444444444")
EXP = uuid.UUID("55555555-5555-5555-5555-555555555555")
CUST = uuid.UUID("66666666-6666-6666-6666-666666666666")
SUPP = uuid.UUID("77777777-7777-7777-7777-777777777777")


class TestEngineBuilders:
    @pytest.mark.asyncio
    async def test_credit_note_entry_reverses_the_sale(self, monkeypatch):
        captured = {}

        async def fake_prepare(**kw):
            captured.update(kw)
            return {"entry": {"id": str(uuid.uuid4())}}

        monkeypatch.setattr(accounting_service, "prepare_journal", fake_prepare)
        await engine.record_credit_note(
            organization_id=ORG,
            customer_id=CUST,
            receivable_account_id=AR,
            revenue_account_id=REV,
            amount=5000,
            transaction_date="2026-09-25",
            description="Credit note CN-1",
            source_id=None,
        )
        lines = captured["lines"]
        assert captured["source_type"] == "credit_note"
        assert len(lines) == 2
        # Dr Revenue (sale reversed) / Cr Receivable (balance shrinks)
        assert lines[0]["account_id"] == str(REV)
        assert lines[0]["debit"] == 5000 and lines[0]["credit"] == 0
        assert lines[1]["account_id"] == str(AR)
        assert lines[1]["debit"] == 0 and lines[1]["credit"] == 5000
        assert "Sales reversal" in lines[0]["description"]

    @pytest.mark.asyncio
    async def test_purchase_return_entry_reverses_the_bill(self, monkeypatch):
        captured = {}

        async def fake_prepare(**kw):
            captured.update(kw)
            return {"entry": {"id": str(uuid.uuid4())}}

        monkeypatch.setattr(accounting_service, "prepare_journal", fake_prepare)
        await engine.record_purchase_return(
            organization_id=ORG,
            supplier_id=SUPP,
            expense_account_id=EXP,
            payable_account_id=AP,
            amount=9000,
            transaction_date="2026-09-25",
            description="Purchase return DN-1",
            source_id=None,
        )
        lines = captured["lines"]
        assert captured["source_type"] == "purchase_return"
        assert len(lines) == 2
        # Dr Payable (payable shrinks) / Cr Expense (purchase reversed)
        assert lines[0]["account_id"] == str(AP)
        assert lines[0]["debit"] == 9000 and lines[0]["credit"] == 0
        assert lines[1]["account_id"] == str(EXP)
        assert lines[1]["debit"] == 0 and lines[1]["credit"] == 9000


class TestAutoJournalBranches:
    @pytest.mark.asyncio
    async def test_credit_note_resolves_party_ledger_then_revenue(self, monkeypatch):
        from app.services import party_ledger_service

        calls = {}

        async def fake_receivable(org_id, customer_id):
            return None  # force the control-account fallback chain

        async def fake_resolve(org_id, *, account_name):
            return {"id": str(AR), "name": account_name}

        async def fake_default(org_id, kind, fallback_type=None):
            return {"id": str(REV), "account_type": kind}

        async def fake_record(**kw):
            calls.update(kw)
            return {"entry": {"id": str(uuid.uuid4())}}

        monkeypatch.setattr(
            party_ledger_service, "resolve_customer_receivable_account", fake_receivable
        )
        monkeypatch.setattr(accounting_service, "resolve_account", fake_resolve)
        monkeypatch.setattr(engine, "_resolve_default_account", fake_default)
        monkeypatch.setattr(engine, "record_credit_note", fake_record)

        result = await engine.auto_journal(
            organization_id=ORG,
            document_type="credit_note",
            document={"id": str(uuid.uuid4())},
            amount=500,
            transaction_date="2026-09-25",
            description="Credit note CN-9",
            customer_id=CUST,
        )
        assert "journal_entry" in result
        assert calls["receivable_account_id"] == AR
        assert calls["revenue_account_id"] == REV

    @pytest.mark.asyncio
    async def test_purchase_return_resolves_payable_then_expense(self, monkeypatch):
        from app.services import party_ledger_service

        calls = {}

        async def fake_payable(org_id, supplier_id):
            return None

        async def fake_resolve(org_id, *, account_name):
            return {"id": str(AP), "name": account_name}

        async def fake_default(org_id, kind, fallback_type=None):
            return {"id": str(EXP), "account_type": kind}

        async def fake_record(**kw):
            calls.update(kw)
            return {"entry": {"id": str(uuid.uuid4())}}

        monkeypatch.setattr(
            party_ledger_service, "resolve_supplier_payable_account", fake_payable
        )
        monkeypatch.setattr(accounting_service, "resolve_account", fake_resolve)
        monkeypatch.setattr(engine, "_resolve_default_account", fake_default)
        monkeypatch.setattr(engine, "record_purchase_return", fake_record)

        result = await engine.auto_journal(
            organization_id=ORG,
            document_type="purchase_return",
            document={"id": str(uuid.uuid4())},
            amount=900,
            transaction_date="2026-09-25",
            description="Purchase return DN-9",
            supplier_id=SUPP,
        )
        assert "journal_entry" in result
        assert calls["payable_account_id"] == AP
        assert calls["expense_account_id"] == EXP

    @pytest.mark.asyncio
    async def test_unsupported_document_type_still_warns(self):
        result = await engine.auto_journal(
            organization_id=ORG,
            document_type="quotation",
            document={},
            amount=100,
            transaction_date="2026-09-25",
            description="x",
        )
        assert "journal_warning" in result


class TestToolJournalOrchestration:
    """create_credit_note / create_purchase_return mirror create_invoice:
    prepare → validate → post → source-tie → leave DRAFT."""

    async def _run(self, monkeypatch, *, tool_name, doc, status=None):
        from app import tools as tools_mod
        from app.repositories import credit_note_repository as cn_repo
        from app.repositories import purchase_return_repository as pr_repo

        entry_id = uuid.uuid4()
        calls = {"validated": None, "posted": None, "linked": None, "marked": 0}

        async def fake_service(**kw):
            return dict(doc)

        async def fake_auto_journal(**kw):
            calls["auto"] = kw
            return {"journal_entry": {"entry": {"id": str(entry_id)}}}

        async def fake_validate(*, entry_id):
            calls["validated"] = entry_id

        async def fake_post(*, entry_id):
            calls["posted"] = entry_id

        monkeypatch.setattr(tools_mod, "auto_journal", fake_auto_journal)
        monkeypatch.setattr(accounting_service, "validate_journal", fake_validate)
        monkeypatch.setattr(accounting_service, "post_journal", fake_post)

        if tool_name == "create_credit_note":
            monkeypatch.setattr(
                tools_mod.credit_note_service, "create_credit_note",
                fake_service,
                raising=True,
            )

            async def fake_link(*, credit_note_id, journal_entry_id):
                calls["linked"] = (credit_note_id, journal_entry_id)

            async def fake_mark(*, credit_note_id):
                calls["marked"] += 1

            monkeypatch.setattr(cn_repo, "link_journal_to_credit_note", fake_link)
            monkeypatch.setattr(cn_repo, "mark_issued", fake_mark)
        else:
            monkeypatch.setattr(
                tools_mod.purchase_return_service, "create_purchase_return",
                fake_service,
                raising=True,
            )

            async def fake_link(*, return_id, journal_entry_id):
                calls["linked"] = (return_id, journal_entry_id)

            async def fake_mark(*, return_id):
                calls["marked"] += 1

            monkeypatch.setattr(pr_repo, "link_journal_to_purchase_return", fake_link)
            monkeypatch.setattr(pr_repo, "mark_open", fake_mark)

        handler = tools_mod._TOOL_REGISTRY[tool_name]["handler"]
        result = await handler(ORG)
        return result, calls, entry_id

    @pytest.mark.asyncio
    async def test_credit_note_tool_posts_and_links(self, monkeypatch):
        doc = {
            "id": str(uuid.uuid4()),
            "credit_note_number": "CN-000001",
            "credit_note_date": "2026-09-25",
            "customer_id": str(CUST),
            "total": 5000,
            "status": "DRAFT",
        }
        result, calls, entry_id = await self._run(
            monkeypatch,
            tool_name="create_credit_note",
            doc=doc,
            status="ISSUED",
        )
        assert isinstance(result, ToolResult) and result.success
        assert result.data["status"] == "ISSUED"
        assert result.data["journal_posted"] is True
        assert result.data["journal_entry_id"] == str(entry_id)
        assert calls["validated"] == entry_id
        assert calls["posted"] == entry_id
        assert calls["linked"][1] == entry_id
        assert calls["marked"] == 1

    @pytest.mark.asyncio
    async def test_purchase_return_tool_posts_and_links(self, monkeypatch):
        doc = {
            "id": str(uuid.uuid4()),
            "return_number": "DN-000001",
            "return_date": "2026-09-25",
            "supplier_id": str(SUPP),
            "total": 900,
            "status": "DRAFT",
        }
        result, calls, entry_id = await self._run(
            monkeypatch,
            tool_name="create_purchase_return",
            doc=doc,
            status="OPEN",
        )
        assert isinstance(result, ToolResult) and result.success
        assert result.data["status"] == "OPEN"
        assert result.data["journal_posted"] is True
        assert result.data["journal_entry_id"] == str(entry_id)
        assert calls["linked"][1] == entry_id
        assert calls["marked"] == 1

    @pytest.mark.asyncio
    async def test_zero_total_skips_journal_without_failing(self, monkeypatch):
        from app import tools as tools_mod

        doc = {
            "id": str(uuid.uuid4()),
            "credit_note_number": "CN-000002",
            "credit_note_date": "2026-09-25",
            "customer_id": str(CUST),
            "total": 0,
            "status": "DRAFT",
        }

        async def fake_service(**kw):
            return dict(doc)

        async def fake_auto_journal(**kw):  # pragma: no cover — must not run
            raise AssertionError("zero-total notes never journal")

        monkeypatch.setattr(
            tools_mod.credit_note_service, "create_credit_note", fake_service
        )
        monkeypatch.setattr(tools_mod, "auto_journal", fake_auto_journal)
        handler = tools_mod._TOOL_REGISTRY["create_credit_note"]["handler"]
        result = await handler(ORG)
        assert result.success and result.data["status"] == "DRAFT"
        assert "journal_posted" not in result.data


def _auth():
    return SimpleNamespace(organization_id=ORG, user_id=uuid.uuid4())


class TestEndpoints:
    """REST endpoints for the Credit Note / Debit Note modules.

    Called directly (async) so the contract pins behavior without an HTTP
    client dependency; FastAPI only resolves Depends() at request time.
    """

    @pytest.mark.asyncio
    async def test_list_credit_notes_filters_and_joins_names(self, monkeypatch):
        from app import main as main_mod
        from app.repositories import credit_note_repository as cn_repo

        rows = [
            {"id": "1", "credit_note_number": "CN-000001", "status": "DRAFT",
             "customer_id": "c1", "reason": "damaged chair"},
            {"id": "2", "credit_note_number": "CN-000002", "status": "ISSUED",
             "customer_id": "c2", "reason": "discount"},
        ]

        async def fake_list(org_id, *, limit=500):
            return rows

        async def fake_fetch_many(table, **kw):
            return [
                {"id": "c1", "name": "Alpha Traders"},
                {"id": "c2", "name": "Beta Co"},
            ]

        monkeypatch.setattr(cn_repo, "list_credit_notes", fake_list)
        monkeypatch.setattr(main_mod, "fetch_many", fake_fetch_many)

        out = await main_mod.list_credit_notes_endpoint(
            query="", status="ALL", auth=_auth()
        )
        assert out["count"] == 2
        assert out["items"][0]["customer_name"] == "Alpha Traders"

        out = await main_mod.list_credit_notes_endpoint(
            query="cn-000002", status="ALL", auth=_auth()
        )
        assert out["count"] == 1 and out["items"][0]["id"] == "2"

        out = await main_mod.list_credit_notes_endpoint(
            query="", status="ISSUED", auth=_auth()
        )
        assert out["count"] == 1 and out["items"][0]["status"] == "ISSUED"

    @pytest.mark.asyncio
    async def test_get_credit_note_404(self, monkeypatch):
        from app import main as main_mod
        from app.repositories import credit_note_repository as cn_repo
        from fastapi import HTTPException

        async def fake_get(org_id, *, credit_note_id):
            return None

        monkeypatch.setattr(cn_repo, "get_credit_note", fake_get)
        with pytest.raises(HTTPException) as exc:
            await main_mod.get_credit_note_endpoint(uuid.uuid4(), auth=_auth())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_credit_note_validates_reason(self):
        from app import main as main_mod
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await main_mod.create_credit_note_endpoint(
                {"customer_id": "c1", "items": [{"description": "x"}]}, auth=_auth()
            )
        assert exc.value.status_code == 409
        assert "reason" in str(exc.value.detail).lower()

        with pytest.raises(HTTPException) as exc:
            await main_mod.create_credit_note_endpoint(
                {"customer_id": "c1", "reason": "refund"}, auth=_auth()
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_create_credit_note_delegates_to_service(self, monkeypatch):
        from app import main as main_mod
        from app.services import credit_note_service

        created = {"id": "n1", "credit_note_number": "CN-000009", "total": 100}
        captured = {}

        async def fake_create(**kw):
            captured.update(kw)
            return created

        monkeypatch.setattr(credit_note_service, "create_credit_note", fake_create)
        out = await main_mod.create_credit_note_endpoint(
            {
                "customer_id": "c1",
                "reason": "refund",
                "items": [{"description": "chair", "quantity": 1, "unit_price": 100}],
                "credit_note_date": "2026-09-25",
            },
            auth=_auth(),
        )
        assert out["item"]["credit_note_number"] == "CN-000009"
        assert captured["organization_id"] == ORG
        assert captured["credit_note_date"] == "2026-09-25"

    @pytest.mark.asyncio
    async def test_patch_credit_note_status_guards_enum(self, monkeypatch):
        from app import main as main_mod
        from app.repositories import credit_note_repository as cn_repo
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await main_mod.update_credit_note_status_endpoint(
                uuid.uuid4(), {"status": "PAID"}, auth=_auth()
            )
        assert exc.value.status_code == 409

        async def fake_get(org_id, *, credit_note_id):
            return {"id": str(credit_note_id), "status": "DRAFT"}

        async def fake_set(*, credit_note_id, status):
            return {"id": str(credit_note_id), "status": status}

        monkeypatch.setattr(cn_repo, "get_credit_note", fake_get)
        monkeypatch.setattr(cn_repo, "set_status", fake_set)
        out = await main_mod.update_credit_note_status_endpoint(
            uuid.uuid4(), {"status": "VOIDED"}, auth=_auth()
        )
        assert out["item"]["status"] == "VOIDED"

    @pytest.mark.asyncio
    async def test_debit_note_endpoints_validate_party_and_status(self, monkeypatch):
        from app import main as main_mod
        from app.repositories import purchase_return_repository as pr_repo
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await main_mod.create_debit_note_endpoint(
                {"reason": "returned", "items": [{"description": "x"}]}, auth=_auth()
            )
        assert exc.value.status_code == 409
        assert "supplier" in str(exc.value.detail).lower()

        with pytest.raises(HTTPException) as exc:
            await main_mod.update_debit_note_status_endpoint(
                uuid.uuid4(), {"status": "ISSUED"}, auth=_auth()
            )
        assert exc.value.status_code == 409

        async def fake_list(org_id, *, limit=500):
            return [{"id": "9", "return_number": "DN-000009", "status": "OPEN",
                     "supplier_id": "s1", "reason": "defective"}]

        async def fake_fetch_many(table, **kw):
            return [{"id": "s1", "name": "ABC Computers"}]

        monkeypatch.setattr(pr_repo, "list_purchase_returns", fake_list)
        monkeypatch.setattr(main_mod, "fetch_many", fake_fetch_many)
        out = await main_mod.list_debit_notes_endpoint(
            query="", status="ALL", auth=_auth()
        )
        assert out["count"] == 1
        assert out["items"][0]["supplier_name"] == "ABC Computers"


class TestQuestionnaireInstructions:
    """360° questionnaire: numbered multi-fact question + per-line chips."""

    def test_clean_question_preserves_options_per_part(self):
        from app.accounting_reasoning import _clean_question

        cleaned = _clean_question(
            {
                "text": "intro\n1. Which treatment?\n2. What date?",
                "options_per_part": [
                    ["capitalize", "expense"],
                    "TODAY",
                    42,          # junk dropped
                    [],          # empty kept (index alignment)
                ],
                "options": ["x", "y"],
            }
        )
        assert cleaned["options_per_part"] == [
            ["capitalize", "expense"],
            ["TODAY"],
            [],
        ]
        assert cleaned["options"] == ["x", "y"]

    def test_plain_string_question_still_works(self):
        from app.accounting_reasoning import _clean_question

        cleaned = _clean_question("Which treatment applies?")
        assert cleaned is not None
        assert cleaned["text"] == "Which treatment applies?"
        assert cleaned["options_per_part"] == []

    def test_reasoning_source_pins_the_instructions(self):
        from pathlib import Path

        import app.accounting_reasoning as ar

        src = Path(ar.__file__).read_text(encoding="utf-8")
        assert "CONSOLIDATED QUESTIONNAIRE" in src
        assert "options_per_part" in src
        assert "CHART-OF-ACCOUNTS GRANULARITY" in src
        assert "CREDIT / DEBIT NOTES" in src
        # the agent maps options_per_part onto AgentResponse.question_options
        import app.agent as agent_mod

        agent_src = Path(agent_mod.__file__).read_text(encoding="utf-8")
        assert "options_per_part" in agent_src


class TestCategoryGranularity:
    """Items never become accounts — categories do."""

    @pytest.mark.parametrize(
        ("item", "category"),
        [
            ("2 office chairs", "Furniture & Fixtures"),
            ("sofa set for the lobby", "Furniture & Fixtures"),
            ("bed for the guest room", "Furniture & Fixtures"),
            ("wall fittings", "Fixtures & Fittings"),
            ("false ceiling fittings", "Fixtures & Fittings"),
            ("dell laptop for admin", "Computer Equipment"),
            ("delivery bike", "Vehicles"),
            ("solar panels", "Plant & Machinery"),
            ("", "Other Equipment & Fixtures"),
            ("something entirely new", "Other Equipment & Fixtures"),
        ],
    )
    def test_category_for_item(self, item, category):
        from app.account_resolution import category_for_item

        assert category_for_item(item) == category

    @pytest.mark.asyncio
    async def test_asset_gap_proposes_the_category_not_the_item(
        self, monkeypatch
    ):
        from app import account_resolution as ar
        from app.repositories import account_repository as a_repo
        from app.services import fixed_asset_service

        async def _no_account(*a, **k):
            return None

        async def _no_chart(*a, **k):
            return []

        monkeypatch.setattr(fixed_asset_service, "_resolve_gl_account", _no_account)
        monkeypatch.setattr(a_repo, "get_chart_of_accounts", _no_chart)
        gap = await ar.fixed_asset_account_gap(
            ORG, entities={"item_description": "2 office chairs"}
        )
        assert gap is not None
        assert gap.name == "Furniture & Fixtures"
        assert gap.account_type == "ASSET"

    @pytest.mark.asyncio
    async def test_heading_account_id_finds_the_ppe_parent(self, monkeypatch):
        from app.repositories import account_repository as a_repo

        ppe = str(uuid.uuid4())
        other = str(uuid.uuid4())

        async def fake_chart(org_id, *, limit=500):
            return [
                {"id": ppe, "name": "Property, Plant & Equipment"},
                {"id": other, "name": "Ungrouped Asset"},
            ]

        async def fake_grouping(org_id):
            return {ppe}  # only the heading has children

        monkeypatch.setattr(a_repo, "get_chart_of_accounts", fake_chart)
        monkeypatch.setattr(a_repo, "get_grouping_account_ids", fake_grouping)

        assert await heading_account_id(ORG, nature="ASSET") == ppe
        # non-asset natures never look for a parent
        assert await heading_account_id(ORG, nature="EXPENSE") is None

    @pytest.mark.asyncio
    async def test_heading_account_id_none_without_heading(self, monkeypatch):
        from app.repositories import account_repository as a_repo

        async def fake_chart(org_id, *, limit=500):
            return [{"id": str(uuid.uuid4()), "name": "Cash"}]

        async def fake_grouping(org_id):
            return set()

        monkeypatch.setattr(a_repo, "get_chart_of_accounts", fake_chart)
        monkeypatch.setattr(a_repo, "get_grouping_account_ids", fake_grouping)
        assert await heading_account_id(ORG, nature="ASSET") is None





