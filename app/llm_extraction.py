"""Stage 2 — SHORT LLM enrichment of the PRELIMINARY EXTRACTION (literal only).

Production motivation (2026-10-18): the deterministic literal regexes are
template-bound ("tables", "some dozen", "a couple of ..." slip through), and a
missed literal later starves the grounded treatment binding of its facts.

CONTRACT - extraction, never interpretation (this module may NOT):
* conclude a transaction NATURE (inventory vs expense), compute a unit price,
  or decide any account - those belong to the later accounting stages;
* overwrite a literal the deterministic pass already extracted (the rules are
  the AUTHORITATIVE first pass; the model only FILLS GAPS);
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
    '"<CASH|CREDIT|BANK|CARD|TRANSFER|CHEQUE>"|null, "named_parties": '
    '["<string>", ...] (max 5), "document_reference": "<INV-000012 style '
    'token>"|null, "invoice_number": "<digits>"|null, '
    '"provisional_intent_hint": "<canonical intent or null>", '
    '"candidate_subject_areas": ["<one of: fixed_assets,revenue,'
    'receivables,payables,expenses,purchases,loans,equity,tax,bank,cash>", '
    '...]} RULES: extract ONLY values the user LITERALLY stated; null when '
    'absent; NEVER infer, compute, or guess (e.g. no quantity unless '
    'stated); NEVER decide accounting treatment or accounts; keep the '
    "request's own wording for items and parties."
)


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
    desc = payload.get("item_description")
    if desc is not None and str(desc).strip():
        clean["item_description"] = str(desc).strip()[:120]
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
    # DETERMINISTIC-FIRST MERGE: the rules' literals are authoritative; the
    # model only fills gaps.  Contractual keys (label/original_request/note/
    # today) are Python-owned and never touched.
    merged = dict(preliminary)
    literals = dict(merged.get("literals") or {})
    filled: List[str] = []
    for key in (
        "amount", "transaction_date", "item_description", "quantity",
        "payment_channel", "document_reference",
        "invoice_number", "bill_number", "reason",
    ):
        if key in clean and literals.get(key) is None:
            literals[key] = clean[key]
            filled.append(key)
    if clean.get("named_parties") and not literals.get(
        "named_parties_or_items_candidates"
    ):
        literals["named_parties_or_items_candidates"] = clean["named_parties"]
        filled.append("named_parties_or_items_candidates")
    merged["literals"] = literals
    if clean.get("candidate_subject_areas"):
        areas = list(dict.fromkeys(
            list(merged.get("candidate_subject_areas") or [])
            + clean["candidate_subject_areas"]
        ))
        merged["candidate_subject_areas"] = areas
    if clean.get("provisional_intent_hint") and not merged.get(
        "provisional_intent_hint"
    ):
        merged["provisional_intent_hint"] = clean["provisional_intent_hint"]
        filled.append("provisional_intent_hint")
    audit["llm"] = "ok"
    audit["filled"] = filled
    return merged, audit

