"""
ERP AI Agent — Structured LLM Entity & Intent Extraction
=========================================================
Replaces brittle regex entity extraction with a strict Pydantic schema
backed by Gemini structured JSON output (``response_schema``).

Contract:
  * Distinguishes ``informational`` queries, ``transactional`` booking
    requests, and ``advisory`` / planned-purchase statements.
  * Never invents counterparties from generic nouns ("bills", "suppliers",
    "invoices") or captures amounts as item descriptions.
  * Returns a low-confidence fallback ``StructuredTransactionDraft`` when
    the provider is unavailable or returns unparseable output so the caller
    can fall back cleanly to the deterministic planner.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any, Dict, List, Literal, Optional

import structlog
from google.genai import types
from pydantic import BaseModel, Field, field_validator

from app.gemini_client import get_client
from app.tool_selector import _INTENT_TOOLS

log = structlog.get_logger(__name__)

# Canonical read-only / informational intents alongside tool_selector's mutation intents
_INFORMATIONAL_INTENTS = (
    "get_open_payables",
    "get_open_receivables",
    "generate_cash_flow",
    "list_bank_accounts",
    "get_inventory_status",
    "supplier_balance",
    "customer_balance",
    "generate_supplier_ledger",
    "generate_customer_ledger",
    "generate_general_ledger",
    "generate_trial_balance",
    "generate_balance_sheet",
    "generate_profit_loss",
    "list_expenses",
    "list_customers",
    "list_suppliers",
    "list_employees",
    "project_profitability",
    "get_chart_of_accounts",
)

CANONICAL_INTENTS = tuple(sorted(set(_INTENT_TOOLS.keys()) | set(_INFORMATIONAL_INTENTS)))

_PAYMENT_CHANNEL_ALIASES = {
    "cash": "cash",
    "bank": "bank_transfer",
    "bank_transfer": "bank_transfer",
    "bank transfer": "bank_transfer",
    "transfer": "bank_transfer",
    "online": "bank_transfer",
    "credit": "credit",
    "payable": "credit",
    "on credit": "credit",
    "cheque": "cheque",
    "check": "cheque",
}

_EXTRACTION_PROMPT_TEMPLATE = """Extract structured ERP fields as JSON matching the schema.

Canonical intents:
{intents}

Rules:
1. user_intent_type MUST classify the utterance carefully:
   - "informational": user asks to view/list/check existing data, balances, reports, or status (e.g. "what is our cash balance?", "show me all outstanding supplier bills").
   - "transactional": explicit command to record/post/create an entry or master record (e.g. "record cash purchase of 50000", "create invoice for Acme").
   - "advisory": user describes an in-progress/planned action or seeks guidance without an explicit booking command (e.g. "I am purchasing 2 sofas from Shabbir Furniture" -> advisory, NOT transactional).
2. counterparty: extract ONLY if a specific named person/company is stated. NEVER treat generic words ("bills", "supplier", "vendor", "customer", "invoices", "cash") as a counterparty name. Set counterparty to null when absent.
3. line_items: extract each item/service with singular/clean description, numeric quantity, unit_price, and unit if stated. Never put amounts into description.
4. payment_channel: one of "cash", "bank_transfer", "credit", "cheque", or null.
5. transaction_nature: e.g. OPERATING_EXPENSE, FIXED_ASSET, INVENTORY, REVENUE, SERVICE, or null.
6. currency: default "PKR" unless another currency is stated.
7. missing_fields: list material fields still unknown for transactional/advisory requests (e.g. ["total_amount", "transaction_date", "payment_channel"]). Empty for informational queries.
8. confidence: 0.0-1.0 overall extraction confidence.

Context:
{context_json}

History:
{history_json}

