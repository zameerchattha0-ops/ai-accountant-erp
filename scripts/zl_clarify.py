"""Read-only: dump clarifications + confirmations for a session (ai schema)."""
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

SID = sys.argv[1] if len(sys.argv) > 1 else "afcfecae-124e-4baf-bb9a-7873b8bb5cee"

for tname in ("clarifications", "confirmations"):
    r = httpx.get(
        f"{URL}/rest/v1/{tname}",
        headers=HA,
        params={
            "select": "*",
            "execution_session_id": f"eq.{SID}",
            "order": "created_at.asc",
            "limit": "50",
        },
        timeout=45,
    ).json()
    print(f"=== {tname} ({len(r) if isinstance(r, list) else 'ERR'}) ===")
    if isinstance(r, list):
        for row in r:
            print(json.dumps(row, indent=2, default=str)[:4000])
            print("  ---")
    else:
        print(json.dumps(r)[:500])
