"""Regression suite - inventory purchase treatment (production 2026-10-18).

THE FAILURE: session a2af6ba1 "Bought 2 tables ON CREDIT FROM SHABBIR
FURNITURES" - classification said INVENTORY (HIGH, USER_ANSWER) but the
canonical plan dropped the nature and the item lines, the wording-recovery
regex could not match "tables", and the journal posted
DR 6000 General Operating Expense / CR Shabbir payable.

Pins, per the approved conditions:
1. the CONFIRMED nature + GROUNDED item lines survive materialization;
2. a missing grounded quantity/description STOPS execution with a question
   (never inferred from the total);
3. credit acquisitions no longer claim cash_bank impact; cash + settlement
   paths unchanged;
4. the posting invariant fails closed - an INVENTORY purchase never posts to
   an expense ledger; draft cleanup is attempted only where supported and
   cleanup failures are reported honestly; an unposted draft is never a
   success;
5. both LLM-enabled and LLM-disabled paths of the stage-2 enrichment and
   the stage-15 review (flag-gated; deterministic safeguards authoritative).
No live database: every seam is stubbed (app/tests/conftest.py contract).
"""
from __future__ import annotations

import asyncio
import json
import uuid

from app.models.schemas import ToolCall
from app.plan_materialization import ERROR, TREATMENT, prepare_plan

_ORG = uuid.UUID("00000000-0000-4000-8000-000000000099")


def _run(coro):
    return asyncio.run(coro)


def _tables_treatment(**overrides):
    treatment = {
        "intent": "record_credit_purchase",
        "transaction_nature": "INVENTORY",
        "entities": {
            "supplier_name": "SHABBIR FURNITURES",
            "payment_method": "CREDIT",
            "item_description": "tables",
            "quantity": 2.0,
            "item_quantity": 2.0,
            "amount": 230000.0,
            "transaction_date": "2026-10-18",
        },
    }
    treatment.update(overrides)
    return treatment


def _bill_call(**extra):
    args = {
        "notes": "tables",
        "total": 230000.0,
        "subtotal": 230000.0,
        "bill_date": "2026-10-18",
        "supplier_id": str(uuid.uuid4()),
    }
    args.update(extra)
    return ToolCall(tool_name="create_purchase_bill", arguments=args)


async def _stub_supplier_resolved(*args, **kwargs):
    from app.plan_materialization import Resolution

    return Resolution(
        role="supplier", requested="SHABBIR FURNITURES",
        status="one", match_id=str(uuid.uuid4()),
    )


# ---------------------------------------------------------------------------
# 1 - MATERIALIZATION: nature + grounded lines travel with the call
# ---------------------------------------------------------------------------

def test_materialization_binds_nature_and_grounded_lines(monkeypatch):
    """THE tables case: nature bound; qty=2 is the user's OWN literal; the
    unit price is arithmetic on grounded values (230,000 / 2)."""
    import app.plan_materialization as pm

    monkeypatch.setattr(pm, "resolve_reference", _stub_supplier_resolved)
    original = _bill_call()
    snapshot = dict(original.arguments)
    result = _run(prepare_plan(
        organization_id=_ORG,
        calls=[original],
        treatment=_tables_treatment(),
    ))
    assert not result.blocks, result.blocks
    call = result.calls[0]
    assert call.arguments["transaction_nature"] == "INVENTORY"
    assert call.arguments["items"] == [{
        "description": "tables",
        "quantity": 2.0,
        "unit_price": 115000.0,
    }]
    statuses = [(d.parameter, d.status) for d in result.decisions]
    assert ("transaction_nature", TREATMENT) in statuses
    assert ("items", TREATMENT) in statuses
    assert original.arguments == snapshot


