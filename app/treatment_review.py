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
from typing import Any, Dict, List, Optional, Tuple

import structlog

log = structlog.get_logger(__name__)

_CONTRADICTION_KEYS = frozenset(
    {"nature_vs_plan", "settlement_vs_plan", "amount_vs_plan", "tax_vs_plan", "other"}
)

_INSTRUCTION = (
    "You are an accounting treatment REVIEWER. You receive CONFIRMED FACTS "
    "and a CANONICAL PLAN (tool calls about to execute). Output STRICT JSON: "
    '{"contradictions": [{"kind": "nature_vs_plan|settlement_vs_plan|'
    'amount_vs_plan|tax_vs_plan|other", "why": "<one sentence>"}], '
    '"missing_material_facts": ["<fact name>"]}. '
    "Flag ONLY direct contradictions between the confirmed facts and the "
    "plan (e.g. nature INVENTORY but the plan carries no nature or no item "
    "lines; CREDIT but the plan settles cash now; a total that differs from "
    "the confirmed amount). Never invent facts. Never suggest accounts. If "
    "the plan is consistent with the facts, output empty lists. Note: "
    "Return document tools (create_credit_note, create_purchase_return) are "
    "document-level contra reversal vouchers; their lines represent returned goods/services, "
    "and they do not take a transaction_nature argument."
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


def _budget_treatment_prompt(
    instruction: str,
    facts: Dict[str, Any],
    plan: List[Dict[str, Any]],
    max_chars: int = 6000,
) -> str:
    """Safely structure and budget prompt to guarantee valid JSON and prevent mid-string cuts.

    Allocates character budget:
    - instruction: always intact
    - plan: tool calls essential for checking contradiction
    - facts: confirmed facts, with line items / descriptions truncated if needed
    """
    instruction_text = instruction.strip()
    overhead = len(instruction_text) + 50
    available_chars = max(1000, max_chars - overhead)

    budgeted_plan = []
    for call in plan:
        c = dict(call)
        args = dict(c.get("arguments") or {})
        items = args.get("items")
        if isinstance(items, list) and len(items) > 10:
            args["items"] = items[:10] + [{"truncated_items_summary": f"{len(items) - 10} more items"}]
        c["arguments"] = args
        budgeted_plan.append(c)

    budgeted_facts = dict(facts)
    desc = budgeted_facts.get("item_description")
    if isinstance(desc, str) and len(desc) > 200:
        budgeted_facts["item_description"] = desc[:197] + "..."

    items_facts = budgeted_facts.get("items")
    if isinstance(items_facts, list) and len(items_facts) > 10:
        budgeted_facts["items"] = items_facts[:10] + [{"truncated_items_summary": f"{len(items_facts) - 10} more items"}]

    payload = {
        "confirmed_facts": budgeted_facts,
        "canonical_plan": budgeted_plan,
    }
    payload_json = json.dumps(payload, indent=2, default=str)

    # If payload still exceeds available chars, reduce line items to 5
    if len(payload_json) > available_chars:
        for c in budgeted_plan:
            args = c.get("arguments") or {}
            items = args.get("items")
            if isinstance(items, list) and len(items) > 5:
                args["items"] = items[:5] + [{"truncated_items_summary": f"{len(items) - 5} more items"}]
        if isinstance(budgeted_facts.get("items"), list) and len(budgeted_facts["items"]) > 5:
            budgeted_facts["items"] = budgeted_facts["items"][:5] + [{"truncated_items_summary": f"{len(budgeted_facts['items']) - 5} more items"}]
        payload = {
            "confirmed_facts": budgeted_facts,
            "canonical_plan": budgeted_plan,
        }
        payload_json = json.dumps(payload, indent=2, default=str)

    return f"{instruction_text}\n\n{payload_json}"


def _extract_facts_and_plan(
    *,
    intent: str,
    classification: Any,
    entities: Dict[str, Any],
    calls: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    nature = str(getattr(classification, "transaction_nature", "") or "")
    if intent in ("record_sale", "record_cash_sale", "create_invoice", "create_sale_invoice", "record_receipt") and nature in ("OPERATING_EXPENSE", "CONSUMABLE", "FIXED_ASSET"):
        nature = "INVENTORY" if (entities.get("item_description") or entities.get("quantity")) else "REVENUE"
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
        "subtotal": entities.get("subtotal"),
        "tax_amount": entities.get("tax_amount") or entities.get("printed_tax"),
        "tax_code": entities.get("tax_code"),
        "transaction_date": entities.get("transaction_date"),
    }
    extracted_plan: List[Dict[str, Any]] = []
    for call in (calls or []):
        tool_name = getattr(call, "tool_name", "")
        raw_args = dict(getattr(call, "arguments", None) or {})
        call_args = {
            k: v
            for k, v in raw_args.items()
            if k in (
                "transaction_nature", "payment_method", "items", "total",
                "subtotal", "amount", "tax_total", "tax_code", "notes", "bill_date",
                "quantity", "description", "item_description", "reason",
                "credit_note_date", "return_date", "customer_id", "supplier_id",
                "customer_name", "supplier_name", "invoice_id", "bill_id",
            )
        }
        # For return tools (credit notes & purchase returns), if items array is not
        # materialized yet, preserve/synthesize the item line from description/quantity
        # so the treatment reviewer can see the line item substance.
        if tool_name in ("create_credit_note", "create_purchase_return") and not call_args.get("items"):
            desc = call_args.get("description") or call_args.get("item_description") or facts.get("item_description")
            qty = call_args.get("quantity") or facts.get("quantity")
            amt = call_args.get("amount") or facts.get("amount")
            if desc or qty:
                try:
                    qty_f = float(qty) if qty not in (None, "", 0) else 1.0
                except (ValueError, TypeError):
                    qty_f = 1.0
                try:
                    amt_f = float(amt) if amt not in (None, "", 0) else None
                except (ValueError, TypeError):
                    amt_f = None
                unit_price = round(amt_f / qty_f, 2) if (amt_f and qty_f) else amt_f
                call_args["items"] = [{
                    "description": str(desc or "Item return").strip(),
                    "quantity": qty_f,
                    "unit_price": unit_price,
                }]
        extracted_plan.append({
            "tool": tool_name,
            "arguments": call_args,
        })
    return facts, extracted_plan


def _facts_block(
    *,
    intent: str,
    classification: Any,
    entities: Dict[str, Any],
    calls: Any,
) -> str:
    facts, plan = _extract_facts_and_plan(
        intent=intent,
        classification=classification,
        entities=entities,
        calls=calls,
    )
    return json.dumps({"confirmed_facts": facts, "canonical_plan": plan}, indent=2, default=str)


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

    facts, plan = _extract_facts_and_plan(
        intent=intent,
        classification=classification,
        entities=entities,
        calls=calls,
    )

    # Authority Split Rule: Deterministic tax deviation check (Python authoritative)
    subtotal = float(entities.get("subtotal") or entities.get("amount") or 0.0)
    printed_tax = entities.get("tax_amount") or entities.get("printed_tax")
    tax_code = entities.get("tax_code")
    if printed_tax is not None and tax_code and subtotal > 0:
        try:
            from app.services import tax_service

            is_mat, computed_tax, diff = tax_service.evaluate_tax_deviation(
                subtotal=subtotal, printed_tax=float(printed_tax), tax_code=str(tax_code)
            )
            if is_mat:
                log.warning(
                    "authority_split.intercepted",
                    reason="tax_deviation",
                    printed_tax=printed_tax,
                    computed_tax=computed_tax,
                    diff=diff,
                )
                review.ran = True
                review.ok = False
                review.blocked = True
                review.flags.append(
                    {
                        "kind": "amount_vs_plan",
                        "why": (
                            f"Printed tax ({printed_tax}) differs from computed tax "
                            f"({computed_tax}) on tax code '{tax_code}' by {diff:.2f}"
                        ),
                    }
                )
                review.question = (
                    f"The printed/entered tax ({printed_tax}) differs from calculated tax ({computed_tax}) "
                    f"for subtotal {subtotal} under tax code '{tax_code}'. Please clarify the correct tax amount before posting."
                )
                review.audit["llm"] = "flagged"
                review.audit["flags"] = len(review.flags)
                return review
        except Exception as tax_exc:  # noqa: BLE001
            log.warning("treatment_review.tax_check_failed", error=str(tax_exc)[:160])

    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()

        prompt = _budget_treatment_prompt(
            instruction=_INSTRUCTION,
            facts=facts,
            plan=plan,
            max_chars=6000,
        )

        raw = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt),
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
