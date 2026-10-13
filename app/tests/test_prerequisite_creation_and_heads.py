"""Prerequisite auto-creation + missing-head handling.

Two mechanisms under test:

1. ``agent._prerequisite_gap_for_plan`` — the gate that decides when a
   missing-ledger gap is a HARD PREREQUISITE (auto-created before the
   mutation, covered by the same approval) versus a CHOICE among existing
   ledgers (ask the user).  The INVENTORY-natured purchase family now
   joins ``register_fixed_asset``; the fixed-asset behaviour is pinned
   as a regression.

2. ``tools._create_account(parent_account_name=…)`` — the missing-HEAD
   prerequisite: an explicitly named section heading that does not exist
   is created first (grouping account of the child's type), an existing
   heading of the SAME type is reused, a type clash never parents, and
   an explicit ``parent_account_id`` always wins.

No live DB, no live provider — repository seams are monkeypatched.
"""

from __future__ import annotations

import asyncio
import uuid

from app.account_resolution import (
    AccountGap,
    ensure_create_account_first,
    gap_for_nature,
    inventory_gap_from_chart,
)
from app.agent import (
    _prerequisite_create_args,
    _prerequisite_gap_for_plan,
)
from app.models.schemas import ToolCall
from app.repositories import account_repository as account_repo
from app.tools import _create_account

_ORG = uuid.UUID("00000000-0000-0000-0000-00000000ca11")


def _inventory_gap(**kw):
    return gap_for_nature("Inventory", "INVENTORY", "inventory_nature")


def _plan(*tools):
    return [ToolCall(tool_name=t, arguments={}) for t in tools]


# ------------------------------------------------- prerequisite gap gate

def test_inventory_gap_carries_the_prerequisite_source():
    """The probe's gap must be recognisable by the prerequisite gate."""
    gap = inventory_gap_from_chart([
        {"name": "Cash", "account_type": "ASSET", "is_active": True},
        {"name": "Rent", "account_type": "EXPENSE", "is_active": True},
    ])
    assert gap is not None
    assert gap.source == "inventory_nature"
    assert gap.name == "Inventory"
    assert gap.account_type == "ASSET"


def test_purchase_family_auto_creates_the_missing_inventory_ledger():
    gap = _inventory_gap()
    assert gap is not None and not gap.candidates
    for tool in ("record_cash_purchase", "record_credit_purchase",
                 "record_purchase", "create_purchase_bill"):
        chosen = _prerequisite_gap_for_plan(
            gaps=[gap], planned=_plan(tool), intent=tool,
        )
        assert chosen is gap, tool


def test_inventory_gap_with_candidates_is_never_auto_created():
    """Existing ledgers to choose from -> ask, never duplicate the COA."""
    gap = _inventory_gap()
    gap.candidates = ["Stock in Trade", "Merchandise Inventory"]
    chosen = _prerequisite_gap_for_plan(
        gaps=[gap], planned=_plan("create_purchase_bill"),
        intent="record_cash_purchase",
    )
    assert chosen is None


def test_non_purchase_plan_never_carries_the_inventory_prerequisite():
    gap = _inventory_gap()
    chosen = _prerequisite_gap_for_plan(
        gaps=[gap], planned=_plan("create_expense"), intent="record_expense",
    )
    assert chosen is None


def test_fixed_asset_prerequisite_behaviour_is_preserved():
    gap = gap_for_nature("Building", "FIXED_ASSET", "fixed_asset_nature")
    assert gap is not None
    chosen = _prerequisite_gap_for_plan(
        gaps=[gap], planned=_plan("register_fixed_asset"),
        intent="register_fixed_asset",
    )
    assert chosen is gap
    gap.candidates = ["Vehicle - Car"]
    assert _prerequisite_gap_for_plan(
        gaps=[gap], planned=_plan("register_fixed_asset"),
        intent="register_fixed_asset",
    ) is None


def test_unrelated_gap_sources_are_asked_not_created():
    gap = AccountGap(name="Cleaning", source="explicit_reference")
    assert _prerequisite_gap_for_plan(
        gaps=[gap], planned=_plan("create_expense"), intent="record_expense",
    ) is None


def test_prerequisite_create_args_from_the_inventory_gap():
    """The gap already carries the determined shape — nothing invented."""
    args = asyncio.run(_prerequisite_create_args(_inventory_gap()))
    assert args is not None
    assert args["name"] == "Inventory"
    assert args["account_type"] == "ASSET"
    assert args["normal_balance"] == "DEBIT"


def test_injected_create_account_runs_first():
    calls = _plan("create_purchase_bill", "record_supplier_payment")
    merged = ensure_create_account_first(
        calls, arguments={"name": "Inventory", "account_type": "ASSET"}
    )
    assert [c.tool_name for c in merged] == [
        "create_account", "create_purchase_bill", "record_supplier_payment",
    ]


# -------------------------------------------------- create_account heads

