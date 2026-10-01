"""
Project Repository — Supabase data access for project records.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import fetch_many, fetch_one, insert_one, search_ilike


async def search_projects(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await search_ilike(
        "projects",
        column="name",
        value=query,
        organization_id=organization_id,
        select="id,name,project_code,status,customer_id,is_active",
        limit=limit,
    )


async def get_project(
    organization_id: uuid.UUID, *, project_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        "projects",
        filters={
            "id": str(project_id),
            "organization_id": str(organization_id),
        },
    )


async def list_projects(
    organization_id: uuid.UUID,
    *,
    is_active: bool = True,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await fetch_many(
        "projects",
        filters={"organization_id": str(organization_id), "is_active": is_active},
        order="name.asc",
        limit=limit,
    )


async def create_project(
    *,
    organization_id: uuid.UUID,
    name: str,
    project_code: Optional[str] = None,
    description: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    budget: Optional[float] = None,
    currency_code: str = "PKR",
    billing_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a project.  ``projects.project_code`` is NOT NULL, so when the
    user did not state one it is DERIVED here (same pattern as
    ``account_repository.next_available_code``) instead of letting the NOT
    NULL violation surface as "Required project field 'project_code' is
    missing. This value must be supplied by the user" — a field no user of a
    natural-language request ever mentions (production 2026-10-01, project
    session 03221efb)."""
    code = (project_code or "").strip().upper() or await _derive_project_code(
        organization_id, name
    )
    return await insert_one(
        "projects",
        data={
            "organization_id": str(organization_id),
            "name": name,
            "project_code": code,
            "description": description,
            "customer_id": str(customer_id) if customer_id else None,
            "start_date": start_date,
            "end_date": end_date,
            "budget": budget,
            "currency_code": currency_code,
            "billing_type": billing_type,
            "is_active": True,
        },
    )


def _code_stem(name: str) -> str:
    """A short, readable code stem from the project name ("Mobile App" → MOB)."""
    letters = re.findall(r"[A-Za-z0-9]+", str(name or ""))
    if not letters:
        return "PRJ"
    first = letters[0][:3].upper()
    return first or "PRJ"


async def _derive_project_code(organization_id: uuid.UUID, name: str) -> str:
    """``<STEM>-###`` with the next free number for this organisation."""
    stem = _code_stem(name)
    existing = await fetch_many(
        "projects",
        filters={"organization_id": str(organization_id)},
        select="project_code",
        limit=1000,
    )
    used = {
        str(row.get("project_code") or "").upper()
        for row in existing
        if row.get("project_code")
    }
    for n in range(1, 1000):
        candidate = f"{stem}-{n:03d}"
        if candidate.upper() not in used:
            return candidate
    # Pathological exhaustion: a timestamp suffix is still deterministic and
    # collision-free enough for a human-facing code.
    return f"{stem}-{int(datetime.now(timezone.utc).timestamp())}"


async def get_project_profitability(
    organization_id: uuid.UUID,
    *,
    project_id: uuid.UUID,
) -> List[Dict[str, Any]]:
    """Query the v_project_profitability view for a project."""
    return await fetch_many(
        "v_project_profitability",
        filters={
            "project_id": str(project_id),
            "organization_id": str(organization_id),
        },
    )
