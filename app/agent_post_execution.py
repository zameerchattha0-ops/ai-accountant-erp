"""Post-execution verification, integrity checks, and failure summary helpers for app.agent."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.idempotency import FINANCIAL_WRITE_TOOLS
from app.models.schemas import ToolCall, ToolResult


def intent_tool_names(intent: str) -> frozenset:
    """The tool slugs that carry out *intent* as a financial mutation."""
    from app.tool_selector import intent_tools

    candidates = set(intent_tools(intent)) | {str(intent or "")}
    return frozenset(name for name in candidates if name in FINANCIAL_WRITE_TOOLS)


def financial_mutation_failures(tool_results: Sequence[ToolResult]) -> List[ToolResult]:
    """Failed financial mutations (idempotency-guarded writes to the books)."""
    return [
        tr for tr in tool_results
        if not tr.success and tr.tool_name in FINANCIAL_WRITE_TOOLS
    ]


def primary_mutation_failed(tool_results: Sequence[ToolResult], *, intent: str) -> bool:
    """True when the user's primary requested mutation did not succeed."""
    primary_tools = intent_tool_names(intent)
    if not primary_tools:
        return False
    primary_results = [tr for tr in tool_results if tr.tool_name in primary_tools]
    if not primary_results:
        return True
    return any(not tr.success for tr in primary_results)


def plan_performs_no_financial_mutation(
    *, intent: str, calls: Sequence[ToolCall]
) -> bool:
    """True when a transaction plan performs NO financial mutation."""
    from app.planner import _TRANSACTION_INTENTS

    if intent not in _TRANSACTION_INTENTS:
        return False
    if not intent_tool_names(intent):
        return False
    return not any(tc.tool_name in FINANCIAL_WRITE_TOOLS for tc in calls or ())


CARRY_ENTITY_ARGS: Dict[str, Dict[str, str]] = {
    "create_credit_note": {
        "invoice_number": "invoice_number",
        "customer_name": "customer_name",
        "line_items": "items",
        "item_description": "description",
        "quantity": "quantity",
        "amount": "amount",
        "reason": "reason",
    },
    "create_purchase_return": {
        "bill_number": "bill_number",
        "supplier_name": "supplier_name",
        "line_items": "items",
        "item_description": "description",
        "quantity": "quantity",
        "amount": "amount",
        "reason": "reason",
    },
}


def carry_forward_write_args(
    calls: Sequence[ToolCall],
    *,
    entities: Dict[str, Any],
    original: Sequence[ToolCall],
) -> List[ToolCall]:
    """Ensure a continuation round never drops reference numbers, priced lines, or reason."""
    if not calls:
        return list(calls or ())
    orig_by_tool: Dict[str, Dict[str, Any]] = {}
    for oc in original or ():
        if oc.tool_name not in orig_by_tool:
            orig_by_tool[oc.tool_name] = dict(oc.arguments or {})

    merged: List[ToolCall] = []
    for call in calls:
        args = dict(call.arguments or {})

        def _empty(value: Any) -> bool:
            return value in (None, "", [], {})

        for key, value in (orig_by_tool.get(call.tool_name) or {}).items():
            if _empty(args.get(key)) and not _empty(value):
                args[key] = value
        for entity_key, arg_key in (CARRY_ENTITY_ARGS.get(call.tool_name) or {}).items():
            value = (entities or {}).get(entity_key)
            if _empty(args.get(arg_key)) and not _empty(value):
                args[arg_key] = value
        merged.append(ToolCall(tool_name=call.tool_name, arguments=args))
    return merged


