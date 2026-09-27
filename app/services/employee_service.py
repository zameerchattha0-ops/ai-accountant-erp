"""Employee Service — business logic for the Employees module.

Design contract (LLM-first, deliberately template-free):

* ``create`` needs ONLY ``full_name`` + ``date_of_joining`` + ``basic_salary``;
  every other detail is optional and can be filled later.
* ``set_allowances`` NEVER parses natural language.  The user's sentence is
  structured by the LLM upstream (the agent pipeline) into
  ``allowances=[{description, amount, frequency, allowance_type,
  effective_from}]``; this service VALIDATES each entry and writes one row
  per component.  Python validates and executes — it does not interpret.
* Every rejection message is written for the MODEL to act on: it names what
  is missing or wrong so the agent asks the user (single-call
  questionnaire), instead of a silent default.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import employee_repository as repo

log = structlog.get_logger(__name__)

_FREQUENCY_SYNONYMS = {
    "MONTHLY": "MONTHLY", "MONTH": "MONTHLY", "PER MONTH": "MONTHLY",
    "MONTHLY BASIS": "MONTHLY", "EVERY MONTH": "MONTHLY",
    "ONE_TIME": "ONE_TIME", "ONE-TIME": "ONE_TIME", "ONE TIME": "ONE_TIME",
    "ONE OFF": "ONE_TIME", "ONE-OFF": "ONE_TIME", "ONEOFF": "ONE_TIME",
    "SINGLE": "ONE_TIME", "ONCE": "ONE_TIME",
    "ANNUAL": "ANNUAL", "YEARLY": "ANNUAL", "PER YEAR": "ANNUAL",
    "PER ANNUM": "ANNUAL", "EVERY YEAR": "ANNUAL",
}
_COMPONENT_KINDS = {"ALLOWANCE", "DEDUCTION", "BONUS"}
_MIN_NAME = 2
#: everything the model may pass beyond the three mandatory fields — an
#: invented key is dropped, never carried into the insert.
_OPTIONAL_FIELDS = (
    "designation", "department", "employment_type", "cnic", "date_of_birth",
    "gender", "phone", "email", "address", "bank_name",
    "bank_account_number", "tax_number", "pay_day", "probation_end_date",
    "notes",
)


class EmployeeInputError(ValueError):
    """A correctable input problem — the message is written for the model."""


def _clean_date(value: Any, *, label: str) -> str:
    """Mechanical date resolution (server-side truth); never guessed."""
    from app.date_parser import parse_transaction_date

    text = str(value or "").strip()
    if not text:
        raise EmployeeInputError(
            f"{label} is required — ask the user for it (YYYY-MM-DD or DD/MM/YYYY)."
        )
    parsed = parse_transaction_date(text)
    if not parsed.ok:
        raise EmployeeInputError(
            f"{label} '{text}' is not a parseable date — {parsed.error} "
            "Ask the user again."
        )
    return str(parsed.iso_date)


def _clean_amount(value: Any, *, label: str) -> float:
    """Numeric validation for the LLM's composed amounts ("1,25,000" ok)."""
    if value is None or value == "":
        raise EmployeeInputError(f"{label} is missing — ask the user for the amount.")
    if isinstance(value, str):
        stripped = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
        try:
            value = float(stripped)
        except (TypeError, ValueError):
            raise EmployeeInputError(
                f"{label} '{value}' is not a number — ask the user for the amount."
            ) from None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise EmployeeInputError(f"{label} is not a number — ask the user for the amount.")
    if number <= 0:
        raise EmployeeInputError(f"{label} must be greater than zero.")
    return round(number, 2)


def _clean_frequency(value: Any) -> str:
    """Map the model's frequency wording onto the stored enum (or reject)."""
    if value is None or not str(value).strip():
        return "MONTHLY"
    token = re.sub(r"[_\-]+", " ", str(value).strip().upper())
    token = re.sub(r"\s+", " ", token)
    normalized = _FREQUENCY_SYNONYMS.get(token)
    if not normalized:
        raise EmployeeInputError(
            f"'{value}' is not a supported frequency — supported: MONTHLY, "
            "ONE_TIME, ANNUAL. Ask the user which one applies."
        )
    return normalized


