"""
Project Service — business logic for project operations.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import project_repository as repo

log = structlog.get_logger(__name__)


async def search(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await repo.search_projects(organization_id, query=query, limit=limit)


async def get(
    organization_id: uuid.UUID, *, project_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_project(organization_id, project_id=project_id)


async def create(
    organization_id: uuid.UUID,
    *,
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
    """Create a project.

    ``project_code`` is OPTIONAL from the caller's point of view: the
    repository derives ``<STEM>-###`` when the user did not state a code
    (``projects.project_code`` is NOT NULL, and no natural-language request
    names one).
    """
    return await repo.create_project(
        organization_id=organization_id,
        name=name,
        project_code=project_code,
        description=description,
        customer_id=customer_id,
        start_date=start_date,
        end_date=end_date,
        budget=budget,
        currency_code=currency_code,
        billing_type=billing_type,
    )


async def get_profitability(
    organization_id: uuid.UUID,
    *,
    project_id: uuid.UUID,
) -> List[Dict[str, Any]]:
    return await repo.get_project_profitability(
        organization_id, project_id=project_id
    )
