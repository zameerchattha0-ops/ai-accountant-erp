"""Purchases & procurement pipeline (RFQ/PO, purchase bills, supplier payments, returns)."""

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
    reconcile_line_items,
)

PURCHASE_INTENTS = frozenset(
    {
        "create_purchase_order",
        "update_purchase_order_status",
        "create_purchase_bill",
        "record_credit_purchase",
        "record_cash_purchase",
        "record_purchase",
        "record_supplier_payment",
        "record_payment",
        "create_purchase_return",
    }
)


def _extract_supplier(entities: Dict[str, Any]) -> str:
    return str(
        entities.get("supplier_name")
        or entities.get("party_name")
        or entities.get("counterparty")
        or entities.get("party")
        or ""
    ).strip()


def _build_purchase_order_call(plan: TransactionPlan) -> tuple[List[Dict[str, Any]], List[str]]:
    entities = plan.entities
    supplier_name = _extract_supplier(entities)
    product_name = str(
        entities.get("product_name")
        or entities.get("item_name")
        or entities.get("item_description")
        or entities.get("description")
        or ""
    ).strip()
    missing: List[str] = []
    if not supplier_name:
        missing.append("supplier_name")
    if not product_name and not entities.get("items") and not entities.get("line_items"):
        missing.append("item_description")
    if missing:
        return [], missing

    args: Dict[str, Any] = {
        "supplier_name": supplier_name,
        "status": str(entities.get("order_status") or entities.get("status") or "RFQ").upper(),
        "order_date": default_txn_date(entities),
    }
    if product_name:
        qty_raw = entities.get("quantity") or 1
        try:
            qty = float(qty_raw)
        except (TypeError, ValueError):
            qty = 1.0
        args["product_name"] = product_name
        args["quantity"] = qty if qty > 0 else 1.0
        price = parse_positive_amount(
            entities.get("unit_price") or entities.get("price") or entities.get("amount")
        )
        if price is not None and price > 0:
            args["unit_price"] = price
    nature = str(plan.nature or entities.get("transaction_nature") or "").upper()
    if nature:
        args["transaction_nature"] = nature
    return [{"tool_name": "create_purchase_order", "arguments": args}], []


def _build_purchase_bill_call(plan: TransactionPlan) -> tuple[List[Dict[str, Any]], List[str]]:
    entities = plan.entities
    supplier_id = entities.get("supplier_id")
    supplier_name = _extract_supplier(entities)
    amount = parse_positive_amount(entities.get("amount") or entities.get("total"))
    missing: List[str] = []
    if not supplier_id and not supplier_name:
        missing.append("supplier_name")
    if amount is None:
        missing.append("amount")
    if missing:
        return [], missing

    txn_date = default_txn_date(entities)
    params: Dict[str, Any] = {
        "bill_date": txn_date,
        "subtotal": amount,
        "total": amount,
        "notes": str(entities.get("item_description") or "Credit purchase recorded by the agent"),
    }
    if supplier_id:
        params["supplier_id"] = str(supplier_id)
    else:
        params["supplier_name"] = supplier_name

    items = reconcile_line_items(
        entities,
        default_description="Purchase item",
        total_amount=amount,
    )
    if items is None and entities.get("line_items"):
        return [], ["line_items"]
    if items:
        params["items"] = items
        derived = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)
        params["subtotal"] = derived
        params["total"] = derived

    if entities.get("account_id"):
        params["account_id"] = str(entities["account_id"])
    return [{"tool_name": "create_purchase_bill", "arguments": params}], []


def _build_supplier_payment_call(plan: TransactionPlan) -> tuple[List[Dict[str, Any]], List[str]]:
    entities = plan.entities
    supplier_id = entities.get("supplier_id")
    supplier_name = _extract_supplier(entities)
    amount = parse_positive_amount(entities.get("amount"))
    payment_method = normalize_payment_method(entities.get("payment_method"))
    missing: List[str] = []
    if not supplier_id and not supplier_name:
        missing.append("supplier_name")
    if amount is None:
        missing.append("amount")
    if not payment_method:
        missing.append("payment_method")
    if missing:
        return [], missing

    args: Dict[str, Any] = {
        "amount": amount,
        "payment_date": default_txn_date(entities),
        "payment_method": payment_method,
    }
    if supplier_id:
        args["supplier_id"] = str(supplier_id)
    else:
        args["supplier_name"] = supplier_name
    for key in ("bill_id", "bill_number", "wht_rate_percent", "wht_amount", "reference"):
        if entities.get(key) is not None:
            args[key] = entities[key]
    return [{"tool_name": "record_supplier_payment", "arguments": args}], []


class PurchasesPipeline(BasePipeline):
    section = "purchases"

    async def handle(self, plan: TransactionPlan, org_id: str, **kwargs: Any) -> Dict[str, Any]:
        return await handle(plan, org_id, **kwargs)


async def handle(
    plan: TransactionPlan,
    org_id: str,
    *,
    execute_tool: Optional[ExecuteToolFn] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Handle purchase, procurement RFQ/PO, vendor bill, and supplier payment flows."""
    entities = plan.entities
    intent = plan.intent.lower()
    amount = parse_positive_amount(entities.get("amount") or entities.get("total"))
    payment_method = normalize_payment_method(entities.get("payment_method"))
    warnings: List[str] = []

    sec73 = check_section_73_cash_limit(amount, payment_method)
    if sec73:
        warnings.append(sec73)

    advisory: Optional[str] = None
    if plan.user_intent_type == "advisory":
        advisory = (
            "CFO Procurement Advisory: Compare formal quotations from multiple vendors before "
            "issuing an RFQ/PO. Route payments exceeding PKR 50,000 through banking channels "
            "(Section 73) and apply Section 153 WHT on vendor settlement."
        )
        if not plan.tool_selection and intent not in ("create_purchase_order",):
            return await finalize_result(
                section="purchases",
                plan=plan,
                tool_calls=[],
                warnings=warnings,
                advisory=advisory,
                execute_tool=execute_tool,
            )

    tool_calls: List[Dict[str, Any]] = []
    missing: List[str] = []

    if intent == "create_purchase_order":
        tool_calls, missing = _build_purchase_order_call(plan)
    elif intent in ("create_purchase_bill", "record_credit_purchase"):
        tool_calls, missing = _build_purchase_bill_call(plan)
    elif intent in ("record_supplier_payment", "record_payment"):
        tool_calls, missing = _build_supplier_payment_call(plan)
    elif intent == "create_purchase_return":
        supplier_name = _extract_supplier(entities)
        if not supplier_name and not entities.get("supplier_id"):
            missing.append("supplier_name")
        if amount is None:
            missing.append("amount")
        if not entities.get("reason"):
            missing.append("reason")
        if not missing:
            args: Dict[str, Any] = {
                "amount": amount,
                "return_date": default_txn_date(entities),
                "reason": str(entities["reason"]),
            }
            if entities.get("supplier_id"):
                args["supplier_id"] = str(entities["supplier_id"])
            else:
                args["supplier_name"] = supplier_name
            if entities.get("bill_number") or entities.get("bill_id"):
                args["bill_number"] = entities.get("bill_number") or entities.get("bill_id")
            tool_calls = [{"tool_name": "create_purchase_return", "arguments": args}]
    else:
        tool_calls = plan.normalized_tool_selection()

    return await finalize_result(
        section="purchases",
        plan=plan,
        tool_calls=tool_calls,
        missing_fields=missing,
        warnings=warnings,
        advisory=advisory,
        execute_tool=execute_tool,
    )
