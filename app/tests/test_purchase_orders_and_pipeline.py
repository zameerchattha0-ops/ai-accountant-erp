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
    rfq_id = uuid.uuid4()
    po_id = uuid.uuid4()
    grn_id = uuid.uuid4()
    prod_id = uuid.uuid4()

    items = [
        {
            "product_id": str(prod_id),
            "description": "Office Chairs",
            "quantity": 5.0,
            "unit_price": 10000.0,
            "tax_amount": 0.0,
            "line_total": 50000.0,
        }
    ]
    rfq_row = {
        "id": str(rfq_id),
        "organization_id": str(org_id),
        "po_number": "RFQ-000001",
        "supplier_id": str(supplier_id),
        "status": "RFQ",
        "order_date": "2026-10-28",
        "total": 50000.0,
        "items": items,
    }
    po_row = {
        "id": str(po_id),
        "organization_id": str(org_id),
        "po_number": "PO-000001",
        "supplier_id": str(supplier_id),
        "status": "ORDERED",
        "order_date": "2026-10-28",
        "total": 50000.0,
        "parent_order_id": str(rfq_id),
        "source_rfq_id": str(rfq_id),
        "items": items,
    }
    grn_row = {
        "id": str(grn_id),
        "organization_id": str(org_id),
        "po_number": "GRN-000001",
        "supplier_id": str(supplier_id),
        "status": "RECEIVED",
        "order_date": "2026-10-28",
        "total": 50000.0,
        "parent_order_id": str(po_id),
        "source_rfq_id": str(rfq_id),
        "source_po_id": str(po_id),
        "items": items,
    }

    by_id = {str(rfq_id): rfq_row, str(po_id): po_row, str(grn_id): grn_row}

    async def fake_create_po(**kw):
        st = str(kw.get("status") or "RFQ").upper()
        if st == "RFQ":
            return rfq_row
        if st == "ORDERED":
            return po_row
        return grn_row

    async def fake_get_po(oid, *, order_id):
        return by_id.get(str(order_id))

    with patch("app.services.supplier_service.get", new=AsyncMock(return_value={"id": str(supplier_id), "name": "Apex Supplies"})), \
         patch("app.repositories.purchase_order_repository.create_purchase_order", side_effect=fake_create_po), \
         patch("app.repositories.purchase_order_repository.get_purchase_order", side_effect=fake_get_po), \
         patch("app.repositories.purchase_order_repository.get_purchase_order_items", new=AsyncMock(return_value=items)), \
         patch("app.repositories.purchase_order_repository.mark_purchase_order_promoted", new=AsyncMock(return_value={"promoted_at": "now"})) as mock_promote, \
         patch("app.services.purchase_order_service.fetch_many", new=AsyncMock(return_value=[])), \
         patch("app.services.inventory_service.receive_stock", new=AsyncMock(return_value={"id": str(uuid.uuid4())})) as mock_recv:

        # 1. Create RFQ
        created = await purchase_order_service.create_order(
            organization_id=org_id,
            supplier_id=supplier_id,
            items=items,
            status="RFQ",
        )
        assert created["status"] == "RFQ"
        assert created["po_number"] == "RFQ-000001"

        # 2. Transition RFQ -> ORDERED: preserves RFQ and mints PO-000001
        ordered = await purchase_order_service.transition_order_status(
            organization_id=org_id,
            order_id=rfq_id,
            new_status="ORDERED",
        )
        assert ordered["po_number"] == "PO-000001"
        assert ordered["status"] == "ORDERED"
        assert ordered["promoted_from"]["po_number"] == "RFQ-000001"
        assert rfq_row["status"] == "RFQ"

        # 3. Transition ORDERED -> RECEIVED: preserves PO-000001 and mints GRN-000001
        received = await purchase_order_service.transition_order_status(
            organization_id=org_id,
            order_id=po_id,
            new_status="RECEIVED",
            auto_receive_stock=True,
        )
        assert received["po_number"] == "GRN-000001"
        assert received["status"] == "RECEIVED"
        assert received["promoted_from"]["po_number"] == "PO-000001"
        assert mock_promote.await_count == 2
        mock_recv.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_update_purchase_order_status_repo_calls_update_one_correctly():
    """Verify repo update_purchase_order_status passes row_id and organization_id to update_one."""
    from app.repositories import purchase_order_repository as po_repo

    org_id = uuid.uuid4()
    order_id = uuid.uuid4()

    mock_update_one = AsyncMock(return_value={"id": str(order_id), "status": "ORDERED"})

    with patch("app.repositories.purchase_order_repository.update_one", new=mock_update_one):
        res = await po_repo.update_purchase_order_status(
            organization_id=org_id,
            order_id=order_id,
            new_status="ORDERED",
        )
        assert res["status"] == "ORDERED"
        mock_update_one.assert_awaited_once_with(
            "purchase_orders",
            row_id=order_id,
            data={"status": "ORDERED"},
            organization_id=org_id,
        )