def test_missing_quantity_blocks_with_clarification(monkeypatch):
    """No stated quantity -> never back-solved from the total: execution
    STOPS with a question and the refusal is an audited decision."""
    import app.plan_materialization as pm

    monkeypatch.setattr(pm, "resolve_reference", _stub_supplier_resolved)
    treatment = _tables_treatment()
    treatment["entities"] = dict(treatment["entities"])
    del treatment["entities"]["quantity"]
    del treatment["entities"]["item_quantity"]
    result = _run(prepare_plan(
        organization_id=_ORG,
        calls=[_bill_call()],
        treatment=treatment,
    ))
    assert result.blocked
    assert "HOW MANY" in " ".join(result.blocks)
    assert "items" not in result.calls[0].arguments
    blocked = [d for d in result.decisions if d.status == ERROR]
    assert blocked and blocked[0].parameter == "items"


def test_laptop_case_grounds_unit_price_from_quantity():
    """Same-day incident: 2 LAPTOPS / 12,000 -> unit 6,000; nature bound."""
    result = _run(prepare_plan(
        organization_id=_ORG,
        calls=[ToolCall(tool_name="create_purchase_bill", arguments={
            "notes": "LAPTOPS", "total": 12000.0, "bill_date": "2026-10-18",
            "supplier_id": str(uuid.uuid4()),
        })],
        treatment={
            "intent": "record_credit_purchase",
            "transaction_nature": "INVENTORY",
            "entities": {
                "item_description": "LAPTOPS", "quantity": 2.0,
                "amount": 12000.0,
            },
        },
    ))
    call = result.calls[0]
    assert call.arguments["transaction_nature"] == "INVENTORY"
    assert call.arguments["items"][0]["unit_price"] == 6000.0


def test_expense_nature_binds_nature_but_never_synthesises_items():
    """ORDINARY EXPENSE control: an OPERATING_EXPENSE purchase carries the
    nature but no stock lines - the expense path stays untouched."""
    result = _run(prepare_plan(
        organization_id=_ORG,
        calls=[ToolCall(tool_name="create_purchase_bill", arguments={
            "notes": "office tea", "total": 900.0,
            "supplier_id": str(uuid.uuid4()),
        })],
        treatment={
            "intent": "record_purchase",
            "transaction_nature": "OPERATING_EXPENSE",
            "entities": {"amount": 900.0},
        },
    ))
    assert not result.blocks
    assert result.calls[0].arguments["transaction_nature"] == "OPERATING_EXPENSE"
    assert "items" not in result.calls[0].arguments


def test_no_treatment_context_keeps_legacy_behaviour():
    """Backward compatibility: without treatment the plan is untouched."""
    result = _run(prepare_plan(
        organization_id=_ORG,
        calls=[ToolCall(tool_name="create_purchase_bill", arguments={
            "total": 500.0, "supplier_id": str(uuid.uuid4()),
        })],
    ))
    assert not result.blocks
    assert "transaction_nature" not in result.calls[0].arguments


# ---------------------------------------------------------------------------
# 2 - IMPACT METADATA: cash_bank for credit acquisitions (reasoning.py)
# ---------------------------------------------------------------------------

def test_credit_purchase_impact_drops_cash_bank():
    from app.reasoning import build_event_profile

    profile = build_event_profile("record_credit_purchase")
    assert profile.affected["cash_bank"] is False       # FIX 3
    assert profile.affected["party_ledger"] is True
    assert profile.affected["ar_ap"] is True


def test_cash_purchase_keeps_cash_bank():
    from app.reasoning import build_event_profile

    profile = build_event_profile("record_cash_purchase")
    assert profile.affected["cash_bank"] is True


def test_supplier_settlement_keeps_cash_bank():
    """record_payment IS the cash movement - its event must keep cash_bank."""
    from app.reasoning import build_event_profile

    profile = build_event_profile("record_payment")
    assert profile.affected["cash_bank"] is True


def test_credit_sale_event_drops_cash_bank():
    from app.reasoning import build_event_profile

    profile = build_event_profile("record_credit_sale")
    assert profile.affected["cash_bank"] is False
    assert profile.affected["revenue"] is True



# ---------------------------------------------------------------------------
# 3 - POSTING BOUNDARY: the invariant fails closed (_create_purchase_bill)
# ---------------------------------------------------------------------------

