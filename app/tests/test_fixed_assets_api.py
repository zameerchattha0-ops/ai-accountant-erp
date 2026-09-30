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
                "useful_life_years": "5",
                "salvage_value": "0",
            },
            auth=auth,
        )

        assert out["item"]["asset_code"] == "FA-000001"
        assert captured["org"] == ORG
        assert captured["payment_method"] == "CASH"
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

