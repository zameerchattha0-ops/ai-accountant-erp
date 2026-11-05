import pytest
import uuid
from app.planner import plan, _identify_intent
from app.classifier import classify_transaction

def test_intent_patterns_for_bill_and_invoice():
    # 1. Bill payment with loose phrasing
    intent1 = _identify_intent("Paid in full the bill no. 5 today")
    assert intent1 == "record_payment", f"Expected record_payment, got {intent1}"

    intent1_alt = _identify_intent("paid bill 5 today")
    assert intent1_alt == "record_payment", f"Expected record_payment, got {intent1_alt}"

    # 2. Invoice receipt with loose phrasing
    intent2 = _identify_intent("Received amount of invoice 0006 in full today")
    assert intent2 == "record_receipt", f"Expected record_receipt, got {intent2}"

    intent2_alt = _identify_intent("received against invoice 6")
    assert intent2_alt == "record_receipt", f"Expected record_receipt, got {intent2_alt}"

def test_planner_entities_extraction():
    p1 = plan("Paid in full the bill no. 5 today")
    assert p1.intent == "record_payment"

    p2 = plan("Received amount of invoice 0006 in full today")
    assert p2.intent == "record_receipt"

@pytest.mark.asyncio
async def test_classifier_does_not_treat_bill_or_invoice_as_inventory():
    org_id = uuid.uuid4()
    # If bill_number or invoice_number is present, it must NOT require 4-way nature clarification
    clf_bill = await classify_transaction(
        organization_id=org_id,
        intent="record_payment",
        entities={"supplier_name": "Delta Pvt", "bill_number": "5"},
        message="Paid in full the bill no. 5 today",
    )
    assert clf_bill.requires_clarification is False

    clf_unknown_bill = await classify_transaction(
        organization_id=org_id,
        intent="unknown",
        entities={"bill_number": "5"},
        message="Paid in full the bill no. 5 today",
    )
    assert clf_unknown_bill.requires_clarification is False

    clf_receipt = await classify_transaction(
        organization_id=org_id,
        intent="record_receipt",
        entities={"invoice_number": "0006"},
        message="Received amount of invoice 0006 in full today",
    )
    assert clf_receipt.requires_clarification is False
