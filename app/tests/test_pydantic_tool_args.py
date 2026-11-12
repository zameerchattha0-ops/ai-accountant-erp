"""Tests for Pydantic tool Args models, schema auto-generation, and 2-tier dynamic tool loading."""

from __future__ import annotations

import uuid
import pytest
from pydantic import BaseModel

import app.tool_router as tr
import app.tools as tools_mod
from app.erp_endpoints import ERP_MODULES
from app.models.schemas import ToolResult
from app.qwen_client import QwenClient
from app.tool_router import (
    TIER_1_TOOLS,
    _pydantic_schema_to_gemini_parameters,
    get_gemini_tool_definitions,
    get_section_tools,
    invalidate_tool_definition_cache,
)
from app.tools import _TOOL_REGISTRY, list_tools


@pytest.fixture(autouse=True)
def _isolate_tool_registry_from_leaked_test_tools(monkeypatch):
    """Ensure test-only tools leaked by earlier test modules do not pollute registry checks."""
    invalidate_tool_definition_cache()
    for slug in list(_TOOL_REGISTRY.keys()):
        if slug.startswith("test_"):
            monkeypatch.delitem(_TOOL_REGISTRY, slug, raising=False)
    yield
    invalidate_tool_definition_cache()


def _expected_flat_type(prop_schema: dict, defs: dict) -> str:
    if "$ref" in prop_schema:
        ref_name = prop_schema["$ref"].rsplit("/", 1)[-1]
        prop_schema = defs.get(ref_name, {})
    for union_key in ("anyOf", "oneOf"):
        if union_key in prop_schema:
            non_null = [
                sub for sub in prop_schema[union_key]
                if not (isinstance(sub, dict) and sub.get("type") == "null")
            ]
            if non_null:
                return _expected_flat_type(non_null[0], defs)
    t = prop_schema.get("type", "string")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    return t


class TestPydanticToolArgsModels:
    def test_all_registered_handlers_have_args_model(self):
        slugs = list_tools()
        assert len(slugs) >= 89
        missing = []
        for slug in slugs:
            entry = _TOOL_REGISTRY[slug]
            handler = entry["handler"]
            args_model = getattr(handler, "_args_model", None)
            if args_model is None or not (
                isinstance(args_model, type) and issubclass(args_model, BaseModel)
            ):
                missing.append(slug)
        assert missing == [], f"Handlers missing Pydantic _args_model: {missing}"

    def test_every_args_model_produces_valid_json_schema(self):
        for slug in list_tools():
            handler = _TOOL_REGISTRY[slug]["handler"]
            args_model = handler._args_model
            schema = args_model.model_json_schema()
            assert isinstance(schema, dict), f"{slug}: schema must be dict"
            assert schema.get("type") == "object", f"{slug}: root schema type must be object"
            assert isinstance(schema.get("properties"), dict), f"{slug}: properties must be dict"

    @pytest.mark.asyncio
    async def test_gemini_tool_definitions_match_pydantic_schemas(self, monkeypatch):
        invalidate_tool_definition_cache()

        async def _should_not_hit_db(*_args, **_kwargs):
            raise AssertionError("DB should not be queried when all handlers use _args_model")

        monkeypatch.setattr(tr, "fetch_many", _should_not_hit_db)

        defs = await get_gemini_tool_definitions()
        by_name = {d["name"]: d for d in defs}
        assert set(by_name.keys()) == set(list_tools())

        for slug in list_tools():
            handler = _TOOL_REGISTRY[slug]["handler"]
            raw_schema = handler._args_model.model_json_schema()
            raw_defs = raw_schema.get("$defs") or {}
            raw_props = raw_schema.get("properties") or {}
            raw_required = [
                r for r in (raw_schema.get("required") or [])
                if r not in ("organization_id", "created_by", "ai_execution_id")
            ]

            decl = by_name[slug]
            assert decl["name"] == slug
            assert decl["description"]

            if not raw_props:
                assert "parameters" not in decl, (
                    f"{slug}: parameter-less tool must omit 'parameters' for Gemini"
                )
            else:
                params = decl.get("parameters")
                assert isinstance(params, dict), f"{slug}: missing parameters"
                assert params["type"] == "object"
                assert set(params["properties"].keys()) == set(raw_props.keys())
                assert params["required"] == raw_required
                for pname, pschema in raw_props.items():
                    expected_type = _expected_flat_type(pschema, raw_defs)
                    assert params["properties"][pname]["type"] == expected_type, (
                        f"{slug}.{pname}: expected type {expected_type}, "
                        f"got {params['properties'][pname]['type']}"
                    )

    @pytest.mark.asyncio
    async def test_client_converters_accept_pydantic_tool_definitions(self):
        invalidate_tool_definition_cache()
        defs = await get_gemini_tool_definitions()
        openai_tools = QwenClient._to_openai_tools(defs)
        assert len(openai_tools) == len(defs)
        for t in openai_tools:
            assert t["type"] == "function"
            assert t["function"]["name"]
            assert t["function"]["parameters"]["type"] == "object"

        # Verify Gemini schema helper produces Gemini-safe types (no anyOf/$defs)
        for slug in ("create_invoice", "record_cash_sale", "create_purchase_bill", "run_payroll"):
            handler = _TOOL_REGISTRY[slug]["handler"]
            params = _pydantic_schema_to_gemini_parameters(handler._args_model)
            assert params is not None
            assert "$defs" not in params
            for pval in params["properties"].values():
                assert "anyOf" not in pval
                assert pval["type"] in ("string", "number", "integer", "boolean", "array", "object")

    @pytest.mark.asyncio
    async def test_fallback_to_db_and_ast_for_handler_without_args_model(self, monkeypatch):
        invalidate_tool_definition_cache()
        dummy_slug = "_test_legacy_no_args_model_tool"

        async def _legacy_handler(organization_id: uuid.UUID, **kw) -> ToolResult:
            val = kw.get("legacy_note")
            return ToolResult(tool_name=dummy_slug, success=True, data={"val": val})

        monkeypatch.setitem(
            _TOOL_REGISTRY,
            dummy_slug,
            {
                "handler": _legacy_handler,
                "read_only": True,
                "description": "Legacy test tool",
                "contract": None,
                "live_target": None,
                "args_model": None,
            },
        )

        async def _fake_fetch_many(table_name, **_kwargs):
            if table_name == "ai_tools":
                return [{"id": "legacy-1", "slug": dummy_slug}]
            return []

        class _FakeResult:
            data = [
                {
                    "tool_id": "legacy-1",
                    "parameter_name": "db_only_param",
                    "description": "From DB",
                    "data_type": "string",
                    "required": False,
                    "position": 1,
                }
            ]

        class _FakeQuery:
            def select(self, *_a, **_kw):
                return self

            def in_(self, *_a, **_kw):
                return self

            def limit(self, *_a, **_kw):
                return self

            def execute(self):
                return _FakeResult()

        class _FakeSchema:
            def table(self, _n):
                return _FakeQuery()

        class _FakeClient:
            def schema(self, _n):
                return _FakeSchema()

        async def _fake_execute(q):
            return q.execute()

        import app.database as db_mod

        monkeypatch.setattr(tr, "fetch_many", _fake_fetch_many)
        monkeypatch.setattr(db_mod, "get_service_client", lambda: _FakeClient())
        monkeypatch.setattr(db_mod, "_execute", _fake_execute)

        defs = await get_gemini_tool_definitions()
        by_name = {d["name"]: d for d in defs}
        assert dummy_slug in by_name
        props = by_name[dummy_slug]["parameters"]["properties"]
        assert "db_only_param" in props
        assert "legacy_note" in props
        invalidate_tool_definition_cache()


