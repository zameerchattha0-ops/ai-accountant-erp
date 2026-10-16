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

# probe: (id, message, canned clarify answers list)
SMOKE = [
    ("p1-ordinary-expense",
     "I spent 450 at Staples on office supplies today.", []),
    ("p2-van-purchase",
     "Bought a delivery van for 8,500 cash from Quick Motors yesterday.", []),
    ("p3-vague-payment",
     "Paid some money to Ali yesterday.", ["4,000 for consulting work"]),
    ("p4-credit-laptop",
     "I bought a laptop from ABC Computers on credit.", ["1,200"]),
]


def _parse_set_cookie(header: str) -> str:
    for part in header.split(","):
        part = part.strip()
        if part.startswith("_vercel_jwt="):
            return part.split(";", 1)[0]
    return ""


def call(url: str, token: str, bypass: str, path: str, body: dict,
         state: dict) -> tuple[int, dict]:
    """POST with Vercel SSE-protection handling: first POST → 307 with a
    _vercel_jwt Set-Cookie; resend to the BARE path (redirect Location)
    carrying the cookie — the query param alone never clears SSE protection."""
    full = (f"{url}{path}?x-vercel-protection-bypass={bypass}"
            "&x-vercel-set-bypass-cookie=true")
    bare = f"{url}{path}"

    def _send(target: str, cookie: str) -> tuple[int, dict, str]:
        headers = {"Authorization": f"Bearer {token}",
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
    return code, parsed


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
    args = ap.parse_args()

    token = (CACHE / "probe_bearer.txt").read_text(encoding="utf-8").strip()
    state: dict = {}
    results: list[dict] = []

    for pid, message, answers in SMOKE[: args.max_probes]:
        rec: dict = {"probe": pid, "message": message, "stages": []}
        t0 = time.time()
        code, body = call(args.url, token, args.bypass, "/api/ai/execute",
                          {"message": message}, state)
        rec["stages"].append({"endpoint": "execute", "http": code, **trim(body)})
        print(f"[{pid}] execute HTTP {code} status={body.get('status')} "
              f"q={str(body.get('question'))[:60]!r}")

        answer_i = 0
        for _ in range(4):
            status = body.get("status")
            sid = body.get("execution_id")
            if status == "AWAITING_CLARIFICATION" and sid:
                ans = answers[answer_i] if answer_i < len(answers) else "cash"
                answer_i += 1
                time.sleep(args.delay)
                code, body = call(args.url, token, args.bypass, "/api/ai/clarify",
                                  {"session_id": sid, "answer": ans}, state)
                rec["stages"].append({"endpoint": "clarify", "http": code,
                                      "sent": ans, **trim(body)})
                print(f"[{pid}] clarify HTTP {code} status={body.get('status')}")
            elif status == "AWAITING_CONFIRMATION" and sid:
                time.sleep(args.delay)
                code, body = call(args.url, token, args.bypass, "/api/ai/confirm",
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