def _repo_spy(monkeypatch, *, existing_heading=None):
    """Monkeypatch the repository seams the handler uses; record calls."""
    calls = {"search": [], "code": [], "create": []}

    async def _search(organization_id, *, query, limit=50):
        calls["search"].append(query)
        if existing_heading is not None and query == existing_heading["name"]:
            return [existing_heading]
        return []

    async def _next_code(organization_id, requested_code, **kw):
        calls["code"].append(requested_code)
        return requested_code

    async def _create(**kw):
        new_id = str(uuid.uuid4())
        # Record the INPUT kwargs plus the id the fake RETURNED (the real
        # repository returns the inserted row; the handler reads its id).
        calls["create"].append({**dict(kw), "_returned_id": new_id})
        return {"id": new_id, **kw}

    monkeypatch.setattr(account_repo, "search_accounts", _search)
    monkeypatch.setattr(account_repo, "next_available_code", _next_code)
    monkeypatch.setattr(account_repo, "create_account", _create)
    return calls


def test_missing_heading_is_created_then_the_child_parented(monkeypatch):
    calls = _repo_spy(monkeypatch, existing_heading=None)
    result = asyncio.run(_create_account(
        _ORG,
        name="Cleaning Supplies",
        code="6510",
        account_type="EXPENSE",
        normal_balance="DEBIT",
        parent_account_name="Office Sundries",
    ))
    assert result.success is True
    # heading FIRST, child second
    assert [c["name"] for c in calls["create"]] == [
        "Office Sundries", "Cleaning Supplies",
    ]
    heading = calls["create"][0]
    assert heading["account_type"] == "EXPENSE"  # same type as the child
    child = calls["create"][1]
    assert child["parent_account_id"] == heading["_returned_id"]  # NOT None
    # the extra kw never reaches the repository
    assert "parent_account_name" not in child
    assert result.data["parent_heading"]["created"] is True


def test_existing_heading_of_the_same_type_is_reused(monkeypatch):
    heading = {
        "id": str(uuid.uuid4()), "code": "6500",
        "name": "Office & Administration", "account_type": "EXPENSE",
        "is_active": True,
    }
    calls = _repo_spy(monkeypatch, existing_heading=heading)
    result = asyncio.run(_create_account(
        _ORG,
        name="Pantry Snacks",
        code="6560",
        account_type="EXPENSE",
        normal_balance="DEBIT",
        parent_account_name="Office & Administration",
    ))
    assert result.success is True
    assert len(calls["create"]) == 1  # ONLY the child — no heading created
    assert calls["create"][0]["parent_account_id"] == heading["id"]
    assert result.data["parent_heading"]["created"] is False


def test_type_clash_never_parents_the_child(monkeypatch):
    """An expense must never hang under an ASSET heading (2026-09-30)."""
    clash = {
        "id": str(uuid.uuid4()), "code": "1000",
        "name": "Current Assets", "account_type": "ASSET",
        "is_active": True,
    }
    calls = _repo_spy(monkeypatch, existing_heading=clash)
    result = asyncio.run(_create_account(
        _ORG,
        name="Marketing Retainer Fee",
        code="6545",
        account_type="EXPENSE",
        normal_balance="DEBIT",
        parent_account_name="Current Assets",
    ))
    assert result.success is True
    assert len(calls["create"]) == 1  # the child only
    assert "parent_account_id" not in calls["create"][0]
    assert "parent_heading" not in result.data


def test_explicit_parent_account_id_always_wins(monkeypatch):
    calls = _repo_spy(monkeypatch, existing_heading=None)
    fixed_parent = str(uuid.uuid4())
    result = asyncio.run(_create_account(
        _ORG,
        name="Security Deposit",
        code="1290",
        account_type="ASSET",
        normal_balance="DEBIT",
        parent_account_id=fixed_parent,
        parent_account_name="A Name That Must Be Ignored",
    ))
    assert result.success is True
    assert len(calls["create"]) == 1
    assert calls["create"][0]["parent_account_id"] == fixed_parent
    assert "parent_heading" not in result.data
    # the ignored name was popped — never forwarded to the repository
    assert "parent_account_name" not in calls["create"][0]


def test_child_name_reuse_still_short_circuits(monkeypatch):
    """The search-before-create (P2) branch is untouched by the parent
    work: an exact child-name match is REUSED before anything else."""
    existing = {
        "id": str(uuid.uuid4()), "code": "6210",
        "name": "Rent", "account_type": "EXPENSE", "is_active": True,
    }

    async def _search(organization_id, *, query, limit=50):
        return [existing] if query == "Rent" else []

    monkeypatch.setattr(account_repo, "search_accounts", _search)
    result = asyncio.run(_create_account(
        _ORG,
        name="Rent",
        code="6210",
        account_type="EXPENSE",
        normal_balance="DEBIT",
        parent_account_name="Premises",
    ))
    assert result.success is True
    assert result.data.get("reused_existing") is True
