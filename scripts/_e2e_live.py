"""LIVE end-to-end harness - real books, real LLM, full execution logs.

Owner-run operator script (NOT part of the unit suite - the suite stays
hermetic per app/tests/conftest.py).  Drives the SAME entry points the API
uses (agent.execute / resume_with_clarification) with the real client, then
dumps the ai.execution_steps trail and the final recorded journal for the
record scenario.

Run: venv\\Scripts\\python.exe -u scripts\\_e2e_live.py   (detached; logs to stdout)
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(__import__("pathlib").Path(
    __file__).resolve().parents[1]))

from app.agent import execute, resume_with_clarification  # noqa: E402
from app.ai_orchestrator import get_client  # noqa: E402
from app.auth import AuthContext  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import fetch_many  # noqa: E402

EMAIL = "zameerchattha3@gmail.com"
ERP = __import__("pathlib").Path(__file__).resolve().parents[1]
_env: Dict[str, str] = {}
for _line in (ERP / ".env").read_text(encoding="utf-8-sig").splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _v = _line.split("=", 1)
        _env[_k.strip()] = _v.strip().strip('"').strip("'")
_URL, _KEY = _env["SUPABASE_URL"], _env["SUPABASE_SERVICE_ROLE_KEY"]
_H = {"apikey": _KEY, "Authorization": f"Bearer {_KEY}"}
_HA = {**_H, "Accept-Profile": "ai"}

ANALYTICS_QUESTIONS = [
    "How much did I buy from SHABBIR FURNITURES this month?",
    "What is my total purchases this month?",
    "Show me my unpaid supplier bills",
]
AMBIGUOUS = "shabbir payment"
RECORD_MSG = "Bought 1 office chair ON CREDIT FROM SHABBIR FURNITURES for 15000 today"


def p(*args: Any) -> None:
    print(*args, flush=True)


async def resolve_identity() -> Dict[str, Any]:
    """Best-effort: admin API first; fallback = the membership-VERIFIED
    ids this account has always used (confirmed via organization_members +
    the supplier/bill rows they created)."""
    uid = None
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{_URL}/auth/v1/admin/users", headers=_H)
            r.raise_for_status()
            for u in (r.json().get("users") or []):
                if (u.get("email") or "").lower() == EMAIL.lower():
                    uid = u["id"]
                    break
    except Exception as exc:  # noqa: BLE001 - fall through to known ids
        p(f"(admin users API unavailable: {str(exc)[:80]} - using "
          "membership-verified ids)")
    if not uid:
        uid = "b2ad946f-9d5e-4c71-832b-3b873e13d1aa"  # this account's id
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
        p(f"  {str(st.get('created_at'))[11:19]} {kind:<24} "
          f"[{st.get('status')}] {blob[:220]}")



async def run_analytics(ctx: Dict[str, Any]) -> None:
    for q in ANALYTICS_QUESTIONS + [AMBIGUOUS]:
        p(f"\n================ Q: {q}")
        resp = await execute(
            user_message=q, user_id=ctx["user_id"],
            organization_id=ctx["organization_id"], auth=AuthContext(**ctx),
            conversation_id=None, attachments=None,
            questionnaire_client=get_client(),
        )
        p(f"STATUS: {resp.status}")
        if getattr(resp, "question", None):
            p(f"QUESTION: {resp.question}")
        if getattr(resp, "summary", None):
            p("ANSWER:\n" + str(resp.summary)[:1500])
        if getattr(resp, "execution_id", None):
            await dump_trail(uuid.UUID(str(resp.execution_id)), q[:40])


def _auto_answer(question: str) -> str:
    low = (question or "").lower()
    # CATALOGUE-HINTED NATURE QUESTION (2026-10-18): answer (a) YES —
    # INVENTORY, consistent with the 'chairs' stock record.
    if "consistent with your stock" in low or "as an inventory purchase" in low:
        return "a"
    if "amount" in low or "how much" in low:
        return "15000"
    if "nature" in low or "is this item" in low:
        return "c"          # consumable/expense - minimal footprint
    if "supplier" in low and ("create" in low or "should i" in low):
        return "yes, create it"   # sanction the new supplier ledger
    if "payment" in low or "credit" in low or "cash" in low:
        return "CREDIT"
    if "date" in low:
        return date.today().isoformat()
    return "yes"


async def run_record(ctx: Dict[str, Any]) -> None:
    p(f"\n================ RECORD: {RECORD_MSG}")
    resp = await execute(
        user_message=RECORD_MSG, user_id=ctx["user_id"],
        organization_id=ctx["organization_id"], auth=AuthContext(**ctx),
        conversation_id=None, attachments=None,
        questionnaire_client=get_client(),
    )
    session = uuid.UUID(str(resp.execution_id))
    for turn in range(1, 6):
        p(f"\n--- turn {turn}: {resp.status}")
        if getattr(resp, "question", None):
            p(f"QUESTION: {str(resp.question)[:400]}")
        if getattr(resp, "summary", None) and not getattr(resp, "question", None):
            p("SUMMARY: " + str(resp.summary)[:600])
        if (getattr(resp.status, "name", None) or str(resp.status)) in ("AWAITING_CONFIRMATION", "WAITING_FOR_USER"):
            # the plan is ready - APPROVE it (this is the "user clicks yes")
            from app.agent import resume_with_confirmation

            p("AUTO-CONFIRM: approved=True")
            resp = await resume_with_confirmation(
                session_id=session, approved=True, user_id=ctx["user_id"],
                organization_id=ctx["organization_id"],
                auth=AuthContext(**ctx),
            )
            if getattr(resp, "execution_id", None):
                session = uuid.UUID(str(resp.execution_id))
            continue
        if (getattr(resp.status, "name", None) or str(resp.status)) not in ("AWAITING_CLARIFICATION",):
            break
        answer = _auto_answer(str(resp.question or ""))
        p(f"AUTO-ANSWER: {answer}")
        resp = await resume_with_clarification(
            session_id=session, user_answer=answer, user_id=ctx["user_id"],
            organization_id=ctx["organization_id"], auth=AuthContext(**ctx),
            structured_answers=None, questionnaire_client=get_client(),
        )
        if getattr(resp, "execution_id", None):
            # a resume may continue under a NEW session id - always carry
            # the LATEST one forward (harness catch, 2026-10-18)
            session = uuid.UUID(str(resp.execution_id))
    await dump_trail(session, "RECORD final")
    # ---- FINAL RECORDING: whatever landed in the books ------------------
    bills = await fetch_many(
        "purchase_bills",
        filters={"organization_id": f"{ctx['organization_id']}",
                 "bill_date": f"{date.today().isoformat()}"},
        order="created_at.desc", limit=3,
    )
    for b in bills or []:
        p(f"\nBILL {b.get('bill_number')} status={b.get('status')} "
          f"total={b.get('total')} notes={str(b.get('notes'))[:60]!r}")
    jes = await fetch_many(
        "journal_entries",
        filters={"organization_id": f"{ctx['organization_id']}",
                 "source_type": "purchase_bill"},
        order="created_at.desc", limit=2,
    ) or []
    for je in jes:
        p(f"JOURNAL {je.get('journal_number')} status={je.get('status')} "
          f"date={je.get('transaction_date')} total={je.get('total_debit')}")
        lines = await fetch_many(
            "journal_lines", filters={"entry_id": f"{je['id']}"},
            order="line_number.asc", limit=10,
        ) or []
        for ln in lines:
            accs = await fetch_many(
                "accounts", filters={"id": f"{ln.get('account_id')}"},
                limit=1,
            ) or [{}]
            a = accs[0]
            p(f"    DR {str(ln.get('debit')):>12}  CR {str(ln.get('credit')):>12}"
              f"  [{a.get('code')}] {a.get('name')}")


async def main() -> None:
    s = get_settings()
    p("FLAGS:", {
        "router": s.llm_router_enabled, "analytics": s.analytics_agent_enabled,
        "classification": s.llm_classification_enabled,
        "stage2": s.llm_preliminary_extraction_enabled,
        "review": s.treatment_review_enabled,
    })
    ctx = await resolve_identity()
    p("IDENTITY:",
      {k: str(v) for k, v in ctx.items() if k != "role_permissions"},
      f"perms={len(ctx['role_permissions'])}")
    if "--record-only" not in sys.argv:
        await run_analytics(ctx)
    await run_record(ctx)
    p("\n===== E2E COMPLETE =====")


if __name__ == "__main__":
    asyncio.run(main())
