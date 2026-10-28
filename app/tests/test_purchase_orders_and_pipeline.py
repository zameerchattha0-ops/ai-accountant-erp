"""
Unit tests for:
1. Multi-State Inventory Pipeline (On-Hand, Inbound In-Flight, Reserved, Consignment, Available)
2. Dedicated Purchase Order (PO/RFQ) lifecycle: RFQ -> ORDERED -> RECEIVED -> BILLED
3. Conversational Universal Status Updates (Single & Bulk) across all modules
"""

from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.services import purchase_order_service, inventory_service
from app.tools.document_status_tools import update_document_status


@pytest.mark.asyncio
async def test_create_and_transition_purchase_order():
    org_id = uuid.uuid4()
    supplier_id = uuid.uuid4()
    order_id = uuid.uuid4()
    prod_id = uuid.uuid4()

    mock_order = {
        "id": str(order_id),
        "organization_id": str(org_id),
        "po_number": "RFQ-000001",
        "supplier_id": str(supplier_id),
        "status": "RFQ",
        "order_date": "2026-10-28",
        "total": 50000.0,
        "items": [
            {
                "product_id": str(prod_id),
                "description": "Office Chairs",
                "quantity": 5.0,
                "unit_price": 10000.0,
                "tax_amount": 0.0,
                "line_total": 50000.0,
            }
        ],
    }

    with patch("app.services.supplier_service.get", new=AsyncMock(return_value={"id": str(supplier_id), "name": "Apex Supplies"})), \
         patch("app.repositories.purchase_order_repository.create_purchase_order", new=AsyncMock(return_value=mock_order)), \
         patch("app.repositories.purchase_order_repository.get_purchase_order", new=AsyncMock(return_value=mock_order)), \
         patch("app.repositories.purchase_order_repository.get_purchase_order_items", new=AsyncMock(return_value=mock_order["items"])), \
         patch("app.repositories.purchase_order_repository.update_purchase_order_status", new=AsyncMock(return_value={"status": "ORDERED"})), \
         patch("app.services.inventory_service.receive_stock", new=AsyncMock(return_value={"id": str(uuid.uuid4())})):

        # 1. Create RFQ
        created = await purchase_order_service.create_order(
            organization_id=org_id,
            supplier_id=supplier_id,
            items=mock_order["items"],
            status="RFQ",
        )
        assert created["status"] == "RFQ"
        assert created["po_number"] == "RFQ-000001"

        # 2. Transition RFQ -> ORDERED (Vendor Confirmed PO)
        ordered = await purchase_order_service.transition_order_status(
            organization_id=org_id,
            order_id=order_id,
            new_status="ORDERED",
        )
        assert ordered is not None

        # 3. Transition ORDERED -> RECEIVED (GRN - Goods Arrived in Warehouse)
        mock_order["status"] = "ORDERED"
        received = await purchase_order_service.transition_order_status(
            organization_id=org_id,
            order_id=order_id,
            new_status="RECEIVED",
            auto_receive_stock=True,
        )
        assert received is not None


@pytest.mark.asyncio
async def test_stock_pipeline_segregation():
    org_id = uuid.uuid4()
    p1 = str(uuid.uuid4())

    mock_tracing = {
        p1: {
            "opening_quantity": 2.0,
            "purchased_quantity": 8.0,
            "sold_quantity": 2.0,
            "closing_quantity": 8.0,  # Q_on_hand
            "average_cost": 5000.0,
            "valuation": 40000.0,
        }
    }

    mock_po_rows = [{"id": "po1", "status": "ORDERED"}]
    mock_po_items = [{"purchase_order_id": "po1", "product_id": p1, "quantity": 10.0}]
    mock_quotations = [{"id": "qtn1", "status": "ACCEPTED"}]
    mock_quotation_items = [{"quotation_id": "qtn1", "product_id": p1, "quantity": 3.0}]
    mock_movements = [
        {"product_id": p1, "quantity": 2.0, "direction": "ISSUE", "source_type": "consignment"}
    ]

    async def side_effect(table, **kw):
        if table == "purchase_orders":
            return mock_po_rows
        elif table == "purchase_order_items":
            return mock_po_items
        elif table == "quotations":
            return mock_quotations
        elif table == "quotation_items":
            return mock_quotation_items
        elif table == "inventory_movements":
            return mock_movements
        return []

    with patch("app.services.inventory_service.get_product_unit_tracing", new=AsyncMock(return_value=mock_tracing)), \
         patch("app.services.inventory_service.fetch_many", new=AsyncMock(side_effect=side_effect)):

        pipeline = await inventory_service.get_stock_pipeline(org_id)
        assert p1 in pipeline
        metrics = pipeline[p1]
        assert metrics["qty_on_hand"] == 8.0
        assert metrics["qty_inbound_transit"] == 10.0
        assert metrics["qty_reserved"] == 3.0
        assert metrics["qty_customer_premises"] == 2.0
        # Q_available = max(0, Q_on_hand - Q_reserved) = 8.0 - 3.0 = 5.0
        assert metrics["qty_available"] == 5.0


@pytest.mark.asyncio
async def test_universal_document_status_update_bulk():
    org_id = uuid.uuid4()
    bill1_id = uuid.uuid4()
    bill2_id = uuid.uuid4()

    mock_bills = [
        {"id": str(bill1_id), "bill_number": "PUR-000014", "status": "OPEN", "total": 50000.0},
        {"id": str(bill2_id), "bill_number": "PUR-000015", "status": "OPEN", "total": 85000.0},
    ]

    with patch("app.tools.document_status_tools.fetch_many", new=AsyncMock(side_effect=lambda t, **kw: [mock_bills[0]] if "14" in str(kw.get("filters", {}).get("bill_number", "")) else [mock_bills[1]])), \
         patch("app.tools.document_status_tools.update_one", new=AsyncMock(return_value={"id": "mock"})), \
         patch("app.tools.document_status_tools._resolve_party_name", new=AsyncMock(return_value="Al-Rehman Traders")):

        res = await update_document_status(
            org_id,
            document_type="purchase_bill",
            target_status="PAID",
            reference_numbers=["PUR-000014", "15"],
        )

        assert res.success is True
        assert res.data["updated_count"] == 2
        assert res.data["target_status"] == "PAID"
        assert len(res.data["documents"]) == 2
        assert "Successfully updated 2 bills to status **PAID**" in res.data["summary"]
        assert "PUR-000014" in res.data["summary"]
        assert "PUR-000015" in res.data["summary"]
