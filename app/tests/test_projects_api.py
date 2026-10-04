"""Projects API — the REST layer the Projects page drives.

There was no ``/api/projects`` at all before this (the page was a
``ComingSoon`` placeholder while ``project_service`` existed only for the AI
agent), so these tests pin the contract the UI now depends on:

* LIST: items (P&L + customer label merged) + REGISTER-WIDE counts + summary +
  the customer list, in ONE request; ``query``/``status`` narrow ``items``
  only, so a filter can never make the counts lie.
* CREATE: the service derives the code, validates the rules, and every refusal
  surfaces as 409/404 with its own message — never a constraint violation.
* PATCH: the id comes from the PATH, only editable fields are accepted, and a
  missing project answers 404.
* SERVICE: the validation the page mirrors client-side (name, budget, date
  order, enums) is enforced server-side too, because the AI agent posts
  through the same functions.
"""

import uuid

import pytest

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
PROJECT = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _auth():
    from types import SimpleNamespace

    return SimpleNamespace(organization_id=ORG, user_id=uuid.uuid4())


def _project(**over) -> dict:
    base = {
        "id": str(PROJECT),
        "organization_id": str(ORG),
        "project_code": "MOB-001",
        "name": "Mobile App",
        "description": "Android rebuild",
        "customer_id": None,
        "status": "ACTIVE",
        "billing_type": "FIXED_PRICE",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "budget": 2000000.0,
        "currency_code": "PKR",
        "is_active": True,
    }
    base.update(over)
    return base


def _patch_reads(monkeypatch, projects: list, pnl: list, customers: list):
    """Stub the list endpoint's three reads (no live database)."""
    from app import main as main_mod
    from app.services import project_service

    async def fake_list(org_id, *, limit=500):
        return list(projects)

    async def fake_fetch(table, *, filters, select="*", order=None,
                         limit=100, offset=0):
        assert filters == {"organization_id": str(ORG)}
        if table == "v_project_profitability":
            return list(pnl)
        if table == "customers":
            return list(customers)
        raise AssertionError(f"unexpected table {table}")

    monkeypatch.setattr(project_service, "list_projects", fake_list)
    monkeypatch.setattr(main_mod, "fetch_many", fake_fetch)


