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
    "amount": "The financial transaction monetary amount / cost (e.g. 150000, 50000, 2500.50).",
    "transaction_date": "The purchase or transaction date (e.g. today, 2026-10-21, 01/01/2026, yesterday).",
    "useful_life_years": "Asset useful life in years as an integer (e.g. 5, 5 years, 10, or 'NONE' / 'no depreciation' if declined).",
    "depreciation_method": "Depreciation method: STRAIGHT_LINE, REDUCING_BALANCE, or NONE.",
    "salvage_value": "Asset salvage / residual scrap value at end of life (e.g. 0, 5000; 0 if none/unspecified).",
    "payment_type": "Payment settlement method: CASH, BANK, or CREDIT.",
    "payment_method": "Payment method: CASH, BANK_TRANSFER, CHEQUE, CARD, or CREDIT.",
    "supplier_name": "Name of the supplier or vendor (e.g. Shabbir Furnitures).",
    "customer_name": "Name of the customer.",
    "item_description": "Description of the item, product, or service bought or sold.",
    "quantity": "Quantity or unit count (e.g. 2, 10).",
    "asset_name": "Name or identifier of the fixed asset (e.g. Two Tables, Delivery Van, Workstation).",
    "transaction_nature": "Classification: FIXED_ASSET, INVENTORY, CONSUMABLE, or SERVICE.",
    "capitalization_decision": "CAPITALIZE or EXPENSE.",
    "settlement_position": "Settlement treatment: PAID_NOW, OUTSTANDING (payable/pay later), PREPAID, or SETTLE_EXISTING_PAYABLE.",
    "account_name": "Specific ledger account name to post to.",
    "line_items": "Prices, quantities, or details of multiple item lines (e.g. 'tables 10000 each and chairs 3000 each').",
}

