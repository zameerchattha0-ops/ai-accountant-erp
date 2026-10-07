"""Dump step trails for the saved AES session ids (bounded, fast)."""
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

ids = json.loads((ERP / "aes_session_ids.json").read_text(encoding="utf-8"))
only = sys.argv[1:] or ids

for sid in only:
    steps = httpx.get(
        f"{URL}/rest/v1/execution_steps",
        headers=H,
        params={
            "select": "step_order,created_at,description,status,input_summary,error_details",
            "execution_session_id": f"eq.{sid}",
            "order": "step_order.asc",
            "limit": "300",
        },
        timeout=45,
    ).json()
    if isinstance(steps, dict):
        print(f"ERROR {sid}: {json.dumps(steps)[:300]}")
        continue
    print(f"\n=== {sid} ({len(steps)} steps) ===")
    for st in steps:
        body = (st.get("input_summary") or "").replace("\n", " ")
        if len(body) > 500:
            body = body[:500] + " …"
        line = (
            f"  {st.get('step_order'):>3} {str(st.get('created_at'))[11:19]} "
            f"{st.get('description')} [{st.get('status')}] {body}"
        )
        err = st.get("error_details")
        if err:
            line += f"  ERROR={str(err)[:400]}"
        print(line)
