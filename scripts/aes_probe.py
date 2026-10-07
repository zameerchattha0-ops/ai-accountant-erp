"""Read-only probe: find AES Engineering sessions about child account /
Default Revenue creation failures. Single fast HTTP call, then a bounded
number of trail fetches. Usage: python scripts/aes_probe.py [needle]
"""
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
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept-Profile": "ai"}
TABLE = f"{URL}/rest/v1/execution_steps"

NEEDLE = sys.argv[1] if len(sys.argv) > 1 else "aes"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 15

# 1) RECEIVED rows whose user text mentions the needle (or revenue/account).
rows = httpx.get(
    TABLE,
    headers=H,
    params={
        "select": "execution_session_id,created_at,input_summary",
        "description": "eq.RECEIVED",
        "order": "created_at.desc",
        "limit": "120",
    },
    timeout=45,
).json()
if isinstance(rows, dict):
    print("API ERROR:", json.dumps(rows)[:500])
    sys.exit(2)

hits = [
    r
    for r in rows
    if NEEDLE in (r.get("input_summary") or "").lower()
    or "revenue" in (r.get("input_summary") or "").lower()
    or "account" in (r.get("input_summary") or "").lower()
]
print(f"scanned {len(rows)} RECEIVED rows, {len(hits)} match needle/account/revenue")
for r in hits[:LIMIT]:
    print(" ", r.get("created_at"), r["execution_session_id"],
          (r.get("input_summary") or "").replace("\n", " ")[:160])

# save ids for trail step
ids = [r["execution_session_id"] for r in hits[:LIMIT]]
(ERP / "aes_session_ids.json").write_text(json.dumps(ids, indent=2), encoding="utf-8")
print(f"wrote {len(ids)} ids -> aes_session_ids.json")
