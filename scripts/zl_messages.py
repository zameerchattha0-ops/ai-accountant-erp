"""Read-only: list ai-schema tables, then dump the last messages of a session."""
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
CONV = sys.argv[2] if len(sys.argv) > 2 else "a263f74e-8529-4ef5-9d5c-9e430a21d5fa"

# 1) ai schema tables
doc = httpx.get(
    f"{URL}/rest/v1/",
    headers={**HA, "Accept": "application/openapi+json"},
    timeout=45,
).json()
tables = sorted(doc.get("definitions", {}))
print("AI SCHEMA TABLES:")
for n in tables:
    print("  ", n)

# 2) probe message-ish tables for this conversation/session
for tname in tables:
    if not any(
        kw in tname for kw in ("message", "conversation", "response", "reply")
    ):
        continue
    r = httpx.get(
        f"{URL}/rest/v1/{tname}",
        headers=HA,
        params={"select": "*", "limit": "1"},
        timeout=30,
    ).json()
    cols = list(r[0].keys()) if isinstance(r, list) and r else r
    print(f"\n{tname} columns: {cols}")
    if isinstance(r, list) and r:
        # try conversation_id filter, then session id filter
        for filt_col, filt_val in (
            ("conversation_id", CONV),
            ("execution_session_id", SID),
        ):
            if filt_col in cols:
                rows = httpx.get(
                    f"{URL}/rest/v1/{tname}",
                    headers=HA,
                    params={
                        "select": "*",
                        filt_col: f"eq.{filt_val}",
                        "order": "created_at.asc",
                        "limit": "50",
                    },
                    timeout=30,
                ).json()
                print(
                    f"  rows for {filt_col}={filt_val}: "
                    f"{len(rows) if isinstance(rows, list) else rows}"
                )
