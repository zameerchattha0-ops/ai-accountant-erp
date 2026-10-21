"""
LIVE EFFECTIVENESS BATTERY — 2026-10-20 features (multi-angle, real DB + real LLM)
==================================================================================
Drives the REAL tool handlers and the REAL stage-2 LLM extraction against the
live database (test org ...0010) and the live model chain.  Every feature
applied today is attacked from several angles with different phrasings.

  A. LLM EXTRACTION (stage 2) — party/item/quantity/reason LLM-AUTHORITATIVE,
     amount/date DETERMINISTIC-FIRST.  Angles: the two failing production
     sentences, plus paraphrases, plus a hallucinated-amount guard.
  B. CASH PURCHASE TREATMENT — direct Dr Inventory-or-expense / Cr Cash, NO
     bill row, NO payable.  Angles: inventory nature, expense nature, the
     payable-is-never-touched check, the journal anatomy.
  C. CASH ACCOUNT SELF-HEAL — ensure_cash_account creates "Cash" when the
     chart lacks one (fresh org), and reuses an existing one.
  D. UNITS TRACKING SETTLEMENT-AGNOSTIC — cash AND credit inventory purchases
     both receive units into v_product_stock.
  E. CATALOGUE UNITS COLUMN — list returns live quantity_on_hand.

Usage: venv\\Scripts\\python scripts/_live_effectiveness_battery.py
"""
from __future__ import annotations

import asyncio
import json
import random
import string
import sys
import uuid
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ERP_ROOT))

TEST_ORG_ID = "00000000-0000-4000-8000-000000000010"
ORG = uuid.UUID(TEST_ORG_ID)
SFX = "".join(random.choices(string.ascii_lowercase, k=5))

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


async def _fetch(table: str, filters: dict, limit: int = 200) -> list[dict]:
    from app.database import fetch_many
    return await fetch_many(table, filters=filters, limit=limit)


# ---------------------------------------------------------------------------
# A. LLM EXTRACTION — the two production failures + paraphrases + a guard
# ---------------------------------------------------------------------------
async def section_a_extraction() -> None:
    print("\n=== A. LLM EXTRACTION (stage 2, real model) ===", flush=True)
    from app.accounting_reasoning import preliminary_extraction
    from app.llm_extraction import enrich_preliminary

    async def extract(msg: str):
        prelim = preliminary_extraction(msg)
        merged, audit = await enrich_preliminary(
            user_message=msg, preliminary=prelim, client=None,
        )
        return merged.get("literals") or {}, audit

    # A1 — THE DEBIT-NOTE FAILURE: party swallowed into the item by the regex.
    lit, _ = await extract("purchase return to umer autos against damaged motorbikes")
    record("A1_supplier_extracted", lit.get("supplier_name") == "umer autos",
           f"supplier_name={lit.get('supplier_name')!r}")
    record("A1_item_cleaned", lit.get("item_description") == "damaged motorbikes",
           f"item={lit.get('item_description')!r}")

    # A2 — THE CREDIT-PURCHASE sentence: supplier + item + written quantity.
    lit, _ = await extract("I purchased two bikes on credit from umer autos")
    record("A2_supplier_extracted", lit.get("supplier_name") == "umer autos",
           f"supplier_name={lit.get('supplier_name')!r}")
    record("A2_item_is_bikes", (lit.get("item_description") or "").lower() == "bikes",
           f"item={lit.get('item_description')!r}")
    record("A2_quantity_two", lit.get("quantity") == 2, f"qty={lit.get('quantity')!r}")

    # A3 — paraphrase: different party + item phrasing still splits cleanly.
    lit, _ = await extract("we sent back the broken fridges to Cold Traders Ltd")
    record("A3_supplier_cold_traders", "cold traders" in (lit.get("supplier_name") or "").lower(),
           f"supplier_name={lit.get('supplier_name')!r}")

    # A4 — HALLUCINATION GUARD: a regex-found amount must SURVIVE (LLM cannot
    # overwrite amount/date). The model is told 999; the rules extracted 45000.
    prelim = preliminary_extraction("Bought 5 office chairs on credit from SHABBIR FURNITURES for 45000 today")
    from app.tests.test_inventory_purchase_treatment_20261018 import _StubClient
    stub = _StubClient(json.dumps({"amount": 999.0, "transaction_date": "1999-01-01",
                                   "item_description": "office chairs",
                                   "supplier_name": "SHABBIR FURNITURES", "quantity": 5}))
    merged, _ = await enrich_preliminary(
        user_message="Bought 5 office chairs on credit from SHABBIR FURNITURES for 45000 today",
        preliminary=prelim, client=stub,
    )
    lits = merged.get("literals") or {}
    record("A4_amount_deterministic_wins", lits.get("amount") == 45000.0,
           f"amount={lits.get('amount')!r} (LLM tried 999)")
    record("A4_date_deterministic_wins", lits.get("transaction_date") != "1999-01-01",
           f"date={lits.get('transaction_date')!r} (LLM tried 1999-01-01)")
    record("A4_item_llm_wins", lits.get("item_description") == "office chairs",
           f"item={lits.get('item_description')!r}")

