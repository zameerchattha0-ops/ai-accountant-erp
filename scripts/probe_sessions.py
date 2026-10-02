"""List the newest agent sessions (and their last steps) from production.

Usage:
    python scripts/probe_sessions.py [limit]
"""
from __future__ import annotations

import sys
import pathlib
import httpx

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env: dict[str, str] = {}
for _line in (_ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _v = _line.split("=", 1)
        _env[_k.strip()] = _v.strip().strip('"').strip("'")

URL = _env["SUPABASE_URL"]
KEY = _env["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def main() -> None:  # pragma: no cover - diagnostic
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    # find the sessions table
    root = httpx.get(f"{URL}/rest/v1/", headers=H, params={"select": "*"}, timeout=30)
    import re

    names = sorted(set(re.findall(r'"([a-z_]*session[a-z_]*)"', root.text)))
    print("session-ish tables:", names)
    table = next((n for n in names if "step" not in n), None)
    if not table:
        return
    rows = httpx.get(
        f"{URL}/rest/v1/{table}",
        headers=H,
        params={
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        },
        timeout=30,
    ).json()
    if isinstance(rows, dict):
        print("error:", rows)
        return
    for r in rows:
        print(
            {k: r.get(k) for k in list(r)[:10]}
        )


if __name__ == "__main__":
    main()
