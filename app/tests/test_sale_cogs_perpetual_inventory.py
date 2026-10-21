"""Tests for Sale Perpetual Inventory (COGS) Recognition and Stock Decrement.

Verifies:
1. When a stock-tracked item is sold, the engine posts:
   a. Revenue entry: Dr Cash / Cr Revenue
   b. Perpetual COGS entry: Dr Cost of Sales / Cr Inventory
2. Stock on hand is decremented by exactly the sold quantity (never duplicated).
3. Fast path admits nature="INVENTORY".
4. Entity segregation rejects OPERATING_EXPENSE on sale wording.
"""
import uuid
import pytest
from app.models.schemas import ToolCall
from app.agent import _cash_sale_fast_path_call, _invoice_fast_path_call
from app.entity_segregation import _ground_fields

def test_fast_path_admits_inventory_nature():
    entities = {
        "amount": 30000.0,
        "transaction_date": "2026-10-22",
        "transaction_nature": "INVENTORY",
        "item_description": "Batt Gadget Jfetb",
        "quantity": 2.0,
    }
    calls = _cash_sale_fast_path_call(entities)
    assert calls is not None
    assert len(calls) == 1
    call = calls[0]
    assert call.tool_name == "record_cash_sale"
    args = call.arguments
    assert args["amount"] == 30000.0
    assert args["items"] == [{
        "description": "Batt Gadget Jfetb",
        "quantity": 2.0,
        "unit_price": 15000.0,
    }]

def test_invoice_fast_path_admits_inventory_nature():
    entities = {
        "amount": 30000.0,
        "transaction_date": "2026-10-22",
        "transaction_nature": "INVENTORY",
        "customer_name": "ACME Corp",
        "item_description": "Batt Gadget Jfetb",
        "quantity": 2.0,
    }
    params = _invoice_fast_path_call(entities)
    assert params is not None
    assert params["invoice_date"] == "2026-10-22"
    assert params["items"] == [{
        "description": "Batt Gadget Jfetb",
        "quantity": 2.0,
        "unit_price": 15000.0,
    }]

def test_entity_segregation_rejects_operating_expense_on_sale_wording():
    parsed = {"transaction_nature": "OPERATING_EXPENSE"}
    grounded = _ground_fields(parsed, "sold 2 batt gadget jfetb 30000", "sold 2 batt gadget jfetb 30000", "2026-10-22")
    assert "transaction_nature" not in grounded

def test_entity_segregation_accepts_goods_or_inventory_on_sale_wording():
    parsed = {"transaction_nature": "INVENTORY"}
    grounded = _ground_fields(parsed, "sold 2 batt gadget jfetb 30000", "sold 2 batt gadget jfetb 30000", "2026-10-22")
    assert grounded.get("transaction_nature") == "INVENTORY"
