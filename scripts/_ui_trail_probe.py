"""Read-only: pull the newest execution session(s) + full step trail from
the ai schema (PostgREST, service role). Debug aid for the 2026-10-17 UI
turn that answered 'SELL 2 CHAIRS TO GETA LTD FOR 54000' with a degenerate
AWAITING_CLARIFICATION prose message. Never prints secrets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
ERP = Path(r"e:\Qoder\Ai Accountant\ERP")
env: dict[str, str] = {}
for line in (ERP / ".env").read_text(encoding="utf-8-sig").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

URL = env["SUPABASE_URL"]
KEY = env["SUPABASE_SERVICE_ROLE_KEY"]
HA = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept-Profile": "ai"}

sessions = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "id,status,current_phase,created_at,user_request,organization_id",
        "order": "created_at.desc",
        "limit": "8",
    },
    timeout=45,
).json()
print("== newest execution_sessions ==")
for s in sessions:
    print(f"{s['created_at'][:19]}  {str(s['id'])[:8]}  {s['status']:<22} "
          f"{(s.get('user_request') or '').replace(chr(10), ' ')[:90]}")

target = None
_term = (sys.argv[1].upper() if len(sys.argv) > 1 else "SELL 2 CHAIRS")
_wide = None
if all(c in "0123456789abcdef" for c in _term.lower()) and len(_term) >= 6:
    _wide = httpx.get(
        f"{URL}/rest/v1/execution_sessions",
        headers=HA,
        params={
            "select": "id,status,current_phase,created_at,user_request,organization_id",
            "order": "created_at.desc",
            "limit": "120",
        },
        timeout=45,
    ).json()
    target = next(
        (s for s in _wide if str(s["id"]).startswith(_term.lower())), None
    )
else:
    for s in sessions:
        if _term in (s.get("user_request") or "").upper():
            target = s
            break
if not target:
    # widen once if the newest 8 don't carry the term
    _wide = _wide or httpx.get(
        f"{URL}/rest/v1/execution_sessions",
        headers=HA,
        params={
            "select": "id,status,current_phase,created_at,user_request,organization_id",
            "order": "created_at.desc",
            "limit": "80",
        },
        timeout=45,
    ).json()
    target = next(
        (s for s in _wide if _term in (s.get("user_request") or "").upper()),
        None,
    )
if not target:
    print(f"no sessions matching {_term!r}")
    raise SystemExit(0)

sid = target["id"]
print(f"\n== trail for session {str(sid)[:8]} ({target['status']}) ==")
steps = httpx.get(
    f"{URL}/rest/v1/execution_steps",
    headers=HA,
    params={
        "select": "*",
        "execution_session_id": f"eq.{sid}",
        "order": "created_at.asc",
    },
    timeout=45,
).json()
for st in steps:
    desc = (st.get("description") or "-")
    print(f"\n--- {st['created_at'][11:19]}  {desc}")
    for key in ("input_summary", "output_summary", "result_summary",
                "error", "detail", "status"):
        val = st.get(key)
        if val:
            txt = val if isinstance(val, str) else json.dumps(val)
            print(f"  [{key}] {txt[:1200]}")
