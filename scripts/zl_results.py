"""Read-only: fetch execution_results for the session + probe public chat tables."""
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
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
HA = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept-Profile": "ai"}

SID = "afcfecae-124e-4baf-bb9a-7873b8bb5cee"
CONV = "a263f74e-8529-4ef5-9d5c-9e430a21d5fa"

# 1) execution_results (ai schema)
r = httpx.get(
    f"{URL}/rest/v1/execution_results",
    headers=HA,
    params={
        "select": "*",
        "execution_session_id": f"eq.{SID}",
        "order": "created_at.asc",
        "limit": "50",
    },
    timeout=45,
).json()
print(f"=== execution_results ({len(r) if isinstance(r, list) else 'ERR'}) ===")
if isinstance(r, list):
    for row in r:
        print(json.dumps(row, indent=2, default=str)[:6000])
        print("  ---")

# 2) probe public-schema chat/message tables
doc = httpx.get(
    f"{URL}/rest/v1/",
    headers={**H, "Accept": "application/openapi+json"},
    timeout=45,
).json()
pub = sorted(doc.get("definitions", {}))
cand = [
    t
    for t in pub
    if any(kw in t for kw in ("message", "chat", "conversation", "activity"))
]
print(f"\nPUBLIC tables of interest: {cand}")

for tname in cand:
    r = httpx.get(
        f"{URL}/rest/v1/{tname}",
        headers=H,
        params={"select": "*", "limit": "1"},
        timeout=30,
    ).json()
    cols = list(r[0].keys()) if isinstance(r, list) and r else r
    print(f"\n{tname} columns: {cols}")
    if not isinstance(r, list) or not r:
        continue
    for filt_col, filt_val in (
        ("conversation_id", CONV),
        ("execution_session_id", SID),
        ("session_id", SID),
    ):
        if filt_col in cols:
            rows = httpx.get(
                f"{URL}/rest/v1/{tname}",
                headers=H,
                params={
                    "select": "*",
                    filt_col: f"eq.{filt_val}",
                    "order": "created_at.asc",
                    "limit": "100",
                },
                timeout=30,
            ).json()
            n = len(rows) if isinstance(rows, list) else rows
            print(f"  rows by {filt_col}: {n}")
            if isinstance(rows, list) and rows:
                (ERP / f"zl_rows_{tname}.json").write_text(
                    json.dumps(rows, indent=2, default=str), encoding="utf-8"
                )
                print(f"  saved to zl_rows_{tname}.json")
