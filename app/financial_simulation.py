"""What-If Financial Simulation & Capitalization Sandboxing Engine
===================================================================
A high-precision, hermetic financial simulation sandbox empowering Virtual CFOs,
treasurers, and controllers to model complex strategic financial scenarios:

1. **Lease vs. Buy (IFRS 16 vs. IAS 16)**:
   - Outright purchase: IAS 16 PPE capitalization, straight-line depreciation, full Day 0 cash drain.
   - Finance/Operating lease: IFRS 16 Right-of-Use (RoU) Asset, lease liability amortized at
     the incremental borrowing rate (IBR), front-loaded interest + straight-line amortization,
     and liquidity/working capital preservation.
2. **Cash vs. Bank Settlement (Section 73 & Section 21(l) ITO 2001)**:
   - Cash settlement: 100% tax disallowance for payments exceeding PKR 50,000 (expenses) or
     PKR 250,000 (capital assets), generating 29% corporate tax penalty, Section 205 default
     surcharge (12% p.a.), and Section 182 non-compliance penalty.
   - Approved banking channels: 100% legitimate tax shield, full deductibility, zero penalty.
3. **Capitalize vs. Expense (IAS 16 vs. Opex)**:
   - Immediate expensing (Opex): 100% P&L hit in Year 1, EBITDA reduction, immediate tax shield.
   - Balance sheet capitalization (IAS 16 Capex): 0% Year 1 EBITDA hit, multi-year depreciation,
     balance sheet asset preservation, and discounted time-value-of-money tax shield diff.

Architecture & Quality Standards:
- Python 3.12+ type safety and Pydantic v2 validation.
- Mathematically exact discounting (continuous/monthly compound interest).
- 100% hermetic: zero live DB queries, zero network I/O, deterministic output.
- Plain-English Virtual CFO executive recommendations, risk flags, and markdown reporting.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# Statutory & Financial Default Benchmarks
# =============================================================================

DEFAULT_CORPORATE_TAX_RATE = 0.29          # 29% Standard Corporate Tax Rate in Pakistan (ITO 2001)
DEFAULT_DISCOUNT_RATE = 0.12                # 12% Cost of Capital / WACC benchmark
DEFAULT_SECTION_205_SURCHARGE_RATE = 0.12   # 12% p.a. default surcharge u/s 205 ITO 2001
DEFAULT_SECTION_182_PENALTY_RATE = 0.05     # 5% statutory penalty benchmark u/s 182 ITO 2001
DEFAULT_AUDIT_DELAY_MONTHS = 12             # 12-month expected FBR audit assessment horizon
SECTION_73_EXPENSE_LIMIT = 50000.0          # PKR 50,000 cash threshold for expenses u/s 73/21(l)
SECTION_73_ASSET_LIMIT = 250000.0           # PKR 250,000 cash threshold for capital assets u/s 73(2)/(3)


# =============================================================================
# Enums
# =============================================================================

class ScenarioType(str, Enum):
    """Supported financial simulation scenarios."""
    LEASE_VS_BUY = "LEASE_VS_BUY"
    CASH_VS_BANK = "CASH_VS_BANK"
    CAPITALIZE_VS_EXPENSE = "CAPITALIZE_VS_EXPENSE"


class PaymentTiming(str, Enum):
    """Timing of lease payments."""
    IN_ARREARS = "IN_ARREARS"   # Ordinary annuity (payment at end of each period)
    IN_ADVANCE = "IN_ADVANCE"   # Annuity due (payment at beginning of each period)


class SettlementMethod(str, Enum):
    """Payment settlement instrument."""
    CASH = "CASH"
    BANK = "BANK"


class DepreciationMethod(str, Enum):
    """Depreciation methodology."""
    STRAIGHT_LINE = "STRAIGHT_LINE"
    REDUCING_BALANCE = "REDUCING_BALANCE"


# =============================================================================
# Pydantic v2 Models: Granular Simulation Components
# =============================================================================

class SchedulePeriod(BaseModel):
    """Periodic cash flow and accounting impact entry in comparative schedule."""
    period_index: int = Field(..., ge=0, description="Sequential period index (0 = Day 0 / Upfront)")
    period_label: str = Field(..., description="Human-readable period descriptor (e.g. Month 0, Month 1, Year 1)")
    
    # Cash Flow Dynamics
    option_a_cash_flow: float = Field(..., description="Net cash outflow/(inflow) under Option A (negative = outflow)")
    option_b_cash_flow: float = Field(..., description="Net cash outflow/(inflow) under Option B (negative = outflow)")
    cash_flow_diff: float = Field(..., description="Option A Cash Flow - Option B Cash Flow")
    
    # Discounting & Present Value
    discount_factor: float = Field(..., ge=0.0, description="Discount factor (1 / (1 + r)^t)")
    discounted_option_a_cf: float = Field(..., description="Discounted cash flow under Option A")
    discounted_option_b_cf: float = Field(..., description="Discounted cash flow under Option B")
    
    # Accounting / P&L Impacts
    option_a_pl_impact: float = Field(..., description="Operating P&L expense charge under Option A")
    option_b_pl_impact: float = Field(..., description="Operating P&L expense charge under Option B")
    pl_impact_diff: float = Field(..., description="Option A P&L Charge - Option B P&L Charge")
    
    # Balance Sheet & Supplementary Notes
    option_a_carrying_value: float = Field(default=0.0, ge=0.0, description="Carrying value / Liability under Option A")
    option_b_carrying_value: float = Field(default=0.0, ge=0.0, description="Carrying value / Liability under Option B")
    notes: Optional[str] = Field(default=None, description="Granular commentary for this period")


class OptionSummary(BaseModel):
    """Executive financial summary for an individual simulation option."""
    option_key: str = Field(..., description="Machine identifier (e.g. BUY, LEASE, CASH, BANK, EXPENSE, CAPITALIZE)")
    option_name: str = Field(..., description="Formal accounting title of the option")
    governing_standard: str = Field(..., description="Governing standard (e.g. IAS 16, IFRS 16, ITO 2001 Section 73)")
    
    # Cash Flow & NPV Metrics
    initial_cash_outlay: float = Field(..., description="Day 0 immediate cash drain")
    total_nominal_cash_outflow: float = Field(..., description="Total nominal cash paid over the horizon")
    present_value_cash_outflow: float = Field(..., description="Discounted present value of all cash outflows")
    present_value_tax_shield: float = Field(default=0.0, description="Discounted present value of tax shields earned")
    net_present_cost: float = Field(..., description="Net present cost (PV Outflows - PV Tax Shields)")
    
    # P&L Metrics
    period_1_pl_charge: float = Field(..., description="P&L expense hit in Period 1 (Month 1 or Year 1)")
    total_nominal_pl_charge: float = Field(..., description="Total nominal cumulative P&L charge over asset life")
    
    # Strategic Statements
    balance_sheet_impact: str = Field(..., description="Summary of balance sheet position and gearing effect")
    working_capital_impact: str = Field(..., description="Working capital and liquidity headroom impact")
    
    # Specific granular metrics
    key_metrics: Dict[str, Any] = Field(default_factory=dict, description="Scenario-specific granular data points")


class TaxExposureDiff(BaseModel):
    """Detailed tax exposure breakdown for Section 73 ITO 2001 compliance."""
    is_statutory_violation: bool = Field(..., description="Whether transaction violates Section 73 / 21(l)")
    governing_section: str = Field(..., description="Governing statutory section")
    statutory_threshold: float = Field(..., description="Applicable statutory cash ceiling")
    disallowed_amount: float = Field(..., description="Gross amount disallowed from taxable expenditure")
    corporate_tax_penalty: float = Field(..., description="Direct corporate income tax penalty at 29%")
    default_surcharge_amount: float = Field(..., description="Section 205 default surcharge for audit assessment horizon")
    statutory_penalty_amount: float = Field(..., description="Section 182 penalty for incorrect return submission")
    total_tax_penalty_exposure: float = Field(..., description="Sum of corporate tax, surcharge, and Section 182 penalty")
    tax_shield_lost: float = Field(..., description="Foregone allowable tax shield")
    effective_tax_penalty_rate_pct: float = Field(..., description="Effective penalty as a percentage of gross amount")
    net_economic_waste_of_cash: float = Field(..., description="Total economic loss of cash vs. compliant bank settlement")
    recommended_banking_channels: List[str] = Field(
        default_factory=lambda: ["Bank Transfer (IBFT/RTGS)", "Crossed Cheque", "Crossed Pay Order"]
    )
    statutory_verdict: str = Field(..., description="Definitive legal verdict for tax audit defense")


class ExecutiveRecommendation(BaseModel):
    """Authoritative Virtual CFO strategic recommendation and action plan."""
    verdict: str = Field(..., description="Concise strategic verdict code (e.g. PREFER_LEASE, MANDATORY_BANK, CAPITALIZE)")
    headline: str = Field(..., description="Executive headline for board-level decision makers")
    plain_english_summary: str = Field(..., description="Crisp, jargon-free CFO explanation")
    financial_justification: str = Field(..., description="Quantitative and mathematical justification")
    liquidity_headroom_analysis: str = Field(..., description="Analysis of working capital and cash runway impact")
    cfo_action_plan: List[str] = Field(default_factory=list, description="Immediate sequenced tactical action items")
    risk_flags: List[str] = Field(default_factory=list, description="Statutory, operational, or covenant risk flags")
    accounting_standard_reference: str = Field(..., description="Citations to applicable IFRS / IAS / ITO clauses")


class FinancialSimulationResult(BaseModel):
    """Root container for a financial simulation run."""
    scenario_type: ScenarioType = Field(..., description="Simulation scenario type")
    scenario_name: str = Field(..., description="Human-friendly scenario title")
    base_amount: float = Field(..., gt=0, description="Base principal / transaction amount modeled")
    parameters_applied: Dict[str, Any] = Field(default_factory=dict, description="Normalized simulation parameters")
    
    # Comparative Models
    options: Dict[str, OptionSummary] = Field(..., description="Individual metrics keyed by option identifier")
    schedule: List[SchedulePeriod] = Field(default_factory=list, description="Period-by-period comparative schedule")
    variance_summary: Dict[str, Any] = Field(default_factory=dict, description="Comparative variances and deltas")
    
    # Specific Modules
    tax_exposure: Optional[TaxExposureDiff] = Field(default=None, description="Tax exposure diff if applicable")
    recommendation: ExecutiveRecommendation = Field(..., description="Executive Virtual CFO recommendation")
    
    simulation_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of simulation generation"
    )

    def to_markdown(self) -> str:
        """Render a comprehensive, publication-ready Virtual CFO Markdown report."""
        opt_keys = list(self.options.keys())
        opt_a = self.options[opt_keys[0]] if len(opt_keys) > 0 else None
        opt_b = self.options[opt_keys[1]] if len(opt_keys) > 1 else None

        lines = [
            f"# 📊 Strategic Financial Simulation: {self.scenario_name}",
            f"**Base Amount Modeled**: PKR {self.base_amount:,.2f} | **Generated**: {self.simulation_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## 🎯 Executive CFO Verdict",
            f"### **{self.recommendation.headline}**",
            f"> {self.recommendation.plain_english_summary}",
            "",
            f"**Quantitative Justification**: {self.recommendation.financial_justification}",
            "",
            f"**Liquidity & Working Capital**: {self.recommendation.liquidity_headroom_analysis}",
            "",
            "## ⚖️ Comparative Financial Model Summary",
        ]

        if opt_a and opt_b:
            lines.extend([
                f"| Financial Metric | {opt_a.option_name} | {opt_b.option_name} | Variance (Delta) |",
                "| :--- | :--- | :--- | :--- |",
                f"| **Governing Standard** | {opt_a.governing_standard} | {opt_b.governing_standard} | - |",
                f"| **Initial Cash Outlay (Day 0)** | PKR {opt_a.initial_cash_outlay:,.2f} | PKR {opt_b.initial_cash_outlay:,.2f} | PKR {(opt_a.initial_cash_outlay - opt_b.initial_cash_outlay):,.2f} |",
                f"| **Total Nominal Cash Outflow** | PKR {opt_a.total_nominal_cash_outflow:,.2f} | PKR {opt_b.total_nominal_cash_outflow:,.2f} | PKR {(opt_a.total_nominal_cash_outflow - opt_b.total_nominal_cash_outflow):,.2f} |",
                f"| **Present Value of Cash Outflow (NPV)** | PKR {opt_a.present_value_cash_outflow:,.2f} | PKR {opt_b.present_value_cash_outflow:,.2f} | PKR {(opt_a.present_value_cash_outflow - opt_b.present_value_cash_outflow):,.2f} |",
                f"| **PV of Tax Shields** | PKR {opt_a.present_value_tax_shield:,.2f} | PKR {opt_b.present_value_tax_shield:,.2f} | PKR {(opt_a.present_value_tax_shield - opt_b.present_value_tax_shield):,.2f} |",
                f"| **Net Present Cost (NPC)** | PKR {opt_a.net_present_cost:,.2f} | PKR {opt_b.net_present_cost:,.2f} | PKR {(opt_a.net_present_cost - opt_b.net_present_cost):,.2f} |",
                f"| **Period 1 P&L Charge** | PKR {opt_a.period_1_pl_charge:,.2f} | PKR {opt_b.period_1_pl_charge:,.2f} | PKR {(opt_a.period_1_pl_charge - opt_b.period_1_pl_charge):,.2f} |",
                f"| **Balance Sheet Position** | {opt_a.balance_sheet_impact} | {opt_b.balance_sheet_impact} | - |",
                f"| **Working Capital Effect** | {opt_a.working_capital_impact} | {opt_b.working_capital_impact} | - |",
                "",
            ])

        # If tax exposure module is active
        if self.tax_exposure and self.tax_exposure.is_statutory_violation:
            lines.extend([
                "## ⚠️ Statutory Tax Exposure & Penalty Audit (Section 73 ITO 2001)",
                f"> **CRITICAL STATUTORY AUDIT WARNING**: {self.tax_exposure.statutory_verdict}",
                "",
                "| Statutory Component | Cash Settlement Exposure | Bank Settlement | Net Penalty Avoided |",
                "| :--- | :--- | :--- | :--- |",
                f"| **Statutory Threshold** | PKR {self.tax_exposure.statutory_threshold:,.2f} | N/A (Exempt) | - |",
                f"| **Disallowed Expenditure** | PKR {self.tax_exposure.disallowed_amount:,.2f} | PKR 0.00 | PKR {self.tax_exposure.disallowed_amount:,.2f} |",
                f"| **Corporate Tax Penalty (29%)** | PKR {self.tax_exposure.corporate_tax_penalty:,.2f} | PKR 0.00 | PKR {self.tax_exposure.corporate_tax_penalty:,.2f} |",
                f"| **Section 205 Default Surcharge (12% p.a.)** | PKR {self.tax_exposure.default_surcharge_amount:,.2f} | PKR 0.00 | PKR {self.tax_exposure.default_surcharge_amount:,.2f} |",
                f"| **Section 182 Penalty (5%)** | PKR {self.tax_exposure.statutory_penalty_amount:,.2f} | PKR 0.00 | PKR {self.tax_exposure.statutory_penalty_amount:,.2f} |",
                f"| **Total Tax & Surcharge Loss** | PKR {self.tax_exposure.total_tax_penalty_exposure:,.2f} | PKR 0.00 | PKR {self.tax_exposure.total_tax_penalty_exposure:,.2f} |",
                f"| **Allowable Tax Shield Earned** | PKR 0.00 (Forfeited) | PKR {self.tax_exposure.tax_shield_lost:,.2f} | PKR {self.tax_exposure.tax_shield_lost:,.2f} |",
                f"| **Net Economic Waste of Cash** | **PKR {self.tax_exposure.net_economic_waste_of_cash:,.2f}** | **PKR 0.00** | **PKR {self.tax_exposure.net_economic_waste_of_cash:,.2f}** |",
                "",
            ])

        # Action Plan & Risk Flags
        lines.extend([
            "## 📋 Virtual CFO Tactical Action Plan",
        ])
        for idx, act in enumerate(self.recommendation.cfo_action_plan, 1):
            lines.append(f"{idx}. {act}")
        lines.append("")

        if self.recommendation.risk_flags:
            lines.append("## 🚩 Governance & Risk Flags")
            for rf in self.recommendation.risk_flags:
                lines.append(f"- ⚠️ **{rf}**")
            lines.append("")

        # Schedule preview (up to 12 periods or all if smaller)
        if self.schedule:
            lines.extend([
                "## 📅 Comparative Periodic Schedule (First Sample Periods)",
                "| Period | Option A Cash Flow | Option B Cash Flow | Cash Delta | Option A P&L | Option B P&L | Discount Factor |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            sample_periods = self.schedule[:12]
            for p in sample_periods:
                lines.append(
                    f"| {p.period_label} | PKR {p.option_a_cash_flow:,.2f} | PKR {p.option_b_cash_flow:,.2f} | PKR {p.cash_flow_diff:,.2f} | PKR {p.option_a_pl_impact:,.2f} | PKR {p.option_b_pl_impact:,.2f} | {p.discount_factor:.4f} |"
                )
            if len(self.schedule) > 12:
                lines.append(f"*... {len(self.schedule) - 12} additional periods modeled in detailed data structure.*")
            lines.append("")

        return "\n".join(lines)


# =============================================================================
# Helper Utilities: Pure Financial Mathematics
# =============================================================================

def calculate_annuity_payment(
    principal: float,
    rate_per_period: float,
    number_of_periods: int,
    timing: PaymentTiming = PaymentTiming.IN_ARREARS,
) -> float:
    """Calculate exact periodic payment for an amortizing annuity.
    
    Formula (Ordinary Annuity - In Arrears):
        P = (r * PV) / (1 - (1 + r)^(-n))
    Formula (Annuity Due - In Advance):
        P = (r * PV) / ((1 - (1 + r)^(-n)) * (1 + r))
    """
    if number_of_periods <= 0:
        raise ValueError("number_of_periods must be strictly positive.")
    if rate_per_period == 0:
        return principal / number_of_periods

    pv_factor = (1.0 - math.pow(1.0 + rate_per_period, -number_of_periods)) / rate_per_period
    if timing == PaymentTiming.IN_ADVANCE:
        pv_factor *= (1.0 + rate_per_period)
    
    return principal / pv_factor


def present_value_of_stream(
    cash_flows: List[float],
    rate_per_period: float,
    start_period: int = 0,
) -> float:
    """Calculate exact present value of a periodic cash flow stream.
    
    PV = sum_{t=0}^n (CF_t / (1 + r)^t)
    """
    pv = 0.0
    for idx, cf in enumerate(cash_flows):
        t = start_period + idx
        df = 1.0 / math.pow(1.0 + rate_per_period, t)
        pv += cf * df
    return pv


# Alias for convenience
present_value_stream = present_value_of_stream


# =============================================================================
# Scenario 1 Engine: Lease vs. Buy (IFRS 16 vs. IAS 16)
# =============================================================================

def simulate_lease_vs_buy(
    amount: float,
    parameters: Dict[str, Any],
) -> FinancialSimulationResult:
    """Simulate outright purchase (IAS 16) vs. finance/operating lease (IFRS 16).
    
    Parameters expected / supported:
    - useful_life_months (int, default 36)
    - lease_term_months (int, default = useful_life_months)
    - annual_discount_rate (float, default 0.12 = 12%)
    - incremental_borrowing_rate (float, default = annual_discount_rate)
    - monthly_lease_payment (Optional[float], default auto-calculated from IBR)
    - residual_value (float, default 0.0)
    - upfront_deposit (float, default 0.0)
    - corporate_tax_rate (float, default 0.29 = 29%)
    - payment_timing (str: "IN_ARREARS" or "IN_ADVANCE", default "IN_ARREARS")
    - annual_maintenance_cost_buy (float, default 0.0)
    """
    useful_life_m = int(parameters.get("useful_life_months", 36))
    if useful_life_m <= 0:
        useful_life_m = 36
    
    lease_term_m = int(parameters.get("lease_term_months", useful_life_m))
    if lease_term_m <= 0:
        lease_term_m = useful_life_m

    annual_discount = float(parameters.get("annual_discount_rate", DEFAULT_DISCOUNT_RATE))
    ibr_annual = float(parameters.get("incremental_borrowing_rate", annual_discount))
    tax_rate = float(parameters.get("corporate_tax_rate", DEFAULT_CORPORATE_TAX_RATE))
    residual_val = float(parameters.get("residual_value", 0.0))
    upfront_deposit = float(parameters.get("upfront_deposit", 0.0))
    maint_annual = float(parameters.get("annual_maintenance_cost_buy", 0.0))
    maint_monthly = maint_annual / 12.0

    raw_timing = str(parameters.get("payment_timing", "IN_ARREARS")).upper()
    timing = PaymentTiming.IN_ADVANCE if "ADVANCE" in raw_timing else PaymentTiming.IN_ARREARS

    # Monthly discount rates
    r_monthly_discount = annual_discount / 12.0
    r_monthly_ibr = ibr_annual / 12.0

    # -------------------------------------------------------------------------
    # Option 1: Buy (IAS 16 PPE Capitalization)
    # -------------------------------------------------------------------------
    buy_depreciation_monthly = (amount - residual_val) / useful_life_m
    buy_tax_shield_monthly = buy_depreciation_monthly * tax_rate
    buy_maint_after_tax = maint_monthly * (1.0 - tax_rate)

    # -------------------------------------------------------------------------
    # Option 2: Lease (IFRS 16 RoU Asset + Lease Liability)
    # -------------------------------------------------------------------------
    financed_principal = max(0.0, amount - upfront_deposit)
    
    # Resolve or compute monthly lease rental
    custom_payment = parameters.get("monthly_lease_payment")
    if custom_payment is not None and float(custom_payment) > 0:
        monthly_payment = float(custom_payment)
    else:
        monthly_payment = calculate_annuity_payment(
            principal=financed_principal,
            rate_per_period=r_monthly_ibr,
            number_of_periods=lease_term_m,
            timing=timing,
        )

    # Under IFRS 16:
    # 1. Initial Lease Liability = PV of lease payments discounted at IBR
    # 2. RoU Asset = Initial Lease Liability + upfront payment/deposit
    if timing == PaymentTiming.IN_ADVANCE:
        # First payment at Month 0
        df_stream = [1.0] + [math.pow(1.0 + r_monthly_ibr, -t) for t in range(1, lease_term_m)]
        initial_lease_liability = monthly_payment * sum(df_stream)
    else:
        df_stream = [math.pow(1.0 + r_monthly_ibr, -t) for t in range(1, lease_term_m + 1)]
        initial_lease_liability = monthly_payment * sum(df_stream)

    initial_rou_asset = initial_lease_liability + upfront_deposit
    rou_monthly_amortization = initial_rou_asset / lease_term_m

    # Generate schedules and amortization
    schedule: List[SchedulePeriod] = []
    
    # Period 0 (Day 0)
    day0_buy_cf = -amount
    day0_lease_cf = -upfront_deposit - (monthly_payment if timing == PaymentTiming.IN_ADVANCE else 0.0)
    
    schedule.append(SchedulePeriod(
        period_index=0,
        period_label="Day 0 (Commencement)",
        option_a_cash_flow=day0_buy_cf,
        option_b_cash_flow=day0_lease_cf,
        cash_flow_diff=day0_buy_cf - day0_lease_cf,
        discount_factor=1.0,
        discounted_option_a_cf=day0_buy_cf,
        discounted_option_b_cf=day0_lease_cf,
        option_a_pl_impact=0.0,
        option_b_pl_impact=0.0,
        pl_impact_diff=0.0,
        option_a_carrying_value=amount,
        option_b_carrying_value=initial_lease_liability,
        notes="Commencement: Outright purchase requires 100% upfront cash. Lease requires minimal Day 0 outlay."
    ))

    current_liability = initial_lease_liability
    if timing == PaymentTiming.IN_ADVANCE:
        current_liability = max(0.0, current_liability - monthly_payment)

    current_ppe_carrying = amount
    current_rou_carrying = initial_rou_asset

    total_lease_nominal_outflow = abs(day0_lease_cf)
    total_buy_nominal_outflow = amount
    pv_buy_outflows = amount
    pv_lease_outflows = abs(day0_lease_cf)
    
    pv_buy_tax_shields = 0.0
    pv_lease_tax_shields = 0.0
    
    total_buy_nominal_pl = 0.0
    total_lease_nominal_pl = 0.0
    
    month_1_buy_pl = 0.0
    month_1_lease_pl = 0.0

    max_months = max(useful_life_m, lease_term_m)

    for m in range(1, max_months + 1):
        df_disc = 1.0 / math.pow(1.0 + r_monthly_discount, m)

        # --- Buy Calculations ---
        buy_active = (m <= useful_life_m)
        m_depr = buy_depreciation_monthly if buy_active else 0.0
        m_maint = maint_monthly if buy_active else 0.0
        m_tax_shield_buy = (m_depr + m_maint) * tax_rate
        
        # Salvage at final month
        m_salvage = residual_val if m == useful_life_m else 0.0
        
        buy_cf = -m_maint + m_salvage
        buy_pl = m_depr + m_maint
        
        total_buy_nominal_outflow += m_maint - m_salvage
        pv_buy_outflows += (m_maint - m_salvage) * df_disc
        pv_buy_tax_shields += m_tax_shield_buy * df_disc
        total_buy_nominal_pl += buy_pl
        
        current_ppe_carrying = max(residual_val, current_ppe_carrying - m_depr)

        # --- Lease Calculations ---
        lease_active = (m <= lease_term_m)
        if lease_active:
            # IFRS 16 interest on opening liability
            interest_expense = current_liability * r_monthly_ibr
            amortization_expense = rou_monthly_amortization
            lease_pl = amortization_expense + interest_expense
            
            # Payment timing logic
            if timing == PaymentTiming.IN_ADVANCE:
                # Payment was made at commencement for month 1, and month m payment is for month m+1
                lease_cf = -monthly_payment if m < lease_term_m else 0.0
                principal_repaid = max(0.0, monthly_payment - interest_expense) if m < lease_term_m else 0.0
            else:
                lease_cf = -monthly_payment
                principal_repaid = max(0.0, monthly_payment - interest_expense)
            
            current_liability = max(0.0, current_liability - principal_repaid)
            current_rou_carrying = max(0.0, current_rou_carrying - amortization_expense)
            
            # Tax shield on lease: Under Section 28(1)(e) ITO 2001, lease rentals paid to financial institutions are deductible
            # Or in financial accounts: tax shield on (amortization + interest). In standard statutory practice, rentals paid are allowed.
            rental_paid = abs(lease_cf)
            m_tax_shield_lease = rental_paid * tax_rate
            
            total_lease_nominal_outflow += rental_paid
            pv_lease_outflows += rental_paid * df_disc
            pv_lease_tax_shields += m_tax_shield_lease * df_disc
            total_lease_nominal_pl += lease_pl
        else:
            lease_cf = 0.0
            lease_pl = 0.0
            interest_expense = 0.0
            amortization_expense = 0.0

        if m == 1:
            month_1_buy_pl = buy_pl
            month_1_lease_pl = lease_pl

        schedule.append(SchedulePeriod(
            period_index=m,
            period_label=f"Month {m}",
            option_a_cash_flow=buy_cf,
            option_b_cash_flow=lease_cf,
            cash_flow_diff=buy_cf - lease_cf,
            discount_factor=df_disc,
            discounted_option_a_cf=buy_cf * df_disc,
            discounted_option_b_cf=lease_cf * df_disc,
            option_a_pl_impact=buy_pl,
            option_b_pl_impact=lease_pl,
            pl_impact_diff=buy_pl - lease_pl,
            option_a_carrying_value=current_ppe_carrying,
            option_b_carrying_value=current_liability,
            notes=(
                f"Lease Interest: PKR {interest_expense:,.2f}, RoU Amort: PKR {amortization_expense:,.2f}"
                if lease_active else "Lease term completed."
            )
        ))

    net_present_cost_buy = pv_buy_outflows - pv_buy_tax_shields
    net_present_cost_lease = pv_lease_outflows - pv_lease_tax_shields

    # Construct Option Summaries
    buy_option = OptionSummary(
        option_key="BUY",
        option_name="Outright Purchase (IAS 16 PPE)",
        governing_standard="IAS 16 Property, Plant and Equipment",
        initial_cash_outlay=amount,
        total_nominal_cash_outflow=total_buy_nominal_outflow,
        present_value_cash_outflow=pv_buy_outflows,
        present_value_tax_shield=pv_buy_tax_shields,
        net_present_cost=net_present_cost_buy,
        period_1_pl_charge=month_1_buy_pl,
        total_nominal_pl_charge=total_buy_nominal_pl,
        balance_sheet_impact="Capitalizes PPE asset. Full upfront cash drain directly depletes liquid reserves.",
        working_capital_impact=f"Severe immediate working capital reduction of PKR {amount:,.2f}.",
        key_metrics={
            "useful_life_months": useful_life_m,
            "monthly_depreciation": buy_depreciation_monthly,
            "salvage_value": residual_val,
            "annual_maintenance_cost": maint_annual,
        }
    )

    lease_option = OptionSummary(
        option_key="LEASE",
        option_name="Operating/Finance Lease (IFRS 16)",
        governing_standard="IFRS 16 Leases",
        initial_cash_outlay=abs(day0_lease_cf),
        total_nominal_cash_outflow=total_lease_nominal_outflow,
        present_value_cash_outflow=pv_lease_outflows,
        present_value_tax_shield=pv_lease_tax_shields,
        net_present_cost=net_present_cost_lease,
        period_1_pl_charge=month_1_lease_pl,
        total_nominal_pl_charge=total_lease_nominal_pl,
        balance_sheet_impact=f"Recognizes RoU Asset PKR {initial_rou_asset:,.2f} and Lease Liability PKR {initial_lease_liability:,.2f}.",
        working_capital_impact=f"Preserves PKR {(amount - abs(day0_lease_cf)):,.2f} in liquid operating cash on Day 0.",
        key_metrics={
            "lease_term_months": lease_term_m,
            "monthly_lease_payment": monthly_payment,
            "initial_rou_asset": initial_rou_asset,
            "initial_lease_liability": initial_lease_liability,
            "incremental_borrowing_rate_pct": ibr_annual * 100.0,
            "payment_timing": timing.value,
        }
    )

    # Executive Recommendation Logic
    liquid_cash_preserved = amount - abs(day0_lease_cf)
    npc_diff = net_present_cost_buy - net_present_cost_lease  # positive means buy is more costly in NPC -> lease wins

    if npc_diff > 0:
        verdict = "PREFER_LEASE"
        headline = "Executive Recommendation: Execute IFRS 16 Lease Structure"
        plain_summary = (
            f"Leasing delivers superior capital efficiency, saving PKR {abs(npc_diff):,.2f} on a Net Present Cost basis "
            f"while preserving PKR {liquid_cash_preserved:,.2f} in immediate liquid working capital."
        )
        fin_justification = (
            f"The lease structure reduces Day 0 cash outlay from PKR {amount:,.2f} to PKR {abs(day0_lease_cf):,.2f}. "
            f"Although total nominal lease cash outflows (PKR {total_lease_nominal_outflow:,.2f}) exceed outright purchase "
            f"(PKR {total_buy_nominal_outflow:,.2f}) due to finance charges, the Net Present Cost of the lease "
            f"(PKR {net_present_cost_lease:,.2f}) is lower than purchase (PKR {net_present_cost_buy:,.2f}) when evaluated at "
            f"the company's cost of capital ({annual_discount * 100:.1f}%)."
        )
    else:
        verdict = "PREFER_BUY"
        headline = "Executive Recommendation: Execute Outright Purchase (IAS 16)"
        plain_summary = (
            f"Outright purchase is financially optimal, generating a Net Present Cost advantage of PKR {abs(npc_diff):,.2f} "
            f"by avoiding cumulative financing interest of PKR {(total_lease_nominal_outflow - amount):,.2f}."
        )
        fin_justification = (
            f"Purchasing avoids the financing interest loaded into the {ibr_annual * 100:.1f}% IBR lease structure. "
            f"The Net Present Cost of outright purchase is PKR {net_present_cost_buy:,.2f} vs. PKR {net_present_cost_lease:,.2f} for the lease."
        )

    recommendation = ExecutiveRecommendation(
        verdict=verdict,
        headline=headline,
        plain_english_summary=plain_summary,
        financial_justification=fin_justification,
        liquidity_headroom_analysis=(
            f"Day 0 liquidity preservation under lease structure: PKR {liquid_cash_preserved:,.2f}. "
            f"Enables the enterprise to maintain solvency buffer and allocate liquid capital to higher-ROI trading activities."
        ),
        cfo_action_plan=[
            "Review treasury cash runway to confirm whether Day 0 purchase outlay breaches minimum liquidity covenants.",
            "Verify lessor's implicit interest rate against prime corporate borrowing benchmarks (KIBOR / SOFR).",
            "Under IFRS 16, ensure RoU asset amortization and lease liability interest schedules are configured in ERP.",
            "Confirm tax deductibility of lease rentals under Section 28(1)(e) ITO 2001 with tax advisor.",
        ],
        risk_flags=[
            "IFRS 16 recognizes lease liability on balance sheet, which increases reported financial gearing / leverage ratios.",
            "Front-loaded P&L charges: Monthly lease expense (amortization + interest) in Year 1 is higher than flat IAS 16 depreciation.",
        ],
        accounting_standard_reference="IFRS 16 Leases (para 24, 26, 37) & IAS 16 Property, Plant and Equipment (para 50, 60)"
    )

    return FinancialSimulationResult(
        scenario_type=ScenarioType.LEASE_VS_BUY,
        scenario_name="Lease vs. Buy Strategic Capitalization Simulation",
        base_amount=amount,
        parameters_applied={
            "useful_life_months": useful_life_m,
            "lease_term_months": lease_term_m,
            "annual_discount_rate": annual_discount,
            "incremental_borrowing_rate": ibr_annual,
            "corporate_tax_rate": tax_rate,
            "residual_value": residual_val,
            "upfront_deposit": upfront_deposit,
            "payment_timing": timing.value,
        },
        options={
            "BUY": buy_option,
            "LEASE": lease_option,
        },
        schedule=schedule,
        variance_summary={
            "npc_difference": npc_diff,
            "day0_cash_preserved": liquid_cash_preserved,
            "nominal_cash_difference": total_buy_nominal_outflow - total_lease_nominal_outflow,
            "pv_outflow_difference": pv_buy_outflows - pv_lease_outflows,
            "pv_tax_shield_difference": pv_buy_tax_shields - pv_lease_tax_shields,
        },
        tax_exposure=None,
        recommendation=recommendation,
    )


# =============================================================================
# Scenario 2 Engine: Cash vs. Bank Settlement (Section 73 ITO 2001)
# =============================================================================

def simulate_cash_vs_bank(
    amount: float,
    parameters: Dict[str, Any],
) -> FinancialSimulationResult:
    """Simulate Cash vs. Crossed Bank Transfer under Section 73 & Section 21(l) ITO 2001.
    
    Evaluates:
    - Section 73/21(l) 100% tax disallowance if cash payment > PKR 50,000 (expense) or > PKR 250,000 (asset).
    - 29% corporate income tax penalty on disallowed expenditure.
    - Section 205 default surcharge (12% p.a. for assessment delay horizon, e.g. 12 months).
    - Section 182 penalty for non-compliant/inaccurate return (5%).
    - Comparison with crossed banking instrument (100% tax shield, zero penalty).
    """
    tax_rate = float(parameters.get("corporate_tax_rate", DEFAULT_CORPORATE_TAX_RATE))
    surcharge_rate = float(parameters.get("default_surcharge_rate", DEFAULT_SECTION_205_SURCHARGE_RATE))
    penalty_rate = float(parameters.get("statutory_penalty_rate", DEFAULT_SECTION_182_PENALTY_RATE))
    audit_delay_m = int(parameters.get("audit_delay_months", DEFAULT_AUDIT_DELAY_MONTHS))
    is_capital_asset = bool(parameters.get("is_capital_asset", False))

    threshold = SECTION_73_ASSET_LIMIT if is_capital_asset else SECTION_73_EXPENSE_LIMIT
    is_violation = amount > threshold

    if is_violation:
        disallowed_amt = amount
        corp_tax_penalty = disallowed_amt * tax_rate
        surcharge_amt = corp_tax_penalty * surcharge_rate * (audit_delay_m / 12.0)
        statutory_penalty = corp_tax_penalty * penalty_rate
        total_penalty = corp_tax_penalty + surcharge_amt + statutory_penalty
        forfeited_tax_shield = amount * tax_rate
        net_economic_waste = total_penalty + forfeited_tax_shield
        statutory_verdict = (
            f"NON-COMPLIANT: Cash transaction of PKR {amount:,.2f} breaches the Section 73 "
            f"statutory ceiling of PKR {threshold:,.2f}. Mandatory 100% disallowance u/s 21(l) applies."
        )
    else:
        disallowed_amt = 0.0
        corp_tax_penalty = 0.0
        surcharge_amt = 0.0
        statutory_penalty = 0.0
        total_penalty = 0.0
        forfeited_tax_shield = 0.0
        net_economic_waste = 0.0
        statutory_verdict = (
            f"COMPLIANT: Cash transaction of PKR {amount:,.2f} is within the Section 73 "
            f"statutory limit of PKR {threshold:,.2f}."
        )

    effective_penalty_pct = (total_penalty / amount) * 100.0 if amount > 0 else 0.0

    # Option 1: Cash Settlement
    # In cash, the company pays the amount, gets NO tax shield (if > 50k), and pays tax penalty + surcharges
    nominal_cash_outflow_cash_mode = amount + total_penalty
    cash_pl_charge = amount + total_penalty

    # Option 2: Bank Settlement (Crossed Cheque / Bank Transfer)
    # In bank, the company pays the amount, receives 29% tax shield, zero penalty
    bank_tax_shield = amount * tax_rate
    nominal_cash_outflow_bank_mode = amount  # gross cash outflow to vendor
    net_economic_cost_bank_mode = amount - bank_tax_shield  # after-tax economic cost

    tax_exposure = TaxExposureDiff(
        is_statutory_violation=is_violation,
        governing_section="Section 73 & Section 21(l) Income Tax Ordinance 2001",
        statutory_threshold=threshold,
        disallowed_amount=disallowed_amt,
        corporate_tax_penalty=corp_tax_penalty,
        default_surcharge_amount=surcharge_amt,
        statutory_penalty_amount=statutory_penalty,
        total_tax_penalty_exposure=total_penalty,
        tax_shield_lost=forfeited_tax_shield,
        effective_tax_penalty_rate_pct=effective_penalty_pct,
        net_economic_waste_of_cash=net_economic_waste,
        recommended_banking_channels=["Crossed Cheque", "Direct Bank Transfer (IBFT/RTGS)", "Crossed Pay Order"],
        statutory_verdict=statutory_verdict,
    )

    cash_option = OptionSummary(
        option_key="CASH",
        option_name="Cash Settlement (Non-Banking Channel)",
        governing_standard="Section 73 & Section 21(l) ITO 2001",
        initial_cash_outlay=amount,
        total_nominal_cash_outflow=nominal_cash_outflow_cash_mode,
        present_value_cash_outflow=nominal_cash_outflow_cash_mode,
        present_value_tax_shield=0.0,
        net_present_cost=nominal_cash_outflow_cash_mode,
        period_1_pl_charge=cash_pl_charge,
        total_nominal_pl_charge=cash_pl_charge,
        balance_sheet_impact="Immediate cash reduction. Generates contingent tax liability and FBR audit scrutiny.",
        working_capital_impact=f"Severe cash drain of PKR {nominal_cash_outflow_cash_mode:,.2f} including tax penalties.",
        key_metrics={
            "cash_paid_to_vendor": amount,
            "disallowed_expenditure": disallowed_amt,
            "corporate_tax_penalty_29pct": corp_tax_penalty,
            "section_205_surcharge": surcharge_amt,
            "section_182_penalty": statutory_penalty,
            "effective_penalty_percentage": effective_penalty_pct,
        }
    )

    bank_option = OptionSummary(
        option_key="BANK",
        option_name="Crossed Banking Channel Settlement",
        governing_standard="Section 73 Approved Banking Channel (ITO 2001)",
        initial_cash_outlay=amount,
        total_nominal_cash_outflow=amount,
        present_value_cash_outflow=amount,
        present_value_tax_shield=bank_tax_shield,
        net_present_cost=net_economic_cost_bank_mode,
        period_1_pl_charge=amount,
        total_nominal_pl_charge=amount,
        balance_sheet_impact="Clean bank reconciliation. Bank statement acts as primary evidentiary audit record.",
        working_capital_impact=f"Optimizes net cash outflow to PKR {net_economic_cost_bank_mode:,.2f} via tax deductibility.",
        key_metrics={
            "bank_payment_to_vendor": amount,
            "tax_shield_earned": bank_tax_shield,
            "net_effective_cost": net_economic_cost_bank_mode,
            "statutory_compliance_status": "100% FULLY_COMPLIANT",
        }
    )

    # Schedule: Immediate Settlement vs. FBR Audit Assessment at Month 12
    schedule: List[SchedulePeriod] = [
        SchedulePeriod(
            period_index=0,
            period_label="Day 0 (Vendor Payment)",
            option_a_cash_flow=-amount,
            option_b_cash_flow=-amount,
            cash_flow_diff=0.0,
            discount_factor=1.0,
            discounted_option_a_cf=-amount,
            discounted_option_b_cf=-amount,
            option_a_pl_impact=amount,
            option_b_pl_impact=amount,
            pl_impact_diff=0.0,
            option_a_carrying_value=0.0,
            option_b_carrying_value=0.0,
            notes="Initial disbursement of invoice amount to vendor."
        )
    ]

    if is_violation:
        schedule.append(SchedulePeriod(
            period_index=audit_delay_m,
            period_label=f"Month {audit_delay_m} (FBR Tax Audit & Assessment)",
            option_a_cash_flow=-total_penalty,
            option_b_cash_flow=0.0,
            cash_flow_diff=-total_penalty,
            discount_factor=1.0 / math.pow(1.0 + (DEFAULT_DISCOUNT_RATE / 12.0), audit_delay_m),
            discounted_option_a_cf=-total_penalty / math.pow(1.0 + (DEFAULT_DISCOUNT_RATE / 12.0), audit_delay_m),
            discounted_option_b_cf=0.0,
            option_a_pl_impact=total_penalty,
            option_b_pl_impact=0.0,
            pl_impact_diff=total_penalty,
            option_a_carrying_value=0.0,
            option_b_carrying_value=0.0,
            notes=f"FBR disallows cash payment u/s 21(l). Demands 29% tax + Sec 205 surcharge + Sec 182 penalty."
        ))

    # Executive Recommendation
    if is_violation:
        verdict = "MANDATORY_BANK_SETTLEMENT"
        headline = "CRITICAL: Halt Cash Payment — Settle Exclusively via Approved Banking Channel"
        plain_summary = (
            f"Settling this PKR {amount:,.2f} invoice in cash triggers 100% tax disallowance under Section 73 ITO 2001, "
            f"resulting in an unrecoverable tax penalty of PKR {corp_tax_penalty:,.2f} (29%), a Section 205 surcharge of "
            f"PKR {surcharge_amt:,.2f}, and forfeiting PKR {forfeited_tax_shield:,.2f} in legitimate tax deductions. "
            f"Total economic destruction: PKR {net_economic_waste:,.2f} ({effective_penalty_pct:.1f}% penalty burden)."
        )
        fin_justification = (
            f"Cash settlement raises the effective financial burden from 71.0% (PKR {net_economic_cost_bank_mode:,.2f} net bank cost) "
            f"to {((nominal_cash_outflow_cash_mode / amount) * 100):.1f}% (PKR {nominal_cash_outflow_cash_mode:,.2f}). "
            f"Issuing a crossed cheque or electronic bank transfer saves the enterprise PKR {net_economic_waste:,.2f}."
        )
    else:
        verdict = "CASH_PERMISSIBLE_BUT_BANK_PREFERRED"
        headline = "Compliant: Transaction Within Statutory Cash Ceiling"
        plain_summary = (
            f"The transaction amount of PKR {amount:,.2f} is below the Section 73 limit of PKR {threshold:,.2f}. "
            f"Cash settlement does not trigger statutory disallowance, though crossed bank transfer provides superior audit trail."
        )
        fin_justification = (
            "No tax disallowance applies. Maintain payment receipt and cash voucher to defend against audit aggregation."
        )

    recommendation = ExecutiveRecommendation(
        verdict=verdict,
        headline=headline,
        plain_english_summary=plain_summary,
        financial_justification=fin_justification,
        liquidity_headroom_analysis=(
            f"Bank settlement guarantees full tax shield of PKR {bank_tax_shield:,.2f}, directly reducing the company's "
            f"annual corporate income tax payable and preserving cash liquidity."
        ),
        cfo_action_plan=[
            "Halt any manual cash withdrawal or bearer cheque issuance for this transaction.",
            "Issue payment via Crossed Cheque marked 'Account Payee Only' or direct electronic Inter-Bank Fund Transfer (IBFT).",
            "Archive the electronic transaction advice / cheque counterfoil with the vendor invoice in ERP.",
            "Ensure vendor NTN/STRN is validated against Active Taxpayers List (ATL) for Section 153 WHT compliance.",
        ],
        risk_flags=[
            "Section 73 Cash Smurfing Risk: Splitting this transaction into smaller sub-PKR 50k cash vouchers under the same account head is treated as willful evasion by tax authorities.",
            "Section 205 Default Surcharge: Compound 12% p.a. surcharge applies from the date tax was due until date of recovery.",
        ],
        accounting_standard_reference="Income Tax Ordinance 2001 (Section 73, Section 21(l), Section 205, Section 182)"
    )

    return FinancialSimulationResult(
        scenario_type=ScenarioType.CASH_VS_BANK,
        scenario_name="Section 73 ITO 2001 Cash vs. Bank Settlement Simulation",
        base_amount=amount,
        parameters_applied={
            "corporate_tax_rate": tax_rate,
            "default_surcharge_rate": surcharge_rate,
            "statutory_penalty_rate": penalty_rate,
            "audit_delay_months": audit_delay_m,
            "is_capital_asset": is_capital_asset,
            "statutory_threshold": threshold,
        },
        options={
            "CASH": cash_option,
            "BANK": bank_option,
        },
        schedule=schedule,
        variance_summary={
            "net_economic_waste_of_cash": net_economic_waste,
            "tax_penalty_exposure": total_penalty,
            "forfeited_tax_shield": forfeited_tax_shield,
            "net_bank_cost": net_economic_cost_bank_mode,
        },
        tax_exposure=tax_exposure,
        recommendation=recommendation,
    )


# =============================================================================
# Scenario 3 Engine: Capitalize vs. Expense (IAS 16 vs. Opex)
# =============================================================================

def simulate_capitalize_vs_expense(
    amount: float,
    parameters: Dict[str, Any],
) -> FinancialSimulationResult:
    """Simulate immediate expensing (Opex) vs. balance sheet capitalization (IAS 16 Capex).
    
    Evaluates:
    - Year 1 P&L hit: 100% EBITDA and Net Income hit under Opex vs. fractional depreciation hit under Capex.
    - Balance Sheet impact: Asset preservation, Tangible Net Worth, and debt covenant ratios.
    - Cash flow & Time Value of Money (TVM): Immediate Year 1 tax shield (Opex) vs. deferred depreciation
      tax shields spread over useful life (Capex).
    - Compliance boundaries under IAS 16 (Property, Plant and Equipment criteria).
    """
    useful_life_years = int(parameters.get("useful_life_years", 3))
    if useful_life_years <= 0:
        useful_life_years = 3

    salvage_val = float(parameters.get("salvage_value", 0.0))
    annual_discount = float(parameters.get("annual_discount_rate", DEFAULT_DISCOUNT_RATE))
    tax_rate = float(parameters.get("corporate_tax_rate", DEFAULT_CORPORATE_TAX_RATE))

    # -------------------------------------------------------------------------
    # Option 1: Operating Expense (Opex - Immediate P&L hit)
    # -------------------------------------------------------------------------
    opex_year_1_pl = amount
    opex_year_1_tax_shield = amount * tax_rate
    # Present value of tax shield discounted at end of Year 1
    pv_opex_tax_shield = opex_year_1_tax_shield / (1.0 + annual_discount)
    opex_net_present_cost = amount - pv_opex_tax_shield

    # -------------------------------------------------------------------------
    # Option 2: Balance Sheet Capitalization (IAS 16 Capex)
    # -------------------------------------------------------------------------
    annual_depreciation = (amount - salvage_val) / useful_life_years
    capex_year_1_pl = annual_depreciation
    capex_annual_tax_shield = annual_depreciation * tax_rate

    # Calculate PV of multi-year tax shields
    pv_capex_tax_shields = 0.0
    for y in range(1, useful_life_years + 1):
        df = 1.0 / math.pow(1.0 + annual_discount, y)
        pv_capex_tax_shields += capex_annual_tax_shield * df

    # Add PV of salvage value cash inflow if any
    pv_salvage = salvage_val / math.pow(1.0 + annual_discount, useful_life_years)
    capex_net_present_cost = (amount - pv_salvage) - pv_capex_tax_shields

    # Schedule: Year-by-Year Comparative Schedule
    schedule: List[SchedulePeriod] = [
        SchedulePeriod(
            period_index=0,
            period_label="Day 0 (Capital Outlay)",
            option_a_cash_flow=-amount,
            option_b_cash_flow=-amount,
            cash_flow_diff=0.0,
            discount_factor=1.0,
            discounted_option_a_cf=-amount,
            discounted_option_b_cf=-amount,
            option_a_pl_impact=0.0,
            option_b_pl_impact=0.0,
            pl_impact_diff=0.0,
            option_a_carrying_value=0.0,
            option_b_carrying_value=amount,
            notes="Initial cash disbursement to supplier/contractor."
        )
    ]

    current_carrying_value = amount

    for y in range(1, useful_life_years + 1):
        df_y = 1.0 / math.pow(1.0 + annual_discount, y)
        current_carrying_value = max(salvage_val, current_carrying_value - annual_depreciation)
        
        # In Year 1: Opex has 100% tax shield, subsequent years 0
        opex_cf = (opex_year_1_tax_shield if y == 1 else 0.0)
        opex_pl = (amount if y == 1 else 0.0)
        
        # Capex has annual depreciation tax shield, and in final year salvage value
        salvage_inflow = salvage_val if y == useful_life_years else 0.0
        capex_cf = capex_annual_tax_shield + salvage_inflow
        capex_pl = annual_depreciation

        schedule.append(SchedulePeriod(
            period_index=y,
            period_label=f"Year {y}",
            option_a_cash_flow=opex_cf,
            option_b_cash_flow=capex_cf,
            cash_flow_diff=opex_cf - capex_cf,
            discount_factor=df_y,
            discounted_option_a_cf=opex_cf * df_y,
            discounted_option_b_cf=capex_cf * df_y,
            option_a_pl_impact=opex_pl,
            option_b_pl_impact=capex_pl,
            pl_impact_diff=opex_pl - capex_pl,
            option_a_carrying_value=0.0,
            option_b_carrying_value=current_carrying_value,
            notes=(
                f"Year {y}: Opex P&L hit = PKR {opex_pl:,.2f}; Capex Depreciation = PKR {capex_pl:,.2f}. "
                f"Asset Carrying Value = PKR {current_carrying_value:,.2f}."
            )
        ))

    # Summaries
    opex_option = OptionSummary(
        option_key="EXPENSE",
        option_name="Operating Expense (Opex Write-Off)",
        governing_standard="IAS 1 Presentation & Matching Principle",
        initial_cash_outlay=amount,
        total_nominal_cash_outflow=amount,
        present_value_cash_outflow=amount,
        present_value_tax_shield=pv_opex_tax_shield,
        net_present_cost=opex_net_present_cost,
        period_1_pl_charge=opex_year_1_pl,
        total_nominal_pl_charge=amount,
        balance_sheet_impact="Zero asset recorded. Retained earnings drop immediately by after-tax expense.",
        working_capital_impact=f"Immediate Year 1 P&L reduction of PKR {amount:,.2f}; tax shield of PKR {opex_year_1_tax_shield:,.2f} received upfront.",
        key_metrics={
            "year_1_ebitda_impact": -amount,
            "year_1_net_income_impact": -amount * (1.0 - tax_rate),
            "upfront_tax_shield": opex_year_1_tax_shield,
            "pv_tax_shield": pv_opex_tax_shield,
        }
    )

    capex_option = OptionSummary(
        option_key="CAPITALIZE",
        option_name="Balance Sheet Capitalization (IAS 16 PPE)",
        governing_standard="IAS 16 Property, Plant and Equipment",
        initial_cash_outlay=amount,
        total_nominal_cash_outflow=amount - salvage_val,
        present_value_cash_outflow=amount - pv_salvage,
        present_value_tax_shield=pv_capex_tax_shields,
        net_present_cost=capex_net_present_cost,
        period_1_pl_charge=capex_year_1_pl,
        total_nominal_pl_charge=amount - salvage_val,
        balance_sheet_impact=f"Capitalizes Fixed Asset of PKR {amount:,.2f}. Preserves equity and debt covenant headroom.",
        working_capital_impact=f"Year 1 EBITDA is 100% protected (PKR 0 hit). P&L hit is restricted to PKR {capex_year_1_pl:,.2f}.",
        key_metrics={
            "useful_life_years": useful_life_years,
            "annual_depreciation": annual_depreciation,
            "year_1_ebitda_impact": 0.0,
            "year_1_net_income_impact": -annual_depreciation * (1.0 - tax_rate),
            "annual_tax_shield": capex_annual_tax_shield,
            "pv_tax_shields": pv_capex_tax_shields,
        }
    )

    # Financial analysis of TVM tax shield vs EBITDA protection
    tvm_tax_shield_advantage_opex = pv_opex_tax_shield - pv_capex_tax_shields
    year_1_ebitda_protection_capex = amount

    verdict = "CAPITALIZE_IF_QUALIFIED"
    headline = "Strategic Assessment: Capitalize under IAS 16 to Protect EBITDA & Covenants"
    plain_summary = (
        f"Capitalizing this PKR {amount:,.2f} expenditure shields Year 1 EBITDA from a 100% P&L charge, restricting "
        f"Period 1 earnings reduction to straight-line depreciation of PKR {capex_year_1_pl:,.2f}. However, immediate expensing "
        f"would deliver an accelerated tax shield advantage of PKR {tvm_tax_shield_advantage_opex:,.2f} on a present-value basis."
    )
    fin_justification = (
        f"1. **Earnings Impact**: Capitalization preserves PKR {year_1_ebitda_protection_capex:,.2f} of Year 1 EBITDA and "
        f"PKR {(amount - capex_year_1_pl) * (1.0 - tax_rate):,.2f} of Net Profit.\n"
        f"2. **Balance Sheet**: Recognized asset carrying value is PKR {amount - annual_depreciation:,.2f} at Year 1 close.\n"
        f"3. **Tax Timing (TVM)**: Immediate expensing delivers full PKR {opex_year_1_tax_shield:,.2f} tax shield in Year 1, "
        f"whereas capitalization spreads tax relief over {useful_life_years} years (PV = PKR {pv_capex_tax_shields:,.2f})."
    )

    recommendation = ExecutiveRecommendation(
        verdict=verdict,
        headline=headline,
        plain_english_summary=plain_summary,
        financial_justification=fin_justification,
        liquidity_headroom_analysis=(
            f"If enterprise liquidity is tight, immediate expensing optimizes immediate tax payable by PKR {opex_year_1_tax_shield:,.2f}. "
            f"If bank covenants or EBITDA performance are paramount, capitalization is mandatory."
        ),
        cfo_action_plan=[
            "Verify compliance with IAS 16.7 recognition criteria (probable future economic benefits > 1 year).",
            "Routine repairs, servicing, and consumables CANNOT be capitalized under IAS 16 para 12.",
            "If capitalizing, record in Asset Register with assigned depreciation schedule and location tag.",
            "If expensing for tax purposes under statutory initial allowance rules, record deferred tax liability (IAS 12).",
        ],
        risk_flags=[
            "IAS 16 Compliance Gate: Inappropriate capitalization of operating expenses constitutes financial misstatement.",
            "Future Impairment Risk: Capitalized asset must undergo annual IAS 36 impairment review if cash-generating capability drops.",
        ],
        accounting_standard_reference="IAS 16 Property, Plant and Equipment (para 7, 12, 48) & IAS 12 Income Taxes"
    )

    return FinancialSimulationResult(
        scenario_type=ScenarioType.CAPITALIZE_VS_EXPENSE,
        scenario_name="IAS 16 Capitalize vs. Expense Sandboxing Simulation",
        base_amount=amount,
        parameters_applied={
            "useful_life_years": useful_life_years,
            "salvage_value": salvage_val,
            "annual_discount_rate": annual_discount,
            "corporate_tax_rate": tax_rate,
        },
        options={
            "EXPENSE": opex_option,
            "CAPITALIZE": capex_option,
        },
        schedule=schedule,
        variance_summary={
            "year_1_ebitda_protection": year_1_ebitda_protection_capex,
            "tvm_tax_shield_advantage_opex": tvm_tax_shield_advantage_opex,
            "npc_difference": opex_net_present_cost - capex_net_present_cost,
            "year_1_pl_delta": opex_year_1_pl - capex_year_1_pl,
        },
        tax_exposure=None,
        recommendation=recommendation,
    )


# =============================================================================
# Primary Public API: Core Engine Dispatcher
# =============================================================================

def normalize_scenario_type(raw_type: str) -> ScenarioType:
    """Normalize scenario type string or alias into canonical ScenarioType enum."""
    cleaned = (raw_type or "").strip().upper().replace(" ", "_").replace("-", "_")
    
    # 1. Lease vs. Buy aliases
    if cleaned in {
        "LEASE_VS_BUY", "LEASE_BUY", "LEASE_VS_PURCHASE", "IFRS16", "IFRS_16",
        "LEASE_OR_BUY", "BUY_VS_LEASE", "LEASE_ANALYSIS"
    }:
        return ScenarioType.LEASE_VS_BUY
    
    # 2. Cash vs. Bank aliases
    if cleaned in {
        "CASH_VS_BANK", "CASH_BANK", "SECTION73", "SECTION_73", "SEC_73",
        "ITO2001", "ITO_2001", "TAX_SETTLEMENT", "BANK_VS_CASH"
    }:
        return ScenarioType.CASH_VS_BANK
        
    # 3. Capitalize vs. Expense aliases
    if cleaned in {
        "CAPITALIZE_VS_EXPENSE", "CAPEX_VS_OPEX", "CAPEX_OPEX", "IAS16",
        "IAS_16", "CAPITALISE_VS_EXPENSE", "CAPITALIZATION", "EXPENSE_VS_CAPITALIZE"
    }:
        return ScenarioType.CAPITALIZE_VS_EXPENSE

    valid_options = ["LEASE_VS_BUY", "CASH_VS_BANK", "CAPITALIZE_VS_EXPENSE"]
    raise ValueError(
        f"Unsupported scenario_type '{raw_type}'. Supported simulation scenarios: {valid_options}"
    )


def simulate_scenario(
    scenario_type: str,
    amount: float,
    parameters: Optional[Dict[str, Any]] = None,
) -> FinancialSimulationResult:
    """Execute a what-if financial simulation scenario.
    
    Args:
        scenario_type: Scenario identifier or alias:
            - 'LEASE_VS_BUY' (IFRS 16 RoU vs IAS 16 Capex purchase)
            - 'CASH_VS_BANK' (Section 73 ITO 2001 cash penalty vs bank transfer)
            - 'CAPITALIZE_VS_EXPENSE' (IAS 16 balance sheet vs Opex write-off)
        amount: Principal transaction or asset amount (must be positive).
        parameters: Optional scenario-specific modeling parameters.
        
    Returns:
        FinancialSimulationResult: Rich, structured comparative model containing schedules,
        P&L impacts, cash flow schedules, tax exposure diffs, and CFO recommendations.
        
    Raises:
        ValueError: If amount <= 0 or scenario_type is unrecognized.
    """
    if amount <= 0:
        raise ValueError(f"Simulation amount must be strictly greater than 0. Received: {amount}")

    params = parameters or {}
    canonical_type = normalize_scenario_type(scenario_type)

    if canonical_type == ScenarioType.LEASE_VS_BUY:
        return simulate_lease_vs_buy(amount=amount, parameters=params)
    elif canonical_type == ScenarioType.CASH_VS_BANK:
        return simulate_cash_vs_bank(amount=amount, parameters=params)
    elif canonical_type == ScenarioType.CAPITALIZE_VS_EXPENSE:
        return simulate_capitalize_vs_expense(amount=amount, parameters=params)
    else:  # pragma: no cover
        raise ValueError(f"Unhandled scenario type: {canonical_type}")