_SYSTEM_INSTRUCTION = (
    "You are an expert accounting ERP natural language clarification interpreter and form-field extraction parser.\n"
    "A user was presented with questionnaire cards or questions and replied with an unstructured, conversational, "
    "multi-part, bulleted, or colloquial reply (in English, mixed English/Urdu, or numbers).\n\n"
    "You are given:\n"
    "1. The exact questions asked;\n"
    "2. The user's reply;\n"
    "3. The EXACT ALLOWABLE FIELD ENDPOINTS with their specifications.\n\n"
    "INTERPRETATION & EXTRACTION RULES:\n"
    "- Accept ANY natural phrasing, slang, shorthand, or conversational response.\n"
    "- Extract values for allowable field endpoints based on user meaning:\n"
    "  * Useful life: numbers like '5 years', '5 yrs', '5 saal', '10' -> '5' or '10'. If user declines ('no depreciation', 'none', 'cost only', 'skip') -> 'NONE'.\n"
    "  * Depreciation method: 'straight line', 'equal monthly', 'sl' -> 'STRAIGHT_LINE'; 'reducing balance', 'written down', 'rb', '15%' -> 'REDUCING_BALANCE'; 'none', 'cost only' -> 'NONE'.\n"
    "  * Salvage value: '0', 'zero', 'none', 'nil', 'scrap 0' -> '0'; or numeric amount.\n"
    "  * Payment method / type: 'bank', 'bank transfer', 'online', 'meezan', 'hbl', 'wire' -> 'BANK'; 'cash', 'cash in hand' -> 'CASH'; 'credit', 'pay later', 'bill', 'udhaar' -> 'CREDIT'.\n"
    "  * Amount: parse numeric values, e.g. '50000', '50k', 'Rs 50,000' -> '50000'.\n"
    "- ONLY output keys present in the ALLOWABLE FIELD ENDPOINTS list.\n"
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

    # Progressive Standard Schedule & Quick Decline Fast-Paths
    from app.conversational_manager import is_standard_schedule_acceptance
    is_multi_reply = any(sep in cleaned_reply for sep in (",", "\n", ";")) or bool(re.search(r"\b(?:paid|bank|transfer|cash|rs|pkr|\d{3,})\b", cleaned_reply, re.IGNORECASE))
    if not is_multi_reply and is_standard_schedule_acceptance(cleaned_reply):
        dep_fields = [f for f in ("useful_life_years", "depreciation_method", "salvage_value") if f in allowed_set]
        if dep_fields:
            res: Dict[str, str] = {}
            if "useful_life_years" in allowed_set:
                res["useful_life_years"] = "5"
            if "depreciation_method" in allowed_set:
                res["depreciation_method"] = "STRAIGHT_LINE"
            if "salvage_value" in allowed_set:
                res["salvage_value"] = "0"
            return res

    if any(k in cleaned_reply.lower() for k in ("decline depreciation", "no depreciation", "cost only", "skip depreciation")):
        res = {}
        if "useful_life_years" in allowed_set:
            res["useful_life_years"] = "NONE"
        if "depreciation_method" in allowed_set:
            res["depreciation_method"] = "NONE"
        if "salvage_value" in allowed_set:
            res["salvage_value"] = "0"
        return res

    if client is None:
        try:
            from app.ai_orchestrator import get_client
            client = get_client()
        except Exception as exc:
            log.warning("answer_parsing.get_client_failed", error=str(exc)[:160])
            client = None

    if client is None:
        # Hermetic / offline deterministic fallback parser
        fallback: Dict[str, str] = {}
        low = cleaned_reply.lower()
        if any(f in allowed_set for f in ("payment_type", "payment_method")):
            if any(k in low for k in ("bank", "transfer", "meezan", "hbl", "ubl", "online")):
                if "payment_method" in allowed_set:
                    fallback["payment_method"] = "BANK"
                if "payment_type" in allowed_set:
                    fallback["payment_type"] = "BANK"
            elif "cash" in low:
                if "payment_method" in allowed_set:
                    fallback["payment_method"] = "CASH"
                if "payment_type" in allowed_set:
                    fallback["payment_type"] = "CASH"
            elif any(k in low for k in ("credit", "on credit", "payable")):
                if "payment_method" in allowed_set:
                    fallback["payment_method"] = "CREDIT"
                if "payment_type" in allowed_set:
                    fallback["payment_type"] = "CREDIT"
        if "transaction_date" in allowed_set:
            if "today" in low:
                fallback["transaction_date"] = "today"
            elif "yesterday" in low:
                fallback["transaction_date"] = "yesterday"
            else:
                m_date = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b", low)
                if m_date:
                    fallback["transaction_date"] = m_date.group(1)
        if "useful_life_years" in allowed_set:
            m_yr = re.search(r"\b(\d+)\s*(?:years?|yrs?|saal)\b", low)
            if m_yr:
                fallback["useful_life_years"] = m_yr.group(1)
        if "depreciation_method" in allowed_set:
            if any(k in low for k in ("straight line", "slm", "equal")):
                fallback["depreciation_method"] = "STRAIGHT_LINE"
            elif any(k in low for k in ("reducing balance", "wdv", "written down")):
                fallback["depreciation_method"] = "REDUCING_BALANCE"
        if "salvage_value" in allowed_set:
            if any(k in low for k in ("zero", "nil", "none", "0")):
                fallback["salvage_value"] = "0"
            else:
                m_salv = re.search(r"\b(?:salvage|scrap|residual)\s*(?:of|is|was)?\s*(\d+)\b", low)
                if m_salv:
                    fallback["salvage_value"] = m_salv.group(1)
        if fallback:
            return fallback
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


# ---------------------------------------------------------------------------
# Out-of-Order Correction Detection & Absorption (Decision 3)
# ---------------------------------------------------------------------------

_CORRECTION_TRIGGER_RE = re.compile(
    r"\b(?:actually|correction|correct\s+that|change\s+(?:the\s+)?|wait[,.]?|not\s+[a-zA-Z0-9\s]+,\s*(?:make\s+it|use)|update\s+(?:the\s+)?|no,\s*(?:make\s+it|use)|wrong\s+[a-zA-Z]+|instead\s+of|make\s+it\s+[a-zA-Z0-9\s]+instead)\b",
    re.IGNORECASE,
)


def detect_out_of_order_correction(
    user_reply: str,
    current_entities: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Detect whether user input is an out-of-order correction and extract corrected fields.

    Handles seamless absorption of corrections mid-flow:
      - "Wait, change the amount to 280,000" -> {"amount": 280000.0, "total_amount": 280000.0}
      - "Actually paid via Meezan Bank, not cash" -> {"payment_method": "BANK", "payment_channel": "bank_transfer", "bank_name": "Meezan Bank"}
      - "Supplier is actually Dell Pakistan" -> {"supplier_name": "Dell Pakistan", "counterparty": "Dell Pakistan"}
      - "Make it 5 years straight line instead" -> {"useful_life_years": "5", "depreciation_method": "STRAIGHT_LINE"}
      - "Expense it instead of capitalizing" -> {"transaction_nature": "OPERATING_EXPENSE", "capitalization_decision": "EXPENSE"}
    """
    reply = (user_reply or "").strip()
    if not reply:
        return None

    if not _CORRECTION_TRIGGER_RE.search(reply):
        return None

    updates: Dict[str, Any] = {}
    reply_low = reply.lower()
    reply_up = reply.upper()

    # 1. Amount correction
    # Ignore numbers immediately followed by time units or count units (e.g. "5 years", "10 units")
    m_amt = re.search(
        r"(?:amount|cost|total|price|it\s+was|make\s+it)?\s*(?:to|is|was)?\s*(?:rs\.?|pkr|\$)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(k|thousand)?(?!\s*(?:years?|yrs?|saal|months?|days?|units?|pcs?|%))\b",
        reply,
        re.IGNORECASE,
    )
    if m_amt:
        raw_num = m_amt.group(1).replace(",", "")
        try:
            val = float(raw_num)
            if m_amt.group(2):
                val *= 1000.0
            # Only set amount if explicitly mentioning amount or value is a realistic financial number
            has_amt_context = any(w in reply_low for w in ("amount", "cost", "total", "price", "rs", "pkr", "$", "k", "thousand"))
            if val > 0 and (has_amt_context or val >= 50.0):
                updates["amount"] = val
                updates["total_amount"] = val
        except (ValueError, TypeError):
            pass

    # 2. Payment channel / bank correction
    if any(k in reply_low for k in ("bank", "transfer", "meezan", "hbl", "mcb", "ubl", "alfalah", "cash", "credit", "cheque", "check")):
        if any(k in reply_low for k in ("bank", "transfer", "online", "wire")):
            updates["payment_method"] = "BANK"
            updates["payment_channel"] = "bank_transfer"
        elif "cash" in reply_low:
            updates["payment_method"] = "CASH"
            updates["payment_channel"] = "cash"
        elif any(k in reply_low for k in ("credit", "payable", "udhaar", "pay later")):
            updates["payment_method"] = "CREDIT"
            updates["payment_channel"] = "credit"
        elif any(k in reply_low for k in ("cheque", "check")):
            updates["payment_method"] = "CHEQUE"
            updates["payment_channel"] = "cheque"

        # Check bank name
        for b_name in ("Meezan Bank", "Meezan", "HBL", "MCB", "UBL", "Bank Alfalah", "Alfalah", "Standard Chartered", "Allied Bank", "Faysal Bank"):
            if b_name.lower() in reply_low:
                updates["bank_name"] = b_name
                updates["payment_method"] = "BANK"
                updates["payment_channel"] = "bank_transfer"
                break

    # 3. Transaction nature / capitalization correction
    if any(k in reply_low for k in ("expense", "operating expense", "p&l")):
        updates["transaction_nature"] = "OPERATING_EXPENSE"
        updates["capitalization_decision"] = "EXPENSE"
    elif any(k in reply_low for k in ("capitalize", "fixed asset", "asset")):
        updates["transaction_nature"] = "FIXED_ASSET"
        updates["capitalization_decision"] = "CAPITALIZE"

    # 4. Useful life / depreciation correction
    m_life = re.search(r"\b(\d+)\s*(?:years|year|saal|yrs|yr)\b", reply_low)
    if m_life:
        updates["useful_life_years"] = m_life.group(1)
    if "straight line" in reply_low or "sl" in reply_low:
        updates["depreciation_method"] = "STRAIGHT_LINE"
    elif "reducing balance" in reply_low or "rb" in reply_low:
        updates["depreciation_method"] = "REDUCING_BALANCE"

    # 5. Supplier / Counterparty correction
    m_supp = re.search(
        r"(?:supplier|vendor|from|party)\s+(?:is\s+)?(?:actually\s+)?([A-Za-z0-9\s&.-]+?)(?:\s*(?:not|,|\.|$))",
        reply,
        re.IGNORECASE,
    )
    if m_supp:
        supp_name = m_supp.group(1).strip()
        if supp_name and supp_name.lower() not in ("cash", "bank", "yesterday", "today"):
            updates["supplier_name"] = supp_name
            updates["counterparty"] = supp_name

    # 6. Date correction
    if any(k in reply_low for k in ("yesterday", "today")) or re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", reply):
        from app.date_parser import parse_transaction_date
        d_res = parse_transaction_date(reply)
        if d_res.ok and d_res.iso_date:
            updates["transaction_date"] = d_res.iso_date
            updates["expense_date"] = d_res.iso_date

    return updates if updates else None