class TestTwoTierDynamicToolLoading:
    @pytest.mark.asyncio
    async def test_tier1_tools_always_present(self):
        invalidate_tool_definition_cache()
        assert len(TIER_1_TOOLS) >= 10
        assert TIER_1_TOOLS.issubset(set(list_tools()))

        for sec in (None, "tier1", "purchases", "sales", "fixed_assets", "payroll", "tax", "banking"):
            defs = await get_gemini_tool_definitions(section=sec)
            names = {d["name"] for d in defs}
            missing = TIER_1_TOOLS - names
            assert not missing, f"section={sec!r} missing Tier 1 tools: {missing}"

    @pytest.mark.asyncio
    async def test_tier1_only_excludes_tier2_write_tools(self):
        invalidate_tool_definition_cache()
        defs = await get_gemini_tool_definitions(section="tier1")
        names = {d["name"] for d in defs}
        assert names == TIER_1_TOOLS
        for write_tool in ("create_invoice", "create_purchase_bill", "register_fixed_asset", "run_payroll"):
            assert write_tool not in names

    @pytest.mark.asyncio
    async def test_tier2_tools_loaded_only_for_requested_section(self):
        invalidate_tool_definition_cache()

        purchases_defs = await get_gemini_tool_definitions(section="purchases")
        purchases_names = {d["name"] for d in purchases_defs}
        assert {"create_purchase_bill", "record_cash_purchase", "create_purchase_return", "record_supplier_payment", "create_purchase_order"}.issubset(purchases_names)
        assert "create_invoice" not in purchases_names
        assert "register_fixed_asset" not in purchases_names
        assert "run_payroll" not in purchases_names

        sales_defs = await get_gemini_tool_definitions(section="sales")
        sales_names = {d["name"] for d in sales_defs}
        assert {"create_invoice", "record_cash_sale", "create_quotation", "convert_quotation", "create_credit_note", "record_customer_receipt"}.issubset(sales_names)
        assert "create_purchase_bill" not in sales_names
        assert "register_fixed_asset" not in sales_names
        assert "run_payroll" not in sales_names

        fa_defs = await get_gemini_tool_definitions(section="fixed_assets")
        fa_names = {d["name"] for d in fa_defs}
        assert {"register_fixed_asset", "dispose_fixed_asset", "record_asset_depreciation"}.issubset(fa_names)
        assert "create_invoice" not in fa_names
        assert "create_purchase_bill" not in fa_names

        payroll_defs = await get_gemini_tool_definitions(section="payroll")
        payroll_names = {d["name"] for d in payroll_defs}
        assert {"run_payroll", "pay_employee_salary", "create_employee", "set_employee_allowances"}.issubset(payroll_names)
        assert "create_invoice" not in payroll_names
        assert "create_purchase_bill" not in payroll_names

        tax_defs = await get_gemini_tool_definitions(section="tax")
        tax_names = {d["name"] for d in tax_defs}
        assert {"get_organization_tax_profile", "set_organization_tax_profile"}.issubset(tax_names)
        assert "run_payroll" not in tax_names
        assert "register_fixed_asset" not in tax_names

    def test_all_erp_modules_map_to_registered_tools(self):
        registered = set(list_tools())
        for mod_key in ERP_MODULES:
            sec_tools = get_section_tools(mod_key)
            assert sec_tools, f"ERP_MODULES[{mod_key!r}] mapped to empty tool set"
            assert sec_tools.issubset(registered), (
                f"ERP_MODULES[{mod_key!r}] mapped unknown tools: {sec_tools - registered}"
            )
