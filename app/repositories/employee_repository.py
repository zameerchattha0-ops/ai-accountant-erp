"""
Employee Repository — Supabase data access for employee records.

Mirrors ``customer_repository``: org-scoped reads, trigger-assigned
``employee_code`` (never generated here), one bounded query per call.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.database import (
    fetch_many,
    fetch_one,
    insert_many,
    insert_one,
    search_ilike,
    update_one,
)

_SELECT = (
    "id,employee_code,full_name,date_of_joining,basic_salary,status,"
    "designation,department,employment_type,phone,email,is_active"
)
_ALLOWANCE_SELECT = (
    "id,employee_id,component_kind,allowance_type,description,amount,"
    "frequency,effective_from,effective_to,source,raw_text,created_at"
)


async def search_employees(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    """Search employees by name/code; typo-tolerant fallback on a miss.

    Same two-stage shape as the customer incident fix (2026-09-24): strict
    ILIKE first (fast, indexed); only on a miss, re-read a bounded set and
    rank with separator-insensitive ``name_key`` matching.
    """
    text = str(query or "").strip()
    rows = await search_ilike(
        "employees",
        column="full_name",
        value=text,
        organization_id=organization_id,
        select=_SELECT,
        limit=limit,
    )
    # An exact employee CODE is a legitimate query ("EMP-000007").
    if not rows and text:
        by_code = await get_employee_by_code(organization_id, code=text)
        if by_code:
            rows = [by_code]
    if rows or not text:
        return rows
    from app.name_matching import normalized_matches

    candidates = await fetch_many(
        "employees",
        filters={"organization_id": str(organization_id)},
        select=_SELECT,
        order="full_name.asc",
        limit=500,
    )
    return normalized_matches(candidates, text, limit=limit, field="full_name")


async def list_employees(
    organization_id: uuid.UUID, *, limit: int = 500
) -> List[Dict[str, Any]]:
    """Every employee row in the organisation (payroll reads the full roster).

    One bounded query — the per-employee eligibility decision (status,
    joining date) is made by the payroll service, never here.
    """
    return await fetch_many(
        "employees",
        filters={"organization_id": str(organization_id)},
        select=_SELECT,
        order="full_name.asc",
        limit=limit,
    )


async def get_employee(
    organization_id: uuid.UUID, *, employee_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    """Fetch a single employee by ID within organisation scope."""
    return await fetch_one(
        "employees",
        filters={
            "id": str(employee_id),
            "organization_id": str(organization_id),
        },
    )


async def get_employee_by_code(
    organization_id: uuid.UUID, *, code: str
) -> Optional[Dict[str, Any]]:
    """Exact code lookup (case-insensitive on the caller's side)."""
    return await fetch_one(
        "employees",
        filters={
            "employee_code": str(code or "").strip().upper(),
            "organization_id": str(organization_id),
        },
    )


async def create_employee(
    *,
    organization_id: uuid.UUID,
    full_name: str,
    date_of_joining: str,
    basic_salary: float,
    **optional: Any,
) -> Dict[str, Any]:
    """Insert an employee. ``employee_code`` is assigned by the DB trigger."""
    data: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "full_name": full_name,
        "date_of_joining": date_of_joining,
        "basic_salary": basic_salary,
        "is_active": True,
    }
    data.update({k: v for k, v in optional.items() if v is not None})
    return await insert_one("employees", data=data)


async def update_employee(
    organization_id: uuid.UUID,
    *,
    employee_id: uuid.UUID,
    data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Update an employee (org-scoped; the second guard blocks foreign ids)."""
    return await update_one(
        "employees",
        row_id=employee_id,
        data=data,
        organization_id=organization_id,
    )


async def list_allowances(
    organization_id: uuid.UUID,
    *,
    employee_id: uuid.UUID,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Every allowance/component row for one employee (newest first)."""
    return await fetch_many(
        "employee_allowances",
        filters={
            "employee_id": str(employee_id),
            "organization_id": str(organization_id),
        },
        select=_ALLOWANCE_SELECT,
        order="effective_from.desc",
        limit=limit,
    )


async def list_allowances_for_organization(
    organization_id: uuid.UUID, *, limit: int = 2000
) -> List[Dict[str, Any]]:
    """Every allowance/component row of the organisation in ONE query.

    A payroll run needs the components of the whole roster; calling
    ``list_allowances`` per employee would be N round-trips.
    """
    return await fetch_many(
        "employee_allowances",
        filters={"organization_id": str(organization_id)},
        select=_ALLOWANCE_SELECT,
        order="effective_from.desc",
        limit=limit,
    )


async def insert_allowances(
    organization_id: uuid.UUID,
    *,
    employee_id: uuid.UUID,
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert one row per allowance component (single bulk insert)."""
    if not rows:
        return []
    return await insert_many(
        "employee_allowances",
        data=[
            {
                "organization_id": str(organization_id),
                "employee_id": str(employee_id),
                **row,
            }
            for row in rows
        ],
    )
