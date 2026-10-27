"""
Live end-to-end trace of clarification queries on real books and real LLMs.
Measures Turn 1 and Turn 2 latency with microsecond accuracy,
dumps the full ai_execution_steps trail, and identifies bottlenecks.
"""

from __future__ import annotations

import asyncio
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ERP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ERP_ROOT))

from app.agent import execute, resume_with_clarification
from app.ai_orchestrator import get_client
from app.auth import AuthContext
from app.database import fetch_many
import httpx

EMAIL = "zameerchattha3@gmail.com"
_env: Dict[str, str] = {}
env_file = ERP_ROOT / ".env"
if env_file.exists():
    for _line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.split("=", 1)
            _env[_k.strip()] = _v.strip().strip('"').strip("'")

_URL = _env.get("SUPABASE_URL", "")
_KEY = _env.get("SUPABASE_SERVICE_ROLE_KEY", "")
_H = {"apikey": _KEY, "Authorization": f"Bearer {_KEY}"}
_HA = {**_H, "Accept-Profile": "ai"}


async def resolve_identity() -> Dict[str, Any]:
    uid = None
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{_URL}/auth/v1/admin/users", headers=_H)
            r.raise_for_status()
            for u in (r.json().get("users") or []):
                if (u.get("email") or "").lower() == EMAIL.lower():
                    uid = u["id"]
                    break
    except Exception as exc:
        p(f"(admin users API unavailable: {str(exc)[:80]} - using membership-verified ids)")
    if not uid:
        uid = "b2ad946f-9d5e-4c71-832b-3b873e13d1aa"
    members = await fetch_many(
        "organization_members",
        filters={"user_id": f"{uid}", "status": "ACTIVE"},
        limit=5,
    )
    if not members:
        raise SystemExit("no ACTIVE membership for the user")
    m = members[0]
    roles = await fetch_many(
        "organization_roles", filters={"id": f"{m['role_id']}"}, limit=1,
    )
    role = roles[0] if roles else {}
    role_code = str(role.get("role_code") or role.get("code") or "owner")
    perms: List[str] = []
    for key in ("permissions", "role_permissions"):
        raw = role.get(key)
        if isinstance(raw, list):
            perms = [str(x) for x in raw]
    return {
        "user_id": uuid.UUID(str(m["user_id"])),
        "organization_id": uuid.UUID(str(m["organization_id"])),
        "role_code": role_code,
        "role_permissions": perms,
    }


async def dump_trail(session_id: uuid.UUID, label: str) -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            f"{_URL}/rest/v1/execution_steps", headers=_HA,
            params={"select": "created_at,step_type,status,input_summary",
                    "execution_session_id": f"eq.{session_id}",
                    "order": "created_at.asc"},
        )
        steps = r.json() if r.status_code == 200 else []
    p(f"\n----- TRAIL [{label}] ({len(steps)} steps) -----")
    for st in steps:
        kind = st.get("step_type") or "?"
        blob = st.get("input_summary") or ""
        if not isinstance(blob, str):
            blob = json.dumps(blob, default=str)
        p(f"  {str(st.get('created_at'))[11:19]} {kind:<24} [{st.get('status')}] {blob[:220]}")


def p(*args: Any) -> None:
    print(*args, flush=True)


