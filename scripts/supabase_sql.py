#!/usr/bin/env python3
"""Execute a SQL statement against the Supabase Management API (pg meta endpoint).

Usage:
    python scripts/supabase_sql.py <sql-file>
    python scripts/supabase_sql.py --inline "SELECT 1"

Prints result rows (union of row-object keys, in first-seen order) as a
TSV table, or the error object.  Read-only queries only — this script runs
the docs/LATENCY_QUERIES.sql audit against the live project.

Credentials: SUPABASE_URL (+ optional SUPABASE_SERVICE_ROLE, unused here) from
.env; SUPABASE_ACCESS_TOKEN / sbp_ PAT from Supabase.txt or .env.  Values are
read, never printed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env_value(key: str) -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _pat() -> str:
    supa = ROOT / "Supabase.txt"
    if supa.exists():
        for line in supa.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"(sbp_[A-Za-z0-9]+)", line)
            if m:
                return m.group(1)
    for key in ("SUPABASE_ACCESS_TOKEN", "SUPABASE_PAT"):
        v = _env_value(key)
        if v:
            return v
    raise SystemExit("no Supabase PAT (sbp_) found in Supabase.txt or .env")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--inline":
        sql = " ".join(argv[1:])
    else:
        sql = Path(argv[0]).read_text(encoding="utf-8")

    url = _env_value("SUPABASE_URL") or ""
    m = re.search(r"([a-z]+)\.supabase\.co", url)
    if not m:
        raise SystemExit("SUPABASE_URL missing or malformed in .env")
    project_ref = m.group(1)

    body = json.dumps({"query": sql}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{project_ref}/database/query",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_pat()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {detail}")
        return 1

    if isinstance(payload, dict) and payload.get("error"):
        print(json.dumps(payload["error"]))
        return 1
    if not payload:
        print("(no rows)")
        return 0
    if isinstance(payload, dict):
        payload = [payload]

    columns: list[str] = []
    for row in payload:
        if isinstance(row, dict):
            for key in row:
                if key not in columns:
                    columns.append(key)
    print("\t".join(columns))
    for row in payload:
        if isinstance(row, dict):
            print("\t".join("" if row.get(c) is None else str(row[c]) for c in columns))
        else:
            print("\t".join(str(v) for v in row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
