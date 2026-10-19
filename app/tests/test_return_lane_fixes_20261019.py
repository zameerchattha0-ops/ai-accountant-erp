"""Return-lane faithful carry + schema gates + integrity rules (2026-10-19).

Covers the stage-0 failures and their fixes:
* ``_normalize_return_args`` — invoice/bill reference RESOLUTION, price
  DERIVATION from stated total, ZERO-total refusal before any write;
* ``_carry_forward_write_args`` — a continuation round may reword a write
  call, never SHRINK it (original-plan keys fill drops; model-sent values
  are never overwritten; entity injection only for the return tools);
* fast-path builders — deterministic promotion for credit notes / debit
  notes with self-gating completeness;
* ``_document_integrity_violations`` — the verifier rules that stop a
  zero-total / unlinked / unposted document from ever claiming VERIFIED.
"""
import uuid
from types import SimpleNamespace

import pytest

from app.agent import (
    _carry_forward_write_args,
    _credit_note_fast_path_call,
    _document_integrity_violations,
)
from app.models.schemas import ToolCall
from app.tools import _normalize_return_args

ORG = uuid.UUID("aaaaaaaa-1111-2222-3333-444444444444")


# --- reference resolution + price derivation -------------------------------
@pytest.mark.asyncio
async def test_invoice_number_resolves_and_prices_are_derived(monkeypatch):
    async def fake_fetch(table, *, filters=None, **_kw):
        assert table == "invoices"
        assert filters.get("invoice_number") == "INV-000014"
        return [{"id": "inv-row-1"}]

    monkeypatch.setattr("app.database.fetch_many", fake_fetch)
    kw = await _normalize_return_args(
        ORG,
        {
            "customer_name": "abc technologies",
            "invoice_number": "INV-000014",
            "description": "damaged chair",
            "quantity": 1,
            "amount": 8000,
            "reason": "damaged on arrival",
        },
        kind="credit_note",
    )
    assert kw["invoice_id"] == "inv-row-1"
    assert "invoice_number" not in kw       # consumed helper key stripped
    assert "amount" not in kw               # consumed helper key stripped
    assert kw["items"][0]["unit_price"] == 8000.0  # derived, not guessed


@pytest.mark.asyncio
async def test_bill_number_resolves_for_the_debit_note(monkeypatch):
    async def fake_fetch(table, *, filters=None, **_kw):
        assert table == "purchase_bills"
        assert filters.get("bill_number") == "PUR-000013"
        return [{"id": "bill-row-1"}]

    monkeypatch.setattr("app.database.fetch_many", fake_fetch)
    kw = await _normalize_return_args(
        ORG,
        {
            "supplier_id": "supp-1",
            "bill_number": "PUR-000013",
            "description": "defective chair",
            "quantity": 1,
            "amount": 9000,
        },
        kind="purchase_return",
    )
    assert kw["bill_id"] == "bill-row-1"
    assert kw["items"][0]["unit_price"] == 9000.0


@pytest.mark.asyncio
async def test_zero_total_is_refused_before_any_write():
    with pytest.raises(ValueError, match="ZERO amount"):
        await _normalize_return_args(
            ORG,
            {
                "customer_name": "abc",
                "items": [{"description": "x", "quantity": 1,
                           "unit_price": 0}],
                "reason": "damaged",
            },
            kind="credit_note",
        )


@pytest.mark.asyncio
async def test_unknown_reference_keeps_flow_but_still_prices(monkeypatch):
    async def fake_fetch(table, *, filters=None, **_kw):  # noqa: ARG001
        return []  # reference not found — never blocks the document

    monkeypatch.setattr("app.database.fetch_many", fake_fetch)
    kw = await _normalize_return_args(
        ORG,
        {
            "customer_name": "abc",
            "invoice_number": "INV-999999",
            "description": "returned item",
            "amount": 5000,
        },
        kind="credit_note",
    )
    assert "invoice_id" not in kw           # honestly unresolved, no invent
    assert kw["items"][0]["unit_price"] == 5000.0


