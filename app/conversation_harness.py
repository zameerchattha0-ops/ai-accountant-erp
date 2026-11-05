"""Autonomous Accounting Disambiguation & Grounding Harness.

Interprets user requests, probes live ERP records (purchase bills, sales invoices,
parties, chart of accounts), detects multi-record ambiguities (e.g. same supplier
on different dates, different records on same date), and formats rich, detailed
options so the user and LLM converge on the One True Path with zero assumptions.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import structlog

from app.database import fetch_many, fetch_one
from app.repositories import invoice_repository, purchase_repository
from app.services import customer_service, supplier_service

log = structlog.get_logger()


@dataclass
class DocumentCandidate:
    """A live database record candidate for settlement or allocation."""
    doc_type: str  # "bill" or "invoice"
    id: uuid.UUID
    number: str
    doc_date: str
    due_date: Optional[str]
    party_id: uuid.UUID
    party_name: str
    total: float
    amount_paid: float
    balance_due: float
    status: str
    notes: Optional[str] = None
    currency_code: str = "PKR"

    @property
    def identifier(self) -> str:
        return f"{self.doc_type}:{self.id}"

    def to_option_label(self) -> str:
        prefix = "Bill" if self.doc_type == "bill" else "Invoice"
        date_str = self.doc_date or "No date"
        return f"{prefix} {self.number} ({date_str}) — Rs. {self.balance_due:,.2f} due (Total: Rs. {self.total:,.2f})"


@dataclass
class DisambiguationContext:
    """The live probed state against which user's message is evaluated."""
    matching_bills: List[DocumentCandidate] = field(default_factory=list)
    matching_invoices: List[DocumentCandidate] = field(default_factory=list)
    supplier: Optional[Dict[str, Any]] = None
    customer: Optional[Dict[str, Any]] = None
    extracted_amount: Optional[float] = None
    extracted_party: Optional[str] = None
    extracted_number: Optional[str] = None
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None


@dataclass
class HarnessResult:
    """Outcome of the harness turn evaluation."""
    status: str  # "AWAITING_CLARIFICATION", "RESOLVED", "NO_MATCH"
    intent: Optional[str] = None
    bound_document: Optional[DocumentCandidate] = None
    bound_entities: Dict[str, Any] = field(default_factory=dict)
    grounded_question: Optional[str] = None
    options: List[Dict[str, str]] = field(default_factory=list)
    compliance_warnings: List[str] = field(default_factory=list)