class TestListProjects:
    @pytest.mark.asyncio
    async def test_one_request_carries_items_counts_summary_and_customers(
        self, monkeypatch
    ):
        from app import main as main_mod

        projects = [
            _project(),
            _project(id="44444444-4444-4444-4444-444444444444",
                     project_code="WEB-001", name="Website", status="PLANNING",
                     budget=None),
        ]
        pnl = [
            {"project_id": str(PROJECT), "project_revenue": 500000.0,
             "project_costs": 300000.0, "gross_profit": 200000.0,
             "margin_percent": 40.0},
        ]
        customers = [{"id": "55555555-5555-5555-5555-555555555555",
                      "name": "Zameer Labs"}]
        _patch_reads(monkeypatch, projects, pnl, customers)

        out = await main_mod.list_projects_endpoint(auth=_auth())

        assert out["counts"] == {
            "ALL": 2, "PLANNING": 1, "ACTIVE": 1, "ON_HOLD": 0,
            "COMPLETED": 0, "CANCELLED": 0,
        }
        assert out["summary"]["budget"] == 2000000.0
        assert out["summary"]["revenue"] == 500000.0
        assert out["summary"]["gross_profit"] == 200000.0
        assert out["customers"] == customers
        by_id = {item["id"]: item for item in out["items"]}
        assert by_id[str(PROJECT)]["revenue"] == 500000.0
        assert by_id[str(PROJECT)]["margin_percent"] == 40.0
        assert by_id["44444444-4444-4444-4444-444444444444"]["revenue"] == 0.0

    @pytest.mark.asyncio
    async def test_the_filter_narrows_items_but_never_the_counts(
        self, monkeypatch
    ):
        from app import main as main_mod

        projects = [
            _project(),
            _project(id="44444444-4444-4444-4444-444444444444",
                     project_code="WEB-001", name="Website", status="PLANNING"),
        ]
        _patch_reads(monkeypatch, projects, [], [])

        out = await main_mod.list_projects_endpoint(
            query="website", status="PLANNING", auth=_auth()
        )
        assert [item["name"] for item in out["items"]] == ["Website"]
        assert out["counts"]["ALL"] == 2
        assert out["counts"]["ACTIVE"] == 1

        # an unknown status is normalised — never an error, never an empty lie
        out2 = await main_mod.list_projects_endpoint(
            status="WHATEVER", auth=_auth()
        )
        assert out2["status"] == "ALL"
        assert len(out2["items"]) == 2

    @pytest.mark.asyncio
    async def test_a_broken_profitability_view_still_renders_the_register(
        self, monkeypatch
    ):
        """The P&L columns are decoration, not authority: if the view is down
        the page must still list projects (with zeros), not 500."""
        from app import main as main_mod
        from app.services import project_service

        async def fake_list(org_id, *, limit=500):
            return [_project()]

        async def fake_fetch(table, *, filters, select="*", order=None,
                             limit=100, offset=0):
            if table == "v_project_profitability":
                raise RuntimeError("view unavailable")
            return []

        monkeypatch.setattr(project_service, "list_projects", fake_list)
        monkeypatch.setattr(main_mod, "fetch_many", fake_fetch)

        out = await main_mod.list_projects_endpoint(auth=_auth())
        assert len(out["items"]) == 1
        assert out["items"][0]["revenue"] == 0.0

    @pytest.mark.asyncio
    async def test_a_full_page_is_reported_truncated(self, monkeypatch):
        """A register that fills the read page must SAY SO — the counts and the
        summary then describe only the rows read, so pretending completeness
        would be a quiet lie."""
        from app import main as main_mod

        full = [
            _project(id=str(uuid.uuid4()))
            for _ in range(main_mod._PROJECT_REGISTER_LIMIT)
        ]
        _patch_reads(monkeypatch, full, [], [])

        out = await main_mod.list_projects_endpoint(auth=_auth())
        assert out["truncated"] is True
        assert out["total"] == main_mod._PROJECT_REGISTER_LIMIT

    @pytest.mark.asyncio
    async def test_a_short_page_is_not_truncated(self, monkeypatch):
        from app import main as main_mod

        _patch_reads(monkeypatch, [_project()], [], [])
        out = await main_mod.list_projects_endpoint(auth=_auth())
        assert out["truncated"] is False
        assert out["total"] == 1
        assert out["degraded"] == []

    @pytest.mark.asyncio
    async def test_a_degraded_lookup_is_named_never_shown_as_zero(
        self, monkeypatch
    ):
        """Both lookups failing must still render the register AND be named, so
        the page shows "—" (unknown) instead of a bare 0 that reads as
        "this project earned nothing"."""
        from app import main as main_mod
        from app.services import project_service

        async def fake_list(org_id, *, limit=500):
            return [_project()]

        async def broken_fetch(table, *, filters, select="*", order=None,
                               limit=100, offset=0):
            raise RuntimeError(f"{table} unavailable")

        monkeypatch.setattr(project_service, "list_projects", fake_list)
        monkeypatch.setattr(main_mod, "fetch_many", broken_fetch)

        out = await main_mod.list_projects_endpoint(auth=_auth())
        assert out["degraded"] == ["profitability", "customers"]
        assert out["items"][0]["revenue"] == 0.0


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_the_payload_reaches_the_service_with_page_defaults(
        self, monkeypatch
    ):
        from app import main as main_mod
        from app.services import project_service

        captured: dict = {}

        async def fake_create(org_id, **kw):
            captured["org"] = org_id
            captured.update(kw)
            return {
                "id": str(PROJECT),
                **kw,
                # the repository derives the code when the caller states none
                "project_code": kw.get("project_code") or "MOB-001",
            }

        monkeypatch.setattr(project_service, "create", fake_create)

        out = await main_mod.create_project_endpoint(
            {
                "name": "  Mobile App  ",
                "budget": 2000000,
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "status": "ACTIVE",
                "billing_type": "fixed_price",
                "currency_code": "PKR",
                "customer_id": "55555555-5555-5555-5555-555555555555",
            },
            auth=_auth(),
        )

        assert out["item"]["project_code"] == "MOB-001"
        assert captured["org"] == ORG
        # the endpoint PASSES the value through; the service trims it (the
        # service is stubbed here — trimming is pinned in the service tests)
        assert captured["name"] == "  Mobile App  "
        assert captured["status"] == "ACTIVE"
        assert captured["billing_type"] == "fixed_price"
        assert str(captured["customer_id"]) == "55555555-5555-5555-5555-555555555555"

    @pytest.mark.asyncio
    async def test_a_missing_name_is_409_not_a_500(self):
        from app import main as main_mod
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await main_mod.create_project_endpoint({"budget": 10}, auth=_auth())
        assert exc.value.status_code == 409
        assert "name" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_a_service_refusal_surfaces_with_its_message(
        self, monkeypatch
    ):
        from app import main as main_mod
        from app.services import project_service
        from fastapi import HTTPException

        async def refuse(org_id, **kw):
            raise ValueError("The end date cannot be before the start date.")

        monkeypatch.setattr(project_service, "create", refuse)

        with pytest.raises(HTTPException) as exc:
            await main_mod.create_project_endpoint(
                {"name": "Mobile App", "start_date": "2026-06-30",
                 "end_date": "2026-01-01"},
                auth=_auth(),
            )
        assert exc.value.status_code == 409
        assert "end date" in str(exc.value.detail)


