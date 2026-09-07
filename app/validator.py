"""
ERP AI Agent — Validator
==========================
Final business and accounting safety gate before any mutation.

Reads ``ai.validation_rules`` from the database and applies them in
addition to hard-coded structural checks.  Database-level constraints
(triggers, CHECK, NOT NULL) remain the last line of defence.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import structlog

from app.database import fetch_many
from app.models.schemas import ValidationResult
from app.repositories import (
    account_repository,
    customer_repository,
    organization_repository,
    supplier_repository,
)

log = structlog.get_logger(__name__)


async def validate_operation(
    *,
    organization_id: uuid.UUID,
    operation: str,
    data: Dict[str, Any],
) -> ValidationResult:
    """Run all applicable validation rules before a mutation.

    *operation* is the tool slug or action name (e.g. ``create_invoice``).
    Returns a ``ValidationResult`` with errors and warnings.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # --- Structural checks (always run) -----------------------------------
    errors.extend(_check_amounts(data))
    errors.extend(_check_dates(data))

    # --- Database-stored validation rules ---------------------------------
    rules = await _load_rules(operation)
    for rule in rules:
        rule_errors = await _apply_rule(
            rule, organization_id=organization_id, data=data
        )
        errors.extend(rule_errors)

    # --- Entity existence checks ------------------------------------------
    if "customer_id" in data and data["customer_id"]:
        c = await customer_repository.get_customer(
            organization_id, customer_id=uuid.UUID(str(data["customer_id"]))
        )
        if not c:
            errors.append("Customer not found.")

    if "supplier_id" in data and data["supplier_id"]:
        s = await supplier_repository.get_supplier(
            organization_id, supplier_id=uuid.UUID(str(data["supplier_id"]))
        )
        if not s:
            errors.append("Supplier not found.")

    if "account_id" in data and data["account_id"]:
        a = await account_repository.get_account(
            organization_id, account_id=uuid.UUID(str(data["account_id"]))
        )
        if not a:
            errors.append("Account not found.")

    # --- Accounting period check ------------------------------------------
    txn_date = data.get("transaction_date") or data.get("invoice_date") or data.get("bill_date") or data.get("expense_date")
    if txn_date:
        period_ok = await _check_period_open(organization_id, txn_date)
        if period_ok is False:
            errors.append("The accounting period for this date is closed or locked.")

    result = ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
    log.info(
        "validator.result",
        operation=operation,
        valid=result.valid,
        error_count=len(errors),
    )
    return result


# ---- Private helpers ------------------------------------------------------

def _check_amounts(data: Dict[str, Any]) -> List[str]:
    """Ensure monetary amounts are positive where required."""
    errors: List[str] = []
    for field in ("amount", "total", "subtotal", "unit_price"):
        val = data.get(field)
        if val is not None:
            try:
                if float(val) < 0:
                    errors.append(f"{field} must not be negative.")
            except (TypeError, ValueError):
                errors.append(f"{field} is not a valid number.")
    return errors


def _check_dates(data: Dict[str, Any]) -> List[str]:
    """Ensure dates are valid and logically ordered."""
    errors: List[str] = []
    for field in ("transaction_date", "invoice_date", "bill_date", "expense_date", "due_date"):
        val = data.get(field)
        if val is not None:
            try:
                date.fromisoformat(str(val))
            except (ValueError, TypeError):
                errors.append(f"{field} is not a valid ISO date.")
    return errors


async def _load_rules(operation: str) -> List[Dict[str, Any]]:
    """Load active validation rules that apply to *operation*."""
    rules = await fetch_many(
        "ai_validation_rules",
        filters={"applies_to": operation, "status": "ACTIVE"},
        order="priority.desc",
    )
    return rules or []


async def _apply_rule(
    rule: Dict[str, Any],
    *,
    organization_id: uuid.UUID,
    data: Dict[str, Any],
) -> List[str]:
    """Apply a single validation rule and return any error messages."""
    rule_type = rule.get("rule_type", "")
    condition = rule.get("condition") or {}
    error_msg = rule.get("error_message", "Validation failed.")

    if rule_type == "ENTITY_EXISTS":
        field = condition.get("field", "")
        entity = condition.get("entity", "")
        val = data.get(field)
        if not val:
            return []  # Not required here
        if entity == "customer":
            c = await customer_repository.get_customer(
                organization_id, customer_id=uuid.UUID(str(val))
            )
            if not c:
                return [error_msg]
        elif entity == "supplier":
            s = await supplier_repository.get_supplier(
                organization_id, supplier_id=uuid.UUID(str(val))
            )
            if not s:
                return [error_msg]

    elif rule_type == "AMOUNT_POSITIVE":
        fields = condition.get("fields", [])
        for f in fields:
            val = data.get(f)
            if val is not None and float(val) <= 0:
                return [error_msg]

    elif rule_type == "BALANCED":
        debit = float(data.get("total_debit", 0))
        credit = float(data.get("total_credit", 0))
        if abs(debit - credit) > 0.01:
            return [error_msg]

    elif rule_type == "PERIOD_OPEN":
        date_field = condition.get("date_field", "transaction_date")
        txn_date = data.get(date_field)
        if txn_date:
            is_open = await _check_period_open(organization_id, str(txn_date))
            if is_open is False:
                return [error_msg]

    return []


async def _check_period_open(
    organization_id: uuid.UUID, transaction_date: str
) -> Optional[bool]:
    """Check whether the accounting period for *transaction_date* is OPEN.

    Returns True (open), False (closed/locked), or None (no period found).
    """
    from app.database import call_rpc

    try:
        result = await call_rpc(
            "get_period_for_date",
            params={"p_date": transaction_date, "p_org_id": str(organization_id)},
        )
        if result and isinstance(result, list) and len(result) > 0:
            period = result[0]
            status = period.get("status", "")
            return status == "OPEN"
    except Exception:
        pass
    return None  # Cannot determine — let database trigger enforce
