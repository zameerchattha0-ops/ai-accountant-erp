"""Read-only: find sessions (any org) whose request mentions revenue/account
creation, plus list AES conversations/messages tables if present."""
from __future__ import annotations

import json
import re
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

# 1) all tables (public) to spot message/conversation tables
root = httpx.get(f"{URL}/rest/v1/", headers=H, params={"select": "*"}, timeout=45)
names = sorted(set(re.findall(r'"([a-z_]+)"', root.text)))
print("conversation-ish tables:", [n for n in names if any(k in n for k in ("message", "conversation", "chat"))])

# 2) sessions mentioning revenue/account keywords across ALL orgs
rows = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "id,organization_id,status,current_phase,created_at,user_request",
        "order": "created_at.desc",
        "limit": "300",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:400])
    sys.exit(2)

print(f"total recent sessions: {len(rows)}")
for r in rows:
    req = (r.get("user_request") or "").lower()
    if any(k in req for k in ("revenue", "account", "chart of accounts", "child", "parent")):
        print(
            f"{r['created_at'][:19]}  {r['id']}  org={str(r.get('organization_id'))[:8]}  "
            f"{r['status']:<18} {(r.get('user_request') or '')[:120]}"
        )