class TestUpdateProject:
    @pytest.mark.asyncio
    async def test_the_path_id_wins_over_a_body_that_claims_one(
        self, monkeypatch
    ):
        """A body carrying ``project_id`` must never reach ``**fields`` — it
        would collide with the keyword argument (TypeError → 500)."""
        from app import main as main_mod
        from app.services import project_service

        captured: dict = {}

        async def fake_update(org_id, *, project_id, **fields):
            captured["org"] = org_id
            captured["project_id"] = project_id
            captured["fields"] = fields
            return {"id": str(project_id), **fields}

        monkeypatch.setattr(project_service, "update", fake_update)

        out = await main_mod.update_project_endpoint(
            PROJECT,
            {"project_id": "99999999-9999-9999-9999-999999999999",
             "name": "Mobile App v2"},
            auth=_auth(),
        )
        assert captured["project_id"] == PROJECT
        assert captured["fields"] == {"name": "Mobile App v2"}
        assert out["item"]["name"] == "Mobile App v2"

    @pytest.mark.asyncio
    async def test_an_unknown_project_is_404_with_its_message(
        self, monkeypatch
    ):
        from app import main as main_mod
        from app.services import project_service
        from fastapi import HTTPException

        async def missing(org_id, *, project_id, **fields):
            raise ValueError(f"Project {project_id} not found.")

        monkeypatch.setattr(project_service, "update", missing)

        with pytest.raises(HTTPException) as exc:
            await main_mod.update_project_endpoint(
                PROJECT, {"name": "Renamed"}, auth=_auth()
            )
        assert exc.value.status_code == 404
        assert "not found" in str(exc.value.detail)



class TestServiceValidation:
    """The rules the page mirrors in ``projectFormBlocker`` — enforced here
    too, because the AI agent posts through the very same functions."""

    @pytest.mark.asyncio
    async def _create(self, monkeypatch, **kwargs):
        from app.repositories import project_repository as repo
        from app.services import project_service

        captured: dict = {}

        async def fake_create(**kw):
            captured.update(kw)
            return {"id": str(PROJECT), **kw}

        monkeypatch.setattr(repo, "create_project", fake_create)
        await project_service.create(ORG, **kwargs)
        return captured

    @pytest.mark.asyncio
    async def test_a_blank_budget_is_no_budget_not_zero(self, monkeypatch):
        captured = await self._create(
            monkeypatch, name="Mobile App", project_code="MOB-001", budget=""
        )
        assert captured["budget"] is None

    @pytest.mark.asyncio
    async def test_the_name_is_trimmed_not_re_cased(self, monkeypatch):
        captured = await self._create(
            monkeypatch, name="  Mobile App  ", project_code="MOB-001"
        )
        assert captured["name"] == "Mobile App"

    @pytest.mark.asyncio
    async def test_a_negative_budget_is_refused_with_a_sentence(
        self, monkeypatch
    ):
        from app.services import project_service

        with pytest.raises(ValueError, match="cannot be negative"):
            await project_service.create(
                ORG, name="Mobile App", project_code="MOB-001", budget=-5
            )

    @pytest.mark.asyncio
    async def test_a_non_numeric_budget_is_refused(self, monkeypatch):
        from app.services import project_service

        with pytest.raises(ValueError, match="must be a number"):
            await project_service.create(
                ORG, name="Mobile App", project_code="MOB-001", budget="lots"
            )

    @pytest.mark.asyncio
    async def test_an_end_date_before_the_start_date_is_refused(
        self, monkeypatch
    ):
        from app.services import project_service

        with pytest.raises(ValueError, match="end date cannot be before"):
            await project_service.create(
                ORG, name="Mobile App", project_code="MOB-001",
                start_date="2026-06-30", end_date="2026-01-01",
            )

    @pytest.mark.asyncio
    async def test_an_unknown_status_names_the_valid_ones(self, monkeypatch):
        from app.services import project_service

        with pytest.raises(ValueError, match="Unknown project status"):
            await project_service.create(
                ORG, name="Mobile App", project_code="MOB-001", status="DONE"
            )

    @pytest.mark.asyncio
    async def test_an_unknown_billing_type_is_refused(self, monkeypatch):
        from app.services import project_service

        with pytest.raises(ValueError, match="Unknown billing type"):
            await project_service.create(
                ORG, name="Mobile App", project_code="MOB-001",
                billing_type="HOURLY",
            )

    @pytest.mark.asyncio
    async def test_a_two_character_name_floor_is_enforced(self, monkeypatch):
        from app.services import project_service

        with pytest.raises(ValueError, match="project name is required"):
            await project_service.create(
                ORG, name=" x ", project_code="MOB-001"
            )


