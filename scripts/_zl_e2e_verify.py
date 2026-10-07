"""End-to-end: the Zameer Labs scenario now resolves through the canonical loop."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app.account_resolution import preflight_account_gaps, question_for_gap
from app.planner import _merge_clarification_answers, plan

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

# The Zameer Labs chart (asset side) — no inventory ledger.
CHART = [
    {"name": "Bank", "account_type": "ASSET"},
    {"name": "Cash", "account_type": "ASSET"},
    {"name": "Accounts Receivable", "account_type": "ASSET"},
    {"name": "Prepaid Expenses", "account_type": "ASSET"},
    {"name": "Computer Equipment", "account_type": "ASSET"},
    {"name": "Vehicle - Car", "account_type": "ASSET"},
]


async def main() -> None:
    # STEP 1 — the deterministic preflight NOW proposes the gap
    # (monkeypatching the repository seam the way tests do).
    from app.repositories import account_repository as acct_repo

    async def _chart(organization_id, **kwargs):
        return CHART

    acct_repo.get_chart_of_accounts = _chart
    gaps = await preflight_account_gaps(
        ORG,
        tool_calls=[],
        entities={"transaction_nature": "INVENTORY"},
        intent="record_cash_purchase",
    )
    print(f"1) preflight gaps       -> {[g.name for g in gaps]}")
    assert gaps, "preflight must propose the inventory gap"

    # STEP 2 — the canonical question satisfies the merge contract
    question = question_for_gap(gaps[0])
    print(f"2) canonical question   -> {question[:110]}...")

    # STEP 3 — the owner approves
    merged = _merge_clarification_answers(
        {"transaction_nature": "INVENTORY"},
        [{"question": question, "answer": "Yes, create it"}],
    )
    print(f"3) merge create_account -> {merged.get('create_account')!r}")
    assert merged.get("create_account") == "Inventory"

    # STEP 4 — the planner OFFERS the tool
    p = plan(
        "We Purchase Two Bikes, for resale on cash today",
        clarification_history=[{"question": question, "answer": "Yes, create it"}],
    )
    print(f"4) plan offers          -> create_account in tools: "
          f"{'create_account' in p.potential_tools}")
    assert "create_account" in p.potential_tools

    # STEP 5 — the LEGACY session history (the free-form question that was
    # already stored) folds too, so the existing conversation recovers.
    legacy = _merge_clarification_answers(
        {"transaction_nature": "INVENTORY"},
        [{
            "question": "1. Should I create a new inventory account to record "
                        "this purchase correctly? Yes or no.\n"
                        "2. Or use an existing account?",
            "answer": "1) Yes, Create Inventory Account\n2) No",
        }],
    )
    print(f"5) legacy history folds -> {legacy.get('create_account')!r}")
    assert legacy.get("create_account") == "Inventory"

    print("\nALL STEPS OK — the COA-creation agent is reachable end to end.")


asyncio.run(main())
