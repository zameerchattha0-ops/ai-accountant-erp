"""
ERP AI Agent — Document / Receipt / Invoice Vision Extraction
==============================================================
Turns an uploaded document image into STRUCTURED extraction data via the
verified vision-capable Qwen chain (qwen3-vl-plus → qwen3-vl-flash).

Architectural rules:
* The vision model is an EXTRACTION aid only — NEVER the accounting
  authority. Its output is injected as ERP Agent context; the agent,
  planner, classifier, validator and accounting engine keep full control
  of what the document MEANS operationally.
* Extraction must preserve uncertainty: unreadable fields stay null and
  are listed in ``uncertainties`` so the agent can ask the user. Values
  are never invented or "corrected".
* No permanent storage: images are processed in-memory per request.
* Capability routing: only the vision chain is used; a model that
  returns unusable output is skipped in favour of the next one.
* Document contents are never logged — only metadata (sizes, model,
  confidence) reaches the log.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any, Dict, List, Optional

import structlog

from app.models.schemas import AttachmentRef
from app.qwen_client import ProviderError

log = structlog.get_logger(__name__)

# --- Validation limits -------------------------------------------------------
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024  # 8 MB per document (decoded)
MAX_DOCUMENTS_PER_REQUEST = 3
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


class DocumentValidationError(Exception):
    """Raised when an attachment cannot be used (user-fixable problem)."""


_EXTRACTION_SYSTEM_PROMPT = """\
You are a precise document-data extraction engine for an accounting ERP.
Extract ONLY what is visibly present in the document. Rules:

1. NEVER invent, guess or "correct" values. If a field is unreadable or
   absent, set it to null.
2. Amounts must be transcribed exactly as printed (do not reformat,
   re-round or convert currency).
3. Dates must be normalised to ISO YYYY-MM-DD ONLY when the printed date
   is unambiguous; otherwise null.
4. Every field you could not read confidently MUST be listed in
   "uncertainties" with a short reason.
5. Reply with a SINGLE JSON object — no prose, no markdown fences.

JSON contract:
{
  "document_type": "invoice" | "receipt" | "bill" | "quotation" | "other" | "unknown",
  "supplier": {"name": string|null},
  "customer": {"name": string|null},
  "invoice_number": string|null,
  "document_date": "YYYY-MM-DD"|null,
  "currency": string|null,
  "line_items": [
    {"description": string, "quantity": number|null,
     "unit_price": number|null, "amount": number|null}
  ],
  "subtotal": number|null,
  "tax_amount": number|null,
  "discount": number|null,
  "total": number|null,
  "payment_method_hint": string|null,
  "confidence": number,
  "uncertainties": [string]
}
"""


def validate_attachment(att: AttachmentRef) -> str:
    """Validate and decode an inline attachment. Returns the data URI.

    Raises DocumentValidationError for user-fixable problems (wrong type,
    too large, corrupt base64). These are ERP/application errors — they
    must NEVER trigger provider fallback.
    """
    if not att.data_base64:
        raise DocumentValidationError(
            f"'{att.file_name}' has no uploaded content (only a preview "
            "reference). Please re-attach the file."
        )
    if (att.mime_type or "").lower() not in ALLOWED_MIME_TYPES:
        raise DocumentValidationError(
            f"'{att.file_name}' is of type '{att.mime_type or 'unknown'}'. "
            "Only PNG, JPEG or WEBP images can be processed."
        )
    try:
        base64.b64decode(att.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentValidationError(
            f"'{att.file_name}' could not be decoded (corrupt upload)."
        ) from exc
    raw_len = len(att.data_base64) * 3 // 4
    if raw_len > MAX_DOCUMENT_BYTES:
        raise DocumentValidationError(
            f"'{att.file_name}' is larger than "
            f"{MAX_DOCUMENT_BYTES // (1024 * 1024)} MB."
        )
    return f"data:{att.mime_type};base64,{att.data_base64}"


def _parse_extraction_json(raw: str) -> Dict[str, Any]:
    """Parse the model's JSON reply, tolerating markdown fences."""
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    # Some models prepend prose before the JSON object — take the first {…}.
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in model reply")
        text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("extraction reply is not a JSON object")
    return data


