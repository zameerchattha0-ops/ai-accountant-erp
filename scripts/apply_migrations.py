"""Apply SQL migrations through the Supabase Management API.

There is no local Postgres CLI in this project (MASTER_PROMPT 7.5): the
database lives on Supabase and PostgREST cannot run DDL.  This runner is
the supported way to apply a migration — it needs only
``SUPABASE_ACCESS_TOKEN`` from ``E:\\Qoder\\.secrets\\tokens.env`` plus
``SUPABASE_URL`` (from ``.env`` / the secrets file) and never prints
secret values, only their lengths.

Modes::

    # apply a migration by basename (resolved under database/migrations/)
    python scripts/apply_migrations.py 086_payroll.sql
    # apply an arbitrary .sql file (probes, one-off DDL)
    python scripts/apply_migrations.py path/to/file.sql
    # no args: idempotent re-check of 084/085/086 + employees/payroll verify
    python scripts/apply_migrations.py
    # replay the browser's exact PostgREST GETs (console-404 hunting)
    python scripts/apply_migrations.py --rest

Each statement batch runs as one API call; a failing statement returns
HTTP 400 with the Postgres error and is reported per file (``FAIL``),
so one broken migration never hides the outcome of the others.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # scripts/ sits inside the repo root
SECRETS = Path(r"E:\Qoder\.secrets\tokens.env")
MIG = ROOT / "database" / "migrations"
FILES = [
    "084_create_employees.sql",
    "085_seed_employee_tools_control_plane.sql",
    "086_seed_payroll_tools_control_plane.sql",
]

VERIFY_SQL = """
select to_regclass('public.employees')            as employees,
       to_regclass('public.employee_allowances')  as allowances;
select slug, tool_type, status from ai.tools
 where slug in ('search_employee','get_employee',
                'create_employee','set_employee_allowances',
                'run_payroll','pay_employee_salary')
 order by slug;
select capability, allowed_tools from ai.permissions
 where capability in ('master_data', 'payroll')
 order by capability;
"""


def load_env(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            out[key.strip()] = value
    return out


def load_secrets() -> dict:
    merged = load_env(ROOT / ".env")          # repo defaults (SUPABASE_URL...)
    merged.update({k: v for k, v in load_env(SECRETS).items() if v})
    print("--- credential inventory (name -> value length) ---")
    for name in ("SUPABASE_URL", "SUPABASE_ACCESS_TOKEN",
                 "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL"):
        print(f"  {name}: {len(merged.get(name, ''))}")
    return merged


def query(ref: str, token: str, sql: str):
    """POST one SQL batch to the Management API; return parsed JSON."""
    body = json.dumps({"query": sql}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return None, f"HTTP {exc.code}: {detail[:2000]}"
    except Exception as exc:  # noqa: BLE001 - report anything the API throws
        return None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    sec = load_secrets()
    for required in ("SUPABASE_URL", "SUPABASE_ACCESS_TOKEN"):
        if required not in sec:
            print(f"FATAL: {required} missing from {SECRETS}")
            return 2
    ref_raw = sec["SUPABASE_URL"]
    import re as _re
    print("SUPABASE_URL shape:",
          _re.sub(r"[A-Za-z0-9]{10,}", "<ID>", ref_raw))
    if "//" in ref_raw:
        ref = ref_raw.split("//", 1)[1].split(".", 1)[0]
    else:
        ref = ref_raw.strip("/").split(".", 1)[0]
    token = sec["SUPABASE_ACCESS_TOKEN"]

    # --rest: replay the browser's exact PostgREST GETs from the console 404s
    if len(sys.argv) > 1 and sys.argv[1] == "--rest":
        anon = sec.get("SUPABASE_ANON_KEY", "")
        base = sec["SUPABASE_URL"].rstrip("/")
        for path in ("/rest/v1/employees?select=*&limit=1",
                     "/rest/v1/employee_allowances?select=*&limit=1"):
            req = urllib.request.Request(
                base + path,
                headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    print(f"{path} -> HTTP {resp.status}: "
                          f"{resp.read().decode()[:300]}")
            except urllib.error.HTTPError as exc:
                print(f"{path} -> HTTP {exc.code}: "
                      f"{exc.read().decode('utf-8', 'replace')[:300]}")
        return 0

    # file mode: each arg is an .sql path, or a basename under database/migrations/
    if len(sys.argv) > 1:
        failed = False
        for arg in sys.argv[1:]:
            path = Path(arg)
            if not path.exists() and (MIG / path.name).exists():
                path = MIG / path.name
            if not path.exists():
                print(f"FAIL  {arg}: file not found (tried as given and under {MIG})")
                failed = True
                continue
            result, err = query(ref, token, path.read_text(encoding="utf-8"))
            if err:
                print(f"FAIL  {path.name}: {err}")
                failed = True
            else:
                print(f"OK    {path.name}: {json.dumps(result)[:500]}")
        return 1 if failed else 0

    pre, err = query(ref, token,
                     "select to_regclass('public.employees') as employees, "
                     "to_regclass('public.employee_allowances') as allowances")
    print(f"pre-check: {'ok' if err is None else err}")
    if pre:
        print(f"pre-check rows: {json.dumps(pre)}")
    tables_exist = bool(pre and pre[0].get("employees"))

    failed = False
    for name in FILES:
        if name.startswith("084") and tables_exist:
            print(f"SKIP  {name}: employees table already exists")
            continue
        sql = (MIG / name).read_text(encoding="utf-8")
        result, err = query(ref, token, sql)
        if err:
            print(f"FAIL  {name}: {err}")
            failed = True
        else:
            print(f"OK    {name}: {json.dumps(result)[:500]}")

    print("--- verification ---")
    result, err = query(ref, token, VERIFY_SQL)
    if err:
        print(f"verify FAILED: {err}")
        return 1
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
