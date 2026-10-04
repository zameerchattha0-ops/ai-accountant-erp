"""
Project Service — business logic for project operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import project_repository as repo

log = structlog.get_logger(__name__)


async def list_projects(
    organization_id: uuid.UUID, *, limit: int = 2000
) -> List[Dict[str, Any]]:
    """The whole register for the Projects page (active rows, name order).

    Paged in the repository: a single PostgREST response caps at ~1000 rows, so
    an unpaged read made the register — and everything derived from it — quietly
    incomplete.
    """
    return await repo.list_all_projects(organization_id, limit=limit)


#: ``project_status`` / ``billing_type_code`` enums (migration 001).  Validated
#: here so a refused value reads as a sentence instead of a Postgres enum
#: error reaching the user.
PROJECT_STATUSES = ("PLANNING", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED")
BILLING_TYPES = ("FIXED_PRICE", "TIME_AND_MATERIALS", "RETAINER")

#: The only columns an edit may change.  ``project_code`` is an identifier
#: (documents and journals already cite it) and ``organization_id`` is never a
#: caller's business — an unknown key is REFUSED, not silently dropped.
UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "status",
        "start_date",
        "end_date",
        "budget",
        "billing_type",
        "customer_id",
    }
)


def _blank_to_none(value: Any) -> Optional[Any]:
    """``""`` from a form means "no value" — never the string ``""`` in a
    date/numeric column."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _clean_common(
    *,
    name: Any = None,
    budget: Any = None,
    start_date: Any = None,
    end_date: Any = None,
    status: Any = None,
    billing_type: Any = None,
) -> Dict[str, Any]:
    """Validate + normalise the fields create and update share.

    Every rule here is mirrored in the page's ``projectFormBlocker`` so the
    user reads the refusal BEFORE the round trip — but the server never
    trusts that mirror (the agent path posts through the same functions).
    """
    out: Dict[str, Any] = {}

    if name is not None:
        clean_name = str(name or "").strip()
        if len(clean_name) < 2:
            raise ValueError("A project name is required (at least 2 characters).")
        out["name"] = clean_name

    if budget is not None:
        raw_budget = _blank_to_none(budget)
        if raw_budget is None:
            out["budget"] = None  # a blank field means "no budget", not 0
        else:
            try:
                value = round(float(raw_budget), 2)
            except (TypeError, ValueError):
                raise ValueError("Project budget must be a number.")
            if value < 0:
                raise ValueError("Project budget cannot be negative.")
            out["budget"] = value

    start = _blank_to_none(start_date)
    end = _blank_to_none(end_date)
    for label, value in (("start", start), ("end", end)):
        if value is not None:
            try:
                datetime.strptime(str(value)[:10], "%Y-%m-%d")
            except ValueError:
                raise ValueError(
                    f"The {label} date must be formatted YYYY-MM-DD."
                )
    if start is not None:
        out["start_date"] = str(start)[:10]
    if end is not None:
        out["end_date"] = str(end)[:10]
    if start is not None and end is not None and str(end)[:10] < str(start)[:10]:
        raise ValueError("The end date cannot be before the start date.")

    if status is not None:
        status_up = str(status).strip().upper()
        if status_up not in PROJECT_STATUSES:
            raise ValueError(
                f"Unknown project status '{status}'. Use one of: "
                f"{', '.join(PROJECT_STATUSES).lower().replace('_', ' ')}."
            )
        out["status"] = status_up

    if billing_type is not None:
        billing_up = str(billing_type).strip().upper()
        if billing_up not in BILLING_TYPES:
            raise ValueError(
                f"Unknown billing type '{billing_type}'. Use one of: "
                f"{', '.join(BILLING_TYPES).lower().replace('_', ' ')}."
            )
        out["billing_type"] = billing_up

    return out


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
    status: str = "PLANNING",
) -> Dict[str, Any]:
    """Create a project.

    ``project_code`` is OPTIONAL from the caller's point of view: the
    repository derives ``<STEM>-###`` when the user did not state a code
    (``projects.project_code`` is NOT NULL, and no natural-language request
    names one).

    The rules (name, budget, date order, enums) are enforced HERE so both the
    Projects page and the AI agent get the same sentence instead of a
    constraint violation.
    """
    if name is None:
        # ``_clean_common`` treats None as "field not sent" (the update
        # contract) — creation has no such luxury: there is no project
        # without a name, and the refusal must be a sentence, not a KeyError.
        raise ValueError("A project name is required (at least 2 characters).")
    clean = _clean_common(
        name=name,
        budget=budget,
        start_date=start_date,
        end_date=end_date,
        status=status,
        billing_type=billing_type,
    )
    return await repo.create_project(
        organization_id=organization_id,
        name=clean["name"],
        project_code=project_code,
        description=(str(description).strip() or None) if description else None,
        customer_id=customer_id,
        start_date=clean.get("start_date"),
        end_date=clean.get("end_date"),
        budget=clean.get("budget"),
        currency_code=str(currency_code or "PKR").upper(),
        billing_type=clean.get("billing_type"),
        status=clean.get("status") or "PLANNING",
    )