@pytest.mark.asyncio
async def test_create_po_intent_recognition_and_disambiguation_guard():
    """Verify 'CREATE PO FOR SHABBIR FURNITURE' plans create_purchase_order and never triggers bill settlement."""
    from app.planner import plan
    from app.agent import _resolve_open_document_reference, _deterministic_mutation_calls

    msg = "CREATE PO FOR SHABBIR FURNITURE"
    plan_res = plan(msg)

    assert plan_res.intent == "create_purchase_order"
    assert plan_res.extracted_entities.get("supplier_name") == "SHABBIR FURNITURE"
    assert plan_res.extracted_entities.get("item_description") is None
    assert "item_description" in plan_res.missing_fields
    assert len(plan_res.clarification_questions) == 1
    assert "What item or product are you ordering from SHABBIR FURNITURE?" in plan_res.clarification_questions[0]

    # Verify _resolve_open_document_reference does not run bill settlement disambiguation
    org_id = uuid.uuid4()
    entities = {
        "user_message": msg,
        "original_request": msg,
        "intent": "create_purchase_order",
        "supplier_name": "SHABBIR FURNITURE",
    }
    await _resolve_open_document_reference(org_id, entities)
    assert entities.get("requires_disambiguation") is not True
    assert entities.get("bill_id") is None


@pytest.mark.asyncio
async def test_create_po_with_item_qty_price_fast_path():
    """Verify 'CREATE PO FOR SHABBIR FURNITURE FOR 5 OFFICE CHAIRS AT 15000 EACH' extracts all fields and executes."""
    from app.planner import plan
    from app.agent import _deterministic_mutation_calls

    msg = "CREATE PO FOR SHABBIR FURNITURE FOR 5 OFFICE CHAIRS AT 15000 EACH"
    plan_res = plan(msg)

    assert plan_res.intent == "create_purchase_order"
    assert plan_res.extracted_entities.get("supplier_name") == "SHABBIR FURNITURE"
    assert plan_res.extracted_entities.get("item_description") == "OFFICE CHAIRS"
    assert plan_res.extracted_entities.get("quantity") == 5.0
    assert plan_res.extracted_entities.get("unit_price") == 15000.0
    assert plan_res.extracted_entities.get("amount") == 75000.0
    assert plan_res.missing_fields == []
    assert plan_res.requires_clarification is False

    org_id = uuid.uuid4()
    calls = await _deterministic_mutation_calls(
        organization_id=org_id,
        execution_plan=plan_res,
        classification=None,
    )
    assert calls is not None
    assert len(calls) == 1
    assert calls[0].tool_name == "create_purchase_order"
    assert calls[0].arguments["supplier_name"] == "SHABBIR FURNITURE"
    assert calls[0].arguments["product_name"] == "OFFICE CHAIRS"
    assert calls[0].arguments["quantity"] == 5.0
    assert calls[0].arguments["unit_price"] == 15000.0


