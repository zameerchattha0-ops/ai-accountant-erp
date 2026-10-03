"""Fixed Assets register — REST endpoint wiring + refusal contract.

The Fixed Assets page drives these endpoints; every MUTATION must reach
``fixed_asset_service`` (the accounting engine posts the journal), so the page
and the AI agent can never disagree about the register.

Pinned invariants:
* LIST: items + counts + summary in ONE read; counts and the summary describe
  the whole REGISTER while ``query``/``status`` narrow the rows only.
* REGISTER: name + cost validation (409) before the service is reached; the
  service receives the parsed payload and ``created_by``.
* DETAIL: 404 for an asset outside the caller's organisation.
* DEPRECIATION / DISPOSAL: numeric payloads are validated here, then the
  service's ``ValueError`` (no policy, wrong status, unconfigured accounts)
  surfaces as 409 with its own message — never a generic 500.
"""

import uuid
from types import SimpleNamespace

import pytest

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
ASSET = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _auth() -> SimpleNamespace:
    """The endpoints only read organization_id / user_id from the context."""
    return SimpleNamespace(organization_id=ORG, user_id=uuid.uuid4())


def _rows() -> list:
    return [
        {"id": "a1", "asset_code": "FA-000001", "name": "Delivery Van",
         "purchase_date": "2026-09-01", "purchase_cost": 4000000.0,
         "accumulated_depreciation": 0.0, "book_value": 4000000.0,
         "salvage_value": 0.0, "useful_life_years": 5,
         "depreciation_method": "STRAIGHT_LINE", "status": "ACTIVE"},
        {"id": "a2", "asset_code": "FA-000002", "name": "Old Laptop",
         "purchase_date": "2025-01-10", "purchase_cost": 200000.0,
         "accumulated_depreciation": 200000.0, "book_value": 0.0,
         "salvage_value": 0.0, "useful_life_years": 4,
         "depreciation_method": "STRAIGHT_LINE", "status": "FULLY_DEPRECIATED"},
        {"id": "a3", "asset_code": "FA-000003", "name": "Sold Printer",
         "purchase_date": "2024-05-02", "purchase_cost": 50000.0,
         "accumulated_depreciation": 50000.0, "book_value": 0.0,
         "salvage_value": 0.0, "useful_life_years": 3,
         "depreciation_method": "STRAIGHT_LINE", "status": "SOLD"},
    ]


