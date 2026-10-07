"""Read-only: count clarification rows per AES session vs history limit=20."""
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
        "select": "id,status,created_at",
        "organization_id": "eq.4c2922a2-6ae5-4774-900d-355db905b36a",
        "order": "created_at.desc",
        "limit": "15",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:300])
    sys.exit(2)

for s in rows:
    cl = httpx.get(
        f"{URL}/rest/v1/clarifications",
        headers=HA,
        params={
            "select": "created_at,question,user_response,status",
            "execution_session_id": f"eq.{s['id']}",
            "order": "created_at.asc",
            "limit": "500",
        },
        timeout=45,
    ).json()
    if isinstance(cl, dict):
        print(f"{s['id'][:8]}: clar ERR {json.dumps(cl)[:150]}")
        continue
    answered = [c for c in cl if c.get("user_response")]
    unanswered = [c for c in cl if not c.get("user_response")]
    # what get_clarification_history(limit=20, asc) would actually return
    hist20 = answered[:20]
    rev_in_all = [c for c in answered if "revenue ledger check:" in (c.get("question") or "").lower()]
    rev_in_20 = [c for c in hist20 if "revenue ledger check:" in (c.get("question") or "").lower()]
    print(
        f"{s['id'][:8]} [{s['status']:>17}] rows={len(cl):3} answered={len(answered):3} "
        f"unanswered={len(unanswered):2} | revenue answered rows={len(rev_in_all)} "
        f"| revenue WITHIN first-20-history={len(rev_in_20)}"
    )