def document_integrity_violations(
    tool_results: Sequence[Any],
    *,
    entities: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Deterministic post-write integrity checks for return documents."""
    ents = entities or {}
    violations: List[str] = []
    for tr in tool_results or ():
        if not (getattr(tr, "success", False) and isinstance(tr.data, dict)):
            continue
        data = tr.data
        name = getattr(tr, "tool_name", "")
        if name == "create_credit_note":
            if float(data.get("total") or 0) <= 0:
                violations.append("credit note recorded a ZERO amount — it reverses nothing")
            if not data.get("journal_posted"):
                violations.append("credit note has no posted reversal journal")
            if (ents.get("invoice_number") or ents.get("invoice_id")) and not (
                data.get("invoice_id") or data.get("invoice_number")
            ):
                violations.append("credit note is not linked to the invoice the user named")
        elif name == "create_purchase_return":
            if float(data.get("total") or 0) <= 0:
                violations.append("debit note recorded a ZERO amount — it reverses nothing")
            if not data.get("journal_posted"):
                violations.append("debit note has no posted reversal journal")
            if (ents.get("bill_number") or ents.get("bill_id")) and not (
                data.get("bill_id") or data.get("bill_number")
            ):
                violations.append("debit note is not linked to the bill the user named")
    return violations


REQUIRED_VALUE_ERROR_RE = re.compile(
    r"must be supplied by the user|required .* field '.*' is missing",
    re.IGNORECASE,
)


def user_input_required_question(failed: Sequence[ToolResult]) -> Optional[str]:
    """Clarification question when a failure demands a user-supplied required field."""
    for tr in failed or ():
        text = str(tr.error or "").strip()
        if not text or not REQUIRED_VALUE_ERROR_RE.search(text):
            continue
        return (
            "I could not record this yet — the records refused it and said the "
            f"value has to come from you: {text[:400]} Give me that value and I "
            "will continue from where I stopped (nothing else was recorded)."
        )
    return None


def execution_failure_summary(
    successful_results: Sequence[ToolResult],
    failed_results: Sequence[ToolResult],
    *,
    intent: str,
) -> str:
    """Evidence-derived failure summary built strictly from executed tool results."""
    succeeded = [tr.tool_name for tr in successful_results]
    failed = [tr.tool_name for tr in failed_results]
    parts = []
    if intent in failed:
        parts.append(f"{intent} failed — nothing was recorded for it")
    else:
        parts.append(f"{', '.join(failed)} failed")
    if succeeded:
        parts.append("completed before the failure: " + ", ".join(succeeded))
    return "Operation FAILED. " + ". ".join(parts) + "."


def mutation_date(tc: ToolCall, tr: Optional[ToolResult]) -> Optional[str]:
    """Best-effort recorded date of a mutation."""
    from app.tool_router import _TXN_DATE_PARAM

    param = _TXN_DATE_PARAM.get(tc.tool_name)
    args = tc.arguments or {}
    for key in (param, "transaction_date"):
        if key and args.get(key):
            return str(args[key])
    if tr is not None and isinstance(getattr(tr, "data", None), dict):
        if tr.data.get("transaction_date"):
            return str(tr.data["transaction_date"])
    return None


RECORDED_DATE_KEYS = (
    "transaction_date", "invoice_date", "bill_date", "expense_date",
    "quotation_date", "credit_note_date", "return_date", "receipt_date",
    "payment_date", "transfer_date",
)


def extract_recorded_date(tool_results: List[ToolResult]) -> Tuple[Optional[str], bool]:
    """Recorded transaction date and defaulted flag from mutation results."""
    date_val: Optional[str] = None
    defaulted = False
    for tr in tool_results or []:
        data = tr.data if isinstance(tr.data, dict) else {}
        if not date_val:
            for key in RECORDED_DATE_KEYS:
                if data.get(key):
                    date_val = str(data[key])[:10]
                    break
        defaulted = defaulted or bool(data.get("date_defaulted"))
        if date_val and defaulted:
            break
    return date_val, defaulted


def build_batch_breakdown(
    batch_items: List[Dict[str, Any]],
    tool_calls: List[ToolCall],
    tool_results: List[ToolResult],
) -> str:
    """Per-document result summary for a BATCH plan."""
    from app.tools import get_handler as _registry_entry

    mutations: List[tuple] = []
    for idx, tc in enumerate(tool_calls):
        entry = _registry_entry(tc.tool_name)
        if entry and not entry.get("read_only", False):
            tr = tool_results[idx] if idx < len(tool_results) else None
            mutations.append((tc, tr))

    planned = len(batch_items)
    lines = [f"Batch execution - {planned} documents requested:"]
    for i, (tc, tr) in enumerate(mutations, start=1):
        if tr is not None and tr.success:
            dated = mutation_date(tc, tr)
            suffix = f" Dated {dated}." if dated else ""
            lines.append(f"  Document {i} ({tc.tool_name}): created.{suffix}")
        else:
            err = (tr.error if tr is not None else "not executed") or "unknown error"
            lines.append(f"  Document {i} ({tc.tool_name}): FAILED - {err}")

    succeeded = sum(1 for _, tr in mutations if tr is not None and tr.success)
    failed = len(mutations) - succeeded
    lines.append(
        f"  Total: {succeeded} succeeded, {failed} failed"
        + (f", {planned - len(mutations)} not executed" if len(mutations) < planned else "")
        + ". Each document is independent - successful siblings were not rolled back."
    )
    return "\n".join(lines)
