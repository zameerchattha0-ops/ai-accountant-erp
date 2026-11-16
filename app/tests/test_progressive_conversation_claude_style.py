"""Unit & Integration Tests for Claude-Style LLM-First Natural Conversational Accounting Agent
========================================================================================
Validates the implementation of the 3 user-selected pillars:
1. Decision 1 (Option A): Single focused high-leverage question at a time with smart accounting defaults
   (e.g., 5-year straight line for furniture, 3-year for computers) instead of multi-question form dumps.
2. Decision 2 (Option A): Real-time Living Draft Voucher Card in UI sidebar/preview pane
   (`AgentResponse.living_draft` and `AgentResponse.data["living_draft"]`).
3. Decision 3: Mid-flow consultative question answering (Section 73 cash limits, Section 153 WHT,
   IAS 16 capitalization) and seamless absorption of out-of-order corrections without questionnaire schema failures.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

import app.agent as agent_mod
from app.consultative_advisory import get_consultative_advice, is_consultative_query
from app.conversational_manager import (
    expand_standard_schedule_answers,
    extract_conversational_corrections,
    format_claude_style_progressive_question,
    is_standard_schedule_acceptance,
)
from app.living_draft import build_living_draft
from app.models.schemas import AgentResponse, ExecutionPlan, ExecutionStatus


# ============================================================================
# 1. Decision 1 (Option A): Progressive Single-Question Pacing & Smart Defaults
# ============================================================================

class TestProgressivePacingAndSmartDefaults:
    """Verifies that progressive clarification asks one focused question with smart corporate defaults."""

    def test_fixed_asset_schedule_focus_with_smart_defaults(self):
        """Fixed asset with missing depreciation fields produces a single consultative question with 5-year default."""
        prompt, chips, options = format_claude_style_progressive_question(
            intent="register_fixed_asset",
            missing_fields=["useful_life_years", "depreciation_method", "salvage_value"],
            entities={
                "item_description": "executive tables",
                "quantity": 5,
                "amount": 150000.0,
                "supplier_name": "Apex Supplies",
            },
            nature="FIXED_ASSET",
        )

        # Consultative, natural Claude-style framing:
        assert "executive tables" in prompt
        assert "5-year straight-line depreciation" in prompt or "useful life" in prompt
        assert "Would you like to apply this" in prompt or "adopt" in prompt or "schedule" in prompt.lower()
        # High-leverage quick-reply chips:
        assert len(chips) >= 2
        assert any("Straight Line" in c or "Standard" in c or "5 Years" in c for c in chips)

    def test_computer_equipment_gets_3_year_default(self):
        """Computers and IT equipment automatically default to 3-year straight line."""
        prompt, chips, _ = format_claude_style_progressive_question(
            intent="register_fixed_asset",
            missing_fields=["useful_life_years", "depreciation_method"],
            entities={"item_description": "Dell XPS Laptops", "amount": 300000.0},
            nature="FIXED_ASSET",
        )
        assert "Dell XPS Laptops" in prompt
        assert "3-year" in prompt
        assert "straight-line" in prompt.lower()

    def test_standard_schedule_acceptance_triggers(self):
        """Standard schedule acceptance recognizes various human affirmative expressions."""
        assert is_standard_schedule_acceptance("Standard schedule is fine")
        assert is_standard_schedule_acceptance("yes")
        assert is_standard_schedule_acceptance("proceed")
        assert is_standard_schedule_acceptance("standard")
        assert is_standard_schedule_acceptance("use standard schedule")
        assert is_standard_schedule_acceptance("slm")
        assert is_standard_schedule_acceptance("1")
        assert is_standard_schedule_acceptance("(1)")

    def test_expand_standard_schedule_populates_all_three_fields(self):
        """Accepting the standard schedule unpacks useful_life_years, method, and zero salvage."""
        expanded = expand_standard_schedule_answers(
            "standard schedule is fine",
            {"item_description": "studio desks"},
        )
        assert expanded is not None
        assert expanded["useful_life_years"] == 5
        assert expanded["depreciation_method"] == "STRAIGHT_LINE"
        assert expanded["salvage_value"] == 0.0

    def test_missing_payment_method_recommends_bank_over_50k(self):
        """When payment method is missing and amount > 50,000, prompts for payment and recommends bank transfer."""
        prompt, chips, _ = format_claude_style_progressive_question(
            intent="record_purchase",
            missing_fields=["payment_method"],
            entities={"amount": 75000.0, "item_description": "Raw Material"},
        )
        assert "Section 73" in prompt or "50,000" in prompt
        assert "Bank Transfer" in prompt or any("Bank Transfer" in c for c in chips)


# ============================================================================
# 2. Decision 2 (Option A): Real-Time Living Draft Voucher Card
# ============================================================================

class TestLivingDraftVoucherCard:
    """Verifies that Living Draft constructs balanced, audit-ready voucher cards for the sidebar/preview pane."""

    def test_build_living_draft_fixed_asset_balanced_double_entry(self):
        """Living draft creates balanced Dr/Cr lines, depreciation summary, and counterparty details."""
        draft = build_living_draft(
            intent="register_fixed_asset",
            entities={
                "item_description": "5 Studio Tables",
                "quantity": 5,
                "amount": 150000.0,
                "supplier_name": "Apex Supplies",
                "payment_channel": "bank_transfer",
                "bank_name": "Meezan Bank",
                "useful_life_years": 5,
                "depreciation_method": "STRAIGHT_LINE",
            },
            missing_fields=[],
            nature="FIXED_ASSET",
        )

        d_dict = draft.to_dict()
        assert d_dict["total_amount"] == 150000.0
        assert d_dict["payment_channel"] == "bank_transfer"
        assert d_dict["status"] in ("ready_for_confirmation", "READY_TO_POST", "drafting")

        # Double-entry balance check:
        lines = d_dict.get("voucher_preview") or d_dict.get("voucher_lines") or []
        assert len(lines) >= 2
        total_dr = sum(float(ln.get("debit") if isinstance(ln, dict) else ln.debit or 0.0) for ln in lines)
        total_cr = sum(float(ln.get("credit") if isinstance(ln, dict) else ln.credit or 0.0) for ln in lines)
        assert total_dr == total_cr == 150000.0

        # Depreciation preview check:
        dep = d_dict["depreciation_schedule"]
        assert dep is not None
        assert dep["useful_life_years"] in (3, 5)

    def test_living_draft_emits_section_73_warning_for_cash_over_50k(self):
        """Cash payments over 50k trigger Section 73 warning in living draft compliance notes."""
        draft = build_living_draft(
            intent="record_purchase",
            entities={
                "item_description": "Office Supplies",
                "amount": 80000.0,
                "payment_channel": "cash",
                "supplier_name": "Paper Mart",
            },
            missing_fields=[],
            nature="CONSUMABLE",
        )
        d_dict = draft.to_dict()
        notes = " ".join(d_dict.get("compliance_notes") or [])
        assert "Section 73" in notes
        assert "50,000" in notes


# ============================================================================
# 3. Decision 3: Mid-Flow Consultative Q&A and Out-of-Order Corrections
# ============================================================================

class TestConsultativeAdvisoryAndCorrections:
    """Verifies that mid-flow consultative questions are answered and corrections absorbed cleanly."""

    def test_detect_consultative_tax_and_accounting_queries(self):
        """Correctly identifies user queries asking for tax or accounting guidance."""
        assert is_consultative_query("What is the cash limit under tax law?")
        assert is_consultative_query("Can we expense this instead of capitalizing?")
        assert is_consultative_query("What is Section 73?")
        assert is_consultative_query("What is the withholding tax on services?")
        assert is_consultative_query("What depreciation rate applies to computers?")
        assert not is_consultative_query("Recorded 5 chairs from Apex for 50000")

    def test_section_73_statutory_advisory_content(self):
        """Advisory response cites Section 73(1), PKR 50,000 limit, crossed banking mandate, and disallowance."""
        advice = get_consultative_advice("What is the cash limit under Section 73?")
        assert advice is not None
        assert "Section 73" in advice
        assert "50,000" in advice
        assert "banking channel" in advice.lower() or "bank transfer" in advice.lower()
        assert "disallowed" in advice.lower()

    def test_section_153_wht_advisory_content(self):
        """Advisory response explains goods (5%/10%) vs services and withholding rules."""
        advice = get_consultative_advice("How much is the withholding tax under section 153?")
        assert advice is not None
        assert "Section 153" in advice
        assert "5.0%" in advice
        assert "Tenth Schedule" in advice or "Non-Filers" in advice or "withholding" in advice.lower()

    def test_extract_conversational_corrections_quantity_and_bank(self):
        """Seamlessly extracts out-of-order corrections: new quantity, recalculates amount, and sets bank."""
        entities = {
            "item_description": "studio chairs",
            "quantity": 5.0,
            "amount": 100000.0,
            "payment_method": "CASH",
        }
        corrections = extract_conversational_corrections(
            "Actually make that 3 chairs instead of 5, and we paid via Meezan Bank, not cash.",
            entities,
        )
        assert corrections["quantity"] == 3.0
        assert corrections["amount"] == 60000.0  # (100k / 5) * 3
        assert corrections["payment_method"] == "BANK"
        assert corrections["bank_name"] == "Meezan Bank"


# ============================================================================
# 4. End-to-End Agent Clarification Turn (Hermetically Mocked)
# ============================================================================

class TestAgentConversationalIntegration:
    """Verifies that AgentResponse carries living_draft and provides Claude-style progressive interaction."""

    @pytest.mark.asyncio
    async def test_agent_clarification_response_carries_living_draft(self, monkeypatch):
        """When agent parks for clarification, response includes living_draft in both attribute and data dict."""
        from app.models.schemas import ExecutionPlan, TransactionClassification

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        fake_session = {
            "id": str(session_id),
            "session_id": str(session_id),
            "organization_id": str(org_id),
            "status": "awaiting_clarification",
            "user_id": str(user_id),
            "created_at": "2026-11-16T12:00:00Z",
        }

        # Mock database seams to keep test strictly hermetic
        monkeypatch.setattr(agent_mod, "fetch_one", AsyncMock(return_value=fake_session))
        monkeypatch.setattr(agent_mod, "fetch_many", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_mod, "create_execution_session", AsyncMock(return_value=fake_session))
        monkeypatch.setattr(agent_mod, "_close_superseded_sessions", AsyncMock(return_value=0))
        monkeypatch.setattr(agent_mod, "seed_clarification_history", AsyncMock())
        monkeypatch.setattr(agent_mod, "_load_org_preferences", AsyncMock(return_value={}))
        monkeypatch.setattr(agent_mod, "resolve_confirmation", AsyncMock(return_value={}))
        monkeypatch.setattr(agent_mod, "get_clarification_history", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_mod, "_update_status", AsyncMock())
        monkeypatch.setattr(agent_mod, "_log_step", AsyncMock())
        monkeypatch.setattr(agent_mod, "flush_step_logs", AsyncMock())
        monkeypatch.setattr(agent_mod, "create_clarification", AsyncMock(return_value={"id": "clar-1", "question": "Clarify schedule"}))
        monkeypatch.setattr(agent_mod, "create_execution_result", AsyncMock(return_value={"id": "res-1"}))
        monkeypatch.setattr(agent_mod, "build_context", AsyncMock(return_value=AsyncMock(current_user=None, organization=None)))

        # Plan requiring fixed asset clarification:
        def _fake_plan(*args, **kwargs):
            return ExecutionPlan(
                intent="register_fixed_asset",
                requires_clarification=True,
                missing_fields=["useful_life_years", "depreciation_method"],
                clarification_questions=["What is the useful life and depreciation method?"],
                extracted_entities={
                    "item_description": "5 studio tables",
                    "quantity": 5,
                    "amount": 150000.0,
                    "supplier_name": "Apex Supplies",
                    "payment_method": "BANK",
                    "transaction_nature": "FIXED_ASSET",
                },
            )

        monkeypatch.setattr(agent_mod, "run_planner", _fake_plan)

        async def _fake_classify(*args, **kwargs):
            return TransactionClassification(
                transaction_nature="FIXED_ASSET",
                confidence="HIGH",
                requires_clarification=False,
            )

        monkeypatch.setattr("app.classifier.classify_transaction", _fake_classify)

        response = await agent_mod.execute(
            user_message="Digital Creators bought 5 studio tables for 150000 from Apex Supplies",
            user_id=user_id,
            organization_id=org_id,
        )

        assert response.status == ExecutionStatus.AWAITING_CLARIFICATION
        assert response.requires_user_input is True

        # Decision 2 (Option A): Real-time living draft preview card present:
        assert response.living_draft is not None
        assert response.data is not None
        assert "living_draft" in response.data
        assert response.data["living_draft"]["total_amount"] == 150000.0

        # Decision 1 (Option A): Progressive question asks about standard schedule:
        assert response.question is not None
        assert "5-year" in response.question or "depreciation" in response.question.lower() or "schedule" in response.question.lower()

        # Questionnaire contract preserved for backward compatibility:
        assert response.questionnaire is not None
        assert "questions" in response.questionnaire
