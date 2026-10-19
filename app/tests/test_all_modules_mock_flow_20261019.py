"""ALL-MODULE mock cycle: purchase → sale → sales return (credit note OF
that invoice) → purchase return (debit note OF that bill).

Hermetic — no LLM, no live database: the REAL tool handlers run over an
in-memory document store, and the REAL ``engine.auto_journal`` / ``record_*``
builders produce every journal line (only account resolution and the
prepare/validate/post sink are stubbed), so the directions, amounts,
cross-module references and status transitions asserted here are the
production ones.

Module invariants pinned by this cycle:
* purchase (INVENTORY): DR Inventory / CR Payable, stock RECEIPT recorded,
  posting invariant satisfied (debit == Inventory ledger);
* sale                : DR Receivable / CR Revenue, journal tied, ISSUED;
* sales return        : credit note REFERENCES the invoice (same customer),
  reverses DR Revenue / CR Receivable, status ISSUED, journal tied;
* purchase return     : debit note REFERENCES the bill (same supplier),
  reverses DR Payable / CR expense side, status OPEN, journal tied;
* nets                : customer AR nets 0, supplier AP nets 0 after the
  full returns; every journal balanced (ΣDR == ΣCR).
"""
import uuid

import pytest

import app.accounting_engine as engine
import app.services.accounting_service as accounting_service
from app.services import party_ledger_service

ORG = uuid.UUID("aaaaaaaa-1111-2222-3333-444444444444")
REV = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
AR = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
AP = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
EXP = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000004")
INV_LEDGER = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000005")
CUST = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
SUPP = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
PRODUCT = uuid.UUID("dddddddd-0000-0000-0000-000000000001")


