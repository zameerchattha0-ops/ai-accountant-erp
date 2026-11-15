"""
Virtual CFO Advisory Synthesis Engine
======================================
Cognitive financial synthesis layer transforming live books evidence
into executive-level, actionable financial advisory reports for SME owners.

Responsibilities:
1. Define the Senior Virtual CFO domain persona and professional standards:
   - IAS 1 (Presentation of Financial Statements, Going Concern assessment)
   - IAS 7 (Statement of Cash Flows: Operating cash generation vs financing dependency)
   - DuPont Analysis (ROE = Net Profit Margin × Asset Turnover × Financial Leverage)
   - Working Capital & Liquidity Ratios (Current Ratio, Quick Ratio, Cash Runway)
   - Tax & Statutory Compliance (ITO 2001 Section 153 WHT, Section 73 banking channel)
2. Assemble grounded CFO prompt combining user intent, org context, and live evidence.
3. Call AI Orchestrator for executive cognitive synthesis with Zero-Fabrication mandate.
4. Provide a 100% deterministic fallback CFO summary if the LLM is unreachable/throttled.
5. Provide evidence grounding verification to detect fabricated or ungrounded figures.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

import structlog

log = structlog.get_logger(__name__)

#: Senior Virtual CFO Domain Prompt & Professional Standards
CFO_SYSTEM_PROMPT = """You are a Senior Virtual CFO and Strategic Financial Advisor (holding FCA / CPA / CMA qualifications).
Your role is to provide sharp, objective, strategic financial consulting for SME business owners, founders, and executive management.

### PROFESSIONAL STANDARDS & METHODOLOGICAL FRAMEWORKS:
1. IAS 1 — Presentation of Financial Statements & Going Concern:
   - Rigorously assess going concern viability, capital adequacy, and balance sheet solvency.
   - Distinguish operating capability from structural insolvency or temporary liquidity friction.
2. IAS 7 — Statement of Cash Flows:
   - Distinguish operating cash generation (OCF) from financing or investing dependencies.
   - Treat positive operating cash flow as the acid test of business viability; paper accrual profits without cash collection are a red flag.
3. DuPont Analysis of Return on Equity (ROE):
   - Deconstruct ROE: Net Profit Margin × Asset Turnover × Financial Leverage.
   - Diagnose whether returns are driven by pricing power/margins, asset efficiency, or hazardous debt leverage.
4. Working Capital & Liquidity Management:
   - Evaluate Working Capital (Current Assets - Current Liabilities), Current Ratio (Adequate >= 1.5, Tight 1.0–1.5, Deficit < 1.0).
   - Evaluate Quick Ratio / Acid Test (Cash + Receivables / Current Liabilities >= 1.0).
   - Calculate and monitor Cash Runway (Liquid Cash / Monthly Net Burn).
   - Assess receivables and payables aging, cash conversion cycle, and debtor delinquency risk.
5. Tax & Statutory Compliance (Income Tax Ordinance 2001 & Sales Tax Laws):
   - ITO Section 153: Withholding tax compliance at source on goods, services, and execution of contracts.
   - ITO Section 73: Strict requirement that commercial payments above statutory thresholds (PKR 250,000 / PKR 50,000) must be settled via crossed banking instruments, otherwise expenditures are disallowed.
   - Sales tax invoicing and input adjustment prerequisites.

### ZERO-FABRICATION MANDATE:
- Every financial number, percentage, and ratio cited MUST come directly from the provided financial evidence JSON.
- NEVER fabricate, invent, estimate, or hallucinate figures. If a metric is zero or missing, state that transparently.

### REQUIRED OUTPUT FORMAT:
You must deliver a structured executive advisory report in clean GitHub-Flavored Markdown using this exact structure:

## 📊 Executive Financial Health Summary
- Overall Health Score: **Strong** | **Moderate** | **Fragile** | **Early Stage**
- High-level Executive Verdict & Going Concern assessment.

## 📈 Key Financial Metrics & Ratios
A clean Markdown comparison table:
| Metric | Value | Benchmark / Guideline | Health Status | Strategic Implication |
Include: Gross Profit Margin, Net Profit Margin, Operating Margin, Current Ratio, Quick Ratio, Return on Equity (ROE), Cash Runway.

