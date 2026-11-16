"""Unit tests for Party Role & Relationship Disambiguator (Task 3).

Specifications tested:
- 5-Stage Skeptical Evidentiary Hierarchy.
- Money-flow vector evaluation:
  * Money OUT + open payable -> supplier (settlement u/s 153).
  * Money OUT + employee roster -> employee (salary / advance u/s 149).
  * Money OUT + owner/director -> owner (drawings / loan).
  * Money IN + open receivable -> customer (collection IFRS 9).
  * Money IN + owner/director -> owner (capital injection).
- Dual-role counterparties & IAS 32 offsetting prohibition (Alpha Logistics case).
- Conflicting roles (Employee + Director) triggering clarification.
- Genuinely ambiguous / novel party with zero history -> requires_clarification=True (conf < 0.65).
- Separator-insensitive name matching via name_key.
- Offline execution with zero database calls (conftest _no_live_database invariant).
- Fail-safe degradation when LLM unavailable.
"""

import pytest
from app.party_disambiguation import (
    PartyRoleResult,
    disambiguate_party_role,
    WHT_SUPPLIER_RULE,
    WHT_EMPLOYEE_RULE,
    WHT_OWNER_DRAWINGS_RULE,
)
from app.config import get_settings


@pytest.fixture
def mock_open_payables():
    return [
        {
            "id": "bill-001",
            "supplier_name": "Shabbir Furniture",
            "bill_number": "BILL-1044",
            "balance": 150000.0,
        },
        {
            "id": "bill-002",
            "party_name": "Al-Areesh Engineering",
            "bill_number": "BILL-1045",
            "balance": 85000.0,
        },
        {
            "id": "bill-003",
            "supplier_name": "Alpha Logistics",
            "bill_number": "BILL-1046",
            "balance": 35000.0,
        },
    ]


@pytest.fixture
def mock_open_receivables():
    return [
        {
            "id": "inv-001",
            "customer_name": "MegaCorp Industries",
            "invoice_number": "INV-2026-001",
            "balance": 250000.0,
        },
        {
            "id": "inv-002",
            "party_name": "Apex Tech Solutions",
            "invoice_number": "INV-2026-002",
            "balance": 120000.0,
        },
        {
            "id": "inv-003",
            "customer_name": "Alpha Logistics",
            "invoice_number": "INV-2026-003",
            "balance": 50000.0,
        },
    ]


@pytest.fixture
def mock_employees():
    return [
        {
            "id": "emp-001",
            "full_name": "Hamza Tariq",
            "employee_code": "EMP-001",
            "designation": "Senior Software Engineer",
            "basic_salary": 200000.0,
        },
        {
            "id": "emp-002",
            "full_name": "Fatima Zahra",
            "employee_code": "EMP-002",
            "designation": "UI/UX Designer",
            "basic_salary": 140000.0,
        },
        {
            "id": "emp-003",
            "full_name": "Bilal Khan",
            "employee_code": "EMP-003",
            "designation": "Chief Operating Officer",
            "basic_salary": 350000.0,
        },
    ]


@pytest.fixture
def mock_org_officers():
    return [
        {
            "id": "off-001",
            "full_name": "Zameer Ahmed",
            "role": "Director / Majority Shareholder",
        },
        {
            "id": "off-002",
            "full_name": "Bilal Khan",
            "role": "Director & COO",
        },
    ]


