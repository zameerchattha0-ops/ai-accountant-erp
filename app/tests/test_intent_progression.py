"""Tests for the Live Intent Progression Tracker (DOC-CFO-2026-PROGRESSION-V1)."""

import pytest
from app.conversational_manager import build_intent_progression
from app.models.schemas import AgentResponse, ExecutionStatus


def test_build_intent_progression_clarifying_phase():
    """In clarifying phase, intent progression produces verified facts and active reasoning."""
    ents = {
        "supplier_name": "Dell Technologies",
        "amount": 180000.0,
        "item_description": "Office Laptops",
        "quantity": 3,
        "currency": "PKR",
    }
    missing = ["transaction_nature", "useful_life_years", "payment_channel"]
    
    prog = build_intent_progression(
        intent="record_purchase",
        entities=ents,
        missing_fields=missing,
        status="clarifying",
    )
    
    assert prog["status"] == "clarifying"
    assert len(prog["verified_facts"]) >= 3
    
    # Check verified facts
    fact_labels = [f["label"] for f in prog["verified_facts"]]
    assert "Vendor" in fact_labels
    assert "Amount" in fact_labels
    assert "Description" in fact_labels
    
    # Check reasoning covers missing accounting standards
    assert "IAS 16" in prog["active_reasoning"] or "capital expenditure" in prog["active_reasoning"]
    assert "Section 73" in prog["active_reasoning"] or "corporate banking" in prog["active_reasoning"]
    assert prog["missing_info"] is not None


def test_build_intent_progression_reviewing_and_completed():
    """When all fields are gathered, intent progression indicates reviewing or completed."""
    ents = {
        "counterparty": "Dell Technologies",
        "amount": 180000.0,
        "item_description": "Office Laptops",
        "transaction_nature": "FIXED_ASSET",
        "useful_life_years": 3,
        "payment_channel": "bank_transfer",
        "bank_name": "Meezan Bank",
        "wht_decision": "DEDUCT",
        "wht_rate_percent": 3.0,
        "transaction_date": "2026-11-20",
    }
    
    prog = build_intent_progression(
        intent="register_fixed_asset",
        entities=ents,
        missing_fields=[],
        status="reviewing",
    )
    
    assert prog["status"] == "reviewing"
    assert prog["missing_info"] is None
    
    fact_dict = {f["label"]: f["value"] for f in prog["verified_facts"]}
    assert fact_dict["Vendor"] == "Dell Technologies"
    assert "180,000" in fact_dict["Amount"]
    assert fact_dict["Classification"] == "Capital Asset (IAS 16)"
    assert "3 Years" in fact_dict["Useful Life"]
    assert "Meezan Bank" in fact_dict["Payment Method"]
    assert "3%" in fact_dict["WHT Treatment"]
    assert fact_dict["Posting Date"] == "2026-11-20"


def test_agent_response_schema_carries_intent_progression():
    """AgentResponse model validates and serializes intent_progression."""
    prog_data = {
        "intent": "record_expense",
        "status": "clarifying",
        "verified_facts": [{"label": "Amount", "value": "PKR 50,000"}],
        "active_reasoning": "Checking Section 73 limits.",
        "missing_info": "Payment Channel",
    }
    
    resp = AgentResponse(
        status=ExecutionStatus.AWAITING_CLARIFICATION,
        summary="Awaiting clarification",
        question="How was this paid?",
        intent_progression=prog_data,
        data={"intent_progression": prog_data},
    )
    
    assert resp.intent_progression is not None
    assert resp.intent_progression["status"] == "clarifying"
    assert resp.data["intent_progression"]["verified_facts"][0]["value"] == "PKR 50,000"
