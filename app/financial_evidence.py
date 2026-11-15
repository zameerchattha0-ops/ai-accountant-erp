"""
Live Grounded Financial Evidence Retrieval Layer
================================================
Deterministic financial evidence retrieval, data structuring, and ratio
computation for analytical and advisory accounting queries.

Design principles:
- Grounded: Numbers are strictly retrieved and aggregated from authoritative
  ERP views/tables — never invented or estimated.
- Multi-Tenant: All repository calls are scoped to organization_id.
- Resilient: Every sub-component degrades gracefully on missing or empty data,
  returning deterministic zero defaults or empty lists without raising.
- Safe Math: Strict guards protect against division by zero across all ratios.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

import structlog

from app.pl_structure import (
    ADMINISTRATIVE,
    COST_OF_SALES,
    DISTRIBUTION,
    FINANCE_COSTS,
    OPERATING_EXPENSE_CATEGORIES,
    OPERATING_REVENUE,
    OTHER_INCOME,
    OTHER_OPERATING,
    SELLING_MARKETING,
    TAX_EXPENSE,
    build_statement,
    classify_rows,
)
from app.repositories import (
    bank_repository,
    invoice_repository,
    organization_repository,
    purchase_repository,
    report_repository,
)
from app.services import reporting_service

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Account Classification Helpers (Balance Sheet)
# ---------------------------------------------------------------------------

_CURRENT_ASSET_TERMS: Tuple[str, ...] = (
    "cash",
    "bank",
    "receivable",
    "debtor",
    "inventory",
    "stock",
    "prepaid",
    "prepayment",
    "advance",
    "deposit",
    "petty cash",
    "marketable",
    "short-term",
    "short term",
)

_NON_CURRENT_ASSET_TERMS: Tuple[str, ...] = (
    "fixed asset",
    "property",
    "plant",
    "machinery",
    "equipment",
    "furniture",
    "fixture",
    "vehicle",
    "building",
    "land",
    "depreciation",
    "accumulated depreciation",
    "amortization",
    "accumulated amortization",
    "intangible",
    "software",
    "goodwill",
    "patent",
    "trademark",
    "long-term asset",
    "long term asset",
    "non-current",
    "non current",
)

_LONG_TERM_LIABILITY_TERMS: Tuple[str, ...] = (
    "long-term",
    "long term",
    "non-current",
    "non current",
    "lease liability",
    "bonds payable",
    "debenture",
    "mortgage",
)

_CURRENT_LIABILITY_TERMS: Tuple[str, ...] = (
    "payable",
    "creditor",
    "short-term",
    "short term",
    "accrued",
    "accrual",
    "tax payable",
    "sales tax",
    "vat",
    "gst",
    "wht",
    "withholding",
    "salary payable",
    "salaries payable",
    "wages payable",
    "unearned",
    "overdraft",
)


def is_current_asset(row: Dict[str, Any]) -> bool:
    """Classify whether an ASSET account row represents a current asset."""
    parent = str(row.get("parent_account_name") or "").lower()
    if any(k in parent for k in ("non-current", "non current", "fixed asset", "property", "plant", "intangible")):
        return False
    if "current asset" in parent:
        return True

    name = str(row.get("account_name") or "").lower()
    if any(term in name for term in _NON_CURRENT_ASSET_TERMS):
        return False
    if any(term in name for term in _CURRENT_ASSET_TERMS):
        return True

    code = str(row.get("account_code") or "").strip()
    match = re.search(r"\d+", code)
    if match:
        val = int(match.group())
        if 1000 <= val < 1500:
            return True
        if 1500 <= val < 2000:
            return False

    return True


def is_long_term_liability(row: Dict[str, Any]) -> bool:
    """Classify whether a LIABILITY account row represents a long-term liability."""
    parent = str(row.get("parent_account_name") or "").lower()
    if any(k in parent for k in ("non-current", "non current", "long-term", "long term")):
        return True
    if any(k in parent for k in ("current liabilit", "short-term", "short term")):
        return False

    name = str(row.get("account_name") or "").lower()
    if any(term in name for term in ("short-term", "short term")):
        return False
    if any(term in name for term in _LONG_TERM_LIABILITY_TERMS):
        return True
    if any(term in name for term in _CURRENT_LIABILITY_TERMS):
        return False

    code = str(row.get("account_code") or "").strip()
    match = re.search(r"\d+", code)
    if match:
        val = int(match.group())
        if 2600 <= val < 3000:
            return True
        if 2000 <= val < 2600:
            return False

    return False


def _calculate_period_months(from_date: Optional[str], to_date: Optional[str]) -> float:
    """Calculate the number of months between dates, minimum 1.0."""
    if not from_date or not to_date:
        return 1.0
    try:
        d_from = date.fromisoformat(str(from_date))
        d_to = date.fromisoformat(str(to_date))
        days = (d_to - d_from).days
        if days <= 0:
            return 1.0
        return max(1.0, round(days / 30.4375, 2))
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# Individual Evidence Fetchers
# ---------------------------------------------------------------------------

async def _fetch_profit_and_loss(
    organization_id: uuid.UUID,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Concurrently safe retrieval of profit & loss data and statement."""
    try:
        pl_data = await reporting_service.get_profit_loss_statement(organization_id)
        if isinstance(pl_data, dict) and "statement" in pl_data:
            return pl_data.get("rows", []), pl_data["statement"]
    except Exception as exc:
        log.warning("financial_evidence.reporting_service_pl_failed", error=str(exc)[:200])

    try:
        rows = await report_repository.get_income_statement(organization_id)
        buckets = classify_rows(rows)
        stmt = build_statement(buckets)
        return rows or [], stmt
    except Exception as exc:
        log.warning("financial_evidence.repo_income_statement_failed", error=str(exc)[:200])
        return [], build_statement(classify_rows([]))


