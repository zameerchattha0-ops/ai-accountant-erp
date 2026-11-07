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