async def probe_live_records(
    organization_id: uuid.UUID,
    user_message: str,
    preliminary_entities: Optional[Dict[str, Any]] = None,
) -> DisambiguationContext:
    """Harvest real records matching party, numbers, and amounts from the books."""
    msg = user_message.lower()
    entities = preliminary_entities or {}
    ctx = DisambiguationContext()

    # 1. Extract search hints
    party_hint = (
        entities.get("supplier_name")
        or entities.get("customer_name")
        or entities.get("party")
        or entities.get("name")
    )
    if not party_hint:
        # Loose capture from regex
        m_to_from = re.search(r"\b(?:to|from|for|against)\s+([A-Za-z0-9\s&.-]+?)(?:\s+(?:today|yesterday|on|for|rs|pkr|\d)|$)", user_message, re.I)
        if m_to_from:
            cand = m_to_from.group(1).strip()
            if cand.lower() not in ("cash", "bank", "credit", "full", "the", "bill", "invoice"):
                party_hint = cand

    ctx.extracted_party = party_hint

    # Extract number hint (e.g. "bill 5", "invoice 0006", "inv-12")
    m_num = re.search(r"\b(?:bill|purchase\s*bill|inv|invoice|po|pur)\s*(?:no\.?|number|#)?\s*([A-Za-z0-9_-]+)\b", user_message, re.I)
    if m_num:
        ctx.extracted_number = m_num.group(1).strip()

    # Extract amount hint
    m_amt = re.search(r"\b(?:rs\.?|pkr|₨|\$)?\s*([\d,]+(?:\.\d+)?)\b", user_message, re.I)
    if m_amt:
        try:
            val_s = m_amt.group(1).replace(",", "")
            val_f = float(val_s)
            if val_f > 10:  # avoid picking stray 1-digit numbers
                ctx.extracted_amount = val_f
        except ValueError:
            pass

    # 2. Look up matching suppliers and bills
    matched_suppliers = []
    if party_hint:
        matched_suppliers = await supplier_service.search(organization_id, query=party_hint, limit=3)
        if matched_suppliers:
            ctx.supplier = matched_suppliers[0]

    # Query purchase_bills
    bills = await fetch_many(
        "purchase_bills",
        filters={"organization_id": str(organization_id)},
        select="id,bill_number,bill_date,due_date,supplier_id,total,amount_paid,status,notes,currency_code",
        limit=50,
    )

    for b in (bills or []):
        if str(b.get("status") or "").upper() in ("VOID", "CANCELLED"):
            continue

        b_num = str(b.get("bill_number") or "")
        b_tot = float(b.get("total") or 0.0)
        b_paid = float(b.get("amount_paid") or 0.0)
        b_due = max(0.0, b_tot - b_paid)

        # Check if bill matches query
        is_match = False

        # Match by number hint
        if ctx.extracted_number:
            num_clean = ctx.extracted_number.lstrip("0")
            b_digits = "".join(ch for ch in b_num if ch.isdigit())
            b_clean = b_digits.lstrip("0")
            if ctx.extracted_number == b_num:
                is_match = True
            elif num_clean and b_clean and num_clean == b_clean:
                is_match = True

        # Match by supplier ID
        if ctx.supplier and str(b.get("supplier_id")) == str(ctx.supplier.get("id")):
            is_match = True

        # Match by exact amount if unsettled
        if ctx.extracted_amount and (b_due == ctx.extracted_amount or b_tot == ctx.extracted_amount) and b_due > 0:
            if "bill" in msg or "supplier" in msg or "pay" in msg:
                is_match = True

        if is_match:
            # Resolve supplier name
            sname = "Supplier"
            if ctx.supplier and str(b.get("supplier_id")) == str(ctx.supplier.get("id")):
                sname = str(ctx.supplier.get("name") or "Supplier")
            else:
                s_row = await supplier_service.get(organization_id, supplier_id=uuid.UUID(str(b["supplier_id"])))
                if s_row and s_row.get("name"):
                    sname = str(s_row["name"])

            ctx.matching_bills.append(
                DocumentCandidate(
                    doc_type="bill",
                    id=uuid.UUID(str(b["id"])),
                    number=b_num,
                    doc_date=str(b.get("bill_date") or ""),
                    due_date=str(b.get("due_date") or "") if b.get("due_date") else None,
                    party_id=uuid.UUID(str(b["supplier_id"])),
                    party_name=sname,
                    total=b_tot,
                    amount_paid=b_paid,
                    balance_due=b_due,
                    status=str(b.get("status") or "OPEN"),
                    notes=b.get("notes"),
                    currency_code=str(b.get("currency_code") or "PKR"),
                )
            )

    # 3. Look up matching customers and invoices
    matched_customers = []
    if party_hint:
        matched_customers = await customer_service.search(organization_id, query=party_hint, limit=3)
        if matched_customers:
            ctx.customer = matched_customers[0]

    invoices = await fetch_many(
        "invoices",
        filters={"organization_id": str(organization_id)},
        select="id,invoice_number,invoice_date,due_date,customer_id,total,amount_paid,status,notes,currency_code",
        limit=50,
    )

    for inv in (invoices or []):
        if str(inv.get("status") or "").upper() in ("VOID", "CANCELLED"):
            continue

        inv_num = str(inv.get("invoice_number") or "")
        inv_tot = float(inv.get("total") or 0.0)
        inv_paid = float(inv.get("amount_paid") or 0.0)
        inv_due = max(0.0, inv_tot - inv_paid)

        is_match = False

        if ctx.extracted_number:
            num_clean = ctx.extracted_number.lstrip("0")
            inv_digits = "".join(ch for ch in inv_num if ch.isdigit())
            inv_clean = inv_digits.lstrip("0")
            if ctx.extracted_number == inv_num:
                is_match = True
            elif num_clean and inv_clean and num_clean == inv_clean:
                is_match = True

        if ctx.customer and str(inv.get("customer_id")) == str(ctx.customer.get("id")):
            is_match = True

        if ctx.extracted_amount and (inv_due == ctx.extracted_amount or inv_tot == ctx.extracted_amount) and inv_due > 0:
            if "invoice" in msg or "customer" in msg or "receiv" in msg:
                is_match = True

        if is_match:
            cname = "Customer"
            if ctx.customer and str(inv.get("customer_id")) == str(ctx.customer.get("id")):
                cname = str(ctx.customer.get("name") or "Customer")
            else:
                c_row = await customer_service.get(organization_id, customer_id=uuid.UUID(str(inv["customer_id"])))
                if c_row and c_row.get("name"):
                    cname = str(c_row["name"])

            ctx.matching_invoices.append(
                DocumentCandidate(
                    doc_type="invoice",
                    id=uuid.UUID(str(inv["id"])),
                    number=inv_num,
                    doc_date=str(inv.get("invoice_date") or ""),
                    due_date=str(inv.get("due_date") or "") if inv.get("due_date") else None,
                    party_id=uuid.UUID(str(inv["customer_id"])),
                    party_name=cname,
                    total=inv_tot,
                    amount_paid=inv_paid,
                    balance_due=inv_due,
                    status=str(inv.get("status") or "ISSUED"),
                    notes=inv.get("notes"),
                    currency_code=str(inv.get("currency_code") or "PKR"),
                )
            )

    return ctx


