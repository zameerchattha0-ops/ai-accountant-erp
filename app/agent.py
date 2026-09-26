"""
ERP AI Agent — Central Orchestrator
=====================================
Owns the complete lifecycle of an AI request.

10-phase reasoning protocol (from Constitution v1.2.0):
  Understand → Determine Requirements → Acquire Context →
  Re-evaluate → Plan → Validate → Confirm → Execute → Verify → Respond

13-state execution state machine:
  RECEIVED → INTERPRETING → PLANNING → CONTEXT_LOADING →
  AWAITING_CLARIFICATION → VALIDATING → AWAITING_CONFIRMATION →
  EXECUTING → VERIFYING → COMPLETED (+FAILED/CANCELLED/REJECTED)
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import deque
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog
import time

from app.auth import AuthContext
from app.context_manager import build_context
from app.books_evidence import render_evidence_compact
from app.idempotency import FINANCIAL_WRITE_TOOLS
from app.database import (
    REQUEST_TIMINGS,
    create_clarification,
    create_confirmation,
    create_execution_result,
    create_execution_session,
    create_execution_step,
    create_tool_call as log_tool_call,
    fetch_many,
    fetch_one,
    get_clarification_history,
    resolve_clarification,
    resolve_confirmation,
    seed_clarification_history,
    set_session_phase,
    update_one,
)
from app.ai_orchestrator import get_client
from app.error_normalizer import build_missing_field_question
from app.reasoning import options_for_question, purpose_label, purpose_option, strip_markdown


# ---------------------------------------------------------------------------
# DETERMINISTIC MUTATION FAST PATH (instant mode)
# ---------------------------------------------------------------------------
# Provider evidence (live): ONE Qwen tool-planning round-trip costs 30-85s.
# When the planner + classifier have already resolved EVERYTHING (intent,
# nature, account hint, party, amount, date), re-deriving those parameters
# through the LLM adds pure latency.  For whitelisted intents the tool call
# is built DETERMINISTICALLY here and the LLM is bypassed entirely.  The
# confirmation gate (Phase 5), the tool router/validator and the date
# protocol are unchanged - this only removes the model round-trip.

# the DETERMINISTIC fast path family — when the
# reasoning ladder has fully resolved a transaction (nature/purpose,
# settlement channel, party, amount, date), the tool call is built here
# and the LLM is bypassed entirely.  Ambiguous or unconfirmed plans are
# NEVER fast-pathed — they complete the question ladder first.
_FAST_PATH_INTENTS = {
    "record_credit_purchase",   # R2: credit purchase bill path
    "record_expense",           # R3.5: generic expense (unambiguous)
    "record_receipt",           # R4.5: customer receipt
    "record_payment",           # R4.5: supplier payment
    "record_cash_sale",         # R4.5: cash sale (goods/service)
    "record_bank_transfer",     # R4.5: named bank-to-bank transfer
    "create_invoice",           # R4.7: resolved single-line invoice
    "record_credit_sale",       # R4.7: resolved credit sale -> invoice
}


# R4.8: sale-side intents whose deterministic fast path gates on a CUSTOMER
# ledger.  R4.12 extends it to the money-IN settlement intents: a receipt /
# cash sale settles a CUSTOMER's obligation, so its party gate must search
# the CUSTOMER registry (every other intent keeps the supplier gate).
# Production (session 3ea794a0): "I received 60000 from FDS Labs Pvt" hit
# the supplier gate while FDS Labs was a customer with open Invoice 5.
_CUSTOMER_PARTY_INTENTS = {
    "create_invoice",
    "record_credit_sale",
    "create_quotation",
    "record_receipt",
    "record_cash_sale",
}


# R4.11: the party gate ONLY fires inside a transaction-recording intent.
# The keyword fallback's "unknown" and read-only report intents must never
# ask party questions — there is no recording workflow behind them to
# resolve a ledger for.  This is exactly how the degraded run of
# "I received 60000 from FDS Labs Pvt" (intent=unknown after the LLM
# proposal was contract-rejected) produced "create a new supplier ledger?"
# instead of falling through to the model path that had already read the
# party's receivables.
_PARTY_GATE_INTENTS = _FAST_PATH_INTENTS | {
    "create_quotation",
    "convert_quotation",
    "create_credit_note",
    "create_purchase_return",
    "record_expense_payment",
    "record_cash_purchase",
    "record_purchase",
    "record_sale",
    "register_fixed_asset",
    "dispose_fixed_asset",
    "record_asset_depreciation",
}


# ---------------------------------------------------------------------------
# SERVERLESS PROVIDER BUDGET (host FUNCTION_INVOCATION_TIMEOUT limit)
# ---------------------------------------------------------------------------
# A provider round-trip retries internally (Qwen: 3 attempts, each bounded by
# qwen_timeout_seconds) and then falls back to the next model / Gemini.  With
# the original 120s timeout and a 4-model chain a single stalled
# planning/execution call could therefore consume 300s+ — past the host's
# function limit.  The platform then killed the function mid-run: the session
# stayed EXECUTING forever, no tool call was ever recorded, and the user saw a
# bare timeout error with no way forward.  Every provider round-trip is now
# bounded by an explicit wall-clock budget, so on expiry the run degrades to
# an honest, resumable response instead of being killed.
_LLM_PLANNING_BUDGET_SECONDS = 75.0
_LLM_EXECUTION_BUDGET_SECONDS = 120.0


async def _bounded_provider_call(coro, *, budget: float, stage: str):
    """Await a provider call under a hard wall-clock budget.

    Returns ``(result, None)`` on success or ``(None, reason)`` when the
    budget expired OR the provider failed outright.  From the caller's point of
    view both are the same situation — the model is unavailable — so the run
    degrades to an honest, resumable response and NOTHING is written.  The
    failure is logged with its detail so a real wiring bug stays visible.
    """
    try:
        return await asyncio.wait_for(coro, timeout=budget), None
    except asyncio.TimeoutError:
        return None, (
            f"The AI provider stopped responding ({stage} took longer than "
            f"{int(budget)}s)."
        )
    except Exception as exc:  # noqa: BLE001 — a provider error is data here
        log.warning(
            "agent.provider_failed", stage=stage, detail=str(exc)[:300]
        )
        return None, f"The AI provider could not be reached ({stage})."


async def _party_resolution_question(
    *,
    organization_id: uuid.UUID,
    execution_plan,
) -> Optional[Dict[str, Any]]:
    """Party resolution for the deterministic fast path.

    * EXACT party match            -> None (proceed to the tool call).
    * SIMILAR matches (no exact)   -> a "Party check" question listing the
      candidates (pick one, or create a new party ledger).
    * NOTHING found                -> a confirmation question before a new
      party ledger is created (never silently invented).
    A confirmed creation is marked via the ``supplier_create_confirmed`` /
    ``customer_create_confirmed`` entity and never asked twice.

    R4.8: the gate is INTENT-aware — sale-side intents (create_invoice,
    record_credit_sale, create_quotation) gate on the CUSTOMER, everything
    else keeps the original supplier gate.  This keeps the answered-invoice
    flow on the deterministic fast path when the named customer does not
    exist yet, instead of falling to a 70-80s LLM planning round.
    """
    entities = execution_plan.extracted_entities or {}
    if execution_plan.intent not in _PARTY_GATE_INTENTS:
        # No recording workflow (unknown/report intent): a party question
        # would be asked with nothing to record behind it — return None so
        # the model path interprets the request instead.
        return None
    kind = (
        "customer"
        if execution_plan.intent in _CUSTOMER_PARTY_INTENTS
        else "supplier"
    )
    name = (entities.get(f"{kind}_name") or "").strip()
    if not name:
        return None  # the planner asks for the party in its own round
    if entities.get(f"{kind}_create_confirmed"):
        return None  # user already approved creating this party

    from app.services import customer_service, supplier_service

    service = customer_service if kind == "customer" else supplier_service
    rows = await service.search(
        organization_id, query=name, limit=10
    ) or []
    exact = next(
        (
            r for r in rows
            if (r.get("name") or "").strip().lower() == name.lower()
        ),
        None,
    )
    if exact:
        return None  # exact party exists - proceed
    similar = [
        (r.get("name") or "").strip()
        for r in rows
        if (r.get("name") or "").strip()
    ]
    if similar:
        return {
            "question": (
                f"Party check: I found similar {kind}s for '{name}'. "
                "Which one is the real party for this transaction? "
                "(Or create a new party ledger instead.)"
            ),
            "options": [*similar[:4], f"Create new party '{name}'"],
            "required_fields": [f"{kind}_name"],
        }
    return {
        "question": (
            f"Party check: no {kind} named '{name}' exists yet. "
            f"Create '{name}' as a new {kind} ledger?"
        ),
        "options": [f"Yes - create '{name}'"],
        "required_fields": [f"{kind}_name"],
    }


def _expense_fast_path_call(
    entities: Dict[str, Any],
    classification,
) -> Optional[List[ToolCall]]:
    """R3.5 generic-expense fast path — build the ``create_expense`` call
    WITHOUT any LLM round-trip, or None whenever anything is unresolved
    (the model path then handles it exactly as before).

    Refusal rules (never guess):
    * the purpose must be KNOWN and UNAMBIGUOUSLY an ordinary expense —
      repairs/software/durable answers (capitalization ladder), equipment
      purchases and resale-goods intents are never fast-pathed;
    * the settlement must be confirmed (paid cash / bank) — credit and
      prepaid go through their own paths;
    * amount + underlying event date must both be present.
    """
    amount = entities.get("amount")
    txn_date = entities.get("transaction_date")
    purpose = entities.get("transaction_purpose")
    if amount is None or not txn_date or not purpose:
        return None
    opt = purpose_option(str(purpose))
    if opt is None or opt.capital_class != "EXPENSE":
        # Ambiguous / capitalization / inventory purposes complete the
        # question ladder first — never executed here.
        return None
    if entities.get("transaction_nature") not in (None, "OPERATING_EXPENSE"):
        return None
    payment = str(entities.get("payment_method") or "").upper()
    if payment not in ("CASH", "BANK_TRANSFER"):
        return None
    if str(entities.get("settlement_position") or "").upper() == "SETTLE_EXISTING_PAYABLE":
        # CA treatment 3 — the settlement of an expense ALREADY recorded
        # as payable is NOT a new expense: never fast-path create_expense
        # for it.  The reasoning path locates the outstanding payable
        # (same category), confirms it with the user, then settles it
        # (Dr trade payables / Cr cash-bank).
        return None
    payee = str(entities.get("supplier_name") or "").strip() or "Local Vendor"
    params: Dict[str, Any] = {
        "expense_date": str(txn_date),
        "payee_name": payee,
        "description": str(
            entities.get("description") or purpose_label(str(purpose))
        ),
        "subtotal": float(amount),
        "total": float(amount),
        "payment_mode": payment,
    }
    account_hint = (
        getattr(classification, "account_hint_id", None)
        if classification is not None
        else None
    )
    if account_hint:
        # Purpose-driven expense account hint — the journal debits THIS
        # expense account (Dr expense, Cr cash/bank).
        params["account_id"] = str(account_hint)
    return [ToolCall(tool_name="create_expense", arguments=params)]


def _settlement_fast_gate(
    entities: Dict[str, Any],
) -> Optional[tuple]:
    """Shared R4.5 gate for receipt/payment fast paths: amount + date +
    an EXPLICIT settlement channel (cash/bank — the ledger depends on it)
    + a resolved business operation.  Anything unresolved => None (the
    ladder/model path asks instead of guessing)."""
    amount = entities.get("amount")
    txn_date = entities.get("transaction_date")
    if amount is None or not txn_date:
        return None
    payment = str(entities.get("payment_method") or "").upper()
    if payment not in ("CASH", "BANK_TRANSFER"):
        return None
    nature = str(entities.get("transaction_nature") or "").upper()
    if nature not in ("ALLOCATION", "ADVANCE", "LOAN_OR_SETTLEMENT"):
        return None
    return amount, txn_date, payment, nature


async def _settlement_party(
    organization_id: uuid.UUID,
    *,
    kind: str,
    name: str,
    confirmed: bool,
):
    """R4.5 party gate for the settlement fast paths — EXACT match wins;
    a new party ledger is created ONLY on explicit confirmation (never
    silently invented).  Returns (party_row | None)."""
    from app.services import customer_service, supplier_service

    service = customer_service if kind == "customer" else supplier_service
    rows = await service.search(organization_id, query=str(name), limit=5) or []
    party = next(
        (
            r for r in rows
            if (r.get("name") or "").strip().lower() == str(name).strip().lower()
        ),
        None,
    )
    if party is not None:
        return party
    if not confirmed:
        return None
    if kind == "customer":
        return await customer_service.create(organization_id, name=str(name))
    return await supplier_service.create(organization_id, name=str(name))


async def _receipt_fast_path_call(
    organization_id: uuid.UUID,
    entities: Dict[str, Any],
) -> Optional[List[ToolCall]]:
    """R4.5 receipt fast path — build ``record_customer_receipt`` WITHOUT
    an LLM round-trip once the ladder is fully answered."""
    gate = _settlement_fast_gate(entities)
    if not gate:
        return None
    amount, txn_date, payment, nature = gate
    customer_name = (entities.get("customer_name") or "").strip()
    if not customer_name:
        return None
    customer = await _settlement_party(
        organization_id,
        kind="customer",
        name=customer_name,
        confirmed=bool(entities.get("customer_create_confirmed")),
    )
    if customer is None:
        return None  # the party gate question handles this
    params: Dict[str, Any] = {
        "customer_id": str(customer["id"]),
        "amount": float(amount),
        "receipt_date": str(txn_date),
        "payment_method": payment,
        "transaction_nature": nature,
    }
    reference = entities.get("item_description") or entities.get("description")
    if reference:
        params["reference"] = str(reference)
    return [ToolCall(tool_name="record_customer_receipt", arguments=params)]


async def _payment_fast_path_call(
    organization_id: uuid.UUID,
    entities: Dict[str, Any],
) -> Optional[List[ToolCall]]:
    """R4.5 supplier-payment fast path — mirrors the receipt path."""
    gate = _settlement_fast_gate(entities)
    if not gate:
        return None
    amount, txn_date, payment, nature = gate
    supplier_name = (entities.get("supplier_name") or "").strip()
    if not supplier_name:
        return None
    supplier = await _settlement_party(
        organization_id,
        kind="supplier",
        name=supplier_name,
        confirmed=bool(entities.get("supplier_create_confirmed")),
    )
    if supplier is None:
        return None
    params: Dict[str, Any] = {
        "supplier_id": str(supplier["id"]),
        "amount": float(amount),
        "payment_date": str(txn_date),
        "payment_method": payment,
        "transaction_nature": nature,
    }
    reference = entities.get("item_description") or entities.get("description")
    if reference:
        params["reference"] = str(reference)
    return [ToolCall(tool_name="record_supplier_payment", arguments=params)]


# -----------------------------------------------------------------------
# CA TREATMENT 3 — SETTLEMENT of an expense already recorded as payable.
# Deterministic checklist (no LLM): find the unpaid payable, confirm it
# with the user, allocate the payment to THAT bill (Dr trade payables /
# Cr cash-bank).  Never a second expense.
# -----------------------------------------------------------------------

async def _unpaid_payables(
    organization_id: uuid.UUID, keyword: str
) -> List[Dict[str, Any]]:
    """Every purchase bill with a remaining outstanding balance; keyword
    matches (category vocabulary) rank first, then any unpaid bill."""
    rows = await fetch_many(
        "purchase_bills",
        filters={"organization_id": str(organization_id)},
        select="id,bill_number,supplier_id,bill_date,due_date,total,amount_paid,status,notes",
        limit=50,
    )
    open_rows = [
        r for r in (rows or [])
        if str(r.get("status") or "").upper() not in ("PAID", "CANCELLED", "VOIDED")
        and float(r.get("total") or 0) - float(r.get("amount_paid") or 0) > 0.005
    ]
    if keyword:
        kw = str(keyword).lower()
        matched = [
            r for r in open_rows
            if kw in " ".join(
                str(r.get(k) or "")
                for k in ("notes", "bill_number", "supplier_invoice_ref")
            ).lower()
        ]
        return matched or open_rows
    return open_rows


def _payable_label(bill: Dict[str, Any]) -> str:
    outstanding = float(bill.get("total") or 0) - float(bill.get("amount_paid") or 0)
    return (
        f"{bill.get('bill_number') or 'bill'} — "
        f"{bill.get('notes') or 'unpaid payable'} "
        f"outstanding {outstanding:,.0f} "
        f"(due {bill.get('due_date') or bill.get('bill_date')})"
    )


async def _settlement_check_question(
    organization_id: uuid.UUID, execution_plan
) -> Optional[Dict[str, Any]]:
    """The 'Settlement check' gate: before ANY settlement payment is
    recorded, the located payable is CONFIRMED with the user (never
    silently settled) — or the request falls back to a new expense when
    the books hold no unpaid payable at all."""
    entities = execution_plan.extracted_entities or {}
    if execution_plan.intent != "record_expense":
        return None
    if str(entities.get("settlement_position") or "").upper() != "SETTLE_EXISTING_PAYABLE":
        return None
    if entities.get("settle_confirmed"):
        return None
    if entities.get("amount") is None or not entities.get("transaction_date"):
        return None  # amount/date round lands first
    purpose = str(entities.get("transaction_purpose") or "")
    label = purpose_label(purpose) if purpose else ""
    bills = await _unpaid_payables(organization_id, label)
    if not bills:
        return {
            "question": (
                "Settlement fallback: I could not find any unpaid payable in "
                f"your books, so this {float(entities.get('amount')):,.0f} "
                "cannot be a settlement. Record it as a new expense instead — how?"
            ),
            "options": [
                "Paid now — cash (new expense)",
                "Paid now — bank (new expense)",
                "Record as a new payable — pay later",
            ],
            "required_fields": ["settlement_fallback"],
        }
    if len(bills) == 1:
        return {
            "question": (
                "Settlement check: I found 1 unpaid payable — "
                f"{_payable_label(bills[0])}. Settle this one instead of "
                "recording a new expense?"
            ),
            "options": [
                "Yes — settle it",
                "No — record it as a new expense instead",
            ],
            "required_fields": ["settlement_check"],
        }
    opts = [_payable_label(b) for b in bills[:4]]
    opts.append("None of these — record as a new expense instead")
    return {
        "question": (
            f"Settlement check: I found {len(bills)} unpaid payables. "
            "Which one does this payment settle?"
        ),
        "options": opts,
        "required_fields": ["settlement_check"],
    }


async def _settlement_payment_call(
    organization_id: uuid.UUID, entities: Dict[str, Any]
) -> Optional[List[ToolCall]]:
    """Build the SETTLEMENT payment: allocate to the confirmed payable
    (Dr trade payables / Cr cash-bank) — never a new expense."""
    if str(entities.get("settlement_position") or "").upper() != "SETTLE_EXISTING_PAYABLE":
        return None
    if not entities.get("settle_confirmed"):
        return None
    payment = str(entities.get("payment_method") or "").upper()
    if payment not in ("CASH", "BANK_TRANSFER"):
        return None
    txn_date = entities.get("transaction_date")
    if not txn_date:
        return None
    purpose = str(entities.get("transaction_purpose") or "")
    bills = await _unpaid_payables(
        organization_id, purpose_label(purpose) if purpose else ""
    )
    if not bills:
        return None
    pick = (entities.get("settle_pick") or "").strip().lower()
    target = None
    if pick:
        for bill in bills:
            if pick in _payable_label(bill).lower():
                target = bill
                break
    elif len(bills) == 1:
        target = bills[0]
    if target is None or not target.get("supplier_id"):
        return None
    outstanding = float(target.get("total") or 0) - float(target.get("amount_paid") or 0)
    return [ToolCall(
        tool_name="record_expense_payment",
        arguments={
            "supplier_id": str(target["supplier_id"]),
            "amount": outstanding,
            "payment_date": str(txn_date),
            "payment_method": payment,
            "transaction_nature": "ALLOCATION",
            "bill_id": str(target["id"]),
            "reference": f"Settlement of {target.get('bill_number') or 'payable'}",
        },
    )]


def _cash_sale_fast_path_call(
    entities: Dict[str, Any],
) -> Optional[List[ToolCall]]:
    """R4.5 cash-sale fast path — the trusted ``record_cash_sale`` tool
    resolves the Cash and Revenue accounts itself; the ladder must have
    resolved amount + date + a goods/service nature (other income needs
    a revenue-account decision, so it stays on the model path)."""
    amount = entities.get("amount")
    txn_date = entities.get("transaction_date")
    if amount is None or not txn_date:
        return None
    nature = str(entities.get("transaction_nature") or "").upper()
    if nature not in ("GOODS", "SERVICE"):
        return None
    params: Dict[str, Any] = {
        "amount": float(amount),
        "transaction_date": str(txn_date),
        "description": str(
            entities.get("item_description") or entities.get("description")
            or "Cash sale"
        ),
    }
    # A revenue account the user has REVIEWED and approved (dedicated stream
    # ledger, or an existing account they named).  Passed straight through so the
    # tool credits exactly that ledger instead of choosing one.
    reviewed_account = entities.get("revenue_account_id")
    if reviewed_account:
        params["revenue_account_id"] = str(reviewed_account)
    return [ToolCall(tool_name="record_cash_sale", arguments=params)]


def _transfer_fast_path_call(
    entities: Dict[str, Any],
) -> Optional[List[ToolCall]]:
    """R4.5 bank-transfer fast path — both bank NAMES must be resolved
    (the trusted tool resolves names to ids and refuses unknown banks;
    accounts are never invented)."""
    amount = entities.get("amount")
    txn_date = entities.get("transaction_date")
    source = (entities.get("source_bank_name") or "").strip()
    destination = (entities.get("destination_bank_name") or "").strip()
    if amount is None or not txn_date or not source or not destination:
        return None
    params: Dict[str, Any] = {
        "source_bank_account_id": source,
        "destination_bank_account_id": destination,
        "amount": float(amount),
        "transfer_date": str(txn_date),
    }
    return [ToolCall(tool_name="record_bank_transfer", arguments=params)]


def _invoice_fast_path_call(
    entities: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """R4.7 invoice fast path — build the ``create_invoice`` call WITHOUT
    an LLM round-trip once the ladder is fully answered (nature =
    goods/service, customer, amount, date).  Other-income and asset-
    disposal natures need account decisions the model must make."""
    amount = entities.get("amount")
    txn_date = entities.get("transaction_date")
    if amount is None or not txn_date:
        return None
    nature = str(entities.get("transaction_nature") or "").upper()
    if nature not in ("GOODS", "SERVICE"):
        return None
    customer_name = (entities.get("customer_name") or "").strip()
    if not customer_name:
        return None  # the party gate question handles this
    # when DISTINCT lines were
    # parsed (or multi-item answer given) each becomes its own invoice
    # line.  The stated amount MUST equal Σ(qty × price) — any mismatch
    # is never guessed away; the plan falls back to clarification/model.
    parsed_lines = entities.get("line_items")
    if parsed_lines:
        try:
            items = [
                {
                    "description": str(l.get("description") or "").strip(),
                    "quantity": float(l.get("quantity")),
                    "unit_price": float(l.get("unit_price")),
                }
                for l in parsed_lines
            ]
        except (TypeError, ValueError):
            return None
        if not items or any(
            not i["description"] or i["quantity"] <= 0 or i["unit_price"] < 0
            for i in items
        ):
            return None
        derived = round(
            sum(i["quantity"] * i["unit_price"] for i in items), 2
        )
        if abs(derived - float(amount)) > 0.01:
            return None  # stated total ≠ Σ lines — never reconcile by guess
        return {"invoice_date": str(txn_date), "items": items}
    # the ladder now ASKS for the line description and
    # quantity (parity with the manual form's mandatory line item).  The
    # header total is divided across the units so the derived unit price
    # reconciles with the amount the user actually stated.
    raw_quantity = entities.get("quantity")
    try:
        quantity = float(raw_quantity) if raw_quantity is not None else 1.0
    except (TypeError, ValueError):
        quantity = 1.0
    if quantity <= 0:
        quantity = 1.0
    params: Dict[str, Any] = {
        "invoice_date": str(txn_date),
        "items": [{
            "description": str(
                entities.get("item_description")
                or entities.get("description")
                or ("Service" if nature == "SERVICE" else "Goods")
            ),
            "quantity": quantity,
            "unit_price": round(float(amount) / quantity, 2),
        }],
    }
    return params


async def _invoice_fast_path_party(
    organization_id: uuid.UUID,
    entities: Dict[str, Any],
    params: Dict[str, Any],
) -> Optional[List[ToolCall]]:
    """Customer gate for the invoice fast path (EXACT match or an
    explicitly confirmed new customer ledger — never invented)."""
    customer_name = (entities.get("customer_name") or "").strip()
    customer = await _settlement_party(
        organization_id,
        kind="customer",
        name=customer_name,
        confirmed=bool(entities.get("customer_create_confirmed")),
    )
    if customer is None:
        return None
    params["customer_id"] = str(customer["id"])
    # R4.10 — resolve line items against the product/service catalog:
    # EXACT matches are linked; unresolved ones are created ONLY when the
    # user answered the "Catalog check" round with YES (never invented).
    await _link_or_create_catalog_items(organization_id, entities, params)
    return [ToolCall(tool_name="create_invoice", arguments=params)]


def _invoice_line_names(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the invoice items (description + unit_price) for catalog work."""
    items = params.get("items") or []
    return [
        {"description": str(i.get("description") or "").strip(),
         "unit_price": float(i.get("unit_price") or 0)}
        for i in items if str(i.get("description") or "").strip()
    ]


