"""Read-only: find Zameer Labs Pvt org, list its latest AI activity sessions."""
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

# 1) find the org
orgs = httpx.get(
    f"{URL}/rest/v1/organizations",
    headers=H,
    params={
        "select": "id,name,slug",
        "or": "(name.ilike.*zameer*,slug.ilike.*zameer*)",
    },
    timeout=45,
).json()
print("ORGANIZATIONS:", json.dumps(orgs, indent=2))
if not orgs:
    sys.exit("no org matched 'zameer'")

ORG = orgs[0]["id"]

# 2) latest sessions for that org
rows = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "id,status,current_phase,created_at,user_request",
        "organization_id": f"eq.{ORG}",
        "order": "created_at.desc",
        "limit": "15",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

print(f"\n{len(rows)} sessions for {orgs[0]['name']}:")
for r in rows:
    print(
        f"{r['created_at'][:19]}  {r['id']}  {r['status']:<18} "
        f"{(r.get('current_phase') or '-'):<24} "
        f"{(r.get('user_request') or '').replace(chr(10), ' ')[:130]}"
    )