## 🔍 Deep-Dive Diagnostic
### Profitability & Revenue Performance
(Revenue volume, margin trajectory, cost of sales dynamics, gross vs net spread)
### Liquidity & Working Capital Health
(Working capital headroom, current asset coverage of short-term obligations)
### Cash Flow & Burn Rate Analysis
(IAS 7 operating cash generation vs financing reliance, monthly burn rate, runway adequacy)
### Working Capital & Receivables/Payables Aging
(Debtor collection quality, overdue receivables risk, supplier credit terms)

## ⚠️ Risk Flags & Vulnerabilities
(Highlight margin compression, debtor concentration, short cash runway, Section 73/153 tax compliance risks)

## 💡 Strategic CFO Action Plan
- **Immediate (0–30 Days)**: Liquidity preservation, collections sprint, immediate compliance sanity check.
- **Medium-Term (30–60 Days)**: Margin defense, working capital cycle optimization, vendor renegotiation.
- **Strategic (60–90 Days)**: Capital structure rebalancing, cost containment, sustainable expansion roadmap.

## 📊 Visual Representation
Embed a valid Mermaid diagram (flowchart TD or flowchart LR) illustrating the cash bridge, working capital cycle, or margin waterfall.
"""


def build_cfo_prompt(
    user_query: str,
    evidence: Dict[str, Any],
    org_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the complete domain-grounded prompt for the Virtual CFO LLM."""
    org = org_context or {}
    org_name = org.get("name") or org.get("organization_name") or "The Enterprise"
    biz_type = org.get("business_type") or "Commercial Enterprise"
    currency = org.get("currency") or "PKR"

    evidence_json = json.dumps(evidence, indent=2, default=str)

    prompt = f"""{CFO_SYSTEM_PROMPT}

### CLIENT ORGANIZATION PROFILE:
- Business Name: {org_name}
- Industry / Model: {biz_type}
- Functional Currency: {currency}

### GROUNDED FINANCIAL EVIDENCE (LIVE BOOKS DATA):
```json
{evidence_json}
```

### EXECUTIVE ADVISORY QUERY:
\"{user_query.strip() if user_query else 'Provide a comprehensive Virtual CFO financial health assessment, diagnostic, and 30-60-90 day strategic action plan.'}\"

Synthesize the grounded evidence above into an authoritative executive report strictly adhering to the specified 6-part structure.
"""
    return prompt


