"""Hierarchical P&L classification — pure functions, no database, no I/O.

The financial-statement engine is structured around the ACCOUNTING HIERARCHY,
never around hard-coded account ids: an account is classified by the SECTION
HEAD it hangs under (its parent chain), so two organisations that seed the
same statement structure with different codes classify identically, and a
chart that grows a new ``Selling & Marketing`` subtree needs no code change.

Sections (the multi-step statement the books require):

    Operating Revenue
        ↓
    Cost of Sales
        ↓
    GROSS PROFIT
        ↓
    Operating Expenses      (Administrative / Selling & Marketing /
                             Distribution / Other Operating Expenses)
        ↓
    OPERATING PROFIT
        ↓
    Other Income            ← deliberately OUTSIDE operating revenue
    Finance Costs           ← Interest Expense etc.
    Tax Expense             ← Income Tax Expense etc.
        ↓
    NET PROFIT

SIGN CONVENTION (inherited from ``v_income_statement``): ``net_amount`` is
``debit - credit``.  Revenue is credit-normal, so it arrives NEGATIVE and is
flipped for display; expenses arrive POSITIVE and are shown as deductions.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Section keys — the only vocabulary the statement engine speaks.
# ---------------------------------------------------------------------------
OPERATING_REVENUE = "operating_revenue"
OTHER_INCOME = "other_income"
COST_OF_SALES = "cost_of_sales"
ADMINISTRATIVE = "administrative"
SELLING_MARKETING = "selling_marketing"
DISTRIBUTION = "distribution"
OTHER_OPERATING = "other_operating"
FINANCE_COSTS = "finance_costs"
TAX_EXPENSE = "tax_expense"

# The four operating-expense categories the statement presents separately.
OPERATING_EXPENSE_CATEGORIES: Tuple[str, ...] = (
    ADMINISTRATIVE,
    SELLING_MARKETING,
    DISTRIBUTION,
    OTHER_OPERATING,
)

#: Human labels, in statement order, for the UI and the agent narrative.
SECTION_LABELS: Dict[str, str] = {
    OPERATING_REVENUE: "Operating Revenue",
    OTHER_INCOME: "Other Income",
    COST_OF_SALES: "Cost of Sales",
    ADMINISTRATIVE: "Administrative / General",
    SELLING_MARKETING: "Selling & Marketing",
    DISTRIBUTION: "Distribution",
    OTHER_OPERATING: "Other Operating Expenses",
    FINANCE_COSTS: "Finance Costs",
    TAX_EXPENSE: "Tax Expense",
}


# ---------------------------------------------------------------------------
# Head-name → section matching.
#
# Matching runs against the SECTION HEAD of the account, not the leaf name,
# and is anchored on phrases so "Cost of Sales - Services" cannot be mistaken
# for a generic operating expense.  Phrases are lowercase and
# hyphen/ampersand-insensitive (see ``_normalise``).
# ---------------------------------------------------------------------------
_COST_OF_SALES_PHRASES: Tuple[str, ...] = (
    "cost of sales",
    "cost of goods sold",
    "cogs",
)
_FINANCE_PHRASES: Tuple[str, ...] = (
    "finance cost",
    "finance charges",
    "interest expense",
    "bank charges",
    "foreign exchange loss",
)
_TAX_PHRASES: Tuple[str, ...] = (
    "tax expense",
    "income tax",
    "corporate tax",
    "tax provision",
)
_SELLING_PHRASES: Tuple[str, ...] = (
    "selling and marketing",
    "marketing",
    "advertising",
    "sales and marketing",
)
_DISTRIBUTION_PHRASES: Tuple[str, ...] = (
    "distribution",
    "logistics",
    "freight out",
    "shipping and handling",
)
_ADMIN_PHRASES: Tuple[str, ...] = (
    "administrative",
    "administration",
    "office and administration",
    "office expenses",
    "payroll and staff",
    "premises",
    "communication",
    "technology and software",
    "depreciation and amortisation",
    "depreciation and amortization",
)
_OTHER_INCOME_PHRASES: Tuple[str, ...] = (
    "other income",
    "non operating income",
    "other revenue",
)

# Checked in this order — earlier entries win.
_ALL_EXPENSE_SECTIONS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (_COST_OF_SALES_PHRASES, COST_OF_SALES),
    (_FINANCE_PHRASES, FINANCE_COSTS),
    (_TAX_PHRASES, TAX_EXPENSE),
    (_SELLING_PHRASES, SELLING_MARKETING),
    (_DISTRIBUTION_PHRASES, DISTRIBUTION),
    (_ADMIN_PHRASES, ADMINISTRATIVE),
)


def _normalise(text: Any) -> str:
    """Lowercase, hyphen/ampersand-insensitive form used for all matching."""
    if text is None:
        return ""
    return str(text).lower().replace("&", "and").replace("-", " ").replace("_", " ")


def classify_expense_head(head_name: Any) -> str:
    """Map an expense section-head name to its statement section.

    Order is deliberate: cost of sales wins over everything, then finance and
    tax (which are NOT operating expenses and must never land in the
    administrative bucket), then the operating categories.  Anything unmatched
    — a genuinely custom chart — falls to ``OTHER_OPERATING`` so it still sits
    ABOVE operating profit, never below it.
    """
    head = _normalise(head_name)
    if not head:
        return OTHER_OPERATING
    for phrases, section in _ALL_EXPENSE_SECTIONS:
        for phrase in phrases:
            if phrase in head:
                return section
    return OTHER_OPERATING


def classify_revenue_head(head_name: Any) -> str:
    """Map a revenue section-head name to Operating Revenue or Other Income.

    Other Income is kept OUTSIDE operating revenue: it does not belong in
    gross profit or operating profit.
    """
    head = _normalise(head_name)
    if not head:
        return OPERATING_REVENUE
    for phrase in _OTHER_INCOME_PHRASES:
        if phrase in head:
            return OTHER_INCOME
    return OPERATING_REVENUE


def classify_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Bucket ``v_income_statement`` rows into statement sections.

    GROUP accounts are SKIPPED: their ``subtree_balance`` is the sum of their
    children, so counting both a parent and its children double-counts.  The
    leaves carry the postings.

    Each returned row keeps ``code``/``name``/``amount`` where ``amount`` is
    already sign-normalised for presentation (revenue positive, expenses
    positive) — the statement never shows a negative revenue figure.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {key: [] for key in SECTION_LABELS}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if row.get("is_group"):
            continue
        net = _to_float(row.get("net_amount"))
        if abs(net) <= 0.005:  # sub-cent rounding dust
            continue
        atype = str(row.get("account_type") or "").upper()
        section = classify_account(atype, _head_name_for(row))
        if section is None:
            continue
        # Revenue is credit-normal (net_amount negative) → flip for display.
        amount = -net if atype == "REVENUE" else net
        buckets[section].append({
            "code": str(row.get("account_code") or ""),
            "name": str(row.get("account_name") or ""),
            "account_type": atype,
            "amount": round(amount, 2),
        })
    for bucket in buckets.values():
        bucket.sort(key=lambda r: (r["code"], r["name"]))
    return buckets


def build_statement(buckets: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Turn classified buckets into the multi-step statement.

    Every subtotal is computed HERE, from the same buckets the rows come from,
    so a presentation layer can never show a total that disagrees with the
    lines above it.
    """

    def _total(section: str) -> float:
        return round(sum(r["amount"] for r in buckets.get(section, [])), 2)

    def _group(category: str) -> Dict[str, Any]:
        rows = buckets.get(category, [])
        return {"label": SECTION_LABELS[category], "rows": rows, "total": _total(category)}

    operating_revenue = _total(OPERATING_REVENUE)
    cost_of_sales = _total(COST_OF_SALES)
    gross_profit = round(operating_revenue - cost_of_sales, 2)

    opex_total = round(sum(_total(c) for c in OPERATING_EXPENSE_CATEGORIES), 2)
    operating_profit = round(gross_profit - opex_total, 2)

    other_income = _total(OTHER_INCOME)
    finance_costs = _total(FINANCE_COSTS)
    tax_expense = _total(TAX_EXPENSE)
    net_profit = round(
        operating_profit + other_income - finance_costs - tax_expense, 2
    )

    return {
        "operating_revenue": operating_revenue,
        "cost_of_sales": cost_of_sales,
        "gross_profit": gross_profit,
        "operating_expenses": {
            "categories": [_group(c) for c in OPERATING_EXPENSE_CATEGORIES],
            "total": opex_total,
        },
        "operating_profit": operating_profit,
        "other_income": other_income,
        "finance_costs": finance_costs,
        "tax_expense": tax_expense,
        "net_profit": net_profit,
        "is_loss": net_profit < 0,
        "sections": {
            OPERATING_REVENUE: _group(OPERATING_REVENUE),
            OTHER_INCOME: _group(OTHER_INCOME),
            COST_OF_SALES: _group(COST_OF_SALES),
            FINANCE_COSTS: _group(FINANCE_COSTS),
            TAX_EXPENSE: _group(TAX_EXPENSE),
        },
    }


