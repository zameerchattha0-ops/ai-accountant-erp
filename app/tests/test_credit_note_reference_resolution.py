"""create_credit_note reference resolution — the proven
record_customer_receipt pattern mirrored to the credit-note flow (2026-10-17).

Production evidence (org 4f20f43c, 2026-10-15/16):

* "Create Credit note against invoice no.12"  -> sessions 1063596a / 8191f071,
  both CANCELLED;
* 'Issue credit note against "INV-000011"' -> sessions 69897b2d / 89713e4e,
  both dead the same way.

Every attempt reached intent=create_credit_note (routing was correct) and the
intake even captured the reference (``literals.document_reference``), yet all
died at ``plan_incomplete``: nothing could turn the spoken invoice number into
the invoice_id the service binds — ``get_invoice`` takes ONLY a uuid, no
by-number reader exists, and no ReferenceSpec declared the alias.

The receipt flow received exactly this fix after production session 3ea794a0
("invoice_number is not a parameter"): a DECLARED ReferenceSpec that resolves
the number org-scoped exact-match BEFORE binding, plus a signature-derived
contract so the alias is advertised to the reasoning prompt and accepted by
the gate.  These tests pin the same invariants for create_credit_note:

  1. the declaration exists with the receipt's alias vocabulary;
  2. a spoken number resolves read-only to invoice_id (one exact match),
     and the approved plan itself is never mutated;
  3. an unresolvable number BLOCKS with a question naming it — never
     invents an id, never silently unanchors;
  4. an absent number stays unanchored WITHOUT a question (invoice_id is
     optional in the service);
  5. the registered contract advertises ``invoice_number->invoice_id`` to
     the prompt and the gate accepts the declared alias;
  6. the P1-5 evidence path resolves the customer alias with zero queries.

No live provider, no live database — repository/service lookups stubbed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from app.models.schemas import ToolCall
from app.plan_materialization import (
    DECLARED_REFERENCES,
    declared_reference_inputs,
    prepare_plan,
)

ORG = uuid.uuid4()
INVOICE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CUSTOMER_ID = "11111111-2222-3333-4444-555555555555"


def _credit_note_call(**extra: Any) -> ToolCall:
    """The natural-language shape: customer + invoice NUMBER, no uuids."""
    args: Dict[str, Any] = {
        "customer_name": "Hgf Engineering Ltd",
        "invoice_number": "INV-000011",
        "items": [
            {"description": "Returned widget", "quantity": 1, "unit_price": 100.0}
        ],
        "reason": "goods returned",
    }
    args.update(extra)
    return ToolCall(tool_name="create_credit_note", arguments=args)


def _stub_invoice_lookup(monkeypatch, by_number: Dict[str, Any]) -> None:
    from app.repositories import invoice_repository

    async def _fake(organization_id, *, invoice_number: str):
        # Tenant isolation is part of the contract: every lookup is org-scoped.
        assert str(organization_id) == str(ORG), "lookup escaped the tenant"
        return by_number.get(invoice_number)

    monkeypatch.setattr(invoice_repository, "get_invoice_by_number", _fake)


def _stub_customer_search(monkeypatch, rows_by_query: Dict[str, Any]) -> None:
    from app.services import customer_service

    async def _search(organization_id, *, query: str, limit: int = 25):
        assert str(organization_id) == str(ORG), "lookup escaped the tenant"
        return rows_by_query.get(query, [])

    monkeypatch.setattr(customer_service, "search", _search)


def test_the_declaration_mirrors_the_receipt_pattern() -> None:
    """Invariant 1: the alias vocabulary is exactly the receipt's."""
    specs = DECLARED_REFERENCES["create_credit_note"]

    invoice = specs["invoice_id"]
    assert invoice.parameter == "invoice_id"
    assert invoice.role == "invoice"          # resolves via get_invoice_by_number
    assert invoice.aliases == ("invoice_number",)
    # required=True means "IF a number is given it must resolve" — an absent
    # number is never resolved and never asked about (service: optional).
    assert invoice.required is True

    customer = specs["customer_id"]
    assert customer.role == "customer"
    assert customer.aliases == ("customer_name", "party_name")

    declared = declared_reference_inputs()["create_credit_note"]
    assert declared["invoice_id"] == ("invoice_number",)
    assert declared["customer_id"] == ("customer_name", "party_name")


