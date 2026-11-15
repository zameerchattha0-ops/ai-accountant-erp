"""
Unit Tests for Virtual CFO Advisory Synthesis Engine
=====================================================
Tests for `app/financial_advisor.py`:
1. System prompt assembly & accounting frameworks (IAS 1, IAS 7, DuPont, Working Capital, ITO 2001).
2. LLM synthesis call with mocked orchestrator.
3. Fallback deterministic synthesis when LLM is unavailable/throttled.
4. Evidence grounding verification & hallucination detection.
5. Edge cases: zero revenue, zero liabilities, division by zero resilience.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.financial_advisor import (
    CFO_SYSTEM_PROMPT,
    build_cfo_prompt,
    extract_grounded_numbers,
    generate_cfo_advisory,
    generate_deterministic_cfo_summary,
    verify_evidence_grounding,
)


@pytest.fixture
def sample_evidence():
    return {
        "profit_and_loss": {
            "revenue": 1000000.0,
            "cost_of_sales": 600000.0,
            "gross_profit": 400000.0,
            "operating_expenses": 250000.0,
            "operating_profit": 150000.0,
            "finance_costs": 20000.0,
            "tax_expense": 30000.0,
            "net_profit": 100000.0,
        },
        "balance_sheet": {
            "current_assets": 450000.0,
            "non_current_assets": 800000.0,
            "total_assets": 1250000.0,
            "current_liabilities": 250000.0,
            "long_term_liabilities": 300000.0,
            "total_liabilities": 550000.0,
            "equity": 700000.0,
            "net_assets": 700000.0,
        },
        "cash_flow": {
            "operating_cash_flow": 120000.0,
            "investing_cash_flow": -50000.0,
            "financing_cash_flow": -30000.0,
            "net_cash_change": 40000.0,
            "bank_and_cash_balances": 180000.0,
        },
        "working_capital_metrics": {
            "working_capital": 200000.0,
            "current_ratio": 1.8,
            "quick_ratio": 1.4,
            "working_capital_status": "Adequate",
        },
        "financial_ratios": {
            "gross_margin_pct": 40.0,
            "net_margin_pct": 10.0,
            "operating_margin_pct": 15.0,
            "roa_pct": 8.0,
            "roe_pct": 14.29,
            "debt_to_equity": 0.79,
        },
        "aging_summary": {
            "total_receivables": 150000.0,
            "overdue_receivables": 35000.0,
            "total_payables": 100000.0,
            "overdue_payables": 15000.0,
        },
        "expense_breakdown": [
            {"account_name": "Salaries & Wages", "amount": 150000.0, "percentage": 60.0},
            {"account_name": "Rent", "amount": 50000.0, "percentage": 20.0},
            {"account_name": "Utilities", "amount": 25000.0, "percentage": 10.0},
        ],
        "cash_runway": {
            "liquid_cash": 180000.0,
            "monthly_burn": 45000.0,
            "runway_months": 4.0,
        },
    }


@pytest.fixture
def sample_org_context():
    return {
        "name": "Apex Distribution Ltd",
        "business_type": "Wholesale & Distribution",
        "currency": "PKR",
    }


# ===================================================================
# 1. System Prompt & Accounting Frameworks Tests
# ===================================================================

def test_cfo_system_prompt_standards_and_frameworks():
    """Verify that CFO domain prompt incorporates all required professional frameworks."""
    # Senior Virtual CFO Persona
    assert "Senior Virtual CFO" in CFO_SYSTEM_PROMPT
    assert "FCA / CPA / CMA" in CFO_SYSTEM_PROMPT

    # Accounting Standards
    assert "IAS 1" in CFO_SYSTEM_PROMPT
    assert "Going Concern" in CFO_SYSTEM_PROMPT
    assert "IAS 7" in CFO_SYSTEM_PROMPT
    assert "Operating cash generation" in CFO_SYSTEM_PROMPT or "operating cash flow" in CFO_SYSTEM_PROMPT.lower()

    # DuPont Framework
    assert "DuPont" in CFO_SYSTEM_PROMPT
    assert "ROE" in CFO_SYSTEM_PROMPT
    assert "Asset Turnover" in CFO_SYSTEM_PROMPT
    assert "Financial Leverage" in CFO_SYSTEM_PROMPT

    # Working Capital & Liquidity Ratios
    assert "Working Capital" in CFO_SYSTEM_PROMPT
    assert "Current Ratio" in CFO_SYSTEM_PROMPT
    assert "Quick Ratio" in CFO_SYSTEM_PROMPT or "Acid Test" in CFO_SYSTEM_PROMPT
    assert "Cash Runway" in CFO_SYSTEM_PROMPT

    # Tax & Statutory Compliance
    assert "Income Tax Ordinance 2001" in CFO_SYSTEM_PROMPT or "ITO" in CFO_SYSTEM_PROMPT
    assert "Section 153" in CFO_SYSTEM_PROMPT
    assert "Section 73" in CFO_SYSTEM_PROMPT

    # Zero-Fabrication Mandate
    assert "ZERO-FABRICATION MANDATE" in CFO_SYSTEM_PROMPT
    assert "NEVER fabricate" in CFO_SYSTEM_PROMPT


def test_build_cfo_prompt_assembly(sample_evidence, sample_org_context):
    """Verify prompt combines org context, evidence JSON, and user query."""
    user_query = "What is our liquidity risk and runway status?"
    prompt = build_cfo_prompt(user_query, sample_evidence, sample_org_context)

    # Contains client profile
    assert "Apex Distribution Ltd" in prompt
    assert "Wholesale & Distribution" in prompt
    assert "PKR" in prompt

    # Contains query
    assert user_query in prompt

    # Contains serialized evidence figures
    assert "1000000.0" in prompt
    assert "450000.0" in prompt
    assert "180000.0" in prompt
    assert "Salaries & Wages" in prompt

    # Contains 6-section structure directives
    assert "Executive Financial Health Summary" in prompt
    assert "Key Financial Metrics & Ratios" in prompt
    assert "Deep-Dive Diagnostic" in prompt
    assert "Risk Flags & Vulnerabilities" in prompt
    assert "Strategic CFO Action Plan" in prompt
    assert "Visual Representation" in prompt


# ===================================================================
# 2. LLM Synthesis Call with Mocked Orchestrator
# ===================================================================

@pytest.mark.asyncio
async def test_generate_cfo_advisory_llm_success(sample_evidence, sample_org_context):
    """Test successful LLM advisory generation using mocked AI orchestrator."""
    mock_llm_response = """## 📊 Executive Financial Health Summary
