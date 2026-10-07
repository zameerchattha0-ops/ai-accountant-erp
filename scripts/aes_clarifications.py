"""Read-only: dump ai_clarifications rows (question/answer/fields) for AES sessions."""
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

ids = json.loads((ERP / "aes_session_ids.json").read_text(encoding="utf-8"))
# newest first in listing; dump all clarifications for these sessions
rows = httpx.get(
    f"{URL}/rest/v1/clarifications",
    headers=HA,
    params={
        "select": "execution_session_id,created_at,question,user_response,required_information,options,status",
        "execution_session_id": f"in.({','.join(ids)})",
        "order": "created_at.asc",
        "limit": "200",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

print(f"{len(rows)} clarification rows")
for r in rows:
    print(f"\n--- {str(r['created_at'])[:19]}  session={str(r['execution_session_id'])[:8]}  [{r['status']}]")
    print(f"  Q: {(r.get('question') or '')[:400]}")
    print(f"  A: {(r.get('user_response') or '')[:400]}")
    print(f"  fields: {r.get('required_information')}")
    if r.get("options"):
        print(f"  options: {json.dumps(r['options'])[:300]}")