@pytest.mark.asyncio
async def test_invoice_id_field_carrying_a_number_is_resolved(monkeypatch):
    """The model wrote the NUMBER into the uuid field ("INV-000014" as
    invoice_id) — live this died inside the service with 'badly formed
    hexadecimal UUID string'.  The normalizer resolves it instead."""

    async def fake_fetch(table, *, filters=None, **_kw):
        assert table == "invoices"
        assert filters.get("invoice_number") == "INV-000014"
        return [{"id": "inv-row-7"}]

    monkeypatch.setattr("app.database.fetch_many", fake_fetch)
    kw = await _normalize_return_args(
        ORG,
        {
            "customer_name": "abc",
            "invoice_id": "INV-000014",   # number in the id field
            "description": "damaged chair",
            "amount": 8000,
        },
        kind="credit_note",
    )
    assert kw["invoice_id"] == "inv-row-7"


@pytest.mark.asyncio
async def test_line_total_parity_is_computed_for_the_repo():
    """CRN-000003 (live): lines with quantity × unit_price but no
    line_total stored a ZERO-total document (repo sums line_total)."""
    kw = await _normalize_return_args(
        ORG,
        {
            "customer_name": "abc",
            "items": [{"description": "chair", "quantity": 2,
                       "unit_price": 4000}],
            "reason": "damaged",
        },
        kind="credit_note",
    )
    assert kw["items"][0]["line_total"] == 8000.0


@pytest.mark.asyncio
async def test_credit_note_strips_cross_document_reference():
    kw = await _normalize_return_args(
        ORG,
        {
            "customer_name": "abc",
            "bill_id": "should-never-ride",
            "bill_number": "PUR-000013",
            "description": "returned item",
            "amount": 500,
        },
        kind="credit_note",
    )
    assert "bill_id" not in kw and "bill_number" not in kw
    assert kw["items"][0]["unit_price"] == 500.0


# --- faithful carry-forward ------------------------------------------------
def test_continuation_drops_are_refilled_from_original_plan():
    original = [
        ToolCall(
            tool_name="create_credit_note",
            arguments={
                "items": [{"quantity": 1, "unit_price": 8000.0}],
                "invoice_number": "INV-000014",
            },
        )
    ]
    rebuilt = [
        ToolCall(
            tool_name="create_credit_note",
            arguments={"items": [{"quantity": 1}], "reason": "ok"},
        )
    ]
    out = _carry_forward_write_args(
        rebuilt,
        entities={"amount": 8000, "customer_name": "abc technologies"},
        original=original,
    )
    args = out[0].arguments
    assert args["invoice_number"] == "INV-000014"   # original fills the drop
    assert args["reason"] == "ok"                    # model value NEVER lost
    assert args["amount"] == 8000                    # entity fills pricing
    assert args["customer_name"] == "abc technologies"
    assert args["items"][0].get("unit_price") is None  # not overwritten


def test_carry_forward_never_touches_non_return_tools():
    out = _carry_forward_write_args(
        [ToolCall(tool_name="create_account", arguments={"name": "Bonus"})],
        entities={"amount": 500, "invoice_number": "INV-1"},
        original=[],
    )
    assert out[0].arguments == {"name": "Bonus"}
    assert "amount" not in out[0].arguments


# --- deterministic fast-path builders (promotion floor) --------------------
def test_credit_note_fast_path_gates_and_passes_reference():
    calls = _credit_note_fast_path_call({
        "customer_name": "abc technologies",
        "amount": 8000,
        "transaction_date": "2026-10-19",
        "invoice_number": "INV-000014",
        "item_description": "damaged chair",
        "quantity": 1,
        "reason": "damaged on arrival",
    })
    assert calls and calls[0].tool_name == "create_credit_note"
    args = calls[0].arguments
    assert args["invoice_number"] == "INV-000014"
    assert args["amount"] == 8000
    assert args["credit_note_date"] == "2026-10-19"
    assert args["reason"] == "damaged on arrival"
    # incomplete plans gate themselves — None means the ladder/model asks
    assert _credit_note_fast_path_call({"customer_name": "abc"}) is None
    assert _credit_note_fast_path_call({
        "customer_name": "abc", "amount": 10, "transaction_date": "2026-10-19",
    }) is None  # no line substance — never a hollow note


