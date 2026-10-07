"""Read-only: dump execution_steps + clarifications timeline for AES revenue sessions."""
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
HA = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept-Profile": "ai"}

rows = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "id,status,current_phase,created_at,updated_at,user_request",
        "organization_id": "eq.4c2922a2-6ae5-4774-900d-355db905b36a",
        "order": "created_at.desc",
        "limit": "15",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

for s in rows:
    print("\n" + "=" * 100)
    print(
        f"session {s['id'][:8]} [{s['status']}] phase={s.get('current_phase')} "
        f"created={str(s['created_at'])[:19]} updated={str(s.get('updated_at'))[:19]}"
    )
    print(f"  request: {(s.get('user_request') or '')[:200]}")

    steps = httpx.get(
        f"{URL}/rest/v1/execution_steps",
        headers=HA,
        params={
            "select": "step_order,step_type,description,status,error_details,started_at,completed_at",
            "execution_session_id": f"eq.{s['id']}",
            "order": "step_order.asc",
            "limit": "100",
        },
        timeout=45,
    ).json()
    if isinstance(steps, dict):
        print("  steps ERR:", json.dumps(steps)[:200])
    else:
        for st in steps:
            err = st.get("error_details")
            line = (
                f"  step {st['step_order']}: [{st['status']}] {st['step_type']} — "
                f"{(st.get('description') or '')[:160]}"
            )
            print(line)
            if err:
                print(f"      err: {json.dumps(err)[:400]}")

    cl = httpx.get(
        f"{URL}/rest/v1/clarifications",
        headers=HA,
        params={
            "select": "created_at,question,user_response,status,answered_at",
            "execution_session_id": f"eq.{s['id']}",
            "order": "created_at.asc",
            "limit": "50",
        },
        timeout=45,
    ).json()
    if isinstance(cl, dict):
        print("  clarif ERR:", json.dumps(cl)[:200])
    else:
        seen: set[tuple] = set()
        for c in cl:
            key = (c.get("question"), c.get("user_response"))
            if key in seen:
                continue
            seen.add(key)
            q = (c.get("question") or "").replace("\n", " ")[:110]
            print(
                f"  clar(u) {str(c['created_at'])[11:19]} [{c['status']}] "
                f"Q={q!r} A={(c.get('user_response') or '')[:70]!r}"
            )
