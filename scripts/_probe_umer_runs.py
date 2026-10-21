"""Read-only: dump the full trail for the two 'umer autos' runs (2026-10-20).

1) 'purchase return to umer autos against damaged motorbikes'  (FAILED)
2) 'I purchased two bikes on credit from umer autos'           (COMPLETED)

Prints session rows + every execution_step (description/status/input_summary/
error_details) + any clarification rows, so we can see exactly where the
purchase-return reasoning and the inventory/catalogue sync fell over.
"""
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

TERM = (sys.argv[1] if len(sys.argv) > 1 else "UMER AUTOS").upper()

sessions = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "id,status,current_phase,created_at,updated_at,user_request,organization_id",
        "order": "created_at.desc",
        "limit": "300",
    },
    timeout=60,
).json()

if isinstance(sessions, dict):
    print("API ERROR:", json.dumps(sessions)[:500])
    sys.exit(2)

hits = [s for s in sessions if TERM in (s.get("user_request") or "").upper()]
print(f"== {len(hits)} session(s) matching {TERM!r} ==\n")

for s in hits:
    print("=" * 100)
    print(
        f"session {s['id']}  [{s['status']}]  phase={s.get('current_phase')}  "
        f"created={str(s['created_at'])[:19]}"
    )
    print(f"  request: {(s.get('user_request') or '')[:300]}")

    steps = httpx.get(
        f"{URL}/rest/v1/execution_steps",
        headers=HA,
        params={
            "select": "step_order,step_type,description,status,error_details,input_summary,output_summary,started_at,completed_at",
            "execution_session_id": f"eq.{s['id']}",
            "order": "step_order.asc",
            "limit": "300",
        },
        timeout=60,
    ).json()
    if isinstance(steps, dict):
        print("  steps ERR:", json.dumps(steps)[:300])
    else:
        print(f"  ---- {len(steps)} steps ----")
        for st in steps:
            body = (st.get("input_summary") or "").replace("\n", " ")
            if len(body) > 600:
                body = body[:600] + " …"
            out = (st.get("output_summary") or "").replace("\n", " ")
            if len(out) > 600:
                out = out[:600] + " …"
            print(
                f"  {st.get('step_order'):>3} {st.get('step_type') or '':<12} "
                f"[{st.get('status')}] {st.get('description')}"
            )
            if body:
                print(f"        IN : {body}")
            if out:
                print(f"        OUT: {out}")
            if st.get("error_details"):
                print(f"        ERR: {str(st['error_details'])[:500]}")
    print()
