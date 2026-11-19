"""Hermetic integration tests for the 4 Frontier Conversational Modules (DOC-CFO-2026-FRONTIER-V1).

Governance:
- Overseen by Expert CFO + CA (skeptical audit mindset, Section 73/IFRS 16/IAS 16/ATL standards).
- Overseen by Senior DevOps Lead & AI Native Engineer (Python 3.12+, Pydantic v2, hermetic, zero live DB/network).

Covers:
1. Interactive In-Chat Artifacts & Bidirectional Visual Drafts (app/interactive_artifacts.py)
2. "What-If" Financial Simulation & Capitalization Sandboxing (app/financial_simulation.py)
3. Episodic Memory & Proactive Vendor Fingerprinting Guard (app/vendor_memory_guard.py)
4. Post-Transaction "Next Best Action" (NBA) & Virtual CFO Advisory (app/next_best_action.py)
5. Turn Enrichment Bridge (app/conversational_manager.py: enrich_frontier_metadata)
6. Schema Validation (app/models/schemas.py: AgentResponse, ConfirmationResponse)
"""

import uuid
import pytest
from app.interactive_artifacts import (
    build_interactive_artifact,
    apply_artifact_action,
)
from app.financial_simulation import (
    simulate_scenario,
    ScenarioType,
    FinancialSimulationResult,
)
from app.vendor_memory_guard import (
    lookup_vendor_fingerprint,
    check_duplicate_risk,
    DuplicateRiskLevel,
)
from app.next_best_action import (
    generate_next_best_actions,
    ActionCategory,
    ActionPriority,
)
from app.living_draft import build_living_draft
from app.conversational_manager import enrich_frontier_metadata
from app.models.schemas import AgentResponse, ConfirmationResponse, ExecutionStatus


# ---------------------------------------------------------------------------
# 1. Interactive In-Chat Artifacts & Bidirectional Visual Drafts
# ---------------------------------------------------------------------------

def test_interactive_artifacts_lifecycle_and_rebalancing():
    """Verify voucher artifact creation, reactive slider adjust, and WHT toggle."""
    draft = build_living_draft(
        intent="record_expense",
        entities={
            "transaction_nature": "FIXED_ASSET",
            "item_description": "Dell Latitude 5520",
            "amount": 200000.0,
            "vendor_name": "Dell Pakistan",
            "payment_channel": "bank_transfer",
            "bank_name": "Meezan Bank",
        },
        missing_fields=[],
    )

    art = build_interactive_artifact(draft)
    assert art is not None
    assert art.artifact_type == "interactive_voucher"
    assert len(art.controls) >= 3

    # Check account selector control
    account_ctrl = next((c for c in art.controls if c.control_type == "account_pill_selector"), None)
    assert account_ctrl is not None
    assert account_ctrl.account_pills is not None
    assert len(account_ctrl.account_pills) >= 4

    # Check slider control
    slider_ctrl = next((c for c in art.controls if c.control_type == "depreciation_slider"), None)
    assert slider_ctrl is not None
    assert slider_ctrl.slider is not None
    assert slider_ctrl.slider.current_value == 3  # default 3 years for IT

    # Action 1: Adjust depreciation slider from 3 to 5 years
    d2 = apply_artifact_action(
        draft,
        action_type="adjust_slider",
        action_payload={"slider_value": 5},
    )
    assert d2.depreciation_schedule is not None
    assert d2.depreciation_schedule.useful_life_years == 5
    # Annual depreciation = 200,000 / 5 = 40,000
    assert d2.depreciation_schedule.annual_depreciation == 40000.0

    # Action 2: Toggle WHT on
    d3 = apply_artifact_action(
        d2,
        action_type="toggle_wht",
        action_payload={"is_enabled": True, "rate_percent": 5.0},
    )
    # Check double-entry balance: total debit must equal total credit
    total_debit = sum(line.debit for line in d3.voucher_preview)
    total_credit = sum(line.credit for line in d3.voucher_preview)
    assert total_debit == total_credit == 200000.0
    # Must have withholding tax line
    wht_lines = [l for l in d3.voucher_preview if "Withholding" in l.account_name or "2120" in l.account_name]
    assert len(wht_lines) == 1
    assert wht_lines[0].credit == 10000.0  # 5% of 200k


# ---------------------------------------------------------------------------
# 2. "What-If" Financial Simulation & Capitalization Sandboxing
# ---------------------------------------------------------------------------

