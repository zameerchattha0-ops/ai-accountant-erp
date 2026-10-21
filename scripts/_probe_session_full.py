"""Read-only: dump the FULL trail for ONE execution session id (arg).

Usage: python _probe_session_full.py <session_id> [select_fields]
Prints every execution_step with description/status/input_summary/
output_summary/error_details, plus the session's top-level fields.
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

sid = sys.argv[1]

sess = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={"select": "*", "id": f"eq.{sid}"},
    timeout=60,
).json()
if isinstance(sess, list) and sess:
    s = sess[0]
    print("== SESSION ==")
    for k in ("id", "status", "current_phase", "created_at", "updated_at", "user_request"):
        print(f"  {k}: {s.get(k)}")
    # dump any other interesting scalar fields
    for k, v in s.items():
        if k not in ("id", "status", "current_phase", "created_at", "updated_at", "user_request") and isinstance(v, (str, int, float, bool)) and v:
            print(f"  {k}: {str(v)[:200]}")

steps = httpx.get(
    f"{URL}/rest/v1/execution_steps",
    headers=HA,
    params={
        "select": "*",
        "execution_session_id": f"eq.{sid}",
        "order": "step_order.asc",
        "limit": "400",
    },
    timeout=60,
).json()
print(f"\n== {len(steps) if isinstance(steps, list) else 'ERR'} STEPS ==")
if isinstance(steps, dict):
    print(json.dumps(steps)[:400])
else:
    for st in steps:
        body = (st.get("input_summary") or "").replace("\n", " ")
        if len(body) > 900:
            body = body[:900] + " …"
        out = (st.get("output_summary") or "").replace("\n", " ")
        if len(out) > 900:
            out = out[:900] + " …"
        print(f"\n  {st.get('step_order'):>3} {st.get('step_type') or '':<14} [{st.get('status')}] {st.get('description')}")
        if body:
            print(f"      IN : {body}")
        if out:
            print(f"      OUT: {out}")
        if st.get("error_details"):
            print(f"      ERR: {str(st['error_details'])[:800]}")