async def _catalog_unmatched_names(
    organization_id: uuid.UUID,
    nature: str,
    items: List[Dict[str, Any]],
) -> List[str]:
    """Return the line descriptions with NO EXACT catalog entry.

    ``nature`` GOODS  → the PRODUCT catalog is searched.
    ``nature`` SERVICE → the SERVICE catalog is searched.
    Matching is exact-name (case/space-insensitive) — deterministic,
    never guessed from a fuzzy similarity.
    """
    from app.services import product_service, service_service

    unmatched: List[str] = []
    for line in items:
        name = line["description"]
        if nature == "SERVICE":
            rows = await service_service.search(organization_id, query=name, limit=5)
        else:
            rows = await product_service.search(organization_id, query=name, limit=5)
        if not any(
            str(r.get("name", "")).strip().lower() == name.lower()
            for r in rows
        ):
            if name.lower() not in (n.lower() for n in unmatched):
                unmatched.append(name)
    return unmatched


async def _catalog_check_question(
    organization_id: uuid.UUID,
    execution_plan,
) -> Optional[Dict[str, Any]]:
    """R4.10 "Catalog check" — invoice lines naming items that are NOT in
    the product/service catalog.  Asks ONCE, in the user's own words:

      YES  → the missing entries are created in the catalog (with the
              unit prices from this invoice) and linked to the lines.
      NO   → the lines stay one-off free-text lines (catalog untouched).

    The invoice itself is NEVER blocked by this gate — it only decides
    whether the catalog grows.  Returns None when there is nothing to
    ask (no buildable invoice, everything matched, or already answered).
    """
    entities = execution_plan.extracted_entities or {}
    if execution_plan.intent not in ("create_invoice", "record_credit_sale"):
        return None
    if entities.get("catalog_create_confirmed") or entities.get("catalog_skip"):
        return None  # answered in an earlier round — never re-asked
    params = _invoice_fast_path_call(entities)
    if not params:
        return None  # ladder incomplete — other gates ask first
    nature = str(entities.get("transaction_nature") or "").upper()
    if nature not in ("GOODS", "SERVICE"):
        return None
    unmatched = await _catalog_unmatched_names(
        organization_id, nature, _invoice_line_names(params)
    )
    if not unmatched:
        return None
    names = ", ".join(f"'{n}'" for n in unmatched)
    catalog = "service" if nature == "SERVICE" else "product"
    return {
        "question": (
            f"Catalog check: {names} {'are' if len(unmatched) > 1 else 'is'} "
            f"not in your {catalog} catalog yet. Add "
            f"{'them' if len(unmatched) > 1 else 'it'} to the catalog (with "
            "the unit prices from this invoice)? Reply YES to add, or NO "
            "to invoice as one-off free-text lines."
        ),
        "options": [
            "Yes - add to catalog",
            "No - one-off lines only",
        ],
    }


async def _link_or_create_catalog_items(
    organization_id: uuid.UUID,
    entities: Dict[str, Any],
    params: Dict[str, Any],
) -> None:
    """Link each invoice line to its EXACT catalog entry; create missing
    entries when (and only when) the user confirmed the catalog check."""
    from app.services import product_service, service_service

    nature = str(entities.get("transaction_nature") or "").upper()
    confirmed = bool(entities.get("catalog_create_confirmed"))
    for item in params.get("items") or []:
        name = str(item.get("description") or "").strip()
        if not name:
            continue
        if nature == "SERVICE":
            rows = await service_service.search(organization_id, query=name, limit=5)
        else:
            rows = await product_service.search(organization_id, query=name, limit=5)
        exact = next(
            (
                r for r in rows
                if str(r.get("name", "")).strip().lower() == name.lower()
            ),
            None,
        )
        if exact:
            key = "service_id" if nature == "SERVICE" else "product_id"
            item[key] = str(exact["id"])
            continue
        if not confirmed:
            continue  # catalog_skip or unanswered — one-off free-text line
        try:
            if nature == "SERVICE":
                created = await service_service.create(
                    organization_id,
                    name=name,
                    billing_unit="ITEM",
                    standard_rate=float(item.get("unit_price") or 0),
                )
                item["service_id"] = str(created["id"])
            else:
                created = await product_service.create(
                    organization_id,
                    name=name,
                    unit_price=float(item.get("unit_price") or 0),
                )
                item["product_id"] = str(created["id"])
        except Exception as exc:  # noqa: BLE001 — catalog write is best-effort
            log.warning(
                "catalog.create_failed",
                name=name,
                error=str(exc)[:200],
            )


async def _deterministic_mutation_calls(
    *,
    organization_id: uuid.UUID,
    execution_plan,
    classification,
) -> Optional[List[ToolCall]]:
    """Build the tool calls WITHOUT the LLM, or return None when the plan
    is not fully resolved (the normal model path then handles it)."""
    if execution_plan.intent not in _FAST_PATH_INTENTS:
        return None
    if execution_plan.batch_items:
        return None
    entities = execution_plan.extracted_entities or {}
    if execution_plan.intent == "record_expense":
        # CA treatment 3 first: a confirmed settle-existing-payable
        # allocates the payment to THAT bill — never a new expense.
        settle_call = await _settlement_payment_call(organization_id, entities)
        if settle_call:
            return settle_call
        # R3.5: the generic-expense fast path (purpose + settlement
        # confirmed, unambiguous).  None => the ladder continues instead.
        return _expense_fast_path_call(entities, classification)
    if execution_plan.intent == "record_receipt":
        # R4.5: the receipt fast path (operation + channel + party
        # resolved).  None => the ladder/model path asks instead.
        return await _receipt_fast_path_call(organization_id, entities)
    if execution_plan.intent == "record_payment":
        return await _payment_fast_path_call(organization_id, entities)
    if execution_plan.intent == "record_cash_sale":
        return _cash_sale_fast_path_call(entities)
    if execution_plan.intent == "record_bank_transfer":
        return _transfer_fast_path_call(entities)
    if execution_plan.intent in ("create_invoice", "record_credit_sale"):
        # R4.7: the invoice fast path (nature goods/service + customer +
        # amount + date resolved) — builds the invoice tool call without
        # the LLM; the confirmation gate still applies downstream.
        invoice_params = _invoice_fast_path_call(entities)
        if invoice_params is None:
            return None
        return await _invoice_fast_path_party(
            organization_id, entities, invoice_params
        )
    if classification is not None and getattr(
        classification, "requires_clarification", False
    ):
        # Configuration/nature gap - asking is the safe behaviour.
        return None
    amount = entities.get("amount")
    txn_date = entities.get("transaction_date")
    supplier_name = entities.get("supplier_name")
    if amount is None or not txn_date or not supplier_name:
        # Incomplete plan - never guess; the model path asks for gaps.
        return None
    if classification is not None and getattr(
        classification, "requires_clarification", False
    ):
        # Configuration/nature gap - asking is the safe behaviour.
        return None

    # Party resolution: EXACT match -> reuse.  Otherwise
    # a new party is created ONLY when the user explicitly confirmed it
    # (supplier_create_confirmed from the "Party check" round) - never
    # silently invented.  Anything unresolved goes back to the question.
    from app.services import supplier_service

    confirmed = bool(entities.get("supplier_create_confirmed"))
    rows = await supplier_service.search(
        organization_id, query=str(supplier_name), limit=5
    ) or []
    supplier = next(
        (
            r for r in rows
            if (r.get("name") or "").strip().lower()
            == str(supplier_name).strip().lower()
        ),
        None,
    )
    if supplier is None:
        if not confirmed:
            return None  # the party-resolution question handles this
        supplier = await supplier_service.create(
            organization_id, name=str(supplier_name)
        )

    params: Dict[str, Any] = {
        "supplier_id": str(supplier["id"]),
        "bill_date": str(txn_date),
        "subtotal": float(amount),
        "total": float(amount),
    }
    # R4.10 PARITY: when DISTINCT lines were resolved (multi-item phrasing or
    # the attached-document table), the bill MUST carry them - the manual form
    # records line items and a document bill without its lines loses the very
    # detail the user uploaded.  The stated amount must equal the sum of the
    # lines; any mismatch is never reconciled by guessing (the model path
    # asks instead), and the service recomputes every line_total from
    # quantity x unit_price, so the header can never disagree with its lines.
    line_items = entities.get("line_items")
    if line_items:
        try:
            bill_items = [
                {
                    "description": str(l.get("description") or "").strip(),
                    "quantity": float(l.get("quantity")),
                    "unit_price": float(l.get("unit_price")),
                }
                for l in line_items
            ]
        except (TypeError, ValueError):
            bill_items = None
        if bill_items and any(
            not i["description"] or i["quantity"] <= 0 or i["unit_price"] < 0
            for i in bill_items
        ):
            bill_items = None
        if bill_items:
            derived = round(
                sum(i["quantity"] * i["unit_price"] for i in bill_items), 2
            )
            if abs(derived - float(amount)) <= 0.01:
                params["items"] = bill_items
                params["subtotal"] = derived
                params["total"] = derived
    notes = entities.get("item_description") or (
        "Credit purchase recorded by the agent"
    )
    if notes:
        params["notes"] = str(notes)
    account_hint = (
        getattr(classification, "account_hint_id", None)
        if classification is not None
        else None
    )
    if account_hint:
        # Nature-driven expense/asset account hint - the journal debits
        # THIS account (Dr expense/asset, Cr party payable).
        params["account_id"] = str(account_hint)
    return [ToolCall(tool_name="create_purchase_bill", arguments=params)]
from app.models.schemas import (
    AgentContext,
    AgentResponse,
    AttachmentRef,
    ExecutionPlan,
    ExecutionStatus,
    ToolCall,
    ToolResult,
)
from app.planner import plan as run_planner
from app.tool_execution import execute_planned_tool_calls
from app.tool_router import route_tool_call
from app.tools import get_handler
from app.accounting_engine import verify_journal
from app.entity_contract import (
    build_accounting_impact,
    build_affected_entities,
)
from app.repositories import account_repository as account_repo

log = structlog.get_logger(__name__)

MAX_TOOL_ITERATIONS = 10


def _make_account_label_resolver(organization_id: uuid.UUID):
    """Return an async resolver: account UUID (or UUID-able str) -> GL label."""

    async def _resolve(account_id: Any) -> Optional[str]:
        try:
            account = await account_repo.get_account(
                organization_id, account_id=uuid.UUID(str(account_id))
            )
        except Exception:  # noqa: BLE001 — label fallback handled by caller
            return None
        return account.get("name") if account else None

    return _resolve
# Hard ceiling on planner-driven clarification rounds per conversation.
# After this the request is passed to Gemini with whatever is known —
# Gemini may still ask via its own question routing, but the planner
# gate can no longer loop.
MAX_CLARIFICATION_ROUNDS = 3
# Ceiling for MODEL-driven clarification rounds.  Missing information is
# resolved RECURSIVELY: each answer may reveal another genuinely-required
# dependency (amount → payment treatment → supplier creation → tax
# treatment …), and the agent must keep asking in the SAME conversation
# until nothing material is missing.  The model is instructed to ask ONLY
# when material information is genuinely absent, so this ceiling is just
# a runaway guard, not a question quota.
MODEL_MAX_CLARIFICATION_ROUNDS = 8

# Maps a 13-value execution phase (ai.execution_phase_code, written to
# current_phase) onto the 7-value session lifecycle (ai.session_status_code,
# written to status) and whether the session is now complete.


def _looks_like_question(text: str) -> bool:
    """Heuristic: does this model response ask the user for information?

    The model is instructed to ask at most ONE question when material
    information is missing; such responses contain a question mark.  Used
    to route text-only model responses into the clarification mechanism
    instead of reporting a completed (never verified) ERP operation.
    """
    return "?" in (text or "")


def _usable_question(text: str) -> Optional[str]:
    """Return the model's question if it is real and meaningful.

    Guards against empty/whitespace-only model responses being stored as
    clarification questions (which would strand the user with nothing to
    answer).
    """
    t = (text or "").strip()
    if t and _looks_like_question(t) and re.search(r"[A-Za-z]{3}", t):
        return t
    return None


# ---- CASH-CONFIG GATE (P5 pattern for the cash ledger) --------------------
# A cash settlement with no drawer configured is a CONFIGURATION state, not
# an execution failure: it must park with a guided question (asked once per
# conversation) instead of dead-ending in "Something went wrong", and the
# drawer may be created only AFTER an explicit YES (never invented).
_AFFIRMATIVE_ANSWER_RE = re.compile(
    r"(?i)^\s*(?:y|yes|yep|yeah|yup|sure|ok|okay|fine|confirm\w*|create\w*"
    r"|create\s+it|do\s+it|go\s+ahead|proceed|please\s+(?:do|create|proceed))"
    r"\s*[.!?,]?\s*$"
)


def _is_affirmative_answer(text: Optional[str]) -> bool:
    """True only for a tight set of clear YES replies (never guessing)."""
    return bool(text) and _AFFIRMATIVE_ANSWER_RE.match(str(text).strip()) is not None


def _is_cash_config_error(error: Optional[str]) -> bool:
    """True when a tool failed solely because no cash drawer is configured."""
    return "No cash account specified" in (error or "")


def _cash_configuration_question(cash_gl: Optional[Dict[str, Any]]) -> str:
    """Ask-once guided question replacing the dead-end cash failure.

    Both variants carry "cash ledger" (the creation trigger) and "cash
    account" (the ask-once marker), so a second miss falls through to the
    genuine FAILED path instead of re-parking forever.
    """
    if cash_gl:
        name = str(cash_gl.get("name") or "Cash")
        code = str(cash_gl.get("code") or "")
        return (
            f"No cash account is configured as the cash ledger for this "
            f"organization, so this cash payment or receipt cannot be "
            f"recorded yet — the money side must hit the cash ledger, never "
            f"the bank. Reply YES to create a default '{name}' cash account "
            f"linked to your existing '{name}' ({code}) GL account, then "
            f"I'll retry; or set it up another way and ask me again."
        )
    return (
        "No cash account is configured as the cash ledger for this "
        "organization, so this cash payment or receipt cannot be recorded "
        "yet — and the chart of accounts has no Cash asset account either. "
        "Add a Cash (ASSET) account under Accounting → Chart of Accounts, "
        "then ask me again — I won't invent a GL account myself."
    )


def _cash_drawer_creation_pending(prior_qa: List[Dict[str, str]]) -> bool:
    """True when the cash-ledger question was asked AND the user said YES."""
    for qa in prior_qa or []:
        question = (qa.get("question") or "").lower()
        if "cash ledger" in question and _is_affirmative_answer(qa.get("answer")):
            return True
    return False


def _cash_config_already_asked(prior_qa: List[Dict[str, str]]) -> bool:
    """Ask-once: any prior cash-account question counts (P5 bank mirror)."""
    return any(
        "cash account" in (qa.get("question") or "").lower()
        for qa in prior_qa or []
    )


def _mutation_executed(tool_calls: List[ToolCall]) -> bool:
    """True if any executed tool MUTATES ERP state (not read-only).

    A model question after only read-only lookups (search/get/list) is a
    safe clarification point — no ERP state has changed.  After a mutation
    the run must proceed to verification instead.
    """
    for tc in tool_calls:
        entry = get_handler(tc.tool_name)
        if entry and not entry.get("read_only", True):
            return True
    return False


def _tool_audit_error_text(tr: Optional[ToolResult]) -> Optional[str]:
    """Durable failure text for ``ai.tool_calls.error_details``.

    The model-facing ``error`` is often a sanitised generic sentence (by
    design — internals must not leak to the model), while ``error_details``
    carries the normalised payload INCLUDING the raw exception message.  Both
    are persisted, so the next failure of this kind is root-causable straight
    from the database instead of from server logs.

    A FAILED row must never hold a NULL reason — otherwise the cause has to
    be reconstructed by hand from the plan snapshot.  A FAILED call is
    therefore never written without a reason.
    """
    if tr is None or tr.success:
        return None
    parts: List[str] = []
    if tr.error_category:
        parts.append(f"[{tr.error_category}]")
    if tr.error:
        parts.append(str(tr.error))
    details = tr.error_details if isinstance(tr.error_details, dict) else {}
    raw = details.get("message") or details.get("reason")
    if raw and str(raw) not in " ".join(parts):
        parts.append(f"raw: {str(raw)[:1000]}")
    text = " ".join(parts).strip()
    return text[:2000] or f"{tr.tool_name}: failed without an error message"

# Statuses that can still move.  Distinct from main.py's set (which
# deliberately EXCLUDES WAITING_FOR_USER so reattach does not re-attach a
# parked run): here a parked run IS non-terminal and must be closed when a
# newer request supersedes it.
_NON_TERMINAL_RUN_STATUSES = {
    "PENDING",
    "PLANNING",
    "EXECUTING",
    "WAITING_FOR_USER",
}


async def _close_superseded_sessions(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    keep_session_id: uuid.UUID,
) -> int:
    """Close non-terminal sessions for this user+org that a NEW request has
    superseded.

    Guard: when a run parks on a clarification question and the user
    simply re-sent the request instead of answering, the parked session was
    left WAITING_FOR_USER for ever (`completed_at` NULL).  Multiple such
    orphans can accumulate, and then
    /api/ai/sessions/latest-active — which walks newest-first and SKIPS
    terminal rows — returned an OLD parked session, so the dashboard showed

        "Your last request is still waiting for your answer.
         Send it again to continue."

    immediately after a run that had already COMPLETED successfully.  Sending
    a new request is an explicit statement that the previous one is abandoned,
    so the abandoned rows are closed here rather than left dangling.

    Only rows the caller owns (same org AND user) are touched.  Best-effort:
    a cleanup failure must never block the run itself.
    """
    superseded = 0
    try:
        rows = await fetch_many(
            "ai_execution_sessions",
            filters={
                "organization_id": str(organization_id),
                "user_id": str(user_id),
            },
            select="id,status,current_phase,updated_at",
            order="created_at.desc",
            limit=25,
        )
    except Exception as exc:  # noqa: BLE001 — never block the new run
        log.warning("agent.supersede_lookup_failed", error=str(exc)[:200])
        return 0

    for row in rows or []:
        try:
            if str(row.get("id")) == str(keep_session_id):
                continue
            status = str(row.get("status") or "").upper()
            if status not in _NON_TERMINAL_RUN_STATUSES:
                continue  # already terminal — never rewrite history
            await _update_status(uuid.UUID(str(row["id"])), ExecutionStatus.CANCELLED)
            superseded += 1
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.supersede_failed",
                session_id=str(row.get("id")),
                error=str(exc)[:200],
            )

    if superseded:
        log.info(
            "agent.superseded_sessions_closed",
            count=superseded,
            kept_session=str(keep_session_id),
        )
    return superseded


# Sale intents whose revenue account must be REVIEWED before execution.
_SALE_REVIEW_INTENTS = frozenset({
    "record_cash_sale",
    "record_sale",
    "record_credit_sale",
    "create_invoice",
})


async def _revenue_ledger_review_gate(
    *,
    organization_id: uuid.UUID,
    execution_plan,
):
    """Ask BEFORE a sale picks a revenue account — and create on approval.

    Returns a clarification payload when the USER must decide, otherwise None.

    When the user has already answered, the decision is APPLIED here: on
    approval the dedicated child ledger is created under the revenue parent, and
    the resolved account id is written into the plan's entities so the executing
    tool credits exactly that account.

    This is the flexible-COA behaviour: the chart grows to match how the business
    actually earns (Chairs, Beds, Mobile Phones ...) instead of every sale being
    squeezed into whichever revenue account happens to exist.  It never guesses
    — an unresolved revenue account blocks the sale with a question.
    """
    intent = str(getattr(execution_plan, "intent", "") or "")
    if intent not in _SALE_REVIEW_INTENTS:
        return None
    entities = getattr(execution_plan, "extracted_entities", None)
    if not isinstance(entities, dict):
        return None

    from app.services import revenue_ledger_service as rls

    item = entities.get("item_description") or entities.get("description")
    decision = entities.get("revenue_ledger_decision")
    label = rls.stream_label(item)

    if decision:
        # The user has spoken — apply it (creating the ledger when approved).
        named = entities.get("revenue_account_name")
        account, created = await rls.apply_decision(
            organization_id, label, decision, named_account=named
        )
        if account is not None:
            entities["revenue_account_id"] = str(account["id"])
            entities["revenue_account_resolved"] = (
                "created" if created else "existing"
            )
            log.info(
                "ledger_decision_normalized",
                organization_id=str(organization_id),
                decision=str(decision)[:20],
                outcome="created" if created else "existing",
                revenue_account_id=str(account["id"]),
            )
            return None
        # The decision could not be applied (unknown or ambiguous account
        # name, CREATE without a usable stream, ...).  ASK AGAIN with a
        # targeted error — never let the sale proceed on an unreviewed
        # revenue account, and never silently pick another account.
        log.warning(
            "ledger_decision_invalid",
            organization_id=str(organization_id),
            decision=str(decision)[:20],
        )
        general = await rls.find_general_revenue(organization_id)
        parent_name = (general or {}).get("name") or rls.REVENUE_PARENT_NAME
        proposed = rls.suggest_ledger_name(label) if label else "a new ledger"
        rejected = str(named or decision).strip()[:80]
        return {
            "question": (
                f"Revenue ledger check: your answer \"{rejected}\" could not "
                f"be applied — it does not match exactly one existing revenue "
                f"account in your chart. Create a dedicated ledger "
                f"'{proposed}' under '{parent_name}' so this revenue is "
                f"reported separately? Reply YES to create it, or reply with "
                f"the exact name of an existing revenue account to use instead."
            ),
            # Plain strings — the frontend renders each as a tappable chip.
            "options": [
                f"Create '{proposed}' under {parent_name}",
                f"Use the existing '{parent_name}' account",
            ],
        }

    if not await rls.needs_review(organization_id, item, decision):
        return None

    proposed = rls.suggest_ledger_name(label) if label else "a new ledger"
    general = await rls.find_general_revenue(organization_id)
    parent_name = (general or {}).get("name") or rls.REVENUE_PARENT_NAME
    return {
        "question": (
            f"Revenue ledger check: nothing is recorded against '{label}' yet. "
            f"Create a dedicated ledger '{proposed}' under '{parent_name}' so "
            f"this revenue is reported separately? Reply YES to create it, or "
            f"reply with the name of an existing revenue account to use instead."
        ),
        # AgentResponse.options is List[str] — the frontend renders each entry
        # as a tappable chip and calls opt.trim() on it.  Emitting
        # {"value": ..., "label": ...} dicts here raised a Pydantic
        # ValidationError ("Input should be a valid string [type=string_type,
        # input_value={'value': 'yes', 'label': ...}]") that failed the WHOLE
        # session, and would also have thrown a TypeError in the browser.
        # The planner's decision parser accepts these labels: "Create ..."
        # -> CREATE, anything else -> USE_EXISTING.
        "options": [
            f"Create '{proposed}' under {parent_name}",
            f"Use the existing '{parent_name}' account",
        ],
    }


_PHASE_STATUS_MAP: Dict[ExecutionStatus, tuple] = {
    ExecutionStatus.RECEIVED: ("PENDING", False),
    ExecutionStatus.INTERPRETING: ("PLANNING", False),
    ExecutionStatus.PLANNING: ("PLANNING", False),
    ExecutionStatus.CONTEXT_LOADING: ("PLANNING", False),
    ExecutionStatus.AWAITING_CLARIFICATION: ("WAITING_FOR_USER", False),
    ExecutionStatus.AWAITING_CONFIRMATION: ("WAITING_FOR_USER", False),
    ExecutionStatus.VALIDATING: ("EXECUTING", False),
    ExecutionStatus.EXECUTING: ("EXECUTING", False),
    ExecutionStatus.VERIFYING: ("EXECUTING", False),
    ExecutionStatus.COMPLETED: ("COMPLETED", True),
    ExecutionStatus.FAILED: ("FAILED", True),
    ExecutionStatus.CANCELLED: ("CANCELLED", True),
    ExecutionStatus.REJECTED: ("CANCELLED", True),
}