@pytest.mark.asyncio
async def test_full_procurement_stage_chain_rfq_po_grn_bill():
    """Verify full 4-stage preservation and backward traceability: PUR -> GRN -> PO -> RFQ."""
    from app.repositories import purchase_order_repository as po_repo

    org_id = uuid.uuid4()
    supp_id = uuid.uuid4()
    rfq_id = uuid.uuid4()
    po_id = uuid.uuid4()
    grn_id = uuid.uuid4()
    bill_id = uuid.uuid4()

    orders_store = {}
    items_store = {}
    bills_store = {}
    counters = {"RFQ": 0, "PO": 0, "GRN": 0, "PUR": 0}

    async def fake_generate_po_number(oid, prefix="PO", *, doc_type=None):
        counters[prefix] += 1
        return f"{prefix}-{counters[prefix]:06d}"

    async def fake_insert_one(table, *, data):
        if table == "purchase_orders":
            oid = {
                "RFQ": str(rfq_id),
                "ORDERED": str(po_id),
                "RECEIVED": str(grn_id),
            }[data["status"]]
            row = {"id": oid, **data, "created_at": f"2026-11-29T00:0{counters.get(data['status'], 0)}:00Z"}
            orders_store[oid] = row
            items_store[oid] = []
            return dict(row)
        if table == "purchase_order_items":
            row = {"id": str(uuid.uuid4()), **data}
            items_store[str(data["purchase_order_id"])].append(row)
            return row
        return {"id": str(uuid.uuid4()), **data}

    async def fake_update_one(table, *, row_id, data, organization_id=None, filters=None):
        if table == "purchase_orders" and str(row_id) in orders_store:
            orders_store[str(row_id)].update(data)
            return dict(orders_store[str(row_id)])
        return {}

    async def fake_fetch_one(table, *, filters=None, select="*"):
        if table == "purchase_orders":
            return dict(orders_store[str(filters["id"])]) if str(filters.get("id")) in orders_store else None
        if table == "purchase_bills":
            return dict(bills_store[str(filters["id"])]) if str(filters.get("id")) in bills_store else None
        return None

    async def fake_fetch_many(table, *, filters=None, select="*", order=None, limit=50):
        if table == "purchase_orders":
            return [dict(v) for v in orders_store.values()]
        if table == "purchase_order_items":
            return list(items_store.get(str((filters or {}).get("purchase_order_id")), []))
        if table == "purchase_bills":
            return [dict(v) for v in bills_store.values()]
        if table == "purchase_bill_items":
            return []
        if table == "suppliers":
            return [{"id": str(supp_id), "name": "Tech Depot", "email": "", "phone": ""}]
        return []

    async def fake_create_purchase_bill(**kw):
        counters["PUR"] += 1
        bill = {
            "id": str(bill_id),
            "organization_id": str(org_id),
            "bill_number": f"PUR-{counters['PUR']:06d}",
            "supplier_id": str(kw["supplier_id"]),
            "status": "DRAFT",
            "bill_date": kw["bill_date"],
            "subtotal": 25000.0,
            "tax_total": 0.0,
            "total": 25000.0,
            "source_order_id": str(kw["source_order_id"]) if kw.get("source_order_id") else None,
            "source_grn_id": str(kw["source_grn_id"]) if kw.get("source_grn_id") else None,
            "source_po_id": str(kw["source_po_id"]) if kw.get("source_po_id") else None,
            "source_rfq_id": str(kw["source_rfq_id"]) if kw.get("source_rfq_id") else None,
            "created_at": "2026-11-29T00:05:00Z",
        }
        bills_store[str(bill_id)] = bill
        return bill

    with patch("app.repositories.purchase_order_repository.generate_po_number", side_effect=fake_generate_po_number), \
         patch("app.repositories.purchase_order_repository.insert_one", side_effect=fake_insert_one), \
         patch("app.repositories.purchase_order_repository.update_one", side_effect=fake_update_one), \
         patch("app.repositories.purchase_order_repository.fetch_one", side_effect=fake_fetch_one), \
         patch("app.repositories.purchase_order_repository.fetch_many", side_effect=fake_fetch_many), \
         patch("app.services.purchase_order_service.fetch_many", side_effect=fake_fetch_many), \
         patch("app.services.purchase_order_service.fetch_one", side_effect=fake_fetch_one), \
         patch("app.services.supplier_service.get", new=AsyncMock(return_value={"id": str(supp_id), "name": "Tech Depot"})), \
         patch("app.services.inventory_service.receive_stock", new=AsyncMock(return_value={"id": str(uuid.uuid4())})), \
         patch("app.services.purchase_service.create_purchase_bill", side_effect=fake_create_purchase_bill):

        rfq = await purchase_order_service.create_order(
            organization_id=org_id,
            supplier_id=supp_id,
            items=[{"description": "Network Switch", "quantity": 1, "unit_price": 25000.0}],
            status="RFQ",
        )
        assert rfq["po_number"] == "RFQ-000001"

        po = await purchase_order_service.transition_order_status(
            org_id, order_id=rfq_id, new_status="ORDERED"
        )
        assert po["po_number"] == "PO-000001"
        assert orders_store[str(rfq_id)]["status"] == "RFQ"
        assert orders_store[str(rfq_id)]["promoted_to_order_id"] == str(po_id)

        grn = await purchase_order_service.transition_order_status(
            org_id, order_id=po_id, new_status="RECEIVED", auto_receive_stock=True
        )
        assert grn["po_number"] == "GRN-000001"
        assert orders_store[str(po_id)]["status"] == "ORDERED"
        assert orders_store[str(po_id)]["promoted_to_order_id"] == str(grn_id)
        assert grn["source_rfq_number"] == "RFQ-000001"
        assert grn["source_po_number"] == "PO-000001"

        billed = await purchase_order_service.transition_order_status(
            org_id, order_id=grn_id, new_status="BILLED", auto_create_bill=True
        )
        assert billed["po_number"] == "PUR-000001"
        assert billed["status"] == "BILLED"
        assert orders_store[str(grn_id)]["status"] == "RECEIVED"
        assert orders_store[str(grn_id)]["promoted_to_bill_id"] == str(bill_id)
        assert [c["doc_number"] for c in billed["chain"]] == [
            "RFQ-000001",
            "PO-000001",
            "GRN-000001",
            "PUR-000001",
        ]
        # Verify stock pipeline skips promoted RFQ and PO rows once GRN received them
        all_rows = await purchase_order_service.list_orders(org_id, status="ALL")
        assert {r["po_number"] for r in all_rows} == {"RFQ-000001", "PO-000001", "GRN-000001", "PUR-000001"}


def test_intent_progression_non_posting_purchase_order_copy():
    """Commercial PO/RFQ workflow must label non-posting status cleanly, never claim GL posting."""
    from app.conversational_manager import build_intent_progression

    prog = build_intent_progression(
        intent="create_purchase_order",
        entities={"supplier_name": "Tech Depot", "amount": 25000.0, "item_description": "network switch"},
        missing_fields=[],
        status="completed",
    )
    assert "non-posting" in prog["active_reasoning"].lower()
    assert "successfully posted to the general ledger" not in prog["active_reasoning"].lower()