def test_what_if_financial_simulation_scenarios():
    """Verify Lease vs Buy, Section 73 Cash vs Bank, and Capitalize vs Expense."""
    # A: Lease vs Buy (IFRS 16)
    res_lease = simulate_scenario(scenario_type="lease_vs_buy", amount=1500000.0)
    assert isinstance(res_lease, FinancialSimulationResult)
    assert res_lease.scenario_type == ScenarioType.LEASE_VS_BUY
    assert len(res_lease.options) == 2
    assert "LEASE" in res_lease.options
    assert "BUY" in res_lease.options
    assert "IFRS 16" in res_lease.options["LEASE"].option_name
    assert res_lease.recommendation is not None
    assert len(res_lease.recommendation.cfo_action_plan) >= 2

    # B: Cash vs Bank (Section 73 ITO 2001)
    res_cash = simulate_scenario(scenario_type="cash_vs_bank", amount=100000.0)
    assert res_cash.scenario_type == ScenarioType.CASH_VS_BANK
    assert res_cash.tax_exposure is not None
    # 29% income tax penalty on 100,000 = 29,000
    assert round(res_cash.tax_exposure.corporate_tax_penalty, 0) == 29000.0
    # Must explicitly mandate banking channel
    assert res_cash.recommendation.verdict in ("MANDATORY_BANK_SETTLEMENT", "PREFER_BANK")

    # C: Capitalize vs Expense (IAS 16)
    res_capex = simulate_scenario(scenario_type="capitalize_vs_expense", amount=500000.0)
    assert res_capex.scenario_type == ScenarioType.CAPITALIZE_VS_EXPENSE
    assert len(res_capex.options) == 2
    assert res_capex.options["EXPENSE"].period_1_pl_charge != res_capex.options["CAPITALIZE"].period_1_pl_charge


# ---------------------------------------------------------------------------
# 3. Episodic Memory & Proactive Vendor Fingerprinting Guard
# ---------------------------------------------------------------------------

def test_vendor_memory_and_duplicate_guard():
    """Verify vendor fingerprint retrieval, 30-day ATL check, and 72-hour duplicate detection."""
    history = [
        {
            "vendor_name": "Apex Office Supplies",
            "payment_method": "BANK_TRANSFER",
            "bank_name": "Meezan Bank",
            "account_code": "5100",
            "wht_rate": 0.05,
            "atl_status": "ACTIVE",
            "atl_verified_at": "2026-03-01T10:00:00",
        },
        {
            "vendor_name": "Apex Office Supplies",
            "payment_method": "BANK_TRANSFER",
            "bank_name": "Meezan Bank",
            "account_code": "5100",
            "wht_rate": 0.05,
            "atl_status": "ACTIVE",
            "atl_verified_at": "2026-03-01T10:00:00",
        },
    ]

    # Fingerprint lookup
    fp = lookup_vendor_fingerprint(
        vendor_name="Apex Office Supplies",
        historical_records=history,
        as_of_date="2026-03-10",
    )
    assert fp is not None
    assert fp.customary_payment_method == "BANK"
    assert fp.standard_bank_name == "Meezan Bank"
    assert fp.wht_treatment is not None
    assert fp.wht_treatment.standard_wht_rate == 0.05
    assert fp.wht_treatment.is_atl_stale is False
    prompt = fp.suggest_terms_prompt()
    assert "Meezan Bank" in prompt
    assert "5% WHT" in prompt

    # 30-day ATL expiration check (CFO Mandate)
    fp_stale = lookup_vendor_fingerprint(
        vendor_name="Apex Office Supplies",
        historical_records=history,
        as_of_date="2026-04-15",  # > 30 days after March 1
    )
    assert fp_stale is not None
    assert fp_stale.wht_treatment.is_atl_stale is True

    # 72-hour Duplicate Check
    recent_txs = [
        {
            "vendor_name": "Apex Office Supplies",
            "amount": 75000.0,
            "invoice_ref": "INV-2026-099",
            "transaction_date": "2026-03-15T09:00:00",
            "payment_method": "BANK_TRANSFER",
        }
    ]

    # Duplicate invoice reference -> CRITICAL
    dup_res = check_duplicate_risk(
        vendor_name="Apex Office Supplies",
        amount=75000.0,
        invoice_ref="INV-2026-099",
        recent_transactions=recent_txs,
        reference_date="2026-03-15T14:00:00",
    )
    assert dup_res.risk_level in (DuplicateRiskLevel.CRITICAL, DuplicateRiskLevel.HIGH)
    assert dup_res.is_duplicate is True


# ---------------------------------------------------------------------------
# 4. Post-Transaction Next Best Action (NBA) & Virtual CFO Advisory
# ---------------------------------------------------------------------------