class TestServiceUpdate:
    async def _update(self, monkeypatch, *, fields: dict, current: dict):
        from app.repositories import project_repository as repo
        from app.services import project_service

        captured: dict = {}

        async def fake_get(org_id, *, project_id):
            return dict(current)

        async def fake_update(org_id, *, project_id, fields):
            captured["fields"] = fields
            return {"id": str(project_id), **fields}

        monkeypatch.setattr(repo, "get_project", fake_get)
        monkeypatch.setattr(repo, "update_project", fake_update)
        result = await project_service.update(
            ORG, project_id=PROJECT, **fields
        )
        return captured, result

    @pytest.mark.asyncio
    async def test_an_unknown_field_is_refused_not_silently_dropped(
        self, monkeypatch
    ):
        from app.services import project_service

        with pytest.raises(ValueError, match="Unknown project field"):
            await project_service.update(
                ORG, project_id=PROJECT, project_code="HACK-1"
            )

    @pytest.mark.asyncio
    async def test_a_blank_budget_clears_the_column(self, monkeypatch):
        captured, _ = await self._update(
            monkeypatch, fields={"budget": ""}, current=_project()
        )
        assert captured["fields"] == {"budget": None}

    @pytest.mark.asyncio
    async def test_editing_only_the_end_date_checks_the_stored_start(
        self, monkeypatch
    ):
        from app.repositories import project_repository as repo
        from app.services import project_service

        async def fake_get(org_id, *, project_id):
            return dict(_project())

        monkeypatch.setattr(repo, "get_project", fake_get)

        with pytest.raises(ValueError, match="end date cannot be before"):
            await project_service.update(
                ORG, project_id=PROJECT, end_date="2025-12-31"
            )

    @pytest.mark.asyncio
    async def test_a_patch_of_nothing_is_a_noop(self, monkeypatch):
        from app.repositories import project_repository as repo
        from app.services import project_service

        async def fake_get(org_id, *, project_id):
            return dict(_project())

        async def must_not_write(*args, **kwargs):
            raise AssertionError("a PATCH {} must not write")

        monkeypatch.setattr(repo, "get_project", fake_get)
        monkeypatch.setattr(repo, "update_project", must_not_write)

        result = await project_service.update(ORG, project_id=PROJECT)
        assert result["project_code"] == "MOB-001"


class TestRegisterPaging:
    """A single PostgREST response caps at ~1000 rows, so the register MUST be
    read in pages — otherwise the counts, the summary AND search silently
    describe only the first page."""

    @pytest.mark.asyncio
    async def test_paging_follows_a_full_page_with_a_short_one(self, monkeypatch):
        from app.repositories import project_repository as repo

        offsets: list[int] = []

        async def fake_fetch(table, *, filters, select="*", order=None,
                             limit=100, offset=0):
            offsets.append(offset)
            if offset == 0:
                return [{"id": f"p{i}"} for i in range(limit)]  # a FULL page
            return [{"id": f"p{offset + i}"} for i in range(3)]  # a SHORT page

        monkeypatch.setattr(repo, "fetch_many", fake_fetch)

        rows = await repo.list_all_projects(ORG, limit=2000)
        assert len(rows) == 503  # 500 + 3, then the short page ends the read
        assert offsets == [0, 500]

    @pytest.mark.asyncio
    async def test_paging_stops_at_the_ceiling(self, monkeypatch):
        from app.repositories import project_repository as repo

        async def fake_fetch(table, *, filters, select="*", order=None,
                             limit=100, offset=0):
            return [{"id": f"p{offset + i}"} for i in range(limit)]

        monkeypatch.setattr(repo, "fetch_many", fake_fetch)

        rows = await repo.list_all_projects(ORG, limit=1200)
        assert len(rows) == 1200  # 500 + 500 + 200, then the ceiling stops it

