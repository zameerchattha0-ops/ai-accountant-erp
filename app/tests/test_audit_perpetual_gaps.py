"""Audit findings → fixes: perpetual-inventory end-to-end gaps.

Three silent-failure gaps found during the requirements audit, each with
its regression pin:

1. NATURE RECOVERY — the purchase handler only ran catalogue sync / the
   Dr-Inventory journal / the stock receipt when the CALLER passed
   transaction_nature='INVENTORY'.  The deterministic fast path never does,
   and a minimal model reply may forget — so resale purchases posted to the
   expense default (P&L polluted).  Fixed: deterministic derivation from
   the bill's OWN data (stock-tracked product flag, else the intent
   family's wording rules — planner parity).

2. SALE-SIDE PRODUCT LINK — the COGS trigger only values lines carrying
   product_id, but no sale path attached it (fast path passed no items at
   all; invoice lines were text-only) — revenue posted with NO cost.
   Fixed: EXACT catalogue-name linking in both sale handlers + items on
   the cash-sale fast path.

3. ROUTING PIN — an INVENTORY-natured purchase must never re-route to
   register_fixed_asset (the planner only re-routes FIXED_ASSET nature).

No live DB, no live provider — repository/service seams are monkeypatched.
"""

from __future__ import annotations

import asyncio
import uuid

from app.agent import _cash_sale_fast_path_call
from app.planner import plan
from app.tools import (
    _create_purchase_bill,
    _derive_purchase_nature,
    _link_products_to_items,
)

_ORG = uuid.UUID("00000000-0000-0000-0000-00000000a0d1")


# ------------------------------------------------- 1. nature recovery

def _derive(kw, *, product=None):
    async def _get(organization_id, *, product_id):
        return product

    from unittest.mock import patch
    from app.services import product_service as ps
    with patch.object(ps, "get", _get):
        return asyncio.run(_derive_purchase_nature(_ORG, dict(kw)))


def test_resale_wording_recovers_inventory_nature():
    assert _derive({"notes": "We buy two bikes for resale on cash"}) == "INVENTORY"
    assert _derive({"items": [{"description": "sugar for stock",
                               "quantity": 5, "unit_price": 100}]}) == "INVENTORY"


def test_stock_tracked_product_link_is_authoritative():
    assert _derive(
        {"items": [{"description": "anything", "product_id": str(uuid.uuid4())}]},
        product={"id": "p1", "is_stock_tracked": True},
    ) == "INVENTORY"


def test_no_signal_and_non_resale_wording_derive_nothing():
    assert _derive({}) == ""
    assert _derive({"notes": "Office chairs for the conference room"}) == ""
    # a linked product that is NOT stock-tracked is not inventory
    assert _derive(
        {"items": [{"description": "consulting", "product_id": str(uuid.uuid4())}]},
        product={"id": "p1", "is_stock_tracked": False},
    ) == ""


def test_purchase_handler_recovers_nature_and_syncs_catalogue(monkeypatch):
    """THE keystone integration: a bill with NO transaction_nature but
    resale wording must still (a) hand transaction_nature=INVENTORY to the
    engine, (b) run the catalogue sync, (c) link the line to the product."""
    import app.tools as tools_mod

    captured = {}
    created = {"n": 0}

    async def _create_bill(organization_id, **kw):
        return {
            "id": str(uuid.uuid4()),
            "bill_date": "2026-10-10",
            "bill_number": "PB-1",
            "total": 1000.0,
            "items": kw.get("items") or [],
        }

    async def _sync(organization_id, *, name, quantity, unit_cost):
        created["n"] += 1
        return {"id": str(uuid.uuid4()), "name": name,
                "product_code": f"SKU-{created['n']}", "reused": False}

    async def _auto_journal(**kw):
        captured.update(kw)
        return {"journal_warning": None}  # no entry id -> no post/receipt

    monkeypatch.setattr(tools_mod.purchase_service, "create_purchase_bill", _create_bill)
    monkeypatch.setattr(tools_mod.inventory_service,
                        "find_or_create_catalogue_product", _sync)
    monkeypatch.setattr(tools_mod, "auto_journal", _auto_journal)
    # NEW SEAM (posting-boundary invariant, 2026-10-18): the handler now
    # resolves the Inventory valuation ledger BEFORE any bill/journal write —
    # stub the read-only resolution so the test never touches the DB.
    import app.accounting_engine as engine_mod

    async def _inventory_ledger(organization_id, *, hint_account=None):
        return {"id": str(uuid.uuid4()), "name": "Inventory",
                "account_type": "ASSET"}

    monkeypatch.setattr(
        engine_mod, "resolve_inventory_account", _inventory_ledger
    )

    result = asyncio.run(_create_purchase_bill(
        _ORG,
        supplier_id=str(uuid.uuid4()),
        bill_date="2026-10-10",
        total=1000.0,
        items=[{"description": "bikes", "quantity": 2, "unit_price": 500.0}],
        notes="bikes for resale",
    ))
    assert result.success is True
    assert captured.get("transaction_nature") == "INVENTORY"  # (a)
    assert created["n"] == 1                                     # (b)
    assert result.data.get("catalogue_notes")                    # (c)
    assert result.data["items"][0].get("product_id")