def evaluate_disambiguation_need(
    ctx: DisambiguationContext,
    user_message: str,
) -> Tuple[bool, Optional[str], List[DocumentCandidate]]:
    """Determine whether multiple records create ambiguity requiring user clarification."""
    msg = user_message.lower()

    # If user explicitly asked about bills or payments
    is_payment_shaped = any(w in msg for w in ["pay", "paid", "settle", "bill", "pur", "supplier", "clear"])
    is_receipt_shaped = any(w in msg for w in ["receiv", "receipt", "collect", "invoice", "inv", "customer"])

    # Ambiguity case 1: Multiple matching bills with open balances
    open_bills = [b for b in ctx.matching_bills if b.balance_due > 0]
    if len(open_bills) > 1 and not (is_receipt_shaped and not is_payment_shaped):
        # Multiple bills on different dates or same date!
        return True, "multiple_matching_bills", open_bills

    # Ambiguity case 2: Multiple matching invoices with open balances
    open_invs = [i for i in ctx.matching_invoices if i.balance_due > 0]
    if len(open_invs) > 1 and not (is_payment_shaped and not is_receipt_shaped):
        return True, "multiple_matching_invoices", open_invs

    # Ambiguity case 3: Cross-domain match (both open bills and invoices for similar names)
    if open_bills and open_invs:
        return True, "cross_document_ambiguity", [*open_bills, *open_invs]

    return False, None, []


def build_detailed_disambiguation_card(
    candidates: List[DocumentCandidate],
    party_name: Optional[str] = None,
    context_note: Optional[str] = None,
) -> Tuple[str, List[Dict[str, str]]]:
    """Build a rich, fully-detailed questionnaire card showing dates, totals, and balances."""
    party = party_name or (candidates[0].party_name if candidates else "this party")
    lines = [
        f"### 📋 Disambiguation: Multiple Matching Records for {party}",
        "",
        "I found multiple open documents matching your request. Please select which record you intend to settle:",
        "",
    ]

    options = []
    for idx, c in enumerate(candidates, 1):
        letter = chr(ord('a') + idx - 1)
        doc_label = "Purchase Bill" if c.doc_type == "bill" else "Sales Invoice"
        date_str = c.doc_date or "Unknown Date"
        due_str = f"Due: {c.due_date}" if c.due_date else ""
        note_str = f" *({c.notes})*" if c.notes else ""

        lines.append(
            f"**({letter}) {doc_label} `{c.number}`** — Dated: **{date_str}** {due_str}\n"
            f"   - **Party:** {c.party_name}\n"
            f"   - **Total:** Rs. {c.total:,.2f} | **Remaining Balance:** **Rs. {c.balance_due:,.2f}** ({c.status}){note_str}"
        )

        options.append({
            "value": c.identifier,
            "label": f"({letter.upper()}) {c.number} [{date_str}] — Rs. {c.balance_due:,.2f} due",
        })

    # Add fallback standalone option
    next_letter = chr(ord('a') + len(candidates))
    fallback_label = "Direct Expense Booking (No bill settlement)" if any(c.doc_type == "bill" for c in candidates) else "Direct Receipt Booking (No invoice)"
    lines.append(f"**({next_letter}) {fallback_label}**\n   - Record a new standalone transaction without allocating against an existing document.")

    options.append({
        "value": "standalone_direct",
        "label": f"({next_letter.upper()}) {fallback_label}",
    })

    lines.append("\nPlease reply with the option letter (a, b, c...), the document number, or date.")
    return "\n".join(lines), options