async def trace_query(
    ctx: Dict[str, Any],
    query: str,
    answer: str,
    case_label: str,
) -> None:
    p(f"\n{'='*75}")
    p(f"CASE: {case_label}")
    p(f"QUERY: '{query}'")
    p(f"{'='*75}")

    auth = AuthContext(**ctx)
    conv_id = str(uuid.uuid4())

    # -------------------------------------------------------------
    # TURN 1: Initial query -> AWAITING_CLARIFICATION
    # -------------------------------------------------------------
    p("\n[TURN 1] Sending initial request...")
    t0_turn1 = time.perf_counter()
    resp1 = await execute(
        user_message=query,
        user_id=ctx["user_id"],
        organization_id=ctx["organization_id"],
        auth=auth,
        conversation_id=conv_id,
        attachments=None,
        questionnaire_client=get_client(),
    )
    t1_turn1 = time.perf_counter()
    turn1_duration = t1_turn1 - t0_turn1

    status_str = getattr(resp1.status, "value", str(resp1.status))
    p(f"[TURN 1] Status: {status_str} in {turn1_duration:.2f}s")

    if resp1.question:
        p(f"[TURN 1] Question: {resp1.question}")
    if resp1.options:
        p(f"[TURN 1] Options: {resp1.options}")
    if resp1.required_information:
        p(f"[TURN 1] Required Info: {resp1.required_information}")

    session_id = uuid.UUID(str(resp1.execution_id))
    await dump_trail(session_id, f"{case_label} - Turn 1 Trail")

    if status_str != "AWAITING_CLARIFICATION":
        p(f"[WARN] Expected AWAITING_CLARIFICATION, but got {status_str}. Skipping Turn 2.")
        return

    # -------------------------------------------------------------
    # TURN 2: Resume with Clarification Answer
    # -------------------------------------------------------------
    p(f"\n[TURN 2] Responding with answer: '{answer}'...")
    t0_turn2 = time.perf_counter()
    resp2 = await resume_with_clarification(
        session_id=session_id,
        user_answer=answer,
        user_id=ctx["user_id"],
        organization_id=ctx["organization_id"],
        auth=auth,
        structured_answers=None,
        questionnaire_client=get_client(),
    )
    t1_turn2 = time.perf_counter()
    turn2_duration = t1_turn2 - t0_turn2

    status2_str = getattr(resp2.status, "value", str(resp2.status))
    p(f"[TURN 2] Completed in {turn2_duration:.3f}s (Total: {turn2_duration*1000:.1f}ms)")
    p(f"[TURN 2] Final Status: {status2_str}")
    if resp2.summary:
        p(f"[TURN 2] Summary: {resp2.summary[:300]}")
    if getattr(resp2, "action", None):
        p(f"[TURN 2] Action: {resp2.action}")
    if getattr(resp2, "affected_entities", None):
        p(f"[TURN 2] Affected Entities: {resp2.affected_entities}")
    if getattr(resp2, "data", None):
        p(f"[TURN 2] Data: {resp2.data}")

    new_sid = uuid.UUID(str(resp2.execution_id)) if resp2.execution_id else session_id
    await dump_trail(new_sid, f"{case_label} - Turn 2 Trail")

    # -------------------------------------------------------------
    # TURN 3: If follow-up clarification was asked (e.g. date)
    # -------------------------------------------------------------
    if status2_str == "AWAITING_CLARIFICATION":
        p(f"\n[TURN 2] Asked follow-up question: {resp2.question}")
        p(f"[TURN 2] Options: {resp2.options}")
        p(f"[TURN 2] Required Info: {resp2.required_information}")
        p("\n[TURN 3] Answering follow-up date question with: 'Today'...")
        t0_turn3 = time.perf_counter()
        resp3 = await resume_with_clarification(
            session_id=new_sid,
            user_answer="Today",
            user_id=ctx["user_id"],
            organization_id=ctx["organization_id"],
            auth=auth,
            structured_answers=None,
            questionnaire_client=get_client(),
        )
        t1_turn3 = time.perf_counter()
        turn3_duration = t1_turn3 - t0_turn3
        status3_str = getattr(resp3.status, "value", str(resp3.status))
        p(f"[TURN 3] Completed in {turn3_duration:.3f}s (Total: {turn3_duration*1000:.1f}ms)")
        p(f"[TURN 3] Final Status: {status3_str}")
        if resp3.summary:
            p(f"[TURN 3] Summary: {resp3.summary[:300]}")
        if getattr(resp3, "action", None):
            p(f"[TURN 3] Action: {resp3.action}")
        if getattr(resp3, "data", None):
            p(f"[TURN 3] Data: {resp3.data}")
        final_sid = uuid.UUID(str(resp3.execution_id)) if resp3.execution_id else new_sid
        await dump_trail(final_sid, f"{case_label} - Turn 3 Trail")


async def main():
    p("Initializing live environment and identity...")
    ctx = await resolve_identity()
    p(f"Active Org: {ctx['organization_id']}, User: {ctx['user_id']}")

    # Case 1: Operational task (create_account with missing account_type)
    await trace_query(
        ctx=ctx,
        query="Create account for Cloud Server Hosting",
        answer="Expense",
        case_label="CASE 1: Operational (create_account)",
    )

    # Case 2: Expense with missing payment method -> asks date -> answered today -> posted
    await trace_query(
        ctx=ctx,
        query="Paid 3500 for ac repair",
        answer="Cash",
        case_label="CASE 2: Expense with missing payment method (Follow-up Date)",
    )

    # Case 3: Expense answered with both payment and date in one reply
    await trace_query(
        ctx=ctx,
        query="Paid 2400 for office supplies",
        answer="Cash, today",
        case_label="CASE 3: Expense with multi-part answer ('Cash, today')",
    )


if __name__ == "__main__":
    asyncio.run(main())