# ------------------------------------------------- 2. sale product link

def test_exact_name_match_attaches_product_id(monkeypatch):
    async def _search(organization_id, *, query, limit=25):
        return [
            {"id": str(uuid.uuid4()), "name": "Bikes"},       # wrong case
            {"id": str(uuid.uuid4()), "name": "Bike Stand"},
        ]

    monkeypatch.setattr("app.tools.product_service.search", _search)
    items = [{"description": "bikes", "quantity": 2, "unit_price": 30000.0}]
    asyncio.run(_link_products_to_items(_ORG, items))
    assert items[0].get("product_id")  # case-insensitive EXACT match linked


def test_no_match_leaves_the_line_unlinked(monkeypatch):
    async def _search(organization_id, *, query, limit=25):
        return [{"id": str(uuid.uuid4()), "name": "Something Else"}]

    monkeypatch.setattr("app.tools.product_service.search", _search)
    items = [{"description": "unheard of item"}]
    asyncio.run(_link_products_to_items(_ORG, items))
    assert not items[0].get("product_id")  # never guess a product


def test_existing_product_id_is_never_overwritten(monkeypatch):
    async def _search(organization_id, *, query, limit=25):
        raise AssertionError("must not search when already linked")

    monkeypatch.setattr("app.tools.product_service.search", _search)
    keep = str(uuid.uuid4())
    items = [{"description": "bikes", "product_id": keep}]
    asyncio.run(_link_products_to_items(_ORG, items))
    assert items[0]["product_id"] == keep


# --- LLM CATALOGUE ANALYST (2026-10-20, per-item decrement fix) -------------
def test_llm_analyst_links_a_differently_worded_sale(monkeypatch):
    """A sale worded differently than the catalogue ('office chairs' vs the
    stock-tracked product 'chair') is linked by the LLM analyst (semantic
    'same product' judgment), so stock is decremented for THAT item."""
    from app.config import get_settings

    get_settings().llm_catalogue_match_enabled = True
    chair_id = str(uuid.uuid4())

    class _StubClient:
        async def generate_text_light(self, prompt):
            # two tracked candidates -> 'chair' is index 1
            return '{"match_index": 1, "reason": "same product"}'

    import app.ai_orchestrator as orch
    monkeypatch.setattr(orch, "get_client", lambda: _StubClient())

    async def _search(organization_id, *, query, limit=25):
        return [
            {"id": chair_id, "name": "chair", "is_stock_tracked": True},
            {"id": str(uuid.uuid4()), "name": "Office Desk",
             "is_stock_tracked": True},
        ]

    monkeypatch.setattr("app.tools.product_service.search", _search)
    items = [{"description": "office chairs", "quantity": 2}]
    asyncio.run(_link_products_to_items(_ORG, items))
    assert items[0].get("product_id") == chair_id  # analyst linked


def test_word_fallback_never_links_a_non_stock_product(monkeypatch):
    """The fallback only considers STOCK-TRACKED products — a service/non-stock
    line must never link (and therefore never issue stock)."""
    async def _search(organization_id, *, query, limit=25):
        return [{"id": str(uuid.uuid4()), "name": "chair",
                 "is_stock_tracked": False}]

    monkeypatch.setattr("app.tools.product_service.search", _search)
    items = [{"description": "office chairs", "quantity": 1}]
    asyncio.run(_link_products_to_items(_ORG, items))
    assert not items[0].get("product_id")  # non-stock -> never linked


def test_word_fallback_does_not_cross_distinct_items(monkeypatch):
    """'Honda bike' must not link to a different tracked product that merely
    shares the generic word 'bike' (subset gate blocks the cross)."""
    async def _search(organization_id, *, query, limit=25):
        return [{"id": str(uuid.uuid4()), "name": "Yamaha bike",
                 "is_stock_tracked": True}]

    monkeypatch.setattr("app.tools.product_service.search", _search)
    items = [{"description": "Honda bike", "quantity": 1}]
    asyncio.run(_link_products_to_items(_ORG, items))
    assert not items[0].get("product_id")  # distinct -> never linked


def test_cash_sale_fast_path_now_carries_items():
    """The COGS trigger is only reachable when the call carries items."""
    calls = _cash_sale_fast_path_call({
        "amount": 60000.0,
        "transaction_date": "2026-10-10",
        "transaction_nature": "GOODS",
        "item_description": "bikes",
        "quantity": 2,
    })
    assert calls is not None
    (call,) = calls
    assert call.tool_name == "record_cash_sale"
    items = call.arguments["items"]
    assert len(items) == 1
    assert items[0]["description"] == "bikes"
    assert items[0]["quantity"] == 2.0
    # unit price reconciles with the stated total — never invented
    assert round(items[0]["quantity"] * items[0]["unit_price"], 2) == 60000.0


