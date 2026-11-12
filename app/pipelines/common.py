"""Shared pipeline schemas, validation helpers, and base abstractions."""

from __future__ import annotations

from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Sequence, Union

from pydantic import BaseModel, Field, field_validator

SECTION_73_CASH_THRESHOLD = 50_000.0

ExecuteToolFn = Callable[[str, Dict[str, Any]], Awaitable[Any]]


class SelectedTool(BaseModel):
    """A single tool invocation selected by the unified reasoning call."""

    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class TransactionPlan(BaseModel):
    """Unified single-call output replacing multi-stage serial planning."""

    intent: str
    entities: Dict[str, Any] = Field(default_factory=dict)
    nature: Optional[str] = None
    questions: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    tool_selection: List[Union[str, SelectedTool, Dict[str, Any]]] = Field(
        default_factory=list
    )
    section: Optional[str] = None
    user_intent_type: Literal["informational", "transactional", "advisory"] = (
        "transactional"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    missing_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("intent", mode="before")
    @classmethod
    def _clean_intent(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("TransactionPlan.intent must be non-empty")
        return text

    @field_validator("nature", mode="before")
    @classmethod
    def _normalize_nature(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().upper()
        return text or None

    @field_validator("section", mode="before")
    @classmethod
    def _normalize_section(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None

    def normalized_tool_selection(self) -> List[Dict[str, Any]]:
        """Return tool_selection normalized to ``[{"tool_name", "arguments"}]``."""
        out: List[Dict[str, Any]] = []
        for item in self.tool_selection:
            if isinstance(item, SelectedTool):
                out.append({"tool_name": item.tool_name, "arguments": dict(item.arguments)})
            elif isinstance(item, dict):
                name = str(item.get("tool_name") or item.get("name") or "").strip()
                if name:
                    args = item.get("arguments")
                    out.append(
                        {"tool_name": name, "arguments": dict(args) if isinstance(args, dict) else {}}
                    )
            elif isinstance(item, str) and item.strip():
                out.append({"tool_name": item.strip(), "arguments": {}})
        return out


class BasePipeline:
    """Base interface for domain-specific execution pipelines."""

    section: str = "common"

    async def handle(self, plan: TransactionPlan, org_id: str, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError


def normalize_payment_method(raw: Any) -> Optional[str]:
    """Normalize payment method aliases to CASH, BANK, or CREDIT."""
    text = str(raw or "").strip().upper()
    if not text:
        return None
    if text in ("CASH", "PETTY_CASH"):
        return "CASH"
    if text in ("BANK", "BANK_TRANSFER", "CHEQUE", "ONLINE", "TRANSFER", "PAY_ORDER"):
        return "BANK"
    if text in ("CREDIT", "ON_CREDIT", "CREDIT_PURCHASE", "CREDIT_SALE", "PAYABLE", "RECEIVABLE"):
        return "CREDIT"
    return text


def check_section_73_cash_limit(
    amount: Any,
    payment_method: Any,
) -> Optional[str]:
    """Return a Section 73 / 21(l) compliance warning if cash exceeds PKR 50,000."""
    channel = normalize_payment_method(payment_method)
    if channel != "CASH" or amount is None:
        return None
    try:
        numeric = float(amount)
    except (TypeError, ValueError):
        return None
    if numeric > SECTION_73_CASH_THRESHOLD:
        return (
            f"Section 73 / Section 21(l) Compliance Warning: Cash payment of PKR {numeric:,.2f} "
            "exceeds the PKR 50,000 statutory limit. Route payment via crossed cheque, pay order, "
            "or direct bank transfer to preserve expense deductibility and input tax recovery."
        )
    return None


def parse_positive_amount(raw: Any) -> Optional[float]:
    """Parse a non-negative float amount, returning None when invalid."""
    if raw is None:
        return None
    try:
        val = float(str(raw).replace(",", "").strip())
        return val if val >= 0 else None
    except (TypeError, ValueError):
        return None


def reconcile_line_items(
    entities: Dict[str, Any],
    *,
    default_description: str,
    total_amount: Optional[float],
) -> Optional[List[Dict[str, Any]]]:
    """Build validated line items matching stated total_amount (tolerance 0.01).

    Returns ``None`` when explicit line_items fail validation or disagree with
    ``total_amount`` so callers fall back to clarification rather than guessing.
    """
    parsed_lines = entities.get("line_items")
    if parsed_lines:
        if not isinstance(parsed_lines, list):
            return None
        built: List[Dict[str, Any]] = []
        for entry in parsed_lines:
            if not isinstance(entry, dict):
                return None
            desc = str(entry.get("description") or entry.get("name") or "").strip()
            try:
                qty = float(entry.get("quantity") if entry.get("quantity") is not None else 1.0)
                if entry.get("unit_price") is not None:
                    unit_price = float(entry["unit_price"])
                elif entry.get("total_amount") is not None and qty > 0:
                    unit_price = round(float(entry["total_amount"]) / qty, 2)
                else:
                    return None
            except (TypeError, ValueError):
                return None
            if not desc or qty <= 0 or unit_price < 0:
                return None
            built.append({"description": desc, "quantity": qty, "unit_price": unit_price})

        if not built:
            return None
        if total_amount is not None:
            derived = round(sum(i["quantity"] * i["unit_price"] for i in built), 2)
            if abs(derived - float(total_amount)) > 0.01:
                return None
        return built

    if total_amount is None:
        return None

    raw_qty = entities.get("quantity")
    try:
        qty = float(raw_qty) if raw_qty is not None else 1.0
    except (TypeError, ValueError):
        qty = 1.0
    if qty <= 0:
        qty = 1.0
    desc = str(
        entities.get("item_description")
        or entities.get("description")
        or default_description
    ).strip()
    return [
        {
            "description": desc,
            "quantity": qty,
            "unit_price": round(float(total_amount) / qty, 2),
        }
    ]


def default_txn_date(entities: Dict[str, Any]) -> str:
    """Return stated transaction date or today's ISO date."""
    raw = (
        entities.get("transaction_date")
        or entities.get("bill_date")
        or entities.get("invoice_date")
        or entities.get("order_date")
        or entities.get("date")
    )
    return str(raw).strip() if raw else date.today().isoformat()


def collect_warnings(plan: TransactionPlan, *extra: Optional[str]) -> List[str]:
    """Merge plan warnings and pipeline-detected warnings without duplicates."""
    seen: List[str] = []
    for item in [*plan.warnings, *extra]:
        if item and item not in seen:
            seen.append(item)
    return seen


async def finalize_result(
    *,
    section: str,
    plan: TransactionPlan,
    tool_calls: Sequence[Dict[str, Any]] = (),
    missing_fields: Sequence[str] = (),
    questions: Sequence[Union[str, Dict[str, Any]]] = (),
    warnings: Sequence[str] = (),
    advisory: Optional[str] = None,
    execute_tool: Optional[ExecuteToolFn] = None,
) -> Dict[str, Any]:
    """Construct uniform pipeline response and optionally execute selected tools."""
    merged_missing = list(dict.fromkeys([*plan.missing_fields, *missing_fields]))
    merged_questions = list(questions) if questions else list(plan.questions)
    merged_warnings = collect_warnings(plan, *warnings)

    if merged_missing or merged_questions:
        return {
            "status": "needs_input",
            "section": section,
            "intent": plan.intent,
            "nature": plan.nature,
            "tool_calls": [],
            "missing_fields": merged_missing,
            "questions": merged_questions,
            "warnings": merged_warnings,
            "advisory": advisory,
        }

    calls = list(tool_calls) or plan.normalized_tool_selection()
    execution_results: List[Any] = []
    if execute_tool is not None and calls:
        for call in calls:
            res = await execute_tool(call["tool_name"], call.get("arguments") or {})
            execution_results.append(res)

    return {
        "status": "executed" if execution_results else ("advisory" if plan.user_intent_type == "advisory" and not calls else "ready"),
        "section": section,
        "intent": plan.intent,
        "nature": plan.nature,
        "tool_calls": calls,
        "missing_fields": [],
        "questions": [],
        "warnings": merged_warnings,
        "advisory": advisory,
        "execution_results": execution_results,
    }
