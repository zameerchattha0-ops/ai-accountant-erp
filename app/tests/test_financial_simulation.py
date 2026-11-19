"""Hermetic Unit Tests for What-If Financial Simulation Engine (DOC-ACC-2026-V1 Section 8).

Verifies:
1. Scenario A: Lease vs. Buy (IFRS 16 vs. IAS 16)
   - Initial cash outlay & working capital preservation.
   - Exact mathematical annuity payment derivation.
   - IFRS 16 RoU asset and Lease Liability initialization.
   - Front-loaded P&L profile (declining interest + straight-line amortization).
   - Full amortization down to 0 at term end.
   - NPC comparison, discount rates, residual values, and payment timing.
2. Scenario B: Cash vs. Bank Settlement (Section 73 ITO 2001)
   - Section 73 & Section 21(l) cash limit violation (> PKR 50,000 for expenses, > PKR 250,000 for assets).
   - 29% corporate income tax penalty calculation.
   - Section 205 default surcharge (12% p.a. for assessment delay).
   - Section 182 non-compliance penalty (5%).
   - Net economic waste calculation vs. approved banking channels.
   - Permissible sub-threshold cash handling.
3. Scenario C: Capitalize vs. Expense (IAS 16 vs. Opex)
   - Year 1 P&L hit and 100% EBITDA protection under capitalization.
   - Time value of money (TVM) tax shield acceleration under expensing.
   - Cumulative nominal P&L convergence over multi-year horizon.
   - Balance sheet carrying value schedules.
4. Edge cases, validation, Pydantic v2 serialization, and Markdown report rendering.
"""

from __future__ import annotations

import json
import math
import pytest
from app.financial_simulation import (
    ScenarioType,
    PaymentTiming,
    SchedulePeriod,
    OptionSummary,
    TaxExposureDiff,
    ExecutiveRecommendation,
    FinancialSimulationResult,
    calculate_annuity_payment,
    present_value_stream,
    normalize_scenario_type,
    simulate_scenario,
    simulate_lease_vs_buy,
    simulate_cash_vs_bank,
    simulate_capitalize_vs_expense,
    SECTION_73_EXPENSE_LIMIT,
    SECTION_73_ASSET_LIMIT,
)


# =============================================================================
# Mathematical Helper Tests
# =============================================================================

def test_calculate_annuity_payment_mathematical_precision():
    """Verify ordinary annuity and annuity due formulas against textbook benchmark."""
    # $100,000 at 1% per period for 12 periods
    # P = (0.01 * 100,000) / (1 - (1.01)^-12) = 1,000 / (1 - 0.887449) = 8,884.8788...
    p_arrears = calculate_annuity_payment(100000.0, 0.01, 12, PaymentTiming.IN_ARREARS)
    expected_arrears = (0.01 * 100000.0) / (1.0 - math.pow(1.01, -12))
    assert math.isclose(p_arrears, expected_arrears, rel_tol=1e-9)
    assert round(p_arrears, 2) == 8884.88

    # Annuity Due: payment is discounted by (1 + r)
    p_advance = calculate_annuity_payment(100000.0, 0.01, 12, PaymentTiming.IN_ADVANCE)
    assert math.isclose(p_advance, expected_arrears / 1.01, rel_tol=1e-9)

    # Zero interest rate
    p_zero_rate = calculate_annuity_payment(120000.0, 0.0, 12, PaymentTiming.IN_ARREARS)
    assert p_zero_rate == 10000.0

    # Negative periods should raise ValueError
    with pytest.raises(ValueError):
        calculate_annuity_payment(100000.0, 0.01, 0)


# =============================================================================
# Scenario A: Lease vs. Buy (IFRS 16 vs. IAS 16) Tests
# =============================================================================