async def update(
    organization_id: uuid.UUID, *, project_id: uuid.UUID, **fields: Any
) -> Dict[str, Any]:
    """Edit a project — only ``UPDATABLE_FIELDS`` may change.

    The row is read first (organisation-scoped) so an unknown id answers
    "not found" (404) rather than silently updating nothing, and every value
    is validated against the same rules as ``create``.
    """
    unknown = set(fields) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown project field: {', '.join(sorted(unknown))}. Editable "
            f"fields are {', '.join(sorted(UPDATABLE_FIELDS))}."
        )
    if not fields:
        # Nothing to change — a PATCH of {} is a no-op, not an error.
        current = await repo.get_project(organization_id, project_id=project_id)
        if not current:
            raise ValueError(f"Project {project_id} not found.")
        return current

    current = await repo.get_project(organization_id, project_id=project_id)
    if not current:
        raise ValueError(f"Project {project_id} not found.")

    # Each field is validated ONLY when it is being sent, and a blank value
    # means "clear this column" (except name/status, which the schema needs) —
    # so the form can unset a date or a budget without inventing a sentinel.
    payload: Dict[str, Any] = {}

    if "name" in fields:
        payload.update(_clean_common(name=fields["name"]))

    if "budget" in fields:
        if _blank_to_none(fields["budget"]) is None:
            payload["budget"] = None
        else:
            payload.update(_clean_common(budget=fields["budget"]))

    if "start_date" in fields:
        if _blank_to_none(fields["start_date"]) is None:
            payload["start_date"] = None
        else:
            payload.update(_clean_common(start_date=fields["start_date"]))

    if "end_date" in fields:
        if _blank_to_none(fields["end_date"]) is None:
            payload["end_date"] = None
        else:
            payload.update(_clean_common(end_date=fields["end_date"]))

    if "status" in fields:
        if _blank_to_none(fields["status"]) is None:
            raise ValueError("A project status is required.")
        payload.update(_clean_common(status=fields["status"]))

    if "billing_type" in fields:
        if _blank_to_none(fields["billing_type"]) is None:
            payload["billing_type"] = None
        else:
            payload.update(_clean_common(billing_type=fields["billing_type"]))

    if "description" in fields:
        value = _blank_to_none(fields["description"])
        payload["description"] = str(value).strip() if value else None
    if "customer_id" in fields:
        payload["customer_id"] = (
            str(fields["customer_id"]) if fields["customer_id"] else None
        )

    # The dates are validated ABOVE against what the form sent; re-check the
    # MERGED pair so editing only the end date cannot violate the DB's
    # ``end_date >= start_date`` check with a stale start.
    merged_start = payload.get(
        "start_date", str(current.get("start_date") or "")[:10] or None
    )
    merged_end = payload.get(
        "end_date", str(current.get("end_date") or "")[:10] or None
    )
    if merged_start and merged_end and merged_end < merged_start:
        raise ValueError("The end date cannot be before the start date.")

    updated = await repo.update_project(
        organization_id, project_id=project_id, fields=payload
    )
    if not updated:
        # The row vanished between the read and the write (or the org filter
        # rejected it) — say so instead of returning the stale copy.
        raise ValueError(f"Project {project_id} not found.")
    return {**current, **updated}


async def get_profitability(
    organization_id: uuid.UUID,
    *,
    project_id: uuid.UUID,
) -> List[Dict[str, Any]]:
    return await repo.get_project_profitability(
        organization_id, project_id=project_id
    )