- Overall Health Score: **Strong**
- High-level Executive Verdict: Apex Distribution Ltd shows robust financial health.

## 📈 Key Financial Metrics & Ratios
| Metric | Value | Benchmark | Health Status | Strategic Implication |
| Gross Margin | 40.0% | >= 25% | Strong | Good pricing |

## 🔍 Deep-Dive Diagnostic
### Profitability & Revenue Performance
Revenue reached PKR 1,000,000.00 with net profit of PKR 100,000.00.

## ⚠️ Risk Flags & Vulnerabilities
- Debtor collection delay.

## 💡 Strategic CFO Action Plan
- Immediate: Accelerate receivables collection.

## 📊 Visual Representation
```mermaid
flowchart TD
  Rev --> Profit
```
"""

    mock_client = MagicMock()
    mock_client.generate_text = AsyncMock(return_value=mock_llm_response)

    with patch("app.ai_orchestrator.get_client", return_value=mock_client):
        result = await generate_cfo_advisory(
            user_query="Evaluate our financial performance",
            evidence=sample_evidence,
            org_context=sample_org_context,
        )

        assert result == mock_llm_response.strip()
        mock_client.generate_text.assert_awaited_once()
        call_kwargs = mock_client.generate_text.call_args.kwargs
        assert "Apex Distribution Ltd" in call_kwargs["prompt"]
        assert call_kwargs["thinking_off"] is False


# ===================================================================
# 3. Fallback Deterministic Summary Tests
# ===================================================================

def test_deterministic_summary_structure_and_metrics(sample_evidence, sample_org_context):
    """Verify deterministic summary produces all 6 sections and accurate calculations."""
    summary = generate_deterministic_cfo_summary(sample_evidence, sample_org_context)

    # Verify all 6 mandatory sections
    assert "## 📊 Executive Financial Health Summary" in summary
    assert "## 📈 Key Financial Metrics & Ratios" in summary
    assert "## 🔍 Deep-Dive Diagnostic" in summary
    assert "### Profitability & Revenue Performance" in summary
    assert "### Liquidity & Working Capital Health" in summary
    assert "### Cash Flow & Burn Rate Analysis" in summary
    assert "### Working Capital & Receivables/Payables Aging" in summary
    assert "## ⚠️ Risk Flags & Vulnerabilities" in summary
    assert "## 💡 Strategic CFO Action Plan" in summary
    assert "### Immediate (0–30 Days)" in summary
    assert "### Medium-Term (30–60 Days)" in summary
    assert "### Strategic (60–90 Days)" in summary
    assert "## 📊 Visual Representation" in summary

    # Verify Mermaid Diagram is present
    assert "```mermaid" in summary
    assert "flowchart TD" in summary

    # Verify numbers from evidence are accurately represented
    assert "1,000,000.00" in summary  # Revenue
    assert "400,000.00" in summary    # Gross Profit
    assert "100,000.00" in summary    # Net Profit
    assert "1.80x" in summary         # Current Ratio
    assert "1.40x" in summary         # Quick Ratio
    assert "4.0 Months" in summary or "4.0 months" in summary  # Runway

    # Verify statutory tax references
    assert "Section 73" in summary
    assert "Section 153" in summary


def test_deterministic_summary_health_scores():
    """Verify health score categorization: Strong, Moderate, Fragile, Early Stage."""
    # 1. Strong Case
    strong_evidence = {
        "profit_and_loss": {"revenue": 500000, "net_profit": 50000},
        "balance_sheet": {"current_assets": 200000, "current_liabilities": 100000, "total_assets": 500000, "equity": 300000},
        "cash_flow": {"operating_cash_flow": 60000, "bank_and_cash_balances": 150000},
        "working_capital_metrics": {"current_ratio": 2.0, "quick_ratio": 1.5},
        "cash_runway": {"liquid_cash": 150000, "monthly_burn": 10000, "runway_months": 15.0},
    }
    summary_strong = generate_deterministic_cfo_summary(strong_evidence)
    assert "**Strong**" in summary_strong

    # 2. Fragile Case (Deficit working capital & low runway)
    fragile_evidence = {
        "profit_and_loss": {"revenue": 200000, "net_profit": -50000},
        "balance_sheet": {"current_assets": 50000, "current_liabilities": 100000, "total_assets": 100000, "equity": 10000},
        "cash_flow": {"operating_cash_flow": -30000, "bank_and_cash_balances": 15000},
        "working_capital_metrics": {"current_ratio": 0.5, "quick_ratio": 0.3},
        "cash_runway": {"liquid_cash": 15000, "monthly_burn": 20000, "runway_months": 0.75},
    }
    summary_fragile = generate_deterministic_cfo_summary(fragile_evidence)
    assert "**Fragile**" in summary_fragile
    assert "Working Capital Deficit" in summary_fragile

    # 3. Early Stage Case (Pre-revenue with assets)
    early_evidence = {
        "profit_and_loss": {"revenue": 0.0, "net_profit": 0.0},
        "balance_sheet": {"current_assets": 100000, "current_liabilities": 20000, "total_assets": 200000, "equity": 180000},
        "working_capital_metrics": {"current_ratio": 5.0},
        "cash_runway": {"runway_months": 12.0},
    }
    summary_early = generate_deterministic_cfo_summary(early_evidence)
    assert "**Early Stage**" in summary_early


@pytest.mark.asyncio
async def test_generate_cfo_advisory_fallback_on_llm_exception(sample_evidence, sample_org_context):
    """Verify fallback to deterministic summary when orchestrator raises an exception."""
    mock_client = MagicMock()
    mock_client.generate_text = AsyncMock(side_effect=RuntimeError("Token Harbor gateway timeout"))

    with patch("app.ai_orchestrator.get_client", return_value=mock_client):
        result = await generate_cfo_advisory(
            user_query="Strategic CFO review",
            evidence=sample_evidence,
            org_context=sample_org_context,
        )

        assert "## 📊 Executive Financial Health Summary" in result
        assert "Apex Distribution Ltd" in result
        assert "1,000,000.00" in result


@pytest.mark.asyncio
async def test_generate_cfo_advisory_fallback_on_empty_llm_result(sample_evidence, sample_org_context):
    """Verify fallback to deterministic summary when orchestrator returns empty string."""
    mock_client = MagicMock()
    mock_client.generate_text = AsyncMock(return_value="   ")

    with patch("app.ai_orchestrator.get_client", return_value=mock_client):
        result = await generate_cfo_advisory(
            user_query="Strategic review",
            evidence=sample_evidence,
            org_context=sample_org_context,
        )

        assert "## 📊 Executive Financial Health Summary" in result
        assert "Apex Distribution Ltd" in result


# ===================================================================
# 4. Evidence Grounding Verification Tests
# ===================================================================

def test_extract_grounded_numbers(sample_evidence):
    """Verify that extract_grounded_numbers extracts all numeric values accurately."""
    nums = extract_grounded_numbers(sample_evidence)

    assert 1000000.0 in nums
    assert 600000.0 in nums
    assert 400000.0 in nums
    assert 1.8 in nums
    assert 40.0 in nums
    assert 14.29 in nums
    assert 35000.0 in nums


def test_verify_evidence_grounding_clean(sample_evidence, sample_org_context):
    """Verify that deterministic CFO summary is 100% grounded in evidence."""
    summary = generate_deterministic_cfo_summary(sample_evidence, sample_org_context)
    check = verify_evidence_grounding(summary, sample_evidence)

    assert check["is_grounded"] is True
    assert check["grounded_count"] > 10


def test_verify_evidence_grounding_detects_hallucinations(sample_evidence):
    """Verify that hallucinated numbers outside the evidence are detected."""
    hallucinated_text = (
        "Our company generated PKR 9,999,999.00 in revenue with an astounding 88.5% margin. "
        "We also secured PKR 4,444,444.00 in equity."
    )
    check = verify_evidence_grounding(hallucinated_text, sample_evidence)

    assert check["unmatched_count"] > 0
    # The unmatched numbers should include the fabricated amounts
    unmatched_joined = " ".join(check["unmatched_tokens"])
    assert "9,999,999.00" in unmatched_joined or "9999999" in unmatched_joined
    assert "88.5" in unmatched_joined


# ===================================================================
# 5. Edge Cases & Resilience Tests
# ===================================================================

def test_deterministic_summary_zero_values_and_empty_evidence():
    """Verify safe degradation with completely empty evidence payload without ZeroDivisionError."""
    summary = generate_deterministic_cfo_summary({}, {})

    assert "## 📊 Executive Financial Health Summary" in summary
    assert "0.00" in summary
    assert "```mermaid" in summary


def test_deterministic_summary_zero_liabilities():
    """Verify safe calculation when current liabilities is 0."""
    zero_liabilities_evidence = {
        "profit_and_loss": {"revenue": 100000, "net_profit": 20000},
        "balance_sheet": {"current_assets": 50000, "current_liabilities": 0.0, "total_assets": 100000, "equity": 100000},
    }
    summary = generate_deterministic_cfo_summary(zero_liabilities_evidence)
    assert "## 📊 Executive Financial Health Summary" in summary
    assert "50,000.00" in summary