class TestRegisterListing:
    @pytest.mark.asyncio
    async def test_items_counts_and_summary_come_from_one_read(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        calls = []

        async def fake_list(org_id, *, limit=200):
            calls.append((org_id, limit))
            return _rows()

        monkeypatch.setattr(fixed_asset_service, "list_assets", fake_list)

        out = await main_mod.list_fixed_assets_endpoint(
            query="", status="ALL", auth=_auth()
        )

        assert len(calls) == 1 and calls[0][0] == ORG
        assert [r["id"] for r in out["items"]] == ["a1", "a2", "a3"]
        assert out["counts"]["ALL"] == 3
        assert out["counts"]["ACTIVE"] == 1
        assert out["counts"]["FULLY_DEPRECIATED"] == 1
        assert out["counts"]["SOLD"] == 1
        assert out["counts"]["DISPOSED"] == 0
        # cost 4,000,000 + 200,000 + 50,000; only the van still carries value
        assert out["summary"]["purchase_cost"] == 4250000.0
        assert out["summary"]["accumulated_depreciation"] == 250000.0
        assert out["summary"]["book_value"] == 4000000.0
        assert out["status"] == "ALL"

    @pytest.mark.asyncio
    async def test_filter_narrows_rows_but_not_the_register_totals(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        async def fake_list(org_id, *, limit=200):
            return _rows()

        monkeypatch.setattr(fixed_asset_service, "list_assets", fake_list)

        out = await main_mod.list_fixed_assets_endpoint(
            query="laptop", status="ALL", auth=_auth()
        )
        assert [r["id"] for r in out["items"]] == ["a2"]

        out = await main_mod.list_fixed_assets_endpoint(
            query="", status="SOLD", auth=_auth()
        )
        assert [r["id"] for r in out["items"]] == ["a3"]
        assert out["status"] == "SOLD"
        assert out["summary"]["purchase_cost"] == 4250000.0

        out = await main_mod.list_fixed_assets_endpoint(
            query="fa-000003", status="ALL", auth=_auth()
        )
        assert [r["id"] for r in out["items"]] == ["a3"]


class TestRegisterAsset:
    @pytest.mark.asyncio
    async def test_name_is_required(self):
        from app import main as main_mod
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await main_mod.create_fixed_asset_endpoint(
                {"purchase_cost": 100}, auth=_auth()
            )
        assert exc.value.status_code == 409
        assert "name" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_useful_life_must_be_a_positive_whole_number(self):
        from app import main as main_mod
        from fastapi import HTTPException

        for bad in ("abc", "-2", "0"):
            with pytest.raises(HTTPException) as exc:
                await main_mod.create_fixed_asset_endpoint(
                    {"name": "Van", "purchase_cost": 100, "useful_life_years": bad},
                    auth=_auth(),
                )
            assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_delegates_the_parsed_payload_to_the_service(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        captured: dict = {}

        async def fake_register(org_id, **kw):
            captured["org"] = org_id
            captured.update(kw)
            return {"id": "a1", "asset_code": "FA-000001", "name": kw["name"]}

        monkeypatch.setattr(fixed_asset_service, "register_asset", fake_register)

        auth = _auth()
        out = await main_mod.create_fixed_asset_endpoint(
            {
                "name": "  Delivery Van  ",
                "purchase_cost": "4000000",
                "purchase_date": "2026-09-01",
                "payment_method": "cash",
                # The settlement ledger: forwarded, never dropped (the form's
                # bank/cash picker would otherwise be silently ignored).
                "payment_account_id": "99999999-9999-9999-9999-999999999999",
                "useful_life_years": "5",
                "salvage_value": "0",
            },
            auth=auth,
        )

        assert out["item"]["asset_code"] == "FA-000001"
        assert captured["org"] == ORG
        assert captured["payment_method"] == "CASH"
        assert str(captured["payment_account_id"]) == "99999999-9999-9999-9999-999999999999"
        assert captured["useful_life_years"] == 5
        assert captured["depreciation_method"] == "STRAIGHT_LINE"
        assert captured["created_by"] == auth.user_id

    @pytest.mark.asyncio
    async def test_service_refusal_surfaces_as_409(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service
        from fastapi import HTTPException

        async def refuse(org_id, **kw):
            raise ValueError(
                "No fixed-asset account could be determined for this acquisition."
            )

        monkeypatch.setattr(fixed_asset_service, "register_asset", refuse)
        with pytest.raises(HTTPException) as exc:
            await main_mod.create_fixed_asset_endpoint(
                {"name": "Van", "purchase_cost": 100}, auth=_auth()
            )
        assert exc.value.status_code == 409
        assert "fixed-asset account" in str(exc.value.detail)


class TestLifecycleEndpoints:
    @pytest.mark.asyncio
    async def test_detail_404s_for_an_unknown_asset(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service
        from fastapi import HTTPException

        async def missing(org_id, *, asset_id):
            return None

        monkeypatch.setattr(fixed_asset_service, "get", missing)
        with pytest.raises(HTTPException) as exc:
            await main_mod.get_fixed_asset_endpoint(ASSET, auth=_auth())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_depreciation_passes_the_amount_and_date(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        captured: dict = {}

        async def fake_dep(org_id, **kw):
            captured.update(kw)
            return {"id": "a1", "accumulated_depreciation": 1000.0}

        monkeypatch.setattr(fixed_asset_service, "record_depreciation", fake_dep)

        out = await main_mod.record_fixed_asset_depreciation_endpoint(
            ASSET,
            {"depreciation_amount": "1000", "transaction_date": "2026-09-30"},
            auth=_auth(),
        )
        assert out["item"]["accumulated_depreciation"] == 1000.0
        assert captured["asset_id"] == str(ASSET)
        assert captured["depreciation_amount"] == 1000.0
        assert captured["transaction_date"] == "2026-09-30"

        # blank amount -> the asset's own policy (None, never 0)
        captured.clear()
        await main_mod.record_fixed_asset_depreciation_endpoint(
            ASSET, {"depreciation_amount": ""}, auth=_auth()
        )
        assert captured["depreciation_amount"] is None

    @pytest.mark.asyncio
    async def test_depreciation_amount_must_be_numeric(self):
        from app import main as main_mod
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await main_mod.record_fixed_asset_depreciation_endpoint(
                ASSET, {"depreciation_amount": "lots"}, auth=_auth()
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_disposal_validates_proceeds_and_type(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service
        from fastapi import HTTPException

        captured: dict = {}

        async def fake_dispose(org_id, **kw):
            captured.update(kw)
            return {"id": "a1", "status": "SOLD"}

        monkeypatch.setattr(fixed_asset_service, "dispose_asset", fake_dispose)

        out = await main_mod.dispose_fixed_asset_endpoint(
            ASSET,
            {"disposal_type": "sale", "disposal_amount": "250000"},
            auth=_auth(),
        )
        assert out["item"]["status"] == "SOLD"
        assert captured["disposal_type"] == "SALE"
        assert captured["disposal_amount"] == 250000.0

        with pytest.raises(HTTPException) as exc:
            await main_mod.dispose_fixed_asset_endpoint(
                ASSET, {"disposal_amount": "not-a-number"}, auth=_auth()
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_disposal_refusal_surfaces_as_409(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service
        from fastapi import HTTPException

        async def refuse(org_id, **kw):
            raise ValueError(
                "Asset 'Old Laptop' has status DISPOSED and cannot be "
                "disposed of again."
            )

        monkeypatch.setattr(fixed_asset_service, "dispose_asset", refuse)
        with pytest.raises(HTTPException) as exc:
            await main_mod.dispose_fixed_asset_endpoint(ASSET, {}, auth=_auth())
        assert exc.value.status_code == 409
        assert "cannot be disposed of again" in str(exc.value.detail)


class TestAssetCategories:
    """Categories are CONFIGURATION (default life / method / GL accounts).

    The table already existed with no UI-facing surface — these endpoints are
    what the Fixed Assets page's category manager drives.
    """

    @pytest.mark.asyncio
    async def test_list_comes_from_the_service_scoped_to_the_org(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        calls = []

        async def fake_list(org_id):
            calls.append(org_id)
            return [{"id": "c1", "name": "Vehicles",
                     "default_useful_life_years": 5,
                     "default_depreciation_method": "STRAIGHT_LINE"}]

        monkeypatch.setattr(fixed_asset_service, "list_asset_categories", fake_list)
        out = await main_mod.list_fixed_asset_categories_endpoint(auth=_auth())
        assert calls == [ORG]
        assert out["items"][0]["name"] == "Vehicles"

    @pytest.mark.asyncio
    async def test_create_forwards_payload_and_parses_account_ids(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        seen = {}

        async def fake_create(org_id, **kw):
            seen["org"] = org_id
            seen.update(kw)
            return {"id": "c1", **{k: str(v) if hasattr(v, "hex") else v
                                   for k, v in kw.items()}}

        monkeypatch.setattr(fixed_asset_service, "create_asset_category", fake_create)
        asset_acc, dep_acc, acc_dep = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        out = await main_mod.create_fixed_asset_category_endpoint(
            {
                "name": "  Vehicles  ",
                "default_useful_life_years": 5,
                "default_depreciation_method": "straight_line",
                "default_asset_account_id": str(asset_acc),
                "default_depreciation_expense_account_id": str(dep_acc),
                "default_accumulated_depreciation_account_id": str(acc_dep),
            },
            auth=_auth(),
        )
        assert seen["org"] == ORG
        assert seen["default_asset_account_id"] == asset_acc
        assert seen["default_depreciation_expense_account_id"] == dep_acc
        assert seen["default_accumulated_depreciation_account_id"] == acc_dep
        assert seen["default_useful_life_years"] == 5
        assert out["item"]["id"] == "c1"

    @pytest.mark.asyncio
    async def test_validation_error_is_409_not_500(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service
        from fastapi import HTTPException

        async def refuse(org_id, **kw):
            raise ValueError("A category name is required.")

        monkeypatch.setattr(fixed_asset_service, "create_asset_category", refuse)
        with pytest.raises(HTTPException) as exc:
            await main_mod.create_fixed_asset_category_endpoint({}, auth=_auth())
        assert exc.value.status_code == 409
        assert "category name" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_duplicate_name_is_409(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service
        from fastapi import HTTPException

        async def refuse(org_id, **kw):
            raise ValueError("A category named 'Vehicles' already exists.")

        monkeypatch.setattr(fixed_asset_service, "create_asset_category", refuse)
        with pytest.raises(HTTPException) as exc:
            await main_mod.create_fixed_asset_category_endpoint(
                {"name": "Vehicles"}, auth=_auth()
            )
        assert exc.value.status_code == 409
        assert "already exists" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_update_forwards_only_the_payload_fields(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        seen = {}

        async def fake_update(org_id, *, category_id, **kw):
            seen.update({"org": org_id, "category_id": category_id, **kw})
            return {"id": str(category_id), **kw}

        monkeypatch.setattr(fixed_asset_service, "update_asset_category", fake_update)
        out = await main_mod.update_fixed_asset_category_endpoint(
            ASSET, {"default_useful_life_years": 7}, auth=_auth()
        )
        assert seen["org"] == ORG and seen["category_id"] == ASSET
        assert seen == {"org": ORG, "category_id": ASSET,
                        "default_useful_life_years": 7}
        assert out["item"]["default_useful_life_years"] == 7

    @pytest.mark.asyncio
    async def test_update_maps_not_found_to_404(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service
        from fastapi import HTTPException

        async def miss(org_id, *, category_id, **kw):
            raise ValueError("Category not found.")

        monkeypatch.setattr(fixed_asset_service, "update_asset_category", miss)
        with pytest.raises(HTTPException) as exc:
            await main_mod.update_fixed_asset_category_endpoint(
                ASSET, {"name": "x"}, auth=_auth()
            )
        assert exc.value.status_code == 404

    def test_categories_routes_are_declared_before_the_asset_id_route(self):
        """Path segments match in order: '/categories' must be declared before
        '/{asset_id}' or FastAPI parses 'categories' as a UUID → 422."""
        from app.main import app

        paths = [getattr(r, "path", "") for r in app.routes]
        cat = paths.index("/api/fixed-assets/categories")
        detail = paths.index("/api/fixed-assets/{asset_id}")
        assert cat < detail


class TestRegisterCarriesConfiguration:
    """The form's choices must REACH the service: category + the GL accounts
    that the later depreciation charge will need."""

    @pytest.mark.asyncio
    async def test_register_forwards_category_and_gl_accounts(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        seen = {}

        async def fake_register(org_id, **kw):
            seen.update(kw)
            return {"id": "a1"}

        monkeypatch.setattr(fixed_asset_service, "register_asset", fake_register)
        cat, dep, acc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        asset_acc = uuid.uuid4()
        await main_mod.create_fixed_asset_endpoint(
            {
                "name": "Delivery Van",
                "purchase_cost": 4000000,
                "category_id": str(cat),
                "asset_account_id": str(asset_acc),
                "depreciation_expense_account_id": str(dep),
                "accumulated_depreciation_account_id": str(acc),
            },
            auth=_auth(),
        )
        assert seen["category_id"] == cat
        assert seen["asset_account_id"] == asset_acc
        assert seen["depreciation_expense_account_id"] == dep
        assert seen["accumulated_depreciation_account_id"] == acc
        assert seen["created_by"] is not None

    @pytest.mark.asyncio
    async def test_register_forwards_the_pinned_ledger_name(self, monkeypatch):
        """A caller that NAMES the asset ledger must not lose it.

        This endpoint used to drop ``asset_account_name`` silently, so a
        caller pinning 'Building - Model Town' (the ledger created first in
        the same run) fell back to the ambiguous keyword search and died with
        "No fixed-asset account could be determined for this acquisition"
        (production 2026-10-03).
        """
        from app import main as main_mod
        from app.services import fixed_asset_service

        seen: dict = {}

        async def fake_register(org_id, **kw):
            seen.update(kw)
            return {"id": "a1"}

        monkeypatch.setattr(fixed_asset_service, "register_asset", fake_register)
        await main_mod.create_fixed_asset_endpoint(
            {
                "name": "Building @ Model Town",
                "purchase_cost": 35_000_000,
                "asset_account_name": "Building - Model Town",
            },
            auth=_auth(),
        )
        assert seen["asset_account_name"] == "Building - Model Town"
        assert seen["asset_account_id"] is None

    @pytest.mark.asyncio
    async def test_non_uuid_ids_are_409_not_500(self):
        from app import main as main_mod
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await main_mod.create_fixed_asset_endpoint(
                {"name": "Van", "purchase_cost": 1, "category_id": "nope"},
                auth=_auth(),
            )
        assert exc.value.status_code == 409
        assert "Unknown id" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_depreciation_forwards_explicit_gl_accounts(self, monkeypatch):
        from app import main as main_mod
        from app.services import fixed_asset_service

        seen = {}

        async def fake_dep(org_id, **kw):
            seen.update(kw)
            return {"id": "j1"}

        monkeypatch.setattr(fixed_asset_service, "record_depreciation", fake_dep)
        dep, acc = uuid.uuid4(), uuid.uuid4()
        await main_mod.record_fixed_asset_depreciation_endpoint(
            ASSET,
            {
                "depreciation_amount": 100,
                "depreciation_expense_account_id": str(dep),
                "accumulated_depreciation_account_id": str(acc),
            },
            auth=_auth(),
        )
        assert seen["asset_id"] == str(ASSET)
        assert seen["depreciation_amount"] == 100.0
        assert seen["depreciation_expense_account_id"] == dep
        assert seen["accumulated_depreciation_account_id"] == acc



def _async(value):
    """An awaitable returning ``value`` (for monkeypatched async helpers)."""
    async def _inner(*args, **kwargs):
        return value
    return _inner()


class TestServiceResolvesDepreciationAccounts:
    """Gap 2 (depreciation refuses on missing GL accounts): registration now
    RESOLVES and STORES the two accounts when the chart has them, so the later
    charge finds them on the asset row — and never BLOCKS the acquisition
    when the chart does not."""

    MACHINERY = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
    DEPRECIATION = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    ACCUMULATED = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_registration_stores_resolved_accounts(self, monkeypatch):
        from app.repositories import fixed_asset_repository as repo
        from app.services import fixed_asset_service

        stored = {}

        async def fake_create_asset(**kw):
            stored.update(kw)
            return {"id": str(uuid.uuid4()), **kw}

        monkeypatch.setattr(repo, "create_asset", fake_create_asset)
        monkeypatch.setattr(
            fixed_asset_service, "_resolve_supplier",
            lambda *a, **k: _async(None),
        )
        monkeypatch.setattr(
            fixed_asset_service, "_resolve_settlement_account",
            lambda *a, **k: _async({"id": str(self.MACHINERY), "name": "Bank"}),
        )
        # the journal is the ENGINE's job — never under test here
        monkeypatch.setattr(
            fixed_asset_service, "_post_journal",
            lambda **k: _async({"id": str(uuid.uuid4())}),
        )
        # ... and so is the sub-ledger bookkeeping that follows it
        monkeypatch.setattr(
            repo, "update_asset_by_id", lambda *a, **k: _async(None)
        )
        monkeypatch.setattr(
            repo, "record_asset_transaction", lambda *a, **k: _async(None)
        )
        monkeypatch.setattr(
            fixed_asset_service.account_repo, "get_account",
            lambda *a, **k: _async({"id": str(self.MACHINERY),
                                    "name": "Machinery"}),
        )

        async def chart(org_id, *, account_type=None, limit=100):
            """Mirror the real type filter — resolution relies on it: an ASSET
            lookup must not see 'Depreciation Expense', else the keyword match
            is ambiguous and correctly returns None."""
            accounts = [
                {"id": str(self.MACHINERY), "name": "Machinery"},
                {"id": str(self.DEPRECIATION), "name": "Depreciation Expense"},
                {"id": str(self.ACCUMULATED), "name": "Accumulated Depreciation"},
            ]
            if account_type == "EXPENSE":
                return [a for a in accounts if a["name"] == "Depreciation Expense"]
            if account_type == "ASSET":
                return [a for a in accounts if a["name"] != "Depreciation Expense"]
            return accounts

        monkeypatch.setattr(
            fixed_asset_service.account_repo, "get_chart_of_accounts", chart
        )

        await fixed_asset_service.register_asset(
            ORG, name="Machine", purchase_cost=100.0,
            transaction_date="2026-01-01",
        )
        assert str(stored["gl_depreciation_expense_account_id"]) == str(
            self.DEPRECIATION
        )
        assert str(stored["gl_accumulated_depreciation_account_id"]) == str(
            self.ACCUMULATED
        )

    @pytest.mark.asyncio
    async def test_registration_still_succeeds_without_those_accounts(
        self, monkeypatch
    ):
        """Missing depreciation accounts must never block the ACQUISITION."""
        from app.repositories import fixed_asset_repository as repo
        from app.services import fixed_asset_service

        stored = {}

        async def fake_create_asset(**kw):
            stored.update(kw)
            return {"id": str(uuid.uuid4()), **kw}

        monkeypatch.setattr(repo, "create_asset", fake_create_asset)
        monkeypatch.setattr(
            fixed_asset_service, "_resolve_supplier",
            lambda *a, **k: _async(None),
        )
        monkeypatch.setattr(
            fixed_asset_service, "_resolve_settlement_account",
            lambda *a, **k: _async({"id": str(self.MACHINERY), "name": "Bank"}),
        )
        monkeypatch.setattr(
            fixed_asset_service, "_post_journal",
            lambda **k: _async({"id": str(uuid.uuid4())}),
        )
        monkeypatch.setattr(
            repo, "update_asset_by_id", lambda *a, **k: _async(None)
        )
        monkeypatch.setattr(
            repo, "record_asset_transaction", lambda *a, **k: _async(None)
        )
        # a chart WITHOUT depreciation accounts: the acquisition must proceed
        monkeypatch.setattr(
            fixed_asset_service.account_repo, "get_chart_of_accounts",
            lambda *a, **k: _async([{"id": str(self.MACHINERY),
                                     "name": "Machinery"}]),
        )
        monkeypatch.setattr(
            fixed_asset_service.account_repo, "get_account",
            lambda *a, **k: _async({"id": str(self.MACHINERY),
                                    "name": "Machinery"}),
        )

        await fixed_asset_service.register_asset(
            ORG, name="Machine", purchase_cost=100.0,
            transaction_date="2026-01-01",
        )
        assert stored["gl_depreciation_expense_account_id"] is None
        assert stored["gl_accumulated_depreciation_account_id"] is None