def classify_account(
    account_type: Any,
    head_name: Any = "",
    leaf_name: Any = "",
) -> Optional[str]:
    """Classify an account from its type and (head, leaf) names.

    The caller passes the account's SECTION HEAD when one exists and the
    leaf's own name as ``leaf_name``.

    ``leaf_name`` is a FALLBACK only, used when the account is top-level and
    therefore its own head — never when a head exists, because a leaf named
    "Advertising" under "Office & Administration" is administrative, not
    selling, and the head is the authority.
    """
    atype = str(account_type or "").upper()
    if atype == "REVENUE":
        return classify_revenue_head(head_name or leaf_name)
    if atype == "EXPENSE":
        return classify_expense_head(head_name or leaf_name)
    return None


def _head_name_for(row: Dict[str, Any]) -> str:
    """The section-head name of a ``v_income_statement`` row.

    A GROUP account (``is_group``) is its own head.  A leaf reports
    ``parent_account_name`` when it has one — that IS its head — and otherwise
    falls back to its own name.  This is deliberately not a recursive walk:
    the view already exposes the immediate parent, and head → leaf is the
    shape the seeded charts use.  ``account_head`` in account_resolution walks
    the full chain when a deeper chart needs it.
    """
    if row.get("is_group"):
        return str(row.get("account_name") or "")
    parent = str(row.get("parent_account_name") or "")
    if parent:
        return parent
    return str(row.get("account_name") or "")


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