# ---------------------------------------------------------------------------
# Confirmation disclosure — the user must be told WHAT WILL HAPPEN before
# approving: transaction, amount, party, and every entity that will be
# created (supplier/customer/account/document).  A bare intent label is NOT
# sufficient disclosure.
# ---------------------------------------------------------------------------

_CASH_INTENTS = {"record_cash_purchase", "record_cash_sale"}
# Party ledgers are NEVER required for cash transactions (one-off-cash
# rule): the named party is informational and must not be created.
_CASH_BLOCKED_PARTY_TOOLS = {"create_supplier", "create_customer"}


def cash_party_creation_blocked(intent: str, tool_name: str) -> bool:
    """True when a party-creation tool must be refused for a cash intent."""
    return (intent in _CASH_INTENTS
            and tool_name in _CASH_BLOCKED_PARTY_TOOLS)


def event_prohibited_tools(
    prohibited_actions: Optional[List[Dict[str, str]]]
) -> set:
    """Tool slugs forbidden by the event's PROHIBITED-ACTION analysis.

    Generic negative-reasoning enforcement: the refusal set is derived
    from the economic-event profile (cash ⇒ no party ledger; SERVICE ⇒ no
    inventory movement; expense ⇒ no capitalisation; REPORTING ⇒ no
    mutations) — never from per-scenario special cases.
    """
    from app.reasoning import (
        EconomicEvent,
        EventProfile,
        ProhibitedAction,
        prohibited_tool_names,
    )

    profile = EventProfile(
        event=EconomicEvent.UNKNOWN,
        intent="",
        affected={},
        prohibited=[
            ProhibitedAction(
                action=(a or {}).get("action", ""),
                reason=(a or {}).get("reason", ""),
            )
            for a in (prohibited_actions or [])
        ],
    )
    return prohibited_tool_names(profile)


# Party-creation slugs: the ONLY tools the shortlist guard may refuse with
# the historical duplicate-party wording (the case that guard was written
# for — a search already resolved the party).
_PARTY_CREATE_TOOLS = frozenset({"create_supplier", "create_customer"})


def excluded_tool_refusal(tool_name: str, intent: str) -> Dict[str, str]:
    """FIX-2: accurate refusal for a shortlist-disabled tool.

    RC-2 (production 2026-09-24, "3 computers" incident): a single guard
    refused EVERY excluded tool with the party-duplicate message —
    ``register_fixed_asset`` failed with "an existing record was already
    found for this party" for a party that never existed in the request.
    Party creation keeps its historical wording (byte-identical); every
    other excluded tool gets an honest not-permitted-for-this-intent
    refusal.  Pure — unit tested directly.
    """
    if tool_name in _PARTY_CREATE_TOOLS:
        return {
            "success": False,
            "error": (
                "BUSINESS_RULE_VIOLATION: an existing record was "
                "already found for this party — reuse it. Creating "
                "a duplicate is forbidden."
            ),
            "error_category": "BUSINESS_RULE_VIOLATION",
        }
    return {
        "success": False,
        "error": (
            f"BUSINESS_RULE_VIOLATION: {tool_name} is not part of the "
            f"'{intent}' transaction's permitted toolset — it was "
            "excluded from this plan. Record the event with the tools "
            "that match its accounting intent, or ask the user to "
            "confirm a different treatment."
        ),
        "error_category": "BUSINESS_RULE_VIOLATION",
    }


def plan_conflict_tools(
    *,
    planned_names: Sequence[str],
    prohibited_actions: Optional[List[Dict[str, str]]],
    unpermitted: Any = (),
    batch: bool = False,
) -> set:
    """FIX-6 decision: which planned tools can NEVER execute, when NOTHING
    in the plan remains executable.

    Fail-closed BEFORE the user is asked to approve a plan that execution
    would refuse (production 2026-09-24: a plan whose ONLY tool was
    prohibited for its own event profile was frozen into a confirmation
    and detonated on the approval turn).  Partial tolerance is preserved:
    when at least one planned tool can still execute the set is empty and
    the executor gates refuse individual tools exactly as before.  Batch
    plans keep their existing sub-intent handling (never flagged here).
    Pure — unit tested directly.
    """
    if batch:
        return set()
    names = {str(n) for n in (planned_names or [])}
    if not names:
        return set()
    blocked = names & (
        event_prohibited_tools(prohibited_actions) | set(unpermitted or ())
    )
    if blocked and not (names - blocked):
        return blocked
    return set()



def party_resolved_in_search(
    result_data: Any, entity_name: Optional[str]
) -> bool:
    """True when a successful supplier/customer search resolved the named party.

    Used by the executor to disable the corresponding creation tool
    (reasoning-level fix): once the party exists, the model must reuse it
    and is no longer offered the creation tool.

    Delegates to :func:`app.reasoning.classify_party_match`, which also
    distinguishes EXACT / RESOLVED_PARTIAL / AMBIGUOUS / NONE so the
    executor can detect multiple-candidate ambiguity instead of silently
    reusing an arbitrary "first hit".
    """
    from app.reasoning import PartyMatchState, classify_party_match

    state, _matches = classify_party_match(result_data, entity_name)
    return state in (
        PartyMatchState.EXACT,
        PartyMatchState.RESOLVED_PARTIAL,
        PartyMatchState.AMBIGUOUS,
    )


def party_search_directive(
    state: "PartyMatchState", entity_name: Optional[str], created_tool: str
) -> str:
    """Executor directive fed back to the model after a party search."""
    from app.reasoning import PartyMatchState

    if state is PartyMatchState.AMBIGUOUS:
        return (
            f"Several existing records partially match "
            f"'{entity_name}' and none is an exact match. Do NOT guess and "
            f"do NOT create a duplicate: either confirm with the user which "
            f"existing record to use, or record the transaction without the "
            f"party ledger when the transaction type allows it. "
            f"{created_tool} has been disabled for this request."
        )
    if state is PartyMatchState.EXACT:
        return (
            f"An exact existing record for '{entity_name}' was found above — "
            f"reuse its authoritative id. {created_tool} has been disabled "
            "for this request."
        )
    return (
        f"An existing record for '{entity_name}' was found above — reuse it. "
        f"{created_tool} has been disabled for this request."
    )



def _reasoning_disclosure(reasoning) -> str:
    """The user-facing disclosure of an ACCEPTED LLM accounting proposal.

    The proposal came from a model that inspected the live books, so the user
    is shown THAT accounting reading — the interpretation, the records it
    affects, the proposed impact, what deliberately will not change, the
    remaining uncertainty and the exact confirmation sentence — instead of the
    planner's keyword-intent summary.
    """
    proposal = getattr(reasoning, "proposal", None) or {}
    if not proposal:
        return ""
    parts: list = []
    interpretation = str(proposal.get("interpretation") or "").strip()
    if interpretation:
        parts.append(interpretation)
    affected = proposal.get("affected_records") or []
    if affected:
        parts.append("Affected: " + "; ".join(str(x) for x in affected[:6]))
    impact = proposal.get("accounting_impact") or []
    for entry in impact[:6]:
        if not isinstance(entry, dict):
            continue
        account = str(entry.get("account") or "").strip()
        for side, verb in (("debit", "Dr"), ("credit", "Cr")):
            value = entry.get(side)
            if value in (None, ""):
                continue
            try:
                shown = f"{float(value):,.2f}"
            except (TypeError, ValueError):
                shown = str(value)
            parts.append(f"{verb} {account} {shown}".strip())
    not_affected = proposal.get("not_affected") or []
    if not_affected:
        parts.append(
            "Not affected: " + "; ".join(str(x) for x in not_affected[:6])
        )
    uncertainty = proposal.get("unresolved_uncertainty") or []
    if uncertainty:
        parts.append(
            "Still uncertain: " + "; ".join(str(x) for x in uncertainty[:6])
        )
    confirmation = str(proposal.get("confirmation") or "").strip()
    if confirmation:
        parts.append(confirmation)
    return "\n".join(parts)


def _confirmation_summary(plan) -> str:
    """Human-readable disclosure of what approval will execute."""
    entities = getattr(plan, "extracted_entities", None) or {}
    bits: list = [f"record {plan.intent.replace('_', ' ')}"]
    amount = entities.get("amount")
    if amount:
        try:
            bits.append(f"amount {float(amount):,.0f} PKR")
        except (TypeError, ValueError):
            pass
    if getattr(plan, "entity_name", None):
        bits.append(f"party: {plan.entity_name}")
    tools = set(getattr(plan, "potential_tools", None) or [])
    creations: list = []
    if "create_supplier" in tools:
        creations.append(
            f"supplier '{plan.entity_name}' if it does not already exist")
    if "create_customer" in tools:
        creations.append(
            f"customer '{plan.entity_name}' if it does not already exist")
    if "create_account" in tools:
        creations.append(
            "a new chart-of-accounts account if none suitable exists")
    if "create_purchase_bill" in tools:
        creations.append("a purchase bill")
    if "create_invoice" in tools:
        creations.append("a sales invoice")
    if "create_expense" in tools:
        creations.append("an expense record")
    if creations:
        bits.append("will create: " + "; ".join(creations))
    if "credit" in plan.intent:
        bits.append("a payable/receivable balance will be recorded")
    return "Pending confirmation — " + "; ".join(bits) + "."


async def _account_rescue_question(
    *,
    session_id: uuid.UUID,
    organization_id: uuid.UUID,
    execution_plan,
    failures,
    prior_qa,
    require_no_successful_writes: bool = True,
) -> Optional[AgentResponse]:
    """EXECUTION-AGENT LOOP (rescue): account-DETERMINATION failures become
    the account-creation clarification instead of a dead-end FAILED run.

    Fires only when: every failure is an account-gap error; no creation is
    confirmed yet; the merge-contract question was not asked this
    conversation; clarification rounds remain; and (optionally) no WRITE
    has succeeded — a posted mutation is never re-run behind the user's
    back.  Returns None → the normal FAILED path continues unchanged.
    """
    from app.account_resolution import (
        gap_already_asked,
        gap_from_execution_failure,
        is_account_resolution_error,
        options_for_gap,
        question_for_gap,
    )

    if not failures or not require_no_successful_writes:
        return None
    if not all(
        is_account_resolution_error(getattr(tr, "error", "") or "")
        for tr in failures
    ):
        return None
    entities = getattr(execution_plan, "extracted_entities", None) or {}
    if str(entities.get("create_account") or "").strip():
        return None
    if gap_already_asked(prior_qa) or len(prior_qa) >= MODEL_MAX_CLARIFICATION_ROUNDS:
        return None
    gap = gap_from_execution_failure(
        [getattr(tr, "error", "") or "" for tr in failures],
        entities=entities,
        intent=getattr(execution_plan, "intent", "") or "",
    )
    if gap is None:
        return None
    question = question_for_gap(gap)
    try:
        clarification = await create_clarification(
            session_id=session_id,
            question=question,
            required_fields=["account_configuration"],
        )
        question = clarification.get("question", question)
    except Exception as exc:  # noqa: BLE001 — asking is not optional
        log.warning(
            "agent.account_rescue_clarification_failed",
            session_id=str(session_id),
            error=str(exc)[:200],
        )
    options = options_for_gap(gap)
    await _update_status(session_id, ExecutionStatus.AWAITING_CLARIFICATION)
    await _log_step(session_id, "AWAITING_CLARIFICATION", {
        "source": "account_creation_rescue",
        "gap": {"name": gap.name, "account_type": gap.account_type,
                "source": gap.source},
        "question": question[:300],
    })
    return AgentResponse(
        status=ExecutionStatus.AWAITING_CLARIFICATION,
        execution_id=session_id,
        question=question,
        options=options,
        question_options=[[{"value": o, "label": o} for o in options]],
        required_information=["account_configuration"],
        requires_user_input=True,
    )


# ---------------------------------------------------------------------------
# deterministic report fast-path.  Standard reports and
# simple lookups skip the LLM entirely: the planner's intent is enough to
# call the read-only reporting tools directly and format the rows with
# deterministic code.  Step data records BYPASS_LLM so the audit trail
# honestly shows no model was involved.
# ---------------------------------------------------------------------------
_REPORT_FAST_TOOLS = {
    "generate_trial_balance": "get_trial_balance",
    "generate_balance_sheet": "get_balance_sheet",
    "generate_profit_loss": "get_profit_loss",
    "generate_cash_flow": "get_cash_flow",
    "generate_general_ledger": "get_general_ledger",
    "list_expenses": "list_expenses",
    "list_bank_accounts": "list_bank_accounts",
}
_PARTY_LEDGER_FAST = {
    # intent: (search tool, ledger tool, entity field, id argument)
    "customer_balance": ("search_customer", "get_customer_ledger", "customer_name", "customer_id"),
    "supplier_balance": ("search_supplier", "get_supplier_ledger", "supplier_name", "supplier_id"),
}
# Tiered routing: these intents are simple lookups.  When
# they reach the model at all (fast-path did not apply), they get a light
# output budget instead of the full mutation-sized one.
_LIGHT_BUDGET_INTENTS = set(_REPORT_FAST_TOOLS) | set(_PARTY_LEDGER_FAST)
_FAST_PATH_NUM_KEYS = (
    "debit", "credit", "total", "balance", "amount", "net",
    "inflow", "outflow", "opening_balance", "closing_balance",
)

_FAST_PATH_TITLES = {
    "generate_trial_balance": "Trial Balance",
    "generate_balance_sheet": "Balance Sheet",
    "generate_profit_loss": "Profit & Loss",
    "generate_cash_flow": "Cash Flow",
    "generate_general_ledger": "General Ledger",
    "list_expenses": "Expense Details",
    "list_bank_accounts": "Bank Accounts",
    "customer_balance": "Customer Ledger",
    "supplier_balance": "Supplier Ledger",
}


