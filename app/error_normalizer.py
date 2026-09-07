"""
ERP AI Agent — Semantic Error Normalizer
=========================================
Generically normalises low-level failures into semantic categories so the
agent can decide between:

  * a TARGETED CLARIFICATION (recoverable, user can supply the value),
  * a model retry with a precise instruction (e.g. reuse an existing
    record instead of duplicating), or
  * a genuine system failure (never disguised as a user-input problem).

NO per-tool special cases: classification is driven purely by the shape
of the underlying error (PostgreSQL error codes, PostgREST error bodies,
Pydantic violations, transport failures).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

# --- PostgreSQL error codes -------------------------------------------------
PG_NOT_NULL_VIOLATION = "23502"
PG_UNIQUE_VIOLATION = "23505"
PG_FOREIGN_KEY_VIOLATION = "23503"
PG_CHECK_VIOLATION = "23514"

# Categories
MISSING_REQUIRED_VALUE = "MISSING_REQUIRED_VALUE"
DUPLICATE_RECORD = "DUPLICATE_RECORD"
INVALID_REFERENCE = "INVALID_REFERENCE"
CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
VALIDATION_ERROR = "VALIDATION_ERROR"
INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

_PLURAL_MAP = {
    "suppliers": "supplier",
    "customers": "customer",
    "invoices": "invoice",
    "invoice_items": "invoice item",
    "purchase_bills": "purchase bill",
    "purchase_bill_items": "purchase bill item",
    "expenses": "expense",
    "payments": "payment",
    "receipts": "receipt",
    "journal_entries": "journal entry",
    "projects": "project",
    "accounts": "account",
    "products": "product",
    "bank_accounts": "bank account",
}


def _singularize(table: Optional[str]) -> Optional[str]:
    if not table:
        return None
    if table in _PLURAL_MAP:
        return _PLURAL_MAP[table]
    return table[:-1] if table.endswith("s") else table


def _extract_postgres_details(raw: str) -> Optional[Dict[str, Any]]:
    """Extract code/message/details from a Postgres error embedded in text.

    Supabase/PostgREST surfaces these either as JSON
    ({'message': ..., 'code': ..., 'details': ...}) or as Python dict
    repr / plain Postgres text.
    """
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            err = parsed.get("error") or parsed
            code = err.get("code")
            message = err.get("message")
            if code or message:
                return {
                    "code": code,
                    "message": message,
                    "details": err.get("details") or "",
                    "hint": err.get("hint") or "",
                }
    except (ValueError, TypeError):
        pass

    code_m = re.search(r"'code':\s*'?(\d{5})'?", raw)
    if code_m:
        msg_m = re.search(r"'message':\s*'([^']*)'", raw)
        details_m = re.search(r"'details':\s*'([^']*)'", raw)
        return {
            "code": code_m.group(1),
            "message": msg_m.group(1) if msg_m else raw,
            "details": details_m.group(1) if details_m else "",
            "hint": "",
        }

    nn = re.search(r'null value in column "([^"]+)" of relation "([^"]+)"', raw)
    if nn:
        return {
            "code": PG_NOT_NULL_VIOLATION,
            "message": raw,
            "details": "",
            "hint": "",
            "_column": nn.group(1),
            "_table": nn.group(2),
        }
    dup = re.search(r'duplicate key value violates unique constraint "([^"]+)"', raw)
    if dup:
        return {
            "code": PG_UNIQUE_VIOLATION,
            "message": raw,
            "details": dup.group(1),
            "hint": "",
        }
    if "violates foreign key constraint" in raw:
        return {"code": PG_FOREIGN_KEY_VIOLATION, "message": raw, "details": "", "hint": ""}
    return None


def _field_from_not_null(raw: str, pg: Optional[Dict[str, Any]]) -> Optional[str]:
    if not pg:
        return None
    if pg.get("_column"):
        return pg["_column"]
    m = re.search(r'null value in column "([^"]+)"', pg.get("message") or raw)
    return m.group(1) if m else None


def _table_from_not_null(raw: str, pg: Optional[Dict[str, Any]]) -> Optional[str]:
    if not pg:
        return None
    if pg.get("_table"):
        return pg["_table"]
    m = re.search(r'of relation "([^"]+)"', pg.get("message") or raw)
    return m.group(1) if m else None


_INFRASTRUCTURE_PATTERNS = (
    "connection refused",
    "connection timed out",
    "connect timeout",
    "connection reset",
    "name or service not known",
    "getaddrinfo",
    "service unavailable",
    "httpx.connecterror",
    "database is unavailable",
    "too many connections",
)


def normalize_error(
    raw: Any,
    *,
    operation: Optional[str] = None,
    entity_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalise *raw* (exception text/object) into a semantic error dict.

    Returns at least: {"category", "recoverable", "requires_user_input",
    "reason", "message", "operation", "entity", "field", "user_action"}.
    Genuine infrastructure failures are NEVER marked as user-input problems.
    """
    raw_str = str(raw) if raw else ""
    entity = entity_hint
    field: Optional[str] = None
    category: str = UNKNOWN_ERROR
    recoverable = False
    requires_user_input = False
    reason = raw_str[:300]
    user_action = "Report the failure to the user."

    pg = _extract_postgres_details(raw_str)
    code = (pg or {}).get("code")

    if code == PG_NOT_NULL_VIOLATION:
        category = MISSING_REQUIRED_VALUE
        recoverable = True
        requires_user_input = True
        field = _field_from_not_null(raw_str, pg)
        table = _table_from_not_null(raw_str, pg)
        entity = _singularize(table) or entity
        reason = f"Required {entity or 'record'} field '{field}' is missing"
        user_action = "Ask the user for the missing value, then resume the same operation."
    elif code == PG_UNIQUE_VIOLATION:
        category = DUPLICATE_RECORD
        recoverable = True
        requires_user_input = False
        reason = "A record with the same unique value already exists"
        user_action = (
            "Search for the existing record and reuse its authoritative id "
            "instead of creating a duplicate."
        )
    elif code == PG_FOREIGN_KEY_VIOLATION:
        category = INVALID_REFERENCE
        recoverable = True
        requires_user_input = True
        reason = "The operation references a record that does not exist"
        user_action = "Find or create the referenced record first, then retry with its id."
    elif code == PG_CHECK_VIOLATION:
        category = CONSTRAINT_VIOLATION
        recoverable = True
        requires_user_input = True
        reason = "The provided values violate a database check constraint"
        user_action = "Ask the user for a valid value for the offending field."
    elif pg and code:
        category = VALIDATION_ERROR
        recoverable = True
        requires_user_input = True
        reason = (pg.get("message") or raw_str)[:300]
        user_action = "Correct the invalid values (possibly by asking the user) and retry."
    elif _looks_like_infrastructure(raw_str):
        category = INFRASTRUCTURE_ERROR
        recoverable = False
        requires_user_input = False
        reason = "The database or an external service is currently unavailable"
        user_action = "Report a system failure. Do NOT ask the user for field values."
    elif "validation" in raw_str.lower() or "valueerror" in raw_str.lower():
        category = VALIDATION_ERROR
        recoverable = True
        requires_user_input = True
        reason = raw_str[:300]
        user_action = "Correct the invalid values (possibly by asking the user) and retry."

    return {
        "category": category,
        "recoverable": recoverable,
        "requires_user_input": requires_user_input,
        "entity": entity,
        "operation": operation,
        "field": field,
        "reason": reason,
        "user_action": user_action,
        "message": raw_str[:500],
    }


def _looks_like_infrastructure(raw: str) -> bool:
    lower = raw.lower()
    return any(p in lower for p in _INFRASTRUCTURE_PATTERNS)


def build_missing_field_question(
    entity: Optional[str],
    field: Optional[str],
    record_name: Optional[str] = None,
) -> str:
    """Build a targeted clarification question for a missing mandatory field."""
    field_label = (field or "required value").replace("_", " ")
    what = f" for {record_name}" if record_name else ""
    return f"What value should be used for '{field_label}'{what}?"


def build_duplicate_guidance(entity: Optional[str]) -> str:
    entity_name = entity or "record"
    return (
        f"A {entity_name} with this unique value already exists. Do NOT create "
        f"a duplicate: use the search tool to find the existing {entity_name} "
        "and reuse its authoritative id in the remaining operations."
    )

