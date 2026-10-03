"""Plan-time fixed-asset ledger intelligence — CHECK FIRST, propose only if missing.

Production 2026-10-03: "Record a purchase of Building @ Model Town for
35,000,000 on Cash" died with "No fixed-asset account could be determined"
because the plan carried NO account.  These tests pin the three decisions
(reuse / segregate-create / ask) and the EXACTLY-ONE pin contract.
"""
from __future__ import annotations

import uuid
from typing import Optional

import pytest

from app.account_resolution import (
    decide_fixed_asset_ledger,
    pin_planned_asset_accounts,
    segregated_asset_ledger_name,
)
from app.models.schemas import ToolCall

ORG = uuid.uuid4()


def _acct(name: str, code: str = "1500", parent: Optional[str] = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "code": code,
        "account_type": "ASSET",
        # Party sub-ledgers hang under their control account; a PPE ledger may
        # hang under a PPE heading — or nothing at all.
        "parent_account_id": parent,
    }


def _patch_chart(monkeypatch, chart: list) -> None:
    from app.repositories import account_repository as a_repo

    async def fake_chart(org_id, *, account_type="ASSET", limit=100, **kw):
        return list(chart)

    monkeypatch.setattr(a_repo, "get_chart_of_accounts", fake_chart)


# ---------------------------------------------------------------------------
# Segregating names
# ---------------------------------------------------------------------------
class TestSegregatedLedgerName:
    def test_building_at_location(self):
        assert (
            segregated_asset_ledger_name("Building @ Model Town", "Buildings & Land")
            == "Building - Model Town"
        )

    def test_building_dash_location(self):
        assert (
            segregated_asset_ledger_name("Building - Johar Town", "Buildings & Land")
            == "Building - Johar Town"
        )

    def test_no_identifier_falls_back_to_the_category(self):
        # no separator → the caller uses the plain category ledger
        assert segregated_asset_ledger_name("warehouse", "Buildings & Land") is None

    def test_head_must_match_the_category(self):
        # "Wonder - Model Town" is not a Buildings head — never a Buildings ledger
        assert (
            segregated_asset_ledger_name("Wonder - Model Town", "Buildings & Land")
            is None
        )

    def test_intra_word_hyphen_is_not_a_separator(self):
        assert (
            segregated_asset_ledger_name("Sialkot-Multan Road", "Buildings & Land")
            is None
        )


# ---------------------------------------------------------------------------
# The decision: reuse → segregate → create → ask
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestLedgerDecision:
    async def test_existing_fitting_ledger_is_reused_never_duplicated(self, monkeypatch):
        furniture = _acct("Furniture & Fixtures")
        _patch_chart(monkeypatch, [
            _acct("Computer Equipment"), _acct("Vehicle - Car"), furniture,
        ])
        decision = await decide_fixed_asset_ledger(ORG, asset_name="office chairs")
        assert decision.mode == "reuse"
        assert decision.account_id == furniture["id"]
        assert decision.name == "Furniture & Fixtures"

    async def test_building_gets_its_own_segregated_ledger(self, monkeypatch):
        # The exact production chart: two PPE ledgers exist, but NEITHER is a
        # building — a building is unique, so its own ledger is CREATED.
        _patch_chart(monkeypatch, [_acct("Computer Equipment"), _acct("Vehicle - Car")])
        decision = await decide_fixed_asset_ledger(
            ORG, asset_name="Building @ Model Town"
        )
        assert decision.mode == "create"
        assert decision.name == "Building - Model Town"

    async def test_repeat_for_the_same_building_reuses_its_own_ledger(self, monkeypatch):
        own = _acct("Building - Model Town", code="1530")
        _patch_chart(monkeypatch, [_acct("Computer Equipment"), own])
        decision = await decide_fixed_asset_ledger(
            ORG, asset_name="Building @ Model Town"
        )
        assert decision.mode == "reuse"
        assert decision.account_id == own["id"]

    async def test_another_building_gets_a_different_ledger(self, monkeypatch):
        _patch_chart(monkeypatch, [_acct("Building - Model Town")])
        decision = await decide_fixed_asset_ledger(
            ORG, asset_name="Building - Johar Town"
        )
        assert decision.mode == "create"
        assert decision.name == "Building - Johar Town"

    async def test_identifier_less_property_uses_the_category_ledger(self, monkeypatch):
        _patch_chart(monkeypatch, [_acct("Computer Equipment"), _acct("Vehicle - Car")])
        decision = await decide_fixed_asset_ledger(ORG, asset_name="warehouse")
        assert decision.mode == "create"
        assert decision.name == "Buildings & Land"

    async def test_genuine_tie_between_two_fitting_ledgers_asks(self, monkeypatch):
        _patch_chart(monkeypatch, [_acct("Cars"), _acct("Motor Vehicles")])
        decision = await decide_fixed_asset_ledger(ORG, asset_name="Toyota Hilux")
        assert decision.mode == "ask"
        assert decision.name == "Vehicles"
        assert sorted(decision.candidates) == ["Cars", "Motor Vehicles"]

    async def test_unknown_item_proposes_the_category_not_a_guess(self, monkeypatch):
        _patch_chart(monkeypatch, [_acct("Computer Equipment")])
        decision = await decide_fixed_asset_ledger(ORG, asset_name="zzz gizmo")
        assert decision.mode == "create"
        # never a bucket matched against Cash/Bank — and never "Cash"
        assert decision.name == "Other Equipment & Fixtures"