async def _fetch_balance_sheet(organization_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Safe retrieval of balance sheet rows."""
    try:
        rows = await report_repository.get_balance_sheet(organization_id)
        return rows or []
    except Exception as exc:
        log.warning("financial_evidence.get_balance_sheet_failed", error=str(exc)[:200])
        return []


async def _fetch_cash_flow(
    organization_id: uuid.UUID,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Safe retrieval of cash flow entries, filtered by date if provided."""
    try:
        rows = await report_repository.get_cash_flow(organization_id)
        if not rows:
            return []
        filtered = []
        for r in rows:
            tx_date = str(r.get("transaction_date") or "")
            if from_date and tx_date and tx_date < from_date:
                continue
            if to_date and tx_date and tx_date > to_date:
                continue
            filtered.append(r)
        return filtered
    except Exception as exc:
        log.warning("financial_evidence.get_cash_flow_failed", error=str(exc)[:200])
        return []


async def _fetch_bank_accounts(organization_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Safe retrieval of bank accounts."""
    try:
        rows = await organization_repository.get_bank_accounts(organization_id)
        if rows:
            return rows
    except Exception as exc:
        log.warning("financial_evidence.org_get_bank_accounts_failed", error=str(exc)[:200])

    try:
        rows = await bank_repository.list_bank_accounts(organization_id)
        return rows or []
    except Exception as exc:
        log.warning("financial_evidence.bank_list_bank_accounts_failed", error=str(exc)[:200])
        return []


async def _fetch_cash_accounts(organization_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Safe retrieval of cash accounts."""
    try:
        rows = await bank_repository.list_cash_accounts(organization_id)
        return rows or []
    except Exception as exc:
        log.warning("financial_evidence.bank_list_cash_accounts_failed", error=str(exc)[:200])
        return []


async def _fetch_customer_aging(organization_id: uuid.UUID) -> Tuple[float, float]:
    """Safe retrieval of total open and overdue receivables."""
    total_open = 0.0
    overdue = 0.0
    try:
        rows = await report_repository.get_customer_aging(organization_id)
        if rows:
            for r in rows:
                tot = float(r.get("total_outstanding") or 0.0)
                cur = float(r.get("bucket_current") or 0.0)
                total_open += tot
                od = (
                    float(r.get("bucket_1_30") or 0.0)
                    + float(r.get("bucket_31_60") or 0.0)
                    + float(r.get("bucket_61_90") or 0.0)
                    + float(r.get("bucket_90_plus") or 0.0)
                )
                if od > 0:
                    overdue += od
                elif tot > cur:
                    overdue += (tot - cur)
            return round(total_open, 2), round(overdue, 2)
    except Exception as exc:
        log.warning("financial_evidence.get_customer_aging_failed", error=str(exc)[:200])

    # Fallback to invoice_repository
    try:
        invoices = await invoice_repository.list_invoices(organization_id)
        for inv in invoices or []:
            st = str(inv.get("status") or "").upper()
            if st in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
                tot = float(inv.get("total") or 0.0)
                paid = float(inv.get("amount_paid") or 0.0)
                out = max(0.0, tot - paid)
                total_open += out
                if st == "OVERDUE":
                    overdue += out
        return round(total_open, 2), round(overdue, 2)
    except Exception as exc:
        log.warning("financial_evidence.invoice_repo_fallback_failed", error=str(exc)[:200])
        return 0.0, 0.0


async def _fetch_supplier_aging(organization_id: uuid.UUID) -> Tuple[float, float]:
    """Safe retrieval of total open and overdue payables."""
    total_open = 0.0
    overdue = 0.0
    try:
        rows = await report_repository.get_supplier_aging(organization_id)
        if rows:
            for r in rows:
                tot = float(r.get("total_outstanding") or 0.0)
                cur = float(r.get("bucket_current") or 0.0)
                total_open += tot
                od = (
                    float(r.get("bucket_1_30") or 0.0)
                    + float(r.get("bucket_31_60") or 0.0)
                    + float(r.get("bucket_61_90") or 0.0)
                    + float(r.get("bucket_90_plus") or 0.0)
                )
                if od > 0:
                    overdue += od
                elif tot > cur:
                    overdue += (tot - cur)
            return round(total_open, 2), round(overdue, 2)
    except Exception as exc:
        log.warning("financial_evidence.get_supplier_aging_failed", error=str(exc)[:200])

    # Fallback to purchase_repository
    try:
        bills = await purchase_repository.list_purchase_bills(organization_id)
        for b in bills or []:
            st = str(b.get("status") or "").upper()
            if st in ("OPEN", "PARTIALLY_PAID", "OVERDUE"):
                tot = float(b.get("total") or 0.0)
                paid = float(b.get("amount_paid") or 0.0)
                out = max(0.0, tot - paid)
                total_open += out
                if st == "OVERDUE":
                    overdue += out
        return round(total_open, 2), round(overdue, 2)
    except Exception as exc:
        log.warning("financial_evidence.purchase_repo_fallback_failed", error=str(exc)[:200])
        return 0.0, 0.0


# ---------------------------------------------------------------------------
# Main Evidence Gathering Function
# ---------------------------------------------------------------------------

async def gather_financial_evidence(
    organization_id: uuid.UUID,
    *,
    as_of_date: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Deterministically fetch and compute grounded financial evidence.

    Concurrently retrieves authoritative accounting records, calculates
    financial ratios, liquidity/runway metrics, and working capital status
    strictly without hallucinations.
    """
    effective_as_of = (
        as_of_date
        or to_date
        or datetime.now(timezone.utc).date().isoformat()
    )

    # 1. Concurrently fetch all foundational accounting views
    (
        (income_rows, pl_statement),
        bs_rows,
        cash_flow_rows,
        bank_accounts,
        cash_accounts,
        (total_open_receivables, overdue_receivables),
        (total_open_payables, overdue_payables),
    ) = await asyncio.gather(
        _fetch_profit_and_loss(organization_id),
        _fetch_balance_sheet(organization_id),
        _fetch_cash_flow(organization_id, from_date=from_date, to_date=to_date),
        _fetch_bank_accounts(organization_id),
        _fetch_cash_accounts(organization_id),
        _fetch_customer_aging(organization_id),
        _fetch_supplier_aging(organization_id),
    )

    # 2. Extract Profit & Loss Metrics
    revenue = float(pl_statement.get("operating_revenue") or 0.0)
    cost_of_sales = float(pl_statement.get("cost_of_sales") or 0.0)
    gross_profit = float(pl_statement.get("gross_profit") or 0.0)
    opex_obj = pl_statement.get("operating_expenses") or {}
    if isinstance(opex_obj, dict):
        opex_total = float(opex_obj.get("total") or 0.0)
        opex_categories = opex_obj.get("categories") or []
    else:
        opex_total = float(opex_obj or 0.0)
        opex_categories = []

    operating_profit = float(pl_statement.get("operating_profit") or 0.0)
    other_income = float(pl_statement.get("other_income") or 0.0)
    finance_costs = float(pl_statement.get("finance_costs") or 0.0)
    tax_expense = float(pl_statement.get("tax_expense") or 0.0)
    net_profit = float(pl_statement.get("net_profit") or 0.0)
    is_loss = bool(pl_statement.get("is_loss", net_profit < 0))

    profit_and_loss_data = {
        "revenue": round(revenue, 2),
        "cost_of_sales": round(cost_of_sales, 2),
        "gross_profit": round(gross_profit, 2),
        "operating_expenses": round(opex_total, 2),
        "operating_profit": round(operating_profit, 2),
        "other_income": round(other_income, 2),
        "finance_costs": round(finance_costs, 2),
        "tax_expense": round(tax_expense, 2),
        "net_profit": round(net_profit, 2),
        "is_loss": is_loss,
        "categories": opex_categories,
    }

    # 3. Extract Balance Sheet Metrics
    # Filter grouping accounts to avoid double-counting if subtree rollups exist
    leaf_rows = [r for r in bs_rows if not r.get("is_group", False)]
    if not leaf_rows and bs_rows:
        leaf_rows = bs_rows

    current_assets = 0.0
    non_current_assets = 0.0
    current_liabilities = 0.0
    long_term_liabilities = 0.0
    equity_recorded = 0.0

    cash_from_bs = 0.0
    receivables_from_bs = 0.0

    for row in leaf_rows:
        acc_type = str(row.get("account_type") or "").strip().upper()
        # net_amount in view is debit - credit
        if "net_amount" in row and row["net_amount"] is not None:
            net_amt = float(row["net_amount"])
        elif "balance" in row and row["balance"] is not None:
            net_amt = float(row["balance"])
        elif "amount" in row and row["amount"] is not None:
            # If amount is already provided flipped for liabilities/equity
            net_amt = float(row["amount"]) if acc_type == "ASSET" else -float(row["amount"])
        else:
            net_amt = 0.0

        name = str(row.get("account_name") or "").lower()

        if acc_type == "ASSET":
            if is_current_asset(row):
                current_assets += net_amt
                if any(k in name for k in ("cash", "bank", "petty cash")):
                    cash_from_bs += net_amt
                elif any(k in name for k in ("receivable", "debtor")):
                    receivables_from_bs += net_amt
            else:
                non_current_assets += net_amt

        elif acc_type == "LIABILITY":
            # Liabilities: credit is normal balance -> liability amount is -net_amt
            liab_val = -net_amt
            if is_long_term_liability(row):
                long_term_liabilities += liab_val
            else:
                current_liabilities += liab_val

        elif acc_type == "EQUITY":
            # Equity: credit is normal balance
            equity_recorded += (-net_amt)

    total_assets = round(current_assets + non_current_assets, 2)
    total_liabilities = round(current_liabilities + long_term_liabilities, 2)
    net_assets = round(total_assets - total_liabilities, 2)

    # If equity accounts were posted in DB, use recorded equity;
    # otherwise default to Net Assets (accounting equation A = L + E)
    if abs(equity_recorded) > 0.005:
        equity = round(equity_recorded, 2)
    else:
        equity = round(net_assets, 2)

    balance_sheet_data = {
        "current_assets": round(current_assets, 2),
        "non_current_assets": round(non_current_assets, 2),
        "total_assets": round(total_assets, 2),
        "current_liabilities": round(current_liabilities, 2),
        "long_term_liabilities": round(long_term_liabilities, 2),
        "total_liabilities": round(total_liabilities, 2),
        "equity": round(equity, 2),
        "net_assets": round(net_assets, 2),
    }

    # 4. Extract Cash Flow & Balances
    op_cf = 0.0
    inv_cf = 0.0
    fin_cf = 0.0
    for r in cash_flow_rows:
        cat = str(r.get("cash_flow_category") or "").upper()
        amt = float(r.get("net_amount") or 0.0)
        if cat == "OPERATING":
            op_cf += amt
        elif cat == "INVESTING":
            inv_cf += amt
        elif cat == "FINANCING":
            fin_cf += amt

    net_cash_change = round(op_cf + inv_cf + fin_cf, 2)

    bank_balances = [
        {
            "id": str(b.get("id") or ""),
            "account_name": str(b.get("account_name") or b.get("name") or ""),
            "bank_name": str(b.get("bank_name") or ""),
            "balance": round(float(b.get("current_balance") or b.get("balance") or 0.0), 2),
            "currency_code": str(b.get("currency_code") or "PKR"),
        }
        for b in bank_accounts
    ]

    cash_balances = [
        {
            "id": str(c.get("id") or ""),
            "name": str(c.get("name") or ""),
            "balance": round(float(c.get("current_balance") or c.get("balance") or 0.0), 2),
            "currency_code": str(c.get("currency_code") or "PKR"),
        }
        for c in cash_accounts
    ]

    liquid_from_accounts = sum(b["balance"] for b in bank_balances) + sum(c["balance"] for c in cash_balances)
    # If account registers are empty, use cash/bank ledger balance from balance sheet
    total_liquid_cash = round(
        liquid_from_accounts if liquid_from_accounts > 0 or (bank_balances or cash_balances) else max(0.0, cash_from_bs),
        2,
    )

    cash_flow_data = {
        "operating_cash_flows": round(op_cf, 2),
        "investing_cash_flows": round(inv_cf, 2),
        "financing_cash_flows": round(fin_cf, 2),
        "net_cash_change": round(net_cash_change, 2),
        "bank_balances": bank_balances,
        "cash_balances": cash_balances,
        "total_liquid_cash": round(total_liquid_cash, 2),
        "bank_and_cash_balances": round(total_liquid_cash, 2),
    }

    # 5. Compute Working Capital Metrics
    working_capital = round(current_assets - current_liabilities, 2)
    if current_liabilities > 0:
        current_ratio = round(current_assets / current_liabilities, 2)
    else:
        current_ratio = 0.0

    # Quick Ratio: (Cash + Trade Receivables) / Current Liabilities
    # Trade receivables from aging summary, or from balance sheet receivable accounts
    trade_receivables = total_open_receivables if total_open_receivables > 0 else max(0.0, receivables_from_bs)
    quick_assets = total_liquid_cash + trade_receivables
    if current_liabilities > 0:
        quick_ratio = round(quick_assets / current_liabilities, 2)
    else:
        quick_ratio = 0.0

    if current_liabilities > 0:
        cr_ratio = current_assets / current_liabilities
        if cr_ratio >= 1.5:
            wc_status = "Adequate"
        elif cr_ratio >= 1.0:
            wc_status = "Tight"
        else:
            wc_status = "Deficit"
    else:
        wc_status = "Adequate" if current_assets >= 0 else "Deficit"

    working_capital_metrics = {
        "working_capital": round(working_capital, 2),
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "status": wc_status,
    }

    # 6. Compute Financial Ratios (Division by Zero Safe)
    gross_margin_pct = round((gross_profit / revenue) * 100, 2) if revenue != 0 else 0.0
    net_margin_pct = round((net_profit / revenue) * 100, 2) if revenue != 0 else 0.0
    op_margin_pct = round((operating_profit / revenue) * 100, 2) if revenue != 0 else 0.0
    roa_pct = round((net_profit / total_assets) * 100, 2) if total_assets != 0 else 0.0
    roe_pct = round((net_profit / equity) * 100, 2) if equity != 0 else 0.0
    debt_to_equity = round(total_liabilities / equity, 2) if equity != 0 else 0.0

    financial_ratios = {
        "gross_profit_margin": gross_margin_pct,
        "net_profit_margin": net_margin_pct,
        "operating_margin": op_margin_pct,
        "return_on_assets": roa_pct,
        "return_on_equity": roe_pct,
        "debt_to_equity_ratio": debt_to_equity,
        "debt_to_equity": debt_to_equity,
    }

    # 7. Compute Aging Summary
    aging_summary = {
        "total_open_receivables": round(total_open_receivables, 2),
        "overdue_receivables": round(overdue_receivables, 2),
        "total_open_payables": round(total_open_payables, 2),
        "overdue_payables": round(overdue_payables, 2),
    }

    # 8. Compute Expense Breakdown (Top Expenses by Value & % of Operating Expenses)
    expense_items: List[Dict[str, Any]] = []
    # Collect from category rows first
    for cat in opex_categories:
        for r in cat.get("rows", []):
            amt = float(r.get("amount") or 0.0)
            if amt > 0:
                expense_items.append({
                    "account_code": str(r.get("code") or r.get("account_code") or ""),
                    "account_name": str(r.get("name") or r.get("account_name") or ""),
                    "amount": round(amt, 2),
                })

    # If categories were empty but raw income rows exist, collect operating expenses
    if not expense_items and income_rows:
        for r in income_rows:
            if str(r.get("account_type") or "").upper() == "EXPENSE":
                net = float(r.get("net_amount") or 0.0)
                name = str(r.get("account_name") or "").lower()
                # Exclude COGS, finance costs, and tax
                if net > 0 and not any(k in name for k in ("cost of sales", "cogs", "interest", "finance", "tax")):
                    expense_items.append({
                        "account_code": str(r.get("account_code") or ""),
                        "account_name": str(r.get("account_name") or ""),
                        "amount": round(net, 2),
                    })

    expense_items.sort(key=lambda x: x["amount"], reverse=True)
    expense_breakdown: List[Dict[str, Any]] = []
    for item in expense_items[:10]:
        pct = round((item["amount"] / opex_total) * 100, 2) if opex_total > 0 else 0.0
        expense_breakdown.append({
            "account_code": item["account_code"],
            "account_name": item["account_name"],
            "amount": item["amount"],
            "percentage": pct,
        })

    # 9. Compute Cash Runway
    period_months = _calculate_period_months(from_date, to_date)
    monthly_burn_rate = round(opex_total / period_months, 2) if opex_total > 0 else 0.0
    if monthly_burn_rate > 0:
        runway_months = round(total_liquid_cash / monthly_burn_rate, 2)
    elif total_liquid_cash == 0:
        runway_months = 0.0
    else:
        # Liquid cash > 0 with 0 burn rate represents indefinite runway (no burn)
        runway_months = None

    cash_runway = {
        "total_liquid_cash": round(total_liquid_cash, 2),
        "monthly_burn_rate": monthly_burn_rate,
        "average_monthly_burn_rate": monthly_burn_rate,
        "estimated_cash_runway_months": runway_months,
        "runway_months": runway_months,
    }

    # Assemble and return comprehensive evidence payload
    return {
        "organization_id": str(organization_id),
        "as_of_date": effective_as_of,
        "from_date": from_date,
        "to_date": to_date,
        "profit_and_loss": profit_and_loss_data,
        "balance_sheet": balance_sheet_data,
        "cash_flow": cash_flow_data,
        "working_capital_metrics": working_capital_metrics,
        "financial_ratios": financial_ratios,
        "aging_summary": aging_summary,
        "expense_breakdown": expense_breakdown,
        "cash_runway": cash_runway,
    }
