"""Unit tests for the LLM-driven Economic Event & 360° Impact Map architecture.

Verifies that the LLM is authoritative for:
1. Economic event classification (ACQUISITION, DISPOSAL, EXPENDITURE, etc.)
2. 360° impact map (party_ledger, cash_bank, fixed_asset, inventory, expense, etc.)
3. Prohibited actions (negative reasoning: party_ledger_creation, inventory_movement, etc.)
and that Python serves as the invariant-verifying execution kernel with fallback defaults.
"""

from __future__ import annotations

import pytest
from app.accounting_reasoning import _clean_decision
from app.llm_extraction import _validate as validate_extraction, enrich_preliminary
from app.models.schemas import ExecutionPlan
from app.planner import plan
from app.reasoning import (
    EconomicEvent,
    FieldResolutionState,
    analyze_requirements,
    build_event_profile,
    prohibited_tool_names,
)


def test_clean_decision_parses_llm_impact_map_and_prohibitions():
    raw_payload = {
        "intent": "record_purchase",
        "treatment": "FIXED_ASSET",
        "document_nature": "GOODS",
        "economic_event": "ACQUISITION",
        "impact_map": {
            "party_ledger": False,
            "ar_ap": False,
            "cash_bank": True,
            "inventory": False,
            "fixed_asset": True,
            "expense": False,
            "revenue": False,
            "journal": True,
            "documents": True,
            "dimensions": False,
        },
        "prohibited_actions": [
            {
                "action": "party_ledger_creation",
                "reason": "Direct cash purchase does not require a supplier ledger account",
            },
            {
                "action": "inventory_movement",
                "reason": "Capital equipment for office use is not stock inventory",
            },
        ],
    }

    decision = _clean_decision(raw_payload)

    assert decision["intent"] == "record_purchase"
    assert decision["treatment"] == "FIXED_ASSET"
    assert decision["economic_event"] == "ACQUISITION"
    assert decision["impact_map"]["party_ledger"] is False
    assert decision["impact_map"]["fixed_asset"] is True
    assert decision["impact_map"]["inventory"] is False
    assert len(decision["prohibited_actions"]) == 2
    assert decision["prohibited_actions"][0]["action"] == "party_ledger_creation"
    assert decision["prohibited_actions"][1]["action"] == "inventory_movement"


def test_build_event_profile_adopts_llm_authoritative_impact_map():
    # When intent is a credit purchase, deterministic rules would default party_ledger=True
    # But LLM states this specific purchase has no party ledger (e.g. cash settlement):
    llm_impact = {
        "party_ledger": False,
        "ar_ap": False,
        "cash_bank": True,
        "fixed_asset": True,
        "inventory": False,
    }
    llm_prohibited = [
        {"action": "party_ledger_creation", "reason": "No supplier ledger required"},
        {"action": "inventory_movement", "reason": "Asset is not inventory"},
    ]

    profile = build_event_profile(
        "record_credit_purchase",
        llm_event="ACQUISITION",
        llm_impact_map=llm_impact,
        llm_prohibited_actions=llm_prohibited,
        llm_nature="FIXED_ASSET",
    )

    assert profile.event == EconomicEvent.ACQUISITION
    assert profile.affected["party_ledger"] is False
    assert profile.affected["ar_ap"] is False
    assert profile.affected["cash_bank"] is True
    assert profile.affected["fixed_asset"] is True
    assert profile.affected["inventory"] is False

    # Prohibited tools enforcement
    blocked = prohibited_tool_names(profile)
    assert "create_supplier" in blocked
    assert "create_customer" in blocked


def test_build_event_profile_fallback_when_llm_silent():
    # When LLM parameters are omitted, deterministic rules provide backward compatibility
    profile = build_event_profile("record_credit_purchase")
    assert profile.event == EconomicEvent.ACQUISITION
    assert profile.affected["party_ledger"] is True
    assert profile.affected["ar_ap"] is True
    assert profile.affected["cash_bank"] is False


def test_analyze_requirements_respects_llm_impact_map_party_ledger_false():
    # Analyze requirements with impact_map party_ledger=False
    nodes = analyze_requirements(
        intent="record_credit_purchase",
        entities={"amount": 250000, "supplier_name": "Modern Furnishers"},
        missing_fields=[],
        impact_map={"party_ledger": False},
    )

    party_node = next((n for n in nodes if n.key == "counterparty"), None)
    assert party_node is not None
    assert party_node.state == FieldResolutionState.MISSING_BUT_OPTIONAL
    assert party_node.question is None


def test_preliminary_extraction_validates_economic_event_and_impact_map():
    raw_reply = {
        "provisional_intent_hint": "record_purchase",
        "amount": 150000,
        "payment_channel": "CASH",
        "item_description": "executive office desk",
        "economic_event": "ACQUISITION",
        "impact_map": {
            "party_ledger": False,
            "cash_bank": True,
            "fixed_asset": True,
            "inventory": False,
        },
    }

    clean, failures = validate_extraction(raw_reply)
    assert not failures
    assert clean["economic_event"] == "ACQUISITION"
    assert clean["impact_map"]["party_ledger"] is False
    assert clean["impact_map"]["fixed_asset"] is True


def test_planner_incorporates_llm_impact_map_from_prefill():
    prefill = {
        "amount": 250000,
        "payment_method": "CASH",
        "item_description": "office furniture",
        "economic_event": "ACQUISITION",
        "impact_map": {
            "party_ledger": False,
            "fixed_asset": True,
            "inventory": False,
        },
        "prohibited_actions": [
            {"action": "party_ledger_creation", "reason": "Cash purchase"}
        ],
    }

    plan_obj = plan("buy office furniture for 250000 cash", prefill_entities=prefill)
    assert plan_obj.economic_event == "ACQUISITION"
    assert plan_obj.impact_map.get("party_ledger") is False
    assert plan_obj.impact_map.get("fixed_asset") is True
    assert plan_obj.impact_map.get("inventory") is False
    assert any(p.get("action") == "party_ledger_creation" for p in plan_obj.prohibited_actions)


@pytest.mark.asyncio
async def test_party_gate_bypassed_when_execution_plan_impact_map_party_ledger_is_false():
    import uuid
    from app.agent import _party_resolution_question

    plan_obj = ExecutionPlan(
        intent="record_purchase",
        extracted_entities={"amount": 250000, "supplier_name": "Modern Furnishers"},
        impact_map={"party_ledger": False},
    )

    q = await _party_resolution_question(
        organization_id=uuid.uuid4(),
        execution_plan=plan_obj,
    )
    # Because impact_map["party_ledger"] is False, no supplier ledger prompt is emitted
    assert q is None
