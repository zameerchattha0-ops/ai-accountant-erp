"""Print the full recorded step trail for recent requests matching a needle.

Usage:
  python scripts/show_request_steps.py [needle ...]        (default: chair/alpha)
  python scripts/show_request_steps.py --recent [N]        (list last N sessions
                                                            with their outcome)

Reads SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY from the repo .env; steps live
in schema `ai` / table `execution_steps` (Accept-Profile header).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx


def _show(exc_type, exc, tb):
    import traceback

    traceback.print_exception(exc_type, exc, tb, file=sys.stdout)


sys.excepthook = _show  # a probe reports its errors on stdout

ERP = Path(r"e:\Qoder\Ai Accountant\ERP")
env = {}
for line in (ERP / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

URL = env["SUPABASE_URL"]
KEY = env["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept-Profile": "ai"}
TABLE = f"{URL}/rest/v1/execution_steps"


def fetch_steps(session_id: str) -> list[dict]:
    steps = httpx.get(
        TABLE,
        headers=HEADERS,
        params={
            "select": "*",
            "execution_session_id": f"eq.{session_id}",
            "order": "step_order.asc",
            "limit": "400",
        },
        timeout=30,
    ).json()
    if isinstance(steps, dict):
        print(f"API ERROR for {session_id}: {json.dumps(steps)[:400]}")
        return []
    return [s for s in steps if isinstance(s, dict)]


def print_trail(session_id: str, steps: list[dict]) -> None:
    print(f"\n=== TRAIL {session_id} ({len(steps)} steps) ===")
    for st in steps:
        body = (st.get("input_summary") or "").replace("\n", " ")
        # Clarification/failed rows carry the user-facing question — keep it.
        cap = 1500 if (st.get("description") or "") in (
            "AWAITING_CLARIFICATION", "FAILED"
        ) else 400
        if len(body) > cap:
            body = body[:cap] + " …"
        err = st.get("error_details") or ""
        line = (
            f"  {st.get('step_order'):>3} {st.get('created_at')} "
            f"{st.get('description')} [{st.get('status')}] {body}"
        )
        if err:
            line += f"  ERROR={str(err)[:300]}"
        print(line)


def _outcome(steps: list[dict]) -> tuple[str, str]:
    """(last terminal description, reason) for a session trail."""
    for st in reversed(steps):
        desc = st.get("description") or ""
        if desc in ("FAILED", "COMPLETED", "CANCELLED", "REJECTED"):
            detail = (st.get("input_summary") or "").replace("\n", " ")
            return desc, detail[:200]
    return "OPEN", ""


# --session mode: print one session's trail by id --------------------------
if sys.argv[1:2] == ["--session"] and len(sys.argv) > 2:
    for sid in sys.argv[2:]:
        print_trail(sid, fetch_steps(sid))
    sys.exit(0)

# --recent mode: list the last N sessions with their outcome ---------------
if sys.argv[1:2] == ["--recent"]:
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    rows = httpx.get(
        TABLE,
        headers=HEADERS,
        params={
            "select": "execution_session_id,created_at,input_summary",
            "description": "eq.RECEIVED",
            "order": "created_at.desc",
            "limit": str(n),
        },
        timeout=30,
    ).json()
    if isinstance(rows, dict):
        print("API ERROR:", json.dumps(rows)[:500])
        sys.exit(2)
    for r in rows:
        sid = r["execution_session_id"]
        steps = fetch_steps(sid)
        outcome, reason = _outcome(steps)
        text = (r.get("input_summary") or "").replace("\n", " ")[:120]
        print(
            f"{r.get('created_at')}  {sid}  {outcome:<10} {text}"
            + (f"  || {reason}" if reason and outcome == "FAILED" else "")
        )
    sys.exit(0)

NEEDLE = tuple(a.lower() for a in sys.argv[1:]) or ("chair", "alpha associates")


rows = httpx.get(
    TABLE,
    headers=HEADERS,
    params={
        "select": "*",
        "description": "eq.RECEIVED",
        "order": "created_at.desc",
        "limit": "50",
    },
    timeout=30,
).json()
if isinstance(rows, dict):  # PostgREST error object
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

sessions = []
for r in rows:
    text = (r.get("input_summary") or "").lower()
    if any(n in text for n in NEEDLE) if len(NEEDLE) == 1 else all(
        n in text for n in NEEDLE
    ):
        sessions.append((r["execution_session_id"], r.get("created_at"), text))

if not sessions:
    print(f"No RECEIVED session matching {NEEDLE!r} in the last 50.")
    for r in rows[:15]:
        print(" -", (r.get("input_summary") or "")[:90])
    sys.exit(0)

for s, created, text in sessions:
    print(f"MATCH session={s}  RECEIVED at {created}  input={text[:90]!r}")

for s, created, _ in sessions:
    steps = httpx.get(
        TABLE,
        headers=HEADERS,
        params={
            "select": "*",
            "execution_session_id": f"eq.{s}",
            "order": "step_order.asc",
            "limit": "400",
        },
        timeout=30,
    ).json()
    if isinstance(steps, dict):
        print(f"\n=== TRAIL {s} === API ERROR: {json.dumps(steps)[:400]}")
        continue
    print(f"\n=== TRAIL {s} ({len(steps)} steps) ===")
    for st in steps:
        if not isinstance(st, dict):
            print("  UNEXPECTED ROW:", str(st)[:200])
            continue
        body = (st.get("input_summary") or "").replace("\n", " ")
        if len(body) > 400:
            body = body[:400] + " …"
        err = st.get("error_details") or ""
        line = (
            f"  {st.get('step_order'):>3} {st.get('created_at')} "
            f"{st.get('description')} [{st.get('status')}] {body}"
        )
        if err:
            line += f"  ERROR={str(err)[:300]}"
        print(line)

