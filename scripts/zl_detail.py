"""Read-only: dump the latest Zameer Labs session trail + tool calls + outcome."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ERP = Path(r"e:\Qoder\Ai Accountant\ERP")
env: dict[str, str] = {}
for line in (ERP / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

URL = env["SUPABASE_URL"]
KEY = env["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
HA = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept-Profile": "ai"}

SID = sys.argv[1] if len(sys.argv) > 1 else "afcfecae-124e-4baf-bb9a-7873b8bb5cee"

# 1) session row (all columns — includes outcome/response fields)
sess = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={"select": "*", "id": f"eq.{SID}", "limit": "1"},
    timeout=45,
).json()
if not isinstance(sess, list) or not sess:
    print("SESSION ERROR:", json.dumps(sess)[:500])
    sys.exit(2)
s = sess[0]
print("=== SESSION ===")
for k in sorted(s):
    v = s[k]
    if isinstance(v, str) and len(v) > 1500:
        v = v[:1500] + " …TRUNC"
    print(f"  {k}: {v}")

# 2) steps
steps = httpx.get(
    f"{URL}/rest/v1/execution_steps",
    headers=HA,
    params={
        "select": "*",
        "execution_session_id": f"eq.{SID}",
        "order": "step_order.asc",
        "limit": "300",
    },
    timeout=45,
).json()
print(f"\n=== STEPS ({len(steps) if isinstance(steps, list) else 'ERR'}) ===")
if isinstance(steps, list):
    for st in steps:
        body = (st.get("input_summary") or "").replace("\n", " ")
        if len(body) > 400:
            body = body[:400] + " …"
        line = (
            f"  {st.get('step_order'):>3} {str(st.get('created_at'))[11:19]} "
            f"{st.get('description')} [{st.get('status')}] {body}"
        )
        if st.get("error_details"):
            line += f"  ERROR={str(st['error_details'])[:300]}"
        print(line)

# 3) tool calls
tcs = httpx.get(
    f"{URL}/rest/v1/tool_calls",
    headers=HA,
    params={
        "select": "*",
        "execution_session_id": f"eq.{SID}",
        "order": "created_at.asc",
        "limit": "100",
    },
    timeout=45,
).json()
print(f"\n=== TOOL CALLS ({len(tcs) if isinstance(tcs, list) else 'ERR'}) ===")
if isinstance(tcs, list):
    for t in tcs:
        print("  ---")
        for k in sorted(t):
            v = t[k]
            if isinstance(v, str) and len(v) > 1200:
                v = v[:1200] + " …TRUNC"
            print(f"    {k}: {v}")
