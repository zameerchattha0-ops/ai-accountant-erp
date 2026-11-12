"""
ERP AI Agent — Typed Clarification Resume Schema
=================================================
Replaces brittle regex matching on clarification question text with typed
``ClarificationAnswer`` submissions keyed by ``field_id`` matching
``StructuredTransactionDraft`` fields.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Union

from pydantic import BaseModel, Field

from app.extraction import (
    CounterpartyInfo,
    LineItem,
    StructuredTransactionDraft,
)

_CUSTOMER_INTENTS = frozenset({
    "create_invoice",
    "record_credit_sale",
    "record_cash_sale",
    "record_sale",
    "create_quotation",
    "convert_quotation",
    "record_receipt",
    "create_credit_note",
    "customer_balance",
    "generate_customer_ledger",
})

_EMPLOYEE_INTENTS = frozenset({
    "create_employee",
    "run_payroll",
    "list_employees",
})

_PAYMENT_CHANNEL_MAP = {
    "cash": "cash",
    "bank": "bank_transfer",
    "bank_transfer": "bank_transfer",
    "bank transfer": "bank_transfer",
    "transfer": "bank_transfer",
    "online": "bank_transfer",
    "credit": "credit",
    "on credit": "credit",
    "payable": "credit",
    "cheque": "cheque",
    "check": "cheque",
}

_FIELD_ALIASES: Dict[str, str] = {
    "transaction_intent": "intent",
    "amount": "total_amount",
    "basic_salary": "total_amount",
    "proceeds_amount": "total_amount",
    "depreciation_amount": "total_amount",
    "payment_type": "payment_channel",
    "payment_method": "payment_channel",
    "date_of_joining": "transaction_date",
    "supplier_name": "counterparty",
    "customer_name": "counterparty",
    "employee_name": "counterparty",
    "party_name": "counterparty",
    "counterparty_role": "counterparty",
    "item_description": "line_items",
    "description": "line_items",
    "product_name": "line_items",
    "service_name": "line_items",
    "quantity": "line_items",
    "unit_price": "line_items",
}

VALID_DRAFT_FIELD_IDS = frozenset(StructuredTransactionDraft.model_fields.keys()) | frozenset(_FIELD_ALIASES.keys())


class ClarificationAnswer(BaseModel):
    """Typed answer to a clarification question keyed by draft field_id."""

    field_id: str = Field(..., min_length=1)
    value: Union[str, int, float, list, dict]
    source: Literal["user", "chip_selection", "default"] = "user"


class ClarificationResume(BaseModel):
    """Typed resume payload pairing answers with the original extracted draft."""

    answers: List[ClarificationAnswer] = Field(default_factory=list)
    original_draft: StructuredTransactionDraft


def _infer_role(intent: Any) -> Literal["customer", "supplier", "employee"]:
    intent_str = str(intent or "").strip()
    if intent_str in _CUSTOMER_INTENTS:
        return "customer"
    if intent_str in _EMPLOYEE_INTENTS:
        return "employee"
    return "supplier"


def _coerce_float(value: Any, field_id: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        for prefix in ("pkr", "rs.", "rs", "$", "usd"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
        try:
            return float(cleaned)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric value for {field_id}: {value!r}") from exc
    raise ValueError(f"Invalid numeric value for {field_id}: {value!r}")


def _normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("transaction_date cannot be empty")
    try:
        from app.date_parser import parse_transaction_date

        parsed = parse_transaction_date(text)
        if getattr(parsed, "ok", False) and getattr(parsed, "iso_date", None):
            return str(parsed.iso_date)
    except Exception:
        pass
    return text


def apply_answers(
    draft: StructuredTransactionDraft,
    answers: List[ClarificationAnswer],
) -> StructuredTransactionDraft:
    """Validate and merge typed ``ClarificationAnswer`` entries into *draft*.

    Routes strictly by ``field_id`` — zero regex matching on question text.
    Returns a newly validated ``StructuredTransactionDraft`` instance.
    """
    data: Dict[str, Any] = draft.model_dump()
    answered_ids: set[str] = set()

    for ans in answers:
        fid = ans.field_id.strip()
        if fid not in VALID_DRAFT_FIELD_IDS:
            raise ValueError(f"Unknown draft field_id: {fid!r}")

        val = ans.value
        canonical = _FIELD_ALIASES.get(fid, fid)
        answered_ids.add(fid)
        answered_ids.add(canonical)

        if canonical == "total_amount":
            data["total_amount"] = _coerce_float(val, fid)
        elif canonical == "confidence":
            data["confidence"] = _coerce_float(val, fid)
        elif canonical == "payment_channel":
            low = str(val or "").strip().lower()
            mapped = _PAYMENT_CHANNEL_MAP.get(low)
            if mapped is None:
                raise ValueError(f"Invalid payment_channel value: {val!r}")
            data["payment_channel"] = mapped
        elif canonical == "transaction_date":
            data["transaction_date"] = _normalize_date(val)
        elif canonical == "counterparty":
            if fid == "counterparty_role":
                existing = data.get("counterparty")
                if isinstance(existing, dict) and existing.get("name"):
                    existing["role"] = str(val).strip().lower()
                else:
                    raise ValueError("Cannot set counterparty_role without counterparty name")
            elif isinstance(val, dict):
                cp = CounterpartyInfo.model_validate(val)
                data["counterparty"] = cp.model_dump()
            else:
                role: Literal["customer", "supplier", "employee"]
                if fid == "supplier_name":
                    role = "supplier"
                elif fid == "customer_name":
                    role = "customer"
                elif fid == "employee_name":
                    role = "employee"
                else:
                    existing_cp = data.get("counterparty")
                    role = (
                        existing_cp["role"]
                        if isinstance(existing_cp, dict) and existing_cp.get("role")
                        else _infer_role(data.get("intent"))
                    )
                cp = CounterpartyInfo(
                    name=str(val).strip(),
                    role=role,
                    confidence=1.0,
                )
                data["counterparty"] = cp.model_dump()
        elif canonical == "line_items":
            if fid in ("item_description", "description", "product_name", "service_name"):
                items = list(data.get("line_items") or [])
                if items:
                    items[0]["description"] = str(val).strip()
                else:
                    items.append(LineItem(description=str(val).strip()).model_dump())
                data["line_items"] = items
            elif fid == "quantity":
                qty = _coerce_float(val, fid)
                items = list(data.get("line_items") or [])
                if items:
                    items[0]["quantity"] = qty
                    data["line_items"] = items
                else:
                    raise ValueError("Cannot set quantity when line_items is empty")
            elif fid == "unit_price":
                price = _coerce_float(val, fid)
                items = list(data.get("line_items") or [])
                if items:
                    items[0]["unit_price"] = price
                    data["line_items"] = items
                else:
                    raise ValueError("Cannot set unit_price when line_items is empty")
            elif isinstance(val, list):
                data["line_items"] = [LineItem.model_validate(item).model_dump() for item in val]
            elif isinstance(val, dict):
                data["line_items"] = [LineItem.model_validate(val).model_dump()]
            else:
                data["line_items"] = [LineItem(description=str(val).strip()).model_dump()]
        elif canonical == "missing_fields":
            if not isinstance(val, list):
                raise ValueError("missing_fields must be a list")
            data["missing_fields"] = [str(x) for x in val]
        elif canonical == "transaction_nature":
            data["transaction_nature"] = str(val).strip().upper()
        elif canonical == "currency":
            data["currency"] = str(val).strip().upper() or "PKR"
        elif canonical in ("intent", "user_intent_type"):
            data[canonical] = str(val).strip()

    if "missing_fields" not in answered_ids:
        remaining = [
            f for f in (data.get("missing_fields") or [])
            if f not in answered_ids and _FIELD_ALIASES.get(f, f) not in answered_ids
        ]
        data["missing_fields"] = remaining

    return StructuredTransactionDraft.model_validate(data)