# ---------------------------------------------------------------------------
# The pin: EXACTLY ONE of asset_account_id | asset_account_name
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestPlanPinning:
    async def test_reuses_an_existing_ledger_by_id(self, monkeypatch):
        furniture = _acct("Furniture & Fixtures")
        _patch_chart(monkeypatch, [furniture])
        call = ToolCall(
            tool_name="register_fixed_asset",
            arguments={"name": "office chairs", "purchase_cost": 5000.0},
        )
        gap = await pin_planned_asset_accounts(ORG, tool_calls=[call])
        assert gap is None
        assert call.arguments["asset_account_id"] == furniture["id"]
        assert "asset_account_name" not in call.arguments

    async def test_new_building_ledger_is_pinned_by_name_with_a_create_gap(self, monkeypatch):
        _patch_chart(monkeypatch, [_acct("Computer Equipment"), _acct("Vehicle - Car")])
        call = ToolCall(
            tool_name="register_fixed_asset",
            arguments={"name": "Building @ Model Town", "purchase_cost": 35_000_000.0},
        )
        gap = await pin_planned_asset_accounts(ORG, tool_calls=[call])
        assert call.arguments["asset_account_name"] == "Building - Model Town"
        assert "asset_account_id" not in call.arguments
        # the prerequisite flow must CREATE it first (no candidates → create,
        # never ask — no fitting ledger exists for a building)
        assert gap is not None
        assert gap.name == "Building - Model Town"
        assert gap.source == "fixed_asset_nature"
        assert gap.candidates == []

    async def test_an_already_pinned_call_is_left_alone(self, monkeypatch):
        _patch_chart(monkeypatch, [_acct("Computer Equipment")])
        call = ToolCall(
            tool_name="register_fixed_asset",
            arguments={"name": "Building @ Model Town", "asset_account_id": "pinned"},
        )
        gap = await pin_planned_asset_accounts(ORG, tool_calls=[call])
        assert gap is None
        assert call.arguments["asset_account_id"] == "pinned"

    async def test_the_users_confirmed_account_answer_wins(self, monkeypatch):
        _patch_chart(monkeypatch, [_acct("Computer Equipment")])
        call = ToolCall(
            tool_name="register_fixed_asset",
            arguments={"name": "Building @ Model Town"},
        )
        gap = await pin_planned_asset_accounts(
            ORG, tool_calls=[call],
            entities={"create_account": "Investment Property - Model Town"},
        )
        assert gap is None
        assert (
            call.arguments["asset_account_name"]
            == "Investment Property - Model Town"
        )

    async def test_non_asset_calls_are_never_touched(self, monkeypatch):
        _patch_chart(monkeypatch, [])
        call = ToolCall(tool_name="create_expense", arguments={"amount": 10.0})
        assert await pin_planned_asset_accounts(ORG, tool_calls=[call]) is None
        assert call.arguments == {"amount": 10.0}


