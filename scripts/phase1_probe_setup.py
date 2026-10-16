#!/usr/bin/env python3
"""Phase 1 Option A — probe identity + sandbox auth bootstrap (idempotent).

Ensures a real Supabase auth user exists, is an ACTIVE OWNER member of the
sandbox org (test-traders, 00000000-0000-4000-8000-000000000010), and holds
a fresh ES256 access token.  Writes (gitignored):
    .pytest_cache/probe_login.json {email,password}; probe_bearer.txt token
Optional preview check: --check-url https://... --bypass <secret>.
NEVER prints password or token values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".pytest_cache"
SANDBOX_ORG = "00000000-0000-4000-8000-000000000010"
OWNER_ROLE = "c6bc0316-6c82-4491-a58e-cc0d5efd88cf"
EMAIL = "phase1-probe@erptest.local"


def _env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{key} missing from .env")


def _req(url: str, *, method: str = "GET", headers: dict | None = None,
         body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-url")
    ap.add_argument("--bypass", default="")
    args = ap.parse_args()

    url = _env("SUPABASE_URL")
    svc = _env("SUPABASE_SERVICE_ROLE_KEY")
    anon = _env("SUPABASE_ANON_KEY")
    auth_h = {"apikey": svc, "Authorization": f"Bearer {svc}"}

    login_path = CACHE / "probe_login.json"
    if login_path.exists():
        creds = json.loads(login_path.read_text(encoding="utf-8"))
        print("credentials file: reused")
    else:
        creds = {"email": EMAIL, "password": "P1-" + secrets.token_urlsafe(18)}
        login_path.write_text(json.dumps(creds), encoding="utf-8")
        os.chmod(login_path, 0o600)
        print("credentials file: created")

    code, tok = _req(f"{url}/auth/v1/token?grant_type=password",
                     method="POST", headers={"apikey": anon},
                     body={"email": creds["email"], "password": creds["password"]})
    uid = None
    if code == 200 and tok.get("access_token"):
        import jwt as pyjwt
        uid = pyjwt.decode(tok["access_token"], options={"verify_signature": False})["sub"]
        print(f"auth user exists (login ok): {uid}")
    else:
        code2, body = _req(f"{url}/auth/v1/admin/users", method="POST",
                           headers=auth_h,
                           body={"email": creds["email"],
                                 "password": creds["password"],
                                 "email_confirm": True})
        if code2 in (200, 201):
            uid = body["id"]
            print(f"auth user created: {uid}")
        else:
            ref0 = re.search(r"([a-z]+)\.supabase\.co", url).group(1)
            pat0 = None
            for line in (ROOT / "Supabase.txt").read_text(
                    encoding="utf-8", errors="replace").splitlines():
                m = re.search(r"(sbp_[A-Za-z0-9]+)", line)
                if m:
                    pat0 = m.group(1)
                    break
            code3, body3 = _req(
                f"https://api.supabase.com/v1/projects/{ref0}/auth/users",
                method="POST",
                headers={"Authorization": f"Bearer {pat0}"},
                body={"email": creds["email"], "password": creds["password"],
                      "email_confirm": True})
            if code3 not in (200, 201):
                print(f"create user failed: gotouser={code2} mgmt={code3}")
                return 1
            uid = body3.get("id") or body3.get("user", {}).get("id")
            print(f"auth user created (mgmt api): {uid}")
    if not uid:
        print("no uid resolved")
        return 1

    ref = re.search(r"([a-z]+)\.supabase\.co", url).group(1)
    supa_pat = None
    for line in (ROOT / "Supabase.txt").read_text(
            encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"(sbp_[A-Za-z0-9]+)", line)
        if m:
            supa_pat = m.group(1)
            break
    if not supa_pat:
        print("no sbp_ PAT found (Supabase.txt)")
        return 1
    sql = (
        "insert into public.organization_members "
        "(id, organization_id, user_id, role_id, status) "
        "select gen_random_uuid(), "
        f"'{SANDBOX_ORG}', '{uid}', '{OWNER_ROLE}', 'ACTIVE' "
        "where not exists (select 1 from public.organization_members m "
        f"where m.user_id = '{uid}' "
        f"and m.organization_id = '{SANDBOX_ORG}') returning id;"
    )
    code, body = _req(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        method="POST",
        headers={"Authorization": f"Bearer {supa_pat}"},
        body={"query": sql},
    )
    nrows = len(body) if isinstance(body, list) else "?"
    print(f"membership ensure: HTTP {code} rows={nrows}")

    code, tok = _req(f"{url}/auth/v1/token?grant_type=password",
                     method="POST", headers={"apikey": anon},
                     body={"email": creds["email"], "password": creds["password"]})
    if code != 200 or not tok.get("access_token"):
        print(f"login failed: HTTP {code}")
        return 1
    bearer = tok["access_token"]
    bp = CACHE / "probe_bearer.txt"
    bp.write_text(bearer, encoding="utf-8")
    os.chmod(bp, 0o600)
    print(f"token acquired (len {len(bearer)}) -> {bp.name}")

    if args.check_url:
        target = (f"{args.check_url}/api/ai/providers"
                  f"?x-vercel-protection-bypass={args.bypass}"
                  "&x-vercel-set-bypass-cookie=true")
        req = urllib.request.Request(target,
                                     headers={"Authorization": f"Bearer {bearer}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                print(f"preview auth check: HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:200]
            print(f"preview auth check: HTTP {exc.code} {detail}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