@pytest.mark.asyncio
async def test_a_spoken_invoice_number_resolves_to_the_invoice_id(
    monkeypatch,
) -> None:
    """Invariant 2: one exact org-scoped match -> canonical ids, plan intact."""
    _stub_invoice_lookup(
        monkeypatch,
        {"INV-000011": {"id": INVOICE_ID, "invoice_number": "INV-000011"}},
    )
    _stub_customer_search(
        monkeypatch,
        {"Hgf Engineering Ltd": [{"id": CUSTOMER_ID, "name": "Hgf Engineering Ltd"}]},
    )
    call = _credit_note_call()

    result = await prepare_plan(organization_id=ORG, calls=[call])

    assert not result.blocked, result.blocks
    args = result.calls[0].arguments
    assert args["invoice_id"] == INVOICE_ID
    assert "invoice_number" not in args      # the alias was consumed
    assert args["customer_id"] == CUSTOMER_ID
    assert "customer_name" not in args

    # The approved human-level plan is never mutated (audit invariant).
    assert call.arguments["invoice_number"] == "INV-000011"
    assert "invoice_id" not in call.arguments
    assert "customer_id" not in call.arguments

    # The decision is recorded for the durable audit trail.
    by_parameter = {d.parameter: d for d in result.decisions}
    assert by_parameter["invoice_id"].resolved_id == INVOICE_ID
    assert by_parameter["customer_id"].resolved_id == CUSTOMER_ID


@pytest.mark.asyncio
async def test_an_unresolvable_number_blocks_and_never_invents(monkeypatch) -> None:
    """Invariant 3: unknown number -> question naming it; no id invented."""
    _stub_invoice_lookup(monkeypatch, {})  # the books have no such invoice
    _stub_customer_search(
        monkeypatch,
        {"Hgf Engineering Ltd": [{"id": CUSTOMER_ID, "name": "Hgf Engineering Ltd"}]},
    )

    result = await prepare_plan(organization_id=ORG, calls=[_credit_note_call()])

    assert result.blocked
    assert any("INV-000011" in block for block in result.blocks), result.blocks
    args = result.calls[0].arguments
    assert "invoice_id" not in args  # never invented
    # customer still resolved — one blocked reference does not undo the others
    assert args["customer_id"] == CUSTOMER_ID


@pytest.mark.asyncio
async def test_an_absent_number_stays_unanchored_without_a_question(
    monkeypatch,
) -> None:
    """Invariant 4: invoice_id is optional — nothing asked when nothing given."""
    _stub_invoice_lookup(
        monkeypatch,
        {"INV-000011": {"id": INVOICE_ID, "invoice_number": "INV-000011"}},
    )
    _stub_customer_search(
        monkeypatch,
        {"Hgf Engineering Ltd": [{"id": CUSTOMER_ID, "name": "Hgf Engineering Ltd"}]},
    )
    call = _credit_note_call()
    del call.arguments["invoice_number"]

    result = await prepare_plan(organization_id=ORG, calls=[call])

    assert not result.blocked, result.blocks
    args = result.calls[0].arguments
    assert "invoice_id" not in args  # unanchored, as the service allows
    assert all(d.parameter != "invoice_id" for d in result.decisions)


def test_the_registered_contract_advertises_and_accepts_the_alias() -> None:
    """Invariant 5: signature-derived contract + gate accept the declared alias."""
    from app.tool_contract import validate_arguments
    from app.tools import tool_contracts

    contract = tool_contracts().get("create_credit_note")
    assert contract, (
        "the receipt pattern includes the signature-derived contract — without "
        "it the reasoning prompt never advertises the alias (receipt 3ea794a0)"
    )
    reference_inputs = declared_reference_inputs()["create_credit_note"]
    # The natural phrasing passes the pre-approval gate via the declared alias.
    violations = validate_arguments(
        "create_credit_note",
        {"invoice_number": "INV-000011", "items": [], "reason": "goods returned"},
        contract,
        reference_inputs,
    )
    assert violations == [], violations


def test_the_prompt_advertises_the_alias_pair() -> None:
    """Invariant 5: the contract-primed prompt names the executable spelling."""
    from app.accounting_reasoning import _render_tool_contracts_block
    from app.tools import tool_contracts

    lines = _render_tool_contracts_block(
        ["create_credit_note"], tool_contracts()
    )
    joined = "\n".join(lines)
    assert "create_credit_note" in joined
    assert "invoice_number->invoice_id" in joined, joined
    assert "customer_name->customer_id" in joined, joined


def test_the_evidence_path_resolves_the_customer_with_zero_queries() -> None:
    """Invariant 6: P1-5 consumes the new customer spec before approval."""
    from app.agent import _resolve_declared_aliases_from_evidence

    evidence = SimpleNamespace(
        error=None,
        kind="parties",
        records=[
            {"role": "customer", "id": CUSTOMER_ID, "name": "Hgf Engineering Ltd"},
            {"role": "supplier", "id": str(uuid.uuid4()), "name": "Other Ltd"},
        ],
    )
    call = _credit_note_call()

    replacements = _resolve_declared_aliases_from_evidence([call], [evidence])

    assert replacements, "the customer alias should resolve from turn evidence"
    assert call.arguments["customer_id"] == CUSTOMER_ID
    assert "customer_name" not in call.arguments
