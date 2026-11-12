import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.planner import plan
from app.reasoning import analyze_requirements
from app.services import fixed_asset_service
from app.tool_router import get_gemini_tool_definitions
from app.tools import _TOOL_REGISTRY, derive_live_parameter_schema, list_tools


class TestListAndEntityResumeRegression:
    def test_plan_resume_with_list_line_items_and_bank_settlement(self):
        hist = [
            {
                "field": "transaction_nature",
                "question": "What are these 2 laptops for?",
                "answer": "ASSET",
                "required_information": ["transaction_nature"],
            },
            {
                "field": "payment_method",
                "question": "How are the 2 laptops being settled — by bank transfer, cash, or on credit from the supplier?",
                "answer": "BANK",
                "required_information": ["payment_method"],
            },
            {
                "field": "line_items",
                "question": "line_items",
                "answer": [{"description": "laptops", "quantity": 2, "unit_price": 75000, "amount": 150000}],
            },
            {
                "field": "transaction_date",
                "question": "What is the transaction date?",
                "answer": "2026-11-10",
            },
            {
                "field": "depreciation_method",
                "question": "Which depreciation method should I use?",
                "answer": "NONE",
            },
        ]
        result = plan("record a purchase of 2 laptops", clarification_history=hist)
        ee = result.extracted_entities or {}

        assert result.intent == "register_fixed_asset"
        assert result.transaction_nature == "FIXED_ASSET"
        assert ee.get("supplier_name") is None
        assert ee.get("item_description") == "laptops"
        assert ee.get("asset_name") == "laptops"
        assert ee.get("item_quantity") == 2.0
        assert ee.get("amount") == 150000.0
        assert ee.get("payment_method") == "BANK_TRANSFER"
        assert result.requires_clarification is False

        nodes = analyze_requirements(
            intent=result.intent,
            entities=ee,
            missing_fields=result.missing_fields,
        )
        unresolved = [n for n in nodes if str(n.state.value if hasattr(n.state, "value") else n.state) == "MISSING_AND_REQUIRED"]
        assert unresolved == []

    def test_plan_resume_with_stringified_line_items_purchased_for_employees(self):
        hist = [
            {
                "field": "line_items",
                "question": "Please provide item details",
                "answer": json.dumps([{"description": "laptops", "quantity": 2, "unit_price": 80000}]),
            },
            {
                "field": "transaction_nature",
                "question": "Is this a fixed asset or expense?",
                "answer": "ASSET",
            },
            {
                "field": "payment_method",
                "question": "How was this paid?",
                "answer": "BANK",
            },
            {
                "field": "transaction_date",
                "question": "What is the transaction date?",
                "answer": "2026-11-10",
            },
            {
                "field": "depreciation_method",
                "question": "Depreciation method?",
                "answer": "NONE",
            },
        ]
        result = plan("purchased 2 laptops for office employees", clarification_history=hist)
        ee = result.extracted_entities or {}

        assert result.intent == "register_fixed_asset"
        assert ee.get("supplier_name") is None
        assert ee.get("item_description") == "laptops"
        assert ee.get("asset_name") == "laptops"
        assert ee.get("item_quantity") == 2.0
        assert ee.get("amount") == 160000.0
        assert result.requires_clarification is False

    def test_sale_family_guard_still_blocks_inventory(self):
        hist = [
            {
                "field": "transaction_nature",
                "question": "What are you selling?",
                "answer": "INVENTORY",
            }
        ]
        result = plan("sold 2 laptops for 200000 cash today", clarification_history=hist)
        assert result.transaction_nature != "INVENTORY"


