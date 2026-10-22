"""Live evaluation of LLM Sole Authority implementation on realistic low-information queries.
Tests:
1. "TRAVEL EXP PAID FOR 5000" (User's specific case: travel expense with missing payment method)
2. "office supplies 12000" (Generic expense: missing payment method / cash vs credit)
3. "paid 3500 for ac repair" (Unscheduled repair: missing payment channel)
4. "bought drill machine for 65000" (High value > 50k: Fixed Asset capitalization check)
5. "sold 2 chairs" (Sales inquiry: missing price, customer, cash vs credit)
"""

import asyncio
import json
import sys
import time
import uuid
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
    return pyjwt.encode(
        {
            "sub": TEST_USER_ID,
            "role": "authenticated",
            "aud": "authenticated",
            "email": "test.owner@erptest.local",
            "iat": now,
            "exp": now + 7200,
            "session_id": str(uuid.uuid4()),
        },
        secret,
        algorithm="HS256",
    )


CASES = [
    {
        "id": "CASE-1",
        "description": "User's exact query (Travel expense, missing cash vs bank)",
        "prompt": "TRAVEL EXP PAID FOR 5000",
        "answer": "Paid from Cash in hand",
    },
    {
        "id": "CASE-2",
        "description": "Generic Office Supplies (Missing cash vs credit)",
        "prompt": "office supplies 12000",
        "answer": "Cash, paid today",
    },
    {
        "id": "CASE-3",
        "description": "AC Repair (Unscheduled repair expense)",
        "prompt": "paid 3500 for ac repair",
        "answer": "Cash",
    },
    {
        "id": "CASE-4",
        "description": "High Value Equipment > 50k (Capitalization Check)",
        "prompt": "bought drill machine for 65000",
        "answer": "Company bank account, for factory operations, useful life 5 years",
    },
]


async def run_live_eval():
    secret = load_secret()
    token = make_token(secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", timeout=60.0) as client:
        print("=" * 80)
        print("LIVE EVALUATION: LLM SOLE AUTHORITY EFFECTIVENESS TEST")
        print("=" * 80)

        for tc in CASES:
            print(f"\n>>> [{tc['id']}] PROMPT: \"{tc['prompt']}\"")
            print(f"    Intent: {tc['description']}")

            # Turn 1: Initial user message
            t0 = time.time()
            res = await client.post("/api/ai/execute", json={"message": tc["prompt"]}, headers=headers)
            elapsed = time.time() - t0
            body = res.json()

            status = body.get("status")
            question = body.get("question")
            summary = body.get("summary")
            options = body.get("question_options") or body.get("options")
            execution_id = body.get("execution_id")

            print(f"    Turn 1 Status: {status} ({elapsed:.2f}s)")
            if question:
                print(f"    Clarification Asked:")
                for qline in str(question).strip().splitlines()[:6]:
                    print(f"      | {qline}")
                if options:
                    print(f"      Options/Chips provided: {options}")
            if summary:
                print(f"    Summary: {summary}")

            # Turn 2: Follow-up conversational answer if clarification needed
            if status == "AWAITING_CLARIFICATION" and execution_id:
                print(f"    Answering Clarification with: \"{tc['answer']}\"")
                t1 = time.time()
                res2 = await client.post(
                    "/api/ai/clarify",
                    json={"session_id": str(execution_id), "answer": tc["answer"]},
                    headers=headers,
                )
                elapsed2 = time.time() - t1
                body2 = res2.json()
                status2 = body2.get("status")
                summary2 = body2.get("summary") or body2.get("question")
                print(f"    Turn 2 Status: {status2} ({elapsed2:.2f}s)")
                print(f"    Turn 2 Response: {summary2}")

                # If confirmation is requested
                if status2 == "AWAITING_CONFIRMATION":
                    print(f"    Auto-Confirming...")
                    res3 = await client.post(
                        "/api/ai/confirm",
                        json={"session_id": str(execution_id), "approved": True},
                        headers=headers,
                    )
                    body3 = res3.json()
                    print(f"    Final Status after confirmation: {body3.get('status')}")
                    print(f"    Final Summary: {body3.get('summary')}")

            elif status == "AWAITING_CONFIRMATION" and execution_id:
                print(f"    Auto-Confirming...")
                res3 = await client.post(
                    "/api/ai/confirm",
                    json={"session_id": str(execution_id), "approved": True},
                    headers=headers,
                )
                body3 = res3.json()
                print(f"    Final Status after confirmation: {body3.get('status')}")
                print(f"    Final Summary: {body3.get('summary')}")

            elif status == "COMPLETED":
                print(f"    COMPLETED on Turn 1! Zero clarification needed.")

            print("-" * 60)


if __name__ == "__main__":
    asyncio.run(run_live_eval())

