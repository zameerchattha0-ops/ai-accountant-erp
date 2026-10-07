"""Read-only: dump AES revenue accounts (id, name, type, parent) from the chart."""
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
# public schema (chart of accounts live outside the ai schema)
HA = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

ORG = "4c2922a2-6ae5-4774-900d-355db905b36a"

rows = httpx.get(
    f"{URL}/rest/v1/accounts",
    headers=HA,
    params={
        "select": "id,name,account_type,parent_account_id,is_active",
        "organization_id": f"eq.{ORG}",
        "order": "name.asc",
        "limit": "500",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("accounts ERR:", json.dumps(rows)[:400])
    sys.exit(2)

by_id = {r["id"]: r for r in rows}
rev = [r for r in rows if str(r.get("account_type") or "").upper() in ("REVENUE", "INCOME")]
print(f"total accounts={len(rows)} revenue={len(rev)}")
for r in rev:
    parent = by_id.get(r.get("parent_account_id") or "")
    ptxt = f"  parent={parent.get('name')!r}" if parent else ("  parent=None" if r.get("parent_account_id") else "  parent=<root>")
    print(f"  {r.get('account_type'):10} {r['name']!r} active={r.get('is_active')}{ptxt}")
