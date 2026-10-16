#!/usr/bin/env python3
"""Phase 1 Option A — sandbox probe runner against the preview deployment.

Drives scripted expense-family turns through POST /api/ai/execute (plus
clarify/confirm follow-ups) as the probe identity, capturing every stage.
All traffic targets the sandbox org (test-traders) resolved server-side from
the probe user's membership — never a real organization.

Usage:
    python scripts/phase1_probe_runner.py --url https://... --bypass <secret>
        [--batch smoke] [--delay 5] [--max-probes 4]

Writes .pytest_cache/phase1_probes_<batch>.json (gitignored).  Never prints
the bearer token.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".pytest_cache"


def _env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{key} missing from .env")


def login() -> str:
    """Fresh ES256 access token via password grant (never printed)."""
    creds = json.loads((CACHE / "probe_login.json").read_text(encoding="utf-8"))
    url = _env("SUPABASE_URL")
    anon = _env("SUPABASE_ANON_KEY")
    req = urllib.request.Request(
        f"{url}/auth/v1/token?grant_type=password",
        data=json.dumps(creds).encode(), method="POST",
        headers={"apikey": anon, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        tok = json.loads(resp.read().decode())
    return tok["access_token"]

# probe: (id, message, per-field answer prefs).  Pref "~regex" = first
# option label matching; any other string = free-text fallback; absent
# field = first option, else NUMERIC_DEFAULTS, else "yes".
from datetime import date as _date  # noqa: E402

_NUM_DEFAULTS = {
    "amount": "1200",  # probe sandbox values when the message states none
    "salvage_value": "0",
    "useful_life_years": "60",
    "transaction_date": _date.today().isoformat(),
}
SMOKE = [
    ("p1-ordinary-expense",
     "I spent 450 at Staples on office supplies today.",
     {"transaction_purpose": "~something else",
      "settlement_position": "~paid now.*cash"}),
    ("p2-van-purchase",
     "Bought a delivery van for 8,500 cash from Quick Motors yesterday.",
     {"transaction_purpose": "~equipment",
      "settlement_position": "~paid now.*cash",
      "amount": "8500"}),
    ("p3-vague-payment",
     "Paid some money to Ali yesterday.",
     {"transaction_purpose": "Consulting services",
      "settlement_position": "~paid now", "amount": "4000"}),
    ("p4-credit-laptop",
     "I bought a laptop from ABC Computers on credit.",
     {"transaction_purpose": "~equipment",
      "settlement_position": "~payable",
      "amount": "1200"}),
]


def _parse_set_cookie(header: str) -> str:
    for part in header.split(","):
        part = part.strip()
        if part.startswith("_vercel_jwt="):
            return part.split(";", 1)[0]
    return ""


def call(url: str, bypass: str, path: str, body: dict,
         state: dict, _retry: bool = True) -> tuple[int, dict]:
    """POST with Vercel SSE-protection handling: first POST → 307 with a
    _vercel_jwt Set-Cookie; resend to the BARE path (redirect Location)
    carrying the cookie — the query param alone never clears SSE
    protection.  A 401 refreshes the access token once and retries."""
    full = (f"{url}{path}?x-vercel-protection-bypass={bypass}"
            "&x-vercel-set-bypass-cookie=true")
    bare = f"{url}{path}"

    def _send(target: str, cookie: str) -> tuple[int, dict, str]:
        headers = {"Authorization": f"Bearer {state['token']}",
                   "Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(
            target, data=json.dumps(body).encode(), method="POST",
            headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.status, json.loads(resp.read().decode()), ""
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            sc = _parse_set_cookie(exc.headers.get("Set-Cookie", ""))
            try:
                return exc.code, json.loads(raw), sc
            except json.JSONDecodeError:
                return exc.code, {"raw": raw[:300]}, sc

    code, parsed, sc = _send(full, state.get("cookie", ""))
    if code == 307:
        if sc:
            state["cookie"] = sc
        code, parsed, _ = _send(bare, state.get("cookie", ""))
    if code == 401 and _retry:
        state["token"] = login()
        state.pop("cookie", None)
        return call(url, bypass, path, body, state, _retry=False)
    return code, parsed


def build_answers(body: dict, prefs: dict) -> list[dict]:
    """Field-routed answers for the FIXED-FORMAT questionnaire: one
    {field, answer} per open question, preferring the probe's per-field
    option-regex or free-text preference (see SMOKE)."""
    import re as _re

    qs = (body.get("questionnaire") or {}).get("questions") or []
    out: list[dict] = []
    for q in qs:
        field = str(q.get("field") or "answer")
        opts = [o for o in (q.get("options") or []) if isinstance(o, dict)]
        pref = prefs.get(field)
        value = None
        if isinstance(pref, str) and pref.startswith("~"):
            pat = _re.compile(pref[1:], _re.I)
            for o in opts:
                if pat.search(str(o.get("label") or "")):
                    value = o.get("value")
                    break
        if value is None and opts:
            value = opts[0].get("value")
        if value is None and isinstance(pref, str):
            value = pref
        if value is None and field in _NUM_DEFAULTS:
            value = _NUM_DEFAULTS[field]
        if value is None:
            value = "yes"
        out.append({"field": field, "answer": str(value)})
    return out


def trim(stage: dict) -> dict:
    keys = ("status", "execution_id", "action", "summary", "question",
            "required_information", "verification_status",
            "requires_user_input", "detail")
    return {k: stage.get(k) for k in keys if stage.get(k) is not None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--bypass", required=True)
    ap.add_argument("--batch", default="smoke")
    ap.add_argument("--delay", type=float, default=5.0)
    ap.add_argument("--max-probes", type=int, default=4)
    ap.add_argument("--only", default="",
                    help="comma-separated probe ids (e.g. p4-credit-laptop)")
    args = ap.parse_args()

    state: dict = {"token": login()}
    results: list[dict] = []
    probes = ([p for p in SMOKE if p[0] in args.only.split(",")]
              if args.only else SMOKE[: args.max_probes])

    for pid, message, prefs in probes:
        rec: dict = {"probe": pid, "message": message, "stages": []}
        t0 = time.time()
        code, body = call(args.url, args.bypass, "/api/ai/execute",
                          {"message": message}, state)
        rec["stages"].append({"endpoint": "execute", "http": code, **trim(body)})
        print(f"[{pid}] execute HTTP {code} status={body.get('status')} "
              f"q={str(body.get('question'))[:60]!r}")

        for _ in range(6):
            status = body.get("status")
            sid = body.get("execution_id")
            if status == "AWAITING_CLARIFICATION" and sid:
                routed = build_answers(body, prefs)
                payload = {"session_id": sid,
                           "answer": routed[0]["answer"] if routed else "yes",
                           "answers": routed or None}
                time.sleep(args.delay)
                code, body = call(args.url, args.bypass, "/api/ai/clarify",
                                  payload, state)
                rec["stages"].append({"endpoint": "clarify", "http": code,
                                      "sent": payload["answer"],
                                      "sent_fields": [a["field"] for a in routed],
                                      **trim(body)})
                print(f"[{pid}] clarify HTTP {code} status={body.get('status')} "
                      f"fields={[a['field'] for a in routed]}")
            elif status == "AWAITING_CONFIRMATION" and sid:
                time.sleep(args.delay)
                code, body = call(args.url, args.bypass, "/api/ai/confirm",
                                  {"session_id": sid, "approved": True}, state)
                rec["stages"].append({"endpoint": "confirm", "http": code,
                                      "sent": "approved=True", **trim(body)})
                print(f"[{pid}] confirm HTTP {code} status={body.get('status')} "
                      f"verified={body.get('verification_status')}")
            else:
                break
        rec["elapsed_s"] = round(time.time() - t0, 1)
        results.append(rec)
        time.sleep(args.delay)

    out = CACHE / f"phase1_probes_{args.batch}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n{len(results)} probes -> {out.name}")
    bad = [r["probe"] for r in results if any(
        s["http"] >= 500 for s in r["stages"])]
    if bad:
        print(f"5xx probes: {bad}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