# ---------------------------------------------------------------------------
# B. CASH PURCHASE TREATMENT — no bill, no payable, correct Dr/Cr
# ---------------------------------------------------------------------------
async def section_b_cash_purchase() -> None:
    print("\n=== B. CASH PURCHASE TREATMENT (real tool, live DB) ===", flush=True)
    from app.tools import get_handler
    from app.services import supplier_service

    supplier = await supplier_service.create(ORG, name=f"Batt Cash Sup {SFX}")
    cash_before = await _fetch("purchase_bills",
                               {"organization_id": TEST_ORG_ID,
                                "supplier_id": str(supplier["id"])})

    handler = get_handler("record_cash_purchase")
    record("B0_tool_registered", handler is not None)
    if not handler:
        return
    inv_item = f"Batt Gadget {SFX}"
    res = await handler["handler"](
        ORG, amount=80000.0, transaction_date="2026-10-20",
        transaction_nature="INVENTORY", description=inv_item,
        items=[{"description": inv_item, "quantity": 4, "unit_price": 20000.0}],
    )
    data = getattr(res, "data", {}) or {}
    record("B1_success", bool(getattr(res, "success", False)), str(getattr(res, "error", "") or ""))
    record("B1_journal_posted", data.get("journal_posted") is True,
           str(data.get("journal_warning") or ""))
    record("B1_debit_is_inventory", "inventor" in (data.get("debit_account") or "").lower(),
           f"debit_account={data.get('debit_account')!r}")
    record("B1_credit_is_cash", (data.get("cash_account") or "") != "",
           f"cash_account={data.get('cash_account')!r}")

    # NOTE: the handler returns prepare_journal's dict DIRECTLY (the
    # record_cash_sale convention) — the row is at data["entry"], not nested
    # under data["journal_entry"]["entry"].
    entry_row = data.get("entry") or ((data.get("journal_entry") or {}).get("entry")) or {}
    jid = entry_row.get("id")
    lines = await _fetch("journal_lines", {"entry_id": jid}) if jid else []
    accts = {}
    for l in lines:
        acc = await _fetch("accounts", {"id": str(l["account_id"])}, limit=1)
        accts[str(l["account_id"])] = acc[0] if acc else {}
    debit = [a for a in lines if float(a.get("debit") or 0) > 0]
    credit = [a for a in lines if float(a.get("credit") or 0) > 0]
    dacc = accts.get(str(debit[0]["account_id"]), {}) if debit else {}
    cacc = accts.get(str(credit[0]["account_id"]), {}) if credit else {}
    record("B2_debit_posted_to_inventory_asset",
           dacc.get("account_type") == "ASSET" and "inventor" in (dacc.get("name") or "").lower(),
           f"Dr {dacc.get('code')} {dacc.get('name')} ({dacc.get('account_type')})")
    record("B2_credit_posted_to_cash_asset",
           cacc.get("account_type") == "ASSET" and
           any(t in (cacc.get("name") or "").lower() for t in ("cash", "bank")),
           f"Cr {cacc.get('code')} {cacc.get('name')} ({cacc.get('account_type')})")
    record("B2_no_payable_line",
           not any(a.get("account_type") == "LIABILITY" for a in accts.values()),
           f"account_types={sorted({a.get('account_type') for a in accts.values()})}")

    cash_after = await _fetch("purchase_bills",
                              {"organization_id": TEST_ORG_ID,
                               "supplier_id": str(supplier["id"])})
    record("B3_no_bill_row_created", len(cash_after) == len(cash_before),
           f"bills before={len(cash_before)} after={len(cash_after)}")

    res2 = await handler["handler"](
        ORG, amount=1500.0, transaction_date="2026-10-20",
        transaction_nature="OPERATING_EXPENSE", description=f"Batt office tea {SFX}",
    )
    d2 = getattr(res2, "data", {}) or {}
    jid2 = (d2.get("entry") or ((d2.get("journal_entry") or {}).get("entry")) or {}).get("id")
    lines2 = await _fetch("journal_lines", {"entry_id": jid2}) if jid2 else []
    types2 = set()
    for l in lines2:
        acc = await _fetch("accounts", {"id": str(l["account_id"])}, limit=1)
        if acc:
            types2.add(acc[0].get("account_type"))
    record("B4_expense_nature_posts_expense_and_cash",
           bool(getattr(res2, "success", False)) and "EXPENSE" in types2 and "ASSET" in types2,
           f"line account types={sorted(types2)}")


