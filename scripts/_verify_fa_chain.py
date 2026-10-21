"""Single focused DB verification: find the MOST RECENT fixed asset created
by the E2E run (regardless of name) and trace its FULL end-to-end chain:
  asset row -> journal (posted, balanced) -> debit account -> parent heading
  (non-current / PPE) -> balance sheet row.
One query-pass, minimal turns.  Usage: python scripts/_verify_fa_chain.py"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ERP_ROOT))

ORG = "00000000-0000-4000-8000-000000000010"


async def _fetch(table, filters, limit=100, order=None, select=None):
    from app.database import fetch_many
    kw = {"filters": filters, "limit": limit}
    if order:
        kw["order"] = order
    if select:
        kw["select"] = select
    return await fetch_many(table, **kw)


async def main() -> int:
    print("=== MOST RECENT FIXED ASSET (last 30 min) ===")
    assets = await _fetch("fixed_assets", {"organization_id": ORG},
                          limit=50, order="created_at.desc")
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    recent = []
    for a in assets:
        ca = a.get("created_at") or ""
        try:
            t = dt.datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            if (now - t).total_seconds() < 1800:
                recent.append(a)
        except Exception:
            continue
    if not recent:
        print("  no asset created in the last 30 min")
        return 1
    a = recent[0]
    print(f"  id={a['id']}")
    print(f"  name={a.get('name')!r} code={a.get('asset_code')} "
          f"cost={a.get('purchase_cost')} date={a.get('purchase_date')} "
          f"life={a.get('useful_life_years')} salvage={a.get('salvage_value')} "
          f"method={a.get('depreciation_method')}")
    print(f"  gl_asset_account_id={a.get('gl_asset_account_id')}")
    aid = str(a["id"])

    print("\n=== ACQUISITION JOURNAL ===")
    jents = await _fetch("journal_entries", {"organization_id": ORG},
                         limit=100, order="created_at.desc")
    posted = [e for e in jents
              if str(e.get("source_type")) == "fixed_asset"
              and str(e.get("source_id")) == aid]
    if not posted:
        print("  NO journal source-tied to this asset!")
        return 1
    e = posted[0]
    print(f"  journal={e.get('journal_number')} status={e.get('status')} "
          f"Dr={e.get('total_debit')} Cr={e.get('total_credit')} "
          f"desc={e.get('description')!r}")

    lines = await _fetch("journal_lines", {"entry_id": str(e["id"])}, limit=10)
    for l in lines:
        accs = await _fetch("accounts", {"id": str(l["account_id"])}, limit=1)
        acc = accs[0] if accs else {}
        side = "Dr" if float(l.get("debit") or 0) > 0 else "Cr"
        val = l.get("debit") if side == "Dr" else l.get("credit")
        print(f"  {side} {acc.get('code')} {acc.get('name')!r} "
              f"({acc.get('account_type')}) = {val}")

    # walk the DEBIT account's parent chain to the section heading
    debit_line = next((l for l in lines if float(l.get("debit") or 0) > 0), None)
    if debit_line:
        accs = await _fetch("accounts", {"id": str(debit_line["account_id"])}, limit=1)
        cur = accs[0] if accs else {}
        print("\n=== DEBIT ACCOUNT -> HEADING (parent chain) ===")
        hops, heading = 0, None
        while cur and hops < 7:
            print(f"  {'  ' * hops}{cur.get('code')} {cur.get('name')!r} "
                  f"({cur.get('account_type')})")
            lname = str(cur.get("name") or "").lower()
            if any(h in lname for h in ("non-current", "property, plant",
                                        "property plant", "fixed asset")):
                heading = str(cur.get("name"))
            pid = cur.get("parent_account_id")
            if not pid:
                break
            prows = await _fetch("accounts", {"id": str(pid)}, limit=1)
            cur = prows[0] if prows else None
            hops += 1
        print(f"  => NON-CURRENT HEADING: {heading!r}")

    print("\n=== BALANCE SHEET (this account) ===")
    from app.services import reporting_service
    import uuid as _uuid
    bs = await reporting_service.get_balance_sheet(_uuid.UUID(ORG))
    if debit_line:
        accs = await _fetch("accounts", {"id": str(debit_line["account_id"])}, limit=1)
        acc = accs[0] if accs else {}
        row = next((r for r in bs
                    if str(r.get("account_name")) == str(acc.get("name"))), None)
        if row:
            print(f"  {row.get('account_code')} {row.get('account_name')!r} "
                  f"type={row.get('account_type')} net={row.get('net_amount')}")
        else:
            print(f"  account {acc.get('name')!r} NOT on balance sheet")
    total_assets = sum(float(r.get("net_amount") or 0) for r in bs
                       if str(r.get("account_type")) == "ASSET")
    print(f"  TOTAL ASSETS = {total_assets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
