"""Dump every recorded step of one session as UTF-8 JSON (full fields).

Usage: python scripts/dump_session.py <execution_session_id> [out.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ERP = Path(r"e:\Qoder\Ai Accountant\ERP")
env: dict[str, str] = {}
for line in (ERP / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

HEADERS = {
    "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
    "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
    "Accept-Profile": "ai",
}

sid = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "session_dump.json"
rows = httpx.get(
    f"{env['SUPABASE_URL']}/rest/v1/execution_steps",
    headers=HEADERS,
    params={
        "select": "*",
        "execution_session_id": f"eq.{sid}",
        "order": "step_order.asc",
        "limit": "400",
    },
    timeout=30,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)
path = ERP / out
path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {path} ({len(rows)} rows)")
for r in rows:
    err = r.get("error_details")
    if err:
        print(f"\n--- step {r.get('step_order')} {r.get('description')} ERROR ---")
        print(str(err))