@pytest.mark.asyncio
async def test_purchase_return_fast_path_resolves_supplier(monkeypatch):
    from app.services import supplier_service

    async def _found(_org, *, query, limit=5):
        return [{"id": "supp-1", "name": "SHABBIR FURNITURES"}]

    async def _create(*_a, **_k):
        raise AssertionError("existing supplier must be reused")

    monkeypatch.setattr(supplier_service, "search", _found)
    monkeypatch.setattr(supplier_service, "create", _create)
    from app.agent import _purchase_return_fast_path_call

    calls = await _purchase_return_fast_path_call(ORG, {
        "supplier_name": "SHABBIR FURNITURES",
        "amount": 9000,
        "transaction_date": "2026-10-19",
        "bill_number": "PUR-000013",
        "item_description": "defective chair",
        "quantity": 1,
    })
    assert calls and calls[0].tool_name == "create_purchase_return"
    args = calls[0].arguments
    assert args["supplier_id"] == "supp-1"
    assert args["bill_number"] == "PUR-000013"


@pytest.mark.asyncio
async def test_purchase_return_fast_path_never_invents_a_party(monkeypatch):
    from app.agent import _purchase_return_fast_path_call
    from app.services import supplier_service

    async def _none(_org, *, query, limit=5):
        return []

    monkeypatch.setattr(supplier_service, "search", _none)
    calls = await _purchase_return_fast_path_call(ORG, {
        "supplier_name": "Ghost Traders",
        "amount": 9000,
        "transaction_date": "2026-10-19",
        "item_description": "chair",
    })
    assert calls is None  # no exact match, no confirmation -> ask


# --- deterministic verifier rules -----------------------------------------
def _tr(name, data, success=True):
    return SimpleNamespace(tool_name=name, success=success, data=data)


def test_integrity_flags_zero_total_unposted_and_unlinked():
    ents = {"invoice_number": "INV-000014"}
    violations = _document_integrity_violations(
        [
            _tr("create_credit_note", {
                "total": 0.0, "journal_posted": False, "invoice_id": None,
            }),
        ],
        entities=ents,
    )
    text = " | ".join(violations)
    assert "ZERO amount" in text
    assert "reversal journal" in text
    assert "not linked to the invoice" in text


def test_integrity_passes_a_correct_credit_note():
    violations = _document_integrity_violations(
        [
            _tr("create_credit_note", {
                "total": 8000.0, "journal_posted": True,
                "invoice_id": "inv-1",
            }),
        ],
        entities={"invoice_number": "INV-000014"},
    )
    assert violations == []


def test_integrity_ignores_failed_tool_results():
    violations = _document_integrity_violations(
        [_tr("create_purchase_return", {"total": 0}, success=False)],
        entities={},
    )
    assert violations == []



# --- leftover fixes (2026-10-19, second live round) ------------------------
DN_MESSAGE = (
    "We returned 1 defective chair to SHABBIR FURNITURES - create a debit "
    "note against purchase bill PUR-000013 for 9000 with reason wrong item "
    "delivered"
)


def test_dn_message_extracts_supplier_name():
    """The DN lane's supplier was NEVER extracted (the 'we' subject blocked
    the customer rule; nothing owned 'to <Party>'), forcing the lossy model
    path every turn."""
    from app.planner import plan

    p = plan(DN_MESSAGE)
    assert p.intent == "create_purchase_return"
    assert (p.extracted_entities or {}).get("supplier_name") == "SHABBIR FURNITURES"