class TestFreshOrgBankPrerequisiteResolution:
    @pytest.mark.asyncio
    async def test_fixed_asset_resolve_payment_account_bootstraps_bank_on_fresh_org(self, monkeypatch):
        org_id = uuid.uuid4()
        gl_id = uuid.uuid4()
        fake_gl = {"id": str(gl_id), "name": "Bank", "code": "1010", "account_type": "ASSET"}

        from app.repositories import organization_repository
        import app.accounting_engine as ae

        monkeypatch.setattr(organization_repository, "get_bank_accounts", AsyncMock(return_value=[]))
        ensure_mock = AsyncMock(return_value={"id": str(uuid.uuid4()), "gl_account_id": str(gl_id)})
        monkeypatch.setattr(ae, "ensure_bank_account", ensure_mock)
        monkeypatch.setattr(fixed_asset_service.account_repo, "get_account", AsyncMock(return_value=fake_gl))

        resolved = await fixed_asset_service._resolve_settlement_account(
            org_id, payment_method="BANK_TRANSFER"
        )
        assert resolved == fake_gl
        ensure_mock.assert_awaited_once_with(org_id)


class TestLiveToolSchemaAndDiscovery:
    def test_derive_live_parameter_schema_inspects_handlers_and_contracts(self):
        po_schema = derive_live_parameter_schema("create_purchase_order")
        assert "supplier_name" in po_schema["properties"]
        assert "items" in po_schema["properties"]

        status_schema = derive_live_parameter_schema("update_document_status")
        for req_key in ("document_type", "document_reference", "target_status"):
            assert req_key in status_schema["properties"]

        rec_schema = derive_live_parameter_schema("create_recurring_template")
        for key in ("source_type", "frequency", "name", "auto_post"):
            assert key in rec_schema["properties"]

    @pytest.mark.asyncio
    async def test_discover_erp_capabilities_plural_query(self):
        handler = _TOOL_REGISTRY["discover_erp_capabilities"]["handler"]
        res = await handler(uuid.uuid4(), section="purchases")
        assert res.success is True
        slugs = [t["slug"] for t in res.data["tools"]]
        assert "create_purchase_bill" in slugs
        assert "create_purchase_order" in slugs
        assert "purchases" in res.data["modules"]
        assert any("/api/purchases/" in r["path"] for r in res.data["http_routes"])

    @pytest.mark.asyncio
    async def test_get_gemini_tool_definitions_merges_live_code_when_db_stale_or_partial(self, monkeypatch):
        async def _fake_fetch_many(table_name, **_kwargs):
            if table_name == "ai_tools":
                return [
                    {"id": "t1", "slug": "create_invoice"},
                    {"id": "t2", "slug": "create_purchase_order"},
                ]
            return []

        class _FakeResult:
            def __init__(self, data):
                self.data = data

        class _FakeQuery:
            def select(self, *_args, **_kwargs):
                return self

            def in_(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def execute(self):
                return _FakeResult([
                    {
                        "tool_id": "t1",
                        "parameter_name": "stale_db_only_field",
                        "data_type": "string",
                        "required": False,
                        "description": "Stale DB field",
                        "position": 1,
                    }
                ])

        class _FakeSchema:
            def table(self, _name):
                return _FakeQuery()

        class _FakeClient:
            def schema(self, _name):
                return _FakeSchema()

        async def _fake_execute(query):
            return query.execute()

        import app.database as db_mod
        import app.tool_router as tr
        monkeypatch.setattr(tr, "fetch_many", _fake_fetch_many)
        monkeypatch.setattr(db_mod, "get_service_client", lambda: _FakeClient())
        monkeypatch.setattr(db_mod, "_execute", _fake_execute)
        monkeypatch.setattr(tr, "_TOOL_DEFS_CACHE", None)

        defs = await get_gemini_tool_definitions()
        by_name = {fn["name"]: fn for d in defs for fn in (d.get("functionDeclarations") or [d])}

        # Even though mock DB only returned 2 rows, ALL code-registered tools appear.
        assert set(by_name.keys()) >= set(list_tools())
        assert "discover_erp_capabilities" in by_name

        # Strict contract on create_invoice drops stale DB param and exposes live contract params.
        inv_props = by_name["create_invoice"]["parameters"]["properties"]
        assert "stale_db_only_field" not in inv_props
        assert "invoice_date" in inv_props
        assert "customer_name" in inv_props
        assert "items" in inv_props

        # Empty-DB tool create_purchase_order exposes live handler parameters.
        po_props = by_name["create_purchase_order"]["parameters"]["properties"]
        assert "supplier_name" in po_props
        assert "items" in po_props
