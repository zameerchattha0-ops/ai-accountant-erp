"""Live End-to-End Probe: Sale of a Stock-Tracked Catalogue Item.

Tests:
1. General low-information query without specific intent/detail.
2. Turn-by-turn routing, clarification questionnaire, and entity grounding.
3. Revenue journal posting (Dr Cash / Cr Revenue).
4. Perpetual Inventory COGS journal posting (Dr Cost of Sales / Cr Inventory).
5. Catalogue units on hand reduction (quantity_on_hand decrement).
"""
import asyncio
import sys
import uuid
import time
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ERP_ROOT))

import jwt as pyjwt
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.database import get_service_client
from app.services import inventory_service

TEST_ORG_ID = "00000000-0000-4000-8000-000000000010"
TEST_USER_ID = "00000000-0000-4000-8000-000000000001"
TARGET_PRODUCT_NAME = "Batt Gadget Jfetb"
SALE_QTY = 2.0
SALE_PRICE_TOTAL = 30000.0

def load_secret():
    env = {}
    for line in (ERP_ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env["JWT_SECRET"]

def make_token(secret):
    now = int(time.time())
    return pyjwt.encode({
        "sub": TEST_USER_ID, "role": "authenticated", "aud": "authenticated",
        "email": "test.owner@erptest.local", "iat": now, "exp": now + 7200,
        "session_id": str(uuid.uuid4()),
    }, secret, algorithm="HS256")

async def get_product_state(org_id: uuid.UUID, product_name: str):
    sb = get_service_client()
    prod_row = sb.table("products").select("*").eq("organization_id", str(org_id)).eq("name", product_name).execute().data
    if not prod_row:
        raise RuntimeError(f"Product '{product_name}' not found in DB!")
    product = prod_row[0]
    pid = uuid.UUID(product["id"])
    positions = await inventory_service.positions_for_products(org_id, product_ids=[pid])
    pos = positions.get(str(pid)) or {}
    return {
        "id": pid,
        "name": product["name"],
        "code": product.get("product_code"),
        "is_stock_tracked": product.get("is_stock_tracked"),
        "quantity_on_hand": float(pos.get("quantity_on_hand") or 0.0),
        "average_cost": float(pos.get("average_cost") or product.get("cost_price") or 0.0),
        "total_value": float(pos.get("total_value") or 0.0),
    }

async def run_probe():
    secret = load_secret()
    token = make_token(secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    org_id = uuid.UUID(TEST_ORG_ID)

    print("=======================================================", flush=True)
    print("LIVE SALE & PERPETUAL INVENTORY (COGS) PROBE", flush=True)
    print("=======================================================", flush=True)

    # 1. Capture baseline state
    before = await get_product_state(org_id, TARGET_PRODUCT_NAME)
    print(f"\n[BASELINE STATE] Product: {before['name']} ({before['code']})", flush=True)
    print(f"  * Stock Tracked:        {before['is_stock_tracked']}", flush=True)
    print(f"  * Quantity on Hand:     {before['quantity_on_hand']} units", flush=True)
    print(f"  * Average Unit Cost:    {before['average_cost']:,.2f} PKR", flush=True)
    print(f"  * Total Inventory Value: {before['total_value']:,.2f} PKR", flush=True)
    assert before["quantity_on_hand"] >= SALE_QTY, f"Insufficient stock: {before['quantity_on_hand']} < {SALE_QTY}"

    # 2. General, low-information user query
    user_prompt = f"sold {int(SALE_QTY)} {TARGET_PRODUCT_NAME} {int(SALE_PRICE_TOTAL)}"
    print(f"\n[TURN 1] User Prompt: \"{user_prompt}\"", flush=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=90.0) as client:
        r1 = await client.post("/api/ai/execute", json={"message": user_prompt}, headers=headers)
        body = r1.json()
        current_status = body.get("status")
        text = body.get("question") or body.get("summary") or ""
        exec_id = body.get("execution_id")

        print(f"  -> Agent Status: {current_status}", flush=True)
        print(f"  -> Agent Output: {text}", flush=True)

        turns = 1

        while current_status in ("AWAITING_CLARIFICATION", "AWAITING_CONFIRMATION") and turns < 5:
            turns += 1
            if current_status == "AWAITING_CLARIFICATION":
                t_lower = text.lower()
                if "revenue ledger" in t_lower or "dedicated ledger" in t_lower:
                    ans = "yes"
                elif "customer" in t_lower or "who" in t_lower:
                    ans = "cash customer, today"
                else:
                    ans = "cash, today"

                print(f"\n[TURN {turns}] Answering Clarification: \"{ans}\"", flush=True)
                r = await client.post("/api/ai/clarify", json={"session_id": str(exec_id), "answer": ans}, headers=headers)
            elif current_status == "AWAITING_CONFIRMATION":
                print(f"\n[TURN {turns}] Confirming Plan: approved=True", flush=True)
                r = await client.post("/api/ai/confirm", json={"session_id": str(exec_id), "approved": True}, headers=headers)

            body = r.json()
            current_status = body.get("status")
            text = body.get("question") or body.get("summary") or ""
            # IMPORTANT: session execution id must be updated for next turn
            exec_id = body.get("execution_id") or exec_id
            print(f"  -> Agent Status: {current_status}", flush=True)
            print(f"  -> Agent Output: {text}", flush=True)
            if current_status == "COMPLETED":
                break

    print("\n=======================================================", flush=True)
    print("VERIFICATION & FORENSIC ANALYSIS", flush=True)
    print("=======================================================", flush=True)

    # 3. Post-sale state inspection
    after = await get_product_state(org_id, TARGET_PRODUCT_NAME)
    qty_diff = before["quantity_on_hand"] - after["quantity_on_hand"]
    print(f"\n[INVENTORY UNITS AUDIT]")
    print(f"  * Quantity Before: {before['quantity_on_hand']} units")
    print(f"  * Quantity After:  {after['quantity_on_hand']} units")
    print(f"  * Units Decreased: {qty_diff} units (Expected: {SALE_QTY})")

    # 4. Check Journals in DB
    sb = get_service_client()
    entries = sb.table("journal_entries").select("*").eq("organization_id", str(org_id)).order("created_at", desc=True).limit(6).execute().data
    print(f"\n[LATEST JOURNAL ENTRIES POSTED ({len(entries)})]")
    
    cogs_entry = None
    revenue_entry = None
    for entry in entries:
        eid = entry["id"]
        lines = sb.table("journal_lines").select("*, accounts(name, account_type)").eq("entry_id", eid).execute().data
        line_desc = " | ".join(f"{'Dr' if float(l.get('debit') or 0) > 0 else 'Cr'} {l.get('accounts', {}).get('name')} {float(l.get('debit') or 0) or float(l.get('credit') or 0):,.2f}" for l in lines)
        print(f"  * Entry {entry.get('entry_number')} ({entry.get('status')}): {entry.get('description')}")
        print(f"    Lines: {line_desc}")
        
        # Check if COGS entry
        if any("cost of sales" in (l.get('accounts', {}).get('name') or '').lower() or "cogs" in (l.get('accounts', {}).get('name') or '').lower() for l in lines):
            if cogs_entry is None:
                cogs_entry = {"entry": entry, "lines": lines}
        # Check if Revenue entry
        if any("revenue" in (l.get('accounts', {}).get('name') or '').lower() or "sales" in (l.get('accounts', {}).get('name') or '').lower() for l in lines):
            if any(float(l.get('credit') or 0) == SALE_PRICE_TOTAL for l in lines):
                if revenue_entry is None:
                    revenue_entry = {"entry": entry, "lines": lines}

    # Invariants summary
    print("\n-------------------------------------------------------")
    print("INVARIANTS SUMMARY:")
    print("-------------------------------------------------------")
    cogs_passed = cogs_entry is not None
    stock_decremented = qty_diff == SALE_QTY
    revenue_passed = revenue_entry is not None

    print(f"[{'PASS' if revenue_passed else 'FAIL'}] 1. Revenue Entry Posted (Dr Cash / Cr Revenue {SALE_PRICE_TOTAL:,.2f} PKR)")
    print(f"[{'PASS' if cogs_passed else 'FAIL'}] 2. Perpetual COGS Entry Posted (Dr Cost of Sales / Cr Inventory)")
    print(f"[{'PASS' if stock_decremented else 'FAIL'}] 3. Catalogue Stock Decremented by {SALE_QTY} units")

    return {
        "revenue_passed": revenue_passed,
        "cogs_passed": cogs_passed,
        "stock_decremented": stock_decremented,
        "qty_diff": qty_diff,
        "cogs_entry": cogs_entry,
        "revenue_entry": revenue_entry,
    }

if __name__ == "__main__":
    asyncio.run(run_probe())

