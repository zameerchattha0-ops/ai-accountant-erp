"""
Project Repository — Supabase data access for project records.
"""

from __future__ import annotations

import uuid
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
    description: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    budget: Optional[float] = None,
    currency_code: str = "PKR",
    billing_type: Optional[str] = None,
) -> Dict[str, Any]:
    return await insert_one(
        "projects",
        data={
            "organization_id": str(organization_id),
            "name": name,
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
