"""Read-only: list execution_sessions columns + find AES Engineering org."""
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

# 1) AES Engineering organization (public schema)
orgs = httpx.get(
    f"{URL}/rest/v1/organizations",
    headers=H,
    params={"select": "id,name,slug", "or": "(name.ilike.*aes*,slug.ilike.*aes*)"},
    timeout=45,
).json()
print("ORGANIZATIONS:", json.dumps(orgs, indent=2)[:2000])

# 2) recent sessions with org/user columns
rows = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "*",
        "order": "created_at.desc",
        "limit": "3",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("SESSION API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)
print("SESSION COLUMNS:", sorted(rows[0].keys()) if rows else "(none)")
for r in rows:
    print(json.dumps({k: r[k] for k in sorted(r) if k not in ("plan_json",)}, indent=1, default=str)[:1500])
    print("---")
