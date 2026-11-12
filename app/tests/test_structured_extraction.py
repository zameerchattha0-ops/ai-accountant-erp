"""Tests for Structured LLM Extraction, Typed Clarification Resume, and Pipeline Wiring."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock as _AM

import pytest

import app.agent as agent_mod
import app.extraction as extraction_mod
from app.clarification_schema import (
    ClarificationAnswer,
    ClarificationResume,
    apply_answers,
)
from app.extraction import (
    CounterpartyInfo,
    LineItem,
    StructuredTransactionDraft,
    build_extraction_prompt,
    draft_to_prefill_entities,
    extract_structured,
)
from app.models.schemas import ExecutionPlan, ExecutionStatus, TransactionClassification
from app.questionnaire import (
    QUESTION_BANK,
    build_questionnaire,
    draft_field_id_for,
    questionnaire_schema,
)


class _StubModels:
    def __init__(self, payload: dict | str, *, raise_exc: Exception | None = None):
        self._payload = payload
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: str, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._raise_exc is not None:
            raise self._raise_exc
        text = (
            self._payload
            if isinstance(self._payload, str)
            else json.dumps(self._payload)
        )
        return SimpleNamespace(text=text)


class _StubGeminiClient:
    def __init__(self, payload: dict | str, *, raise_exc: Exception | None = None):
        self.model_name = "gemini-3.8-flash"
        self._models = _StubModels(payload, raise_exc=raise_exc)
        self._gclient = SimpleNamespace(models=self._models)


def _mock_gemini(monkeypatch, payload: dict | str, *, raise_exc: Exception | None = None):
    stub = _StubGeminiClient(payload, raise_exc=raise_exc)
    monkeypatch.setattr(extraction_mod, "get_client", lambda: stub)
    return stub


# ---------------------------------------------------------------------------
# 1. Structured LLM Extraction (mocking Gemini response_schema call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_outstanding_supplier_bills_informational(monkeypatch):
    stub = _mock_gemini(
        monkeypatch,
        {
            "intent": "get_open_payables",
            "counterparty": None,
            "line_items": [],
            "payment_channel": None,
            "transaction_nature": None,
            "transaction_date": None,
            "total_amount": None,
            "currency": "PKR",
            "missing_fields": [],
            "user_intent_type": "informational",
            "confidence": 0.96,
        },
    )

    draft = await extract_structured(
        "Show me all outstanding supplier bills",
        conversation_history=[],
        org_context={"currency": "PKR"},
    )

    assert draft.intent == "get_open_payables"
    assert draft.user_intent_type == "informational"
    assert draft.counterparty is None
    assert draft.confidence == pytest.approx(0.96)
    cfg = stub._models.calls[0]["config"]
    assert cfg.response_schema is StructuredTransactionDraft
    assert cfg.response_mime_type == "application/json"


@pytest.mark.asyncio
async def test_extract_advisory_planned_purchase_sofas(monkeypatch):
    _mock_gemini(
        monkeypatch,
        {
            "intent": "record_purchase",
            "counterparty": {
                "name": "Shabbir Furniture",
                "role": "supplier",
                "confidence": 0.94,
            },
            "line_items": [
                {
                    "description": "sofa",
                    "quantity": 2,
                    "unit_price": None,
                    "unit": "pcs",
                }
            ],
            "payment_channel": None,
            "transaction_nature": "FIXED_ASSET",
            "transaction_date": None,
            "total_amount": None,
            "currency": "PKR",
            "missing_fields": ["total_amount", "payment_channel", "transaction_date"],
            "user_intent_type": "advisory",
            "confidence": 0.91,
        },
    )

    draft = await extract_structured(
        "I am purchasing 2 sofas from Shabbir Furniture",
        conversation_history=[],
        org_context={},
    )

    assert draft.user_intent_type == "advisory"
    assert draft.counterparty is not None
    assert draft.counterparty.name == "Shabbir Furniture"
    assert draft.counterparty.role == "supplier"
    assert len(draft.line_items) == 1
    assert draft.line_items[0].description == "sofa"
    assert draft.line_items[0].quantity == 2


@pytest.mark.asyncio
async def test_extract_transactional_cash_purchase_chairs(monkeypatch):
    _mock_gemini(
        monkeypatch,
        {
            "intent": "record_cash_purchase",
            "counterparty": {
                "name": "ABC",
                "role": "supplier",
                "confidence": 0.92,
            },
            "line_items": [
                {
                    "description": "chair",
                    "quantity": 5,
                    "unit_price": 10000.0,
                    "unit": "pcs",
                }
            ],
            "payment_channel": "cash",
            "transaction_nature": "FIXED_ASSET",
            "transaction_date": None,
            "total_amount": 50000.0,
            "currency": "PKR",
            "missing_fields": ["transaction_date"],
            "user_intent_type": "transactional",
            "confidence": 0.95,
        },
    )

    draft = await extract_structured(
        "Record cash purchase of 5 chairs from ABC at 50000",
        conversation_history=[],
        org_context={},
    )

    assert draft.user_intent_type == "transactional"
    assert draft.payment_channel == "cash"
    assert draft.total_amount == 50000.0
    assert draft.counterparty is not None and draft.counterparty.name == "ABC"
    assert draft.line_items[0].quantity == 5


@pytest.mark.asyncio
async def test_extract_cash_balance_informational(monkeypatch):
    _mock_gemini(
        monkeypatch,
        {
            "intent": "generate_cash_flow",
            "counterparty": None,
            "line_items": [],
            "payment_channel": None,
            "transaction_nature": None,
            "transaction_date": None,
            "total_amount": None,
            "currency": "PKR",
            "missing_fields": [],
            "user_intent_type": "informational",
            "confidence": 0.97,
        },
    )

    draft = await extract_structured(
        "What is our current cash balance?",
        conversation_history=[],
        org_context={},
    )

    assert draft.user_intent_type == "informational"
    assert draft.intent in ("generate_cash_flow", "list_bank_accounts", "get_cash_position")
    assert draft.counterparty is None


@pytest.mark.asyncio
async def test_extract_structured_degrades_gracefully_on_provider_error(monkeypatch):
    _mock_gemini(monkeypatch, {}, raise_exc=RuntimeError("Gemini 503"))

    draft = await extract_structured(
        "Record expense 1000",
        conversation_history=[],
        org_context={},
    )

    assert isinstance(draft, StructuredTransactionDraft)
    assert draft.confidence == 0.0


def test_extraction_prompt_budget_and_intent_distinction_rules():
    prompt = build_extraction_prompt("What is our current cash balance?")
    # Roughly <= 800 tokens (~3600 chars conservatively)
    assert len(prompt) <= 3600
    assert "informational" in prompt
    assert "transactional" in prompt
    assert "advisory" in prompt
    assert "Shabbir Furniture" in prompt


def test_draft_to_prefill_entities_maps_fields():
    draft = StructuredTransactionDraft(
        intent="record_cash_purchase",
        counterparty=CounterpartyInfo(name="ABC", role="supplier", confidence=0.9),
        line_items=[LineItem(description="chair", quantity=5, unit_price=10000.0)],
        payment_channel="cash",
        transaction_nature="FIXED_ASSET",
        transaction_date="2026-10-10",
        total_amount=50000.0,
        currency="PKR",
        missing_fields=[],
        user_intent_type="transactional",
        confidence=0.95,
    )
    prefill = draft_to_prefill_entities(draft)
    assert prefill["semantic_intent"] == "record_cash_purchase"
    assert prefill["supplier_name"] == "ABC"
    assert prefill["item_description"] == "chair"
    assert prefill["quantity"] == 5.0
    assert prefill["payment_method"] == "CASH"
    assert prefill["transaction_nature"] == "FIXED_ASSET"
    assert prefill["transaction_date"] == "2026-10-10"
    assert prefill["amount"] == 50000.0
    assert prefill["currency"] == "PKR"


# ---------------------------------------------------------------------------
# 2. Typed Clarification Resume (app/clarification_schema.py)
# ---------------------------------------------------------------------------


def test_apply_answers_merges_by_field_id_and_updates_missing():
    original = StructuredTransactionDraft(
        intent="record_purchase",
        counterparty=CounterpartyInfo(name="Shabbir Furniture", role="supplier", confidence=0.9),
        line_items=[LineItem(description="sofa", quantity=2)],
        missing_fields=["total_amount", "payment_channel", "transaction_date"],
        user_intent_type="advisory",
        confidence=0.9,
    )
    resume = ClarificationResume(
        original_draft=original,
        answers=[
            ClarificationAnswer(field_id="total_amount", value=120000, source="user"),
            ClarificationAnswer(field_id="payment_channel", value="bank_transfer", source="chip_selection"),
            ClarificationAnswer(field_id="transaction_date", value="2026-11-10", source="user"),
        ],
    )

    updated = apply_answers(resume.original_draft, resume.answers)

    assert updated.total_amount == 120000.0
    assert updated.payment_channel == "bank_transfer"
    assert updated.transaction_date == "2026-11-10"
    assert updated.missing_fields == []
    # Original remains unchanged
    assert original.total_amount is None
    assert len(original.missing_fields) == 3


def test_apply_answers_supports_questionnaire_field_aliases():
    original = StructuredTransactionDraft(
        intent="record_credit_purchase",
        missing_fields=["supplier_name", "amount", "payment_type"],
        user_intent_type="transactional",
        confidence=0.85,
    )
    updated = apply_answers(
        original,
        [
            ClarificationAnswer(field_id="supplier_name", value="Metro Cash & Carry", source="user"),
            ClarificationAnswer(field_id="amount", value="45,000", source="user"),
            ClarificationAnswer(field_id="payment_type", value="CASH", source="chip_selection"),
        ],
    )
    assert updated.counterparty is not None
    assert updated.counterparty.name == "Metro Cash & Carry"
    assert updated.counterparty.role == "supplier"
    assert updated.total_amount == 45000.0
    assert updated.payment_channel == "cash"
    assert updated.missing_fields == []


def test_apply_answers_rejects_unknown_field_id():
    original = StructuredTransactionDraft(user_intent_type="transactional", confidence=0.8)
    with pytest.raises(ValueError, match="Unknown draft field_id"):
        apply_answers(
            original,
            [ClarificationAnswer(field_id="nonexistent_field", value="x", source="user")],
        )


# ---------------------------------------------------------------------------
# 3. Questionnaire field_id Annotations & Agent Pipeline Wiring
# ---------------------------------------------------------------------------


def test_questionnaire_annotations_include_field_id():
    assert QUESTION_BANK["amount"].field_id == "total_amount"
    assert QUESTION_BANK["supplier_name"].field_id == "counterparty"
    assert QUESTION_BANK["payment_type"].field_id == "payment_channel"
    assert QUESTION_BANK["transaction_date"].field_id == "transaction_date"
    assert draft_field_id_for("item_description") == "line_items"

    q = build_questionnaire(["amount", "supplier_name", "payment_type"], intent="record_purchase")
    payload = q.to_payload()
    assert [item["field_id"] for item in payload["questions"]] == [
        "total_amount",
        "counterparty",
        "payment_channel",
    ]
    schema = questionnaire_schema()
    assert "field_id" in schema["properties"]["questions"]["items"]["properties"]


@pytest.mark.asyncio
async def test_agent_execute_calls_extract_structured_and_seeds_planner(monkeypatch, offline_org_lookups):
    org_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    user_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    session_id = uuid.uuid4()

    captured_prefills: list[dict | None] = []

    async def fake_extract(user_message, conversation_history=None, org_context=None):
        return StructuredTransactionDraft(
            intent="record_cash_purchase",
            counterparty=CounterpartyInfo(name="ABC", role="supplier", confidence=0.95),
            line_items=[LineItem(description="chair", quantity=5, unit_price=10000.0)],
            payment_channel="cash",
            transaction_nature="FIXED_ASSET",
            transaction_date="2026-11-10",
            total_amount=50000.0,
            currency="PKR",
            missing_fields=[],
            user_intent_type="transactional",
            confidence=0.92,
        )

    def fake_planner(user_message, clarification_history=None, org_preferences=None, prefill_entities=None):
        captured_prefills.append(prefill_entities)
        return ExecutionPlan(
            intent="record_cash_purchase",
            entity_type="supplier",
            entity_name="ABC",
            potential_tools=[],
            requires_validation=False,
            requires_accounting_engine=False,
            requires_confirmation=False,
            requires_clarification=False,
            missing_fields=[],
            clarification_questions=[],
            expected_outcome="Recorded",
            extracted_entities=dict(prefill_entities or {}),
            economic_event="CASH_PURCHASE",
            impact_map={},
            prohibited_actions=[],
            transaction_nature="FIXED_ASSET",
            transaction_nature_source="LLM",
            batch_items=None,
        )

    monkeypatch.setattr(agent_mod, "extract_structured", fake_extract)
    monkeypatch.setattr(agent_mod, "run_planner", fake_planner)
    monkeypatch.setattr(
        agent_mod,
        "create_execution_session",
        _AM(return_value={"id": str(session_id), "organization_id": str(org_id), "user_id": str(user_id)}),
    )
    monkeypatch.setattr(agent_mod, "_close_superseded_sessions", _AM(return_value=0))
    monkeypatch.setattr(agent_mod, "seed_clarification_history", _AM())
    monkeypatch.setattr(agent_mod, "_load_org_preferences", _AM(return_value={}))
    monkeypatch.setattr(agent_mod, "_update_status", _AM())
    monkeypatch.setattr(agent_mod, "_log_step", _AM())
    monkeypatch.setattr(agent_mod, "flush_step_logs", _AM())
    monkeypatch.setattr(agent_mod, "create_execution_result", _AM(return_value={"id": "res-1"}))
    monkeypatch.setattr(agent_mod, "build_context", _AM(return_value=SimpleNamespace(organization_id=org_id)))
    monkeypatch.setattr(
        agent_mod,
        "get_client",
        lambda: SimpleNamespace(
            generate_with_tools=_AM(return_value={"text": "Recorded cash purchase.", "tool_calls": [], "tool_results": []})
        ),
    )
    monkeypatch.setattr("app.classifier.classify_transaction", _AM(return_value=TransactionClassification(transaction_nature="FIXED_ASSET", confidence="HIGH", source="LLM", requires_clarification=False)))
    monkeypatch.setattr(agent_mod, "_party_resolution_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_settlement_check_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_catalog_check_question", _AM(return_value=None))

    await agent_mod.execute(
        user_message="Record cash purchase of 5 chairs from ABC at 50000",
        user_id=user_id,
        organization_id=org_id,
    )

    assert len(captured_prefills) == 1
    prefill = captured_prefills[0]
    assert prefill is not None
    assert prefill["semantic_intent"] == "record_cash_purchase"
    assert prefill["supplier_name"] == "ABC"
    assert prefill["amount"] == 50000.0
    assert prefill["payment_method"] == "CASH"


@pytest.mark.asyncio
async def test_agent_execute_falls_through_when_low_confidence(monkeypatch, offline_org_lookups):
    org_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    user_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    session_id = uuid.uuid4()

    captured_prefills: list[dict | None] = []

    async def fake_low_conf(user_message, conversation_history=None, org_context=None):
        return StructuredTransactionDraft(
            intent="record_expense",
            total_amount=999999.0,
            user_intent_type="transactional",
            confidence=0.35,
        )

    def fake_planner(user_message, clarification_history=None, org_preferences=None, prefill_entities=None):
        captured_prefills.append(prefill_entities)
        return ExecutionPlan(
            intent="list_expenses",
            entity_type=None,
            entity_name=None,
            potential_tools=[],
            requires_validation=False,
            requires_accounting_engine=False,
            requires_confirmation=False,
            requires_clarification=False,
            missing_fields=[],
            clarification_questions=[],
            expected_outcome="Done",
            extracted_entities={},
            economic_event=None,
            impact_map={},
            prohibited_actions=[],
            transaction_nature=None,
            transaction_nature_source=None,
            batch_items=None,
        )

    monkeypatch.setattr(agent_mod, "extract_structured", fake_low_conf)
    monkeypatch.setattr(agent_mod, "run_planner", fake_planner)
    monkeypatch.setattr(
        agent_mod,
        "create_execution_session",
        _AM(return_value={"id": str(session_id), "organization_id": str(org_id), "user_id": str(user_id)}),
    )
    monkeypatch.setattr(agent_mod, "_close_superseded_sessions", _AM(return_value=0))
    monkeypatch.setattr(agent_mod, "seed_clarification_history", _AM())
    monkeypatch.setattr(agent_mod, "_load_org_preferences", _AM(return_value={}))
    monkeypatch.setattr(agent_mod, "_update_status", _AM())
    monkeypatch.setattr(agent_mod, "_log_step", _AM())
    monkeypatch.setattr(agent_mod, "flush_step_logs", _AM())
    monkeypatch.setattr(agent_mod, "create_execution_result", _AM(return_value={"id": "res-1"}))
    monkeypatch.setattr(agent_mod, "build_context", _AM(return_value=SimpleNamespace(organization_id=org_id)))
    monkeypatch.setattr(
        agent_mod,
        "get_client",
        lambda: SimpleNamespace(
            generate_with_tools=_AM(return_value={"text": "Done.", "tool_calls": [], "tool_results": []})
        ),
    )

    monkeypatch.setattr("app.classifier.classify_transaction", _AM(return_value=TransactionClassification(transaction_nature="OPERATING_EXPENSE", confidence="HIGH", source="LLM", requires_clarification=False)))
    monkeypatch.setattr(agent_mod, "_party_resolution_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_settlement_check_question", _AM(return_value=None))
    monkeypatch.setattr(agent_mod, "_catalog_check_question", _AM(return_value=None))

    await agent_mod.execute(
        user_message="Record electricity expense of 2000",
        user_id=user_id,
        organization_id=org_id,
    )

    assert len(captured_prefills) == 1
    # Low confidence (< 0.6) must NOT inject 999999.0 or record_expense into prefill_entities
    prefill = captured_prefills[0] or {}
    assert prefill.get("amount") != 999999.0


@pytest.mark.asyncio
async def test_resume_with_clarification_accepts_typed_field_id_answers(monkeypatch, offline_org_lookups):
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "Create account for Office Utilities",
    }
    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "What type of account is this?",
        "required_information": ["account_type"],
        "reason": '{"intent": "create_account", "extracted_entities": {"account_name": "Office Utilities"}, "missing_fields": ["account_type"]}',
        "status": "WAITING_FOR_USER",
    }
    executed_calls = []

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        return clarification_row

    async def fake_route_tool_call(tc, organization_id, session_id, user_id, auth=None):
        executed_calls.append(tc)
        return SimpleNamespace(
            tool_name=tc.tool_name,
            success=True,
            data={"name": tc.arguments.get("name"), "account_type": tc.arguments.get("account_type")},
            error=None,
        )

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", _AM(return_value=[]))
    monkeypatch.setattr("app.tool_router.route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(agent_mod, "_update_status", _AM())
    monkeypatch.setattr(agent_mod, "_log_step", _AM())

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Expense",
        user_id=user_id,
        organization_id=org_id,
        structured_answers=[{"field_id": "account_type", "value": "EXPENSE", "source": "chip_selection"}],
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(executed_calls) == 1
    assert executed_calls[0].tool_name == "create_account"
    assert executed_calls[0].arguments["account_type"] == "EXPENSE"
