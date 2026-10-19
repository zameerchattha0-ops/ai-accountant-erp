"""STAGE-0 MODULE CYCLE — the user-text path (2026-10-19).

Every step is raw text exactly as a user would type it in the chat text
area.  Each message is handed to ``app.agent.execute()`` — the SAME entry
point the HTTP endpoint calls — and runs the FULL pipeline for real:
LLM routing, stage-2 extraction, classification, requirement analysis,
planner, questionnaire authoring, confirmation gate, execution, posting
(real LLM, real test-account books).  The harness only TYPES ANSWERS and
CLICKS APPROVE, exactly like the user at the text area.

Scenario (test account, all four document modules):
  1. PURCHASE            — 5 office chairs on credit from SHABBIR 45,000
  2. SALE                — 3 chairs to an existing customer on credit 24,000
  3. SALES RETURN        — credit note AGAINST THE INVOICE from (2), 1 × 8,000
  4. PURCHASE RETURN     — debit note  AGAINST THE BILL from (1), 1 × 9,000
Then a DB verification: documents, cross-references (invoice_id /
bill_id), journal lines and the stock receipt.

Run detached; logs to stdout.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _e2e_live import (  # noqa: E402
    EMAIL,
    _auto_answer as base_answer,
    dump_trail,
    execute,
    get_client,
    p,
    resolve_identity,
    resume_with_clarification,
)
from app.agent import resume_with_confirmation  # noqa: E402
from app.auth import AuthContext  # noqa: E402
from app.database import fetch_many  # noqa: E402


def pick_answer(question: str, hints: dict) -> str:
    """Typed reply for the asked question — scenario-aware, like a user.

    Order matters (live harness catch, credit-note run): a DATE question
    also names the invoice — the date rule must win, or the number is fed
    to a date field and the round dead-ends.
    """
    low = (question or "").lower()
    if "reason" in low:
        return str(hints.get("reason") or "damaged on arrival")
    if "date" in low and "reason" not in low:
        return str(hints.get("date") or date.today().isoformat())
    if hints.get("quantity") and "quantity" in low:
        return str(hints["quantity"])
    if hints.get("amount") and ("amount" in low or "how much" in low):
        return str(hints["amount"])
    # the catalogue-hinted nature question answers with the VALUE (tappable)
    if "fixed asset" in low or "consistent with your stock" in low:
        return "INVENTORY"
    if "which invoice" in low or ("invoice" in low and "credit note" in low):
        return str(hints.get("invoice_no") or "")
    if "which bill" in low or ("bill" in low and hints.get("bill_no")):
        return str(hints.get("bill_no") or "")
    return base_answer(question)


async def drive(ctx: dict, message: str, tag: str, hints: dict):
    """Send one text-area message and run the turn loop to a terminal state."""
    p(f"\n================ [{tag}] USER TEXT: {message}")
    resp = await execute(
        user_message=message, user_id=ctx["user_id"],
        organization_id=ctx["organization_id"], auth=AuthContext(**ctx),
        conversation_id=None, attachments=None,
        questionnaire_client=get_client(),
    )
    session = uuid.UUID(str(resp.execution_id))
    for turn in range(1, 9):
        st = getattr(resp.status, "name", None) or str(resp.status)
        q = str(getattr(resp, "question", None) or "")
        if q:
            p(f"--- [{tag}] turn {turn} {st} QUESTION: {q[:320]}")
        else:
            p(f"--- [{tag}] turn {turn} {st}")
        if getattr(resp, "summary", None) and not q:
            p(f"    SUMMARY: {str(resp.summary)[:400]}")
        if st == "FAILED":
            p(f"    FAILED: {str(getattr(resp, 'error', '') or '')[:400]}")
            break
        if st in ("AWAITING_CONFIRMATION", "WAITING_FOR_USER"):
            p("    AUTO-CONFIRM: approved=True")
            resp = await resume_with_confirmation(
                session_id=session, approved=True, user_id=ctx["user_id"],
                organization_id=ctx["organization_id"], auth=AuthContext(**ctx),
            )
        elif st != "AWAITING_CLARIFICATION":
            break
        else:
            ans = pick_answer(q, hints)
            p(f"    AUTO-ANSWER: {ans}")
            resp = await resume_with_clarification(
                session_id=session, user_answer=ans, user_id=ctx["user_id"],
                organization_id=ctx["organization_id"], auth=AuthContext(**ctx),
                structured_answers=None, questionnaire_client=get_client(),
            )
        if getattr(resp, "execution_id", None):
            session = uuid.UUID(str(resp.execution_id))
    await dump_trail(session, tag)
    return resp, session


async def latest(org: str, table: str):
    rows = await fetch_many(
        table, filters={"organization_id": org},
        order="created_at.desc", limit=1,
    ) or []
    return rows[0] if rows else None


async def main() -> None:
    ctx = await resolve_identity()
    org = str(ctx["organization_id"])
    p("STAGE-0 MODULE CYCLE — identity:",
      {k: str(v) for k, v in ctx.items() if k != "role_permissions"})

    # an existing customer keeps the party gate out of the happy path
    customers = await fetch_many("customers",
                                 filters={"organization_id": org}, limit=1) or []
    cust = str(customers[0].get("name")) if customers else "Geta Ltd"
    p(f"customer for the sale: {cust!r}")

    returns_only = "--returns-only" in sys.argv
    if returns_only:
        # Resume the cycle from the RETURN steps: the previous stage-0 run
        # already posted the purchase bill (45,000) and the sale invoice.
        bill = await latest(org, "purchase_bills")
        invoice = await latest(org, "invoices")
        p("returns-only mode: reusing the documents already on the books")
    else:
        # ---- 1. PURCHASE (text area) -----------------------------------------
        await drive(ctx,
                    "Bought 5 office chairs on credit from SHABBIR FURNITURES "
                    "for 45000 today",
                    "PURCHASE", {"amount": "45000", "quantity": "5"})
        bill = await latest(org, "purchase_bills")
        p(f">>> latest bill: {bill.get('bill_number') if bill else None} "
          f"total={bill.get('total') if bill else None}")

        # ---- 2. SALE ----------------------------------------------------------
        await drive(ctx,
                    f"Sold 3 chairs to {cust} on credit for 24000 today",
                    "SALE", {"amount": "24000"})
        invoice = await latest(org, "invoices")
        p(f">>> latest invoice: {invoice.get('invoice_number') if invoice else None} "
          f"total={invoice.get('total') if invoice else None}")
    inv_no = str(invoice.get("invoice_number")) if invoice else ""

    # ---- 3. SALES RETURN: credit note OF THAT invoice ---------------------
    await drive(ctx,
                f"{cust} returned 1 damaged chair — create a credit note "
                f"against invoice {inv_no} for 8000 with reason damaged "
                f"on arrival",
                "CREDIT-NOTE",
                {"invoice_no": inv_no, "amount": "8000",
                 "reason": "Damaged on arrival"})
    cn = await latest(org, "credit_notes")
    p(f">>> latest credit note: {cn.get('credit_note_number') if cn else None} "
      f"invoice_id={cn.get('invoice_id') if cn else None} "
      f"total={cn.get('total') if cn else None}")

    # ---- 4. PURCHASE RETURN: debit note OF THAT bill ----------------------
    bill_no = str(bill.get("bill_number")) if bill else ""
    await drive(ctx,
                f"We returned 1 defective chair to SHABBIR FURNITURES — "
                f"create a debit note against purchase bill {bill_no} for "
                f"9000 with reason wrong item delivered",
                "DEBIT-NOTE",
                {"bill_no": bill_no, "amount": "9000",
                 "reason": "Wrong item delivered"})
    pr = await latest(org, "purchase_returns")
    p(f">>> latest purchase return: {pr.get('return_number') if pr else None} "
      f"bill_id={pr.get('bill_id') if pr else None} "
      f"total={pr.get('total') if pr else None}")

    # ================= VERIFICATION ========================================
    p("\n===== VERIFICATION =====")
    state = {"ok": True}

    def check(label, cond, detail=""):
        state["ok"] = state["ok"] and bool(cond)
        p(f"  [{'PASS' if cond else 'FAIL'}] {label} {detail}")

    check("purchase bill exists", bill and bill.get("total") == 45000,
          f"{bill.get('bill_number') if bill else None}")
    check("sale invoice exists", invoice and invoice.get("total") == 24000,
          f"{inv_no}")
    if cn and invoice:
        check("credit note REFERENCES the invoice",
              str(cn.get("invoice_id")) == str(invoice.get("id")),
              f"cn.invoice_id={cn.get('invoice_id')} "
              f"invoice.id={invoice.get('id')}")
        check("credit note amount within invoice",
              float(cn.get("total") or 0) <= float(invoice.get("total") or 0),
              f"cn={cn.get('total')} inv={invoice.get('total')}")
    else:
        check("credit note exists", False)
    if pr and bill:
        check("debit note REFERENCES the bill",
              str(pr.get("bill_id")) == str(bill.get("id")),
              f"pr.bill_id={pr.get('bill_id')} bill.id={bill.get('id')}")
    else:
        check("purchase return exists", False)

    jes = await fetch_many("journal_entries",
                           filters={"organization_id": org},
                           order="created_at.desc", limit=4) or []
    p(f"  journals (latest {len(jes)}):")
    for je in jes:
        lines = await fetch_many("journal_lines",
                                 filters={"entry_id": str(je['id'])},
                                 order="line_number.asc", limit=6) or []
        p(f"    {je.get('journal_number')} src={je.get('source_type')} "
          f"total={je.get('total_debit')} status={je.get('status')}")
        for ln in lines:
            accs = await fetch_many("accounts",
                                    filters={"id": str(ln.get('account_id'))},
                                    limit=1) or [{}]
            p(f"      DR {str(ln.get('debit')):>10} "
              f"CR {str(ln.get('credit')):>10} "
              f"[{accs[0].get('code')}] {accs[0].get('name')}")
    posted = len([j for j in jes if j.get("status") == "POSTED"])
    check("four cycle journals posted", posted >= 4, f"posted={posted}/4")

    moves = await fetch_many("inventory_movements",
                             filters={"organization_id": org},
                             order="created_at.desc", limit=3) or []
    p(f"  stock movements (latest {len(moves)}):")
    for m in moves:
        p(f"    {m.get('direction')} qty={m.get('quantity')} "
          f"unit_cost={m.get('unit_cost')} src={m.get('source_type')}")

    verdict = ("ALL CHECKS PASSED" if state["ok"] else "SEE FAILURES ABOVE")
    p(f"\n===== STAGE-0 CYCLE COMPLETE — {verdict} =====")


if __name__ == "__main__":
    asyncio.run(main())