async def extract_document(
    *,
    orchestrator: Any,
    file_name: str,
    data_uri: str,
) -> Dict[str, Any]:
    """Run structured extraction across the vision chain.

    Tries each vision-capable model in order. Provider errors AND
    unusable replies (unparseable JSON) move to the next model — the
    document still needs processing, so this is provider-level fallback,
    not ERP failure.

    Returns the extraction dict plus ``_model`` metadata.
    """
    candidates = orchestrator._candidate_providers(requires_vision=True)
    if not candidates:
        raise DocumentValidationError(
            "No vision-capable AI model is configured for document extraction."
        )

    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {
                    "type": "text",
                    "text": (
                        "Extract this document into the JSON contract. "
                        "Preserve uncertainty; never invent values."
                    ),
                },
            ],
        },
    ]

    provider_errors: List[str] = []
    for candidate in candidates:
        model = candidate["model"]
        try:
            client = candidate["factory"]()
            raw = await client.chat_raw(messages=messages)
            data = _parse_extraction_json(raw)
            data["_model"] = model
            log.info(
                "document_extractor.success",
                model=model,
                confidence=data.get("confidence"),
                uncertainties=len(data.get("uncertainties") or []),
                attempts=len(provider_errors) + 1,
            )
            return data
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            provider_errors.append(f"{model}: {exc}")
            log.warning(
                "document_extractor.model_failed",
                model=model,
                attempt=len(provider_errors),
                fallback_reason=str(exc)[:200],
            )

    raise ProviderError(
        "All vision models failed to extract the document. "
        + "; ".join(provider_errors)
    )


def extraction_to_context_text(data: Dict[str, Any]) -> str:
    """Render extraction data as compact, factual context for the ERP Agent.

    The agent sees EXACTLY what was read — including uncertainties — so it
    can decide what is material and ask the user only when necessary.
    """
    lines: List[str] = []
    doc_type = data.get("document_type") or "unknown"
    lines.append(f"Document type: {doc_type}")
    for role in ("supplier", "customer"):
        party = data.get(role) or {}
        if party.get("name"):
            lines.append(f"{role.capitalize()}: {party['name']}")
    for field, label in (
        ("invoice_number", "Document number"),
        ("document_date", "Date"),
        ("currency", "Currency"),
        ("subtotal", "Subtotal"),
        ("tax_amount", "Tax"),
        ("discount", "Discount"),
        ("total", "Total"),
        ("payment_method_hint", "Payment hint"),
    ):
        value = data.get(field)
        if value not in (None, ""):
            lines.append(f"{label}: {value}")
    items = data.get("line_items") or []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        parts = [str(item.get("description") or f"item {i}")]
        if item.get("quantity") is not None:
            parts.append(f"qty {item['quantity']}")
        if item.get("unit_price") is not None:
            parts.append(f"unit {item['unit_price']}")
        if item.get("amount") is not None:
            parts.append(f"amount {item['amount']}")
        lines.append(f"Line {i}: " + " | ".join(parts))
    uncertainties = data.get("uncertainties") or []
    if uncertainties:
        lines.append(
            "Unreadable/uncertain fields (ask the user only if materially "
            "necessary): " + "; ".join(str(u) for u in uncertainties)
        )
    if data.get("confidence") is not None:
        lines.append(f"Extraction confidence: {data.get('confidence')}")
    return "\n".join(lines)


async def extract_attachments(
    attachments: Optional[List[AttachmentRef]],
    *,
    orchestrator: Any,
) -> Optional[str]:
    """Validate + extract all attachments; returns a context text block.

    Returns None when there are no processable attachments.
    Raises DocumentValidationError for user-fixable upload problems.
    """
    if not attachments:
        return None
    if len(attachments) > MAX_DOCUMENTS_PER_REQUEST:
        raise DocumentValidationError(
            f"Please attach at most {MAX_DOCUMENTS_PER_REQUEST} documents "
            "per message."
        )

    blocks: List[str] = []
    for idx, att in enumerate(attachments, start=1):
        data_uri = validate_attachment(att)
        data = await extract_document(
            orchestrator=orchestrator,
            file_name=att.file_name,
            data_uri=data_uri,
        )
        body = extraction_to_context_text(data)
        blocks.append(f"[Document {idx}: {att.file_name}]\n{body}")

    return "\n\n".join(blocks)