# ---------------------------------------------------------------------------
# The service honours the pinned name (and says WHICH ledger is missing)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestServiceNamePin:
    async def test_exact_name_match_is_case_insensitive(self, monkeypatch):
        from app.services import fixed_asset_service as fas

        target = _acct("Building - Model Town")

        async def fake_chart(org_id, *, account_type="ASSET", limit=100, **kw):
            return [target, _acct("Computer Equipment")]

        monkeypatch.setattr(fas.account_repo, "get_chart_of_accounts", fake_chart)
        found = await fas._resolve_gl_account(
            ORG,
            account_type="ASSET",
            keywords=fas._ASSET_ACCOUNT_KEYWORDS,
            explicit_id=None,
            explicit_name="building - model town",
        )
        assert found and found["name"] == "Building - Model Town"

    async def test_missing_named_ledger_resolves_to_none_not_a_keyword_match(self, monkeypatch):
        from app.services import fixed_asset_service as fas

        async def fake_chart(org_id, *, account_type="ASSET", limit=100, **kw):
            return [_acct("Computer Equipment"), _acct("Vehicle - Car")]

        monkeypatch.setattr(fas.account_repo, "get_chart_of_accounts", fake_chart)
        found = await fas._resolve_gl_account(
            ORG,
            account_type="ASSET",
            keywords=fas._ASSET_ACCOUNT_KEYWORDS,
            explicit_id=None,
            explicit_name="Building - Model Town",
        )
        assert found is None  # register_asset then names THIS ledger in its error


# ---------------------------------------------------------------------------
# The prompt: controlled intelligence, restricted output
# ---------------------------------------------------------------------------
def test_rule_23_tells_the_model_check_first_then_propose_only_if_missing():
    from app.prompts import build_system_instructions

    text = build_system_instructions()
    assert "CHECK FIRST" in text
    assert "existence check only" in text
    assert "Building - Model Town" in text
    assert "EXACTLY ONE of asset_account_id" in text


# ---------------------------------------------------------------------------
# PRODUCTION REGRESSION 2026-10-03 (session 169a88e0) — non-PPE ASSET rows are
# NEVER ledger candidates.
#
# "We Buy Today Honda Civic for 3,450,000 on cash today" died with
# "No fixed-asset account could be determined for this acquisition."
# because the fits scan classified EVERY ASSET row: the AR control "Accounts
# Receivable" and the customer sub-ledger "alpha associates" landed on
# "Vehicles" via category_for_item's nearest-vocabulary fallback, and with the
# real "Vehicle - Car" also matching the decision became a phantom
# mode="ask" — so the plan carried NO ledger and the acquisition could not post.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestNonPpeLedgersAreNeverCandidates:
    async def test_party_subledgers_do_not_fake_a_vehicle_tie(self, monkeypatch):
        ar = _acct("Accounts Receivable", code="1100")
        _patch_chart(monkeypatch, [
            ar,
            _acct("alpha associates", code="1100-0007", parent=ar["id"]),
            _acct("ABC Furnitures", code="1100-0005", parent=ar["id"]),
            _acct("Computer Equipment", code="1500"),
            _acct("Vehicle - Car", code="1520"),
        ])
        decision = await decide_fixed_asset_ledger(
            ORG, asset_name="Today Honda Civic"
        )
        # exactly ONE fitting ledger → reuse it; never an ask
        assert decision.mode == "reuse"
        assert decision.name == "Vehicle - Car"
        assert decision.candidates == []

    async def test_a_customer_named_like_furniture_is_not_the_furniture_ledger(
        self, monkeypatch
    ):
        ar = _acct("Accounts Receivable", code="1100")
        _patch_chart(monkeypatch, [
            ar, _acct("ABC Furnitures", code="1100-0005", parent=ar["id"]),
        ])
        decision = await decide_fixed_asset_ledger(ORG, asset_name="office chairs")
        # a receivable sub-ledger must never receive an asset acquisition
        assert decision.mode == "create"
        assert decision.name == "Furniture & Fixtures"

    async def test_a_real_ppe_ledger_under_a_ppe_heading_is_still_reused(
        self, monkeypatch
    ):
        heading = _acct("Property, Plant & Equipment", code="1500")
        furniture = _acct("Furniture & Fixtures", code="1530", parent=heading["id"])
        _patch_chart(monkeypatch, [heading, furniture])
        decision = await decide_fixed_asset_ledger(ORG, asset_name="office chairs")
        assert decision.mode == "reuse"
        assert decision.account_id == furniture["id"]

    async def test_the_production_request_pins_the_vehicle_ledger(self, monkeypatch):
        ar = _acct("Accounts Receivable", code="1100")
        vehicle = _acct("Vehicle - Car", code="1520")
        _patch_chart(monkeypatch, [
            ar,
            _acct("alpha associates", code="1100-0007", parent=ar["id"]),
            _acct("Computer Equipment", code="1500"),
            vehicle,
        ])
        call = ToolCall(
            tool_name="register_fixed_asset",
            arguments={"name": "Today Honda Civic", "purchase_cost": 3_450_000.0},
        )
        gap = await pin_planned_asset_accounts(ORG, tool_calls=[call])
        assert gap is None                       # the plan IS executable
        assert call.arguments["asset_account_id"] == vehicle["id"]
        assert "asset_account_name" not in call.arguments