_INV = {"id": str(uuid.uuid4()), "name": "Inventory", "account_type": "ASSET"}
_PAYABLE = str(uuid.uuid4())
_EXPENSE = str(uuid.uuid4())


def _bill_rows(with_product=True):
    line = {"description": "tables", "quantity": 2.0, "unit_price": 115000.0}
    if with_product:
        line["product_id"] = str(uuid.uuid4())
    return line


def _journal_result(debit_account_id):
    return {
        "journal_entry": {
            "entry": {"id": str(uuid.uuid4())},
            "lines": [
                {"account_id": str(debit_account_id), "debit": 230000.0,
                 "credit": 0},
                {"account_id": _PAYABLE, "debit": 0, "credit": 230000.0},
            ],
        }
    }


def _stub_handler(monkeypatch, *, ledger, journal_debit, ensure=None,
                  delete_raises=False):
    """Wire every seam the handler touches. Returns a capture dict."""
    import app.tools as tools_mod
    import app.accounting_engine as engine_mod
    import app.database as db_mod

    cap = {"service_calls": 0, "posted": [], "validated": [],
           "received": [], "deleted": [], "resolve_calls": 0}

    async def _create_bill(organization_id, **kw):
        cap["service_calls"] += 1
        return {"id": str(uuid.uuid4()), "bill_number": "PUR-T1",
                "bill_date": "2026-10-18", "total": 230000.0,
                "items": kw.get("items") or []}

    async def _sync(organization_id, *, name, quantity, unit_cost):
        return {"id": _bill_rows()["product_id"], "name": name,
                "product_code": "SKU-T1", "reused": False}

    async def _auto_journal(**kw):
        cap["nature_seen"] = kw.get("transaction_nature")
        return _journal_result(journal_debit)

    async def _resolve(organization_id, *, hint_account=None):
        cap["resolve_calls"] += 1
        return ledger

    async def _ensure(organization_id, *, hint_account=None):
        return ensure  # the VALUE the ensure step produces (may be None)

    async def _validate(entry_id):
        cap["validated"].append(str(entry_id))

    async def _post(entry_id):
        cap["posted"].append(str(entry_id))

    async def _receive(organization_id, *, product_id, quantity, unit_cost,
                       source_type, source_id, movement_date, description):
        cap["received"].append(float(quantity))
        return {"id": str(uuid.uuid4()), "quantity": quantity}

    async def _delete(table, *, row_id, organization_id):
        if delete_raises:
            raise RuntimeError("guard refused")
        cap["deleted"].append(str(row_id))

    monkeypatch.setattr(tools_mod.purchase_service,
                        "create_purchase_bill", _create_bill)
    monkeypatch.setattr(tools_mod.inventory_service,
                        "find_or_create_catalogue_product", _sync)
    monkeypatch.setattr(tools_mod.inventory_service, "receive_stock", _receive)
    monkeypatch.setattr(tools_mod, "auto_journal", _auto_journal)
    monkeypatch.setattr(tools_mod.accounting_service,
                        "validate_journal", _validate)
    monkeypatch.setattr(tools_mod.accounting_service, "post_journal", _post)
    monkeypatch.setattr(engine_mod, "resolve_inventory_account", _resolve)
    monkeypatch.setattr(engine_mod, "ensure_inventory_account", _ensure)
    monkeypatch.setattr(db_mod, "delete_one", _delete)
    return cap


def _invoke(nature="INVENTORY"):
    from app.tools import _create_purchase_bill

    kwargs = {"total": 230000.0, "bill_date": "2026-10-18",
              "supplier_id": str(uuid.uuid4()), "notes": "tables",
              "items": [_bill_rows()]}
    if nature:
        kwargs["transaction_nature"] = nature
    return _run(_create_purchase_bill(_ORG, **kwargs))



