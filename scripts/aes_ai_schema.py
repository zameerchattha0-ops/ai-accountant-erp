"""Read-only: list ai-schema tables; sanity-check tool_calls across org."""
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

# OpenAPI doc lists tables in the ai schema
doc = httpx.get(
    f"{URL}/rest/v1/",
    headers={**HA, "Accept": "application/openapi+json"},
    timeout=45,
).json()
defs = doc.get("definitions", {})
print(f"ai schema tables ({len(defs)}):")
for name in sorted(defs):
    print("  ", name)

# sanity: any tool_calls at all? and count per recent session
tc = httpx.get(
    f"{URL}/rest/v1/tool_calls",
    headers=HA,
    params={"select": "execution_session_id", "limit": "5", "order": "created_at.desc"},
    timeout=45,
).json()
print("\nrecent tool_calls sample:", json.dumps(tc)[:400])

# execution steps table?
for tname in ("execution_steps", "steps", "session_steps", "plan_steps", "execution_step"):
    r = httpx.get(
        f"{URL}/rest/v1/{tname}",
        headers=HA,
        params={"select": "*", "limit": "1"},
        timeout=30,
    ).json()
    kind = "OK cols=" + ",".join(list(r[0].keys())) if isinstance(r, list) and r else ("OK empty" if isinstance(r, list) else r.get("message"))
    print(f"{tname}: {kind}")
