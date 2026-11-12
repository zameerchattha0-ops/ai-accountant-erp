"""Operating expenses pipeline (cash/bank expenses & payable settlement checks)."""

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

EXPENSE_INTENTS = frozenset(
    {
        "record_expense",
        "create_expense",
        "record_expense_payment",
    }
)


class ExpensesPipeline(BasePipeline):
    section = "expenses"

    async def handle(self, plan: TransactionPlan, org_id: str, **kwargs: Any) -> Dict[str, Any]:
        return await handle(plan, org_id, **kwargs)


async def handle(
    plan: TransactionPlan,
    org_id: str,
    *,
    execute_tool: Optional[ExecuteToolFn] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Handle immediate operating expenses without requiring a supplier ledger."""
    entities = plan.entities
    intent = plan.intent.lower()
    amount = parse_positive_amount(entities.get("amount"))
    payment_method = normalize_payment_method(entities.get("payment_method"))
    purpose = str(
        entities.get("transaction_purpose")
        or entities.get("item_description")
        or entities.get("description")
        or ""
    ).strip()

    warnings: List[str] = []
    sec73 = check_section_73_cash_limit(amount, payment_method)
    if sec73:
        warnings.append(sec73)

    # Settlement check gate: if user indicated paying an existing payable and hasn't confirmed
    settlement_pos = str(entities.get("settlement_position") or "").upper()
    if (
        intent == "record_expense"
        and settlement_pos == "SETTLE_EXISTING_PAYABLE"
        and not entities.get("settle_confirmed")
    ):
        return await finalize_result(
            section="expenses",
            plan=plan,
            missing_fields=["settlement_check"],
            questions=[
                {
                    "field": "settlement_check",
                    "question": "Should this payment settle an existing unpaid vendor bill or be recorded as a new operating expense?",
                    "options": [
                        {"value": "settle", "label": "Settle existing payable"},
                        {"value": "new_expense", "label": "Record as new expense"},
                    ],
                }
            ],
            warnings=warnings,
            execute_tool=execute_tool,
        )

    missing: List[str] = []
    if amount is None:
        missing.append("amount")
    if not purpose:
        missing.append("transaction_purpose")
    if not payment_method:
        missing.append("payment_method")
    if missing:
        return await finalize_result(
            section="expenses",
            plan=plan,
            missing_fields=missing,
            warnings=warnings,
            execute_tool=execute_tool,
        )

    # Operating expenses paid via cash/bank do NOT require a supplier ledger.
    args: Dict[str, Any] = {
        "amount": amount,
        "expense_date": default_txn_date(entities),
        "payment_method": payment_method,
        "description": purpose,
    }
    if entities.get("account_id"):
        args["account_id"] = str(entities["account_id"])
    elif entities.get("account_name"):
        args["account_name"] = str(entities["account_name"]).strip()
    if entities.get("category"):
        args["category"] = str(entities["category"]).strip()

    tool_name = "record_expense_payment" if intent == "record_expense_payment" else "record_expense"
    if tool_name == "record_expense_payment" and entities.get("bill_id"):
        args["bill_id"] = str(entities["bill_id"])
        if entities.get("supplier_id"):
            args["supplier_id"] = str(entities["supplier_id"])

    return await finalize_result(
        section="expenses",
        plan=plan,
        tool_calls=[{"tool_name": tool_name, "arguments": args}],
        warnings=warnings,
        execute_tool=execute_tool,
    )