def test_inventory_purchase_posts_inventory_debit_and_receives_stock(monkeypatch):
    """HAPPY PATH: debit == Inventory ledger -> posted; stock receipt is
    verified SEPARATELY from the journal (catalogue alone proves nothing)."""
    cap = _stub_handler(monkeypatch, ledger=_INV, journal_debit=_INV["id"])
    result = _invoke()
    assert result.success is True
    assert result.data["journal_posted"] is True
    assert cap["posted"] and cap["validated"]
    assert cap["received"] == [2.0]          # stock effect: +2 units


def test_a_cash_inventory_purchase_also_receives_units(monkeypatch):
    """UNITS TRACKING IS SETTLEMENT-AGNOSTIC (2026-10-20): a CASH inventory
    purchase must receive stock exactly like a credit one.  The receipt block
    is gated on is_inventory + journal_posted, never on payment_method, so
    paying cash immediately does not skip the stock ledger."""
    cap = _stub_handler(monkeypatch, ledger=_INV, journal_debit=_INV["id"])

    from app.tools import _create_purchase_bill

    result = _run(_create_purchase_bill(
        _ORG,
        total=230000.0, bill_date="2026-10-20",
        supplier_id=str(uuid.uuid4()), notes="tables",
        items=[_bill_rows()],
        transaction_nature="INVENTORY",
        payment_method="CASH",
    ))
    assert result.success is True
    assert result.data["journal_posted"] is True
    assert cap["received"] == [2.0]          # cash STILL receives +2 units


# ---------------------------------------------------------------------------
# 3b - CASH PURCHASE IS ITS OWN DOCUMENT (2026-10-20): no bill, no payable
# ---------------------------------------------------------------------------
# THE ACCOUNTING DEFECT: the old path routed cash purchases through
# create_purchase_bill (writing a purchase_bills row + a payable, then marking
# it PAID).  A cash purchase is settled now — it must be a DIRECT two-line
# journal (Dr Inventory/asset/expense, Cr Cash-or-Bank) with NO supplier
# invoice and NO Accounts-Payable posting.

_CASH = {"id": str(uuid.uuid4()), "name": "Cash", "account_type": "ASSET"}


def _stub_cash_handler(monkeypatch, *, inventory=None, expense=None,
                       cash=None, created_cash=False):
    """Wire every seam _record_cash_purchase touches. Returns a capture dict."""
    import app.tools as tools_mod
    import app.accounting_engine as engine_mod

    cap = {"prepared": None, "validated": [], "posted": [],
           "received": [], "synced": [], "cash_ensure_calls": 0,
           "bill_service_calls": 0}

    async def _fake_bill(*a, **k):       # a bill must NEVER be created
        cap["bill_service_calls"] += 1
        raise AssertionError("cash purchase must not create a purchase bill")

    async def _ensure_cash(org):
        cap["cash_ensure_calls"] += 1
        row = dict(cash or _CASH)
        if created_cash:
            row["cash_account_created"] = True
        return row

    async def _ensure_inventory(org, *, hint_account=None):
        return inventory

    async def _default(org, account_type, **kw):
        return expense

    async def _engine_cash_purchase(*, organization_id, asset_account_id,
                                    cash_account_id, amount, transaction_date,
                                    description, source_id=None):
        cap["prepared"] = {
            "asset_account_id": str(asset_account_id),
            "cash_account_id": str(cash_account_id),
            "amount": amount,
        }
        return {"entry": {"id": str(uuid.uuid4())}, "lines": [],
                "total_debit": amount, "total_credit": amount}

    async def _validate(entry_id):
        cap["validated"].append(str(entry_id))

    async def _post(entry_id):
        cap["posted"].append(str(entry_id))

    async def _sync(org, *, name, quantity, unit_cost):
        cap["synced"].append(name)
        return {"id": str(uuid.uuid4()), "name": name, "product_code": "SKU-C1",
                "reused": False}

    async def _receive(org, *, product_id, quantity, unit_cost, source_type,
                       source_id, movement_date, description):
        cap["received"].append(float(quantity))
        return {"id": str(uuid.uuid4()), "quantity": quantity}

    monkeypatch.setattr(tools_mod.purchase_service,
                        "create_purchase_bill", _fake_bill)
    monkeypatch.setattr(tools_mod, "ensure_cash_account", _ensure_cash)
    monkeypatch.setattr(tools_mod, "record_cash_purchase", _engine_cash_purchase)
    monkeypatch.setattr(tools_mod.accounting_service, "validate_journal", _validate)
    monkeypatch.setattr(tools_mod.accounting_service, "post_journal", _post)
    monkeypatch.setattr(engine_mod, "ensure_inventory_account", _ensure_inventory)
    monkeypatch.setattr(engine_mod, "_resolve_default_account", _default)
    monkeypatch.setattr(tools_mod.inventory_service,
                        "find_or_create_catalogue_product", _sync)
    monkeypatch.setattr(tools_mod.inventory_service, "receive_stock", _receive)
    return cap