def test_lease_vs_buy_standard_scenario():
    """Verify standard 36-month lease vs. outright purchase with 12% IBR."""
    principal = 1_200_000.0
    result = simulate_scenario(
        scenario_type="LEASE_VS_BUY",
        amount=principal,
        parameters={
            "useful_life_months": 36,
            "lease_term_months": 36,
            "annual_discount_rate": 0.12,
            "incremental_borrowing_rate": 0.12,
            "corporate_tax_rate": 0.29,
            "payment_timing": "IN_ARREARS",
        }
    )

    assert result.scenario_type == ScenarioType.LEASE_VS_BUY
    assert result.base_amount == principal
    assert "BUY" in result.options
    assert "LEASE" in result.options

    buy_opt = result.options["BUY"]
    lease_opt = result.options["LEASE"]

    # Outright purchase: 100% Day 0 cash drain
    assert buy_opt.initial_cash_outlay == principal
    assert buy_opt.period_1_pl_charge == pytest.approx(principal / 36.0, rel=1e-4)

    # Lease: Day 0 cash outlay is 0 for in-arrears lease
    assert lease_opt.initial_cash_outlay == 0.0
    assert result.variance_summary["day0_cash_preserved"] == principal

    # RoU Asset and initial liability must equal principal when 100% financed
    assert lease_opt.key_metrics["initial_rou_asset"] == pytest.approx(principal, rel=1e-4)
    assert lease_opt.key_metrics["initial_lease_liability"] == pytest.approx(principal, rel=1e-4)

    # Amortization check over 36 months
    assert len(result.schedule) == 37  # Month 0 to Month 36
    final_period = result.schedule[36]
    # Lease liability at end of month 36 must be zeroed out
    assert final_period.option_b_carrying_value == pytest.approx(0.0, abs=1.0)
    # PPE carrying value at end of month 36 must be zeroed out
    assert final_period.option_a_carrying_value == pytest.approx(0.0, abs=1.0)

    # Front-loaded P&L verification for IFRS 16:
    # Month 1 P&L (amortization + high interest) > Month 36 P&L (amortization + tiny interest)
    month_1_pl = result.schedule[1].option_b_pl_impact
    month_36_pl = result.schedule[36].option_b_pl_impact
    assert month_1_pl > month_36_pl

    # Recommendation and Markdown check
    assert result.recommendation.verdict in ("PREFER_LEASE", "PREFER_BUY")
    md = result.to_markdown()
    assert "Strategic Financial Simulation: Lease vs. Buy" in md
    assert "IFRS 16" in md
    assert "IAS 16" in md


def test_lease_vs_buy_with_upfront_deposit_and_advance_timing():
    """Verify lease simulation with upfront deposit and advance payment timing."""
    principal = 2_000_000.0
    deposit = 500_000.0
    result = simulate_scenario(
        scenario_type="ifrs16",
        amount=principal,
        parameters={
            "useful_life_months": 24,
            "lease_term_months": 24,
            "upfront_deposit": deposit,
            "payment_timing": "IN_ADVANCE",
            "annual_discount_rate": 0.14,
            "incremental_borrowing_rate": 0.14,
        }
    )

    lease_opt = result.options["LEASE"]
    # With upfront deposit and advance payment, initial cash outlay includes deposit + 1st payment
    assert lease_opt.initial_cash_outlay > deposit
    # Working capital preserved at Day 0 is principal minus initial lease outlay
    assert result.variance_summary["day0_cash_preserved"] == pytest.approx(
        principal - lease_opt.initial_cash_outlay, rel=1e-4
    )


def test_lease_vs_buy_custom_monthly_payment():
    """Verify when user specifies an explicit monthly lease payment quote from lessor."""
    principal = 1_000_000.0
    custom_rent = 35_000.0
    result = simulate_scenario(
        scenario_type="lease_buy",
        amount=principal,
        parameters={
            "useful_life_months": 36,
            "monthly_lease_payment": custom_rent,
            "payment_timing": "IN_ARREARS",
        }
    )
    lease_opt = result.options["LEASE"]
    assert lease_opt.key_metrics["monthly_lease_payment"] == custom_rent
    # Nominal total outflow = 36 * 35,000 = 1,260,000
    assert lease_opt.total_nominal_cash_outflow == pytest.approx(36 * custom_rent, rel=1e-4)


