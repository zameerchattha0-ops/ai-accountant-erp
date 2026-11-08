"""
Tests for Bank Account Prerequisite Resolution:
When a user specifies payment/receipt via BANK (e.g. Turn 2 clarification '1) BANK 2) TODAY'
or direct prompt), but the organization has 0 bank accounts configured:
The system must NOT crash with 'No bank account specified and no default bank account configured'.
It must resolve the prerequisite by ensuring/creating a linked bank account and executing smoothly.
"""

from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.accounting_engine import ensure_bank_account
from app.services import payment_service


@pytest.mark.asyncio
async def test_ensure_bank_account_returns_existing_default():
    org_id = uuid.uuid4()
    gl_id = uuid.uuid4()
    mock_default = {
        "id": str(uuid.uuid4()),
        "organization_id": str(org_id),
        "account_name": "Meezan Bank - Main",
        "gl_account_id": str(gl_id),
        "is_default": True,
        "is_active": True,
    }

    with patch("app.repositories.bank_repository.get_default_bank_account", new=AsyncMock(return_value=mock_default)):
        result = await ensure_bank_account(org_id)
        assert result is not None
        assert result["gl_account_id"] == str(gl_id)
        assert result["account_name"] == "Meezan Bank - Main"


@pytest.mark.asyncio
async def test_ensure_bank_account_creates_prerequisite_when_none_exists():
    org_id = uuid.uuid4()
    gl_id = uuid.uuid4()
    mock_gl_account = {
        "id": str(gl_id),
        "code": "1010",
        "name": "Bank",
        "account_type": "ASSET",
        "is_active": True,
    }
    mock_created_bank = {
        "id": str(uuid.uuid4()),
        "organization_id": str(org_id),
        "account_name": "Primary Bank - Main",
        "bank_name": "Primary Bank",
        "gl_account_id": str(gl_id),
        "is_default": True,
        "is_active": True,
    }

    with patch("app.repositories.bank_repository.get_default_bank_account", new=AsyncMock(return_value=None)), \
         patch("app.repositories.bank_repository.list_bank_accounts", new=AsyncMock(return_value=[])), \
         patch("app.accounting_engine._resolve_named_postable_account", new=AsyncMock(return_value=mock_gl_account)), \
         patch("app.repositories.bank_repository.create_bank_account", new=AsyncMock(return_value=mock_created_bank)):

        result = await ensure_bank_account(org_id, bank_name="Primary Bank")
        assert result is not None
        assert result["gl_account_id"] == str(gl_id)
        assert result["bank_account_created"] is True


@pytest.mark.asyncio
async def test_resolve_bank_gl_account_prerequisite_self_heal():
    """Verify that _resolve_bank_gl_account uses ensure_bank_account rather than failing closed."""
    org_id = uuid.uuid4()
    gl_id = uuid.uuid4()

    mock_ensured = {
        "id": str(uuid.uuid4()),
        "gl_account_id": str(gl_id),
        "account_name": "Primary Bank - Main",
    }

    with patch("app.repositories.bank_repository.get_default_bank_account", new=AsyncMock(return_value=None)), \
         patch("app.repositories.bank_repository.list_bank_accounts", new=AsyncMock(return_value=[])), \
         patch("app.accounting_engine.ensure_bank_account", new=AsyncMock(return_value=mock_ensured)):

        resolved_gl = await payment_service._resolve_bank_gl_account(org_id, bank_account_id=None)
        assert resolved_gl == gl_id