def _cash_purchase(**extra):
    from app.tools import _record_cash_purchase

    kwargs = {
        "amount": 230000.0,
        "transaction_date": "2026-10-20",
        "transaction_nature": "INVENTORY",
        "description": "tables",
        "items": [{"description": "tables", "quantity": 2.0,
                   "unit_price": 115000.0}],
    }
    kwargs.update(extra)
    return _run(_record_cash_purchase(_ORG, **kwargs))


def test_cash_purchase_posts_dr_inventory_cr_cash_with_no_bill(monkeypatch):
    """THE FIX: cash purchase = direct Dr Inventory / Cr Cash, NO bill row,
    NO payable — and the Cash ledger is ensured (resolve-or-create) first."""
    cap = _stub_cash_handler(monkeypatch, inventory=_INV, cash=_CASH)
    result = _cash_purchase()
    assert result.success is True
    assert cap["bill_service_calls"] == 0        # NEVER a purchase bill
    assert cap["cash_ensure_calls"] == 1         # Cash ledger ensured first
    assert cap["prepared"]["asset_account_id"] == _INV["id"]
    assert cap["prepared"]["cash_account_id"] == _CASH["id"]
    assert cap["posted"] and cap["validated"]    # auto-validated + posted


def test_cash_purchase_receives_stock_units(monkeypatch):
    """Cash inventory purchases track UNITS too (no bill needed for a receipt)."""
    cap = _stub_cash_handler(monkeypatch, inventory=_INV, cash=_CASH)
    result = _cash_purchase()
    assert result.success is True
    assert cap["synced"] == ["tables"]           # catalogue product created
    assert cap["received"] == [2.0]              # stock ledger +2 units
    assert result.data["stock_received"][0]["quantity"] == 2.0


def test_cash_purchase_discloses_a_created_cash_account(monkeypatch):
    """When the chart had NO Cash ledger, ensure_cash_account CREATES one and
    the write is disclosed (never disguised as a read)."""
    cap = _stub_cash_handler(monkeypatch, inventory=_INV, cash=_CASH,
                             created_cash=True)
    result = _cash_purchase()
    assert result.success is True
    assert result.data.get("cash_account_created") is True


def test_cash_purchase_refuses_when_no_cash_ledger_can_be_made(monkeypatch):
    """No Cash ledger AND create failed -> refuse BEFORE any write."""
    cap = _stub_cash_handler(monkeypatch, inventory=_INV)

    async def _no_cash(org):
        cap["cash_ensure_calls"] += 1
        return None

    monkeypatch.setattr("app.tools.ensure_cash_account", _no_cash)
    result = _cash_purchase()
    assert result.success is False
    assert cap["bill_service_calls"] == 0
    assert not cap["posted"] and not cap["received"]
    assert "Cash/Bank" in result.error


def test_non_inventory_cash_purchase_debits_the_expense_default(monkeypatch):
    """A non-resale cash purchase debits the resolved expense/asset default,
    still credits Cash, and touches neither catalogue nor stock."""
    expense = {"id": str(uuid.uuid4()), "name": "General Operating Expense",
               "account_type": "EXPENSE"}
    cap = _stub_cash_handler(monkeypatch, expense=expense, cash=_CASH)
    result = _cash_purchase(transaction_nature="OPERATING_EXPENSE",
                            description="office tea", amount=900.0,
                            items=None)
    assert result.success is True
    assert cap["prepared"]["asset_account_id"] == expense["id"]
    assert cap["prepared"]["cash_account_id"] == _CASH["id"]
    assert cap["synced"] == [] and cap["received"] == []
    assert cap["bill_service_calls"] == 0