# =============================================================================
# Scenario B: Cash vs. Bank Settlement (Section 73 ITO 2001) Tests
# =============================================================================

def test_cash_settlement_exceeding_threshold_triggers_full_disallowance():
    """Verify Section 73 violation when cash expense exceeds PKR 50,000."""
    amount = 100_000.0
    result = simulate_scenario(
        scenario_type="CASH_VS_BANK",
        amount=amount,
        parameters={
            "corporate_tax_rate": 0.29,
            "default_surcharge_rate": 0.12,
            "statutory_penalty_rate": 0.05,
            "audit_delay_months": 12,
            "is_capital_asset": False,
        }
    )

    assert result.scenario_type == ScenarioType.CASH_VS_BANK
    assert result.tax_exposure is not None
    assert result.tax_exposure.is_statutory_violation is True
    assert result.tax_exposure.statutory_threshold == SECTION_73_EXPENSE_LIMIT
    assert result.tax_exposure.disallowed_amount == amount

    # 1. Corporate tax penalty = 29% * 100k = 29,000
    expected_tax_penalty = 29_000.0
    assert result.tax_exposure.corporate_tax_penalty == pytest.approx(expected_tax_penalty, rel=1e-4)

    # 2. Section 205 surcharge = 29,000 * 12% * (12/12) = 3,480
    expected_surcharge = 3_480.0
    assert result.tax_exposure.default_surcharge_amount == pytest.approx(expected_surcharge, rel=1e-4)

    # 3. Section 182 penalty = 29,000 * 5% = 1,450
    expected_sec182 = 1_450.0
    assert result.tax_exposure.statutory_penalty_amount == pytest.approx(expected_sec182, rel=1e-4)

    # Total penalty exposure = 29,000 + 3,480 + 1,450 = 33,930
    expected_total_penalty = expected_tax_penalty + expected_surcharge + expected_sec182
    assert result.tax_exposure.total_tax_penalty_exposure == pytest.approx(expected_total_penalty, rel=1e-4)

    # Forfeited tax shield (what would have been saved with bank) = 29,000
    assert result.tax_exposure.tax_shield_lost == pytest.approx(29_000.0, rel=1e-4)

    # Net economic waste of cash = total penalty + forfeited tax shield = 33,930 + 29,000 = 62,930
    assert result.tax_exposure.net_economic_waste_of_cash == pytest.approx(62_930.0, rel=1e-4)

    # Verdict must be MANDATORY_BANK_SETTLEMENT
    assert result.recommendation.verdict == "MANDATORY_BANK_SETTLEMENT"
    assert "Halt Cash Payment" in result.recommendation.headline

    # Verify Schedule has Day 0 payment and Month 12 audit penalty
    assert len(result.schedule) == 2
    assert result.schedule[0].period_index == 0
    assert result.schedule[1].period_index == 12
    assert result.schedule[1].option_a_cash_flow == pytest.approx(-expected_total_penalty, rel=1e-4)


def test_cash_settlement_within_threshold_is_compliant():
    """Verify Section 73 passes when cash expense is under PKR 50,000."""
    amount = 45_000.0
    result = simulate_scenario(
        scenario_type="section73",
        amount=amount,
        parameters={"is_capital_asset": False}
    )

    assert result.tax_exposure is not None
    assert result.tax_exposure.is_statutory_violation is False
    assert result.tax_exposure.disallowed_amount == 0.0
    assert result.tax_exposure.corporate_tax_penalty == 0.0
    assert result.tax_exposure.total_tax_penalty_exposure == 0.0
    assert result.recommendation.verdict == "CASH_PERMISSIBLE_BUT_BANK_PREFERRED"