# ---------------------------------------------------------------------------
# C. CASH ACCOUNT SELF-HEAL — create when missing, reuse when present
# ---------------------------------------------------------------------------
async def section_c_cash_selfheal() -> None:
    print("\n=== C. CASH ACCOUNT SELF-HEAL (ensure_cash_account) ===", flush=True)
    from app import accounting_engine
    from app.repositories import account_repository as a_repo

    # C1 — reuse: the test org HAS Cash, so no new account is created.
    created_names = []
    real_create = a_repo.create_account

    async def spy_create(*a, **k):
        created_names.append(k.get("name"))
        return await real_create(*a, **k)

    a_repo.create_account = spy_create
    try:
        row = await accounting_engine.ensure_cash_account(ORG)
    finally:
        a_repo.create_account = real_create
    record("C1_reuses_existing_cash", row is not None and not created_names,
           f"resolved={row.get('name') if row else None!r}, created={created_names}")

    # C2 — CREATE: a brand-new org with NO chart gets a Cash ledger created.
    fresh = uuid.uuid4()
    created = []

    async def _code(org, base, **k):
        return base

    async def _create(*a, **k):
        created.append(k.get("name"))
        return {"id": str(uuid.uuid4()), "code": k.get("code"), "name": k.get("name"),
                "account_type": k.get("account_type")}

    async def _no_resolve(org):
        return None

    real_code = a_repo.next_available_code
    real_create2 = a_repo.create_account
    real_resolve = accounting_engine._resolve_cash_account
    a_repo.next_available_code = _code
    a_repo.create_account = _create
    accounting_engine._resolve_cash_account = _no_resolve
    try:
        row2 = await accounting_engine.ensure_cash_account(fresh)
    finally:
        a_repo.next_available_code = real_code
        a_repo.create_account = real_create2
        accounting_engine._resolve_cash_account = real_resolve
    record("C2_creates_cash_when_missing",
           row2 is not None and row2.get("cash_account_created") is True
           and created == ["Cash"] and row2.get("account_type") == "ASSET",
           f"created={created}, disclosed={row2.get('cash_account_created') if row2 else None}")