@pytest.fixture
def erp(monkeypatch):
    """In-memory ERP: services + seams, real tools + real journal builders."""
    from app import tools as tools_mod
    from app.repositories import credit_note_repository as cn_repo
    from app.repositories import invoice_repository as inv_repo
    from app.repositories import purchase_return_repository as pr_repo
    from app.services import (
        credit_note_service,
        invoice_service,
        purchase_service,
        purchase_return_service,
    )

    store = {
        "invoices": {}, "bills": {}, "credit_notes": {}, "returns": {},
        "seq": {"inv": 0, "pur": 0, "cn": 0, "ret": 0},
        "journals": [], "validated": [], "posted": [],
        "cn_links": [], "cn_marked": [], "pr_links": [], "pr_marked": [],
        "inv_links": [], "inv_marked": [],
        "movements": [], "catalogue_calls": 0, "cogs_calls": 0,
    }

    # ---- account resolution (read-only seams) -----------------------------
    async def fake_party_receivable(_org, _customer_id=None, **_kw):
        return None  # force the control-account path (symmetric nets)

    async def fake_party_payable(_org, _supplier_id=None, **_kw):
        return None

    async def fake_resolve_account(_org, *, account_name=None, **_kw):
        low = str(account_name or "").lower()
        if "receivable" in low:
            return {"id": str(AR), "account_type": "ASSET"}
        if "payable" in low:
            return {"id": str(AP), "account_type": "LIABILITY"}
        if "inventor" in low:
            return {"id": str(INV_LEDGER), "account_type": "ASSET"}
        if "revenue" in low or "sales" in low:
            return {"id": str(REV), "account_type": "REVENUE"}
        return None

    async def fake_default(_org, kind=None, fallback_type=None, **_kw):
        ids = {"REVENUE": REV, "INCOME": REV, "EXPENSE": EXP,
               "ASSET": AR, "LIABILITY": AP}
        return {"id": str(ids.get(kind, EXP)), "account_type": kind,
                "name": kind}

    async def fake_inventory_ledger(_org, **_kw):
        return {"id": str(INV_LEDGER), "name": "Inventory",
                "code": "1200", "account_type": "ASSET"}

    async def fake_prepare(**kw):
        store["journals"].append(dict(kw))
        return {"entry": {"id": str(uuid.uuid4()),
                          "entry_number": f"JV-{len(store['journals']):06d}"},
                "lines": kw.get("lines") or []}

    async def fake_validate(*, entry_id):
        store["validated"].append(entry_id)

    async def fake_post(*, entry_id):
        store["posted"].append(entry_id)

    async def fake_cogs(*_a, **_kw):
        store["cogs_calls"] += 1
        return {}  # COGS/stock-issue is its own module test; keep this cycle clean

    async def fake_link_products(_org, _items):
        return None  # catalogue linking covered by the stock-linkage tests

    monkeypatch.setattr(party_ledger_service,
                        "resolve_customer_receivable_account",
                        fake_party_receivable)
    monkeypatch.setattr(party_ledger_service,
                        "resolve_supplier_payable_account",
                        fake_party_payable)
    monkeypatch.setattr(accounting_service, "resolve_account",
                        fake_resolve_account)
    monkeypatch.setattr(engine, "_resolve_default_account", fake_default)
    monkeypatch.setattr(engine, "resolve_inventory_account",
                        fake_inventory_ledger)
    monkeypatch.setattr(engine, "ensure_inventory_account",
                        fake_inventory_ledger)
    monkeypatch.setattr(accounting_service, "prepare_journal", fake_prepare)
    monkeypatch.setattr(accounting_service, "validate_journal", fake_validate)
    monkeypatch.setattr(accounting_service, "post_journal", fake_post)
    monkeypatch.setattr(engine, "prepare_cogs_for_items", fake_cogs)
    monkeypatch.setattr(tools_mod, "_link_products_to_items", fake_link_products)

    # ---- in-memory document services (cross-module store) -----------------
    def _total(items):
        return round(sum(
            float(i.get("quantity") or 0) * float(i.get("unit_price") or 0)
            for i in items or []
        ), 2)

    async def fake_create_invoice(*, organization_id, customer_id,
                                  items=None, invoice_date=None, **_kw):
        if not items:
            raise ValueError("Invoice requires line items.")
        store["seq"]["inv"] += 1
        doc = {
            "id": str(uuid.uuid4()),
            "invoice_number": f"INV-{store['seq']['inv']:06d}",
            "customer_id": str(customer_id),
            "items": items,
            "total": _total(items),
            "invoice_date": invoice_date or "2026-10-19",
            "status": "DRAFT",
        }
        store["invoices"][doc["id"]] = doc
        return doc

    async def fake_create_bill(*, organization_id, items=None,
                               supplier_id=None, bill_date=None, **_kw):
        if not items:
            raise ValueError("Purchase bill requires line items.")
        store["seq"]["pur"] += 1
        doc = {
            "id": str(uuid.uuid4()),
            "bill_number": f"PUR-{store['seq']['pur']:06d}",
            "supplier_id": str(supplier_id) if supplier_id else None,
            "items": items,
            "total": _total(items),
            "bill_date": bill_date or "2026-10-19",
            "status": "DRAFT",
        }
        store["bills"][doc["id"]] = doc
        return doc

    async def fake_create_cn(*, organization_id, items=None, reason=None,
                             invoice_id=None, customer_id=None, **_kw):
        # THE SALES-RETURN CONTRACT: a credit note of a specific invoice may
        # only exist when that invoice does, and may never exceed it.
        if not items:
            raise ValueError("Credit note requires at least one line item.")
        if not reason:
            raise ValueError("Credit note requires a reason.")
        inv = store["invoices"].get(str(invoice_id or ""))
        if invoice_id and not inv:
            raise ValueError(f"Invoice not found: {invoice_id}")
        total = _total(items)
        if inv and total > float(inv["total"]) + 1e-6:
            raise ValueError("Credit note exceeds the invoice total.")
        store["seq"]["cn"] += 1
        doc = {
            "id": str(uuid.uuid4()),
            "credit_note_number": f"CN-{store['seq']['cn']:06d}",
            "invoice_id": str(invoice_id) if invoice_id else None,
            "invoice_number": inv["invoice_number"] if inv else None,
            "customer_id": str(customer_id or (inv or {}).get("customer_id")),
            "items": items,
            "total": total,
            "reason": reason,
            "credit_note_date": "2026-10-19",
            "status": "DRAFT",
        }
        store["credit_notes"][doc["id"]] = doc
        return doc

    async def fake_create_pr(*, organization_id, items=None, reason=None,
                             bill_id=None, supplier_id=None, **_kw):
        # THE DEBIT-NOTE CONTRACT: same mirroring against the source BILL.
        if not items:
            raise ValueError("Purchase return requires at least one line item.")
        if not reason:
            raise ValueError("Purchase return requires a reason.")
        bill = store["bills"].get(str(bill_id or ""))
        if bill_id and not bill:
            raise ValueError(f"Bill not found: {bill_id}")
        total = _total(items)
        if bill and total > float(bill["total"]) + 1e-6:
            raise ValueError("Purchase return exceeds the bill total.")
        store["seq"]["ret"] += 1
        doc = {
            "id": str(uuid.uuid4()),
            "return_number": f"RET-{store['seq']['ret']:06d}",
            "bill_id": str(bill_id) if bill_id else None,
            "bill_number": bill["bill_number"] if bill else None,
            "supplier_id": str(supplier_id or (bill or {}).get("supplier_id")),
            "items": items,
            "total": total,
            "reason": reason,
            "return_date": "2026-10-19",
            "status": "DRAFT",
        }
        store["returns"][doc["id"]] = doc
        return doc

    monkeypatch.setattr(invoice_service, "create_invoice", fake_create_invoice)
    monkeypatch.setattr(purchase_service, "create_purchase_bill", fake_create_bill)
    monkeypatch.setattr(credit_note_service, "create_credit_note", fake_create_cn)
    monkeypatch.setattr(purchase_return_service, "create_purchase_return",
                        fake_create_pr)


    # ---- journal ties + statuses the tools write after posting ------------
    async def fake_inv_link(*, invoice_id, journal_entry_id):
        store["inv_links"].append((str(invoice_id), str(journal_entry_id)))

    async def fake_inv_mark(*, invoice_id):
        store["inv_marked"].append(str(invoice_id))

    async def fake_cn_link(*, credit_note_id, journal_entry_id):
        store["cn_links"].append((str(credit_note_id), str(journal_entry_id)))

    async def fake_cn_mark(*, credit_note_id):
        store["cn_marked"].append(str(credit_note_id))

    async def fake_pr_link(*, return_id, journal_entry_id):
        store["pr_links"].append((str(return_id), str(journal_entry_id)))

    async def fake_pr_mark(*, return_id):
        store["pr_marked"].append(str(return_id))

    async def fake_mark_paid(**_kw):
        return None

    monkeypatch.setattr(inv_repo, "link_journal_to_invoice", fake_inv_link)
    monkeypatch.setattr(inv_repo, "mark_issued", fake_inv_mark)
    monkeypatch.setattr(cn_repo, "link_journal_to_credit_note", fake_cn_link)
    monkeypatch.setattr(cn_repo, "mark_issued", fake_cn_mark)
    monkeypatch.setattr(pr_repo, "link_journal_to_purchase_return", fake_pr_link)
    monkeypatch.setattr(pr_repo, "mark_open", fake_pr_mark)
    monkeypatch.setattr(purchase_service, "mark_bill_paid", fake_mark_paid)

    # ---- inventory module seams (purchase receipt) ------------------------
    from app.services import inventory_service

    async def fake_find_or_create(org_id, *, name, quantity, unit_cost):
        store["catalogue_calls"] += 1
        return {"id": str(PRODUCT), "name": name, "product_code": "PRD-000007",
                "is_stock_tracked": True, "reused": True}

    async def fake_receive(org_id, **kw):
        mv = {"id": str(uuid.uuid4()),
              "product_id": str(kw.get("product_id")),
              "quantity": float(kw.get("quantity") or 0),
              "unit_cost": float(kw.get("unit_cost") or 0),
              "source_type": kw.get("source_type")}
        store["movements"].append(mv)
        return mv

    monkeypatch.setattr(inventory_service, "find_or_create_catalogue_product",
                        fake_find_or_create)
    monkeypatch.setattr(inventory_service, "receive_stock", fake_receive)

    return store

