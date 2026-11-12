"""Fixed assets pipeline (capitalization, 3rd Schedule ITO 2001 depreciation, disposal)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.pipelines.common import (
    BasePipeline,
    ExecuteToolFn,
    TransactionPlan,
    check_section_73_cash_limit,
    default_txn_date,
    finalize_result,
    normalize_payment_method,
    parse_positive_amount,
)

FIXED_ASSET_INTENTS = frozenset(
    {
        "register_fixed_asset",
        "record_asset_depreciation",
        "dispose_fixed_asset",
    }
)

# 3rd Schedule ITO 2001 reducing-balance depreciation rates (%)
ITO_3RD_SCHEDULE_RATES: Dict[str, float] = {
    "building": 10.0,
    "buildings": 10.0,
    "furniture": 15.0,
    "fixtures": 15.0,
    "plant": 15.0,
    "machinery": 15.0,
    "equipment": 15.0,
    "vehicle": 20.0,
    "vehicles": 20.0,
    "computer": 30.0,
    "computers": 30.0,
    "laptop": 30.0,
    "server": 30.0,
    "workstation": 30.0,
    "printer": 30.0,
    "desktop": 30.0,
    "it_equipment": 30.0,
}


def default_ito_depreciation_rate(asset_name: str, category: str = "") -> float:
    """Return 3rd Schedule ITO 2001 reducing-balance rate for an asset category."""
    haystack = f"{category} {asset_name}".lower()
    for token, rate in ITO_3RD_SCHEDULE_RATES.items():
        if token in haystack:
            return rate
    return 15.0


def _build_register_asset_call(
    plan: TransactionPlan,
) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
    entities = plan.entities
    warnings: List[str] = []
    missing: List[str] = []

    nature = str(plan.nature or entities.get("transaction_nature") or "").upper()
    if nature != "FIXED_ASSET":
        missing.append("transaction_nature")

    name = str(entities.get("asset_name") or entities.get("item_description") or "").strip()
    amount = parse_positive_amount(entities.get("purchase_cost") or entities.get("amount"))
    txn_date = default_txn_date(entities)
    payment = normalize_payment_method(entities.get("payment_method"))

    if not name:
        missing.append("asset_name")
    if amount is None:
        missing.append("amount")
    if not payment:
        missing.append("payment_method")
    elif payment == "CREDIT" and not str(entities.get("supplier_name") or "").strip():
        missing.append("supplier_name")

    sec73 = check_section_73_cash_limit(amount, payment)
    if sec73:
        warnings.append(sec73)

    if missing:
        return [], missing, warnings

    params: Dict[str, Any] = {
        "name": name,
        "purchase_cost": amount,
        "transaction_date": txn_date,
        "payment_method": payment,
        "ito_rate_percent": default_ito_depreciation_rate(
            name, str(entities.get("category") or "")
        ),
    }
    for key, caster in (("useful_life_years", int), ("salvage_value", float)):
        val = entities.get(key)
        if val not in (None, "", [], {}):
            try:
                params[key] = caster(float(val))
            except (TypeError, ValueError):
                pass
    if entities.get("depreciation_method"):
        params["depreciation_method"] = str(entities["depreciation_method"]).strip()
    if entities.get("description"):
        params["description"] = str(entities["description"]).strip()
    if payment == "CREDIT":
        params["supplier_name"] = str(entities["supplier_name"]).strip()

    return [{"tool_name": "register_fixed_asset", "arguments": params}], [], warnings


class FixedAssetsPipeline(BasePipeline):
    section = "fixed_assets"

    async def handle(self, plan: TransactionPlan, org_id: str, **kwargs: Any) -> Dict[str, Any]:
        return await handle(plan, org_id, **kwargs)


async def handle(
    plan: TransactionPlan,
    org_id: str,
    *,
    execute_tool: Optional[ExecuteToolFn] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Handle fixed-asset registration, depreciation posting, and disposal."""
    intent = plan.intent.lower()
    entities = plan.entities
    tool_calls: List[Dict[str, Any]] = []
    missing: List[str] = []
    warnings: List[str] = []

    if intent == "register_fixed_asset":
        tool_calls, missing, warnings = _build_register_asset_call(plan)
    elif intent == "record_asset_depreciation":
        asset_ref = entities.get("asset_id") or entities.get("asset_name") or entities.get("item_description")
        if not asset_ref:
            missing.append("asset_name")
        else:
            args: Dict[str, Any] = {"depreciation_date": default_txn_date(entities)}
            if entities.get("asset_id"):
                args["asset_id"] = str(entities["asset_id"])
            else:
                args["asset_name"] = str(asset_ref).strip()
            if entities.get("amount") is not None:
                args["amount"] = parse_positive_amount(entities.get("amount"))
            tool_calls = [{"tool_name": "record_asset_depreciation", "arguments": args}]
    elif intent == "dispose_fixed_asset":
        asset_ref = entities.get("asset_id") or entities.get("asset_name") or entities.get("item_description")
        proceeds = parse_positive_amount(entities.get("proceeds_amount") or entities.get("amount"))
        if not asset_ref:
            missing.append("asset_name")
        if proceeds is None:
            missing.append("proceeds_amount")
        if not missing:
            args = {
                "disposal_date": default_txn_date(entities),
                "proceeds_amount": proceeds,
                "disposal_type": str(entities.get("disposal_type") or "SALE").upper(),
            }
            if entities.get("asset_id"):
                args["asset_id"] = str(entities["asset_id"])
            else:
                args["asset_name"] = str(asset_ref).strip()
            tool_calls = [{"tool_name": "dispose_fixed_asset", "arguments": args}]
    else:
        tool_calls = plan.normalized_tool_selection()

    return await finalize_result(
        section="fixed_assets",
        plan=plan,
        tool_calls=tool_calls,
        missing_fields=missing,
        warnings=warnings,
        execute_tool=execute_tool,
    )
