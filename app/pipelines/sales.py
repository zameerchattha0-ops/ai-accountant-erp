"""Sales & receivables pipeline (invoices, cash sales, quotations, receipts, credit notes)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.pipelines.common import (
    BasePipeline,
    ExecuteToolFn,
    TransactionPlan,
    default_txn_date,
    finalize_result,
    normalize_payment_method,
    parse_positive_amount,
    reconcile_line_items,
)

SALES_INTENTS = frozenset(
    {
        "create_invoice",
        "record_credit_sale",
        "record_cash_sale",
        "record_sale",
        "record_receipt",
        "record_customer_receipt",
        "create_quotation",
        "create_credit_note",
    }
)

_TAX_FIELDS = ("tax_pricing_mode", "tax_rate_percent", "tax_amount")


def _extract_customer(entities: Dict[str, Any]) -> str:
    return str(
        entities.get("customer_name")
        or entities.get("party_name")
        or entities.get("counterparty")
        or entities.get("party")
        or ""
    ).strip()


def _attach_tax_fields(params: Dict[str, Any], entities: Dict[str, Any]) -> None:
    for key in _TAX_FIELDS:
        if entities.get(key) is not None:
            params[key] = entities[key]


def _build_invoice_call(plan: TransactionPlan) -> tuple[List[Dict[str, Any]], List[str]]:
    entities = plan.entities
    amount = parse_positive_amount(entities.get("amount") or entities.get("total"))
    customer_id = entities.get("customer_id")
    customer_name = _extract_customer(entities)
    nature = str(plan.nature or entities.get("transaction_nature") or "").upper()

    missing: List[str] = []
    if amount is None:
        missing.append("amount")
    if not customer_id and not customer_name:
        missing.append("customer_name")
    if nature and nature not in ("GOODS", "SERVICE", "INVENTORY"):
        return [], ["transaction_nature"]
    if not nature:
        missing.append("transaction_nature")
    if missing:
        return [], missing

    items = reconcile_line_items(
        entities,
        default_description="Service" if nature == "SERVICE" else "Goods",
        total_amount=amount,
    )
    if items is None:
        return [], ["line_items"]

    params: Dict[str, Any] = {
        "invoice_date": default_txn_date(entities),
        "items": items,
    }
    if customer_id:
        params["customer_id"] = str(customer_id)
    else:
        params["customer_name"] = customer_name
    _attach_tax_fields(params, entities)
    return [{"tool_name": "create_invoice", "arguments": params}], []


def _build_cash_sale_call(plan: TransactionPlan) -> tuple[List[Dict[str, Any]], List[str]]:
    entities = plan.entities
    amount = parse_positive_amount(entities.get("amount") or entities.get("total"))
    nature = str(plan.nature or entities.get("transaction_nature") or "").upper()

    missing: List[str] = []
    if amount is None:
        missing.append("amount")
    if not nature or nature not in ("GOODS", "SERVICE", "INVENTORY"):
        missing.append("transaction_nature")
    if missing:
        return [], missing

    items = reconcile_line_items(
        entities,
        default_description="Goods" if nature in ("GOODS", "INVENTORY") else "Service",
        total_amount=amount,
    )
    if items is None:
        return [], ["line_items"]

    params: Dict[str, Any] = {
        "amount": amount,
        "transaction_date": default_txn_date(entities),
        "description": str(
            entities.get("item_description") or entities.get("description") or "Cash sale"
        ),
        "items": items,
    }
    if entities.get("revenue_account_id"):
        params["revenue_account_id"] = str(entities["revenue_account_id"])
    _attach_tax_fields(params, entities)
    return [{"tool_name": "record_cash_sale", "arguments": params}], []


def _build_receipt_call(plan: TransactionPlan) -> tuple[List[Dict[str, Any]], List[str]]:
    entities = plan.entities
    amount = parse_positive_amount(entities.get("amount"))
    customer_id = entities.get("customer_id")
    customer_name = _extract_customer(entities)
    payment_method = normalize_payment_method(entities.get("payment_method")) or "BANK"

    missing: List[str] = []
    if amount is None:
        missing.append("amount")
    if not customer_id and not customer_name:
        missing.append("customer_name")
    if missing:
        return [], missing

    args: Dict[str, Any] = {
        "amount": amount,
        "receipt_date": default_txn_date(entities),
        "payment_method": payment_method,
    }
    if customer_id:
        args["customer_id"] = str(customer_id)
    else:
        args["customer_name"] = customer_name
    for key in ("invoice_id", "invoice_number", "reference"):
        if entities.get(key) is not None:
            args[key] = entities[key]
    return [{"tool_name": "record_customer_receipt", "arguments": args}], []


class SalesPipeline(BasePipeline):
    section = "sales"

    async def handle(self, plan: TransactionPlan, org_id: str, **kwargs: Any) -> Dict[str, Any]:
        return await handle(plan, org_id, **kwargs)


async def handle(
    plan: TransactionPlan,
    org_id: str,
    *,
    execute_tool: Optional[ExecuteToolFn] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Handle sales invoices, cash sales, customer receipts, quotations, and credit notes."""
    intent = plan.intent.lower()
    entities = plan.entities
    tool_calls: List[Dict[str, Any]] = []
    missing: List[str] = []

    if intent in ("create_invoice", "record_credit_sale"):
        tool_calls, missing = _build_invoice_call(plan)
    elif intent in ("record_cash_sale", "record_sale"):
        tool_calls, missing = _build_cash_sale_call(plan)
    elif intent in ("record_receipt", "record_customer_receipt"):
        tool_calls, missing = _build_receipt_call(plan)
    elif intent == "create_credit_note":
        amount = parse_positive_amount(entities.get("amount"))
        customer_name = _extract_customer(entities)
        if amount is None:
            missing.append("amount")
        if not customer_name and not entities.get("customer_id"):
            missing.append("customer_name")
        if not missing:
            args: Dict[str, Any] = {
                "amount": amount,
                "credit_note_date": default_txn_date(entities),
                "reason": str(entities.get("reason") or "Customer credit note"),
            }
            if entities.get("customer_id"):
                args["customer_id"] = str(entities["customer_id"])
            else:
                args["customer_name"] = customer_name
            if entities.get("invoice_number") or entities.get("invoice_id"):
                args["invoice_number"] = entities.get("invoice_number") or entities.get("invoice_id")
            tool_calls = [{"tool_name": "create_credit_note", "arguments": args}]
    elif intent == "create_quotation":
        customer_name = _extract_customer(entities)
        if not customer_name and not entities.get("customer_id"):
            missing.append("customer_name")
        else:
            args = {
                "customer_name": customer_name or str(entities.get("customer_id")),
                "quotation_date": default_txn_date(entities),
                "status": "DRAFT",
            }
            if entities.get("amount") is not None:
                args["amount"] = parse_positive_amount(entities.get("amount"))
            tool_calls = [{"tool_name": "create_quotation", "arguments": args}]
    else:
        tool_calls = plan.normalized_tool_selection()

    return await finalize_result(
        section="sales",
        plan=plan,
        tool_calls=tool_calls,
        missing_fields=missing,
        execute_tool=execute_tool,
    )