@pytest.mark.asyncio
async def test_supplier_payment_with_bank_resolves_prerequisite():
    """End-to-end test of record_supplier_payment with BANK_TRANSFER when zero bank accounts exist."""
    org_id = uuid.uuid4()
    supplier_id = uuid.uuid4()
    bill_id = uuid.uuid4()
    bank_gl_id = uuid.uuid4()
    ap_gl_id = uuid.uuid4()

    mock_ensured = {
        "id": str(uuid.uuid4()),
        "gl_account_id": str(bank_gl_id),
        "account_name": "Primary Bank - Main",
    }

    mock_bill = {
        "id": str(bill_id),
        "organization_id": str(org_id),
        "supplier_id": str(supplier_id),
        "bill_number": "PUR-000012",
        "total": 90000.0,
        "amount_paid": 0.0,
        "status": "OPEN",
    }

    mock_rpc_outcome = {
        "payment": {
            "id": str(uuid.uuid4()),
            "organization_id": str(org_id),
            "amount": 90000.0,
            "payment_method": "BANK_TRANSFER",
        },
        "journal_entry_id": str(uuid.uuid4()),
    }

    with patch("app.repositories.bank_repository.get_default_bank_account", new=AsyncMock(return_value=None)), \
         patch("app.repositories.bank_repository.list_bank_accounts", new=AsyncMock(return_value=[])), \
         patch("app.accounting_engine.ensure_bank_account", new=AsyncMock(return_value=mock_ensured)), \
         patch("app.services.payment_service._resolve_payment_debit_account", new=AsyncMock(return_value=(ap_gl_id, None))), \
         patch("app.services.payment_service.call_rpc", new=AsyncMock(return_value=mock_rpc_outcome)), \
         patch("app.services.accounting_service.validate_journal", new=AsyncMock()), \
         patch("app.services.accounting_service.post_journal", new=AsyncMock()), \
         patch("app.repositories.purchase_repository.get_purchase_bill", new=AsyncMock(return_value=mock_bill)), \
         patch("app.repositories.payment_repository.create_payment_allocation", new=AsyncMock(return_value={"id": "alloc"})), \
         patch("app.services.payment_service._update_bill_paid", new=AsyncMock()):

        res = await payment_service.record_supplier_payment(
            organization_id=org_id,
            supplier_id=supplier_id,
            bill_id=bill_id,
            amount=90000.0,
            payment_method="BANK_TRANSFER",
        )

        assert res["amount"] == 90000.0
        assert res["payment_method"] == "BANK_TRANSFER"


@pytest.mark.asyncio
async def test_record_supplier_payment_rejects_already_paid_bill():
    """Verify duplicate payment protection: paying an already-settled bill raises ValueError."""
    org_id = uuid.uuid4()
    supplier_id = uuid.uuid4()
    bill_id = uuid.uuid4()

    mock_paid_bill = {
        "id": str(bill_id),
        "organization_id": str(org_id),
        "supplier_id": str(supplier_id),
        "bill_number": "PUR-000005",
        "total": 200000.0,
        "amount_paid": 200000.0,
        "status": "PAID",
    }

    with patch("app.repositories.purchase_repository.get_purchase_bill", new=AsyncMock(return_value=mock_paid_bill)):
        with pytest.raises(ValueError, match="already fully settled"):
            await payment_service.record_supplier_payment(
                organization_id=org_id,
                supplier_id=supplier_id,
                bill_id=bill_id,
                amount=200000.0,
                payment_method="CASH",
            )


@pytest.mark.asyncio
async def test_record_customer_receipt_rejects_already_paid_invoice():
    """Verify duplicate receipt protection: collecting on an already-settled invoice raises ValueError."""
    org_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    invoice_id = uuid.uuid4()

    mock_paid_inv = {
        "id": str(invoice_id),
        "organization_id": str(org_id),
        "customer_id": str(customer_id),
        "invoice_number": "INV-000006",
        "total": 450000.0,
        "amount_paid": 450000.0,
        "status": "PAID",
    }

    with patch("app.repositories.invoice_repository.get_invoice", new=AsyncMock(return_value=mock_paid_inv)):
        with pytest.raises(ValueError, match="already fully settled"):
            await payment_service.record_customer_receipt(
                organization_id=org_id,
                customer_id=customer_id,
                invoice_id=invoice_id,
                amount=450000.0,
                payment_method="CASH",
            )


