"""Domain-specific execution pipelines for unified single-call transaction plans."""

from __future__ import annotations

from typing import Any, Dict

from app.pipelines import expenses, fixed_assets, purchases, sales
from app.pipelines.common import BasePipeline, SelectedTool, TransactionPlan

_SECTION_HANDLERS = {
    "purchases": purchases.handle,
    "procurement": purchases.handle,
    "payables": purchases.handle,
    "sales": sales.handle,
    "revenue": sales.handle,
    "receivables": sales.handle,
    "expenses": expenses.handle,
    "fixed_assets": fixed_assets.handle,
    "assets": fixed_assets.handle,
}


def resolve_pipeline_section(plan: TransactionPlan) -> str:
    """Resolve the target pipeline section from explicit section, intent, or nature."""
    if plan.section and plan.section in _SECTION_HANDLERS:
        return plan.section
    intent = plan.intent.lower()
    if intent in purchases.PURCHASE_INTENTS:
        return "purchases"
    if intent in sales.SALES_INTENTS:
        return "sales"
    if intent in expenses.EXPENSE_INTENTS:
        return "expenses"
    if intent in fixed_assets.FIXED_ASSET_INTENTS or plan.nature == "FIXED_ASSET":
        return "fixed_assets"
    if plan.nature == "OPERATING_EXPENSE":
        return "expenses"
    if plan.nature in ("REVENUE", "GOODS", "SERVICE"):
        return "sales"
    return plan.section or "expenses"


async def dispatch_plan(plan: TransactionPlan, org_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Dispatch a unified TransactionPlan to its domain-specific pipeline handler."""
    section = resolve_pipeline_section(plan)
    handler = _SECTION_HANDLERS.get(section, expenses.handle)
    return await handler(plan, org_id, **kwargs)


__all__ = [
    "BasePipeline",
    "SelectedTool",
    "TransactionPlan",
    "dispatch_plan",
    "expenses",
    "fixed_assets",
    "purchases",
    "resolve_pipeline_section",
    "sales",
]
