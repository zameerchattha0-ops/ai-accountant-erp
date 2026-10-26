"""Stage 2 — SHORT LLM extraction of the PRELIMINARY facts (literal only).

Production motivation (2026-10-18): the deterministic literal regexes are
template-bound ("tables", "some dozen", "a couple of ..." slip through), and a
missed literal later starves the grounded treatment binding of its facts.

AUTHORITY SPLIT (2026-10-20, inversion after the umer-autos failures):
* LLM-AUTHORITATIVE - party (supplier_name / customer_name),
  item_description, quantity and reason.  When the model states a valid
  value it WINS over the regex (which is only the FALLBACK).  These are the
  interpretation-heavy fields where the regex swallowed the party into the
  item ("return to umer autos against damaged motorbikes").
* DETERMINISTIC-FIRST - amount and transaction_date.  A literal the rules
  extracted still wins; the model only FILLS their gaps.  A hallucinated
  figure or date is the one failure worse than a missed one, so the regex
  stays authoritative there and the model never overwrites it.

CONTRACT - extraction, never interpretation (this module may NOT):
* conclude a transaction NATURE (inventory vs expense), compute a unit price,
  or decide any account - those belong to the later accounting stages;
* invent values: every field must be literally present in the user's words.
An INVALID model value for a CRITICAL field (quantity) is never assumed: the
failure is RECORDED in the audit and the field stays unfilled, so a required
quantity still triggers the materializer's clarification block downstream.
The deterministic extraction always ships - disabled/unavailable/invalid
model output degrades to it, never blocks a turn.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

log = structlog.get_logger(__name__)

_PAYMENT_CHANNELS = frozenset(
    {"CASH", "CREDIT", "BANK", "CARD", "TRANSFER", "CHEQUE", "CHECK"}
)
_AREAS = frozenset({
    "fixed_assets", "revenue", "receivables", "payables", "expenses",
    "purchases", "loans", "equity", "tax", "bank", "cash",
})
_DOC_REF_RE = re.compile(r"\b(?:INV|BILL|RCPT|PAY|PO|JV)[-/ \t]?\d{2,}\b", re.I)

_INSTRUCTION = (
    'You are a LITERAL extractor for an accounting intake. Output STRICT JSON '
    'only, matching EXACTLY this schema: {"amount": <number|null>, '
    '"transaction_date": "<YYYY-MM-DD>"|null, "item_description": "<string>"'
    '|null, "quantity": <number|null>, "payment_channel": '
    '"<CASH|CREDIT|BANK|CARD|TRANSFER|CHEQUE>"|null, "supplier_name": '
    '"<string>"|null, "customer_name": "<string>"|null, "reason": "<string>"'
    '|null, "bill_number": "<PUR-000013 style token>"|null, "named_parties": '
    '["<string>", ...] (max 5), "document_reference": "<INV-000012 style '
    'token>"|null, "invoice_number": "<digits>"|null, '
    '"provisional_intent_hint": "<canonical intent or null>", '
    '"candidate_subject_areas": ["<one of: fixed_assets,revenue,'
    'receivables,payables,expenses,purchases,loans,equity,tax,bank,cash>", '
    '..., "line_items": [{"description": "<item or service name>", "quantity": <number|null>, "unit_price": <number|null>, "total_amount": <number|null>}]|null, "account_name": "<string>"|null, "account_type": "<ASSET|LIABILITY|EQUITY|REVENUE|EXPENSE>"|null, "account_code": "<string>"|null, "parent_account_name": "<string>"|null, "product_name": "<string>"|null, "service_name": "<string>"|null, "sales_price": <number|null>, "bank_name": "<string>"|null, "employee_name": "<string>"|null, "project_name": "<string>"|null} RULES: extract ONLY values the user LITERALLY stated; null when '
    'absent; NEVER infer, compute, or guess (e.g. no quantity unless '
    'stated); NEVER decide accounting treatment or accounts; keep the '
    "request's own wording for items and parties. PARTY vs ITEM (critical): "
    "the COUNTERPARTY (the business you bought FROM / sold TO / returned "
    "goods TO) is a PARTY and goes in supplier_name (you bought or returned "
    "to them) or customer_name (you sold or received from them) — it is "
    "NEVER part of item_description. item_description is only the GOODS "
    "(e.g. 'return to umer autos against damaged motorbikes' -> "
    "supplier_name='umer autos', item_description='damaged motorbikes'). "
    "MULTI-ITEM EXTRACTION (CRITICAL): When a request mentions multiple items or goods "
    "(e.g. '2 tables and 3 chairs from Shabbir Furnitures', '5 laptops at 100000 and 10 keyboards at 2000', "
    "'bought cement bags and steel rods'), extract each distinct item as an object in 'line_items' with "
    "description, quantity (as a number, e.g. 2, 3), unit_price (if stated, else null), and total_amount (if stated, else null). "
    "Also set item_description to a summary such as 'tables / chairs'. "
    "reason is the user's own stated cause for a return ('damaged', "
    "'wrong item delivered'), null when not stated. "
    "ERP OPERATIONS & SETUP: For tasks across ERP modules, intelligently extract the exact names stated by the user: "
    "account_name (Chart of Accounts ledger title), account_type (ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE if stated or clear), "
    "account_code (numeric code), parent_account_name (heading/grouping), product_name / service_name, sales_price, "
    "bank_name (e.g. Meezan Bank, HBL), employee_name (personnel full name), project_name (project title). null when absent."
)

# Pronouns / fillers that are never a business counterparty (mirrors the
# planner's party guard so a model echo of "we"/"them"/"the supplier" can
# never reach the party gate).
_NOT_A_PARTY = frozenset({
    "the", "a", "an", "it", "us", "we", "you", "they", "i", "me", "him",
    "her", "them", "our", "your", "their", "supplier", "the supplier",
    "customer", "the customer", "vendor", "client", "party",
})


def _plausible_party(value: str) -> bool:
    """Shape-only party guard: a real, non-numeric, non-pronoun name.

    Grounding against the live supplier/customer master happens DOWNSTREAM
    (the party gate); this only rejects obvious non-names so a model echo of
    a pronoun or an amount/date shape never reaches that gate.
    """
    text = (value or "").strip()
    if len(text) < 2:
        return False
    if text.lower().strip(".,") in _NOT_A_PARTY:
        return False
    if re.fullmatch(r"(?:rs\.?|pkr|pk)?\s*[\d,]+(?:\.\d+)?", text, re.IGNORECASE):
        return False  # an amount shape is not a name
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return False  # a date shape is not a name
    return True


def _validate(payload: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Schema-validate the model reply. Returns (clean_fields, failures)."""
    if not isinstance(payload, dict):
        return {}, ["reply is not a JSON object"]
    clean: Dict[str, Any] = {}
    failures: List[str] = []

    def _num(key: str) -> None:
        raw = payload.get(key)
        if raw is None:
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            failures.append(f"{key}: not a number ({raw!r})")
            return
        if value <= 0:
            failures.append(f"{key}: not a positive number ({raw!r})")
            return
        if key == "quantity" and value != int(value):
            failures.append(f"{key}: quantity must be a whole number ({raw!r})")
            return
        clean[key] = int(value) if key == "quantity" else value

    _num("amount")
    _num("quantity")
    date = payload.get("transaction_date")
    if date is not None:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
            clean["transaction_date"] = str(date)
        else:
            failures.append(f"transaction_date: not ISO ({date!r})")
            log.warning("authority_split.intercepted", field="transaction_date", reason="untraceable_date", raw_value=str(date)[:40])
    desc = payload.get("item_description")
    if desc is not None and str(desc).strip():
        clean["item_description"] = str(desc).strip()[:120]
    # LLM-AUTHORITATIVE party + reason + bill (2026-10-20): these are the
    # interpretation-heavy fields.  Validation here is SHAPE ONLY (a real,
    # non-numeric, party-like string); the party is GROUNDED against the live
    # supplier/customer master downstream, never trusted blindly.  A captured
    # amount/date shape or pronoun is rejected so it can never reach a gate.
    for party_key in ("supplier_name", "customer_name"):
        raw_party = payload.get(party_key)
        if raw_party is not None and str(raw_party).strip():
            party = str(raw_party).strip()[:80]
            if _plausible_party(party):
                clean[party_key] = party
            else:
                failures.append(f"{party_key}: not a plausible party ({raw_party!r})")
    reason = payload.get("reason")
    if reason is not None and str(reason).strip():
        clean["reason"] = str(reason).strip()[:160]
    bill = payload.get("bill_number")
    if bill is not None and _DOC_REF_RE.fullmatch(str(bill).strip()):
        clean["bill_number"] = str(bill).strip()
    channel = payload.get("payment_channel")
    if channel is not None:
        norm = str(channel).strip().upper()
        if norm in _PAYMENT_CHANNELS:
            clean["payment_channel"] = norm
        else:
            failures.append(f"payment_channel: outside vocabulary ({channel!r})")
    parties = payload.get("named_parties")
    if isinstance(parties, list):
        kept = [str(p).strip()[:80] for p in parties[:5] if str(p).strip()]
        if kept:
            clean["named_parties"] = kept
    ref = payload.get("document_reference")
    if ref is not None and _DOC_REF_RE.fullmatch(str(ref).strip()):
        clean["document_reference"] = str(ref).strip()
    inv = payload.get("invoice_number")
    if inv is not None and re.fullmatch(r"\d{1,6}", str(inv).strip()):
        clean["invoice_number"] = str(inv).strip()
    hint = payload.get("provisional_intent_hint")
    if hint:
        try:
            from app.accounting_vocabulary import is_canonical_intent

            if is_canonical_intent(str(hint).strip().lower()):
                clean["provisional_intent_hint"] = str(hint).strip().lower()
        except Exception:  # noqa: BLE001 - vocabulary unavailable -> drop
            pass
    areas = payload.get("candidate_subject_areas")
    if isinstance(areas, list):
        kept_areas = [str(a).strip() for a in areas if str(a).strip() in _AREAS]
        if kept_areas:
            clean["candidate_subject_areas"] = kept_areas[:4]
    raw_lines = payload.get("line_items")
    if isinstance(raw_lines, list) and raw_lines:
        valid_lines = []
        for itm in raw_lines:
            if not isinstance(itm, dict):
                continue
            desc = str(itm.get("description") or "").strip()
            if not desc:
                continue
            clean_item: Dict[str, Any] = {"description": desc[:120]}
            qty = itm.get("quantity")
            if qty is not None:
                try:
                    q_num = float(qty)
                    clean_item["quantity"] = int(q_num) if q_num.is_integer() else q_num
                except (ValueError, TypeError):
                    pass
            unit_price = itm.get("unit_price")
            if unit_price is not None:
                try:
                    clean_item["unit_price"] = float(unit_price)
                except (ValueError, TypeError):
                    pass
            total_amt = itm.get("total_amount")
            if total_amt is not None:
                try:
                    clean_item["total_amount"] = float(total_amt)
                except (ValueError, TypeError):
                    pass
            valid_lines.append(clean_item)
        if valid_lines:
            clean["line_items"] = valid_lines
    for str_key in (
        "account_name", "account_code", "parent_account_name",
        "product_name", "service_name", "bank_name", "employee_name",
        "project_name", "template_name",
    ):
        v = payload.get(str_key)
        if v is not None and str(v).strip():
            clean[str_key] = str(v).strip()[:120]

    raw_acct_type = payload.get("account_type")
    if raw_acct_type is not None:
        at = str(raw_acct_type).strip().upper()
        if at in ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"):
            clean["account_type"] = at
        elif "EXPENSE" in at:
            clean["account_type"] = "EXPENSE"
        elif "ASSET" in at:
            clean["account_type"] = "ASSET"
        elif "LIABILIT" in at:
            clean["account_type"] = "LIABILITY"
        elif "REVENUE" in at or "INCOME" in at:
            clean["account_type"] = "REVENUE"
        elif "EQUITY" in at:
            clean["account_type"] = "EQUITY"

    _num("sales_price")

    return clean, failures


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def enrich_preliminary(
    *,
    user_message: str,
    preliminary: Dict[str, Any],
    client: Any = None,
    timeout: Optional[float] = None,
    org_context: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Merge the model's gap-filling literals into the deterministic result.

    Returns ``(preliminary, audit)``.  ``audit`` records whether the model
    ran/skipped/failed and every VALIDATION FAILURE - an invalid critical
    value (quantity) is never silently assumed.

    ``org_context`` (2026-10-19, per-business intelligence) is the live
    org-scoped profile block — it lets the model recognise THIS business's
    invoice numbers, parties and stock items instead of guessing generically.
    """
    from app.config import get_settings

    settings = get_settings()
    audit: Dict[str, Any] = {
        "stage": "preliminary_extraction",
        "llm": "skipped_disabled",
        "filled": [],
        "validation_failures": [],
    }
    if not getattr(settings, "llm_preliminary_extraction_enabled", False):
        return preliminary, audit
    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()
        raw = await asyncio.wait_for(
            client.generate_text_light(
                prompt=(
                    f"{_INSTRUCTION}\n"
                    # PER-BUSINESS CONTEXT (2026-10-19): the live profile
                    # precedes the message so reference numbers ("INV-…"),
                    # parties and stock items of THIS org are recognisable.
                    f"{org_context}\n\n"
                    f"USER MESSAGE:\n{user_message[:2000]}"
                )
            ),
            timeout=timeout
            or getattr(settings, "llm_preliminary_extraction_timeout", 8.0),
        )
    except Exception as exc:  # noqa: BLE001 - degrade to deterministic
        audit["llm"] = "skipped_unavailable"
        audit["error"] = str(exc)[:160]
        log.warning("llm_extraction.unavailable", error=str(exc)[:160])
        return preliminary, audit
    payload = _extract_json(str(raw or ""))
    if payload is None:
        audit["llm"] = "rejected"
        audit["validation_failures"] = ["unparseable reply"]
        log.warning("llm_extraction.reject", reason="unparseable reply")
        return preliminary, audit
    clean, failures = _validate(payload)
    audit["validation_failures"] = failures
    if failures:
        log.warning("llm_extraction.validation", failures=failures)
    # AUTHORITY-SPLIT MERGE (2026-10-20 inversion).  Contractual keys
    # (label/original_request/note/today) stay Python-owned and untouched.
    #
    #   LLM-AUTHORITATIVE (party / item / quantity / reason): the model's
    #     valid value WINS over the regex — these are the interpretation-
    #     heavy fields where a template regex swallowed the party into the
    #     item.  The regex runs only as the FALLBACK when the model omits
    #     them or is disabled/unavailable/invalid.
    #   DETERMINISTIC-FIRST (amount / date / payment_channel / references):
    #     a literal the rules extracted still wins (a hallucinated figure or
    #     date is worse than a missed one); the model only FILLS their gaps.
    merged = dict(preliminary)
    literals = dict(merged.get("literals") or {})
    filled: List[str] = []
    overridden: List[str] = []

    # --- deterministic-first: regex wins, model fills gaps only ---
    for key in (
        "amount", "transaction_date", "payment_channel",
        "document_reference", "invoice_number", "bill_number",
    ):
        if key in clean and literals.get(key) is not None and literals.get(key) != clean[key]:
            reason = "amount_regex_mismatch" if key == "amount" else ("untraceable_date" if key == "transaction_date" else "deterministic_override")
            log.warning(
                "authority_split.intercepted",
                field=key,
                reason=reason,
                deterministic=literals.get(key),
                llm=clean[key],
            )
        elif key in clean and literals.get(key) is None:
            literals[key] = clean[key]
            filled.append(key)

    # --- LLM-authoritative: model wins, regex is the fallback ---
    if "line_items" in clean and clean["line_items"]:
        prior_lines = literals.get("line_items")
        literals["line_items"] = clean["line_items"]
        if not prior_lines:
            filled.append("line_items")
        elif prior_lines != clean["line_items"]:
            overridden.append("line_items")
    for key in ("item_description", "quantity", "reason"):
        if key not in clean:
            continue
        prior = literals.get(key)
        literals[key] = clean[key]
        if prior is None:
            filled.append(key)
        elif prior != clean[key]:
            overridden.append(key)

    # Party (supplier/customer) is LLM-authoritative and is written straight
    # into the literals so the prefill -> planner path can carry it to the
    # party gate (which grounds it against the live master).
    for key in (
        "supplier_name", "customer_name", "account_name", "account_type",
        "account_code", "parent_account_name", "product_name", "service_name",
        "sales_price", "bank_name", "employee_name", "project_name", "template_name",
    ):
        if key in clean and clean[key]:
            prior = literals.get(key)
            literals[key] = clean[key]
            if prior is None:
                filled.append(key)
            elif prior != clean[key]:
                overridden.append(key)

    if clean.get("named_parties") and not literals.get(
        "named_parties_or_items_candidates"
    ):
        literals["named_parties_or_items_candidates"] = clean["named_parties"]
        filled.append("named_parties_or_items_candidates")
    merged["literals"] = literals
    if overridden:
        audit["overrode_regex"] = overridden
        log.info("llm_extraction.overrode_regex", fields=overridden)
    if clean.get("candidate_subject_areas"):
        areas = list(dict.fromkeys(
            list(merged.get("candidate_subject_areas") or [])
            + clean["candidate_subject_areas"]
        ))
        merged["candidate_subject_areas"] = areas
    if clean.get("provisional_intent_hint"):
        merged["provisional_intent_hint"] = clean["provisional_intent_hint"]
        filled.append("provisional_intent_hint")
    audit["llm"] = "ok"
    audit["filled"] = filled
    return merged, audit