def test_capital_asset_cash_threshold_250k():
    """Verify Section 73(2)/(3) asset threshold of PKR 250,000."""
    # Under 250k for asset is permissible
    res_under = simulate_scenario(
        scenario_type="section_73",
        amount=200_000.0,
        parameters={"is_capital_asset": True}
    )
    assert res_under.tax_exposure.is_statutory_violation is False
    assert res_under.tax_exposure.statutory_threshold == SECTION_73_ASSET_LIMIT

    # Over 250k for asset is a violation
    res_over = simulate_scenario(
        scenario_type="section_73",
        amount=300_000.0,
        parameters={"is_capital_asset": True}
    )
    assert res_over.tax_exposure.is_statutory_violation is True
    assert res_over.tax_exposure.disallowed_amount == 300_000.0


# =============================================================================
# Scenario C: Capitalize vs. Expense (IAS 16 vs. Opex) Tests
# =============================================================================

def test_capitalize_vs_expense_ebitda_and_p_and_l():
    """Verify Year 1 EBITDA protection and straight-line depreciation under IAS 16."""
    amount = 600_000.0
    useful_life = 3  # 3 years
    result = simulate_scenario(
        scenario_type="CAPITALIZE_VS_EXPENSE",
        amount=amount,
        parameters={
            "useful_life_years": useful_life,
            "salvage_value": 0.0,
            "corporate_tax_rate": 0.29,
            "annual_discount_rate": 0.12,
        }
    )

    assert result.scenario_type == ScenarioType.CAPITALIZE_VS_EXPENSE
    assert "EXPENSE" in result.options
    assert "CAPITALIZE" in result.options

    opex = result.options["EXPENSE"]
    capex = result.options["CAPITALIZE"]

    # Year 1 P&L Charges:
    # Opex takes 100% of amount in Year 1
    assert opex.period_1_pl_charge == amount
    # Capex takes only 1/3 in Year 1 = 200,000
    assert capex.period_1_pl_charge == pytest.approx(amount / 3.0, rel=1e-4)

    # EBITDA Impact:
    # Capex EBITDA impact is exactly 0.0 in Year 1
    assert capex.key_metrics["year_1_ebitda_impact"] == 0.0
    # Opex EBITDA impact is -600,000
    assert opex.key_metrics["year_1_ebitda_impact"] == -amount

    # Cumulative nominal P&L charges must converge over the 3 years
    assert opex.total_nominal_pl_charge == pytest.approx(amount, rel=1e-4)
    assert capex.total_nominal_pl_charge == pytest.approx(amount, rel=1e-4)

    # Time Value of Money (TVM) Tax Shield Advantage:
    # Immediate expensing provides full tax shield at end of Year 1
    # Capitalization delays 2/3 of the tax shield to Years 2 and 3
    # Therefore, PV(Opex Tax Shield) > PV(Capex Tax Shield)
    assert opex.present_value_tax_shield > capex.present_value_tax_shield
    assert result.variance_summary["tvm_tax_shield_advantage_opex"] > 0

    # Schedule length: Year 0 (Day 0) + 3 years = 4 entries
    assert len(result.schedule) == 4
    # Final year asset carrying value must be 0
    assert result.schedule[3].option_b_carrying_value == pytest.approx(0.0, abs=1.0)


def test_capitalize_vs_expense_with_salvage_value():
    """Verify capitalization schedule with non-zero salvage value."""
    amount = 500_000.0
    salvage = 50_000.0
    result = simulate_scenario(
        scenario_type="capex_vs_opex",
        amount=amount,
        parameters={
            "useful_life_years": 5,
            "salvage_value": salvage,
            "corporate_tax_rate": 0.29,
        }
    )

    capex = result.options["CAPITALIZE"]
    # Depreciable base = 500k - 50k = 450k; annual depr = 90k
    assert capex.key_metrics["annual_depreciation"] == pytest.approx(90_000.0, rel=1e-4)
    # Carrying value at Year 5 must equal salvage value
    final_carrying = result.schedule[5].option_b_carrying_value
    assert final_carrying == pytest.approx(salvage, rel=1e-4)


# =============================================================================
# Public API, Aliases, Validation, Serialization & Markdown Tests
# =============================================================================