def _fmt_num(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_report_rows(rows: Any) -> str:
    """Deterministic row rendering for the fast-path (never an LLM)."""
    lines: List[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = (
            row.get("account_name") or row.get("name") or row.get("description")
            or row.get("account") or "row"
        )
        code = row.get("account_code") or row.get("code")
        head = f"{code} {label}" if code else str(label)
        parts: List[str] = [
            f"{k.replace('_', ' ')} {_fmt_num(row[k])}"
            for k in _FAST_PATH_NUM_KEYS
            if row.get(k) is not None
        ]
        extra = row.get("activity") or row.get("type") or row.get("status")
        if extra:
            parts.insert(0, str(extra))
        lines.append(f"- {head}" + (": " + "; ".join(parts) if parts else ""))
    return "\n".join(lines)


def _party_exact_matches(data: Any, name: str) -> List[Dict[str, Any]]:
    """Exact case-insensitive name matches from a party search result."""
    if isinstance(data, dict):
        rows = (
            data.get("results") or data.get("customers")
            or data.get("suppliers") or data.get("data") or []
        )
    else:
        rows = data or []
    low = (name or "").strip().lower()
    return [
        r for r in rows
        if isinstance(r, dict)
        and (r.get("name") or "").strip().lower() == low
    ]


async def _load_org_preferences(organization_id: uuid.UUID) -> Dict[str, str]:
    """Load learned org preferences; best-effort, {} on failure."""
    try:
        from app.services import preference_service

        return await preference_service.get_all_preferences(organization_id)
    except Exception as exc:  # noqa: BLE001 - defaults must never block a run
        log.warning("agent.org_preferences_load_failed", error=str(exc)[:200])
        return {}


async def _preamble_side_effects(
    *,
    session_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    prior_qa: List[Dict[str, str]],
) -> Dict[str, str]:
    """P0-④ (forensic report ④): preamble side-effects as ONE gather.

    (1) SUPERSEDE — a new request closes this user's earlier non-terminal
        runs; without it the abandoned row stays WAITING_FOR_USER for ever
        and reattach reports a live "waiting for your answer" banner right
        after a COMPLETED run. Best-effort: never blocks the run.
    (2) HISTORY SEED — carry this conversation's answered Q&A into the new
        session (BULK — one round-trip, P0-④) so nothing is re-asked.
    (3) PREFERENCE CAPTURE — remember the last preference-shaped answer
        (best-effort, never blocks the run).
    (4) ORG DEFAULTS — learned preferences for reasoning/planner/context.

    All four are independent once session_id exists: 4 sequential RTs → 1
    (measured preamble ~4.2s; report target ~1.5s). Ordering that depends
    on session_id is preserved (the session row is created before this is
    awaited); AWAITING_*/FAILED durable writes happen LATER and stay
    awaited inline in _log_step. Returns (4)'s dict for every consumer.
    """
    coros: List[Any] = [
        _close_superseded_sessions(
            organization_id, user_id, keep_session_id=session_id
        ),
        seed_clarification_history(session_id, prior_qa),
        _load_org_preferences(organization_id),
    ]
    if prior_qa:
        last_qa = prior_qa[-1] or {}
        from app.services import preference_service

        coros.append(
            preference_service.record_answer_preference(
                organization_id,
                last_qa.get("question") or "",
                last_qa.get("answer") or "",
            )
        )
    results = await asyncio.gather(*coros)
    # Positional: org-preferences is always the third coroutine.
    org_prefs = results[2]
    return org_prefs if isinstance(org_prefs, dict) else {}


def _preference_memory_hint(
    org_prefs: Dict[str, str],
    questions: List[str],
) -> str:
    """Clarification-memory hint.

    When a pending question is preference-shaped AND the org already has a
    learned value, offer it inside the question text ("previously: cash -
    reply SAME to reuse") - one round, no extra calls.
    """
    from app.services import preference_service

    for q in questions or []:
        key = preference_service.preference_key_for_question(q)
        if key and org_prefs.get(key):
            return f"previously: {org_prefs[key]} - reply SAME to reuse"
    return ""


async def _try_report_fast_path(
    *,
    execution_plan: ExecutionPlan,
    session_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    auth: Optional[AuthContext],
) -> Optional[AgentResponse]:
    """Run a deterministic report/lookup without any LLM involvement.

    Returns ``None`` whenever the request is NOT a plain deterministic
    report (unknown shape, missing/ambiguous party) so the normal model
    path handles it - the fast-path never guesses.
    """
    intent = execution_plan.intent
    calls: List[ToolCall] = []

    tool_slug = _REPORT_FAST_TOOLS.get(intent)
    if tool_slug:
        args: Dict[str, Any] = {}
        ents = execution_plan.extracted_entities or {}
        if intent in ("generate_general_ledger", "list_expenses"):
            if ents.get("date_from"):
                args["from_date"] = ents["date_from"]
            if ents.get("date_to"):
                args["to_date"] = ents["date_to"]
        calls.append(ToolCall(tool_name=tool_slug, arguments=args))
    elif intent in _PARTY_LEDGER_FAST:
        search_slug, ledger_slug, name_field, id_arg = _PARTY_LEDGER_FAST[intent]
        name = (execution_plan.extracted_entities or {}).get(name_field)
        if not name:
            return None  # no party named - the normal path resolves/asks
        search_res = await route_tool_call(
            ToolCall(tool_name=search_slug, arguments={"query": str(name), "limit": 25}),
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            auth=auth,
        )
        matches = (
            _party_exact_matches(search_res.data, str(name))
            if search_res.success else []
        )
        if len(matches) != 1:
            # Zero or multiple matches: NEVER first-hit.  The normal model
            # path surfaces the ambiguity to the user.
            return None
        calls.append(ToolCall(
            tool_name=ledger_slug,
            arguments={id_arg: str(matches[0]["id"])},
        ))
    else:
        return None

    await _log_step(session_id, "EXECUTING_TOOLS", {
        "BYPASS_LLM": True,
        "fast_path": True,
        "tools": [c.tool_name for c in calls],
    })

    results: List[ToolResult] = []
    for call in calls:
        results.append(await route_tool_call(
            call,
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            auth=auth,
        ))

    failed = [r for r in results if not r.success]
    if failed:
        await _log_step(session_id, "TOOL_FAILURE", {
            "BYPASS_LLM": True,
            "tool": failed[0].tool_name,
            "error": (failed[0].error or "")[:300],
        })
        await _update_status(session_id, ExecutionStatus.FAILED)
        await create_execution_result(
            session_id=session_id,
            result_data={
                "error": failed[0].error or "report failed",
                "tool": failed[0].tool_name,
                "BYPASS_LLM": True,
            },
            summary=f"Report failed: {failed[0].tool_name}",
            action_type=intent,
            verification_status="FAILED",
            status="FAILED",
        )
        return AgentResponse(
            status=ExecutionStatus.FAILED,
            execution_id=session_id,
            action=intent,
            summary=f"The {intent} could not be completed: {failed[0].error}",
            verification_status="FAILED",
            data={"bypass_llm": True},
        )

    all_rows: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r.data, list):
            all_rows.extend(r.data)
        elif isinstance(r.data, dict):
            inner = r.data.get("rows") or r.data.get("results") or r.data.get("data")
            if isinstance(inner, list):
                all_rows.extend(inner)
    rows_text = _format_report_rows(all_rows)
    title = _FAST_PATH_TITLES.get(intent, intent.replace("_", " ").title())
    summary = (
        f"{title} - {len(all_rows)} rows (deterministic fast-path, no LLM used)"
        + (f":\n{rows_text}" if rows_text else "")
    )
    if intent == "list_expenses" and all_rows:
        total = 0.0
        for row in all_rows:
            try:
                total += float(row.get("total") or 0)
            except (TypeError, ValueError):
                continue
        summary = (
            f"{title} - {len(all_rows)} expenses, total {total:,.2f}"
            + (f":\n{rows_text}" if rows_text else "")
        )

    await _log_step(session_id, "COMPLETED", {
        "BYPASS_LLM": True,
        "fast_path": True,
        "rows": len(all_rows),
    })
    await create_execution_result(
        session_id=session_id,
        result_data={
            "summary": summary,
            "tool_count": len(results),
            "rows": len(all_rows),
            "BYPASS_LLM": True,
        },
        summary=summary,
        action_type=intent,
        verification_status="UNVERIFIED",
        status="COMPLETED",
    )
    return AgentResponse(
        status=ExecutionStatus.COMPLETED,
        execution_id=session_id,
        action=intent,
        summary=summary,
        verification_status="UNVERIFIED",
        data={"bypass_llm": True, "rows": len(all_rows)},
    )


def _reasoning_produced_interpretation(reasoning: Any) -> bool:
    """P1-⑥ (forensic latency report ⑥): has THIS request's reasoning stage
    already produced a usable interpretation of the user's sentence?

    True only when the loop RAN (a real outcome exists), did not fail at
    the provider, and returned a non-empty ``understanding`` dict — i.e.
    re-asking the semantic layer for a fresh interpretation would be the
    report's "full interpretation 2x" waste (measured 1-8s on degraded
    turns).
    """
    return bool(
        reasoning is not None
        and not getattr(reasoning, "provider_failed", False)
        and getattr(reasoning, "understanding", None)
    )


def _prefill_from_reasoning(reasoning: Any, preliminary: Any) -> Dict[str, Any]:
    """P1-⑥: planner prefill derived from the reasoning outcome + the SAME
    deterministic literals both stages saw (preliminary extraction).

    Only literal, traceable values are passed — never facts invented from
    prose. ``semantic_intent`` is deliberately absent: its sole consumers
    are the AI_PERCEPTION log and planner.py's whitelist (which then falls
    back to its regex intent exactly as the existing reasoning-skip paths
    do today — traced before switching, per the report).
    """
    literals = (preliminary or {}).get("literals") or {}
    prefill: Dict[str, Any] = {}
    for key in ("amount", "transaction_date", "item_description"):
        value = literals.get(key)
        if value is not None and value != "":
            prefill[key] = value
    return prefill


async def _resolve_gate_questions(
    *,
    organization_id: uuid.UUID,
    execution_plan: ExecutionPlan,
) -> tuple:
    """P1-⑨ (forensic latency report §5): the four clarification gates
    (party / settlement / catalog / revenue-ledger) are pure read-only
    lookups — run them CONCURRENTLY, then ask in the original deterministic
    order (party → settlement → catalog → revenue) so observable behaviour
    is unchanged while ~3 sequential RTs collapse to ~1 (−0.1-0.3s).
    """
    return tuple(
        await asyncio.gather(
            _party_resolution_question(
                organization_id=organization_id, execution_plan=execution_plan
            ),
            _settlement_check_question(
                organization_id=organization_id, execution_plan=execution_plan
            ),
            _catalog_check_question(
                organization_id=organization_id, execution_plan=execution_plan
            ),
            _revenue_ledger_review_gate(
                organization_id=organization_id, execution_plan=execution_plan
            ),
        )
    )


def _record_phase_timing(
    store: Dict[str, Any], t0: float, marker: str, extra: Dict[str, Any]
) -> None:
    """P2-⑪: mirror one phase marker into the request timings dict.

    Values are SQL-friendly scalars (bounded strings) so
    ``result_payload.timings`` stays a flat JSON object per request —
    p50/p95 per stage = percentile over these after every change ships.
    """
    snapshot: Dict[str, Any] = {"elapsed_ms": int((time.monotonic() - t0) * 1000)}
    for key, value in (extra or {}).items():
        snapshot[key] = (
            value
            if isinstance(value, (int, float, bool, type(None)))
            else str(value)[:120]
        )
    store[marker] = snapshot


# P2-⑫: whitelists for the reasoning prompt's ORGANIZATION PROFILE /
# ACCOUNTING PERIOD blocks (full rows still flow to build_context — only
# the prompt projection is slimmed).
_ORG_PROFILE_FIELDS = (
    "name", "legal_name", "currency", "base_currency", "country",
    "tax_number", "email", "phone", "address",
)
_FY_FIELDS = ("label", "name", "code", "start_date", "end_date", "is_current")
_PERIOD_FIELDS = ("label", "name", "start_date", "end_date", "status", "is_open")


def _slim_row(
    row: Optional[Dict[str, Any]], fields: Sequence[str]
) -> Dict[str, Any]:
    """Whitelist projection for prompt rendering (never raw timestamps)."""
    if not row:
        return {}
    return {k: row[k] for k in fields if row.get(k) is not None}


def _flatten_period(
    fy: Optional[Dict[str, Any]], period: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Flat, prompt-friendly {fy_*, period_*} dict (empty when unknown)."""
    out: Dict[str, Any] = {}
    for key, value in (fy or {}).items():
        out[f"fy_{key}"] = value
    for key, value in (period or {}).items():
        out[f"period_{key}"] = value
    return out


async def _load_org_facts(
    organization_id: uuid.UUID,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """P2-⑫: organization + financial year + open accounting period.

    The reasoning prompt rendered ORGANIZATION PROFILE / ACCOUNTING PERIOD
    as "(none provided)" — risking a wasted evidence round on org/period
    kinds the pipeline could have supplied. Started as a BACKGROUND task at
    execute() entry so it runs concurrently with the preamble (zero added
    serial round-trips); build_context receives the same rows (moved, not
    added — total query count unchanged). Any failure degrades to
    ``(None, None, None)`` and every consumer falls back to fetching (or
    rendering empty) exactly as before.
    """
    from app.repositories import organization_repository

    try:
        org, fy, period = await asyncio.gather(
            organization_repository.get_organization(
                organization_id=organization_id
            ),
            organization_repository.get_current_financial_year(organization_id),
            organization_repository.get_open_accounting_period(organization_id),
        )
        return org, fy, period
    except Exception as exc:  # noqa: BLE001 — facts are best-effort
        log.warning("agent.org_facts_load_failed", error=str(exc)[:200])
        return None, None, None


def _flush_cap_for(close_marker: Optional[str]) -> Optional[float]:
    """P2-⑮ flush policy: ~250ms ONLY for PARKING responses.

    Audit-loss review (report ⑮): the durable AWAITING_*/FAILED rows are
    awaited inline in _log_step and can never be lost; a capped flush only
    risks NON-durable progress rows beyond the cap on a hard serverless
    freeze — observability, never correctness (and the P1-⑤ memo load
    fails soft to a plain refetch). Terminal (COMPLETED/FAILED/REJECTED/
    CANCELLED) and unknown markers keep the report's leave-as-is default:
    the FULL drain.
    """
    if close_marker in ("AWAITING_CLARIFICATION", "AWAITING_CONFIRMATION"):
        return 0.25
    return None


async def _attach_client_ttfb(
    *,
    session_id: uuid.UUID,
    ttfb_ms: float,
    transport: str,
    organization_id: uuid.UUID,
) -> bool:
    """P2-⑪: persist the browser's TTFB as a CLIENT_TTFB step.

    Cold start happens BEFORE the server's ``started_at`` — the browser is
    the only place it is visible. Org-scoped (the session must belong to
    the caller's organisation) and best-effort: returns False instead of
    raising, so observability can never break a client. CLIENT_TTFB is
    unknown to _STEP_TYPE_MAP — ``description`` keeps the marker for SQL
    and the phase defaults to REASON.
    """
    try:
        session = await fetch_one(
            "ai_execution_sessions",
            filters={
                "id": str(session_id),
                "organization_id": str(organization_id),
            },
        )
        if not session:
            return False
        await create_execution_step(
            session_id=session_id,
            step_type="CLIENT_TTFB",
            step_data={
                "ttfb_ms": max(0, int(ttfb_ms)),
                "transport": str(transport)[:16],
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 — observability never fails
        log.warning("agent.client_ttfb_failed", error=str(exc)[:200])
        return False


def _resolve_declared_aliases_from_evidence(
    calls: List[Any],
    evidence_results: List[Any],
) -> List[Dict[str, Any]]:
    """P1-⑤: replace DECLARED party name-aliases in the frozen plan with
    canonical ids already present in THIS request's own evidence.

    Zero extra queries — the reasoning layer's ``parties`` rows (role, id,
    name) were fetched during this turn. Exact single match per declared
    alias AND role only; otherwise the argument is untouched and the
    approval turn's materialization resolves it exactly as before
    (fail-toward-existing-behaviour). The substitution is recorded as a
    durable step for audit.
    """
    from app.plan_materialization import DECLARED_REFERENCES

    rows: List[Dict[str, Any]] = []
    for res in evidence_results or ():
        if (
            getattr(res, "error", None) is None
            and getattr(res, "kind", "") == "parties"
        ):
            rows.extend(r for r in (res.records or []) if isinstance(r, dict))
    if not rows:
        return []
    replacements: List[Dict[str, Any]] = []
    for call in calls or ():
        tool = getattr(call, "tool_name", None)
        args = getattr(call, "arguments", None)
        if not tool or not isinstance(args, dict):
            continue
        for param, spec in (DECLARED_REFERENCES.get(tool) or {}).items():
            if spec.role not in ("customer", "supplier") or args.get(param):
                continue
            alias = next((a for a in spec.aliases if args.get(a)), None)
            if alias is None:
                continue
            name = str(args.get(alias) or "").strip()
            matches = [
                r
                for r in rows
                if str(r.get("name") or "").strip().lower() == name.lower()
                and str(r.get("role") or "").strip().lower() == spec.role
                and r.get("id")
            ]
            if len(matches) != 1:
                continue  # 0 or ambiguous -> materialization handles it
            args[param] = str(matches[0]["id"])
            args.pop(alias, None)
            replacements.append(
                {
                    "tool": tool,
                    "parameter": param,
                    "alias": alias,
                    "requested": name,
                    "resolved_id": str(matches[0]["id"]),
                }
            )
    return replacements


async def execute(
    *,
    user_message: str,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    auth: Optional[AuthContext] = None,
    conversation_id: Optional[str] = None,
    clarification_history: Optional[List[Dict[str, str]]] = None,
    confirmation_granted: bool = False,
    attachments: Optional[List[AttachmentRef]] = None,
    approved_tool_calls: Optional[List[ToolCall]] = None,
    confirmed_intent: Optional[str] = None,
) -> AgentResponse:
    """Main entry point — process a user message through the full agent lifecycle.

    ``clarification_history`` carries prior Q&A from earlier rounds of the
    SAME conversation.  It is (a) merged into entity extraction so answered
    questions are never re-asked, and (b) forwarded to Gemini as context.

    ``confirmation_granted`` is set by ``resume_with_confirmation`` after the
    user approved the pending confirmation, so the PHASE 5 gate does not
    re-raise a new confirmation and execution can actually proceed.

    ``approved_tool_calls`` is the plan snapshot the user approved (migration
    079).  When present the tool selection is NOT re-derived — neither the
    deterministic fast path nor the LLM planning call runs — so the executed
    plan is exactly what the user reviewed.

    ``confirmed_intent`` is the confirmation's ``action_type`` — the intent
    the ORIGINAL turn planned and the user approved.  It is re-applied over
    the keyword planner on approved turns (the semantic prefill those turns
    deliberately skip may be what gave the request its intent), so Phase 7/8
    verification keys on the APPROVED economic event, never on a keyword
    guess.
    """

    session_id: Optional[uuid.UUID] = None
    prior_qa: List[Dict[str, str]] = clarification_history or []
    _t0 = time.monotonic()
    # P2-⑪ (forensic report ⑪): structlog phase timings are LOST on Vercel
    # (runtime-logs 404, DEFECT3) — mirror every marker into a per-request
    # dict carried on this task's context; create_execution_result persists
    # it as result_payload.timings (spawned/zero critical-path cost).
    _timings: Dict[str, Any] = {}
    REQUEST_TIMINGS.set(_timings)

    def _phase_elapsed(marker: str, **extra) -> None:
        _record_phase_timing(_timings, _t0, marker, extra)
        log.info(
            "agent.phase_timing",
            phase=marker,
            elapsed=round(time.monotonic() - _t0, 2),
            **extra,
        )

    try:
        # P2-⑫: org/period facts load CONCURRENTLY with the whole preamble
        # (normally finished before the reasoning loop starts — zero added
        # serial round-trips; failure degrades to None below).
        _org_facts_task = asyncio.create_task(_load_org_facts(organization_id))
        # ---- PHASE 1: RECEIVED -------------------------------------------
        session = await create_execution_session(
            organization_id=organization_id,
            user_id=user_id,
            user_message=user_message,
            conversation_id=conversation_id,
        )
        session_id = uuid.UUID(session["id"])
        # P2-⑪: wall-clock start for this session → every step row gets
        # elapsed_ms (stamped synchronously in _log_step, before any spawn).
        if len(_STEP_START) > 512:
            _STEP_START.clear()
        _STEP_START[str(session_id)] = time.monotonic()
        await _log_step(session_id, "RECEIVED", {"message": user_message})

        # P0-④ (forensic report ④): preamble side-effects as ONE gather —
        # supersede abandoned runs + BULK-seed this conversation's Q&A +
        # capture the last preference-shaped answer + load org defaults
        # were 4 sequential round-trips before thinking (measured preamble
        # ~4.2s; report target ~1.5s). Ordering only depends on session_id
        # (created above); AWAITING_*/FAILED durable writes happen later
        # and stay awaited inline in _log_step. Returns org_prefs for the
        # reasoning/planner/build_context consumers — the old sequential
        # load after document extraction is gone.
        org_prefs = await _preamble_side_effects(
            session_id=session_id,
            organization_id=organization_id,
            user_id=user_id,
            prior_qa=prior_qa,
        )

        # ---- PHASE 1b: DOCUMENT / VISION EXTRACTION ------------------------
        # Attachments are processed in-memory by the vision-capable Qwen
        # chain (qwen3-vl-*). The structured extraction becomes FACTUAL
        # CONTEXT appended to the user message — the ERP Agent (planner,
        # classifier, accounting engine), NOT the vision model, decides
        # what the document means operationally.
        if attachments:
            from app.document_extractor import (
                DocumentValidationError,
                extract_attachments,
            )
            try:
                document_context = await extract_attachments(
                    attachments, orchestrator=get_client()
                )
            except DocumentValidationError as exc:
                # User-fixable upload problem — never a provider fallback.
                await _update_status(session_id, ExecutionStatus.FAILED)
                await _log_step(session_id, "FAILED", {"reason": str(exc)[:300]})
                return AgentResponse(
                    status=ExecutionStatus.FAILED,
                    execution_id=session_id,
                    summary=str(exc),
                )
            if document_context:
                user_message = (
                    f"{user_message}\n\n[Attached document information]\n"
                    f"{document_context}"
                )
                # Persist the enriched request so the extracted facts
                # survive clarification/confirmation resume (continuity
                # rule): resume_with_clarification / resume_with_confirmation
                # re-enter execute() with session.user_request as the
                # message — the document context must still be there.
                await update_one(
                    "ai_execution_sessions",
                    row_id=session_id,
                    data={"user_request": user_message},
                )
                await _log_step(session_id, "DOCUMENT_EXTRACTED", {
                    "attachments": len(attachments),
                    "context_chars": len(document_context),
                })

        # ---- PHASE 2: INTERPRETING / PLANNING ----------------------------
        await _update_status(session_id, ExecutionStatus.INTERPRETING)
        # learned org defaults feed the planner as answered-for entities
        # (an explicit user value always wins). P0-④: loaded concurrently
        # in the preamble gather above — no sequential wait here.
        # ---- PHASE 2a: AI-FIRST SEMANTIC UNDERSTANDING ---
        # The user's request goes to the LLM FIRST. The semantic layer
        # (app/semantic_layer.py) understands the BUSINESS MEANING in any
        # natural wording, grounds every fact against the user's own words
        # (verbatim names, traceable numbers/dates, validated enums), and
        # normalization maps that meaning into the ERP's deterministic
        # vocabulary (activity x terms -> intent; role -> party field). The
        # planner then computes missing-information analysis against the
        # MERGED facts, so the questionnaire contains ONLY genuinely
        # missing/ambiguous fields. The keyword regex extractor is the
        # FALLBACK: provider down / timeout / bad JSON -> {} -> regex-only
        # behaviour, unchanged. Deterministic safeguards (auth, validation,
        # balancing, idempotency, confirmation) are NOT AI. Batch
        # (enumerated) requests keep their per-item deterministic protocol.
        # ---- PHASE 2a0: PRELIMINARY EXTRACTION + LLM ACCOUNTING REASONING --
        #   Python extracts ONLY the literal values from the
        # user's own words and labels them PRELIMINARY.  The LLM is then given
        # the request + that preliminary extraction + a closed catalog of
        # read-only evidence lookups, and it decides what to inspect, what to
        # ask, or what to propose.  Python's role in this stage is purely
        # enforcement: evidence kinds/arguments are validated, every read is
        # organization-scoped and permission-checked, proposals must be
        # complete, and nothing executes here.
        #
        # Nothing below replaces the existing pipeline: when the provider is
        # unavailable, returns no parsable decision, or the request is a batch,
        # the previous behaviour runs unchanged.
        from app.accounting_reasoning import (
            COMPLETE as _R_COMPLETE,
            NEEDS_INPUT as _R_NEEDS_INPUT,
            PROPOSAL as _R_PROPOSAL,
            REFUSAL as _R_REFUSAL,
            ReasoningFacts as _ReasoningFacts,
            preliminary_extraction as _preliminary_extraction,
            proposed_mutation_tools as _proposed_mutation_tools,
            refusal_text as _refusal_text,
            run_reasoning_loop as _run_reasoning_loop,
        )
        from app.config import get_settings as _get_settings

        _settings = _get_settings()
        _preliminary = _preliminary_extraction(user_message)
        await _log_step(session_id, "PRELIMINARY_EXTRACTION", _preliminary)

        _reasoning = None
        # P2-⑫: harvest the background org/period facts (started at entry;
        # normally already finished during the preamble — no added serial
        # round-trip; None rows fall back downstream exactly as before).
        _org_row, _fy_row, _period_row = await _org_facts_task
        _reasoning_calls: Optional[List[ToolCall]] = None
        from app.planner import split_batch_request as _split_batch_now

        # P0-① (forensic latency report): an APPROVED turn re-enters with a
        # FROZEN plan — nothing downstream of the approved-reuse branch
        # consults a fresh reasoning outcome, so running the loop here was
        # 10-30s of pure discarded work per approval, and its NEEDS_INPUT /
        # REFUSAL early-returns could park or REJECT a run the user had
        # already confirmed.  Skipped entirely on approved turns.
        if (
            getattr(_settings, "accounting_reasoning_enabled", False)
            and not _split_batch_now(user_message)
            and approved_tool_calls is None
        ):
            # The model may only propose names from the TRUSTED registry, so it
            # is given exactly that vocabulary — Python decides which tools
            # exist, the model decides which one the event needs.
            from app.tools import list_tools as _list_registered_tools
            from app.tools import tool_contracts as _tool_argument_contracts

            # P1-⑤: seed the loop with this conversation's validated prior
            # evidence (the DATABASE is the memo carrier — serverless-safe:
            # any instance, any turn). Freshness/invalidation is enforced in
            # _load_prior_evidence; zero cost when no fresh snapshot exists.
            _prior_evidence = (
                await _load_prior_evidence(
                    conversation_id=conversation_id,
                    organization_id=organization_id,
                    current_session_id=session_id,
                )
                if conversation_id
                else []
            )
            _reasoning = await _run_reasoning_loop(
                _ReasoningFacts(
                    user_request=user_message,
                    conversation_history=list(prior_qa),
                    preliminary=_preliminary,
                    org_policies=dict(org_prefs or {}),
                    today=_preliminary.get("today", ""),
                    # P2-⑫: real org/period instead of "(none provided)" —
                    # those blocks risked a wasted evidence round on
                    # org/period kinds (report §2). Rows were loaded in the
                    # background at entry; slimmed for the prompt only.
                    organization=_slim_row(_org_row, _ORG_PROFILE_FIELDS),
                    accounting_period=_flatten_period(_fy_row, _period_row),
                ),
                organization_id=organization_id,
                auth=auth,
                session_id=session_id,
                orchestrator=get_client(),
                offered_tools=list(_list_registered_tools()),
                # The ARGUMENT contracts of the tools that will execute the
                # plan.  The model is offered tool NAMES only, so Python must
                # reject an un-bindable argument set BEFORE the user is asked to
                # approve it (2026-09-20: an approved create_invoice plan died at
                # call-binding time).  See app/tool_contract.py.
                tool_contracts=_tool_argument_contracts(),
                max_rounds=int(
                    getattr(_settings, "accounting_reasoning_max_rounds", 3)
                ),
                step_logger=lambda event, payload: _spawn_step_write(
                    _log_step(session_id, event, payload)
                ),
                # P1-⑤: prior_evidence seeds the in-loop cache (P0-③ keying)
                # so a re-requested kind is served with zero database reads.
                prior_evidence=_prior_evidence,
                # P1-⑩: speculative evidence prefetch ∥ round-1 model call
                # (report §5) — flag-controlled, default from settings.
                prefetch_enabled=bool(
                    getattr(_settings, "accounting_reasoning_prefetch", True)
                ),
            )
            # Defense in depth: run_reasoning_loop() contractually returns a
            # populated ReasoningOutcome on every reachable terminal path.
            # If the contract is ever violated, fail CONTROLLED here — never
            # crash on ``as_dict()``, never continue to planning, a confirmation
            # snapshot or execution from a missing reasoning result, and
            # never let the generic handler mask a programming error.
            if _reasoning is None:
                log.error(
                    "agent.reasoning_result_missing",
                    session_id=str(session_id),
                )
                await _update_status(session_id, ExecutionStatus.FAILED)
                await _log_step(session_id, "FAILED", {
                    "reason": "reasoning_result_missing",
                    "stage": "reasoning",
                    "controlled": True,
                })
                return AgentResponse(
                    status=ExecutionStatus.FAILED,
                    execution_id=session_id,
                    summary=(
                        "The accounting reasoning stage failed unexpectedly. "
                        "Nothing was recorded yet. Please send your request "
                        "again — everything you have already told me is kept "
                        "in this conversation."
                    ),
                )
            _reasoning_step = _reasoning.as_dict()
            # P1-⑤: carry the full (bounded, cacheable) evidence rows on the
            # durable step — this is the memo the NEXT turn of this
            # conversation seeds from (freshness is checked at load; the
            # step writer raises its cap ONLY for payloads with this key).
            from app.accounting_reasoning import serialize_evidence_memo

            _reasoning_step["evidence_full"] = serialize_evidence_memo(
                _reasoning.evidence_results
            )
            await _log_step(session_id, "ACCOUNTING_REASONING", _reasoning_step)
            _phase_elapsed(
                "accounting_reasoning.done",
                status=_reasoning.status,
                rounds=_reasoning.rounds,
            )

        # The provider was CALLED in this request and failed (timeout, error or
        # unparseable answer).  Retrying the same chain twice more (perception,
        # then planning) only multiplies the user-visible wait and risks a
        # stale deterministic route.  The request is closed honestly instead.
        _provider_down = bool(
            _reasoning is not None
            and _reasoning.provider_failed
            and getattr(_reasoning, "provider_attempted", False)
        )
        if _provider_down:
            await _log_step(session_id, "REASONING_DEGRADED", {
                "reason": "provider_unavailable",
                "rounds": _reasoning.rounds,
                "note": (
                    "the reasoning round failed; no second identical provider "
                    "round-trip is attempted in this request"
                ),
            })

        if _reasoning is not None and not _reasoning.provider_failed:
            if _reasoning.status == _R_REFUSAL:
                _text = _refusal_text(_reasoning.refusal) or (
                    "This request cannot be executed safely as stated."
                )
                await _update_status(session_id, ExecutionStatus.REJECTED)
                await _log_step(session_id, "REFUSED_BY_REASONING", {"reason": _text})
                return AgentResponse(
                    status=ExecutionStatus.REJECTED,
                    execution_id=session_id,
                    summary=_text,
                )
            if _reasoning.status == _R_COMPLETE:
                _text = _refusal_text(_reasoning.refusal) or (
                    "The records already reflect this request."
                )
                await _update_status(session_id, ExecutionStatus.COMPLETED)
                await _log_step(session_id, "ALREADY_REFLECTED_IN_BOOKS", {
                    "understanding": _reasoning.understanding,
                })
                return AgentResponse(
                    status=ExecutionStatus.COMPLETED,
                    execution_id=session_id,
                    summary=_text,
                )
            if _reasoning.status == _R_NEEDS_INPUT and _reasoning.question:
                # The LLM asked a question GROUNDED in the records it just
                # inspected — never a template question.
                _question = str(_reasoning.question.get("text") or "").strip()
                if _question:
                    _needed = [
                        str(f.get("fact") or "information")
                        for f in (_reasoning.missing_facts or [])
                    ] or ["information"]
                    _clar = await create_clarification(
                        session_id=session_id,
                        question=_question,
                        required_fields=_needed,
                    )
                    await _update_status(
                        session_id, ExecutionStatus.AWAITING_CLARIFICATION
                    )
                    await _log_step(session_id, "AWAITING_CLARIFICATION", {
                        "source": "accounting_reasoning",
                        "question": _question[:500],
                        "evidence": _reasoning.as_dict().get("evidence"),
                    })
                    # 360° questionnaire: per-numbered-line tap-chips ride
                    # along as question_options (aligned by line index; the
                    # frontend renders one answer box + chips per line and
                    # still accepts free text).
                    _q_parts = _reasoning.question.get("options_per_part") or []
                    _q_opts = [
                        [
                            {"value": str(o), "label": str(o)}
                            for o in (part or [])
                        ]
                        for part in _q_parts
                        if isinstance(part, list)
                    ] or None
                    return AgentResponse(
                        status=ExecutionStatus.AWAITING_CLARIFICATION,
                        execution_id=session_id,
                        question=_clar.get("question", _question),
                        options=_reasoning.question.get("options") or None,
                        question_options=_q_opts,
                        required_information=_needed,
                        requires_user_input=True,
                    )
            if _reasoning.status == _R_PROPOSAL and _reasoning.proposal:
                _mutations = _proposed_mutation_tools(_reasoning)
                if _mutations:
                    _reasoning_calls = [
                        ToolCall(
                            tool_name=call["tool_name"],
                            arguments=dict(call.get("arguments") or {}),
                        )
                        for call in _mutations
                    ]
                    await _log_step(session_id, "REASONING_PROPOSAL_ACCEPTED", {
                        "interpretation": (
                            _reasoning.proposal.get("interpretation") or ""
                        )[:500],
                        "tools": [c.tool_name for c in _reasoning_calls],
                        "not_affected": _reasoning.proposal.get("not_affected"),
                        "uncertainty": _reasoning.proposal.get(
                            "unresolved_uncertainty"
                        ),
                        "confirmation": _reasoning.proposal.get("confirmation"),
                    })

        from app.semantic_layer import extract_semantic_facts, normalize_to_erp
        from app.planner import split_batch_request as _split_batch

        _ai_prefill: Dict[str, Any] = {}
        # P1-⑥ (forensic latency report ⑥): the semantic layer and the
        # reasoning stage BOTH interpret the same sentence. When reasoning
        # already produced an understanding, a fresh semantic LLM call is
        # the report's "full interpretation 2x" waste (1-8s on degraded
        # turns). _would_interpret is byte-for-byte the pre-P1-⑥ condition —
        # the change below only reroutes its TRUE branch; semantic stays for
        # provider-down / reasoning-skipped / understanding-less paths.
        _would_interpret = (
            not _split_batch(user_message)
            and _reasoning_calls is None
            # P0-①: approved turns already carry a validated plan; a second
            # LLM interpretation of the original sentence is pure waste.
            and approved_tool_calls is None
            and not _provider_down
            and not (
                _reasoning is not None
                and _reasoning.usable
                and _reasoning.status in (_R_NEEDS_INPUT, _R_COMPLETE, _R_REFUSAL)
            )
        )
        if _would_interpret and _reasoning_produced_interpretation(_reasoning):
            # P1-⑥: planner prefill derived from the reasoning outcome
            # instead of a fresh semantic LLM call.
            _ai_prefill = _prefill_from_reasoning(_reasoning, _preliminary)
            await _log_step(session_id, "AI_PERCEPTION", {
                "facts": sorted(_ai_prefill.keys()),
                "intent": None,
                "ambiguous": False,
                "source": "accounting_reasoning_prefill",
            })
        elif _would_interpret:
            _semantic = await extract_semantic_facts(
                user_message, orchestrator=get_client()
            )
            _ai_prefill = normalize_to_erp(_semantic)
            if _semantic:
                await _log_step(session_id, "AI_PERCEPTION", {
                    "facts": sorted(_semantic.keys()),
                    "intent": _ai_prefill.get("semantic_intent"),
                    "ambiguous": bool(_semantic.get("ambiguous")),
                    "source": "semantic_llm",
                })
        execution_plan = run_planner(
            user_message,
            clarification_history=prior_qa,
            org_preferences=org_prefs,
            prefill_entities=_ai_prefill or None,
        )
        if confirmed_intent:
            # P0-①: the approval is keyed to the confirmation's action_type —
            # the intent the user actually approved.  Re-apply it over the
            # keyword planner (which runs WITHOUT the semantic prefill this
            # path skips) so tool shortlisting, guards and Phase 7/8
            # verification all operate on the APPROVED event.
            execution_plan.intent = str(confirmed_intent)
        _phase_elapsed("planner.done", intent=execution_plan.intent)

        # deterministic semantic tool shortlist.  Seeds the
        # exclusion set so the model only SEES the tools relevant to this
        # economic event plus its entity-type lookups (<= 15 tools).
        # NEVER excludes a planner-listed tool; batch plans keep the full
        # toolset - every sub-intent needs its own tools.
        from app.tool_selector import excluded_for_intent
        from app.tools import list_tools as _list_all_tools

        excluded_tools: set = set()
        if not execution_plan.batch_items:
            excluded_tools |= excluded_for_intent(
                execution_plan.intent,
                execution_plan.potential_tools,
                _list_all_tools(),
            )
        # the audit trail records WHY the treatment was
        # chosen - the resolved nature and its source (USER_ANSWER /
        # PREFERENCE / DETERMINISTIC_RULE).
        planning_details: Dict[str, Any] = {
            "intent": execution_plan.intent,
            "extracted_entities": execution_plan.extracted_entities,
        }
        if execution_plan.transaction_nature:
            planning_details["transaction_nature"] = (
                execution_plan.transaction_nature
            )
            planning_details["nature_source"] = (
                execution_plan.transaction_nature_source
            )
        await _log_step(session_id, "PLANNING", planning_details)
        await _log_step(session_id, "ECONOMIC_EVENT", {
            "event": execution_plan.economic_event,
            "impact_map": execution_plan.impact_map,
            "prohibited_actions": execution_plan.prohibited_actions,
        })
        if prior_qa:
            # Post-answer FULL re-evaluation marker: after clarification
            # answers the complete operation is re-planned from scratch —
            # original request + all answers + merged entities — never a
            # narrow "just the newly answered field" pass.
            await _log_step(session_id, "RE_EVALUATION", {
                "prior_answers": len(prior_qa),
                "merged_entities": execution_plan.extracted_entities,
                "intent": execution_plan.intent,
            })
        await _update_status(session_id, ExecutionStatus.PLANNING)

        # ---- PHASE 2b: CONSOLIDATED clarification check -------------------
        # Ask ONLY when the planner found genuinely-missing material info
        # AND the clarification budget is not exhausted.  Everything already
        # provided in the message (any format) or answered in prior rounds
        # has been merged into extracted_entities by the planner, so it is
        # never re-asked here.  ALL independent gaps are gathered into ONE
        # questionnaire — the user answers everything in a single round
        # (360° analysis is mandatory; 360° questioning is minimal).
        if (
            execution_plan.requires_clarification
            and len(prior_qa) < MAX_CLARIFICATION_ROUNDS
            and _reasoning_calls is None
            # P0-①: an approved plan is frozen — a questionnaire gap can
            # never park a turn whose plan the user already confirmed.
            and approved_tool_calls is None
        ):
            from app.reasoning import plan_clarification_text

            question = (
                plan_clarification_text(
                    execution_plan.clarification_questions,
                    execution_plan.missing_fields,
                )
                or "Please provide more details."
            )
            # offer the learned default inside the question
            # ("previously: cash - reply SAME to reuse").
            memory_hint = _preference_memory_hint(
                org_prefs, execution_plan.clarification_questions
            )
            if memory_hint:
                question = f"{question}\n({memory_hint})"
            # R3.4a: never render model markdown in the question card.
            question = strip_markdown(question) or question
            # R3.4b: data-driven tap-to-answer options — the backend
            # emits one [{value, label}] list per question that has a
            # finite option set (purpose, capitalization, settlement,
            # operation, channel, nature, dates).  R4.6 FIX: empty
            # entries are kept as None placeholders so each list stays
            # INDEX-ALIGNED with its numbered sub-question — compacting
            # the array shifted the chips onto the wrong questions.
            question_options = [
                options_for_question(q) or []
                for q in execution_plan.clarification_questions
            ]
            question_options = (
                question_options if any(question_options) else None
            )
            clarification = await create_clarification(
                session_id=session_id,
                question=question,
                required_fields=execution_plan.missing_fields,
            )
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=clarification.get("question", question),
                required_information=execution_plan.missing_fields,
                question_options=question_options,
                requires_user_input=True,
            )
        if execution_plan.requires_clarification:
            log.warning(
                "agent.clarification_budget_exhausted",
                rounds=len(prior_qa),
                proceeding_with_partial_info=True,
            )

        # ---- PHASE 2c: DETERMINISTIC REPORT FAST-PATH ----
        # Plain reports/lookups with no open questions skip the LLM: the
        # planner's intent directly drives the read-only tools and the
        # rows are formatted deterministically.  Returns None for anything
        # ambiguous - the normal model path then handles it.
        fast_response = await _try_report_fast_path(
            execution_plan=execution_plan,
            session_id=session_id,
            organization_id=organization_id,
            user_id=user_id,
            auth=auth,
        )
        if fast_response is not None:
            return fast_response

        # ---- P5 GUARD: bank accounts are never invented. ------------------
        # A transfer needs EXISTING bank accounts; an empty lookup is a
        # configuration state the user must resolve — the agent must not
        # create bank accounts (and GL accounts) on its own initiative.
        if execution_plan.intent == "record_bank_transfer" and not confirmation_granted:
            from app.services import bank_service

            # Ask ONCE per conversation — after the user has answered the
            # bank-configuration question, the model proceeds (creation is
            # then user-sanctioned or explicitly declined).
            already_asked = any(
                "bank account" in (qa.get("question") or "").lower()
                for qa in prior_qa
            )
            banks = await bank_service.list_bank_accounts(organization_id)
            if not banks and not already_asked:
                question = (
                    "No bank accounts are configured for this organization, "
                    "so a bank-to-cash transfer cannot be recorded yet. I "
                    "will not create bank accounts on my own. Please add "
                    "them under Banking → Bank Accounts (or tell me to "
                    "create them, including the bank name and account "
                    "details), then ask me again."
                )
                await create_clarification(
                    session_id=session_id,
                    question=question,
                    required_fields=["bank_accounts_configuration"],
                )
                await _update_status(session_id, ExecutionStatus.AWAITING_CLARIFICATION)
                await _log_step(session_id, "AWAITING_CLARIFICATION", {
                    "source": "bank_accounts_configuration",
                    "question": question[:500],
                })
                return AgentResponse(
                    status=ExecutionStatus.AWAITING_CLARIFICATION,
                    execution_id=session_id,
                    question=question,
                    required_information=["bank_accounts_configuration"],
                    requires_user_input=True,
                )

        # ---- CASH-CONFIG GATE: a user-sanctioned YES on the parked
        # cash-ledger question creates the default drawer before any
        # execution path (model, fast path, or approval re-run) can settle
        # in cash.  P5 pattern: creation ONLY after an explicit YES — never
        # on the agent's own initiative; links the EXISTING cash GL account
        # (never invents a GL, never falls back to the bank ledger).
        if _cash_drawer_creation_pending(prior_qa):
            from app.services import bank_service

            drawer_before = await bank_service.repo.get_default_cash_account(
                organization_id
            )
            created_drawer = await bank_service.ensure_default_cash_account(
                organization_id
            )
            if created_drawer and not drawer_before:
                # Durable observability marker (structlog is lost on Vercel
                # — DEFECT3) — written only on the turn that actually
                # created the drawer, never on later idempotent passes.
                await _log_step(session_id, "CASH_DRAWER_CREATED", {
                    "cash_account_id": str(created_drawer.get("id")),
                    "name": created_drawer.get("name"),
                    "gl_account_id": str(created_drawer.get("gl_account_id")),
                    "source": "cash_accounts_configuration",
                })

        _phase_elapsed("context.start")
        # ---- PHASE 3: CONTEXT LOADING ------------------------------------
        await _update_status(session_id, ExecutionStatus.CONTEXT_LOADING)
        # All entities extracted from the request (plus merged clarification
        # answers) flow into the context — Gemini reuses them instead of
        # re-parsing the raw text.
        entity_hints: Dict[str, Any] = dict(execution_plan.extracted_entities)
        if execution_plan.entity_name and execution_plan.entity_type:
            entity_hints.setdefault(
                f"{execution_plan.entity_type}_name", execution_plan.entity_name
            )

        if approved_tool_calls is not None:
            # P0-①: the frozen approved plan has NO consumer for the domain
            # context — Phase 4 (its only heavy reader) is skipped, and
            # verification reads tool results, not context rows.  Build the
            # STRUCTURE from the planner's entities + already-loaded org
            # preferences: zero DB round-trips (kills the 12-query build AND
            # the duplicate org-preferences fetch on this path).
            context = AgentContext(
                organization={},
                user={"user_id": str(user_id)},
                extracted_entities=entity_hints,
                clarification_history=list(prior_qa),
                org_preferences=dict(org_prefs or {}),
            )
        else:
            context = await build_context(
                organization_id=organization_id,
                user_id=user_id,
                intent=execution_plan.intent,
                entity_hints=entity_hints,
                clarification_history=prior_qa,
                # P1-⑦ (forensic latency report ⑦): org preferences were
                # already loaded this turn — pass them through (kills the
                # duplicate query) — and skip the seven domain fetches when a
                # validated reasoning proposal owns the plan (Phase 4, their
                # only heavy consumer, does not run; traced: open_questions
                # feeds logs only, gates look up their own rows, prompts.py
                # renders relevant_* only for the Phase-4 prompt).
                org_preferences=dict(org_prefs or {}),
                domain_fetches=_reasoning_calls is None,
                # P2-⑫: rows already loaded at entry (moved, not added —
                # the same queries build_context used to run itself).
                organization=_org_row,
                financial_year=_fy_row,
                accounting_period=_period_row,
            )
        # the model's own reasoning products travel WITH the
        # context so every later LLM call reassesses them instead of silently
        # replacing them with a keyword route.
        context.preliminary_extraction = dict(_preliminary or {})
        if _reasoning is not None:
            context.live_evidence = [
                result.as_dict() for result in (_reasoning.evidence_results or [])
            ]
            context.accounting_reasoning = {
                "status": _reasoning.status,
                "understanding": _reasoning.understanding,
                "proposal": _reasoning.proposal,
                "evidence_summary": render_evidence_compact(
                    _reasoning.evidence_results or []
                ),
            }
        await _log_step(session_id, "CONTEXT_LOADING", {
            "customers": len(context.relevant_customers),
            "suppliers": len(context.relevant_suppliers),
            "accounts": len(context.relevant_accounts),
            "live_evidence": len(context.live_evidence),
        })

        _phase_elapsed("context.built")
        # ---- PHASE 3b: INTELLIGENT TRANSACTION CLASSIFICATION (360°) ------
        # Deterministic (no LLM): ERP configuration → item/account mapping →
        # business rules → user answers.  If the treatment is MATERIALLY
        # AMBIGUOUS (e.g. laptop: fixed asset vs expense) and no authoritative
        # configuration exists, ASK — never default to a generic expense.
        from app.classifier import classify_transaction, _classification_question

        classification = await classify_transaction(
            organization_id=organization_id,
            intent=execution_plan.intent,
            entities=context.extracted_entities,
            message=user_message,
            # P1-⑧ (forensic latency report ⑧): skip ONLY the account-hint /
            # config-gap DB work on proposal/approved paths (its consumers —
            # fastpath, Phase-4 prompt, config-gap question — do not run
            # there). Nature-affecting lookups still run: build_event_profile
            # consumes transaction_nature for the executor's prohibited-set
            # guard (traced; P0-① kept classification running for this).
            resolve_account_hints=(
                _reasoning_calls is None and approved_tool_calls is None
            ),
            # RC-4a: honest provenance — a learned org preference must not
            # be reported as USER_ANSWER ("the user said so").
            explicit_nature_source=execution_plan.transaction_nature_source,
        )
        execution_plan.classification = classification
        context.classification = classification
        await _log_step(session_id, "CLASSIFICATION", {
            "transaction_nature": classification.transaction_nature,
            "confidence": classification.confidence,
            "source": classification.source,
            "account_hint": classification.account_hint_code,
            "requires_clarification": classification.requires_clarification,
        })

        _phase_elapsed("classification.done", nature=classification.transaction_nature)
        # ---- PHASE 3c: 360° DEPENDENCY GRAPH (requirement gap analysis) ---
        # Every materially relevant dimension gets an explicit resolution
        # state; only genuinely-open user decisions become questions.  An
        # empty ERP context is valid information — never a failure.
        from app.reasoning import analyze_requirements, collect_open_questions

        dependency_nodes = analyze_requirements(
            intent=execution_plan.intent,
            entities=execution_plan.extracted_entities,
            missing_fields=execution_plan.missing_fields,
            classification=classification,
            relevant_customers=context.relevant_customers,
            relevant_suppliers=context.relevant_suppliers,
            relevant_bank_accounts=context.relevant_bank_accounts,
        )
        open_questions = collect_open_questions(dependency_nodes)
        await _log_step(session_id, "REQUIREMENT_ANALYSIS", {
            "dependencies": [n.as_dict() for n in dependency_nodes],
            "open_questions": [q["field"] for q in open_questions],
        })

        _phase_elapsed("requirements.done", open_questions=[q["field"] for q in open_questions])
        # ---- PHASE 3d: NATURE-REFINED IMPACT MAP (negative reasoning) -----
        # With the economic NATURE known, refine the event profile: the
        # 360° impact map becomes precise (INVENTORY stock vs FIXED_ASSET
        # capitalisation vs EXPENSE vs SERVICE) and the PROHIBITED mutation
        # set is finalised.  This is authoritative context for the model
        # and enforced by the executor below.
        from app.reasoning import build_event_profile as build_refined_profile

        event_profile = build_refined_profile(
            execution_plan.intent, classification=classification
        )
        execution_plan.impact_map = dict(event_profile.affected)
        execution_plan.prohibited_actions = [
            p.as_dict() for p in event_profile.prohibited
        ]
        context.economic_event = event_profile.event.value
        context.impact_map = dict(event_profile.affected)
        context.prohibited_actions = [
            p.as_dict() for p in event_profile.prohibited
        ]
        await _log_step(session_id, "IMPACT_ANALYSIS", event_profile.as_dict())

        if (
            classification.requires_clarification
            and len(prior_qa) < MODEL_MAX_CLARIFICATION_ROUNDS
            and _reasoning_calls is None
            # P0-①: the classification still RUNS on approved turns (its
            # nature refines the event profile that powers the executor's
            # prohibited-tools guard) but its question must never park a
            # confirmed plan — any configuration gap was resolved during the
            # original turn.
            and approved_tool_calls is None
        ):
            if classification.transaction_nature:
                # Configuration gap: the nature is decided (user answer /
                # rules) but no matching account exists.  Ask a targeted
                # CONFIGURATION question — asked only ONCE per conversation
                # (afterwards the model creates/selects the account itself).
                already_asked = any(
                    "chart of accounts" in (qa.get("question") or "").lower()
                    for qa in prior_qa
                )
                if already_asked:
                    pass  # continue to the model with the config-gap context
                else:
                    nature_label = classification.transaction_nature.replace("_", " ").lower()
                    # Smart account resolution: offer the user the most
                    # relevant EXISTING accounts (e.g. 'bonus' → Salaries /
                    # Wages) AND the option to create a dedicated account.
                    candidates = list(
                        getattr(classification, "candidate_accounts", None) or []
                    )
                    if candidates:
                        suggestion = ", ".join(
                            f"'{c}'" for c in candidates[:4]
                        )
                        question = (
                            f"There is no dedicated account for this entry "
                            f"(nature: {nature_label}). You can classify it "
                            f"under an existing account — for example "
                            f"{suggestion} — or I can create a new dedicated "
                            f"account for it. Which do you prefer? "
                            f"(Say 'create' for a new account, or name the "
                            f"account to use.)"
                        )
                        options = [*candidates[:4], "Create new account"]
                    else:
                        question = (
                            f"There is no {nature_label} account in your chart of "
                            f"accounts for this entry. Should I create one (for "
                            f"example a 'Computer Equipment' fixed-asset account), "
                            f"or do you want to use a specific existing account?"
                        )
                        options = ["Create new account"]
                    # R3.4: account NAMES only in user-facing text (never
                    # internal codes) and tappable options.
                    question = strip_markdown(question) or question
                    clarification = await create_clarification(
                        session_id=session_id,
                        question=question,
                        required_fields=["account_configuration"],
                    )
                    return AgentResponse(
                        status=ExecutionStatus.AWAITING_CLARIFICATION,
                        execution_id=session_id,
                        question=clarification.get("question", question),
                        required_information=["account_configuration"],
                        options=options,
                        question_options=[
                            [
                                {"value": str(o), "label": str(o)}
                                for o in options
                            ]
                        ],
                        requires_user_input=True,
                    )
            else:
                question = _classification_question(classification)
                # R3.4: the 4-way nature decision is tap-to-answer too.
                nature_options = options_for_question(question)
                question = strip_markdown(question) or question
                clarification = await create_clarification(
                    session_id=session_id,
                    question=question,
                    required_fields=["transaction_nature"],
                )
                return AgentResponse(
                    status=ExecutionStatus.AWAITING_CLARIFICATION,
                    execution_id=session_id,
                    question=clarification.get("question", question),
                    required_information=["transaction_nature"],
                    question_options=[nature_options] if nature_options else None,
                    requires_user_input=True,
                )

        # ---- PHASE 3.5: DETERMINISTIC MUTATION FAST PATH (instant mode) ---
        # When the reasoning layers have fully resolved the transaction,
        # the tool call is built here and the 30-85s LLM planning call is
        # SKIPPED entirely (see _deterministic_mutation_calls).  Returns
        # None whenever anything is unresolved - the model path below then
        # handles it exactly as before.
        # BEFORE the tool call, the named party is
        # RESOLVED like a chartered accountant would - exact match → use
        # it; similar matches → the user picks the real party; nothing
        # found → the user confirms the new party ledger.  Never silently
        # invented.
        _phase_elapsed("party_question.start")
        # P1-⑨ (forensic latency report §5): all four gate LOOKUPS run once,
        # concurrently, up front — then each ask-check below runs in the
        # original deterministic order (party → settlement → catalog →
        # revenue), so which question the user sees is unchanged.
        party_question = settlement_question = catalog_question = review = None
        if _reasoning_calls is None and approved_tool_calls is None:
            (
                party_question,
                settlement_question,
                catalog_question,
                review,
            ) = await _resolve_gate_questions(
                organization_id=organization_id,
                execution_plan=execution_plan,
            )
        else:
            _gate_skip_reason = (
                "approved plan reuse — plan frozen by confirmation"
                if approved_tool_calls is not None
                else "validated LLM accounting proposal is in force"
            )
            # A validated LLM accounting proposal already inspected the books
            # and declared which records are — and are NOT — affected. Python
            # does not re-invent a party requirement on top of that; it still
            # enforces registry, permissions, constraints and the confirmation
            # gate at execution time.
            for _skipped_gate in (
                "party_resolution",
                "settlement_check",
                "catalog_check",
                "revenue_ledger_review",
            ):
                await _log_step(session_id, "GATE_SKIPPED", {
                    "gate": _skipped_gate,
                    "reason": _gate_skip_reason,
                })
        if party_question:
            party_required = party_question.get("required_fields") or [
                "supplier_name"
            ]
            clarification = await create_clarification(
                session_id=session_id,
                question=party_question["question"],
                required_fields=party_required,
            )
            await _log_step(session_id, "AWAITING_CLARIFICATION", {
                "source": "party_resolution",
                "question": party_question["question"][:300],
            })
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=clarification.get("question", party_question["question"]),
                options=party_question.get("options"),
                required_information=party_required,
                requires_user_input=True,
            )
        _phase_elapsed("party_question.done", asked=bool(party_question))
        # CA treatment 3 — SETTLEMENT CHECK: a settle-existing-payable
        # request locates the unpaid payable and CONFIRMS it with the
        # user before any payment is recorded (never silently settled,
        # never a second expense).  No unpaid payable → the fallback
        # re-picks the treatment.
        _phase_elapsed("settlement_question.start")
        # P1-⑨: lookup already resolved concurrently above.
        if settlement_question:
            settle_required = settlement_question.get("required_fields") or [
                "settlement_check"
            ]
            clarification = await create_clarification(
                session_id=session_id,
                question=settlement_question["question"],
                required_fields=settle_required,
            )
            await _log_step(session_id, "AWAITING_CLARIFICATION", {
                "source": "settlement_check",
                "question": settlement_question["question"][:300],
            })
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=clarification.get(
                    "question", settlement_question["question"]
                ),
                options=settlement_question.get("options"),
                required_information=settle_required,
                requires_user_input=True,
            )
        _phase_elapsed("settlement_question.done", asked=bool(settlement_question))
        # invoice lines naming items
        # that are not in the product/service catalog are resolved the
        # same way the party gate works — the user decides ONCE whether
        # the catalog grows; nothing is silently invented.
        _phase_elapsed("catalog_question.start")
        # P1-⑨: lookup already resolved concurrently above.
        if catalog_question:
            clarification = await create_clarification(
                session_id=session_id,
                question=catalog_question["question"],
                required_fields=["item_description"],
            )
            await _log_step(session_id, "AWAITING_CLARIFICATION", {
                "source": "catalog_check",
                "question": catalog_question["question"][:300],
            })
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=clarification.get(
                    "question", catalog_question["question"]
                ),
                options=catalog_question.get("options"),
                required_information=["item_description"],
                requires_user_input=True,
            )
        _phase_elapsed("catalog_question.done", asked=bool(catalog_question))

        # ---- PHASE 3c: SALE REVENUE-LEDGER REVIEW (flexible COA) ----------
        # A sale must never be booked to an arbitrary revenue account.  When the
        # item sold names a stream with no dedicated ledger, ASK — and create the
        # ledger on approval — BEFORE any execution.  Never assumes.
        # P1-⑨: lookup already resolved concurrently above (None on the
        # proposal/approved path — the GATE_SKIPPED logs moved up front).
        if review is not None:
            # PERSIST the question — the answer round must find a pending
            # clarification row.  (Without this row the answer was silently
            # discarded on resume and the SAME question was re-asked forever.)
            clarification = await create_clarification(
                session_id=session_id,
                question=review["question"],
                required_fields=["revenue_ledger_decision"],
                options=review.get("options"),
            )
            log.info(
                "ledger_question_created",
                session_id=str(session_id),
                clarification_id=str(clarification.get("id")),
            )
            await _log_step(session_id, "AWAITING_CLARIFICATION", {
                "source": "revenue_ledger",
                "question": review["question"][:300],
            })
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=review["question"],
                options=review.get("options"),
                required_information=["revenue_ledger_decision"],
                requires_user_input=True,
            )

        if approved_tool_calls:
            # The user approved THIS plan (snapshot stored with the
            # confirmation): reuse it verbatim — no re-planning, no fresh
            # LLM tool selection, no way to lose the approved entities.
            deterministic_calls: Optional[List[ToolCall]] = list(approved_tool_calls)
            await _log_step(session_id, "APPROVED_PLAN_REUSED", {
                "tools": [tc.tool_name for tc in deterministic_calls],
            })
        elif _reasoning_calls:
            # The validated LLM accounting proposal IS the plan: the model
            # inspected the live books, stated the interpretation, the affected
            # records, the impact, what will NOT change and the uncertainty, and
            # Python accepted it.  Execution still passes through the full
            # security/validation/confirmation stack below.
            deterministic_calls = list(_reasoning_calls)
            execution_plan.requires_confirmation = True
            await _log_step(session_id, "REASONING_PLAN_EXECUTION", {
                "tools": [tc.tool_name for tc in deterministic_calls],
                "source": "llm_accounting_reasoning",
            })
        else:
            deterministic_calls = await _deterministic_mutation_calls(
                organization_id=organization_id,
                execution_plan=execution_plan,
                classification=classification,
            )
        _phase_elapsed("deterministic.done", fast=deterministic_calls is not None)
        llm_text = ""
        planned_tool_calls: List[ToolCall] = []
        if deterministic_calls is not None:
            planned_tool_calls = deterministic_calls
            await _log_step(session_id, "DETERMINISTIC_EXECUTION", {
                "intent": execution_plan.intent,
                "bypass_llm": True,
                "tools": [tc.tool_name for tc in planned_tool_calls],
            })
        else:
            # ---- PHASE 4: AI REASONING (planning call — Qwen → Gemini) ----
            # First call WITHOUT executor — gets the model's planned tool calls
            # so we can check the confirmation gate BEFORE executing anything.
            # The orchestrator dispatches to Qwen (primary) and falls back to
            # Gemini only on genuine provider failure.
            if _provider_down:
                # The SAME provider chain already failed the accounting
                # reasoning round in this request.  A second (and third) attempt
                # adds tens of seconds and can only produce a route that was not
                # decided on the books — so the run stops honestly instead, with
                # nothing recorded and every fact kept for the resend.
                await _update_status(session_id, ExecutionStatus.FAILED)
                await _log_step(session_id, "FAILED", {
                    "reason": "provider_unavailable",
                    "stage": "reasoning",
                    "rounds": _reasoning.rounds,
                })
                return AgentResponse(
                    status=ExecutionStatus.FAILED,
                    execution_id=session_id,
                    summary=(
                        "The AI provider did not answer in time. Nothing was "
                        "recorded yet. Please send your request again — "
                        "everything you have already told me is kept in this "
                        "conversation."
                    ),
                )
            client = get_client()
            # simple lookup intents that reached
            # the model (the deterministic fast-path did not apply - ambiguous
            # phrasing) get a lighter output budget.
            light_budget = execution_plan.intent in _LIGHT_BUDGET_INTENTS
            # PROGRESS VISIBILITY: the planning round-trip is the first point
            # where a request sits for tens of seconds doing nothing the user
            # can see (measured 6-16s; the provider endpoint itself costs
            # ~15-20s per probe from ap-southeast-1).  Emit the INTERPRETING
            # phase so the progress UI shows a real stage with rotating status
            # text instead of freezing on the last recorded one.
            # _STEP_TYPE_MAP already maps INTERPRETING -> REASON.
            await _log_step(session_id, "INTERPRETING", {
                "source": "llm_planning",
                "intent": execution_plan.intent,
            })
            _phase_elapsed("llm_call.start")
            planning_result, provider_stall = await _bounded_provider_call(
                client.generate_with_tools(
                    user_message=user_message,
                    context=context,
                    light_budget=light_budget,
                    excluded_tools=excluded_tools or None,
                ),
                budget=_LLM_PLANNING_BUDGET_SECONDS,
                stage="planning",
            )
            if planning_result is None:
                # Bounded failure instead of a platform kill: the session is
                # closed honestly and the user can simply answer again — every
                # fact already given is preserved in this conversation.
                await _update_status(session_id, ExecutionStatus.FAILED)
                await _log_step(session_id, "FAILED", {
                    "reason": provider_stall,
                    "stage": "planning",
                })
                return AgentResponse(
                    status=ExecutionStatus.FAILED,
                    execution_id=session_id,
                    summary=(
                        f"{provider_stall} Nothing was recorded yet. "
                        "Please send your request again — everything you have "
                        "already told me is kept in this conversation."
                    ),
                )
            _phase_elapsed("llm_call.done")
            llm_text = planning_result.get("text", "")
            planned_tool_calls = planning_result.get("tool_calls", [])

        # ---- PHASE 4b: Model-driven clarification gate ---------------------
        # The model may respond with a TEXT-ONLY question (no tool calls)
        # when it genuinely cannot proceed — e.g. the supplier named in the
        # request does not exist.  An AI response is NOT a completed ERP
        # operation: route it through the existing clarification mechanism
        # so the user can answer and the SAME conversation resumes.
        if (
            not planned_tool_calls
            and _usable_question(llm_text)
            and len(prior_qa) < MODEL_MAX_CLARIFICATION_ROUNDS
        ):
            await create_clarification(
                session_id=session_id,
                question=_usable_question(llm_text),
                required_fields=execution_plan.missing_fields,
            )
            await _log_step(session_id, "AWAITING_CLARIFICATION", {
                "source": "model",
                "question": _usable_question(llm_text)[:500],
            })
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=_usable_question(llm_text),
                required_information=execution_plan.missing_fields,
                requires_user_input=True,
            )


        # ---- FIX-5 / FIX-1: reconcile the INTENT with the planned tools,
        # then never let the shortlist guard refuse the plan itself.
        # RC-1/RC-5 (production 2026-09-24, "3 computers" incident): the
        # reasoning layer proposed register_fixed_asset while the plan/
        # confirmation intent said record_expense; the approved turn then
        # re-seeded the shortlist from the MISMATCHED intent, the plan's own
        # tool landed in excluded_tools, and the executor refused the only
        # planned call with the party-duplicate story -> FAILED.  The
        # reconciliation is GENERIC — derived from the intent->tool table,
        # never an event template.  Batch plans keep full toolsets (the
        # shortlist seed skips them too).
        _unpermitted: set = set()
        if planned_tool_calls and not execution_plan.batch_items:
            from app.planner import intent_requires_confirmation
            from app.tool_selector import reconcile_intent_with_tools

            _planned_names = [tc.tool_name for tc in planned_tool_calls]
            _intent_before = execution_plan.intent
            _recon_intent, _unpermitted = reconcile_intent_with_tools(
                _intent_before,
                _planned_names,
                execution_plan.potential_tools,
            )
            if _recon_intent != _intent_before:
                execution_plan.intent = _recon_intent
                # Re-seed the shortlist from the RECONCILED intent so the
                # offering, the guards and Phase 7/8 verification all agree
                # with the economic event the plan actually performs.
                excluded_tools = excluded_for_intent(
                    _recon_intent,
                    execution_plan.potential_tools,
                    _list_all_tools(),
                )
                if intent_requires_confirmation(_recon_intent):
                    # The reconciled event class needs user authorization —
                    # never silently execute it merely because the old
                    # intent (e.g. record_expense) did not.
                    execution_plan.requires_confirmation = True
                await _log_step(session_id, "PLANNING", {
                    "intent_before": _intent_before,
                    "intent_after": _recon_intent,
                    "planned_tools": _planned_names,
                    "source": "intent_tool_reconcile",
                })
            # FIX-1: tools the plan is ALLOWED to run are never refused by
            # the shortlist guard — the (frozen) plan is the authority at
            # this point.  Tools OUTSIDE the reconciled intent stay
            # excluded and are refused honestly by excluded_tool_refusal.
            excluded_tools -= set(_planned_names) - _unpermitted

        # ---- PHASE 4c: EXECUTION-AGENT LOOP — ACCOUNT PRE-FLIGHT ----------
        # Every account the planned calls REQUIRE (register_fixed_asset
        # needs a PPE ledger; a known expense category needs its own ledger)
        # or NAME (explicit args, journal lines) is resolved against the live
        # chart BEFORE the user approves anything.  A missing ledger spawns
        # the IFRS-aware account-creation clarification — never a deep
        # execution failure ("No fixed-asset account could be determined…").
        # A user-confirmed creation is injected as the FIRST planned call so
        # the approval snapshot covers it and the tool-order guard unblocks
        # the recording mutation — any intent, any activity.
        if planned_tool_calls and not execution_plan.batch_items:
            from app.account_resolution import (
                account_exists,
                account_shape,
                ensure_create_account_first,
                gap_already_asked,
                heading_account_id,
                options_for_gap,
                preflight_account_gaps,
                question_for_gap,
            )

            _ents = execution_plan.extracted_entities or {}
            _confirmed_acct = str(_ents.get("create_account") or "").strip()
            try:
                _gaps = await preflight_account_gaps(
                    organization_id,
                    tool_calls=planned_tool_calls,
                    entities=_ents,
                    intent=execution_plan.intent,
                    message=user_message,
                    # P1-⑧ parity: nature probes are the classifier's
                    # account-hint DB work — proposal/approved paths skip
                    # them (the execution-time rescue covers those).
                    include_nature_probes=(
                        _reasoning_calls is None and approved_tool_calls is None
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — never break a run
                log.warning("agent.account_preflight_failed",
                            session_id=str(session_id), error=str(exc)[:200])
                _gaps = []
            if _confirmed_acct:
                _gaps = [g for g in _gaps
                         if (g.name or "").strip().lower() != _confirmed_acct.lower()]
            # Gate ORDER is contractual: a confirmation-pending plan must
            # reach PHASE 5 first (reconcile/approval tests pin it).  The ask
            # is deferred there — explicit-ref gaps are asked on the approved
            # turn (refs are checked on every path), nature gaps by the
            # execution-time rescue.  Never a dead end.
            _confirmation_pending = bool(
                execution_plan.requires_confirmation
                and planned_tool_calls
                and not confirmation_granted
            )
            if (_gaps and not _confirmation_pending
                    and not gap_already_asked(prior_qa)
                    and len(prior_qa) < MODEL_MAX_CLARIFICATION_ROUNDS):
                _gap = _gaps[0]
                _q = question_for_gap(_gap)
                try:
                    _clar = await create_clarification(
                        session_id=session_id, question=_q,
                        required_fields=["account_configuration"],
                    )
                    _q = _clar.get("question", _q)
                except Exception as exc:  # noqa: BLE001 — asking is not optional
                    log.warning("agent.account_gap_clarification_failed",
                                session_id=str(session_id), error=str(exc)[:200])
                _opts = options_for_gap(_gap)
                await _log_step(session_id, "AWAITING_CLARIFICATION", {
                    "source": "account_creation_gap",
                    "gap": {"name": _gap.name, "account_type": _gap.account_type,
                            "source": _gap.source},
                    "question": _q[:300],
                })
                return AgentResponse(
                    status=ExecutionStatus.AWAITING_CLARIFICATION,
                    execution_id=session_id,
                    question=_q,
                    options=_opts,
                    question_options=[[{"value": o, "label": o} for o in _opts]],
                    required_information=["account_configuration"],
                    requires_user_input=True,
                )
            # User-confirmed creation → create_account FIRST (injected before
            # the confirmation snapshot, so the approval covers it).
            if _confirmed_acct:
                try:
                    _acct_now = await account_exists(organization_id, _confirmed_acct)
                except Exception:  # noqa: BLE001
                    _acct_now = None
                if _acct_now is None and not any(
                    tc.tool_name == "create_account" for tc in planned_tool_calls
                ):
                    _cls = classification or execution_plan.classification
                    _shape = account_shape(
                        getattr(_cls, "transaction_nature", None) or "OPERATING_EXPENSE"
                    )
                    _create_args: dict = {
                        "name": _confirmed_acct,
                        "code": getattr(_cls, "proposed_account_code", None)
                                or _shape[2],
                        "account_type": _shape[0],
                        "normal_balance": _shape[1],
                        "description": "Created via the account-creation confirmation loop.",
                    }
                    # Category-level granularity: an ASSET category hangs
                    # under the chart's PPE heading when one exists, so
                    # "Furniture & Fixtures" appears UNDER Property, Plant &
                    # Equipment on the balance sheet (never an invented
                    # parent — None stays top-level).
                    if _shape[0] == "ASSET":
                        try:
                            _heading = await heading_account_id(
                                organization_id, nature=_shape[0]
                            )
                        except Exception:  # noqa: BLE001
                            _heading = None
                        if _heading:
                            _create_args["parent_account_id"] = _heading
                    planned_tool_calls = ensure_create_account_first(
                        planned_tool_calls,
                        arguments=_create_args,
                    )
                    if "create_account" not in (execution_plan.potential_tools or []):
                        execution_plan.potential_tools = [
                            *(execution_plan.potential_tools or []), "create_account",
                        ]
                    excluded_tools.discard("create_account")
                    await _log_step(session_id, "PLANNING", {
                        "source": "account_creation_injected",
                        "account": _confirmed_acct,
                        "tools": [tc.tool_name for tc in planned_tool_calls],
                    })

        # ---- PHASE 5: CONFIRMATION GATE (BEFORE execution) ---------------
        # Skipped when resuming an already-approved session
        # (confirmation_granted=True from resume_with_confirmation).
        _phase_elapsed("confirmation_gate.start")
        if (
            execution_plan.requires_confirmation
            and planned_tool_calls
            and not confirmation_granted
        ):
            # ---- PLAN COMPLETENESS: fail closed BEFORE the user approves ----
            # An approved plan that performs no financial mutation cannot deliver
            # the operation the user asked for.  Refuse to snapshot it: ask
            # instead, so no partial state is written and the user is never
            # asked to approve something impossible (production 2026-09-22).
            if _plan_performs_no_financial_mutation(
                intent=execution_plan.intent, calls=planned_tool_calls
            ):
                _tools = ", ".join(tc.tool_name for tc in planned_tool_calls)
                _missing = ", ".join(execution_plan.missing_fields or []) or (
                    "the remaining details"
                )
                _question = (
                    f"Nothing has been recorded yet. I could not build the "
                    f"{str(execution_plan.intent).replace('_', ' ')} from the details "
                    f"I have, so there is nothing for you to approve. The steps I "
                    f"could prepare were: {_tools}. Please supply {_missing} — or "
                    "rephrase the request, and I will try again."
                )
                try:
                    _clarification = await create_clarification(
                        session_id=session_id,
                        question=_question,
                        required_fields=(
                            list(execution_plan.missing_fields or [])
                            or ["missing_details"]
                        ),
                    )
                    _question = _clarification.get("question", _question)
                except Exception as exc:  # noqa: BLE001 — asking is not optional
                    log.warning(
                        "agent.clarification_write_failed",
                        session_id=str(session_id),
                        error=str(exc)[:200],
                    )
                await _log_step(session_id, "AWAITING_CLARIFICATION", {
                    "source": "plan_incomplete",
                    "intent": execution_plan.intent,
                    "planned_tools": [tc.tool_name for tc in planned_tool_calls],
                    "question": _question[:300],
                })
                return AgentResponse(
                    status=ExecutionStatus.AWAITING_CLARIFICATION,
                    execution_id=session_id,
                    question=_question,
                    required_information=(
                        list(execution_plan.missing_fields or [])
                        or ["missing_details"]
                    ),
                    requires_user_input=True,
                )

            # ---- FIX-6: FAIL CLOSED before the user approves a plan that
            # execution would refuse (RC-1/RC-3: the computers incident
            # froze a plan whose only tool contradicted its own event
            # profile and detonated it on the approval turn).  When NOTHING
            # executable remains, ask for the accounting treatment instead
            # of creating a doomed confirmation.  Partial plans keep
            # today's tolerance — the executor gates refuse individual
            # tools with accurate messages.
            _conflict = plan_conflict_tools(
                planned_names=[tc.tool_name for tc in planned_tool_calls],
                prohibited_actions=execution_plan.prohibited_actions,
                unpermitted=_unpermitted,
                batch=bool(execution_plan.batch_items),
            )
            if _conflict:
                _c_reason = next(
                    (
                        str((a or {}).get("reason") or "")
                        for a in (execution_plan.prohibited_actions or [])
                        if event_prohibited_tools([a]) & _conflict
                    ),
                    "the planned step is not permitted for this "
                    "transaction's intent",
                )
                _c_question = (
                    f"Nothing has been recorded yet. I cannot prepare an "
                    f"executable plan: {', '.join(sorted(_conflict))} "
                    f"cannot be recorded for this transaction as it is "
                    f"classified ({_c_reason}). How should this transaction "
                    f"be treated? Confirm the accounting treatment and I "
                    f"will propose a valid plan."
                )
                try:
                    _c_clar = await create_clarification(
                        session_id=session_id,
                        question=_c_question,
                        required_fields=["accounting_treatment"],
                    )
                    _c_question = _c_clar.get("question", _c_question)
                except Exception as exc:  # noqa: BLE001 — asking is not optional
                    log.warning(
                        "agent.treatment_conflict_clarification_failed",
                        session_id=str(session_id),
                        error=str(exc)[:200],
                    )
                await _log_step(session_id, "AWAITING_CLARIFICATION", {
                    "source": "intent_tool_conflict",
                    "intent": execution_plan.intent,
                    "blocked_tools": sorted(_conflict),
                    "question": _c_question[:300],
                })
                return AgentResponse(
                    status=ExecutionStatus.AWAITING_CLARIFICATION,
                    execution_id=session_id,
                    question=_c_question,
                    required_information=["accounting_treatment"],
                    requires_user_input=True,
                )

            # When the plan came from the accounting reasoning layer, the user
            # sees the MODEL's accounting disclosure (interpretation, affected
            # records, impact, what will NOT change, uncertainty and the exact
            # confirmation sentence) — not a keyword-intent summary.
            _disclosure = _reasoning_disclosure(_reasoning)
            # P1-⑤: carry THIS request's already-fetched evidence into the
            # frozen plan — declared party name-aliases become canonical ids
            # HERE, so the approval turn's materialization skips its party
            # search (zero new queries; exact single match only; recorded).
            _alias_fixes = _resolve_declared_aliases_from_evidence(
                planned_tool_calls,
                (_reasoning.evidence_results if _reasoning is not None else None)
                or [],
            )
            if _alias_fixes:
                await _log_step(
                    session_id,
                    "REFERENCE_RESOLVED_FROM_EVIDENCE",
                    {"replacements": _alias_fixes},
                )
            confirmation = await create_confirmation(
                session_id=session_id,
                action_type=execution_plan.intent,
                description=(
                    _disclosure.splitlines()[-1]
                    if _disclosure
                    else (
                        f"Execute: {execution_plan.intent}"
                        f" — {execution_plan.entity_name or ''}"
                    )
                ),
                risk_level="MEDIUM",
                # Snapshot the EXACT plan the user is approving (migration
                # 079): the resumed run reuses these tool calls verbatim.
                plan=[
                    {
                        "tool_name": tc.tool_name,
                        "arguments": dict(tc.arguments or {}),
                    }
                    for tc in planned_tool_calls
                ],
            )
            await _log_step(session_id, "AWAITING_CONFIRMATION", {
                "confirmation_id": confirmation.get("id"),
                "source": "llm_accounting_reasoning" if _disclosure else "plan",
            })
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CONFIRMATION,
                execution_id=session_id,
                action=execution_plan.intent,
                summary=_disclosure or _confirmation_summary(execution_plan),
                confirmation_required=True,
                risk_level="MEDIUM",
            )

        # ---- PHASE 6: TOOL EXECUTION (iterative with Gemini) -------------
        await _update_status(session_id, ExecutionStatus.EXECUTING)

        # Deterministic execution state used by the reasoning guards below:
        # - excluded_tools: seeded BEFORE the planning call with the Work
        #   Stream E semantic shortlist; party/account-creation tools are
        #   REMOVED from the model's offered tool set once a search has
        #   resolved the party - the model cannot attempt what it is not
        #   offered.
        # - account_creation: an explicit account-creation request that has
        #   not succeeded BLOCKS default-account mutations — no silent
        #   degradation to the default expense account.
        account_creation = {"requested": False, "succeeded": False}

        # Build an executor closure that routes through the full
        # security + validation + handler stack.
        async def _executor(tool_name: str, args: dict) -> dict:
            # GENERIC negative-reasoning gate: refuse any tool the economic
            # event profile PROHIBITS (cash ⇒ party-ledger creation; SERVICE
            # ⇒ inventory movement; expense/consumable ⇒ fixed-asset
            # capitalisation; REPORTING ⇒ any mutation).  Correct execution
            # includes correct NON-execution.
            _prohibited = event_prohibited_tools(
                execution_plan.prohibited_actions
            )
            if tool_name in _prohibited:
                _reason = next(
                    (
                        a.get("reason", "")
                        for a in execution_plan.prohibited_actions
                        if tool_name in event_prohibited_tools([a])
                    ),
                    "prohibited by the economic event classification",
                )
                log.warning(
                    "agent.event_prohibited_tool_blocked",
                    session_id=str(session_id),
                    intent=execution_plan.intent,
                    tool=tool_name,
                )
                return {
                    "success": False,
                    "error": (
                        f"BUSINESS_RULE_VIOLATION: {tool_name} is prohibited "
                        f"for this economic event — {_reason}. Do NOT retry "
                        "the same call; adapt the plan accordingly."
                    ),
                    "error_category": "BUSINESS_RULE_VIOLATION",
                }
            # Reasoning-level enforcement of the one-off-cash rule: for
            # cash transactions a party ledger is NEVER required — the
            # named supplier/customer is informational.  Block the CREATE
            # at the plan owner (here), not merely at the DB service
            # layer, so the model's dependency plan itself stays correct.
            if cash_party_creation_blocked(execution_plan.intent, tool_name):
                log.warning(
                    "agent.cash_party_creation_blocked",
                    session_id=str(session_id),
                    intent=execution_plan.intent,
                    tool=tool_name,
                )
                return {
                    "success": False,
                    "error": (
                        "BUSINESS_RULE_VIOLATION: a supplier/customer ledger "
                        "is NOT required for a cash transaction — the named "
                        "party is informational only. Do not create party "
                        "records for cash transactions; record the "
                        "transaction without it."
                    ),
                    "error_category": "BUSINESS_RULE_VIOLATION",
                }
            # Reasoning-level guard: once a party has been resolved by
            # search, its creation tool is disabled — refuse any attempt so
            # the model reuses the resolved record instead.  FIX-2 (RC-2):
            # the refusal TEXT is tool-specific — party tools keep the
            # duplicate-party wording; anything else is honestly reported
            # as not-permitted-for-this-intent, never a fabricated party
            # story ("3 computers" incident).
            if tool_name in excluded_tools:
                log.warning(
                    "agent.excluded_tool_refused",
                    session_id=str(session_id),
                    intent=execution_plan.intent,
                    tool=tool_name,
                )
                return excluded_tool_refusal(tool_name, execution_plan.intent)
            # Reasoning-level guard: the user explicitly requested a new
            # account; until that account is successfully created, default-
            # account mutations are forbidden (no silent degradation).
            if (
                tool_name in ("create_expense", "create_purchase_bill", "create_invoice")
                and account_creation["requested"]
                and not account_creation["succeeded"]
            ):
                return {
                    "success": False,
                    "error": (
                        "BLOCKED: the user explicitly requested a NEW account "
                        "and it has not been created yet. Create the requested "
                        "account first (the create_account tool resolves a "
                        "free code automatically), or ask the user. Do NOT "
                        "record this transaction against a default account."
                    ),
                    "error_category": "BUSINESS_RULE_VIOLATION",
                }
            if tool_name == "create_account":
                account_creation["requested"] = True

            tc = ToolCall(tool_name=tool_name, arguments=args)
            result = await route_tool_call(
                tc,
                organization_id=organization_id,
                user_id=user_id,
                session_id=session_id,
                auth=auth,
            )
            if tool_name == "create_account":
                if result.success:
                    account_creation["succeeded"] = True
                    # The explicit account now exists — no further
                    # create_account attempts are needed.
                    excluded_tools.add("create_account")
            # Reasoning-level narrowing: a successful party search that
            # resolved the named party disables the corresponding creation
            # tool for all subsequent iterations (planning-level fix — the
            # model is no longer OFFERED the creation tool).
            if tool_name in ("search_supplier", "search_customer") and result.success:
                from app.reasoning import PartyMatchState, classify_party_match

                match_state, _matches = classify_party_match(
                    result.data, execution_plan.entity_name
                )
                if match_state in (
                    PartyMatchState.EXACT,
                    PartyMatchState.RESOLVED_PARTIAL,
                    PartyMatchState.AMBIGUOUS,
                ):
                    created_tool = (
                        "create_supplier" if tool_name == "search_supplier"
                        else "create_customer"
                    )
                    excluded_tools.add(created_tool)
                    await _log_step(session_id, "PLANNING", {
                        "party_resolved": execution_plan.entity_name,
                        "party_match_state": match_state.value,
                        "creation_tool_disabled": created_tool,
                    })
                    # Explicit directive fed back with the tool result — the
                    # model must reuse the resolved record, not create one.
                    # For AMBIGUOUS matches the model must NOT silently pick
                    # a candidate: it asks the user or proceeds without the
                    # party ledger — never "first hit", never a duplicate.
                    directive = party_search_directive(
                        match_state, execution_plan.entity_name, created_tool
                    )
                    if isinstance(result.data, dict):
                        return {
                            "success": result.success,
                            **result.data,
                            "directive": directive,
                        }
                    if isinstance(result.data, list):
                        return {
                            "success": result.success,
                            "count": len(result.data),
                            "results": result.data,
                            "directive": directive,
                        }
            # Search tools return LISTS (supplier_service.search etc.) — a
            # dict-only branch would DROPPED them, so the model would receive
            # {"success": true} with no rows and keep re-searching or create
            # records blindly. All result shapes are fed back.
            if result.data is not None:
                if isinstance(result.data, dict):
                    return {"success": result.success, **result.data}
                if isinstance(result.data, list):
                    return {
                        "success": result.success,
                        "count": len(result.data),
                        "results": result.data,
                    }
                return {"success": result.success, "data": result.data}
            return {"success": result.success, "error": result.error}

        # Second AI call WITH executor — full iterative tool loop.
        # The model receives real parameters, executes tools, gets results
        # fed back, and can make follow-up calls until done.
        #
        # This call may only run on the LLM planning path: `client` and
        # `light_budget` are bound there (the `else` above).  On the
        # deterministic fast path they do not exist, so running it would
        # raise ``UnboundLocalError: cannot access local variable 'client'``
        # the moment a confirmed mutation resumed after user approval.  The
        # fast path executes its pre-built tool calls DIRECTLY — no LLM
        # round-trip, exactly what "bypass_llm" promises.
        if deterministic_calls is not None:
            # PROGRESS VISIBILITY: mirror the LLM path so the pipeline lights
            # the same EXECUTING stage on the fast path too.
            await _log_step(session_id, "EXECUTING", {
                "source": "deterministic",
                "intent": execution_plan.intent,
                "tools_planned": len(planned_tool_calls),
            })
            # ---- PLAN MATERIALIZATION (approved plans only) ----------------
            # An approved plan is expressed in the user's own terms
            # (`customer_name`, `product_name`); the tools need canonical ids.
            # Python resolves those references against the LIVE, tenant-scoped
            # books and BLOCKS with an explicit question when it cannot: it
            # never invents an id, never picks between ambiguous records, and
            # never creates anything the user did not approve.  The approved
            # snapshot in ai.confirmations.plan is left untouched — the mapping
            # is recorded durably in the step below.
            from app.plan_materialization import (
                bind_deferred as _bind_deferred,
                captured_ids as _captured_ids,
                prepare_plan as _prepare_plan,
                step_payload as _materialization_payload,
            )
            from app.tools import tool_contracts as _tool_argument_contracts

            materialization = await _prepare_plan(
                organization_id=organization_id,
                calls=planned_tool_calls,
                contracts=_tool_argument_contracts(),
            )
            await _log_step(
                session_id,
                "PLAN_MATERIALIZATION",
                _materialization_payload(materialization, original=planned_tool_calls),
            )
            if materialization.blocked:
                # STOP — ask, never guess.  Nothing has been executed.
                reason = " ".join(materialization.blocks)[:1500]
                question = reason
                try:
                    clarification = await create_clarification(
                        session_id=session_id,
                        question=reason,
                        required_fields=["resolution"],
                    )
                    question = clarification.get("question", reason)
                except Exception as exc:  # noqa: BLE001 — asking is not optional
                    # The question IS the contract with the user; a bookkeeping
                    # write must never turn "which record did you mean?" into a
                    # generic system failure (that is how a resolvable stop
                    # becomes an unexplained crash).
                    log.warning(
                        "agent.clarification_write_failed",
                        session_id=str(session_id),
                        error=str(exc)[:200],
                    )
                await _log_step(session_id, "AWAITING_CLARIFICATION", {
                    "source": "plan_materialization",
                    "question": reason[:300],
                })
                return AgentResponse(
                    status=ExecutionStatus.AWAITING_CLARIFICATION,
                    execution_id=session_id,
                    question=question,
                    required_information=["resolution"],
                    requires_user_input=True,
                )

            # Execute in dependency order: a call whose id comes from an
            # approved prerequisite step runs only AFTER that step produced the
            # id (captured from the real record — never invented).
            executed: List[Dict[str, Any]] = []
            provided_ids: Dict[str, str] = {}
            binding_problems: List[str] = []
            for batch in materialization.batches:
                batch_calls: List[ToolCall] = []
                for position in batch:
                    call = materialization.calls[position]
                    specs = materialization.deferred.get(position)
                    if specs:
                        call, issues = _bind_deferred(
                            call=call,
                            specs=specs,
                            provided_ids=provided_ids,
                            index=position,
                            decisions=materialization.decisions,
                        )
                        binding_problems.extend(issues)
                        if not issues:
                            # keep the canonical record equal to what runs
                            materialization.calls[position] = call
                    batch_calls.append(call)
                batch_results = await execute_planned_tool_calls(batch_calls, _executor)
                provided_ids.update(
                    _captured_ids(calls=batch_calls, results=batch_results)
                )
                executed.extend(batch_results)
            if binding_problems:
                # A prerequisite did not produce a record: the dependent call was
                # skipped rather than filled with an invented id.
                await _log_step(session_id, "FAILED", {
                    "reason": "prerequisite_missing",
                    "stage": "materialization",
                    "detail": " ".join(binding_problems)[:1000],
                    "controlled": True,
                })
            final_result = {
                "text": "",
                "tool_calls": materialization.calls,
                "tool_results": [
                    ToolResult(
                        tool_name=tc.tool_name,
                        success=bool(data.get("success", True)),
                        data=data,
                        error=data.get("error"),
                    )
                    for tc, data in zip(materialization.calls, executed)
                ],
            }
        else:
            # PROGRESS VISIBILITY: the iterative executor loop (up to
            # MAX_TOOL_ITERATIONS model round-trips) is the single longest
            # silent stretch of a run — measured 46-129s with NOTHING written
            # to ai.execution_steps.  Emit EXECUTING first so the UI reports
            # "Executing trusted tools" for the whole loop instead of
            # appearing hung.
            await _log_step(session_id, "EXECUTING", {
                "source": "llm_execution",
                "intent": execution_plan.intent,
                "tools_planned": len(planned_tool_calls),
            })
            final_result, provider_stall = await _bounded_provider_call(
                client.generate_with_tools(
                    user_message=user_message,
                    context=context,
                    executor=_executor,
                    excluded_tools=excluded_tools,
                    light_budget=light_budget,
                ),
                budget=_LLM_EXECUTION_BUDGET_SECONDS,
                stage="execution",
            )
            if final_result is None:
                # The run is closed honestly instead of being killed by the
                # host's function limit (which left the session stuck in
                # EXECUTING with no result and no recorded tool calls).  The
                # interruption is disclosed plainly: the tool loop may have
                # been cut short, so the user is told to check before
                # re-recording.
                await _update_status(session_id, ExecutionStatus.FAILED)
                await _log_step(session_id, "FAILED", {
                    "reason": provider_stall,
                    "stage": "execution",
                })
                return AgentResponse(
                    status=ExecutionStatus.FAILED,
                    execution_id=session_id,
                    summary=(
                        f"{provider_stall} The run was stopped before it could "
                        "finish, so please check the affected records before "
                        "asking again — anything already saved stays saved."
                    ),
                )
        llm_text = final_result.get("text", "") or llm_text
        tool_calls: List[ToolCall] = final_result.get("tool_calls", [])
        tool_results: List[ToolResult] = final_result.get("tool_results", [])

        # ---- BATCH per-document result breakdown -----------
        # Every sub-document is an INDEPENDENT mutation: a failed one never
        # rolls back its successful siblings. The result card must state
        # EXACTLY which documents succeeded and which failed - honestly,
        # derived from actual tool results, never assumed.
        if execution_plan.batch_items:
            breakdown = _build_batch_breakdown(
                execution_plan.batch_items, tool_calls, tool_results
            )
            if breakdown:
                await _log_step(session_id, "BATCH_EXECUTION", {
                    "documents": len(execution_plan.batch_items),
                    "breakdown": breakdown,
                })
                llm_text = (llm_text + "\n\n" + breakdown).strip()

        # Log every tool call for the audit trail (fire-and-forget; drained
        # by flush_step_logs before return).  A FAILED call also records WHY
        # it failed (error_details) — without it the cause of a failure
        # cannot be recovered from the database.
        for i, tc in enumerate(tool_calls):
            tr = tool_results[i] if i < len(tool_results) else None
            _spawn_step_write(
                log_tool_call(
                    session_id=session_id,
                    tool_name=tc.tool_name,
                    tool_input=tc.arguments,
                    tool_output=(
                        {"data": str(tr.data)[:2000], "success": tr.success}
                        if tr else None
                    ),
                    status="COMPLETED" if (tr and tr.success) else "FAILED",
                    error_details=_tool_audit_error_text(tr),
                )
            )

        # ---- NO ERP STATE CHANGED: the model wants user input, or answered
        # informationally.  An AI response is NOT a completed ERP operation.
        # If only read-only lookups ran (search/get/list) and the model asks
        # a question, route it to the clarification mechanism so the user
        # can answer and the SAME conversation resumes.  Anything else with
        # no mutations is an informational answer: COMPLETED but explicitly
        # NOT VERIFIED.
        if not _mutation_executed(tool_calls):
            model_question = _usable_question(llm_text)
            if model_question and len(prior_qa) < MODEL_MAX_CLARIFICATION_ROUNDS:
                await create_clarification(
                    session_id=session_id,
                    question=model_question,
                    required_fields=execution_plan.missing_fields,
                )
                await _log_step(session_id, "AWAITING_CLARIFICATION", {
                    "source": "model",
                    "stage": "execution",
                    "question": model_question[:500],
                })
                return AgentResponse(
                    status=ExecutionStatus.AWAITING_CLARIFICATION,
                    execution_id=session_id,
                    question=model_question,
                    required_information=execution_plan.missing_fields,
                    requires_user_input=True,
                )
            if not (llm_text or "").strip():
                # The model stalled (empty response) after only read-only
                # lookups — nothing was recorded.  Continue the conversation
                # instead of stranding the user.
                generic_question = (
                    "I couldn't complete this request with the information "
                    "available. Could you confirm or provide the remaining "
                    "details (e.g. the payee/vendor, the account to use, or "
                    "the exact amounts)?"
                )
                if len(prior_qa) < MODEL_MAX_CLARIFICATION_ROUNDS:
                    await create_clarification(
                        session_id=session_id,
                        question=generic_question,
                        required_fields=["missing_details"],
                    )
                    return AgentResponse(
                        status=ExecutionStatus.AWAITING_CLARIFICATION,
                        execution_id=session_id,
                        question=generic_question,
                        required_information=["missing_details"],
                        requires_user_input=True,
                    )
            await _update_status(session_id, ExecutionStatus.COMPLETED)
            await create_execution_result(
                session_id=session_id,
                result_data={
                    "summary": llm_text,
                    "tool_count": len(tool_results),
                    "mutations": 0,
                },
                summary=llm_text or execution_plan.expected_outcome or "Done.",
                action_type=execution_plan.intent,
                verification_status="UNVERIFIED",
                status="COMPLETED",
            )
            return AgentResponse(
                status=ExecutionStatus.COMPLETED,
                execution_id=session_id,
                action=execution_plan.intent,
                summary=llm_text or execution_plan.expected_outcome or "Done.",
                verification_status="UNVERIFIED",
            )

        # ---- PHASE 7: VALIDATION -----------------------------------------
        # FAILED must mean a GENUINE execution/system/validation failure —
        # never "the user hasn't provided enough information yet" (that is
        # AWAITING_CLARIFICATION, handled earlier) and never a tool error
        # the model already recovered from (a later successful tool call
        # completed the operation).
        successful_results = [tr for tr in tool_results if tr.success]
        failed_results = [tr for tr in tool_results if not tr.success]

        # ---- PHASE 6b: recoverable missing mandatory fields → clarify -----
        # A tool that failed because a MANDATORY backend value is missing
        # (e.g. PostgreSQL NOT NULL) must NOT terminate the operation: ask
        # the user a targeted question and resume the same pending
        # operation.  Genuine infrastructure failures never take this path
        # (they carry requires_user_input=False).
        user_input_failures = [
            tr for tr in failed_results
            if (tr.error_details or {}).get("requires_user_input")
        ]
        if (
            user_input_failures
            and len(prior_qa) < MODEL_MAX_CLARIFICATION_ROUNDS
        ):
            det = user_input_failures[0].error_details or {}
            question = build_missing_field_question(
                det.get("entity"),
                det.get("field"),
                record_name=(
                    context.extracted_entities.get("supplier_name")
                    or context.extracted_entities.get("customer_name")
                    or context.extracted_entities.get("entity_name")
                ),
            )
            await create_clarification(
                session_id=session_id,
                question=question,
                required_fields=[det.get("field") or "missing_value"],
            )
            await _log_step(session_id, "AWAITING_CLARIFICATION", {
                "source": "semantic_error",
                "category": det.get("category"),
                "operation": det.get("operation"),
                "field": det.get("field"),
                "question": question[:500],
            })
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=question,
                required_information=[det.get("field") or "missing_value"],
                requires_user_input=True,
            )

        if execution_plan.requires_validation and tool_results:
            await _update_status(session_id, ExecutionStatus.VALIDATING)
            if not successful_results:
                # Nothing succeeded — the operation genuinely failed.
                first_error = failed_results[0].error or "unknown error"
                # ---- CASH-CONFIG GATE (P5 mirror): no configured cash
                # drawer is a configuration state, not an execution failure —
                # park with a guided question ONCE instead of dead-ending in
                # "Something went wrong".  A second miss (already asked)
                # falls through to the genuine FAILED path below.
                if _is_cash_config_error(
                    first_error
                ) and not _cash_config_already_asked(prior_qa):
                    from app.services import bank_service

                    question = _cash_configuration_question(
                        await bank_service.find_cash_gl_account(organization_id)
                    )
                    await create_clarification(
                        session_id=session_id,
                        question=question,
                        required_fields=["cash_accounts_configuration"],
                    )
                    await _update_status(
                        session_id, ExecutionStatus.AWAITING_CLARIFICATION
                    )
                    await _log_step(
                        session_id,
                        "AWAITING_CLARIFICATION",
                        {
                            "source": "cash_accounts_configuration",
                            "question": question[:500],
                        },
                    )
                    return AgentResponse(
                        status=ExecutionStatus.AWAITING_CLARIFICATION,
                        execution_id=session_id,
                        question=question,
                        required_information=["cash_accounts_configuration"],
                        requires_user_input=True,
                    )
                # ---- EXECUTION-AGENT LOOP (RESCUE A): an account-
                # DETERMINATION failure with NOTHING recorded yet becomes the
                # account-creation clarification instead of a dead-end FAILED
                # run (mirrors the cash-config gate above; one-shot).
                _rescue = await _account_rescue_question(
                    session_id=session_id,
                    organization_id=organization_id,
                    execution_plan=execution_plan,
                    failures=failed_results,
                    prior_qa=prior_qa,
                )
                if _rescue is not None:
                    return _rescue
                await _update_status(session_id, ExecutionStatus.FAILED)
                await create_execution_result(
                    session_id=session_id,
                    result_data={
                        "error": first_error,
                        "tool": failed_results[0].tool_name,
                        "failed_tools": [
                            {"tool": tr.tool_name, "error": tr.error}
                            for tr in failed_results
                        ],
                    },
                    summary=f"Error: {first_error}",
                    verification_status="FAILED",
                )
                await _log_step(session_id, "FAILED", {
                    "stage": "execution",
                    "reason": "no_tool_succeeded",
                    "failed": [tr.tool_name for tr in failed_results],
                    "controlled": True,
                })
                return AgentResponse(
                    status=ExecutionStatus.FAILED,
                    execution_id=session_id,
                    summary=f"Operation failed: {first_error}",
                )
            # Operation-level verification: a successful AUXILIARY step never
            # proves the user's PRIMARY requested operation succeeded.  A
            # failed financial mutation — and always a failed/missing primary
            # mutation — makes the whole execution FAILED (fail-closed), even
            # though successful auxiliary mutations are retained and reported.
            required_failures = _financial_mutation_failures(tool_results)
            if _primary_mutation_failed(
                tool_results, intent=execution_plan.intent
            ):
                # Match the intent's OWN tools (record_expense -> create_expense;
                # record_sale/record_credit_sale -> create_invoice) — comparing
                # the intent string with a tool-result name matched nothing for
                # those intents and turned a RECORDED expense into "primary
                # operation did not execute".
                primary_tools = _intent_tool_names(execution_plan.intent)
                primary = [
                    tr for tr in tool_results
                    if tr.tool_name in primary_tools
                ]
                if primary:
                    required_failures.extend(
                        tr for tr in primary
                        if not tr.success
                        and all(tr is not r for r in required_failures)
                    )
                else:
                    required_failures.append(
                        ToolResult(
                            tool_name=execution_plan.intent,
                            success=False,
                            error="primary operation did not execute",
                        )
                    )
            if required_failures:
                # ---- EXECUTION-AGENT LOOP (RESCUE B): the primary mutation
                # failed on an account-DETERMINATION error while no WRITE has
                # succeeded (read-only lookups may have) and no creation is
                # confirmed yet → ask the same account-creation question
                # instead of parking FAILED.  Account resolution is
                # dependency-first in the services, so nothing financial was
                # posted when this error fires.
                from app.tool_execution import is_read_only_tool

                _rescue = await _account_rescue_question(
                    session_id=session_id,
                    organization_id=organization_id,
                    execution_plan=execution_plan,
                    failures=required_failures,
                    prior_qa=prior_qa,
                    require_no_successful_writes=all(
                        not tr.success or is_read_only_tool(tr.tool_name)
                        for tr in tool_results
                    ),
                )
                if _rescue is not None:
                    return _rescue
                failed_ops = [tr.tool_name for tr in required_failures]
                failed_detail = "; ".join(
                    f"{tr.tool_name}: {(tr.error or 'failed')[:160]}"
                    for tr in required_failures
                )
                failure_summary = _execution_failure_summary(
                    successful_results, required_failures,
                    intent=execution_plan.intent,
                )
                # Same canonical contract builders PHASE 9 uses (entity_contract)
                # so the failure result card carries the real affected entities
                # of the mutations that DID happen.
                affected = build_affected_entities(tool_results)
                accounting_impact = await build_accounting_impact(
                    tool_results,
                    resolve_account_name=_make_account_label_resolver(
                        organization_id
                    ),
                )
                # Durable timeline: the execution must explicitly show
                #   <auxiliary> -> SUCCESS, <primary> -> FAILED, overall FAILED
                # instead of ending silently (or worse, at a success step).
                await _update_status(session_id, ExecutionStatus.FAILED)
                await _log_step(session_id, "FAILED", {
                    "stage": "execution",
                    "reason": "required_mutation_failed",
                    "failed_operations": failed_ops,
                    "succeeded_operations": [
                        tr.tool_name for tr in successful_results
                    ],
                    "detail": failed_detail[:300],
                    "controlled": True,
                })
                # The result row is mechanical truth — never the LLM
                # narrative or the plan's expected_outcome.
                await create_execution_result(
                    session_id=session_id,
                    result_data={
                        "summary": failure_summary,
                        "tool_count": len(tool_results),
                        "succeeded_operations": [
                            tr.tool_name for tr in successful_results
                        ],
                        "failed_operations": [
                            {
                                "tool": tr.tool_name,
                                "error": (tr.error or "")[:300],
                            }
                            for tr in required_failures
                        ],
                        "affected_entities": affected,
                        "accounting_impact": accounting_impact,
                    },
                    summary=failure_summary,
                    action_type=execution_plan.intent,
                    affected_entities=affected,
                    verification_status="FAILED",
                    status="FAILED",
                )
                return AgentResponse(
                    status=ExecutionStatus.FAILED,
                    execution_id=session_id,
                    action=execution_plan.intent,
                    summary=failure_summary,
                    affected_entities=affected if affected else None,
                    accounting_impact=(
                        accounting_impact if accounting_impact else None
                    ),
                    verification_status="FAILED",
                )
            if failed_results:
                # Recovered partial failure — only NON-required operations
                # (read-only lookups, non-financial auxiliaries) can reach
                # here.  Keep executing; report them transparently.
                await _log_step(session_id, "VALIDATING", {
                    "recovered_failures": [
                        {"tool": tr.tool_name, "error": (tr.error or "")[:300]}
                        for tr in failed_results
                    ],
                })

        # ---- PHASE 8: VERIFICATION ---------------------------------------
        # VERIFIED means the ERP operation actually executed and its
        # resulting DB state was verified (accounting engine).  A response
        # with no executed tools can never be VERIFIED.
        await _update_status(session_id, ExecutionStatus.VERIFYING)
        verified = (
            bool(successful_results)
            and not _primary_mutation_failed(
                tool_results, intent=execution_plan.intent
            )
        )
        for tr in tool_results:
            if tr.success and tr.data and isinstance(tr.data, dict):
                entry = tr.data.get("entry")
                if entry and entry.get("id"):
                    vr = await verify_journal(
                        organization_id=organization_id,
                        entry_id=uuid.UUID(entry["id"]),
                    )
                    if not vr.get("verified"):
                        verified = False
                        log.warning(
                            "journal_verification_failed",
                            session_id=str(session_id),
                            entry_id=str(entry["id"]),
                            tool=tr.tool_name,
                        )
                    else:
                        log.info(
                            "journal_verified",
                            session_id=str(session_id),
                            entry_id=str(entry["id"]),
                            tool=tr.tool_name,
                        )

        # ---- PHASE 9: COMPLETED ------------------------------------------
        status = ExecutionStatus.COMPLETED if verified else ExecutionStatus.FAILED
        await _update_status(session_id, status)

        # Build canonical affected entities + accounting impact.
        # Contracts are defined in app/entity_contract.py and mirrored in
        # frontend/src/lib/types/api.ts — the builders guarantee the shape
        # (e.g. affected_entities[].type is always a non-empty string).
        affected = build_affected_entities(tool_results)
        accounting_impact = await build_accounting_impact(
            tool_results,
            resolve_account_name=_make_account_label_resolver(organization_id),
        )

        # surface the recorded transaction date so the result
        # card can state "Dated: YYYY-MM-DD" honestly (including a defaulted
        # today-assumption flagged by the tool router).
        recorded_date, date_defaulted = _extract_recorded_date(tool_results)
        # surface the resolved nature (and its source) so
        # the result card can state "Nature: Fixed Asset - you confirmed"
        # honestly, next to the Dated badge.
        nature_data: Dict[str, Any] = (
            {
                "transaction_nature": execution_plan.transaction_nature,
                "transaction_nature_source": (
                    execution_plan.transaction_nature_source
                ),
            }
            if execution_plan.transaction_nature
            else {}
        )
        response_data = (
            {
                "transaction_date": recorded_date,
                "date_defaulted": date_defaulted,
                **nature_data,
            }
            if recorded_date or nature_data
            else None
        )

        result_summary = llm_text or execution_plan.expected_outcome or "Operation completed."
        if not verified and _primary_mutation_failed(
            tool_results, intent=execution_plan.intent
        ):
            # Belt-and-braces: the VALIDATION phase already returns on a failed
            # primary mutation, so this is unreachable for a real plan
            # (requires_validation is True for every mutation intent).  If it
            # ever IS reached, the execution is NOT verified — so the persisted
            # summary must be the mechanical failure truth, never the LLM
            # narrative or the plan's expected_outcome.
            result_summary = _execution_failure_summary(
                successful_results,
                [
                    tr for tr in tool_results
                    if not tr.success and tr.tool_name in FINANCIAL_WRITE_TOOLS
                ],
                intent=execution_plan.intent,
            )
        elif failed_results:
            # Only NON-required failures reach here (read-only lookups,
            # non-financial auxiliaries).  Report them accurately: nothing
            # was retried, so never use retry wording.
            remaining = "; ".join(
                f"{tr.tool_name} failed: {(tr.error or 'failed')[:120]}"
                for tr in failed_results
            )
            result_summary = (
                f"{result_summary}\n\nNote — some operations failed "
                f"(they were not retried): {remaining}"
            )

        await create_execution_result(
            session_id=session_id,
            result_data={
                "summary": result_summary,
                "tool_count": len(tool_results),
                "affected_entities": affected,
                "accounting_impact": accounting_impact,
                **({"transaction_date": recorded_date,
                    "date_defaulted": date_defaulted} if recorded_date else {}),
                **nature_data,
            },
            summary=result_summary,
            action_type=execution_plan.intent,
            affected_entities=affected,
            verification_status="VERIFIED" if verified else "FAILED",
            status="COMPLETED" if verified else "FAILED",
        )

        return AgentResponse(
            status=status,
            execution_id=session_id,
            action=execution_plan.intent,
            summary=result_summary,
            affected_entities=affected if affected else None,
            accounting_impact=accounting_impact if accounting_impact else None,
            verification_status="VERIFIED" if verified else "FAILED",
            data=response_data,
        )

    except Exception as exc:
        log.error("agent.execute.error", error=str(exc), session_id=str(session_id) if session_id else None)
        if session_id:
            await _update_status(session_id, ExecutionStatus.FAILED)
            await create_execution_result(
                session_id=session_id,
                result_data={"error": str(exc)},
                summary=f"Error: {exc}",
                verification_status="FAILED",
                status="FAILED",
            )
            # Durable timeline: an unhandled exception must be visible in the
            # execution timeline as FAILED, not leave it silently ending at
            # the previous successful step.  "FAILED" is in
            # _DURABLE_STEP_TYPES, so this write is awaited inline — it
            # cannot be lost to a queue flush or a torn-down serverless
            # invocation.  The result row above is written as before.
            await _log_step(session_id, "FAILED", {
                "stage": "agent_execute",
                "reason": str(exc)[:300],
                "error_type": type(exc).__name__,
                "controlled": False,
            })
        return AgentResponse(
            status=ExecutionStatus.FAILED,
            execution_id=session_id,
            summary="An unexpected error occurred. Please try again.",
        )
    finally:
        # all fire-and-forget audit writes are drained
        # before the request returns - the user never waited on them,
        # but every one of them has landed by now.
        # P2-⑪/⑮: compute this session's flush policy BEFORE releasing its
        # bookkeeping, then drain the step queue (250ms cap only when the
        # run PARKED; terminal keeps the full drain — audit-loss review in
        # flush_step_logs / _flush_cap_for).
        _flush_cap = (
            _flush_cap_for(_CLOSE_MARKERS.get(str(session_id)))
            if session_id is not None
            else None
        )
        if session_id is not None:
            _STEP_START.pop(str(session_id), None)
            _CLOSE_MARKERS.pop(str(session_id), None)
        await flush_step_logs(cap_seconds=_flush_cap)


def _session_is_owned(session: Optional[Dict[str, Any]], organization_id: uuid.UUID,
                      user_id: uuid.UUID) -> bool:
    """The session exists AND belongs to the caller's organisation and user."""
    if not session:
        return False
    return (
        str(session.get("organization_id") or "") == str(organization_id)
        and str(session.get("user_id") or "") == str(user_id)
    )


def _session_is_pending(session: Dict[str, Any]) -> bool:
    """The session is still parked on a user decision."""
    return str(session.get("status") or "") == "WAITING_FOR_USER"


async def resume_with_clarification(
    *,
    session_id: uuid.UUID,
    user_answer: str,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    auth: Optional[AuthContext] = None,
) -> AgentResponse:
    """Resume a session after the user answered a clarification.

    The answer is merged with the ORIGINAL request (not treated as a new
    isolated request): the full Q&A history for this session — including
    the just-answered question — is reloaded from the database and passed
    through ``execute(clarification_history=...)`` so the Planner folds
    every answered value into entity extraction and never re-asks it.

    Authorisation + idempotency:
      * the session must exist AND belong to the caller (organisation + user);
      * an empty/whitespace answer is rejected — the clarification stays
        pending with a targeted error;
      * a non-WAITING session has already been answered (duplicate retry,
        double click, replayed HTTP request) and returns a SAFE idempotent
        response — it never re-enters execute() and can never create a
        second ledger, invoice or journal.
    """
    session = await fetch_one("ai_execution_sessions", filters={"id": str(session_id)})
    if not _session_is_owned(session, organization_id, user_id):
        # Not found / not yours — the same response for both, so an
        # attacker learns nothing about other organisations' sessions.
        return AgentResponse(
            status=ExecutionStatus.FAILED,
            summary="Session not found.",
        )
    answer = str(user_answer or "").strip()
    if not answer:
        # Empty or whitespace answers must not consume the pending
        # question — the user is asked again with a targeted error.
        return AgentResponse(
            status=ExecutionStatus.AWAITING_CLARIFICATION,
            execution_id=session_id,
            question=str(session.get("user_request") or "").splitlines()[0]
            if session.get("user_request") else "An answer is required.",
            required_information=["revenue_ledger_decision"],
            requires_user_input=True,
            summary="An answer is required.",
        )
    if not _session_is_pending(session):
        # Already answered/completed — the answer round already ran (or this
        # request is a duplicate).  Replaying execute() here would re-plan and
        # could create a SECOND mutation.  Return a safe idempotent response.
        log.info(
            "duplicate_resume_rejected",
            session_id=str(session_id),
            endpoint="clarify",
            session_status=str(session.get("status"))[:20],
        )
        return await _idempotent_resume_response(session, endpoint="clarify")

    log.info(
        "ledger_answer_received",
        session_id=str(session_id),
        answer_length=len(answer),
    )
    # Record the user's answer on the pending clarification BEFORE resume —
    # the answer must survive even if the resumed run later fails.
    await resolve_clarification(session_id=session_id, user_response=answer)
    log.info("clarification_resumed", session_id=str(session_id))

    # Rebuild the COMPLETE Q&A history for this conversation — the planner
    # merges each answer into the entity set, and Gemini receives both the
    # original request and the structured history as context.
    history = await get_clarification_history(session_id)

    original_request = session.get("user_request", "") or ""
    return await execute(
        user_message=original_request,
        user_id=user_id,
        organization_id=organization_id,
        auth=auth,
        conversation_id=session.get("conversation_id"),
        clarification_history=history,
    )


async def _idempotent_resume_response(
    session: Dict[str, Any], *, endpoint: str
) -> AgentResponse:
    """A safe response for a duplicate resume of an already-resolved session.

    ``ai_execution_results`` holds the outcome of the run that consumed this
    session — replay it verbatim when available so the user sees the SAME
    completed answer their first request produced.  Never re-execute: a
    duplicate must not create a second ledger, invoice or journal.
    """
    session_id = uuid.UUID(str(session["id"]))
    try:
        stored = await fetch_one(
            "ai_execution_results",
            filters={"execution_session_id": str(session_id)},
        )
    except Exception:  # noqa: BLE001 — a read failure must not fabricate state
        stored = None
    if stored:
        summary = str(stored.get("summary") or "")
        if summary:
            log.info(
                "mutation_idempotency_hit",
                session_id=str(session_id),
                endpoint=endpoint,
            )
            return AgentResponse(
                status=ExecutionStatus.COMPLETED,
                execution_id=session_id,
                summary=summary,
            )
    # Nothing replayable is stored: the previous run is gone (reaped, or it
    # failed before writing a result).  Be honest — do NOT pretend success.
    log.warning(
        "mutation_idempotency_hit_no_result",
        session_id=str(session_id),
        endpoint=endpoint,
    )
    return AgentResponse(
        status=ExecutionStatus.FAILED,
        execution_id=session_id,
        summary=(
            "This request was already processed and its result is no longer "
            "available. Please send the request again as a new message — "
            "it was not duplicated."
        ),
    )


async def resume_with_confirmation(
    *,
    session_id: uuid.UUID,
    approved: bool,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    auth: Optional[AuthContext] = None,
) -> AgentResponse:
    """Resume a session after the user confirmed/rejected an action.

    Authorisation + idempotency mirror ``resume_with_clarification``: the
    session must belong to the caller and still be WAITING_FOR_USER; a
    duplicate confirm returns the stored result without re-executing.
    """
    session = await fetch_one("ai_execution_sessions", filters={"id": str(session_id)})
    if not _session_is_owned(session, organization_id, user_id):
        return AgentResponse(
            status=ExecutionStatus.FAILED,
            summary="Session not found.",
        )
    if not _session_is_pending(session):
        log.info(
            "duplicate_resume_rejected",
            session_id=str(session_id),
            endpoint="confirm",
            session_status=str(session.get("status"))[:20],
        )
        return await _idempotent_resume_response(session, endpoint="confirm")

    # Read the PENDING confirmation row BEFORE resolving it: its plan
    # snapshot (migration 079) is the plan the user actually approved.
    confirmations = await fetch_many(
        "ai_confirmations",
        filters={"execution_session_id": str(session_id)},
        order="created_at.asc",
        limit=100,
    )
    pending_row = next(
        (c for c in confirmations if c.get("user_confirmed") is None), None
    )
    await resolve_confirmation(
        session_id=session_id, approved=approved, user_id=user_id
    )
    log.info(
        "confirmation_resumed",
        session_id=str(session_id),
        approved=bool(approved),
    )
    if not approved:
        await _update_status(session_id, ExecutionStatus.REJECTED)
        return AgentResponse(
            status=ExecutionStatus.REJECTED,
            execution_id=session_id,
            summary="Action was rejected by the user.",
        )
    # Reuse the APPROVED plan verbatim (migration 079): the resumed run
    # cannot re-plan into different tools or lose the approved entities
    # (e.g. the resolved revenue_account_id).
    approved_calls: Optional[List[ToolCall]] = None
    snapshot = (pending_row or {}).get("plan")
    if isinstance(snapshot, list) and snapshot:
        calls = [
            ToolCall(
                tool_name=str(entry["tool_name"]),
                arguments=dict(entry.get("arguments") or {}),
            )
            for entry in snapshot
            if isinstance(entry, dict) and entry.get("tool_name")
        ]
        if calls:
            approved_calls = calls
            log.info(
                "approved_plan_reused",
                session_id=str(session_id),
                tools=[c.tool_name for c in calls],
            )
    # If approved, continue execution — carrying any clarification history
    # from this session forward so answered questions stay answered.
    history = await get_clarification_history(session_id)
    return await execute(
        user_message=session.get("user_request", ""),
        user_id=user_id,
        organization_id=organization_id,
        auth=auth,
        conversation_id=session.get("conversation_id"),
        clarification_history=history,
        # The user just approved this action — skip the PHASE 5 gate so
        # execution proceeds instead of re-raising a new confirmation.
        confirmation_granted=True,
        approved_tool_calls=approved_calls,
        # P0-①: carry the APPROVED intent (the confirmation's action_type)
        # so verification keys on what the user confirmed — the keyword
        # planner on this turn runs without the semantic prefill and may not
        # re-derive the original intent on its own.
        confirmed_intent=str((pending_row or {}).get("action_type") or "") or None,
    )


# ---- Private helpers -------------------------------------------------------

async def _update_status(session_id: uuid.UUID, phase: ExecutionStatus) -> None:
    """Persist the execution phase and its derived session status."""
    status, completed = _PHASE_STATUS_MAP.get(phase, ("EXECUTING", False))
    await set_session_phase(
        session_id, phase=phase.value, status=status, completed=completed
    )


# ---------------------------------------------------------------------------
# Fire-and-forget step logging.
#
# Step/control-plane writes (RECEIVED, CLASSIFICATION, ... plus the
# per-tool-call audit rows) must NEVER sit in the user's critical path:
# they are scheduled onto a background task queue with a bounded backlog
# and exception swallowing. flush_step_logs() drains the queue right
# before the request returns, so audit writes still LAND - they just stop
# making the user wait.
# ---------------------------------------------------------------------------
_STEP_TASK_MAX_PENDING = 64
_pending_step_tasks: "deque[asyncio.Task]" = deque()

# P2-⑪/⑮: per-session bookkeeping — wall-clock start (elapsed_ms on every
# step row) and the last parking/terminal marker (flush policy + SQL joins).
_STEP_START: Dict[str, float] = {}
_CLOSE_MARKERS: Dict[str, str] = {}


def _spawn_step_write(coro) -> None:
    """Schedule a control-plane write on the background queue (bounded)."""
    task = asyncio.create_task(coro)
    _pending_step_tasks.append(task)
    # Bounded backlog: under a pathological burst (>64 unwritten writes)
    # the OLDEST write is awaited inline - audit rows are never dropped.
    while len(_pending_step_tasks) > _STEP_TASK_MAX_PENDING:
        oldest = _pending_step_tasks.popleft()
        if not oldest.done():
            try:
                asyncio.get_running_loop().create_task(
                    _await_and_swallow(oldest)
                )
            except Exception:  # noqa: BLE001 - never break the caller
                pass


async def _await_and_swallow(task: asyncio.Task) -> None:
    try:
        await task
    except Exception as exc:  # noqa: BLE001 - audit write failure is logged
        log.warning("agent.step_log_failed", error=str(exc))


async def flush_step_logs(cap_seconds: Optional[float] = None) -> None:
    """Drain the background step-write queue before the response returns.

    P2-⑮ (forensic report ⑮, AFTER the audit-loss review):

    * ``cap_seconds=None`` — terminal states and anything unknown — keeps
      the ORIGINAL full drain: every scheduled audit write lands;
    * a cap (0.25s, parking responses) bounds user-visible wait. Writes
      past the cap are DETACHED with a reaping callback (they still run in
      the background; no 'Task exception was never retrieved'). The
      durable AWAITING_*/FAILED rows are awaited inline in _log_step and
      can never be lost — only non-durable progress rows beyond the cap
      are at risk on a hard serverless freeze: observability, never
      correctness (the P1-⑤ memo load fails soft to a plain refetch).
    """
    deadline = None if cap_seconds is None else time.monotonic() + float(cap_seconds)

    def _detach_and_log(remaining_tasks) -> None:
        for pending in remaining_tasks:
            pending.add_done_callback(_swallow_later)
        log.warning(
            "agent.step_flush_bounded",
            cap_s=cap_seconds,
            detached=len(remaining_tasks),
        )

    while _pending_step_tasks:
        task = _pending_step_tasks.popleft()
        if task.done():
            # Surface (and swallow) any background exception now.
            exc = task.exception() if not task.cancelled() else None
            if exc is not None:
                log.warning("agent.step_log_failed", error=str(exc))
            continue
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _detach_and_log([task, *_pending_step_tasks])
                _pending_step_tasks.clear()
                return
            try:
                # asyncio.wait, NEVER wait_for: wait_for CANCELS the task
                # on timeout — a detached write must keep RUNNING in the
                # background, not be killed at the cap.
                done_set, _ = await asyncio.wait({task}, timeout=remaining)
            except asyncio.CancelledError:
                task.add_done_callback(_swallow_later)
                continue
            if not done_set:
                _detach_and_log([task, *_pending_step_tasks])
                _pending_step_tasks.clear()
                return
            exc = task.exception() if not task.cancelled() else None
            if exc is not None:
                log.warning("agent.step_log_failed", error=str(exc))
            continue
        try:
            await task
        except asyncio.CancelledError:
            # The write task was cancelled (shutdown) - nothing to log.
            continue
        except Exception as exc:  # noqa: BLE001 - audit write failure is logged
            log.warning("agent.step_log_failed", error=str(exc))


def _swallow_later(task: asyncio.Task) -> None:
    """Detach-callback for capped flushes (P2-⑮): reap late errors."""
    if task.cancelled():
        return
    try:
        task.exception()
    except Exception:  # noqa: BLE001 — reaping must never raise
        pass


# Step types that PARK a run or close it.  These are written DURABLY (awaited)
# rather than queued: the session status is persisted synchronously, so if the
# serverless invocation is torn down between the status write and the queue
# flush, a queued step would be lost and the dashboard would show "waiting for
# your answer" with NO question to answer.  That inconsistency is what made
# users re-send instead of answering and left orphaned WAITING_FOR_USER rows.
_DURABLE_STEP_TYPES = {
    "AWAITING_CLARIFICATION",
    "AWAITING_CONFIRMATION",
    "FAILED",
}


async def _log_step(session_id: uuid.UUID, step_type: str, data: Dict[str, Any]) -> None:
    """Record an execution step.

    Fire-and-forget by default: the write is scheduled on the background queue
    and drained by flush_step_logs() before the request returns, so audit
    writes never sit in the user's critical path.

    Steps that park or close the run are the exception — see
    _DURABLE_STEP_TYPES — and are awaited here.
    """
    _sid = str(session_id)
    # P2-⑮: remember the last parking/terminal marker for the flush policy.
    if step_type in (
        "AWAITING_CLARIFICATION", "AWAITING_CONFIRMATION",
        "COMPLETED", "FAILED", "REJECTED", "CANCELLED",
    ):
        if len(_CLOSE_MARKERS) > 512:
            _CLOSE_MARKERS.clear()
        _CLOSE_MARKERS[_sid] = step_type
    # P2-⑪: elapsed_ms since this session's start — stamped SYNCHRONOUSLY
    # here, before any spawn, so the value can never go stale.
    t0 = _STEP_START.get(_sid)
    if t0 is not None:
        data = {**data, "elapsed_ms": int((time.monotonic() - t0) * 1000)}
    coro = create_execution_step(
        session_id=session_id,
        step_type=step_type,
        step_data=data,
    )
    if step_type in _DURABLE_STEP_TYPES:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 — never fail the run on audit
            log.warning("agent.step_log_failed", step=step_type, error=str(exc))
        return
    _spawn_step_write(coro)


# P1-⑤: step markers that PROVE the books may have changed. A memo snapshot
# is reused ONLY from the latest prior session of the conversation when it
# PARKED at a clarification (parking happens BEFORE Phase 6 — no tool ever
# ran) AND none of these markers appear. COMPLETED / FAILED are deliberately
# included: a terminal run may have mutated (FAILED can leave partial
# writes), so the memo fails TOWARD re-fetching — a miss is always safe,
# only a wrong hit would be a correctness bug.
_MUTATION_STEP_MARKERS = frozenset(
    {
        "DETERMINISTIC_EXECUTION",
        "EXECUTING",
        "EXECUTING_TOOLS",
        "REASONING_PLAN_EXECUTION",
        "APPROVED_PLAN_REUSED",
        "TOOL_FAILURE",
        "COMPLETED",
        "FAILED",
    }
)


async def _load_prior_evidence(
    *,
    conversation_id: str,
    organization_id: uuid.UUID,
    current_session_id: uuid.UUID,
) -> List[Any]:
    """P1-⑤: load the conversation's reusable evidence memo, or ``[]``.

    The carrier is the DATABASE (serverless-safe: any instance, any turn —
    an in-process cache would die between invocations). Freshness =
    the latest PRIOR session of this conversation parked at a
    clarification, carried no mutation marker, and holds a serialized
    ``evidence_full`` payload. Anything unexpected -> ``[]`` (a plain
    refetch: a miss is safe, only a wrong hit would be a correctness bug).
    """
    from app.accounting_reasoning import deserialize_evidence_memo

    try:
        sessions = await fetch_many(
            "ai_execution_sessions",
            filters={
                "conversation_id": str(conversation_id),
                "organization_id": str(organization_id),
            },
            select="id",
            order="started_at.desc",
            limit=5,
        )
        prior = next(
            (
                s
                for s in sessions or []
                if str(s.get("id")) != str(current_session_id)
            ),
            None,
        )
        if not prior:
            return []
        steps = await fetch_many(
            "ai_execution_steps",
            filters={"execution_session_id": str(prior["id"])},
            select="description,input_summary",
            order="created_at",
            limit=300,
        ) or []
        descs = [str(s.get("description") or "") for s in steps]
        if "AWAITING_CLARIFICATION" not in descs:
            return []
        if any(d in _MUTATION_STEP_MARKERS for d in descs):
            return []
        payload = next(
            (
                s.get("input_summary")
                for s in reversed(steps)
                if str(s.get("description") or "") == "ACCOUNTING_REASONING"
            ),
            None,
        )
        if not payload:
            return []
        return deserialize_evidence_memo(payload)
    except Exception as exc:  # noqa: BLE001 — the memo is best-effort only
        log.warning("agent.prior_evidence_load_failed", error=str(exc)[:200])
        return []


def _intent_tool_names(intent: str) -> frozenset:
    """The TOOL SLUGS that carry out *intent* as a financial mutation.

    The intent names what the USER asked for; a tool result is named by the
    callable that ran.  Those names differ for exactly the expense/sale intents:

        record_expense      -> create_expense
        record_sale         -> create_invoice
        record_credit_sale  -> create_invoice

    Comparing the intent STRING with a tool-result name therefore matched
    nothing for those intents — and PHASE 7 (``required_failures``) and PHASE 8
    (``verified``) both key on that comparison, so a RECORDED expense was
    reported as "primary operation did not execute" and the run was closed
    FAILED while the expense and its journal were in the books.  The mapping is
    reused from app/tool_selector.py (the intent->toolset primitive) and
    narrowed to the tools that actually write the books.

    Returns the empty set for a non-financial intent — the caller must treat
    that as "this execution is not a financial mutation" (never as a failure).
    """
    from app.tool_selector import intent_tools

    candidates = set(intent_tools(intent)) | {str(intent or "")}
    return frozenset(name for name in candidates if name in FINANCIAL_WRITE_TOOLS)


def _financial_mutation_failures(tool_results: Sequence[ToolResult]) -> List[ToolResult]:
    """Failed FINANCIAL mutations (idempotency-guarded writes to the books).

    A failed financial mutation can never be a "recovered" detail: the books
    either carry the entry or they do not, so its failure is operation-level.
    """
    return [
        tr for tr in tool_results
        if not tr.success and tr.tool_name in FINANCIAL_WRITE_TOOLS
    ]


def _primary_mutation_failed(tool_results: Sequence[ToolResult], *, intent: str) -> bool:
    """True when the user's PRIMARY requested mutation did not succeed.

    The execution intent names the primary operation (e.g. ``create_invoice``).
    For a financial-intent execution the outcome is only honest when:

    * the primary tool actually ran, AND
    * it succeeded.

    A successful AUXILIARY step (``create_customer``) proves nothing about the
    primary operation and can never satisfy this check.
    """
    primary_tools = _intent_tool_names(intent)
    if not primary_tools:
        return False
    primary_results = [tr for tr in tool_results if tr.tool_name in primary_tools]
    if not primary_results:
        # The primary mutation never executed at all.
        return True
    return any(not tr.success for tr in primary_results)


def _plan_performs_no_financial_mutation(
    *, intent: str, calls: Sequence[ToolCall]
) -> bool:
    """True when a plan about to be approved performs NO financial mutation.

    The intent names the operation the USER asked for.  A plan that only prepares
    state (creating the party, a catalog lookup) cannot deliver it: execution then
    "succeeds" at its auxiliary steps while the primary operation never runs —
    production 2026-09-22 (session 0076d9a0) approved
    ``create_customer`` + ``search_product`` for "create an invoice for fds labs
    pvt …", the customer was written, and the invoice could never be recorded.

    ``_primary_mutation_failed`` catches that AFTER execution (and #9 reports it
    honestly); this check refuses to SNAPSHOT the plan at all, so the user is
    never asked to approve an operation that cannot happen and no partial state
    is written.  Only a plan with NO financial mutation at all is refused — a
    plan performing a DIFFERENT financial operation is a legitimate
    re-interpretation (the model may correct the intent) and is judged by the
    confirmation text the user reads, not by this gate.

    Both halves use the TOOL vocabulary (``FINANCIAL_WRITE_TOOLS``): the intent
    only decides WHETHER this execution is financial, never whether a tool
    result matches it by name.
    """
    if not _intent_tool_names(intent):
        return False
    return not any(tc.tool_name in FINANCIAL_WRITE_TOOLS for tc in calls or ())


def _execution_failure_summary(
    successful_results: Sequence[ToolResult],
    failed_results: Sequence[ToolResult],
    *,
    intent: str,
) -> str:
    """Mechanical, evidence-derived failure summary.

    Built ONLY from actual tool results — never from the LLM narrative or the
    plan's ``expected_outcome``.  Principle: an LLM expected outcome is not a
    verified database outcome; only the latter may produce a success claim,
    and a failure claim must state exactly what succeeded and what did not.
    """
    succeeded = [tr.tool_name for tr in successful_results]
    failed = [tr.tool_name for tr in failed_results]
    parts = []
    if intent in failed:
        parts.append(f"{intent} failed — nothing was recorded for it")
    else:
        parts.append(f"{', '.join(failed)} failed")
    if succeeded:
        parts.append(
            "completed before the failure: " + ", ".join(succeeded)
        )
    return "Operation FAILED. " + ". ".join(parts) + "."


def _mutation_date(
    tc: ToolCall, tr: Optional[ToolResult]
) -> Optional[str]:
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


# every key a mutation tool may use for its accounting date.
_RECORDED_DATE_KEYS = (
    "transaction_date", "invoice_date", "bill_date", "expense_date",
    "quotation_date", "credit_note_date", "return_date", "receipt_date",
    "payment_date", "transfer_date",
)


def _extract_recorded_date(
    tool_results: List[ToolResult],
) -> tuple[Optional[str], bool]:
    """Recorded transaction date + defaulted flag from mutation results.

    Returns ``(iso_date_or_document_date, date_defaulted)``; the date is
    ``None`` when no executed tool reported one (read-only runs).
    """
    date_val: Optional[str] = None
    defaulted = False
    for tr in tool_results or []:
        data = tr.data if isinstance(tr.data, dict) else {}
        if not date_val:
            for key in _RECORDED_DATE_KEYS:
                if data.get(key):
                    date_val = str(data[key])[:10]
                    break
        defaulted = defaulted or bool(data.get("date_defaulted"))
        if date_val and defaulted:
            break
    return date_val, defaulted


def _build_batch_breakdown(
    batch_items: List[Dict[str, Any]],
    tool_calls: List[ToolCall],
    tool_results: List[ToolResult],
) -> str:
    """Per-document result summary for a BATCH plan.

    Mutations are collected in execution order and reported one per line.
    The report is honest: fewer mutations executed than documents planned,
    or any failure, is stated explicitly.  each created
    document also states its recorded transaction date.
    """
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
            dated = _mutation_date(tc, tr)
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