User message:
{user_message}"""


class CounterpartyInfo(BaseModel):
    """Extracted business party (customer, supplier, or employee)."""

    name: str
    role: Literal["customer", "supplier", "employee"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Counterparty name cannot be empty")
        return text

    @field_validator("role", mode="before")
    @classmethod
    def _norm_role(cls, value: Any) -> str:
        low = str(value or "").strip().lower()
        if low in ("vendor", "payee"):
            return "supplier"
        if low in ("client", "buyer", "payer"):
            return "customer"
        if low in ("staff", "worker"):
            return "employee"
        return low


class LineItem(BaseModel):
    """Single extracted product or service line item."""

    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    unit: Optional[str] = None

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("LineItem description cannot be empty")
        return text


class StructuredTransactionDraft(BaseModel):
    """Strict Pydantic state produced by LLM structured extraction."""

    intent: Optional[str] = None
    counterparty: Optional[CounterpartyInfo] = None
    line_items: List[LineItem] = Field(default_factory=list)
    payment_channel: Optional[Literal["cash", "bank_transfer", "credit", "cheque"]] = None
    transaction_nature: Optional[str] = None
    transaction_date: Optional[str] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = "PKR"
    missing_fields: List[str] = Field(default_factory=list)
    user_intent_type: Literal["informational", "transactional", "advisory"] = "transactional"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("counterparty", mode="before")
    @classmethod
    def _drop_empty_counterparty(cls, value: Any) -> Any:
        if isinstance(value, dict) and not str(value.get("name") or "").strip():
            return None
        return value

    @field_validator("payment_channel", mode="before")
    @classmethod
    def _norm_payment_channel(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        low = str(value).strip().lower()
        if not low:
            return None
        return _PAYMENT_CHANNEL_ALIASES.get(low, low)

    @field_validator("currency", mode="before")
    @classmethod
    def _default_currency(cls, value: Any) -> str:
        text = str(value or "").strip().upper()
        return text or "PKR"

    @field_validator("user_intent_type", mode="before")
    @classmethod
    def _norm_intent_type(cls, value: Any) -> str:
        if value is None:
            return "transactional"
        return str(value).strip().lower()


def _compact_context(org_context: Optional[dict]) -> Dict[str, Any]:
    if not isinstance(org_context, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in ("name", "currency", "country", "today", "organization_name"):
        if org_context.get(key) is not None:
            out[key] = org_context[key]
    org = org_context.get("organization")
    if isinstance(org, dict):
        for key in ("name", "currency", "country"):
            if org.get(key) is not None and key not in out:
                out[key] = org[key]
    return out


def _compact_history(conversation_history: Optional[list]) -> List[Dict[str, str]]:
    if not isinstance(conversation_history, list):
        return []
    out: List[Dict[str, str]] = []
    for entry in conversation_history[-6:]:
        if isinstance(entry, dict):
            item: Dict[str, str] = {}
            for k in ("field", "field_id", "question", "answer", "role", "content"):
                if entry.get(k) is not None:
                    item[k] = str(entry[k])[:160]
            if item:
                out.append(item)
    return out


def build_extraction_prompt(
    user_message: str,
    conversation_history: Optional[list] = None,
    org_context: Optional[dict] = None,
) -> str:
    """Build the focused (~800 token max) extraction prompt."""
    return _EXTRACTION_PROMPT_TEMPLATE.format(
        intents=", ".join(CANONICAL_INTENTS),
        context_json=json.dumps(_compact_context(org_context), ensure_ascii=False),
        history_json=json.dumps(_compact_history(conversation_history), ensure_ascii=False),
        user_message=(user_message or "").strip()[:1500],
    )


def _strip_json_fences(raw_text: str) -> str:
    cleaned = str(raw_text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _parse_response(response: Any) -> StructuredTransactionDraft:
    if isinstance(response, StructuredTransactionDraft):
        return response
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, StructuredTransactionDraft):
        return parsed
    if isinstance(parsed, dict):
        return StructuredTransactionDraft.model_validate(parsed)

    text = getattr(response, "text", None)
    if not text and hasattr(response, "candidates"):
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                if getattr(part, "text", None):
                    text = part.text
                    break
    if text is None and isinstance(response, (str, dict)):
        if isinstance(response, dict):
            return StructuredTransactionDraft.model_validate(response)
        text = response
    if not text:
        raise ValueError("Empty Gemini structured extraction response")
    cleaned = _strip_json_fences(str(text))
    return StructuredTransactionDraft.model_validate_json(cleaned)


async def _call_gemini_structured(client: Any, prompt: str) -> Any:
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=StructuredTransactionDraft,
        temperature=0.1,
        max_output_tokens=1024,
    )
    if hasattr(client, "generate_structured"):
        result = client.generate_structured(
            prompt=prompt,
            response_schema=StructuredTransactionDraft,
            config=config,
        )
        return await result if inspect.isawaitable(result) else result

    gclient = getattr(client, "_gclient", None)
    models = getattr(gclient, "models", None)
    if models is None or not hasattr(models, "generate_content"):
        raise AttributeError("Gemini client does not expose models.generate_content")

    model_name = getattr(client, "model_name", "gemini-3.8-flash")
    gen_fn = models.generate_content
    if inspect.iscoroutinefunction(gen_fn):
        return await gen_fn(model=model_name, contents=prompt, config=config)
    result = await asyncio.to_thread(
        gen_fn,
        model=model_name,
        contents=prompt,
        config=config,
    )
    return await result if inspect.isawaitable(result) else result


async def extract_structured(
    user_message: str,
    conversation_history: Optional[list] = None,
    org_context: Optional[dict] = None,
) -> StructuredTransactionDraft:
    """Extract a ``StructuredTransactionDraft`` via Gemini structured output.

    Calls Gemini (via ``app/gemini_client.py``) with ``response_schema`` set to
    ``StructuredTransactionDraft``. On provider or validation failure, returns a
    safe fallback draft with ``confidence=0.0`` so callers can fall through to
    ``run_planner()``.
    """
    prompt = build_extraction_prompt(
        user_message=user_message,
        conversation_history=conversation_history or [],
        org_context=org_context or {},
    )
    try:
        client = get_client()
        response = await _call_gemini_structured(client, prompt)
        return _parse_response(response)
    except AssertionError as exc:
        if "REAL_DB_ACCESS" not in str(exc):
            raise
        log.warning("extraction.no_api_key_in_test", error=str(exc)[:200])
        return StructuredTransactionDraft(
            user_intent_type="transactional",
            confidence=0.0,
            missing_fields=[],
        )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully to planner fallback
        log.warning("extraction.structured_failed", error=str(exc)[:200])
        return StructuredTransactionDraft(
            user_intent_type="transactional",
            confidence=0.0,
            missing_fields=[],
        )


_CHANNEL_TO_PLANNER = {
    "cash": "CASH",
    "bank_transfer": "BANK_TRANSFER",
    "credit": "CREDIT",
    "cheque": "CHEQUE",
}


def draft_to_prefill_entities(draft: StructuredTransactionDraft) -> Dict[str, Any]:
    """Convert a ``StructuredTransactionDraft`` to ``planner.plan`` prefill_entities."""
    prefill: Dict[str, Any] = {}
    if draft.intent:
        prefill["semantic_intent"] = draft.intent
    if draft.counterparty and draft.counterparty.name:
        role = draft.counterparty.role
        if role == "supplier":
            prefill["supplier_name"] = draft.counterparty.name
        elif role == "customer":
            prefill["customer_name"] = draft.counterparty.name
        elif role == "employee":
            prefill["employee_name"] = draft.counterparty.name
        prefill["counterparty_role"] = role
    if draft.line_items:
        prefill["line_items"] = [
            li.model_dump(exclude_none=True) for li in draft.line_items
        ]
        descs = [li.description for li in draft.line_items if li.description]
        if descs:
            prefill["item_description"] = " / ".join(descs)
        if len(draft.line_items) == 1:
            first = draft.line_items[0]
            if first.quantity is not None:
                prefill["quantity"] = first.quantity
                prefill["item_quantity"] = first.quantity
            if first.unit_price is not None:
                prefill["unit_price"] = first.unit_price
    if draft.payment_channel:
        mapped = _CHANNEL_TO_PLANNER.get(draft.payment_channel)
        if mapped:
            prefill["payment_method"] = mapped
            prefill["payment_type"] = "BANK" if mapped == "BANK_TRANSFER" else mapped
    if draft.transaction_nature:
        prefill["transaction_nature"] = draft.transaction_nature
    if draft.transaction_date:
        prefill["transaction_date"] = draft.transaction_date
    if draft.total_amount is not None:
        prefill["amount"] = draft.total_amount
    if draft.currency:
        prefill["currency"] = draft.currency
    prefill["user_intent_type"] = draft.user_intent_type
    return prefill