def test_inventory_account_creation_is_disclosed(monkeypatch):
    """Condition 3: account creation is a WRITE and is reported as such."""
    created = {"id": str(uuid.uuid4()), "name": "Inventory",
               "account_type": "ASSET"}
    cap = _stub_handler(monkeypatch, ledger=None,
                        journal_debit=created["id"], ensure=created)
    result = _invoke()
    assert result.success is True
    assert result.data.get("inventory_account_created") is True


def test_inventory_purchase_fails_before_any_write_when_no_ledger(monkeypatch):
    """Conditions 3/4: no ledger -> refuse BEFORE the bill exists."""
    import app.accounting_engine as engine_mod

    cap = _stub_handler(monkeypatch, ledger=None, journal_debit=_EXPENSE)

    async def _no_ensure(organization_id, *, hint_account=None):
        return None

    monkeypatch.setattr(engine_mod, "ensure_inventory_account", _no_ensure)
    result = _invoke()
    assert result.success is False
    assert cap["service_calls"] == 0        # NO bill, NO journal, NO stock
    assert not cap["posted"] and not cap["received"]
    assert "NOTHING was recorded" in result.error


def test_invariant_refuses_expense_routing_and_cleans_draft(monkeypatch):
    """Condition 4 fail-closed: a prepared EXPENSE debit is NEVER posted;
    the DRAFT is deleted (supported cleanup) and the tool reports failure."""
    cap = _stub_handler(monkeypatch, ledger=_INV, journal_debit=_EXPENSE)
    result = _invoke()
    assert result.success is False
    assert not cap["posted"] and not cap["validated"]
    assert cap["deleted"]                   # draft cleanup attempted+supported
    assert "NOT posted" in result.error
    assert not cap["received"]              # stock never moves on a refusal


def test_invariant_reports_cleanup_failure_honestly(monkeypatch):
    cap = _stub_handler(monkeypatch, ledger=_INV, journal_debit=_EXPENSE,
                        delete_raises=True)
    result = _invoke()
    assert result.success is False
    assert "DELETE FAILED" in result.error


def test_ordinary_expense_purchase_unaffected(monkeypatch):
    """ORDINARY EXPENSE control: no inventory resolution, posts as before."""
    cap = _stub_handler(monkeypatch, ledger=_INV, journal_debit=_EXPENSE)
    result = _invoke(nature="OPERATING_EXPENSE")
    assert result.success is True
    assert cap["resolve_calls"] == 0        # invariant scoped to INVENTORY
    assert cap["posted"]



# ---------------------------------------------------------------------------
# 4 - STAGE 2 LLM EXTRACTION (flag-gated; AUTHORITY-SPLIT 2026-10-20)
# ---------------------------------------------------------------------------
# party/item/quantity/reason are LLM-AUTHORITATIVE (model overrides regex);
# amount/transaction_date stay DETERMINISTIC-FIRST (regex wins, model fills
# gaps only) so a hallucinated figure/date can never reach the books.

_PRELIM = {
    "label": "PRELIMINARY EXTRACTION",
    "original_request": "Bought tables for 230000",
    "literals": {"amount": 230000.0},
    "candidate_subject_areas": ["purchases"],
    "provisional_intent_hint": "record_credit_purchase",
    "note": "Provisional only.",
    "today": "2026-10-18",
}


