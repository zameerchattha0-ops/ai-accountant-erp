"""
Canonical entity contracts — single source of truth for what the agent
sends to the frontend in ``AgentResponse.affected_entities`` and
``AgentResponse.accounting_impact``.

The frontend renders these shapes directly (``AIActionCard``), so the
builders GUARANTEE the contract:

* ``affected_entities[].type`` is always a non-empty snake_case string —
  even when a tool result is malformed, partially missing, or None.
* ``accounting_impact[]`` always carries an ``account`` label (resolved
  from the account id when possible) and at most one of debit/credit.

Mirrors ``frontend/src/lib/types/api.ts`` — keep both in sync.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Tool slug -> (canonical entity type, action)
# ---------------------------------------------------------------------------
_TOOL_ENTITY_MAP: Dict[str, Tuple[str, str]] = {
    "create_customer": ("customer", "created"),
    "get_customer": ("customer", "fetched"),
    "search_customer": ("customer", "fetched"),
    "create_supplier": ("supplier", "created"),
    "get_supplier": ("supplier", "fetched"),
    "search_supplier": ("supplier", "fetched"),
    "create_invoice": ("invoice", "created"),
    "get_invoice": ("invoice", "fetched"),
    "create_purchase_bill": ("bill", "created"),
    "get_purchase_bill": ("bill", "fetched"),
    "create_expense": ("expense", "created"),
    "record_customer_receipt": ("receipt", "created"),
    "record_supplier_payment": ("payment", "created"),
    "record_expense_payment": ("payment", "created"),
    "create_bank_account": ("bank_account", "created"),
    "list_bank_accounts": ("bank_account", "fetched"),
    "record_bank_transfer": ("bank_transfer", "created"),
    "prepare_journal": ("journal_entry", "prepared"),
    "validate_journal": ("journal_entry", "validated"),
    "post_journal": ("journal_entry", "posted"),
    "reverse_journal": ("journal_entry", "reversed"),
    "create_project": ("project", "created"),
    "get_project": ("project", "fetched"),
    "create_quotation": ("quotation", "created"),
    "convert_quotation": ("invoice", "created"),
    "create_credit_note": ("credit_note", "created"),
    "create_purchase_return": ("purchase_return", "created"),
    "create_account": ("account", "created"),
    "create_product": ("product", "created"),
    "search_product": ("product", "fetched"),
    "create_service": ("service", "created"),
    "search_service": ("service", "fetched"),
    "register_fixed_asset": ("fixed_asset", "created"),
    "search_fixed_asset": ("fixed_asset", "fetched"),
    "get_fixed_asset": ("fixed_asset", "fetched"),
    "dispose_fixed_asset": ("fixed_asset", "disposed"),
    "record_asset_depreciation": ("fixed_asset", "updated"),
}

_VERB_TO_ACTION = {
    "create": "created",
    "record": "created",
    "prepare": "prepared",
    "validate": "validated",
    "post": "posted",
    "reverse": "reversed",
    "search": "fetched",
    "get": "fetched",
    "list": "fetched",
    "classify": "fetched",
}

_NAME_KEYS = (
    "name", "customer_name", "supplier_name", "account_name",
    "display_name", "title", "description",
)
_NUMBER_KEYS = (
    "journal_number", "invoice_number", "bill_number", "receipt_number",
    "payment_number", "quotation_number", "credit_note_number",
    "document_number", "number", "code",
)
_TOTAL_KEYS = (
    "total", "total_debit", "grand_total", "total_amount", "amount",
)
_ID_KEYS = ("id", "entry_id", "record_id", "party_id")

_UNKNOWN_TYPE = "record"


def _derive_type_action(tool_name: str) -> Tuple[str, str]:
    """Map a tool slug to (entity_type, action). Never returns empty type."""
    mapped = _TOOL_ENTITY_MAP.get(tool_name)
    if mapped:
        return mapped[0], mapped[1]
    # Fallback: strip a known verb prefix: "create_supplier" -> supplier
    match = re.match(r"^([a-z]+)_(.+)$", tool_name or "")
    if match:
        verb, noun = match.group(1), match.group(2)
        if noun and noun not in _VERB_TO_ACTION:
            return noun, _VERB_TO_ACTION.get(verb, "updated")
    return _UNKNOWN_TYPE, "updated"


def _first_str(data: Dict[str, Any], keys: tuple) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_number(data: Dict[str, Any], keys: tuple) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        # Numeric strings ("20000.0") are acceptable.
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def build_affected_entity(tool_name: str, data: Any) -> Optional[Dict[str, Any]]:
    """Build ONE canonical affected entity from a tool result.

    Returns None only when the result carries no identifiable entity at all
    (e.g. a list of search hits or an empty dict).
    """
    if not isinstance(data, dict):
        return None

    # Journal tools nest the entry under "entry".
    entry = data.get("entry")
    if isinstance(entry, dict):
        probe = {**entry, **{k: v for k, v in data.items() if k != "entry"}}
    else:
        probe = data

    entity_type, action = _derive_type_action(tool_name or "")

    entity_id = _first_str(probe, _ID_KEYS)
    if not entity_id:
        return None

    entity: Dict[str, Any] = {"type": entity_type or _UNKNOWN_TYPE}
    if action:
        entity["action"] = action
    entity["id"] = entity_id

    name = _first_str(probe, _NAME_KEYS)
    number = _first_str(probe, _NUMBER_KEYS)
    total = _first_number(probe, _TOTAL_KEYS)
    if name:
        entity["name"] = name[:200]
    if number:
        entity["number"] = number
    if total is not None:
        entity["total"] = total
    return entity


def build_affected_entities(
    tool_results: List[Any], max_entities: int = 20
) -> List[Dict[str, Any]]:
    """Canonical affected-entities list from tool results (contract-safe)."""
    entities: List[Dict[str, Any]] = []
    for tr in tool_results or []:
        if not getattr(tr, "success", False):
            continue
        entity = build_affected_entity(
            getattr(tr, "tool_name", ""), getattr(tr, "data", None)
        )
        if entity:
            entities.append(entity)
        if len(entities) >= max_entities:
            break
    return entities


async def build_accounting_impact(
    tool_results: List[Any],
    resolve_account_name: Callable[[Any], Awaitable[Optional[str]]],
    max_lines: int = 20,
) -> List[Dict[str, Any]]:
    """Canonical accounting-impact lines from journal-bearing tool results.

    ``resolve_account_name(account_id)`` resolves the GL account label;
    failures fall back to a neutral placeholder — the contract requires a
    non-empty ``account`` string.
    """
    lines: List[Dict[str, Any]] = []
    seen: set = set()
    for tr in tool_results or []:
        if not getattr(tr, "success", False):
            continue
        data = getattr(tr, "data", None)
        if not isinstance(data, dict):
            continue
        journal_lines = data.get("lines")
        if not isinstance(journal_lines, list):
            continue
        for line in journal_lines:
            if not isinstance(line, dict):
                continue
            debit = line.get("debit")
            credit = line.get("credit")
            debit_f = float(debit) if isinstance(debit, (int, float)) and debit else None
            credit_f = float(credit) if isinstance(credit, (int, float)) and credit else None
            if debit_f is None and credit_f is None:
                continue
            account_id = line.get("account_id")
            label = None
            if account_id:
                try:
                    label = await resolve_account_name(account_id)
                except Exception:  # noqa: BLE001 — label fallback below
                    label = None
            label = (label or "").strip()
            if not label:
                label = f"Account {str(account_id)[:8]}" if account_id else "Account (unresolved)"
            key = (label, debit_f, credit_f)
            if key in seen:
                continue
            seen.add(key)
            entry_line: Dict[str, Any] = {"account": label}
            if debit_f is not None:
                entry_line["debit"] = debit_f
            if credit_f is not None:
                entry_line["credit"] = credit_f
            description = line.get("description")
            if isinstance(description, str) and description.strip():
                entry_line["description"] = description.strip()[:200]
            lines.append(entry_line)
            if len(lines) >= max_lines:
                return lines
    return lines

