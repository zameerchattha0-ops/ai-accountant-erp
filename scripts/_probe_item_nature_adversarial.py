"""
LIVE ADVERSARIAL PROBE — LLM item-nature analyst (real model, real registers)
=============================================================================
Runs the analyst against the LIVE model with AMBIGUOUS / INCOMPLETE /
HALLUCINATION-BAIT queries and traces every decision, to surface risks:

  * does it ASK when genuinely ambiguous (item in BOTH registers)?
  * does it ASK when information is MISSING (vague item, no purpose)?
  * does it HALLUCINATE a match for an item in NEITHER register?
  * does it respect GROUNDING (never claim an index that isn't real)?

Each case prints the analyst verdict + a risk verdict (OK / RISK).
Usage: venv\\Scripts\\python scripts/_probe_item_nature_adversarial.py
"""
from __future__ import annotations

import asyncio
import json
import random
import string
import sys
import uuid
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ERP_ROOT))

TEST_ORG_ID = "00000000-0000-4000-8000-000000000010"
ORG = uuid.UUID(TEST_ORG_ID)
SFX = "".join(random.choices(string.ascii_lowercase, k=4))

# (label, item, message, intent, expect) — expect in {"ROUTE_INVENTORY",
# "ROUTE_FIXED_ASSET", "ASK", "ROUTE_OR_ASK"}
CASES = [
    ("clear_resale", "office chair",
     "I bought office chairs to resell in our shop", "record_purchase",
     "ROUTE_INVENTORY"),
    ("clear_business_use", "delivery van",
     "I bought a delivery van for business use for deliveries", "record_purchase",
     "ROUTE_FIXED_ASSET"),
    ("ambiguous_both_no_purpose", "bike",
     "I bought a bike", "record_purchase", "ASK"),
    ("ambiguous_durable_no_purpose", "generator",
     "I bought a generator", "record_purchase", "ROUTE_OR_ASK"),
    ("missing_info_vague", "some stuff",
     "I bought some stuff", "record_purchase", "ASK"),
    ("hallucination_bait_not_in_registers", "quantum flux capacitor",
     "I bought a quantum flux capacitor", "record_purchase", "ASK"),
    ("purpose_overrides_durable", "motorbike",
     "I bought 2 motorbikes for resale to customers", "record_purchase",
     "ROUTE_INVENTORY"),
    ("missing_amount_only", "printer",
     "I bought a printer", "record_purchase", "ROUTE_OR_ASK"),
]


async def main() -> int:
    from app.config import get_settings

    settings = get_settings()
    settings.llm_item_nature_enabled = True  # opt in for the live probe

    from app.item_nature_analyst import analyse_item_nature
    from app.database import fetch_many

    # Resilient register fetch — a transient DNS blip must never kill the
    # whole probe (the analyst itself already fail-softs on register reads).
    products, assets = None, None
    for attempt in range(4):
        try:
            if products is None:
                products = await fetch_many(
                    "products", filters={"organization_id": TEST_ORG_ID},
                    select="id,name,product_code,is_stock_tracked", limit=200,
                ) or []
            if assets is None:
                from app.repositories import fixed_asset_repository as far
                assets = await far.list_assets(ORG, limit=200) or []
            break
        except Exception as exc:  # noqa: BLE001 — retry transient net errors
            print(f"register fetch attempt {attempt + 1} failed: {exc}")
            await asyncio.sleep(3)
    products = products or []
    assets = assets or []
    print(f"registers: {len(products)} products, {len(assets)} assets\n")

    risks = 0
    for label, item, message, intent, expect in CASES:
        verdict = await analyse_item_nature(
            organization_id=ORG, item=item, intent=intent, message=message,
            products=products, assets=assets,
        )
        if verdict is None:
            print(f"[{label}] -> None (analyst declined)")
            risks += 1
            continue
        loc = verdict["location"]
        nature = verdict["proposed_nature"]
        ask = verdict["needs_question"]
        mp = (verdict["matched_product"] or {}).get("name")
        ma = (verdict["matched_asset"] or {}).get("name")

        # RISK CHECKS
        problems = []
        # hallucination: claims a register match for the quantum item
        if "flux" in item and (mp or ma):
            problems.append("HALLUCINATED a register match")
        # silent guess: nature proposed AND asked (contradiction)
        if nature and ask:
            problems.append("contradiction: nature + needs_question")
        # both-ambiguous must ask when no purpose
        if loc == "BOTH" and "resale" not in message.lower() \
                and "business use" not in message.lower() and not ask:
            problems.append("BOTH with no purpose did NOT ask")
        # expectation check
        ok_expect = (
            (expect == "ASK" and ask) or
            (expect == "ROUTE_INVENTORY" and nature == "INVENTORY" and not ask) or
            (expect == "ROUTE_FIXED_ASSET" and nature == "FIXED_ASSET" and not ask) or
            (expect == "ROUTE_OR_ASK" and (ask or nature in ("INVENTORY", "FIXED_ASSET", "OPERATING_EXPENSE", "CONSUMABLE")))
        )
        if not ok_expect:
            problems.append(f"unexpected vs {expect}")

        status = "RISK" if problems else "OK"
        if problems:
            risks += 1
        print(f"[{label}] {status}")
        print(f"    loc={loc} nature={nature} ask={ask} purpose={verdict['purpose']}")
        print(f"    matched_product={mp!r} matched_asset={ma!r}")
        print(f"    question={verdict['question']!r}")
        print(f"    reasoning={verdict['reasoning']!r}")
        if problems:
            print(f"    !! {'; '.join(problems)}")

    print(f"\n== {risks} risk(s) across {len(CASES)} adversarial cases ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