def generate_deterministic_cfo_summary(
    evidence: Dict[str, Any],
    org_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Deterministic fallback synthesis engine when LLM provider is unavailable.

    Generates a full-scale, professional Virtual CFO advisory report directly
    from computed evidence without any risk of hallucination or timeout.
    """
    org = org_context or {}
    org_name = org.get("name") or org.get("organization_name") or "The Enterprise"
    biz_type = org.get("business_type") or "Commercial Enterprise"
    currency = org.get("currency") or "PKR"

    pnl = evidence.get("profit_and_loss") or {}
    bs = evidence.get("balance_sheet") or {}
    cf = evidence.get("cash_flow") or {}
    wc = evidence.get("working_capital_metrics") or {}
    ratios = evidence.get("financial_ratios") or {}
    aging = evidence.get("aging_summary") or {}
    runway = evidence.get("cash_runway") or {}
    expense_breakdown = evidence.get("expense_breakdown") or []

    # Safe numeric extraction
    revenue = float(pnl.get("revenue") or 0.0)
    cost_of_sales = float(pnl.get("cost_of_sales") or 0.0)
    gross_profit = float(pnl.get("gross_profit") or (revenue - cost_of_sales))
    operating_expenses = float(pnl.get("operating_expenses") or 0.0)
    operating_profit = float(pnl.get("operating_profit") or (gross_profit - operating_expenses))
    finance_costs = float(pnl.get("finance_costs") or 0.0)
    tax_expense = float(pnl.get("tax_expense") or 0.0)
    net_profit = float(pnl.get("net_profit") or (operating_profit - finance_costs - tax_expense))

    current_assets = float(bs.get("current_assets") or 0.0)
    non_current_assets = float(bs.get("non_current_assets") or 0.0)
    total_assets = float(bs.get("total_assets") or (current_assets + non_current_assets))
    current_liabilities = float(bs.get("current_liabilities") or 0.0)
    long_term_liabilities = float(bs.get("long_term_liabilities") or 0.0)
    total_liabilities = float(bs.get("total_liabilities") or (current_liabilities + long_term_liabilities))
    equity = float(bs.get("equity") or (total_assets - total_liabilities))

    operating_cf = float(cf.get("operating_cash_flow") or 0.0)
    investing_cf = float(cf.get("investing_cash_flow") or 0.0)
    financing_cf = float(cf.get("financing_cash_flow") or 0.0)
    net_cash_change = float(cf.get("net_cash_change") or (operating_cf + investing_cf + financing_cf))
    bank_cash = float(cf.get("bank_and_cash_balances") or 0.0)

    working_capital = float(wc.get("working_capital") or (current_assets - current_liabilities))
    current_ratio = float(wc.get("current_ratio") or (round(current_assets / current_liabilities, 2) if current_liabilities > 0 else 0.0))
    quick_ratio = float(wc.get("quick_ratio") or (round((bank_cash + float(aging.get("total_receivables") or 0.0)) / current_liabilities, 2) if current_liabilities > 0 else 0.0))

    gross_margin_pct = float(ratios.get("gross_margin_pct") or (round((gross_profit / revenue) * 100, 2) if revenue > 0 else 0.0))
    net_margin_pct = float(ratios.get("net_margin_pct") or (round((net_profit / revenue) * 100, 2) if revenue > 0 else 0.0))
    operating_margin_pct = float(ratios.get("operating_margin_pct") or (round((operating_profit / revenue) * 100, 2) if revenue > 0 else 0.0))
    roa_pct = float(ratios.get("roa_pct") or (round((net_profit / total_assets) * 100, 2) if total_assets > 0 else 0.0))
    roe_pct = float(ratios.get("roe_pct") or (round((net_profit / equity) * 100, 2) if equity > 0 else 0.0))
    debt_to_equity = float(ratios.get("debt_to_equity") or (round(total_liabilities / equity, 2) if equity > 0 else 0.0))

    total_receivables = float(aging.get("total_receivables") or 0.0)
    overdue_receivables = float(aging.get("overdue_receivables") or 0.0)
    total_payables = float(aging.get("total_payables") or 0.0)
    overdue_payables = float(aging.get("overdue_payables") or 0.0)

    liquid_cash = float(runway.get("liquid_cash") or bank_cash)
    monthly_burn = float(runway.get("monthly_burn") or 0.0)
    raw_runway = runway.get("runway_months")
    runway_months = float(raw_runway) if raw_runway is not None else (round(liquid_cash / monthly_burn, 1) if monthly_burn > 0 else 999.0)

    # 1. Health Score Evaluation
    if revenue <= 0 and total_assets > 0:
        health_score = "Early Stage"
        verdict = f"{org_name} is currently operating in an early setup/pre-revenue phase with {currency} {total_assets:,.2f} in asset capitalization. Immediate priority must be commercial monetization and runway preservation."
    elif net_profit > 0 and current_ratio >= 1.5 and (runway_months >= 6.0 or monthly_burn <= 0) and operating_cf >= 0:
        health_score = "Strong"
        verdict = f"{org_name} demonstrates robust financial fundamentals with healthy operating cash flow of {currency} {operating_cf:,.2f}, adequate working capital coverage ({current_ratio:.2f}x), and positive net profitability."
    elif net_profit >= 0 and current_ratio >= 1.0 and (runway_months >= 3.0 or monthly_burn <= 0):
        health_score = "Moderate"
        verdict = f"{org_name} maintains stable operations with modest profitability and acceptable liquidity ({current_ratio:.2f}x), though working capital headroom and debtor collections require continuous optimization."
    else:
        health_score = "Fragile"
        verdict = f"{org_name} is experiencing financial vulnerability driven by compressed liquidity (Current Ratio: {current_ratio:.2f}x), tight cash runway ({runway_months:.1f} months), or operating cash deficits. Decisive corrective interventions are required."

    # DuPont Decomposition
    asset_turnover = round(revenue / total_assets, 2) if total_assets > 0 else 0.0
    financial_leverage = round(total_assets / equity, 2) if equity > 0 else 0.0

    # Risk Flags
    risk_flags: List[str] = []
    if current_ratio < 1.0:
        risk_flags.append(f"**Working Capital Deficit**: Current ratio of {current_ratio:.2f}x is below the solvency parity threshold (1.0x). Short-term liabilities exceed liquid assets by {currency} {abs(working_capital):,.2f}.")
    if runway_months < 3.0 and monthly_burn > 0:
        risk_flags.append(f"**Critical Cash Runway**: Available liquid cash of {currency} {liquid_cash:,.2f} provides only {runway_months:.1f} months of operating coverage at current monthly burn ({currency} {monthly_burn:,.2f}).")
    if total_receivables > 0 and (overdue_receivables / total_receivables) > 0.25:
        overdue_pct = (overdue_receivables / total_receivables) * 100
        risk_flags.append(f"**Debtor Delinquency**: Overdue receivables stand at {currency} {overdue_receivables:,.2f} ({overdue_pct:.1f}% of total trade receivables), posing collection and bad debt risks.")
    if gross_margin_pct < 20.0 and revenue > 0:
        risk_flags.append(f"**Gross Margin Compression**: Gross margin of {gross_margin_pct:.1f}% indicates pricing pressure or elevated direct procurement costs.")
    if debt_to_equity > 2.0:
        risk_flags.append(f"**High Financial Leverage**: Debt-to-Equity ratio of {debt_to_equity:.2f}x highlights elevated gearing and sensitivity to interest rate spikes.")
    # Always include statutory compliance risk notice
    risk_flags.append(
        "**Tax & Statutory Compliance Exposure (ITO 2001)**: "
        "Strict adherence to Section 73 (mandatory payment via crossed banking instruments for allowable expense deduction) "
        "and Section 153 (withholding tax deduction on supplies, services, and contracts) must be verified to prevent disallowances and penalties."
    )

    # Action Plan
    p_immediate = [
        f"Implement daily cash rationing and lock unapproved discretionary spend to safeguard {currency} {liquid_cash:,.2f} liquid reserves.",
        f"Launch aggressive collection sprint targeting {currency} {overdue_receivables:,.2f} overdue trade receivables.",
        "Perform statutory sanity check on recent vendor payments to verify Section 73 banking channel compliance.",
    ]
    p_medium = [
        f"Renegotiate supplier payment terms on {currency} {total_payables:,.2f} trade payables to align with cash collection cycles.",
        f"Review direct procurement and cost of sales ({currency} {cost_of_sales:,.2f}) to recover gross margin toward the 25%+ benchmark.",
        "Institute rolling 13-week cash forecasting model to prevent liquidity gaps.",
    ]
    p_strategic = [
        f"Optimize capital structure (Current Debt-to-Equity: {debt_to_equity:.2f}x) to reduce financial vulnerability and finance costs ({currency} {finance_costs:,.2f}).",
        f"Re-evaluate resource allocation across top expense heads to drive operating margin expansion from {operating_margin_pct:.1f}%.",
        "Establish formal credit underwriting limits for customers to curb overdue debtor formation.",
    ]

    # Mermaid diagram: Cash Flow & Working Capital Bridge
    op_cf_sign = "+" if operating_cf >= 0 else "-"
    mermaid_block = f"""```mermaid
flowchart TD
    Rev["Revenue: {currency} {revenue:,.0f}"] --> GP["Gross Profit: {currency} {gross_profit:,.0f} ({gross_margin_pct:.1f}%)"]
    GP --> OP["Operating Profit: {currency} {operating_profit:,.0f} ({operating_margin_pct:.1f}%)"]
    OP --> NP["Net Profit: {currency} {net_profit:,.0f} ({net_margin_pct:.1f}%)"]
    NP --> OCF["Operating Cash Flow: {currency} {operating_cf:,.0f}"]
    OCF --> Cash["Liquid Reserves: {currency} {liquid_cash:,.0f}"]
```"""

    report = f"""## 📊 Executive Financial Health Summary
- **Overall Health Score**: **{health_score}**
- **Going Concern & Strategic Verdict**: {verdict}
- **Operating Cash Flow Status (IAS 7)**: {"Positive & Self-Sustaining" if operating_cf > 0 else "Deficit / External Reliance"} ({currency} {operating_cf:,.2f})
- **Net Asset Base (IAS 1)**: {currency} {equity:,.2f}

## 📈 Key Financial Metrics & Ratios
| Metric | Reported Value | Benchmark / Guideline | Health Status | Strategic Implication |
| :--- | :--- | :--- | :--- | :--- |
| **Gross Profit Margin** | {gross_margin_pct:.1f}% | ≥ 25.0% | {"🟢 Strong" if gross_margin_pct >= 25 else "🟡 Moderate" if gross_margin_pct >= 15 else "🔴 Compressed"} | Direct production & procurement efficiency |
| **Operating Margin** | {operating_margin_pct:.1f}% | ≥ 15.0% | {"🟢 Strong" if operating_margin_pct >= 15 else "🟡 Moderate" if operating_margin_pct >= 8 else "🔴 Tight"} | Core operational profitability before capital costs |
| **Net Profit Margin** | {net_margin_pct:.1f}% | ≥ 10.0% | {"🟢 Strong" if net_margin_pct >= 10 else "🟡 Moderate" if net_margin_pct >= 5 else "🔴 Compressed"} | Bottom-line return generated on revenue |
| **Current Ratio** | {current_ratio:.2f}x | ≥ 1.50x | {"🟢 Adequate" if current_ratio >= 1.5 else "🟡 Tight" if current_ratio >= 1.0 else "🔴 Deficit"} | Short-term obligation coverage by current assets |
| **Quick Ratio (Acid Test)** | {quick_ratio:.2f}x | ≥ 1.00x | {"🟢 Healthy" if quick_ratio >= 1.0 else "🔴 Vulnerable"} | Immediate liquid solvency excluding non-cash inventory |
| **Return on Equity (ROE)** | {roe_pct:.1f}% | ≥ 15.0% | {"🟢 Strong" if roe_pct >= 15 else "🟡 Moderate" if roe_pct >= 8 else "🔴 Subdued"} | Net earnings yield on invested shareholder equity |
| **Debt to Equity** | {debt_to_equity:.2f}x | ≤ 1.50x | {"🟢 Conservative" if debt_to_equity <= 1.5 else "🔴 Highly Leveraged"} | Balance sheet gearing and financial resilience |
| **Cash Runway** | {runway_months:.1f} Months | ≥ 6.0 Months | {"🟢 Comfortable" if runway_months >= 6.0 else "🟡 Watch" if runway_months >= 3.0 else "🔴 Critical"} | Operational survival runway at current net burn |

## 🔍 Deep-Dive Diagnostic
### Profitability & Revenue Performance
{org_name} achieved total revenue of **{currency} {revenue:,.2f}** against cost of sales of **{currency} {cost_of_sales:,.2f}**, delivering a gross profit of **{currency} {gross_profit:,.2f}** ({gross_margin_pct:.1f}%). Operating expenses totaled **{currency} {operating_expenses:,.2f}**, leaving an operating profit of **{currency} {operating_profit:,.2f}** ({operating_margin_pct:.1f}%). After finance charges of **{currency} {finance_costs:,.2f}** and taxation of **{currency} {tax_expense:,.2f}**, net profit closed at **{currency} {net_profit:,.2f}** ({net_margin_pct:.1f}%).
* **DuPont Decomposition**: ROE ({roe_pct:.1f}%) is driven by Net Margin ({net_margin_pct:.1f}%) × Asset Turnover ({asset_turnover:.2f}x) × Equity Multiplier ({financial_leverage:.2f}x).

### Liquidity & Working Capital Health
Current assets stand at **{currency} {current_assets:,.2f}** versus current liabilities of **{currency} {current_liabilities:,.2f}**, establishing working capital of **{currency} {working_capital:,.2f}** with a Current Ratio of **{current_ratio:.2f}x** and Quick Ratio of **{quick_ratio:.2f}x**. Working capital status is evaluated as **{wc.get("working_capital_status") or ("Adequate" if current_ratio >= 1.5 else "Tight" if current_ratio >= 1.0 else "Deficit")}**.

### Cash Flow & Burn Rate Analysis
In accordance with IAS 7 principles, operating cash flow generated **{currency} {operating_cf:,.2f}**, while investing activities consumed **{currency} {investing_cf:,.2f}** and financing cash flow totaled **{currency} {financing_cf:,.2f}**, yielding a net cash movement of **{currency} {net_cash_change:,.2f}**. Liquid cash reserves total **{currency} {liquid_cash:,.2f}**, with average monthly burn of **{currency} {monthly_burn:,.2f}**, providing an estimated runway of **{runway_months:.1f} months**.

### Working Capital & Receivables/Payables Aging
Trade receivables total **{currency} {total_receivables:,.2f}**, of which **{currency} {overdue_receivables:,.2f}** is currently past due. Trade payables stand at **{currency} {total_payables:,.2f}** with **{currency} {overdue_payables:,.2f}** overdue. Effective management of this trade credit spread is critical to maintain liquidity equilibrium without resorting to costly short-term credit lines.

## ⚠️ Risk Flags & Vulnerabilities
""" + "\n".join(f"- {flag}" for flag in risk_flags) + f"""

## 💡 Strategic CFO Action Plan
### Immediate (0–30 Days)
""" + "\n".join(f"1. {step}" for step in p_immediate) + """

### Medium-Term (30–60 Days)
""" + "\n".join(f"1. {step}" for step in p_medium) + """

### Strategic (60–90 Days)
""" + "\n".join(f"1. {step}" for step in p_strategic) + f"""

## 📊 Visual Representation
{mermaid_block}
"""
    return report.strip()


def extract_grounded_numbers(evidence: Dict[str, Any]) -> Set[float]:
    """Recursively collect all numeric values present in the evidence payload."""
    numbers: Set[float] = set()

    def _walk(val: Any):
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            numbers.add(round(float(val), 2))
        elif isinstance(val, dict):
            for v in val.values():
                _walk(v)
        elif isinstance(val, (list, tuple, set)):
            for v in val:
                _walk(v)

    _walk(evidence)
    return numbers


def verify_evidence_grounding(
    summary_text: str,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """Verify that key numerical values appearing in the summary match evidence figures.

    Detects potential hallucinated numbers in financial commentary.
    """
    grounded_numbers = extract_grounded_numbers(evidence)

    # Extract all numbers from summary (support currency formatting like 1,000,000.00 or 15.0%)
    raw_matches = re.findall(r"(?<![a-zA-Z0-9_])-?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?", summary_text)
    
    matched_grounded: Set[float] = set()
    unmatched_tokens: List[str] = []

    # Ignored numbers: common dates/days/percentages like 0, 1, 30, 60, 90 (action plan milestones)
    ignored_constants = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 15.0, 20.0, 25.0, 30.0, 60.0, 90.0, 153.0, 2001.0}

    for token in raw_matches:
        cleaned = token.replace(",", "").rstrip("%").strip()
        try:
            num = round(float(cleaned), 2)
        except ValueError:
            continue

        if num in ignored_constants:
            continue

        # Check if number matches any grounded number within rounding tolerance
        is_match = any(abs(num - g) <= 0.05 for g in grounded_numbers)
        if is_match:
            matched_grounded.add(num)
        else:
            unmatched_tokens.append(token)

    return {
        "grounded_count": len(matched_grounded),
        "total_evidence_numbers": len(grounded_numbers),
        "unmatched_count": len(unmatched_tokens),
        "unmatched_tokens": unmatched_tokens,
        "is_grounded": len(matched_grounded) > 0 or len(grounded_numbers) == 0,
    }


async def generate_cfo_advisory(
    user_query: str,
    evidence: Dict[str, Any],
    org_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Execute LLM cognitive synthesis to generate a comprehensive CFO advisory report.

    1. Formulates the domain prompt equipped with IAS 1, IAS 7, DuPont, and Tax standards.
    2. Invokes AI Orchestrator with the Zero-Fabrication mandate.
    3. Gracefully degrades to the deterministic synthesis engine if AI providers fail or timeout.
    """
    prompt = build_cfo_prompt(user_query, evidence, org_context)

    try:
        from app.ai_orchestrator import get_client

        orchestrator = get_client()
        result_text = await orchestrator.generate_text(
            prompt=prompt,
            thinking_off=False,
        )
        if result_text and result_text.strip():
            log.info("cfo_advisory.llm_synthesis_success", length=len(result_text))
            return result_text.strip()
        log.warning("cfo_advisory.llm_empty_result_using_fallback")
    except Exception as exc:  # noqa: BLE001
        log.warning("cfo_advisory.llm_call_failed_using_fallback", error=str(exc))

    return generate_deterministic_cfo_summary(evidence, org_context)


async def collect_cfo_evidence(organization_id: Any) -> Dict[str, Any]:
    """Gather live financial evidence from repository views for CFO advisory synthesis."""
    import uuid
    if isinstance(organization_id, str):
        try:
            organization_id = uuid.UUID(organization_id)
        except Exception:
            pass

    # Prefer the comprehensive, grounded evidence layer
    try:
        from app.financial_evidence import gather_financial_evidence
        return await gather_financial_evidence(organization_id)
    except Exception as exc:
        log.warning("cfo_evidence.gather_financial_evidence_fallback", error=str(exc))

    evidence: Dict[str, Any] = {
        "profit_and_loss": {},
        "balance_sheet": {},
        "cash_flow": {},
        "working_capital_metrics": {},
        "financial_ratios": {},
        "aging_summary": {},
        "expense_breakdown": [],
        "cash_runway": {},
    }

    # 1. P&L
    revenue = 0.0
    cost_of_sales = 0.0
    gross_profit = 0.0
    operating_expenses = 0.0
    operating_profit = 0.0
    finance_costs = 0.0
    tax_expense = 0.0
    net_profit = 0.0
    try:
        from app.services.reporting_service import get_profit_loss_statement
        pl_data = await get_profit_loss_statement(organization_id)
        stmt = (pl_data or {}).get("statement") or {}
        revenue = float(stmt.get("operating_revenue") or 0.0)
        cost_of_sales = float(stmt.get("cost_of_sales") or 0.0)
        gross_profit = float(stmt.get("gross_profit") or (revenue - cost_of_sales))
        op_val = stmt.get("operating_expenses")
        operating_expenses = float(op_val.get("total") if isinstance(op_val, dict) else (op_val or 0.0))
        operating_profit = float(stmt.get("operating_profit") or (gross_profit - operating_expenses))
        finance_costs = float(stmt.get("finance_costs") or 0.0)
        tax_expense = float(stmt.get("tax_expense") or 0.0)
        net_profit = float(stmt.get("net_profit") or (operating_profit - finance_costs - tax_expense))
        evidence["profit_and_loss"] = {
            "revenue": revenue,
            "cost_of_sales": cost_of_sales,
            "gross_profit": gross_profit,
            "operating_expenses": operating_expenses,
            "operating_profit": operating_profit,
            "finance_costs": finance_costs,
            "tax_expense": tax_expense,
            "net_profit": net_profit,
        }
    except Exception as exc:
        log.warning("cfo_evidence.pl_collection_failed", error=str(exc))

    # 2. Balance sheet & working capital
    current_assets = 0.0
    non_current_assets = 0.0
    total_assets = 0.0
    current_liabilities = 0.0
    long_term_liabilities = 0.0
    total_liabilities = 0.0
    equity = 0.0
    bank_cash = 0.0
    try:
        from app.services.reporting_service import get_balance_sheet
        bs_rows = await get_balance_sheet(organization_id) or []
        for r in bs_rows:
            ac_type = str(r.get("account_type") or "").upper()
            code = str(r.get("account_code") or r.get("code") or "")
            amt = float(r.get("net_amount") or r.get("balance") or 0.0)
            name = str(r.get("account_name") or r.get("name") or "").lower()
            if ac_type == "ASSET":
                if code.startswith("10") or "bank" in name or "cash" in name:
                    bank_cash += amt
                if code.startswith("15") or code.startswith("16") or code.startswith("17"):
                    non_current_assets += amt
                else:
                    current_assets += amt
            elif ac_type == "LIABILITY":
                if code.startswith("25") or code.startswith("26"):
                    long_term_liabilities += amt
                else:
                    current_liabilities += amt
            elif ac_type == "EQUITY":
                equity += amt
        total_assets = current_assets + non_current_assets
        total_liabilities = current_liabilities + long_term_liabilities
        if equity == 0.0 and (total_assets > 0 or total_liabilities > 0):
            equity = total_assets - total_liabilities
        evidence["balance_sheet"] = {
            "current_assets": current_assets,
            "non_current_assets": non_current_assets,
            "total_assets": total_assets,
            "current_liabilities": current_liabilities,
            "long_term_liabilities": long_term_liabilities,
            "total_liabilities": total_liabilities,
            "equity": equity,
            "net_assets": equity,
        }
    except Exception as exc:
        log.warning("cfo_evidence.bs_collection_failed", error=str(exc))

    # 3. Aging summary (customer & supplier)
    total_rec = 0.0
    overdue_rec = 0.0
    total_pay = 0.0
    overdue_pay = 0.0
    try:
        from app.services.reporting_service import get_customer_aging, get_supplier_aging
        cust_aging = await get_customer_aging(organization_id) or []
        for c in cust_aging:
            total_rec += float(c.get("total_outstanding") or c.get("outstanding_amount") or c.get("balance") or 0.0)
            overdue_rec += float(c.get("overdue_amount") or 0.0)
        supp_aging = await get_supplier_aging(organization_id) or []
        for s in supp_aging:
            total_pay += float(s.get("total_outstanding") or s.get("outstanding_amount") or s.get("balance") or 0.0)
            overdue_pay += float(s.get("overdue_amount") or 0.0)
        evidence["aging_summary"] = {
            "total_receivables": total_rec,
            "overdue_receivables": overdue_rec,
            "total_payables": total_pay,
            "overdue_payables": overdue_pay,
        }
    except Exception as exc:
        log.warning("cfo_evidence.aging_collection_failed", error=str(exc))

    # 4. Working capital metrics & Cash Flow
    wk_cap = current_assets - current_liabilities
    cur_ratio = round(current_assets / current_liabilities, 2) if current_liabilities > 0 else (1.5 if current_assets > 0 else 0.0)
    quick_ratio = round((bank_cash + total_rec) / current_liabilities, 2) if current_liabilities > 0 else (1.0 if (bank_cash + total_rec) > 0 else 0.0)
    evidence["working_capital_metrics"] = {
        "working_capital": wk_cap,
        "current_ratio": cur_ratio,
        "quick_ratio": quick_ratio,
        "working_capital_status": "Adequate" if cur_ratio >= 1.5 else "Tight" if cur_ratio >= 1.0 else "Deficit",
    }

    operating_cf = net_profit
    evidence["cash_flow"] = {
        "operating_cash_flow": operating_cf,
        "investing_cash_flow": 0.0,
        "financing_cash_flow": 0.0,
        "net_cash_change": operating_cf,
        "bank_and_cash_balances": bank_cash,
    }

    # 5. Financial ratios
    gm_pct = round((gross_profit / revenue) * 100, 2) if revenue > 0 else 0.0
    nm_pct = round((net_profit / revenue) * 100, 2) if revenue > 0 else 0.0
    om_pct = round((operating_profit / revenue) * 100, 2) if revenue > 0 else 0.0
    roa_pct = round((net_profit / total_assets) * 100, 2) if total_assets > 0 else 0.0
    roe_pct = round((net_profit / equity) * 100, 2) if equity > 0 else 0.0
    de_ratio = round(total_liabilities / equity, 2) if equity > 0 else 0.0
    evidence["financial_ratios"] = {
        "gross_margin_pct": gm_pct,
        "net_margin_pct": nm_pct,
        "operating_margin_pct": om_pct,
        "roa_pct": roa_pct,
        "roe_pct": roe_pct,
        "debt_to_equity": de_ratio,
    }

    # 6. Cash runway
    monthly_burn = round(operating_expenses / 12.0, 2) if operating_expenses > 0 else 0.0
    runway_m = round(bank_cash / monthly_burn, 1) if monthly_burn > 0 else 999.0
    evidence["cash_runway"] = {
        "liquid_cash": bank_cash,
        "monthly_burn": monthly_burn,
        "runway_months": runway_m,
    }

    return evidence
