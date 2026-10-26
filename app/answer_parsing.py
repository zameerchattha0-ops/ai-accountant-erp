"""LLM questionnaire answer parser / packed-reply splitter (2026-10-21).

When a user answers a consolidated clarification question with a packed reply
(e.g., "150000, 5 years, 0" or "cash, today, 5 years, STRAIGHT LINE, 0"),
positional string-splitting fails whenever parts and questions count mismatch.

AUTHORITY SPLIT:
* Grounded LLM takes:
  1. The EXACT questionnaire text asked;
  2. The EXACT list of allowable canonical field endpoints acceptable by Python
     parsers (_merge_field_answer);
  3. The clear gloss/definition of each field endpoint;
  4. The user's unstructured/messy reply;
* Output: A strict JSON map of {canonical_field: extracted_raw_value}.
* Invariant: Python rejects any key not in the allowed endpoint set and routes
  each extracted value through _merge_field_answer for deterministic type-checking,
  range-checking, and double-entry validation.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Sequence

import structlog

log = structlog.get_logger(__name__)

# Canonical field endpoints supported by app/planner.py:_merge_field_answer
# and app/questionnaire.py:QUESTION_BANK.
CANONICAL_FIELD_ENDPOINTS: Dict[str, str] = {
    "amount": "The financial transaction money amount / cost (e.g. 150000, 2500.50).",
    "transaction_date": "The purchase or transaction date (e.g. today, 2026-10-21, 01/01/2026).",
    "useful_life_years": "Asset useful life in years as an integer (e.g. 5, 5 years, 10).",
    "depreciation_method": "Depreciation method: STRAIGHT_LINE, REDUCING_BALANCE, or NONE.",
    "salvage_value": "Asset salvage / residual value at end of life (e.g. 0, 5000).",
    "payment_type": "Payment settlement method: CASH, BANK, or CREDIT.",
    "supplier_name": "Name of the supplier or vendor.",
    "customer_name": "Name of the customer.",
    "item_description": "Description of the item, product, or service bought or sold.",
    "quantity": "Quantity or unit count (e.g. 2, 10).",
    "asset_name": "Name or identifier of the fixed asset (e.g. Delivery Van).",
    "transaction_nature": "Classification: FIXED_ASSET, INVENTORY, CONSUMABLE, or SERVICE.",
    "capitalization_decision": "CAPITALIZE or EXPENSE.",
    "settlement_position": "Settlement treatment: PAID_NOW, OUTSTANDING (payable/pay later), PREPAID, or SETTLE_EXISTING_PAYABLE.",
    "payment_method": "Payment method: CASH, BANK_TRANSFER, CHEQUE, CARD, or CREDIT.",
    "account_name": "Specific ledger account name to post to.",
    "line_items": "Prices, quantities, or details of multiple item lines (e.g. 'tables 10000 each and chairs 3000 each').",
}

_SYSTEM_INSTRUCTION = (
    "You are an exact form-field extraction parser for an accounting ERP system.\n"
    "A user was asked clarification questions and replied with an unstructured, "
    "potentially multi-part or packed answer.\n\n"
    "You are given:\n"
    "1. The exact questions asked;\n"
    "2. The user's reply;\n"
    "3. The EXACT ALLOWABLE FIELD ENDPOINTS with their specifications.\n\n"
    "STRICT GROUNDING RULES:\n"
    "- You must ONLY extract fields present in the ALLOWABLE FIELD ENDPOINTS list.\n"
    "- NEVER invent, hallucinate, or abbreviate field names.\n"
    "- Extract the verbatim substring or minimal raw value for each field from the user reply.\n"
    "- If an allowable field was NOT answered or cannot be determined from the reply, DO NOT include it.\n"
    "- Output STRICT JSON matching: {\"<field_name>\": \"<extracted_value>\"}.\n"
    "- Do not include explanations, notes, or markdown fences outside the JSON."
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def parse_packed_reply_to_endpoints(
    *,
    question_text: str,
    user_reply: str,
    allowed_endpoints: Optional[Sequence[str]] = None,
    client: Optional[Any] = None,
    timeout: float = 8.0,
) -> Optional[Dict[str, str]]:
    """Parse user reply into canonical {field: value} grounded to valid endpoints."""
    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "llm_answer_parsing_enabled", True):
        return None

    cleaned_reply = (user_reply or "").strip()
    if not cleaned_reply:
        return None

    # Determine allowed fields: if none specified, use full canonical vocabulary
    if allowed_endpoints:
        allowed_set = {f.strip() for f in allowed_endpoints if f and f.strip() in CANONICAL_FIELD_ENDPOINTS}
    else:
        allowed_set = set(CANONICAL_FIELD_ENDPOINTS.keys())

    if not allowed_set:
        return None

    if client is None:
        try:
            from app.ai_orchestrator import get_client
            client = get_client()
        except Exception as exc:
            log.warning("answer_parsing.get_client_failed", error=str(exc)[:160])
            return None

    endpoint_docs = [
        f"- {field}: {CANONICAL_FIELD_ENDPOINTS[field]}"
        for field in sorted(allowed_set)
    ]

    prompt = (
        f"QUESTIONS ASKED TO USER:\n{question_text.strip()}\n\n"
        f"USER'S RAW REPLY:\n{cleaned_reply}\n\n"
        f"ALLOWABLE FIELD ENDPOINTS (You may ONLY choose from these exact keys):\n"
        + "\n".join(endpoint_docs) + "\n\n"
        "Return the strictly grounded JSON object:"
    )

    try:
        # Combine system instruction + prompt into one prompt string.
        # The orchestrator's generate_text_light() returns a plain str
        # and does not accept separate system_instruction / temperature.
        full_prompt = f"{_SYSTEM_INSTRUCTION}\n\n{prompt}"
        raw_text = await asyncio.wait_for(
            client.generate_text_light(prompt=full_prompt),
            timeout=timeout,
        )
        raw_text = str(raw_text or "")
        parsed = _extract_json(raw_text)
        if not isinstance(parsed, dict):
            log.info("answer_parsing.invalid_json_output", raw=raw_text[:200])
            return None

        # Filter strictly to allowable endpoints with non-empty values
        grounded: Dict[str, str] = {}
        for k, v in parsed.items():
            k_clean = str(k).strip()
            if k_clean in allowed_set and v is not None:
                val_str = str(v).strip()
                if val_str:
                    grounded[k_clean] = val_str

        if grounded:
            log.info(
                "answer_parsing.grounded_fields_extracted",
                fields=sorted(grounded.keys()),
                reply_preview=cleaned_reply[:60],
            )
            return grounded
        return None

    except asyncio.TimeoutError:
        log.warning("answer_parsing.timeout", timeout=timeout)
        return None
    except Exception as exc:
        log.warning("answer_parsing.failed", error=str(exc)[:200])
        return None


async def parse_line_items_reply_with_llm(
    *,
    user_reply: str,
    existing_items: Optional[List[Dict[str, Any]]] = None,
    client: Optional[Any] = None,
    timeout: float = 8.0,
) -> Optional[Dict[str, Any]]:
    """Parse a user clarification reply specifying prices or details for multi-item lines using LLM."""
    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "llm_answer_parsing_enabled", True):
        return None

    cleaned_reply = (user_reply or "").strip()
    if not cleaned_reply:
        return None

    if client is None:
        try:
            from app.ai_orchestrator import get_client
            client = get_client()
        except Exception as exc:
            log.warning("answer_parsing.get_client_failed", error=str(exc)[:160])
            return None

    items_repr = json.dumps(existing_items or [])
    prompt = (
        "You are an exact accounting line-item price parser.\n"
        f"The transaction has these line items: {items_repr}\n"
        f"USER REPLY: \"{cleaned_reply}\"\n"
        "Extract unit_price and total_amount for each item. "
        "Compute total_amount = quantity * unit_price or unit_price = total_amount / quantity if one is given. "
        "Output STRICT JSON only: {\"line_items\": [{\"description\": \"<item name>\", \"quantity\": <number>, \"unit_price\": <number>, \"total_amount\": <number>}], \"total_amount\": <number>}\n"
        "Do not output any text outside JSON."
    )
    try:
        raw_text = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt),
            timeout=timeout,
        )
        parsed = _extract_json(str(raw_text or ""))
        if isinstance(parsed, dict) and isinstance(parsed.get("line_items"), list):
            valid_items = []
            for itm in parsed["line_items"]:
                if not isinstance(itm, dict):
                    continue
                d = str(itm.get("description") or "").strip()
                if not d:
                    continue
                q = itm.get("quantity")
                up = itm.get("unit_price")
                tot = itm.get("total_amount")
                clean_itm: Dict[str, Any] = {"description": d}
                if q is not None:
                    try:
                        clean_itm["quantity"] = float(q)
                    except (ValueError, TypeError):
                        pass
                if up is not None:
                    try:
                        clean_itm["unit_price"] = float(up)
                    except (ValueError, TypeError):
                        pass
                if tot is not None:
                    try:
                        clean_itm["total_amount"] = float(tot)
                    except (ValueError, TypeError):
                        pass
                if "total_amount" in clean_itm and "unit_price" not in clean_itm and clean_itm.get("quantity"):
                    clean_itm["unit_price"] = clean_itm["total_amount"] / clean_itm["quantity"]
                if "unit_price" in clean_itm and "total_amount" not in clean_itm and clean_itm.get("quantity"):
                    clean_itm["total_amount"] = clean_itm["unit_price"] * clean_itm["quantity"]
                valid_items.append(clean_itm)
            if valid_items:
                tot = parsed.get("total_amount")
                derived_tot = sum(it.get("total_amount", (it.get("quantity", 1) * it.get("unit_price", 0))) for it in valid_items)
                return {
                    "line_items": valid_items,
                    "total_amount": float(tot) if tot is not None else derived_tot,
                }
    except Exception as exc:
        log.warning("answer_parsing.multi_item_failed", error=str(exc)[:160])
    return None