def resolve_user_selection(
    answer: str,
    candidates: List[DocumentCandidate],
) -> Optional[DocumentCandidate]:
    """Map user's plain reply (letter, date, bill number, or value) to the exact DocumentCandidate."""
    ans = answer.strip().lower()

    # 1. Direct identifier or UUID match
    for c in candidates:
        if ans == c.identifier.lower() or ans == str(c.id).lower():
            return c

    # 2. Option letter or sequence match (a, b, c... / 1, 2, 3...)
    clean_letter = ans.replace("(", "").replace(")", "").replace("option", "").strip()
    for idx, c in enumerate(candidates):
        letter = chr(ord('a') + idx)
        if clean_letter in (letter, str(idx + 1)):
            return c

    # 3. Document digits / number match (e.g. "Bill 108", "#108", "000108")
    ans_digits = "".join(ch for ch in ans if ch.isdigit())
    if ans_digits:
        for c in candidates:
            c_digits = "".join(ch for ch in c.number if ch.isdigit())
            if ans_digits == c_digits or ans_digits.lstrip("0") == c_digits.lstrip("0"):
                return c

    for c in candidates:
        if c.number.lower() in ans:
            return c

    # 4. Date match (e.g. "25th Oct", "15-Oct", "2026-10-25")
    _MONTH_MAP = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
    }
    for c in candidates:
        if c.doc_date:
            if c.doc_date.lower() in ans:
                return c
            # Check day + month (e.g. 25 + oct -> 10-25)
            day_m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", ans)
            if day_m:
                day_val = day_m.group(1).zfill(2)
                for mon_name, mon_num in _MONTH_MAP.items():
                    if mon_name in ans and f"-{mon_num}-{day_val}" in c.doc_date:
                        return c
                # If only day is provided and only one candidate matches that day
                if f"-{day_val}" in c.doc_date:
                    return c

    # 5. Amount match (e.g. "the 50000 one", "85000")
    for c in candidates:
        if f"{int(c.total)}" in ans or f"{int(c.balance_due)}" in ans:
            return c

    return None


def validate_compliance_prerequisites(
    candidate: Optional[DocumentCandidate] = None,
    payment_method: str = "CASH",
    *,
    amount: Optional[float] = None,
    action_type: Optional[str] = None,
    has_tax_deducted: bool = False,
    is_active_taxpayer: bool = True,
) -> List[str]:
    """Verify Section 73 crossed-banking instrument guard and Section 153 WHT rules."""
    warnings = []
    pm = (payment_method or "CASH").upper()
    val = float(amount or (candidate.balance_due if candidate else 0.0) or 0.0)

    # Income Tax Ordinance Section 73 guard: payments over PKR 50,000 must be via crossed cheque/banking channel
    if val > 50_000 and pm == "CASH":
        warnings.append(
            f"Statutory Cash Payment Limitation (Section 73): Cash payment of Rs. {val:,.2f} exceeds PKR 50,000. "
            "Under Section 73 of the Income Tax Ordinance 2001, business expenditure exceeding Rs. 50,000 must be "
            "settled via a crossed banking instrument (Bank Transfer, Cheque, Pay Order) to remain tax-deductible."
        )

    # Section 153 WHT Reminder
    if candidate and candidate.doc_type == "bill" and candidate.balance_due >= 25_000:
        warnings.append(
            "ℹ️ **Section 153 WHT**: Supplier settlement will record gross liability discharge with withholding tax "
            "segregation where configured for this vendor."
        )

    return warnings