# ---------------------------------------------------------------------------
# THE CYCLE: purchase -> sale -> sales return (credit note) -> purchase
# return (debit note), in one deterministic run over the real tool handlers.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_document_cycle_purchase_sale_credit_note_debit_note(erp):
    from app import tools as tools_mod

    def handler(name):
        return tools_mod._TOOL_REGISTRY[name]["handler"]

    def pair(j, dr_acct, cr_acct, amount):
        """Balanced 2-sided entry: DR dr_acct / CR cr_acct for `amount`."""
        lines = j["lines"]
        drs = [l for l in lines if float(l.get("debit") or 0) > 0]
        crs = [l for l in lines if float(l.get("credit") or 0) > 0]
        assert round(sum(float(l["debit"]) for l in lines), 2) == round(
            sum(float(l["credit"]) for l in lines), 2), "journal unbalanced"
        assert {str(l["account_id"]) for l in drs} == {str(dr_acct)}, lines
        assert {str(l["account_id"]) for l in crs} == {str(cr_acct)}, lines
        assert round(sum(float(l["debit"]) for l in drs), 2) == amount

    def net(acct):
        return round(sum(
            float(l.get("debit") or 0) - float(l.get("credit") or 0)
            for j in erp["journals"] for l in j["lines"]
            if str(l.get("account_id")) == str(acct)
        ), 2)

    # ---- 1. PURCHASE (inventory, on credit) -------------------------------
    bill_res = await handler("create_purchase_bill")(
        ORG,
        supplier_id=SUPP,
        items=[{"description": "office chairs", "quantity": 10,
                "unit_price": 4500}],
        transaction_nature="INVENTORY",
        payment_method="CREDIT",
        bill_date="2026-10-19",
    )
    assert bill_res.success, bill_res.error
    bill = erp["bills"][bill_res.data["id"]]
    assert bill["bill_number"] == "PUR-000001" and bill["total"] == 45000
    # posting invariant passed: the debit IS the Inventory ledger
    pair(erp["journals"][0], INV_LEDGER, AP, 45000)
    # catalogue + perpetual stock receipt both fired
    assert erp["catalogue_calls"] == 1
    assert erp["movements"] == [dict(
        id=erp["movements"][0]["id"], product_id=str(PRODUCT),
        quantity=10.0, unit_cost=4500.0, source_type="purchase_bill",
    )]

    # ---- 2. SALE (credit invoice to the customer) -------------------------
    inv_res = await handler("create_invoice")(
        ORG,
        customer_id=CUST,
        items=[{"description": "chairs", "quantity": 5, "unit_price": 6000}],
        invoice_date="2026-10-19",
    )
    assert inv_res.success, inv_res.error
    invoice = erp["invoices"][inv_res.data["id"]]
    assert invoice["invoice_number"] == "INV-000001" and invoice["total"] == 30000
    pair(erp["journals"][1], AR, REV, 30000)
    assert erp["inv_links"][0][0] == invoice["id"]
    assert erp["inv_marked"] == [invoice["id"]]

    # ---- 3. SALES RETURN: credit note OF THAT invoice ---------------------
    cn_res = await handler("create_credit_note")(
        ORG,
        customer_id=CUST,
        items=[{"description": "chairs (returned)", "quantity": 5,
                "unit_price": 6000}],
        invoice_id=invoice["id"],
        reason="Damaged on arrival — full return of INV-000001",
        credit_note_date="2026-10-19",
    )
    assert cn_res.success, cn_res.error
    cn = erp["credit_notes"][cn_res.data["id"]]
    # cross-module reference: THE invoice, same customer, mirrored amount
    assert cn["invoice_id"] == invoice["id"]
    assert cn["invoice_number"] == "INV-000001"
    assert cn["customer_id"] == invoice["customer_id"]
    assert cn["total"] == invoice["total"] == 30000
    # reversal: DR Revenue / CR Receivable, ISSUED, journal tied
    pair(erp["journals"][2], REV, AR, 30000)
    assert cn_res.data["status"] == "ISSUED"
    assert erp["cn_links"][0][0] == cn["id"]
    assert erp["cn_marked"] == [cn["id"]]

    # ---- 4. PURCHASE RETURN: debit note OF THAT bill ----------------------
    pr_res = await handler("create_purchase_return")(
        ORG,
        supplier_id=SUPP,
        items=[{"description": "office chairs (returned)", "quantity": 10,
                "unit_price": 4500}],
        bill_id=bill["id"],
        reason="Wrong item delivered — full return of PUR-000001",
        return_date="2026-10-19",
    )
    assert pr_res.success, pr_res.error
    pr = erp["returns"][pr_res.data["id"]]
    assert pr["bill_id"] == bill["id"]
    assert pr["bill_number"] == "PUR-000001"
    assert pr["supplier_id"] == bill["supplier_id"]
    assert pr["total"] == bill["total"] == 45000
    # reversal: DR Payable / CR expense side, OPEN, journal tied
    pair(erp["journals"][3], AP, EXP, 45000)
    assert pr_res.data["status"] == "OPEN"
    assert erp["pr_links"][0][0] == pr["id"]
    assert erp["pr_marked"] == [pr["id"]]

    # ---- 5. LEDGER NETS after the full cycle ------------------------------
    assert net(AR) == 0        # +30,000 sale  - 30,000 credit note
    assert net(AP) == 0        # -45,000 bill  + 45,000 debit note
    assert net(REV) == 0       # revenue fully reversed by the return
    assert net(INV_LEDGER) == 45000  # stock purchased (COGS module stubbed)
    assert len(erp["journals"]) == 4
    assert len(erp["validated"]) == len(erp["posted"]) == 4


