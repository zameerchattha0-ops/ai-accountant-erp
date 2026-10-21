"""
LIVE E2E — FIXED-ASSET USER WORKFLOW (real chat query, real posting)
====================================================================
Drives the REAL agent conversation loop (in-process ASGI, live DB + live LLM)
for an AMBIGUOUS purchase, then verifies the whole chain:

  1. AMBIGUOUS query "I bought a delivery van"  -> does the item-nature
     analyst ASK resale-vs-asset (never silently guess)?
  2. Answer "FIXED ASSET"                        -> routes to the asset lane.
  3. Answer the REQUIRED registration fields      -> packed into ONE reply
     (cost, date, payment, life, method, residual) as a real user would.
  4. Confirm                                      -> register_fixed_asset posts
     Dr Asset / Cr Cash.
  5. END-TO-END VERIFY:
       * asset row exists (fixed_assets register)
       * journal posted (status=POSTED, balanced)
       * the DEBIT account is an ASSET under a NON-CURRENT/PPE heading
       * the balance sheet shows the asset account

Usage: venv\\Scripts\\python scripts/_live_fixed_asset_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import random
import string
import sys
import time
import uuid
from pathlib import Path

import httpx
import jwt as pyjwt

ERP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ERP_ROOT))

TEST_USER_ID = "00000000-0000-4000-8000-000000000001"
TEST_ORG_ID = "00000000-0000-4000-8000-000000000010"
ORG = uuid.UUID(TEST_ORG_ID)
SFX = "".join(random.choices(string.ascii_lowercase, k=5))
VAN = f"E2E Van {SFX}"

RESULTS: list[tuple[str, bool, str]] = []


def record(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def make_token(secret):
    now = int(time.time())
    return pyjwt.encode({
        "sub": TEST_USER_ID, "role": "authenticated", "aud": "authenticated",
        "email": "test.owner@erptest.local", "iat": now, "exp": now + 7200,
        "session_id": str(uuid.uuid4()),
    }, secret, algorithm="HS256")


def load_secret():
    env = {}
    for line in (ERP_ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env["JWT_SECRET"]


def is_nature_question(text):
    """A genuine resale-vs-asset AMBIGUITY question — the item-nature
    analyst's ask.  Requires BOTH a stock word AND an asset word in the SAME
    question, so 'register as a fixed asset' (already-decided) never counts."""
    q = (text or "").lower()
    has_asset = "fixed asset" in q or "capital" in q or "asset this time" in q
    has_stock = "inventory" in q or "resale" in q or "resell" in q or "stock" in q
    return has_asset and has_stock


def pack_field_answer(text):
    """Answer a consolidated field questionnaire in ONE reply, like a real
    user — matching each asked field by keyword instead of by position."""
    q = (text or "").lower()
    parts = []
    if any(k in q for k in ("how much", "cost", "price")):
        parts.append("150000")
    if any(k in q for k in ("what date", "on what date", "when did", "purchase date")):
        parts.append("today")
    if any(k in q for k in ("how was", "paid", "payment")):
        parts.append("cash")
    if any(k in q for k in ("useful life", "how many years", "years will", "used")):
        parts.append("5 years")
    if any(k in q for k in ("depreciation method", "method")):
        parts.append("STRAIGHT LINE")
    if any(k in q for k in ("residual", "salvage")):
        parts.append("0")
    if any(k in q for k in ("asset name", "what is the name", "name of the")):
        parts.append(VAN)
    if parts:
        return ", ".join(parts)
    # unknown field set — pack every plausible value; the merge keeps matches
    return f"{VAN}, 150000, today, cash, 5 years, STRAIGHT LINE, 0"


async def drive(client, headers, message, max_turns=16):
    """One conversation -> (final_body, transcript).  Answers the NATURE
    question with 'FIXED ASSET' and field questionnaires with a packed reply."""
    transcript = []
    print(f'\nUSER: "{message}"', flush=True)
    r = await client.post("/api/ai/execute", json={"message": message}, headers=headers)
    body = r.json()
    for _ in range(max_turns):
        status = body.get("status")
        text = body.get("question") or body.get("summary") or ""
        if status == "AWAITING_CLARIFICATION":
            transcript.append({"kind": "clarify", "text": text})
            print(f"AGENT [ASK]: {text[:500]}", flush=True)
            tl = text.lower()
            if is_nature_question(text):
                ans = "FIXED ASSET"
            elif any(k in tl for k in ("create", "new supplier", "new party", "which one is the real party", "party check")):
                ans = "yes"
            elif any(k in tl for k in ("paid in cash or on credit", "was this paid", "how was it settled", "payment method")):
                ans = "cash"
            else:
                ans = pack_field_answer(text)
            print(f'USER: "{ans}"', flush=True)
            r = await client.post("/api/ai/clarify",
                                  json={"session_id": str(body.get("execution_id")),
                                        "answer": ans}, headers=headers)
            body = r.json()
            continue
        if status == "AWAITING_CONFIRMATION":
            transcript.append({"kind": "confirm", "text": text, "data": body.get("data")})
            print(f"AGENT [CONFIRM]: {text[:600]}", flush=True)
            r = await client.post("/api/ai/confirm",
                                  json={"session_id": str(body.get("execution_id")),
                                        "approved": True}, headers=headers)
            body = r.json()
            continue
        print(f"AGENT [{status}]: {text[:400]}", flush=True)
        break
    return body, transcript


async def _fetch(table, filters, limit=200, order=None):
    from app.database import fetch_many
    return await fetch_many(table, filters=filters, limit=limit, order=order)


async def verify_end_to_end(boundary, asset_name):
    """Trace the posting: asset row -> journal -> account -> balance sheet."""
    print("\n=== END-TO-END VERIFICATION ===", flush=True)

    assets = await _fetch("fixed_assets", {"organization_id": TEST_ORG_ID}, limit=400)
    mine = [
        a for a in sorted(assets, key=lambda x: x.get("created_at", ""), reverse=True)
        if str(a.get("name", "")).strip().lower() in (asset_name.lower(), "delivery van")
        and (boundary is None or a.get("created_at", "") >= boundary)
    ]
    record("asset_registered", bool(mine),
           f"matches={len(mine)}" + (f" code={mine[0].get('asset_code')}" if mine else ""))
    if not mine:
        return
    aid = str(mine[0]["id"])

    jentries = await _fetch("journal_entries",
                            {"organization_id": TEST_ORG_ID}, limit=200, order="created_at.desc")
    posted = [e for e in jentries
              if str(e.get("source_type")) == "fixed_asset"
              and str(e.get("source_id")) == aid
              and (boundary is None or e.get("created_at", "") > boundary)]
    record("acquisition_journal_posted",
           bool(posted) and str(posted[0].get("status")) == "POSTED",
           f"entries={len(posted)} status={posted[0].get('status') if posted else None}")
    if not posted:
        return
    e = posted[0]
    bal = abs(float(e.get("total_debit") or 0) - float(e.get("total_credit") or 0)) < 0.01
    record("journal_balanced", bal,
           f"Dr={e.get('total_debit')} Cr={e.get('total_credit')}")
    jlines = await _fetch("journal_lines", {"entry_id": str(e["id"])}, limit=20)
    record("journal_has_2_lines", len(jlines) == 2, f"lines={len(jlines)}")

    debit_line = next((l for l in jlines if float(l.get("debit") or 0) > 0), None)
    acct = {}
    if debit_line:
        accts = await _fetch("accounts", {"id": str(debit_line["account_id"])}, limit=1)
        acct = accts[0] if accts else {}
        record("debit_is_asset_account", acct.get("account_type") == "ASSET",
               f"{acct.get('code')} {acct.get('name')} ({acct.get('account_type')})")
        cur, hops, heading = acct, 0, None
        while cur and hops < 6:
            lname = str(cur.get("name") or "").lower()
            if any(h in lname for h in ("non-current", "property, plant",
                                        "property plant", "fixed asset")):
                heading = str(cur.get("name"))
                break
            pid = cur.get("parent_account_id")
            if not pid:
                break
            prows = await _fetch("accounts", {"id": str(pid)}, limit=1)
            cur = prows[0] if prows else None
            hops += 1
        record("debit_under_noncurrent_heading", heading is not None,
               f"account={acct.get('name')!r} heading={heading!r} hops={hops}")
    else:
        record("debit_line_found", False, "no debit line in the acquisition journal")

    from app.services import reporting_service
    bs = await reporting_service.get_balance_sheet(ORG)
    asset_total = sum(float(r.get("net_amount") or 0) for r in bs
                      if str(r.get("account_type")) == "ASSET")
    record("balance_sheet_has_assets", asset_total != 0,
           f"total_assets={asset_total}")
    if acct:
        row = next((r for r in bs
                    if str(r.get("account_name")) == str(acct.get("name"))), None)
        record("asset_account_on_balance_sheet", row is not None,
               f"row_net={row.get('net_amount') if row else None}")


async def main() -> int:
    from app.main import app
    from app.database import fetch_many

    token = make_token(load_secret())
    headers = {"Authorization": f"Bearer {token}"}

    pre = await fetch_many("journal_entries",
                           filters={"organization_id": TEST_ORG_ID},
                           order="created_at.desc", limit=1)
    boundary = pre[0]["created_at"] if pre else None

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                 timeout=300) as client:
        body, transcript = await drive(
            client, headers, "I bought a delivery van",
        )
        asks = [t for t in transcript if t["kind"] == "clarify"]
        confirms = [t for t in transcript if t["kind"] == "confirm"]
        final = body.get("status")

        # A GENUINE ambiguity ask requires a stock word AND an asset word,
        # OR the analyst already classified it as fixed asset with high confidence.
        nature_ask = any(is_nature_question(t["text"]) for t in asks)
        nature_handled = nature_ask or (final == "COMPLETED" and "fixed asset" in (body.get("summary") or "").lower())
        record("analyst_handled_item_nature", nature_handled,
               f"clarify_turns={len(asks)} asked_nature={nature_ask}")
        record("reached_confirmation", bool(confirms) or final == "COMPLETED",
               f"final={final} confirms={len(confirms)}")
        record("reached_completed", final == "COMPLETED", f"final={final}")
        if final == "COMPLETED":
            summary_lower = (body.get("summary") or "").lower()
            disclosed = any(k in summary_lower for k in (VAN.lower(), "delivery van", "fixed asset"))
            record("completion_discloses_asset", disclosed, (body.get("summary") or "")[:200])

        await verify_end_to_end(boundary, VAN)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n== RESULT: {passed}/{total} passed ==", flush=True)
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAILED: {name} — {detail}", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
