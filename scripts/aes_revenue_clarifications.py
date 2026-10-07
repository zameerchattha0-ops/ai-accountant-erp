"""Read-only: show only revenue-ledger clarifications for AES sessions."""
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

rows = httpx.get(
    f"{URL}/rest/v1/clarifications",
    headers=HA,
    params={
        "select": "execution_session_id,created_at,question,user_response,required_information,options,status,answered_at",
        "execution_session_id": f"in.({','.join(ids)})",
        "order": "created_at.asc",
        "limit": "500",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

rev = [r for r in rows if "revenue ledger" in (r.get("question") or "").lower()]
print(f"total rows={len(rows)}, revenue-ledger rows={len(rev)}")
for r in rev:
    print(f"\n--- {str(r['created_at'])[:19]} session={str(r['execution_session_id'])[:8]} [{r['status']}]")
    print(f"  Q: {(r.get('question') or '')[:500]}")
    print(f"  A: {(r.get('user_response') or '')[:500]!r}")
    print(f"  fields: {r.get('required_information')}  answered_at: {r.get('answered_at')}")
    if r.get("options"):
        print(f"  options: {json.dumps(r['options'], ensure_ascii=False)[:400]}")

# Also: any OTHER answers that look like revenue decisions (YES / Create ... under ...)
cand = [
    r for r in rows
    if r.get("user_response")
    and "revenue" in (r.get("user_response") or "").lower()
    and r not in rev
]
print(f"\nother revenue-mentioning answers: {len(cand)}")
for r in cand[:20]:
    print(f"  {str(r['created_at'])[:19]} s={str(r['execution_session_id'])[:8]} Q={(r.get('question') or '')[:80]!r} A={(r.get('user_response') or '')[:120]!r}")