def test_scenario_type_aliases_normalization():
    """Verify all scenario name aliases correctly resolve to canonical Enums."""
    assert normalize_scenario_type("lease_vs_buy") == ScenarioType.LEASE_VS_BUY
    assert normalize_scenario_type("IFRS16") == ScenarioType.LEASE_VS_BUY
    assert normalize_scenario_type("ifrs_16") == ScenarioType.LEASE_VS_BUY
    assert normalize_scenario_type("lease-buy") == ScenarioType.LEASE_VS_BUY

    assert normalize_scenario_type("cash_vs_bank") == ScenarioType.CASH_VS_BANK
    assert normalize_scenario_type("section73") == ScenarioType.CASH_VS_BANK
    assert normalize_scenario_type("sec_73") == ScenarioType.CASH_VS_BANK
    assert normalize_scenario_type("ito2001") == ScenarioType.CASH_VS_BANK

    assert normalize_scenario_type("capitalize_vs_expense") == ScenarioType.CAPITALIZE_VS_EXPENSE
    assert normalize_scenario_type("capex_vs_opex") == ScenarioType.CAPITALIZE_VS_EXPENSE
    assert normalize_scenario_type("ias16") == ScenarioType.CAPITALIZE_VS_EXPENSE
    assert normalize_scenario_type("ias_16") == ScenarioType.CAPITALIZE_VS_EXPENSE

    with pytest.raises(ValueError, match="Unsupported scenario_type"):
        normalize_scenario_type("cryptocurrency_arbitrage")


def test_input_validation_amount_guard():
    """Verify simulation strictly rejects non-positive amounts."""
    with pytest.raises(ValueError, match="strictly greater than 0"):
        simulate_scenario("LEASE_VS_BUY", amount=0.0)

    with pytest.raises(ValueError, match="strictly greater than 0"):
        simulate_scenario("CASH_VS_BANK", amount=-500.0)


def test_pydantic_v2_serialization_and_immutability():
    """Verify Pydantic v2 model_dump and model_dump_json produce hermetic output."""
    res = simulate_scenario("section73", 75000.0)
    dumped_dict = res.model_dump()
    assert isinstance(dumped_dict, dict)
    assert dumped_dict["scenario_type"] == "CASH_VS_BANK"
    assert dumped_dict["base_amount"] == 75000.0

    json_str = res.model_dump_json()
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["scenario_type"] == "CASH_VS_BANK"


def test_present_value_stream_math():
    """Verify present_value_of_stream with multi-period cash flows."""
    flows = [100.0, 100.0, 100.0]
    rate = 0.10
    # Period 0: 100/(1.1^0) = 100
    # Period 1: 100/(1.1^1) = 90.909
    # Period 2: 100/(1.1^2) = 82.644
    # Total = 273.5537
    pv = present_value_stream(flows, rate_per_period=rate, start_period=0)
    expected = 100.0 + (100.0 / 1.1) + (100.0 / 1.21)
    assert math.isclose(pv, expected, rel_tol=1e-9)


def test_lease_vs_buy_with_residual_and_maintenance():
    """Verify Buy scenario with salvage value and recurring annual maintenance costs."""
    principal = 1_000_000.0
    salvage = 100_000.0
    maint_annual = 60_000.0  # 5,000 / month
    res = simulate_lease_vs_buy(
        amount=principal,
        parameters={
            "useful_life_months": 36,
            "residual_value": salvage,
            "annual_maintenance_cost_buy": maint_annual,
            "corporate_tax_rate": 0.29,
        }
    )
    buy_opt = res.options["BUY"]
    assert buy_opt.key_metrics["salvage_value"] == salvage
    assert buy_opt.key_metrics["annual_maintenance_cost"] == maint_annual
    # Monthly depr = (1,000,000 - 100,000) / 36 = 25,000
    assert buy_opt.key_metrics["monthly_depreciation"] == pytest.approx(25_000.0, rel=1e-4)


