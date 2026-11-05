import pytest
import uuid
from app.conversation_harness import (
    DocumentCandidate,
    DisambiguationContext,
    evaluate_disambiguation_need,
    build_detailed_disambiguation_card,
    resolve_user_selection,
    validate_compliance_prerequisites,
    probe_live_records,
)

def test_disambiguation_for_multiple_bills_on_different_dates():
    # Setup 2 bills for the same supplier on different dates
    bill1 = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="BILL-000101",
        doc_date="2026-10-15",
        due_date="2026-10-30",
        party_id=uuid.uuid4(),
        party_name="Delta Pvt",
        total=50000.0,
        amount_paid=0.0,
        balance_due=50000.0,
        status="OPEN",
        notes="Office laptop chargers",
    )
    bill2 = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="BILL-000108",
        doc_date="2026-10-25",
        due_date="2026-11-10",
        party_id=uuid.uuid4(),
        party_name="Delta Pvt",
        total=50000.0,
        amount_paid=0.0,
        balance_due=50000.0,
        status="OPEN",
        notes="Network switches",
    )

    ctx = DisambiguationContext(
        matching_bills=[bill1, bill2],
        extracted_party="Delta Pvt",
        extracted_amount=50000.0,
    )

    needs_clar, reason, candidates = evaluate_disambiguation_need(ctx, "Paid 50000 to Delta today")
    assert needs_clar is True
    assert reason == "multiple_matching_bills"
    assert len(candidates) == 2

    # Verify detailed card has dates and amounts
    card_text, options = build_detailed_disambiguation_card(candidates, party_name="Delta Pvt")
    assert "BILL-000101" in card_text
    assert "2026-10-15" in card_text
    assert "BILL-000108" in card_text
    assert "2026-10-25" in card_text
    assert "Rs. 50,000.00" in card_text
    assert len(options) == 3  # Bill 1, Bill 2, Standalone Expense

    # User answers by date
    selected_by_date = resolve_user_selection("the 25th Oct one", candidates)
    assert selected_by_date is not None
    assert selected_by_date.number == "BILL-000108"

    # User answers by option letter
    selected_by_letter = resolve_user_selection("a", candidates)
    assert selected_by_letter is not None
    assert selected_by_letter.number == "BILL-000101"

    # User answers by bill number
    selected_by_num = resolve_user_selection("Bill 108", candidates)
    assert selected_by_num is not None
    assert selected_by_num.number == "BILL-000108"


def test_disambiguation_for_different_records_on_same_date():
    bill_a = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="BILL-000201",
        doc_date="2026-10-28",
        due_date=None,
        party_id=uuid.uuid4(),
        party_name="Tech Solutions",
        total=15000.0,
        amount_paid=0.0,
        balance_due=15000.0,
        status="OPEN",
    )
    bill_b = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="BILL-000202",
        doc_date="2026-10-28",
        due_date=None,
        party_id=uuid.uuid4(),
        party_name="Tech Solutions",
        total=85000.0,
        amount_paid=0.0,
        balance_due=85000.0,
        status="OPEN",
    )

    candidates = [bill_a, bill_b]
    # User selects by amount
    selected_by_amt = resolve_user_selection("the 85000 bill", candidates)
    assert selected_by_amt is not None
    assert selected_by_amt.number == "BILL-000202"


def test_section_73_compliance_guard():
    # If payment > 50,000 is made via CASH, trigger Section 73 warning
    high_val_bill = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="BILL-000300",
        doc_date="2026-11-01",
        due_date=None,
        party_id=uuid.uuid4(),
        party_name="Supplier Alpha",
        total=120000.0,
        amount_paid=0.0,
        balance_due=120000.0,
        status="OPEN",
    )
    warnings = validate_compliance_prerequisites(high_val_bill, payment_method="CASH")
    assert len(warnings) >= 1
    assert any("Section 73" in w for w in warnings)

    # When paid via BANK, Section 73 cash warning should NOT appear
    bank_warnings = validate_compliance_prerequisites(high_val_bill, payment_method="BANK_TRANSFER")
    assert not any("Section 73" in w for w in bank_warnings)


@pytest.mark.asyncio
@pytest.mark.allows_db
async def test_probe_live_records_live_db():
    org_id = uuid.UUID("00000000-0000-4000-8000-000000000010")
    # Probe for bill 5
    ctx = await probe_live_records(org_id, "Paid in full the bill no. 5 today")
    assert len(ctx.matching_bills) >= 1
    matched = ctx.matching_bills[0]
    assert "5" in matched.number


@pytest.mark.asyncio
async def test_end_to_end_multiturn_disambiguation_flow(monkeypatch):
    """Simulate complete 2-turn conversation:
    Turn 1: Ambiguous payment request matches 2 bills on different dates.
    Agent presents full detailed options card.
    Turn 2: User replies 'the 25th Oct one' -> Harness resolves exact document and executes.
    """
    from app.agent import _resolve_open_document_reference
    from app.conversation_harness import DocumentCandidate

    org_id = uuid.uuid4()
    bill1 = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="BILL-000101",
        doc_date="2026-10-15",
        due_date="2026-10-30",
        party_id=uuid.uuid4(),
        party_name="Delta Pvt",
        total=50000.0,
        amount_paid=0.0,
        balance_due=50000.0,
        status="OPEN",
        notes="Office laptop chargers",
    )
    bill2 = DocumentCandidate(
        doc_type="bill",
        id=uuid.uuid4(),
        number="BILL-000108",
        doc_date="2026-10-25",
        due_date="2026-11-10",
        party_id=uuid.uuid4(),
        party_name="Delta Pvt",
        total=50000.0,
        amount_paid=0.0,
        balance_due=50000.0,
        status="OPEN",
        notes="Network switches",
    )

    # Monkeypatch probe_live_records to return both bills
    async def mock_probe(*args, **kwargs):
        ctx = DisambiguationContext(
            matching_bills=[bill1, bill2],
            extracted_party="Delta Pvt",
            extracted_amount=50000.0,
        )
        return ctx

    import app.conversation_harness as ch
    monkeypatch.setattr(ch, "probe_live_records", mock_probe)

    # --- TURN 1 ---
    turn1_entities = {
        "user_message": "Paid 50000 to Delta today",
        "supplier_name": "Delta Pvt",
        "amount": 50000.0,
    }
    await _resolve_open_document_reference(org_id, turn1_entities)
    assert turn1_entities.get("requires_disambiguation") is True
    question = turn1_entities.get("disambiguation_question")
    assert "Disambiguation: Multiple Matching Records for Delta Pvt" in question
    assert "BILL-000101" in question and "2026-10-15" in question
    assert "BILL-000108" in question and "2026-10-25" in question

    # --- TURN 2 ---
    # User responds: "the 25th Oct one"
    turn2_entities = {
        "user_message": "the 25th Oct one",
        "prior_qa": [
            {
                "question": question,
                "answer": "the 25th Oct one",
            }
        ]
    }
    await _resolve_open_document_reference(org_id, turn2_entities)
    assert turn2_entities.get("requires_disambiguation") is False
    assert turn2_entities.get("bill_id") == str(bill2.id)
    assert turn2_entities.get("bill_number") == "BILL-000108"
    assert turn2_entities.get("supplier_name") == "Delta Pvt"
    assert turn2_entities.get("amount") == 50000.0
