"""Stage 15 - BOUNDED plan-versus-treatment review (advisory, may BLOCK).

Placed at the PLAN-TO-TREATMENT boundary (after materialization, before
execution) as an INDEPENDENT second reader of the same deterministic facts:

* WHAT it reads: the confirmed facts from stages 1-8 (intent, nature +
  its source, settlement channel, party, item literals, amount, date) and
  the canonical tool calls about to execute;
* WHAT it may do: FLAG contradictions (e.g. "classified INVENTORY but the
  plan carries no nature/items", "CREDIT settlement but the plan pays cash")
  and, for material-fact gaps, propose the blocking question;
* WHAT it may NEVER do: invent facts, modify arguments, choose accounts, or
  override the accounting engine.  The deterministic materializer, the
  engine's nature routing, and the posting invariant remain AUTHORITATIVE
  even when this review never runs (MODEL_ABSENT / disabled / timeout - as
  in production 2026-10-18, the review must be pure defense-in-depth).

Every outcome is audited: ran / skipped_disabled / skipped_unavailable /
rejected / flagged.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

_CONTRADICTION_KEYS = frozenset(
    {"nature_vs_plan", "settlement_vs_plan", "amount_vs_plan", "other"}
)

_INSTRUCTION = (
    "You are an accounting treatment REVIEWER. You receive CONFIRMED FACTS "
    "and a CANONICAL PLAN (tool calls about to execute). Output STRICT JSON: "
    '{"contradictions": [{"kind": "nature_vs_plan|settlement_vs_plan|'
    'amount_vs_plan|other", "why": "<one sentence>"}], '
    '"missing_material_facts": ["<fact name>"]}. '
    "Flag ONLY direct contradictions between the confirmed facts and the "
    "plan (e.g. nature INVENTORY but the plan carries no nature or no item "
    "lines; CREDIT but the plan settles cash now; a total that differs from "
    "the confirmed amount). Never invent facts. Never suggest accounts. If "
    "the plan is consistent with the facts, output empty lists."
)


@dataclass
class TreatmentReview:
    ran: bool = False          # the model actually answered
    ok: bool = True            # no blocking contradiction found
    blocked: bool = False      # execution must stop with a question
    question: str = ""
    flags: List[Dict[str, str]] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    audit: Dict[str, Any] = field(default_factory=dict)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _validate_reply(payload: Any) -> tuple:
    """Schema-validate: contradictions must carry a known kind + why."""
    if not isinstance(payload, dict):
        return None, ["reply is not a JSON object"]
    flags: List[Dict[str, str]] = []
    failures: List[str] = []
    raw_flags = payload.get("contradictions")
    if isinstance(raw_flags, list):
        for item in raw_flags:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip()
            why = str(item.get("why") or "").strip()[:300]
            if kind in _CONTRADICTION_KEYS and why:
                flags.append({"kind": kind, "why": why})
    missing = [
        str(m).strip()[:80]
        for m in (payload.get("missing_material_facts") or [])
        if str(m).strip()
    ][:6]
    return {"flags": flags, "missing": missing}, failures


def _facts_block(
    *,
    intent: str,
    classification: Any,
    entities: Dict[str, Any],
    calls: Any,
) -> str:
    nature = str(getattr(classification, "transaction_nature", "") or "")
    source = str(getattr(classification, "source", "") or "")
    facts = {
        "intent": intent,
        "transaction_nature": nature or None,
        "nature_source": source or None,
        "payment_method": entities.get("payment_method"),
        "party": entities.get("supplier_name") or entities.get("customer_name"),
        "item_description": entities.get("item_description"),
        "quantity": entities.get("quantity") or entities.get("item_quantity"),
        "amount": entities.get("amount"),
        "transaction_date": entities.get("transaction_date"),
    }
    plan = [
        {
            "tool": getattr(call, "tool_name", ""),
            "arguments": {
                k: v
                for k, v in (getattr(call, "arguments", None) or {}).items()
                if k
                in (
                    "transaction_nature", "payment_method", "items", "total",
                    "subtotal", "amount", "notes", "bill_date",
                )
            },
        }
        for call in (calls or [])
    ]


async def review_plan_treatment(
    *,
    organization_id: uuid.UUID,
    intent: str,
    classification: Any,
    entities: Dict[str, Any],
    calls: Any,
    client: Any = None,
    timeout: Optional[float] = None,
) -> TreatmentReview:
    """The bounded review round-trip.  NEVER raises; degrades to ok=True.

    A reply that fails validation is REJECTED (ok, not blocked) - a broken
    model response must never stop a correct deterministic run; the posting
    invariant still guards the ledger.
    """
    from app.config import get_settings

    settings = get_settings()
    review = TreatmentReview(
        audit={
            "stage": "treatment_review",
            "llm": "skipped_disabled",
            "flags": 0,
            "missing": [],
        }
    )
    if not getattr(settings, "treatment_review_enabled", False):
        return review
    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()
        prompt = (
            f"{_INSTRUCTION}\n\n{_facts_block(intent=intent, classification=classification, entities=entities, calls=calls)}"
        )
        raw = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt[:6000]),
            timeout=timeout or getattr(settings, "treatment_review_timeout", 10.0),
        )
    except Exception as exc:  # noqa: BLE001 - degrade: correctness unaffected
        review.audit["llm"] = "skipped_unavailable"
        review.audit["error"] = str(exc)[:160]
        log.warning("treatment_review.unavailable", error=str(exc)[:160])
        return review
    payload = _extract_json(str(raw or ""))
    if payload is None:
        review.audit["llm"] = "rejected"
        log.warning("treatment_review.reject", reason="unparseable reply")
        return review
    parsed, failures = _validate_reply(payload)
    if parsed is None or failures:
        review.audit["llm"] = "rejected"
        review.audit["validation_failures"] = failures
        log.warning("treatment_review.validation", failures=failures)
        return review
    review.ran = True
    review.flags = parsed["flags"]
    review.missing = parsed["missing"]
    review.audit["llm"] = "flagged" if review.flags else "ok"
    review.audit["flags"] = len(review.flags)
    review.audit["missing"] = review.missing
    if review.flags:
        # BLOCKING is the ONLY authority this module has.  The question names
        # the contradiction; it never resolves it, never rewrites the plan.
        review.ok = False
        review.blocked = True
        review.question = (
            "An accounting review flagged a contradiction between the "
            "confirmed facts and the planned recording before anything was "
            "posted: "
            + "; ".join(f"[{f['kind']}] {f['why']}" for f in review.flags[:3])
            + ". Please confirm or correct the details so the right "
            "treatment can be recorded (nothing has been written)."
        )
    return review

    return (
        f"CONFIRMED FACTS:\n{json.dumps(facts, default=str)}\n"
        f"CANONICAL PLAN:\n{json.dumps(plan, default=str)}"
    )