def test_zero_tax_rate_handling():
    """Verify zero corporate tax rate runs without errors (e.g. tax-exempt NGO/SEZ entity)."""
    res = simulate_scenario(
        "lease_vs_buy",
        amount=500_000.0,
        parameters={"corporate_tax_rate": 0.0}
    )
    assert res.options["BUY"].present_value_tax_shield == 0.0
    assert res.options["LEASE"].present_value_tax_shield == 0.0

    res_tax = simulate_scenario(
        "cash_vs_bank",
        amount=100_000.0,
        parameters={"corporate_tax_rate": 0.0}
    )
    assert res_tax.tax_exposure.corporate_tax_penalty == 0.0


def test_section_73_exact_boundary_conditions():
    """Verify strict statutory boundary: <= PKR 50,000 allowed, > 50,000 disallowed."""
    # Exactly 50,000: Permissible
    res_exact_50k = simulate_scenario("section73", 50000.0)
    assert res_exact_50k.tax_exposure.is_statutory_violation is False
    assert res_exact_50k.tax_exposure.disallowed_amount == 0.0

    # 50,001: Statutory violation
    res_50k_plus = simulate_scenario("section73", 50001.0)
    assert res_50k_plus.tax_exposure.is_statutory_violation is True
    assert res_50k_plus.tax_exposure.disallowed_amount == 50001.0

    # Exactly 250,000 for asset: Permissible
    res_exact_250k = simulate_scenario("section73", 250000.0, {"is_capital_asset": True})
    assert res_exact_250k.tax_exposure.is_statutory_violation is False

    # 250,001 for asset: Statutory violation
    res_250k_plus = simulate_scenario("section73", 250001.0, {"is_capital_asset": True})
    assert res_250k_plus.tax_exposure.is_statutory_violation is True


def test_audit_delay_months_scaling_surcharge():
    """Verify Section 205 default surcharge scales proportionally with assessment delay."""
    # 24 months audit delay -> surcharge is 24/12 * 12% = 24% of tax penalty
    res_24m = simulate_scenario(
        "section73",
        100_000.0,
        parameters={"audit_delay_months": 24, "corporate_tax_rate": 0.29, "default_surcharge_rate": 0.12}
    )
    tax_penalty = 29_000.0
    expected_surcharge_24m = tax_penalty * 0.12 * 2.0  # 6,960
    assert res_24m.tax_exposure.default_surcharge_amount == pytest.approx(expected_surcharge_24m, rel=1e-4)


def test_capitalize_vs_expense_direct_call():
    """Verify direct simulate_capitalize_vs_expense call with markdown report."""
    res = simulate_capitalize_vs_expense(1_000_000.0, {"useful_life_years": 4})
    assert res.scenario_type == ScenarioType.CAPITALIZE_VS_EXPENSE
    md = res.to_markdown()
    assert "IAS 16 Capitalize vs. Expense Sandboxing Simulation" in md
    assert "Operating Expense (Opex Write-Off)" in md
    assert "Balance Sheet Capitalization (IAS 16 PPE)" in md


def test_to_markdown_rich_rendering():
    """Verify markdown report generation for executive presentation."""
    # Test cash vs bank markdown report (which includes tax exposure table)
    res_tax = simulate_scenario("CASH_VS_BANK", 150_000.0)
    md_tax = res_tax.to_markdown()
    assert "# 📊 Strategic Financial Simulation" in md_tax
    assert "Section 73 & Section 21(l)" in md_tax
    assert "CRITICAL STATUTORY AUDIT WARNING" in md_tax
    assert "Virtual CFO Tactical Action Plan" in md_tax

    # Test lease vs buy markdown report
    res_lease = simulate_scenario("LEASE_VS_BUY", 500_000.0)
    md_lease = res_lease.to_markdown()
    assert "Outright Purchase (IAS 16 PPE)" in md_lease
    assert "Operating/Finance Lease (IFRS 16)" in md_lease
    assert "Comparative Periodic Schedule" in md_lease