# ---------------------------------------------------------------------------
# D. UNITS TRACKING SETTLEMENT-AGNOSTIC — cash AND credit both receive stock
# ---------------------------------------------------------------------------
async def section_d_units_tracking() -> None:
    print("\n=== D. UNITS TRACKING (cash AND credit receive units) ===", flush=True)
    from app.tools import get_handler
    from app.services import supplier_service, inventory_service

    handler = get_handler("record_cash_purchase")
    bill_handler = get_handler("create_purchase_bill")
    supplier = await supplier_service.create(ORG, name=f"Batt Unit Sup {SFX}")

    cash_item = f"Batt CashUnit {SFX}"
    res = await handler["handler"](
        ORG, amount=30000.0, transaction_date="2026-10-20",
        transaction_nature="INVENTORY", description=cash_item,
        items=[{"description": cash_item, "quantity": 7, "unit_price": 4000.0}],
    )
    recv = (getattr(res, "data", {}) or {}).get("stock_received") or []
    record("D1_cash_purchase_receives_units",
           bool(getattr(res, "success", False)) and any(
               float(r.get("quantity") or 0) > 0 for r in recv),
           f"stock_received={[r.get('quantity') for r in recv]}")

    credit_item = f"Batt CreditUnit {SFX}"
    res2 = await bill_handler["handler"](
        ORG, supplier_id=str(supplier["id"]), transaction_nature="INVENTORY",
        items=[{"description": credit_item, "quantity": 3, "unit_price": 5000.0}],
    )
    recv2 = (getattr(res2, "data", {}) or {}).get("stock_received") or []
    record("D2_credit_purchase_receives_units",
           bool(getattr(res2, "success", False)) and any(
               float(r.get("quantity") or 0) > 0 for r in recv2),
           f"stock_received={[r.get('quantity') for r in recv2]}")

    # D3 — verify the units landed in v_product_stock.  Use the AUTHORITATIVE
    # product_id returned in each receipt (the word-level catalogue matcher may
    # REUSE one product for all "Batt *" items, so a name->id lookup is wrong).
    for label, recv_rows, expect in (("cash", recv, 7.0), ("credit", recv2, 3.0)):
        pid = recv_rows[0].get("product_id") if recv_rows else None
        pos = await inventory_service.stock_position(
            ORG, product_id=uuid.UUID(str(pid))) if pid else None
        qty = float((pos or {}).get("quantity_on_hand") or 0)
        # >= expect because a reused shared product also holds this run's OTHER
        # receipts (4 from Section B) — what matters is these units ARE there.
        record(f"D3_{label}_units_in_stock_ledger", qty >= expect - 1e-6,
               f"product={pid} on_hand={qty} (>= {expect} from this receipt)")


# ---------------------------------------------------------------------------
# E. CATALOGUE UNITS COLUMN — list surfaces live quantity_on_hand
# ---------------------------------------------------------------------------
async def section_e_catalogue_units() -> None:
    print("\n=== E. CATALOGUE UNITS COLUMN (list returns quantity_on_hand) ===", flush=True)
    from app.services import product_service, inventory_service

    prods = await product_service.list_catalog(ORG, query="Batt", status="ALL")
    record("E0_catalogue_returns_rows", bool(prods), f"matched={len(prods)}")
    if not prods:
        return
    ids = [uuid.UUID(str(p["id"])) for p in prods if p.get("id")]
    positions = await inventory_service.positions_for_products(ORG, product_ids=ids)
    for r in prods:
        pos = positions.get(str(r.get("id")))
        r["quantity_on_hand"] = (float(pos.get("quantity_on_hand") or 0)
                                 if pos is not None
                                 else (0 if r.get("is_stock_tracked") else None))
    tracked = [p for p in prods if p.get("is_stock_tracked")]
    record("E1_tracked_items_carry_units",
           all(isinstance(p.get("quantity_on_hand"), (int, float)) for p in tracked),
           f"tracked={[(p['name'], p.get('quantity_on_hand')) for p in tracked][:4]}")
    record("E2_some_units_are_positive",
           any((p.get("quantity_on_hand") or 0) > 0 for p in tracked),
           f"max={max((p.get('quantity_on_hand') or 0) for p in tracked) if tracked else 0}")


async def main() -> int:
    print(f"== LIVE EFFECTIVENESS BATTERY (org {TEST_ORG_ID}, suffix {SFX}) ==", flush=True)
    await section_a_extraction()
    await section_b_cash_purchase()
    await section_c_cash_selfheal()
    await section_d_units_tracking()
    await section_e_catalogue_units()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n== RESULT: {passed}/{total} passed ==", flush=True)
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAILED: {name} — {detail}", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

