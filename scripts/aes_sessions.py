"""Read-only: list AES Engineering sessions (org id fixed), newest first."""
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

ORG = "4c2922a2-6ae5-4774-900d-355db905b36a"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 40

rows = httpx.get(
    f"{URL}/rest/v1/execution_sessions",
    headers=HA,
    params={
        "select": "id,status,current_phase,created_at,user_request",
        "organization_id": f"eq.{ORG}",
        "order": "created_at.desc",
        "limit": str(LIMIT),
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

print(f"{len(rows)} AES sessions:")
for r in rows:
    print(
        f"{r['created_at'][:19]}  {r['id']}  {r['status']:<18} "
        f"{(r.get('current_phase') or '-'):<24} "
        f"{(r.get('user_request') or '').replace(chr(10), ' ')[:110]}"
    )

ids = [r["id"] for r in rows]
(ERP / "aes_session_ids.json").write_text(json.dumps(ids, indent=2), encoding="utf-8")