def test_cash_sale_fast_path_prefers_parsed_lines_that_reconcile():
    calls = _cash_sale_fast_path_call({
        "amount": 9000.0,
        "transaction_date": "2026-10-10",
        "transaction_nature": "GOODS",
        "line_items": [
            {"description": "bikes", "quantity": 2, "unit_price": 3000.0},
            {"description": "helmets", "quantity": 3, "unit_price": 1000.0},
        ],
    })
    (call,) = calls
    assert [i["description"] for i in call.arguments["items"]] == [
        "bikes", "helmets",
    ]


# ------------------------------------------------- 3. routing pin

def test_resale_purchase_never_routes_to_fixed_asset():
    """The audit's original requirement: an INVENTORY-natured purchase must
    stay in the purchase family — the planner only re-routes FIXED_ASSET."""
    p = plan("we buy two bikes for resale on cash today")
    assert p.intent == "record_cash_purchase"
    assert p.intent != "register_fixed_asset"
    # and the deterministic natures agree the goods are FOR RESALE
    assert str(p.extracted_entities.get("transaction_nature") or "").upper() != "FIXED_ASSET"


# ------------------------------------------------- 4. inventory missing-head self-heal
# (mirror of the CoS ensure pins in test_cogs_missing_head_and_guard: a
#  stock purchase may not be refused because the chart lacks an Inventory
#  ledger — the engine CREATES the standard head itself.)

def _patch_empty_chart(monkeypatch):
    from app.repositories import account_repository as a_repo

    async def _no_groups(_org):
        return set()

    async def _no_rows(*_args, **_kwargs):
        return []

    monkeypatch.setattr(a_repo, "get_grouping_account_ids", _no_groups)
    monkeypatch.setattr(a_repo, "search_accounts", _no_rows)


def test_ensure_inventory_creates_top_level_asset_when_chart_lacks_it(monkeypatch):
    from app import accounting_engine
    from app.repositories import account_repository as a_repo

    _patch_empty_chart(monkeypatch)
    created_args = {}

    async def _next_code(_org, requested, **_kw):
        return requested

    async def _create(*, organization_id, code, name, account_type,
                      normal_balance, parent_account_id, description):
        created_args.update(code=code, name=name, account_type=account_type,
                            normal_balance=normal_balance,
                            parent_account_id=parent_account_id)
        return {"id": str(uuid.uuid4()), "code": code, "name": name,
                "account_type": account_type}

    monkeypatch.setattr(a_repo, "next_available_code", _next_code)
    monkeypatch.setattr(a_repo, "create_account", _create)

    row = asyncio.run(accounting_engine.ensure_inventory_account(_ORG))
    assert row and row["name"] == "Inventory"
    assert created_args["account_type"] == "ASSET"
    assert created_args["normal_balance"] == "DEBIT"
    # a parent is NEVER invented — the new standard head is top-level
    assert created_args["parent_account_id"] is None


def test_ensure_inventory_returns_existing_ledger_without_creating(monkeypatch):
    """Resolve wins: an existing Inventory-named postable ASSET is returned
    as-is and create_account must never be called."""
    from app import accounting_engine
    from app.repositories import account_repository as a_repo

    existing = {"id": str(uuid.uuid4()), "code": "1200", "name": "Inventory",
                "account_type": "ASSET", "is_active": True}

    async def _no_groups(_org):
        return set()

    async def _search(_org, *, query, limit=10):
        return [existing] if query == "Inventory" else []

    async def _boom(*_a, **_k):
        raise AssertionError("create_account must not run when resolve succeeds")

    monkeypatch.setattr(a_repo, "get_grouping_account_ids", _no_groups)
    monkeypatch.setattr(a_repo, "search_accounts", _search)
    monkeypatch.setattr(a_repo, "create_account", _boom)

    row = asyncio.run(accounting_engine.ensure_inventory_account(_ORG))
    assert row == existing


def test_ensure_inventory_returns_none_when_create_fails(monkeypatch):
    """Honest None (the caller keeps its warning) — never a fabricated row."""
    from app import accounting_engine
    from app.repositories import account_repository as a_repo

    _patch_empty_chart(monkeypatch)

    async def _next_code(_org, requested, **_kw):
        return requested

    async def _boom(*_a, **_k):
        raise RuntimeError("chart write refused")

    monkeypatch.setattr(a_repo, "next_available_code", _next_code)
    monkeypatch.setattr(a_repo, "create_account", _boom)

    assert asyncio.run(accounting_engine.ensure_inventory_account(_ORG)) is None