class _StubClient:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    async def generate_text_light(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def _settings(monkeypatch, **flags):
    from app.config import get_settings

    settings = get_settings()
    for key, value in flags.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def test_stage2_disabled_returns_deterministic_unchanged(monkeypatch):
    from app.llm_extraction import enrich_preliminary

    _settings(monkeypatch, llm_preliminary_extraction_enabled=False)
    merged, audit = _run(enrich_preliminary(
        user_message="Bought tables for 230000",
        preliminary=dict(_PRELIM),
        client=AssertionError("must not be called"),  # loud no-LLM guard
    ))
    assert merged == _PRELIM
    assert audit["llm"] == "skipped_disabled"


def test_stage2_amount_stays_deterministic_but_item_is_llm_authoritative(monkeypatch):
    """AUTHORITY SPLIT: amount 999 must NOT overwrite the rules' 230000
    (deterministic-first), while item/quantity/party ARE taken from the model
    (LLM-authoritative)."""
    from app.llm_extraction import enrich_preliminary

    _settings(monkeypatch, llm_preliminary_extraction_enabled=True)
    client = _StubClient(json.dumps({
        "amount": 999.0,               # must NOT overwrite the rules' 230000
        "quantity": 2,                 # taken from the model (authoritative)
        "item_description": "office chairs",
        "payment_channel": "CREDIT",
        "supplier_name": "SHABBIR FURNITURES",
        "named_parties": ["SHABBIR FURNITURES"],
        "candidate_subject_areas": ["purchases"],
    }))
    merged, audit = _run(enrich_preliminary(
        user_message="Bought 2 office chairs on credit from SHABBIR FURNITURES for 230000",
        preliminary=dict(_PRELIM), client=client,
    ))
    assert merged["literals"]["amount"] == 230000.0     # deterministic wins
    assert merged["literals"]["quantity"] == 2          # model authoritative
    assert merged["literals"]["item_description"] == "office chairs"
    assert merged["literals"]["supplier_name"] == "SHABBIR FURNITURES"
    assert merged["literals"]["payment_channel"] == "CREDIT"
    assert "quantity" in audit["filled"]
    assert "supplier_name" in audit["filled"]
    # extraction, NOT interpretation: no treatment/account keys ever merge
    assert "transaction_nature" not in merged["literals"]


def test_stage2_llm_fixes_a_party_swallowed_into_the_item(monkeypatch):
    """THE UMER-AUTOS FAILURE (2026-10-20): the regex captured the WHOLE
    phrase 'return to umer autos against damaged motorbikes' as the item,
    losing the supplier.  The model is now authoritative: it splits the party
    out and the clean item reaches the literals."""
    from app.llm_extraction import enrich_preliminary

    _settings(monkeypatch, llm_preliminary_extraction_enabled=True)
    # the deterministic floor already (wrongly) put the whole phrase in item
    prelim = {
        "label": "PRELIMINARY EXTRACTION",
        "original_request": "purchase return to umer autos against damaged motorbikes",
        "literals": {"item_description": "return to umer autos against damaged motorbikes"},
        "candidate_subject_areas": ["purchases"],
        "note": "Provisional only.",
        "today": "2026-10-20",
    }
    client = _StubClient(json.dumps({
        "supplier_name": "umer autos",
        "item_description": "damaged motorbikes",
        "quantity": None,
        "amount": None,
        "reason": "damaged motorbikes",
        "named_parties": ["umer autos"],
        "candidate_subject_areas": ["purchases", "payables"],
    }))
    merged, audit = _run(enrich_preliminary(
        user_message="purchase return to umer autos against damaged motorbikes",
        preliminary=prelim, client=client,
    ))
    # the model OVERRIDES the regex-swallowed item and adds the supplier
    assert merged["literals"]["item_description"] == "damaged motorbikes"
    assert merged["literals"]["supplier_name"] == "umer autos"
    assert merged["literals"]["reason"] == "damaged motorbikes"
    assert "item_description" in audit["overrode_regex"]
    assert "supplier_name" in audit["filled"]


def test_stage2_invalid_quantity_is_recorded_never_assumed(monkeypatch):
    """Condition 1: an invalid critical value is RECORDED, not assumed - the
    field stays unfilled so the materializer still asks the question."""
    from app.llm_extraction import enrich_preliminary

    _settings(monkeypatch, llm_preliminary_extraction_enabled=True)
    client = _StubClient(json.dumps({"quantity": "two", "amount": -5}))
    merged, audit = _run(enrich_preliminary(
        user_message="Bought tables", preliminary=dict(_PRELIM),
        client=client,
    ))
    assert "quantity" not in merged["literals"]
    assert any("quantity" in f for f in audit["validation_failures"])
    assert any("amount" in f for f in audit["validation_failures"])


def test_stage2_unparseable_reply_degrades_silently(monkeypatch):
    from app.llm_extraction import enrich_preliminary

    _settings(monkeypatch, llm_preliminary_extraction_enabled=True)
    merged, audit = _run(enrich_preliminary(
        user_message="x", preliminary=dict(_PRELIM),
        client=_StubClient("sorry, no json today"),
    ))
    assert merged == _PRELIM
    assert audit["llm"] == "rejected"



# ---------------------------------------------------------------------------
# 5 - STAGE 15 TREATMENT REVIEW (advisory; never authoritative)
# ---------------------------------------------------------------------------

class _FakeClassification:
    transaction_nature = "INVENTORY"
    source = "USER_ANSWER"


def _review(monkeypatch, reply):
    from app.treatment_review import review_plan_treatment

    _settings(monkeypatch, treatment_review_enabled=True)
    client = _StubClient(reply)
    review = _run(review_plan_treatment(
        organization_id=_ORG,
        intent="record_credit_purchase",
        classification=_FakeClassification(),
        entities={"item_description": "tables", "quantity": 2.0,
                  "amount": 230000.0, "payment_method": "CREDIT"},
        calls=[ToolCall(tool_name="create_purchase_bill",
                        arguments={"total": 230000.0})],
        client=client,
    ))
    return review, client


def test_review_disabled_is_skipped(monkeypatch):
    from app.treatment_review import review_plan_treatment

    _settings(monkeypatch, treatment_review_enabled=False)
    review = _run(review_plan_treatment(
        organization_id=_ORG, intent="record_credit_purchase",
        classification=_FakeClassification(), entities={},
        calls=[], client=AssertionError("must not be called"),
    ))
    assert review.ran is False and review.ok is True
    assert review.audit["llm"] == "skipped_disabled"


def test_review_flags_contradiction_and_blocks_with_question(monkeypatch):
    review, client = _review(monkeypatch, json.dumps({
        "contradictions": [{
            "kind": "nature_vs_plan",
            "why": "classified INVENTORY but the plan carries no nature or items",
        }],
        "missing_material_facts": ["item lines"],
    }))
    assert review.ran is True
    assert review.blocked is True and review.ok is False
    assert "INVENTORY" in review.question
    # the prompt carried ONLY the bounded confirmed facts + plan args
    assert "CONFIRMED FACTS" in client.prompts[0]
    assert review.audit["llm"] == "flagged"


def test_review_consistent_plan_passes(monkeypatch):
    review, _ = _review(monkeypatch, json.dumps(
        {"contradictions": [], "missing_material_facts": []}
    ))
    assert review.ran is True
    assert review.blocked is False and review.ok is True


def test_review_client_error_degrades_to_ok(monkeypatch):
    """MODEL_ABSENT (production 2026-10-18) must never stop the turn."""
    from app.treatment_review import review_plan_treatment

    _settings(monkeypatch, treatment_review_enabled=True)

    class _Boom:
        async def generate_text_light(self, prompt):
            raise RuntimeError("provider down")

    review = _run(review_plan_treatment(
        organization_id=_ORG, intent="record_credit_purchase",
        classification=_FakeClassification(), entities={}, calls=[],
        client=_Boom(),
    ))
    assert review.ran is False and review.ok is True
    assert review.audit["llm"] == "skipped_unavailable"


def test_review_unparseable_reply_never_blocks(monkeypatch):
    review, _ = _review(monkeypatch, "not json at all")
    assert review.ran is False and review.ok is True
    assert review.audit["llm"] == "rejected"