def test_dn_message_extracts_bill_number_literal():
    """'against purchase bill PUR-000013' used to extract NOTHING (PUR was
    not in the reference alternation)."""
    from app.accounting_reasoning import preliminary_extraction

    literals = preliminary_extraction(DN_MESSAGE).get("literals") or {}
    assert literals.get("bill_number") == "PUR-000013"
    assert literals.get("document_reference") == "PUR-000013"
    assert literals.get("invoice_number") is None  # a bill ref is never an invoice


def test_bill_reference_seed_reaches_the_plan_prefill():
    from app.agent import _seed_invoice_reference

    prefill: dict = {}
    _seed_invoice_reference(
        {"literals": {"bill_number": "PUR-000013"}}, prefill
    )
    assert prefill["bill_number"] == "PUR-000013"
    # invoice seeding unchanged and independent
    prefill2: dict = {}
    _seed_invoice_reference(
        {"literals": {"invoice_number": "INV-000014"}}, prefill2
    )
    assert prefill2["invoice_number"] == "INV-000014"


def test_reason_literal_is_extracted_from_the_message():
    from app.accounting_reasoning import preliminary_extraction

    literals = preliminary_extraction(DN_MESSAGE).get("literals") or {}
    assert literals.get("reason") == "wrong item delivered"


def test_fast_paths_never_emit_a_reasonless_document():
    cn = _credit_note_fast_path_call({
        "customer_name": "abc technologies", "amount": 8000,
        "transaction_date": "2026-10-19",
        "item_description": "damaged chair", "quantity": 1,
    })
    assert cn[0].arguments["reason"] == "Return of damaged chair"
    # the user's own wording always wins over the derived description
    cn2 = _credit_note_fast_path_call({
        "customer_name": "abc", "amount": 8000,
        "transaction_date": "2026-10-19", "item_description": "chair",
        "reason": "wrong item delivered",
    })
    assert cn2[0].arguments["reason"] == "wrong item delivered"


@pytest.mark.asyncio
async def test_get_invoice_resolves_a_number_in_the_id_field(monkeypatch):
    """get_invoice died inside uuid coercion when the model passed the
    NUMBER as invoice_id ('badly formed hexadecimal UUID string')."""
    from app import tools as tools_mod

    async def fake_by_number(_org, *, invoice_number):
        assert invoice_number == "INV-000014"
        return {"id": "11111111-9999-4999-8999-000000000009",
                "invoice_number": "INV-000014"}

    async def fake_get(org_id, *, invoice_id):
        assert str(invoice_id) == "11111111-9999-4999-8999-000000000009"
        return {"id": "11111111-9999-4999-8999-000000000009", "total": 24000}

    monkeypatch.setattr(
        "app.repositories.invoice_repository.get_invoice_by_number",
        fake_by_number,
    )
    monkeypatch.setattr(tools_mod.invoice_service, "get_invoice", fake_get)
    result = await tools_mod._TOOL_REGISTRY["get_invoice"]["handler"](
        ORG, invoice_id="INV-000014"
    )
    assert result.success and result.data["total"] == 24000


@pytest.mark.asyncio
async def test_get_purchase_bill_resolves_a_number_in_the_id_field(monkeypatch):
    from app import tools as tools_mod

    async def fake_fetch(table, *, filters=None, **_kw):
        assert table == "purchase_bills"
        assert filters.get("bill_number") == "PUR-000013"
        return [{"id": "22222222-9999-4999-8999-000000000005"}]

    async def fake_get(org_id, *, bill_id):
        assert str(bill_id) == "22222222-9999-4999-8999-000000000005"
        return {"id": "22222222-9999-4999-8999-000000000005", "total": 45000}

    monkeypatch.setattr("app.database.fetch_many", fake_fetch)
    monkeypatch.setattr(tools_mod.purchase_service, "get_purchase_bill", fake_get)
    result = await tools_mod._TOOL_REGISTRY["get_purchase_bill"]["handler"](
        ORG, bill_id="PUR-000013"
    )
    assert result.success and result.data["total"] == 45000