# ---------------------------------------------------------------------------
# The SERVICE's keyword fallback excludes non-PPE accounts too, so one real
# PPE ledger still resolves uniquely for callers that omit the account
# (the REST endpoint relies on exactly this).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestServiceKeywordSearchExcludesNonPpe:
    async def _service(self, monkeypatch):
        from app.services import fixed_asset_service as fas

        ar = _acct("Accounts Receivable", code="1100")
        rows = [
            ar,
            _acct("ABC Furnitures", code="1100-0005", parent=ar["id"]),
            _acct("Vehicle - Car", code="1520"),
        ]

        async def fake_chart(org_id, *, account_type="ASSET", limit=100, **kw):
            return list(rows)

        monkeypatch.setattr(fas.account_repo, "get_chart_of_accounts", fake_chart)
        return fas

    async def test_without_the_flag_the_customer_ledger_still_poisons_it(
        self, monkeypatch
    ):
        fas = await self._service(monkeypatch)
        found = await fas._resolve_gl_account(
            ORG,
            account_type="ASSET",
            keywords=fas._ASSET_ACCOUNT_KEYWORDS,
            explicit_id=None,
            exclude_keywords=("accumulated depreciation",),
        )
        assert found is None  # ambiguous: 'ABC Furnitures' + 'Vehicle - Car'

    async def test_with_the_flag_the_one_real_ppe_ledger_resolves(self, monkeypatch):
        fas = await self._service(monkeypatch)
        found = await fas._resolve_gl_account(
            ORG,
            account_type="ASSET",
            keywords=fas._ASSET_ACCOUNT_KEYWORDS,
            explicit_id=None,
            exclude_keywords=("accumulated depreciation",),
            exclude_non_ppe=True,
        )
        assert found is not None and found["name"] == "Vehicle - Car"

    async def test_a_named_non_ppe_ledger_is_refused_with_a_precise_reason(
        self, monkeypatch
    ):
        """'missing' would be a lie: the ledger exists, it just cannot hold
        an acquisition.  Say which one it is."""
        fas = await self._service(monkeypatch)
        with pytest.raises(ValueError) as excinfo:
            await fas._resolve_gl_account(
                ORG,
                account_type="ASSET",
                keywords=fas._ASSET_ACCOUNT_KEYWORDS,
                explicit_id=None,
                explicit_name="ABC Furnitures",
                exclude_non_ppe=True,
            )
        message = str(excinfo.value)
        assert "ABC Furnitures" in message
        assert "not a property, plant & equipment ledger" in message

