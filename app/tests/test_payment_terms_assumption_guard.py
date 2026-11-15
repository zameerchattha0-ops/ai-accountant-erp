import pytest
from app.extraction import StructuredTransactionDraft
from app.llm_extraction import _validate
from app.planner import plan


def test_unspecified_payment_terms_purchase_requires_payment_type():
    """When the user message does not specify cash or credit, planner must not assume cash."""
    p = plan("purchased two tables from shabbir furnitures today")
    assert p.intent == "record_purchase"
    assert "payment_type" in p.missing_fields


def test_ungrounded_prefill_normalized_to_record_purchase():
    """If an LLM or prefill prematurely outputs record_cash_purchase without payment method, it is normalized."""
    prefill = {
        "semantic_intent": "record_cash_purchase",
        "supplier_name": "Shabbir Furnitures",
        "transaction_nature": "INVENTORY",
        "item_description": "tables",
        "quantity": 2.0,
    }
    p = plan("purchased two tables from shabbir furnitures today", prefill_entities=prefill)
    assert p.intent == "record_purchase"
    assert "payment_type" in p.missing_fields


def test_explicit_cash_purchase_specializes():
    """When the user explicitly says 'on cash', it specializes to record_cash_purchase."""
    p = plan("purchased two tables from shabbir furnitures today on cash")
    assert p.intent == "record_cash_purchase"
    assert "payment_type" not in p.missing_fields


def test_explicit_credit_purchase_specializes():
    """When the user explicitly says 'on credit', it specializes to record_credit_purchase."""
    p = plan("purchased two tables from shabbir furnitures today on credit")
    assert p.intent == "record_credit_purchase"
    assert "payment_type" not in p.missing_fields


def test_clarification_answer_specializes_to_credit():
    """Answering 'on credit' to the questionnaire specializes to record_credit_purchase."""
    history = [
        {"field": "transaction_nature", "question": "Is this fixed asset or inventory?", "answer": "INVENTORY"},
        {"field": "payment_type", "question": "Was this paid in cash or on credit?", "answer": "on credit"},
        {"field": "amount", "question": "What is the total amount?", "answer": "50000"},
    ]
    prefill = {
        "supplier_name": "Shabbir Furnitures",
        "item_description": "tables",
        "quantity": 2.0,
    }
    p = plan("purchased two tables from shabbir furnitures today", clarification_history=history, prefill_entities=prefill)
    assert p.intent == "record_credit_purchase"
    assert not p.missing_fields


def test_clarification_answer_specializes_to_cash():
    """Answering 'cash' to the questionnaire specializes to record_cash_purchase."""
    history = [
        {"field": "transaction_nature", "question": "Is this fixed asset or inventory?", "answer": "INVENTORY"},
        {"field": "payment_type", "question": "Was this paid in cash or on credit?", "answer": "cash"},
        {"field": "amount", "question": "What is the total amount?", "answer": "50000"},
    ]
    prefill = {
        "supplier_name": "Shabbir Furnitures",
        "item_description": "tables",
        "quantity": 2.0,
    }
    p = plan("purchased two tables from shabbir furnitures today", clarification_history=history, prefill_entities=prefill)
    assert p.intent == "record_cash_purchase"
    assert not p.missing_fields


def test_extraction_draft_normalizes_intent_when_payment_channel_missing():
    """StructuredTransactionDraft normalizes specialized purchase/sale intents if payment_channel is null."""
    draft1 = StructuredTransactionDraft(intent="record_cash_purchase", payment_channel=None)
    assert draft1.intent == "record_purchase"

    draft2 = StructuredTransactionDraft(intent="record_credit_purchase", payment_channel=None)
    assert draft2.intent == "record_purchase"

    draft3 = StructuredTransactionDraft(intent="record_cash_sale", payment_channel=None)
    assert draft3.intent == "record_sale"

    draft4 = StructuredTransactionDraft(intent="record_purchase", payment_channel="cash")
    assert draft4.intent == "record_cash_purchase"

    draft5 = StructuredTransactionDraft(intent="record_purchase", payment_channel="credit")
    assert draft5.intent == "record_credit_purchase"


def test_llm_extraction_validation_normalizes_hint():
    """_validate in llm_extraction normalizes ungrounded provisional_intent_hint."""
    clean, failures = _validate({
        "provisional_intent_hint": "record_cash_purchase",
        "payment_channel": None,
    })
    assert clean.get("provisional_intent_hint") == "record_purchase"

    clean_cash, _ = _validate({
        "provisional_intent_hint": "record_purchase",
        "payment_channel": "CASH",
    })
    assert clean_cash.get("provisional_intent_hint") == "record_purchase"
    assert clean_cash.get("payment_channel") == "CASH"


def test_turn1_asks_nature_payment_and_amount_together():
    """All open decisions (intended use, settlement, amount) are asked in Turn 1."""
    prefill = {
        "semantic_intent": "record_purchase",
        "transaction_nature": "INVENTORY",  # ungrounded LLM guess
        "supplier_name": "Shabbir Furnitures",
        "quantity": 2.0,
        "item_description": "tables",
    }
    p = plan("purchased two tables from shabbir furnitures today", prefill_entities=prefill)
    assert "transaction_nature" in p.missing_fields
    assert "payment_type" in p.missing_fields
    assert "amount" in p.missing_fields


def test_fixed_asset_choice_branches_to_asset_registration():
    """Selecting fixed asset branches to register_fixed_asset and asks useful life/depreciation."""
    history = [
        {"field": "transaction_nature", "answer": "FIXED_ASSET", "question": "nature"},
        {"field": "payment_type", "answer": "CREDIT", "question": "payment_type"},
        {"field": "amount", "answer": "50000", "question": "amount"},
    ]
    p = plan("purchased two tables from shabbir furnitures today", clarification_history=history)
    assert p.intent == "register_fixed_asset"
    assert "useful_life_years" in p.missing_fields
    assert "depreciation_method" in p.missing_fields

