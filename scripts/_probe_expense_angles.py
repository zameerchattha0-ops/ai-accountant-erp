"""Comprehensive probe: trace end-to-end routing, analysis and posting
for diverse low-information natural expense queries.
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
from app.database import fetch_many, get_service_client

TEST_ORG_ID = "00000000-0000-4000-8000-000000000010"
TEST_USER_ID = "00000000-0000-4000-8000-000000000001"

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

TEST_CASES = [
    {
        "angle": "1. Casual Refreshment / Office",
        "prompt": "got tea and sugar for office 850",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Office Supplies / General Expense",
    },
    {
        "angle": "2. Utility Bill (Colloquial / Bare)",
        "prompt": "electricity bill 12000",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Utilities Expense",
    },
    {
        "angle": "3. Rent / Facility (Bare Noun)",
        "prompt": "warehouse rent 45000",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Rent Expense",
    },
    {
        "angle": "4. Travel / Ride-hail (Brand/Colloquial)",
        "prompt": "uber to client office 1400",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Travel / Operating Expense",
    },
    {
        "angle": "5. Digital Advertising / Social Ad",
        "prompt": "boosted facebook post 3000",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Advertising Expense",
    },
    {
        "angle": "6. SaaS / Software Subscription (Abbreviated)",
        "prompt": "figma sub 4500",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Software Subscriptions",
    },
    {
        "angle": "7. Repair & Maintenance (Unscheduled)",
        "prompt": "ac repair in hall 3500",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Repairs / Operating Expense",
    },
    {
        "angle": "8. Vague Minimal Expense",
        "prompt": "spent 1200 on cleaning",
        "expected_nature": "EXPENSE",
        "ideal_account_family": "Supplies / Operating Expense",
    },
]

async def probe_case(client, headers, tc):
    print(f"\n=======================================================", flush=True)
    print(f"PROBING ANGLE: {tc['angle']}", flush=True)
    print(f"USER PROMPT:   \"{tc['prompt']}\"", flush=True)
    print(f"EXPECTED:      Nature={tc['expected_nature']}, Account ~ {tc['ideal_account_family']}", flush=True)
    print(f"=======================================================", flush=True)

    r = await client.post("/api/ai/execute", json={"message": tc["prompt"]}, headers=headers)
    body = r.json()
    status = body.get("status")
    text = body.get("question") or body.get("summary") or ""
    data = body.get("data") or {}

    print(f"  -> Turn 1 Status: {status}", flush=True)
    print(f"  -> Agent Output:  {text[:200]}", flush=True)

    # If it asked clarification or confirmation, inspect details
    plan = data.get("plan") or {}
    print(f"  -> Resolved Intent: {data.get('intent') or plan.get('intent')}", flush=True)
    print(f"  -> Tool Planned:    {data.get('tool') or [c.get('tool_name') for c in (data.get('tools') or [])]}", flush=True)

    # Auto-answer if asking clarification
    turns = 0
    while status in ("AWAITING_CLARIFICATION", "AWAITING_CONFIRMATION") and turns < 4:
        turns += 1
        if status == "AWAITING_CLARIFICATION":
            # For low-info expenses, provide reasonable user answer
            ans = "cash, today" if any(w in text.lower() for w in ("how", "paid", "when", "date")) else "record it, paid in cash today"
            print(f"  -> Answering Clarification: \"{ans}\"", flush=True)
            r = await client.post(
                "/api/ai/clarify",
                json={"session_id": str(body.get("execution_id")), "answer": ans},
                headers=headers
            )
            body = r.json()
            status = body.get("status")
            text = body.get("question") or body.get("summary") or ""
            data = body.get("data") or {}
            print(f"  -> Turn {turns+1} Status: {status}", flush=True)
            print(f"  -> Agent Output:  {text[:200]}", flush=True)

        elif status == "AWAITING_CONFIRMATION":
            print(f"  -> Confirming: approved=True", flush=True)
            r = await client.post(
                "/api/ai/confirm",
                json={"session_id": str(body.get("execution_id")), "approved": True},
                headers=headers
            )
            body = r.json()
            status = body.get("status")
            text = body.get("question") or body.get("summary") or ""
            data = body.get("data") or {}
            print(f"  -> Turn {turns+1} Status: {status}", flush=True)
            print(f"  -> Agent Output:  {text[:200]}", flush=True)
            break

    print(f"  -> Final Status: {status}", flush=True)
    return {
        "angle": tc["angle"],
        "prompt": tc["prompt"],
        "final_status": status,
        "summary": text[:200],
    }

async def main():
    secret = load_secret()
    token = make_token(secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    transport = ASGITransport(app=app)
    results = []
    async with AsyncClient(transport=transport, base_url="http://test", timeout=90.0) as client:
        for tc in TEST_CASES:
            try:
                res = await probe_case(client, headers, tc)
                results.append(res)
            except Exception as exc:
                print(f"  [ERROR] {exc}", flush=True)
                results.append({"angle": tc["angle"], "error": str(exc)})

    print("\n\n=======================================================", flush=True)
    print("PROBE RUN SUMMARY OF EXPENSE ANGLES", flush=True)
    print("=======================================================", flush=True)
    for r in results:
        print(f"[{r.get('final_status', 'ERROR')}] {r.get('angle')}: {r.get('summary', r.get('error', ''))[:100]}")

if __name__ == "__main__":
    asyncio.run(main())

