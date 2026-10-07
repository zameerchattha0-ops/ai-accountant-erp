"""Read-only: dump tool-call logs for AES revenue-ledger sessions."""
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

SESSIONS = [
    "aa041df4",
    "57dab71f",
    "7320eeb3",
    "6dd32c77",
    "8778d89a",
    "7951a863",
]

# full session ids
rows = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "id,status,current_phase,created_at,user_request",
        "organization_id": "eq.4c2922a2-6ae5-4774-900d-355db905b36a",
        "order": "created_at.desc",
        "limit": "60",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

full = {r["id"]: r for r in rows if r["id"][:8] in SESSIONS}
print(f"matched sessions: {len(full)}")

# discover tool log table columns first
cols = httpx.get(
    f"{URL}/rest/v1/tool_definitions",
    headers=HA,
    params={"select": "*", "limit": "1"},
    timeout=45,
).json()
if isinstance(cols, dict):
    cols2 = httpx.get(
        f"{URL}/rest/v1/tools", headers=HA, params={"select": "*", "limit": "1"}, timeout=45
    ).json()
    print("tool_definitions ERR:", json.dumps(cols)[:200])
    if isinstance(cols2, dict):
        print("tools ERR:", json.dumps(cols2)[:200])
        TOOL_TABLE = None
    else:
        print("tools cols:", list(cols2[0].keys()) if cols2 else "empty")
        TOOL_TABLE = "tools"
else:
    print("tool_definitions cols:", list(cols[0].keys()) if cols else "empty")
    TOOL_TABLE = "tool_definitions"

tool_names: dict[str, str] = {}
if TOOL_TABLE:
    trows = httpx.get(
        f"{URL}/rest/v1/{TOOL_TABLE}",
        headers=HA,
        params={"select": "id,name,tool_name", "limit": "500"},
        timeout=45,
    ).json()
    if isinstance(trows, dict):
        trows = httpx.get(
            f"{URL}/rest/v1/{TOOL_TABLE}",
            headers=HA,
            params={"select": "*", "limit": "500"},
            timeout=45,
        ).json()
    if isinstance(trows, dict):
        print("tool rows ERR:", json.dumps(trows)[:300])
    else:
        for t in trows:
            nm = t.get("name") or t.get("tool_name") or t.get("id")
            tool_names[str(t.get("id"))] = str(nm)
        print(f"tool name map: {len(tool_names)}")

for sid, s in full.items():
    print("\n" + "=" * 90)
    print(f"session {sid[:8]} [{s['status']}] {str(s['created_at'])[:19]}")
    print(f"  request: {(s.get('user_request') or '')[:300]}")
    logs = httpx.get(
        f"{URL}/rest/v1/tool_calls",
        headers=HA,
        params={
            "select": "created_at,tool_id,call_order,status,error_details,input_payload,output_payload",
            "execution_session_id": f"eq.{sid}",
            "order": "created_at.asc",
            "limit": "200",
        },
        timeout=45,
    ).json()
    if isinstance(logs, dict):
        print("  LOG API ERROR:", json.dumps(logs)[:300])
        continue
    print(f"  tool calls: {len(logs)}")
    for lg in logs:
        st = lg.get("status")
        err = lg.get("error_details") or ""
        tname = tool_names.get(str(lg.get("tool_id")), str(lg.get("tool_id"))[:8])
        print(f"   - {str(lg['created_at'])[11:19]} {tname} [{st}] {str(err)[:300]}")
        if st not in ("success", "completed", "SUCCEEDED", "succeeded", None) or err:
            print(f"       input: {json.dumps(lg.get('input_payload'))[:500]}")
            print(f"       output: {json.dumps(lg.get('output_payload'))[:500]}")