@pytest.mark.asyncio
async def test_money_out_matches_open_payable_supplier(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Money OUT to Shabbir Furniture matches open payable bill -> supplier (settlement u/s 153)."""
    result = await disambiguate_party_role(
        party_name="Shabbir Furniture",
        money_direction="OUT",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert isinstance(result, PartyRoleResult)
    assert result.role == "supplier"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert result.clarification_question is None
    assert "2010" in str(result.account_head)
    assert "Section 153" in str(result.statutory_wht_rule)
    assert result.matched_record is not None
    assert result.matched_record["bill_number"] == "BILL-1044"


@pytest.mark.asyncio
async def test_money_out_matches_employee_roster(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Money OUT to Hamza Tariq matches active employee roster -> employee (salary / advance u/s 149)."""
    result = await disambiguate_party_role(
        party_name="Hamza Tariq",
        money_direction="OUT",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert result.role == "employee"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert "2150" in str(result.account_head)
    assert "Section 149" in str(result.statutory_wht_rule)
    assert result.matched_record is not None
    assert result.matched_record["employee_code"] == "EMP-001"


@pytest.mark.asyncio
async def test_money_out_matches_officer_drawings(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Money OUT to Zameer Ahmed (Director) with no employee/payable record -> owner (drawings)."""
    result = await disambiguate_party_role(
        party_name="Zameer Ahmed",
        money_direction="OUT",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert result.role == "owner"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert "3200" in str(result.account_head)
    assert "drawings" in str(result.statutory_wht_rule).lower() or "section 150" in str(result.statutory_wht_rule).lower()


@pytest.mark.asyncio
async def test_money_in_matches_open_receivable_customer(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Money IN from MegaCorp Industries matches open invoice -> customer (collection IFRS 9)."""
    result = await disambiguate_party_role(
        party_name="MegaCorp Industries",
        money_direction="IN",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert result.role == "customer"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert "1110" in str(result.account_head)
    assert result.matched_record is not None
    assert result.matched_record["invoice_number"] == "INV-2026-001"


@pytest.mark.asyncio
async def test_money_in_matches_officer_capital_injection(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Money IN from Zameer Ahmed (Director) -> owner (capital injection / equity / loan)."""
    result = await disambiguate_party_role(
        party_name="Zameer Ahmed",
        money_direction="IN",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert result.role == "owner"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert "3010" in str(result.account_head) or "Capital" in str(result.account_head)


@pytest.mark.asyncio
async def test_dual_role_party_ias32_offsetting_prohibition(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Alpha Logistics is both a supplier (AP) and customer (AR). Under IAS 32, no silent netting.

    Money OUT -> settles supplier payable (2010).
    Money IN -> settles customer receivable (1110).
    """
    # 1. Money OUT
    out_result = await disambiguate_party_role(
        party_name="Alpha Logistics",
        money_direction="OUT",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )
    assert out_result.role == "supplier"
    assert out_result.requires_clarification is False
    assert "2010" in str(out_result.account_head)
    assert "IAS 32" in out_result.reasoning

    # 2. Money IN
    in_result = await disambiguate_party_role(
        party_name="Alpha Logistics",
        money_direction="IN",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )
    assert in_result.role == "customer"
    assert in_result.requires_clarification is False
    assert "1110" in str(in_result.account_head)
    assert "IAS 32" in in_result.reasoning


@pytest.mark.asyncio
async def test_employee_and_officer_conflict_triggers_clarification(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Bilal Khan is registered as BOTH an employee and a Director. Outgoing payment without memo is ambiguous."""
    result = await disambiguate_party_role(
        party_name="Bilal Khan",
        money_direction="OUT",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert result.confidence < 0.65
    assert result.requires_clarification is True
    assert result.clarification_question is not None
    assert "salary" in result.clarification_question.lower() or "drawings" in result.clarification_question.lower()
    assert len(result.clarification_options) >= 2


@pytest.mark.asyncio
async def test_novel_party_zero_history_requires_clarification(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """Novel party with zero matches across all registers requires clarification with smart options."""
    # Money OUT
    out_result = await disambiguate_party_role(
        party_name="Ali Raza",
        money_direction="OUT",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert out_result.role == "unknown"
    assert out_result.confidence < 0.65
    assert out_result.requires_clarification is True
    assert out_result.clarification_question is not None
    assert len(out_result.clarification_options) >= 3
    assert any("Supplier" in opt for opt in out_result.clarification_options)
    assert any("Employee" in opt for opt in out_result.clarification_options)
    assert any("Owner" in opt for opt in out_result.clarification_options)

    # Money IN
    in_result = await disambiguate_party_role(
        party_name="Ali Raza",
        money_direction="IN",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert in_result.role == "unknown"
    assert in_result.confidence < 0.65
    assert in_result.requires_clarification is True
    assert any("Customer" in opt for opt in in_result.clarification_options)


@pytest.mark.asyncio
async def test_separator_insensitive_name_matching(
    mock_open_payables, mock_open_receivables, mock_employees, mock_org_officers
):
    """'alareesh engineering' matches 'Al-Areesh Engineering' via name_key."""
    result = await disambiguate_party_role(
        party_name="alareesh engineering",
        money_direction="OUT",
        open_receivables=mock_open_receivables,
        open_payables=mock_open_payables,
        employees=mock_employees,
        org_officers=mock_org_officers,
    )

    assert result.role == "supplier"
    assert result.confidence >= 0.90
    assert result.requires_clarification is False
    assert result.matched_record is not None
    assert result.matched_record["party_name"] == "Al-Areesh Engineering"


@pytest.mark.asyncio
async def test_empty_party_name_handled():
    """Empty party name returns role='unknown' and requires_clarification=True."""
    result = await disambiguate_party_role(
        party_name="",
        money_direction="OUT",
        open_receivables=[],
        open_payables=[],
        employees=[],
        org_officers=[],
    )

    assert result.role == "unknown"
    assert result.confidence == 0.0
    assert result.requires_clarification is True


@pytest.mark.asyncio
async def test_llm_mode_with_mock_client(monkeypatch):
    """Verify LLM client pathway when enabled with mock client."""
    class MockClient:
        async def generate_text_light(self, prompt: str):
            return (
                '{\n'
                '  "role": "supplier",\n'
                '  "confidence": 0.96,\n'
                '  "requires_clarification": false,\n'
                '  "clarification_question": null,\n'
                '  "clarification_options": [],\n'
                '  "account_head": "2010 Accounts Payable",\n'
                '  "statutory_wht_rule": "Section 153 WHT 15%",\n'
                '  "standard_reference": "IFRS 9",\n'
                '  "reasoning": "Vendor bill settlement confirmed by payment memo."\n'
                '}'
            )

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_party_disambiguation_enabled", True)

    result = await disambiguate_party_role(
        party_name="Tariq Legal Chambers",
        money_direction="OUT",
        open_receivables=[],
        open_payables=[{"party_name": "Tariq Legal Chambers", "bill_number": "B-99"}],
        employees=[],
        org_officers=[],
        client=MockClient(),
    )

    assert result.decision_source == "llm"
    assert result.role == "supplier"
    assert result.confidence == 0.96
    assert result.requires_clarification is False
