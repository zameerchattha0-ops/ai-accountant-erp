"""Test-account junk cleanup (2026-10-19, user-requested).

Removes ONLY the artifacts of the pre-fix buggy runs, each with an honest
per-item PASS/SKIP/FAIL line (the DB guard may refuse a POSTED journal —
that is reported, never worked around):

* credit notes CRN-000002 / CRN-000003 (zero-total hollow documents) and
  their line rows;
* the supplier literally named "Yes, Create It" (the party-answer routing
  bug) together with its dependent bill PUR-000011, bill lines, stock
  movements, journal JV-000050 and its party-ledger account.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _e2e_live import p, resolve_identity  # noqa: E402
from app.database import delete_one, fetch_many  # noqa: E402

ORG = None  # set in main


async def _kill(table: str, row_id, label: str) -> bool:
    try:
        await delete_one(table, row_id=uuid.UUID(str(row_id)),
                         organization_id=ORG)
        p(f"  [PASS] deleted {label}")
        return True
    except Exception as exc:  # noqa: BLE001 — report, never work around
        p(f"  [FAIL] {label}: {str(exc)[:160]}")
        return False


async def main() -> None:
    global ORG
    ctx = await resolve_identity()
    ORG = uuid.UUID(str(ctx["organization_id"]))
    org = str(ORG)
    p(f"CLEANUP for organization {org}")

    # ---- 1. hollow credit notes ------------------------------------------
    for number in ("CRN-000002", "CRN-000003"):
        rows = await fetch_many(
            "credit_notes",
            filters={"organization_id": org, "credit_note_number": number},
            limit=1,
        ) or []
        if not rows:
            p(f"  [SKIP] {number} not found")
            continue
        cn_id = rows[0]["id"]
        items = await fetch_many(
            "credit_note_items",
            filters={"credit_note_id": str(cn_id)},
            limit=50,
        ) or []
        for it in items:
            await _kill("credit_note_items", it["id"],
                        f"{number} line {it.get('id')}")
        await _kill("credit_notes", cn_id, f"{number}")

    # ---- 2. the 'Yes, Create It' cluster ----------------------------------
    suppliers = await fetch_many(
        "suppliers",
        filters={"organization_id": org, "name": "Yes, Create It"},
        limit=2,
    ) or []
    if not suppliers:
        p("  [SKIP] supplier 'Yes, Create It' not found")
    else:
        supp = suppliers[0]
        bills = await fetch_many(
            "purchase_bills",
            filters={"organization_id": org, "bill_number": "PUR-000011"},
            limit=1,
        ) or []
        for bill in bills:
            bill_id = str(bill["id"])
            # stock movements sourced from this bill
            moves = await fetch_many(
                "inventory_movements",
                filters={"organization_id": org, "source_id": bill_id},
                limit=20,
            ) or []
            for mv in moves:
                await _kill("inventory_movements", mv["id"],
                            f"movement {mv.get('id')}")
            lines = await fetch_many(
                "purchase_bill_items",
                filters={"bill_id": bill_id},
                limit=20,
            ) or []
            for ln in lines:
                await _kill("purchase_bill_items", ln["id"],
                            f"PUR-000011 line {ln.get('id')}")
            # journal: posted entries may be guard-protected — honest report
            jes = await fetch_many(
                "journal_entries",
                filters={"organization_id": org, "journal_number": "JV-000050"},
                limit=1,
            ) or []
            for je in jes:
                j_lines = await fetch_many(
                    "journal_lines",
                    filters={"entry_id": str(je["id"])},
                    limit=10,
                ) or []
                deleted = True
                for jl in j_lines:
                    ok = await _kill("journal_lines", jl["id"],
                                     f"JV-000050 line {jl.get('id')}")
                    deleted = deleted and ok
                ok = await _kill("journal_entries", je["id"],
                                 "JV-000050 (posted)")
                if not ok:
                    # The guard says it: a POSTED entry is REVERSED, never
                    # deleted — the sanctioned correction path (the reversal
                    # lines are the lasting tombstone of the junk run).
                    try:
                        from app.services import accounting_service

                        await accounting_service.reverse_journal(
                            entry_id=uuid.UUID(str(je["id"])),
                            reason=(
                                "Test-account cleanup: party-answer routing "
                                "bug artifact (supplier 'Yes, Create It')"
                            ),
                        )
                        p("  [PASS] reversed JV-000050 (sanctioned path)")
                    except Exception as exc:  # noqa: BLE001 — report honestly
                        p(f"  [FAIL] JV-000050 reversal: {str(exc)[:160]}")
                deleted = deleted or ok
            await _kill("purchase_bills", bill["id"], "PUR-000011")

        # the party-ledger account the bug created (only deletable when the
        # journal lines above are gone)
        accts = await fetch_many(
            "accounts",
            filters={"organization_id": org, "name": "Yes, Create It"},
            limit=2,
        ) or []
        for acct in accts:
            await _kill("accounts", acct["id"],
                        f"ledger account {acct.get('code')} 'Yes, Create It'")
        await _kill("suppliers", supp["id"], "supplier 'Yes, Create It'")

    # ---- 3. verification ---------------------------------------------------
    p("\n===== POST-CLEANUP VERIFICATION =====")
    for table, needle in (
        ("credit_notes", "credit_note_number"),
        ("suppliers", "name"),
    ):
        for value in ("CRN-000002", "CRN-000003", "Yes, Create It"):
            rows = await fetch_many(
                table,
                filters={"organization_id": org, needle: value},
                limit=1,
            ) or []
            state = "GONE" if not rows else "STILL PRESENT"
            p(f"  [{'PASS' if not rows else 'NOTE'}] {table}.{needle}="
              f"{value!r} -> {state}")
    p("\n===== CLEANUP COMPLETE =====")


if __name__ == "__main__":
    asyncio.run(main())