def _clean_component_kind(value: Any) -> str:
    if value is None or not str(value).strip():
        return "ALLOWANCE"
    token = re.sub(r"[_\-]+", " ", str(value).strip().upper())
    token = _FREQUENCY_SYNONYMS.get(token, token).replace(" ", "_")
    if token not in _COMPONENT_KINDS:
        raise EmployeeInputError(
            f"'{value}' is not a supported component — supported: ALLOWANCE, "
            "DEDUCTION, BONUS."
        )
    return token


async def search(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await repo.search_employees(
        organization_id, query=query, limit=max(1, min(int(limit or 25), 50))
    )


async def _resolve_employee(
    organization_id: uuid.UUID, reference: Any
) -> Dict[str, Any]:
    """Resolve an employee from a code (EMP-â€¦), a uuid, or a name.

    Ambiguity is a QUESTION, never a guess: several name matches raise an
    error that names the codes, so the agent asks the user which employee.
    """
    text = str(reference or "").strip()
    if not text:
        raise EmployeeInputError(
            "Which employee is this for? Provide the employee code (EMP-â€¦), "
            "the full name, or the id."
        )
    try:
        return_row = await repo.get_employee(organization_id, employee_id=uuid.UUID(text))
        if return_row:
            return return_row
    except (ValueError, AttributeError):
        pass
    code_row = await repo.get_employee_by_code(organization_id, code=text)
    if code_row:
        return code_row
    matches = await search(organization_id, query=text, limit=10)
    exact = [
        row for row in matches
        if str(row.get("full_name") or "").strip().lower() == text.lower()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        codes = ", ".join(str(r.get("employee_code") or r.get("id")) for r in exact)
        raise EmployeeInputError(
            f"More than one employee matches '{text}' ({codes}) — ask the user "
            "which one, then pass its employee code."
        )
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = ", ".join(
            f"{r.get('full_name')} ({r.get('employee_code')})" for r in matches[:6]
        )
        raise EmployeeInputError(
            f"'{text}' matches several employees: {options} — ask the user "
            "which one, then pass its employee code."
        )
    raise EmployeeInputError(
        f"No employee matches '{text}' — ask the user for the exact name or "
        "the employee code, or create the employee first."
    )


async def create(
    organization_id: uuid.UUID,
    *,
    full_name: str,
    date_of_joining: Any,
    basic_salary: Any,
    **optional: Any,
) -> Dict[str, Any]:
    """Create an employee from the THREE mandatory fields (+ optional detail).

    Search-before-create: an exact name match whose phone/cnic agrees (or
    when neither side has one) reuses the existing record instead of
    duplicating a person.
    """
    name = str(full_name or "").strip()
    if len(name) < _MIN_NAME:
        raise EmployeeInputError(
            "full_name is required (at least 2 characters) — ask the user for "
            "the employee's name."
        )
    joined = _clean_date(date_of_joining, label="date_of_joining")
    salary = _clean_amount(basic_salary, label="basic_salary")

    clean_optional: Dict[str, Any] = {}
    for key, value in (optional or {}).items():
        if key not in _OPTIONAL_FIELDS or value in (None, ""):
            continue
        if key in ("date_of_birth", "probation_end_date"):
            clean_optional[key] = _clean_date(value, label=key)
        elif key == "pay_day":
            try:
                day = int(value)
            except (TypeError, ValueError):
                raise EmployeeInputError(
                    "pay_day must be a day of month (1-31) — ask the user."
                ) from None
            if not 1 <= day <= 31:
                raise EmployeeInputError("pay_day must be between 1 and 31.")
            clean_optional[key] = day
        elif key == "employment_type":
            token = re.sub(r"[^A-Z]+", "_", str(value).strip().upper()).strip("_")
            if token:
                clean_optional[key] = token
        else:
            clean_optional[key] = value

    phone = clean_optional.get("phone")
    cnic = clean_optional.get("cnic")
    existing = await search(organization_id, query=name, limit=10)
    for row in existing:
        same_name = str(row.get("full_name") or "").strip().lower() == name.lower()
        if not same_name:
            continue
        same_phone = phone and str(row.get("phone") or "").strip() == str(phone).strip()
        same_cnic = cnic and str(row.get("cnic") or "").strip() == str(cnic).strip()
        if same_phone or same_cnic or (not phone and not cnic):
            log.info(
                "employee_service.reused_existing",
                code=row.get("employee_code"),
            )
            return {
                **row,
                "reused_existing": True,
                "note": (
                    f"An employee named '{name}' already exists "
                    f"({row.get('employee_code')}) — reused; no duplicate "
                    "record was created."
                ),
            }

    data = await repo.create_employee(
        organization_id=organization_id,
        full_name=name,
        date_of_joining=joined,
        basic_salary=salary,
        **clean_optional,
    )
    log.info("employee_service.created", code=data.get("employee_code"))
    return data


async def get(
    organization_id: uuid.UUID,
    *,
    employee: Any = None,
    employee_id: Any = None,
) -> Dict[str, Any]:
    """One employee plus their allowance records."""
    row = await _resolve_employee(organization_id, employee_id or employee)
    allowances = await repo.list_allowances(
        organization_id, employee_id=uuid.UUID(str(row["id"]))
    )
    return {**row, "allowances": allowances}


async def set_allowances(
    organization_id: uuid.UUID,
    *,
    employee: Any,
    allowances: Any,
    raw_text: Optional[str] = None,
    effective_from: Any = None,
    ai_execution_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Validate the LLM-structured components and write one row per part.

    The LLM composes ``allowances`` from the user's natural-language
    sentence; THIS function never interprets that sentence.  It validates
    every entry (description, numeric amount, frequency enum, effective
    date) and writes the rows — ``raw_text`` is stored alongside purely for
    audit, and marks the rows ``source='AI'``.
    """
    if not isinstance(allowances, list) or not allowances:
        raise EmployeeInputError(
            "allowances must be a non-empty list of components, each with a "
            "description and a numeric amount — structure the user's sentence "
            "first, then call again."
        )
    target = await _resolve_employee(organization_id, employee)
    employee_uuid = uuid.UUID(str(target["id"]))
    default_from = (
        _clean_date(effective_from, label="effective_from")
        if effective_from
        else None
    )

    rows: List[Dict[str, Any]] = []
    monthly_total = 0.0
    one_time_total = 0.0
    for index, entry in enumerate(allowances[:24], start=1):
        if not isinstance(entry, dict):
            raise EmployeeInputError(
                f"allowances[{index}] must be an object with a description "
                "and an amount."
            )
        description = str(
            entry.get("description")
            or entry.get("name")
            or entry.get("label")
            or ""
        ).strip()
        if not description:
            raise EmployeeInputError(
                f"allowances[{index}] needs a description (for example "
                '"House rent") — ask the user what the payment is for.'
            )
        amount = _clean_amount(
            entry.get("amount"), label=f"allowances[{index}].amount"
        )
        frequency = _clean_frequency(entry.get("frequency"))
        kind = _clean_component_kind(entry.get("component_kind"))
        per_entry_from = entry.get("effective_from")
        row: Dict[str, Any] = {
            "component_kind": kind,
            "allowance_type": (
                re.sub(
                    r"[^A-Z0-9]+",
                    "_",
                    str(entry.get("allowance_type") or description).strip().upper(),
                ).strip("_")[:40]
                or None
            ),
            "description": description[:160],
            "amount": amount,
            "frequency": frequency,
            "source": "AI" if raw_text else "MANUAL",
            "raw_text": (str(raw_text)[:2000] if raw_text else None),
        }
        if per_entry_from:
            row["effective_from"] = _clean_date(
                per_entry_from, label=f"allowances[{index}].effective_from"
            )
        elif default_from:
            row["effective_from"] = default_from
        if ai_execution_id:
            row["ai_execution_id"] = str(ai_execution_id)
        rows.append(row)
        if kind == "DEDUCTION":
            continue
        if frequency == "MONTHLY":
            monthly_total += amount
        elif frequency == "ONE_TIME":
            one_time_total += amount

    created = await repo.insert_allowances(
        organization_id, employee_id=employee_uuid, rows=rows
    )
    log.info(
        "employee_service.allowances_set",
        employee=str(employee_uuid),
        count=len(created),
    )
    return {
        "employee": {
            "id": str(target.get("id")),
            "employee_code": target.get("employee_code"),
            "full_name": target.get("full_name"),
        },
        "created": created,
        "monthly_total": round(monthly_total, 2),
        "one_time_total": round(one_time_total, 2),
        "raw_text": raw_text,
    }