def test_conversation_harness_flags_already_paid_bill():
    """Verify that conversation harness detects already-paid bills and prepares an audit warning card."""
    from app.conversation_harness import (
        DisambiguationContext,
        DocumentCandidate,
        evaluate_disambiguation_need,
        build_detailed_disambiguation_card,
    )

    doc = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="PUR-000005",
        doc_date="2026-10-17",
        due_date=None,
        party_id=uuid.uuid4(),
        party_name="Delta Pvt",
        total=200000.0,
        amount_paid=200000.0,
        balance_due=0.0,
        status="PAID",
    )

    ctx = DisambiguationContext(matching_bills=[doc], extracted_number="5")
    is_amb, reason, candidates = evaluate_disambiguation_need(ctx, "Paid in full the bill no. 5 today")

    assert is_amb is True
    assert reason == "bill_already_paid"
    assert len(candidates) == 1
    assert candidates[0].number == "PUR-000005"

    card_text, options = build_detailed_disambiguation_card(candidates, reason=reason)
    assert "Already Paid in Full" in card_text
    assert "PUR-000005" in card_text
    assert any(opt["value"] == "cancel" for opt in options)


@pytest.mark.asyncio
async def test_record_supplier_payment_tool_auto_links_open_bill_and_rejects_duplicate():
    """Verify tool _record_supplier_payment auto-links open bills and rejects paying suppliers with only settled bills."""
    from app.tools import _record_supplier_payment

    org_id = uuid.uuid4()
    supplier_id = uuid.uuid4()
    bill_id = uuid.uuid4()

    mock_open_bill = {
        "id": str(bill_id),
        "organization_id": str(org_id),
        "supplier_id": str(supplier_id),
        "bill_number": "PUR-000012",
        "total": 90000.0,
        "amount_paid": 0.0,
        "status": "OPEN",
    }

    # Case 1: Open bill exists matching amount -> auto-links
    with patch("app.services.supplier_service.search", new=AsyncMock(return_value=[{"id": str(supplier_id), "name": "Alpha Traders"}])), \
         patch("app.database.fetch_many", new=AsyncMock(return_value=[mock_open_bill])), \
         patch("app.services.payment_service.record_supplier_payment", new=AsyncMock(return_value={"id": "pmt1", "amount": 90000.0})) as mock_rec:

        res = await _record_supplier_payment(
            organization_id=org_id,
            supplier_name="Alpha Traders",
            amount=90000.0,
            payment_mode="BANK",
        )
        assert res.success is True
        # Verify bill_id was auto-linked in the call
        called_kw = mock_rec.call_args.kwargs
        assert called_kw.get("bill_id") == bill_id

    # Case 2: Only paid bill exists -> rejects duplicate payment to protect GL
    mock_paid_bill = {
        "id": str(bill_id),
        "organization_id": str(org_id),
        "supplier_id": str(supplier_id),
        "bill_number": "PUR-000005",
        "total": 200000.0,
        "amount_paid": 200000.0,
        "status": "PAID",
    }
    with patch("app.services.supplier_service.search", new=AsyncMock(return_value=[{"id": str(supplier_id), "name": "DElta Pvt"}])), \
         patch("app.database.fetch_many", new=AsyncMock(return_value=[mock_paid_bill])):

        res = await _record_supplier_payment(
            organization_id=org_id,
            supplier_name="DElta Pvt",
            amount=200000.0,
            payment_mode="CASH",
        )
        assert res.success is False
        assert "no outstanding open bills" in res.error
        assert "PUR-000005" in res.error
        assert "already fully settled in your books" in res.error


@pytest.mark.asyncio
async def test_resolve_open_document_reference_catches_already_paid_bill_id():
    """Verify _resolve_open_document_reference detects already-settled bills even if bill_id was already extracted."""
    from app.agent import _resolve_open_document_reference

    org_id = uuid.uuid4()
    bill_id = uuid.uuid4()
    sup_id = uuid.uuid4()

    mock_paid_bill = {
        "id": str(bill_id),
        "organization_id": str(org_id),
        "supplier_id": str(sup_id),
        "bill_number": "PUR-000005",
        "total": 200000.0,
        "amount_paid": 200000.0,
        "status": "PAID",
    }

    entities = {
        "user_message": "PAID BILL 5 IN FULL",
        "bill_id": str(bill_id),
        "supplier_name": "DElta Pvt",
    }

    with patch("app.repositories.purchase_repository.get_purchase_bill", new=AsyncMock(return_value=mock_paid_bill)):
        await _resolve_open_document_reference(org_id, entities)
        assert entities.get("requires_disambiguation") is True
        assert entities.get("disambiguation_reason") == "bill_already_paid"
        assert "PUR-000005" in entities.get("disambiguation_question", "")