def test_next_best_action_and_virtual_cfo():
    """Verify Capex budget monitoring, statutory tax calendar, and runway calculation."""
    posted_tx = {
        "intent": "record_expense",
        "total": 150000.0,
        "amount": 150000.0,
        "vendor_name": "Hardware Hub",
        "payment_channel": "bank_transfer",
        "bank_name": "HBL",
        "date": "2026-03-24",
        "transaction_date": "2026-03-24",
        "wht_amount": 7500.0,
        "is_capex": True,
        "lines": [
            {"account_code": "1510", "debit": 150000.0, "credit": 0.0},
            {"account_code": "2120", "debit": 0.0, "credit": 7500.0},
            {"account_code": "1020", "debit": 0.0, "credit": 142500.0},
        ],
    }

    snapshot = {
        "budgets": {
            "capex": {
                "budget": 500000.0,
                "actual_mtd": 270000.0,
                "period": "Q2 2026",
            },
            "opex": {
                "budget": 800000.0,
                "actual_mtd": 650000.0,
                "period": "March 2026",
            },
        },
        "cash_flow": {
            "total_liquid_cash": 3000000.0,
        },
        "cash_runway": {
            "total_liquid_cash": 3000000.0,
            "monthly_burn_rate": 500000.0,
            "runway_months": 6.0,
        },
    }

    nba = generate_next_best_actions(posted_transaction=posted_tx, financial_snapshot=snapshot)
    assert len(nba.items) >= 3

    # Must contain Budget headroom check (270k + 150k = 420k / 500k = 84% burn)
    budget_items = [it for it in nba.items if it.category == ActionCategory.BUDGET]
    assert len(budget_items) >= 1
    assert "84.0%" in budget_items[0].executive_summary
    assert "80,000.00" in budget_items[0].executive_summary

    # Must contain Statutory Tax Calendar (15th of next month for Section 153 WHT)
    tax_items = [it for it in nba.items if it.category == ActionCategory.TAX_COMPLIANCE]
    assert len(tax_items) >= 1
    assert any("15" in (it.deadline_date or "") for it in tax_items)


# ---------------------------------------------------------------------------
# 5. Turn Enrichment Bridge & Response Schema Integration
# ---------------------------------------------------------------------------

def test_enrich_frontier_metadata_and_agent_response():
    """Verify unified enrichment bridge output and Pydantic v2 schema compliance."""
    draft = build_living_draft(
        intent="record_expense",
        entities={"amount": 350000.0, "vendor_name": "Dell Pakistan"},
        missing_fields=[],
    )

    enriched = enrich_frontier_metadata(
        user_message="Could you simulate lease vs buy for this laptop fleet?",
        living_draft=draft.to_dict(),
        entities={"amount": 350000.0, "vendor_name": "Dell Pakistan"},
        intent="record_expense",
        is_completed=True,
    )

    # All 4 capabilities must be populated
    assert enriched["interactive_artifacts"] is not None
    assert len(enriched["interactive_artifacts"]) == 1
    assert enriched["simulations"] is not None
    assert len(enriched["simulations"]) == 1
    assert enriched["vendor_insights"] is not None
    assert enriched["next_best_actions"] is not None
    assert len(enriched["next_best_actions"]) >= 1

    # Verify Pydantic v2 AgentResponse round-trip serialization
    resp = AgentResponse(
        status=ExecutionStatus.COMPLETED,
        execution_id=uuid.uuid4(),
        summary="Expense recorded successfully.",
        action="record_expense",
        living_draft=draft.to_dict(),
        interactive_artifacts=enriched["interactive_artifacts"],
        simulations=enriched["simulations"],
        vendor_insights=enriched["vendor_insights"],
        next_best_actions=enriched["next_best_actions"],
    )

    dumped = resp.model_dump()
    assert dumped["interactive_artifacts"] is not None
    assert dumped["simulations"] is not None
    assert dumped["vendor_insights"] is not None
    assert dumped["next_best_actions"] is not None

    # Verify ConfirmationResponse
    conf = ConfirmationResponse(
        execution_id=uuid.uuid4(),
        action="record_expense",
        living_draft=draft.to_dict(),
        interactive_artifacts=enriched["interactive_artifacts"],
        simulations=enriched["simulations"],
        vendor_insights=enriched["vendor_insights"],
    )
    conf_dump = conf.model_dump()
    assert conf_dump["status"] == "AWAITING_CONFIRMATION"
    assert conf_dump["interactive_artifacts"] is not None
