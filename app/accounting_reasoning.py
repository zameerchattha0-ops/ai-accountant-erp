"""
AI-Native ERP — LLM ACCOUNTING REASONING LOOP
==============================================================

This module implements the architectural correction: the LLM is the PRIMARY
accounting reasoning layer, and Python is the controlled execution and
enforcement layer.

    User request
      → authenticated session
      → PRELIMINARY deterministic extraction only (literal, never a verdict)
      → LLM requests the books evidence it needs
      → Python validates + permission-checks + reads the evidence
      → LLM reassesses on LIVE BOOKS EVIDENCE and chooses a next step
          · ask a contextual question
          · explain that a prerequisite record is missing
          · propose a preparatory/correcting transaction
          · propose a settlement/allocation
          · propose a journal/document mutation
          · refuse (unsafe or unsupported)
          · complete
      → Python validates and enforces the proposal
      → execute through the trusted tool router
      → LLM reassesses the ACTUAL result
      → verify against the ledger before reporting success

What Python does here (enforcement, never interpretation):

* identity/organization scoping is injected, never taken from the model;
* evidence kinds, argument names and argument types are a CLOSED set — an
  unknown kind/argument is REJECTED and the rejection is fed back;
* the outcome must be exactly one of ask / request-evidence / propose / refuse
  / complete, with the mandated disclosure fields for a proposal;
* the round budget is bounded;
* nothing here decides what a phrase means, which party is required, whether an
  asset exists, or which workflow applies.  The caller (agent) additionally
  enforces the trusted tool registry, permissions and the confirmation gate
  before anything executes.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import structlog

from app.books_evidence import (
    EVIDENCE_KINDS,
    EVIDENCE_LABEL,
    EvidenceRequest,
    EvidenceResult,
    deferred_evidence_requests,
    evidence_catalog_text,
    gather_evidence,
    parse_evidence_requests,
    render_evidence,
    render_evidence_compact,
    validate_evidence_request,
)

log = structlog.get_logger(__name__)

#: Round budget — evidence round(s), reassessment, result review.
MAX_REASONING_ROUNDS = 3

#: Outcome kinds the caller reacts to.
NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
NEEDS_INPUT = "NEEDS_INPUT"
PROPOSAL = "PROPOSAL"
REFUSAL = "REFUSAL"
COMPLETE = "COMPLETE"
UNSUPPORTED = "UNSUPPORTED"



# ---------------------------------------------------------------------------
# Prompt — what the reasoning layer is told
# ---------------------------------------------------------------------------

_BASE_SYSTEM_RULES = """
You are the PRIMARY ACCOUNTING REASONING LAYER of a chartered-accountant
assisted ERP. Python here does ONLY: identity/org checks, tool and schema
validation, permissions, confirmation gates, database constraints, journal
balancing, idempotency, execution, audit. You decide the accounting; Python
enforces and executes.

THE PRELIMINARY PLANNER MAY BE INCOMPLETE OR WRONG.
"PRELIMINARY EXTRACTION — may be corrected after accounting review" is regex/
keyword output, NOT a verdict. Do not follow its intent, workflow, party
requirement or missing-field list blindly; reclassify if the records disagree.

ASSUME NOTHING IS RECORDED UNTIL YOU HAVE CHECKED.
Before proposing a mutation, inspect the areas that could already hold the
event: documents, journal entries, subledgers, open items, the fixed-asset
register, the chart of accounts, the accounting period.

THE SAME PHRASE MEANS DIFFERENT THINGS IN DIFFERENT BOOKS.
"paid ABC 50,000" could be: settlement of a payable; an advance; a loan
repayment; an owner withdrawal; an immediately-paid purchase; payment of an
expense already recorded; a new transaction; a correction. Decide from the
RECORDS, never from the verb.

DOUBLE-ENTRY & FULL-SPECTRUM ACCOUNTING:
Reason across every area: cash/bank, receivables, inventory, prepaid, fixed
assets, accumulated depreciation, payables, accruals, loans, taxes payable,
advances, capital/drawings, revenue, COGS, operating expenses, depreciation,
finance costs, and disposal gains/losses. Every journal entry must balance
(Debits == Credits).

UNIVERSAL CA COGNITIVE PROTOCOL — 4-STAGE PIPELINE:
1. INTENT & GOAL COMPREHENSION: Distinguish reporting/inquiry (lookup books),
   operational master data (create employee/bank/customer/supplier/product/account,
   zero journal impact), commercial transaction (purchase, sale, expense,
   payment, receipt, asset acquisition), or ambiguous/advisory intent (ask or
   advise upfront).
2. MODULE & ENDPOINT IDENTIFICATION: Map intent to the exact ERP tool and
   inspect its required fields.
3. CONTEXT RE-VISITING & GAP ANALYSIS: Extract stated facts first; ask ONLY
   for missing mandatory fields in one consolidated questionnaire.
4. PREREQUISITE RESOLUTION & EXECUTION: Check live database records for
   parties/items/accounts, resolve prerequisites first, then propose execution.

HARD PROHIBITIONS:
- Never invent accounts, parties, assets, documents, amounts or dates.
- Never decide a treatment from a keyword alone.
- Never assume a party ledger is required (a cash-only event may need none).
- Never assume an asset or a document already exists.
- Never assume HOW this transaction was settled (cash/bank/credit) or any
  other fact the user did not state in THIS request. A learned past-session
  value is context, not an answer: ask (option b) or list it in
  missing_material_facts — never default it into a proposal or a
  "per org policy" disclosure.
- Never ask a generic question when the records could answer it.
- Never claim success: success comes from actual tool results and the verified
  ledger, not from your own text.

CHART-OF-ACCOUNTS GRANULARITY:
Ledgers are CATEGORY-level — never one account per item, and never a single
generic bucket when a category is identifiable (Furniture, Fixtures & Fittings,
Computer Equipment, Vehicles; Utilities, Rent, Travel). The individual item
lives on the document line, never as its own account.

CORE ERP MODULE SUMMARY:
- Master Data (0 journal impact): create_employee, create_bank_account,
  create_product (purchase context: cost_price, unit_price=0.0), create_service,
  create_customer, create_supplier, create_account, create_project.
- Purchases & Payables: create_purchase_order (RFQ/ORDERED; INVENTORY vs
  FIXED_ASSET), create_purchase_bill (ON_CREDIT, supplier required),
  record_supplier_payment / record_payment (settle payable, optional WHT u/s 153).
- Sales & Receivables: create_quotation (DRAFT quote), create_invoice (ON_CREDIT,
  customer required), record_cash_sale (PAID_NOW), record_receipt (settle AR).
- Expenses, Assets, Banking & Payroll: record_expense (PAID_NOW, no supplier
  ledger needed), register_fixed_asset (capital equipment/furniture/vehicles),
  record_bank_transfer, run_payroll, pay_employee_salary,
  set/get_organization_tax_profile, set/get_organization_leave_policy.
- Reporting: get_general_ledger, get_trial_balance, get_profit_loss,
  get_customer_ledger, get_supplier_ledger, get_inventory_status.

FBR & CFO ADVISORY PROTOCOL HEADER:
Act as an authoritative Chartered Accountant and CFO Advisor. Never assume
counterparty tax status (STRN/NTN/ATL) — inspect live org and party tax
profiles first. For intended capital purchases (e.g. furniture/equipment),
advise on multi-vendor quotations, RFQ/PO controls, capitalization, and
statutory compliance (Section 73 banking channel > PKR 50,000, Section 153 WHT).

CREDIT / DEBIT NOTES:
Credit notes reverse revenue/AR; debit notes reverse purchase/AP — both
auto-post their reversal journal from the document. Explain questions in plain,
friendly English for non-accountants.
""".strip()

_TAX_COMPLIANCE_RULES = """
STATUTORY TAX & COMPLIANCE RULES (PAKISTAN ITO 2001, SALES TAX ACT 1990 & PROVINCIAL ACTS):
1. CHARTERED TAX CONSULTANT (NO ASSUMPTIONS):
   - NEVER ASSUME counterparty tax status, STRN, NTN, or item nature.
   - ALWAYS inspect live books first: check buyer org tax profile and party
     saved profile (STRN, tax_number, sales_tax_status). If unknown for a
     taxable transaction, ask the user before proposing final posting.

2. GOODS VS. SERVICES JURISDICTION & SALES TAX SPLITTING:
   - Sales Tax Splitting splits gross vs net revenue/cost and routes tax to
     Sales Tax Output Payable (Account 2110) or Input Sales Tax Recoverable
     (Account 1060) using tax_pricing_mode ('exclusive', 'inclusive', 'exempt').
   - GOODS -> Federal FBR (Sales Tax Act 1990 — 18% standard GST).
     S.3(1A) 4% Further Tax MUST be charged on goods sold to unregistered
     persons (Total 22%).
   - SERVICES -> Provincial jurisdiction (0% Further Tax — S.3(1A) does NOT
     apply to services):
     * Punjab: PRA (16% standard) | Sindh: SRB (15%) | KPK: KPRA (15%)
     * Balochistan: BRA (15%) | Islamabad: ICT/FBR Services (15%)

3. SECTION 73 BANKING CHANNEL & CASH THRESHOLD GUARD:
   - Under Section 73 of the Income Tax Ordinance 2001 & Sales Tax Act 1990:
     Any business expenditure or purchase exceeding PKR 50,000 paid in CASH is
     NON-COMPLIANT (expense deduction disallowed u/s 21(l) and input sales tax
     forfeited). Always warn the user and recommend crossed cheque, pay order,
     or direct bank transfer (BANK) when cash exceeds PKR 50,000.

4. INPUT TAX ELIGIBILITY (SECTION 8 & PROVINCIAL RULES):
   - Active Buyer + Active Supplier Goods (P-01): 18% GST -> Account 1060 Asset.
   - Inactive Supplier (P-02): Input tax held under compliance review.
   - Unregistered Supplier (P-03): Supplier cannot charge GST; input tax = 0;
     no 4% Further Tax on purchase; total capitalized into cost.
   - Services Reduced-Rate Schemes (e.g. IT 3% SRB / 5% PRA, Construction 5%):
     No input tax adjustment admissible; reduced tax capitalized into cost.

5. DUAL WITHHOLDING (INCOME TAX U/S 153 + PROVINCIAL SALES TAX WH-ST):
   - Federal Income Tax u/s 153 (Account 2120 Withholding Tax Payable u/s 153):
     Check valid Exemption Certificate (0%) first. Otherwise deduct ATL rate:
     IT/Software 4%; Professional (legal/audit/engineering) 15%; Specified
     (transport/courier/hotel/security) 7%; Other services 14%; Goods 5%
     (Companies) / 5.5% (Individuals/AOPs); Contracts 7.5%/8%; Advertising 1.5%.
   - Provincial Sales Tax Withholding (Account 2130-WHST):
     Unregistered/Inactive or prescribed sectors (Advertising, Security, Courier,
     Janitorial): 100% withheld; Active corporate: 20% (1/5th); Telecom/Banking: 0%.
   - Payroll tax u/s 149 is covered under payroll rules (Account 2121).
""".strip()

_PROCUREMENT_RULES = """
PROCUREMENT & CAPITAL ACQUISITION WORKFLOW (CFO ADVISORY & CONTROLS):
1. CFO & PROCUREMENT ADVISORY FOR IN-PROGRESS PURCHASES:
   - When a user describes an intended or in-progress purchase (e.g. "I am
     purchasing 2 sofas from Shabbir Furniture", "planning to buy laptops"):
     Do NOT book an immediate GL entry blindly; act as CFO & Procurement Advisor:
     * Vendor Quotations: Recommend obtaining/comparing formal quotations from
       multiple vendors on price, quality, warranty, delivery, and ATL filer status.
     * RFQ / Purchase Order (PO): Generate a formal RFQ or PO via
       create_purchase_order (status='RFQ' or 'ORDERED') once vendor/terms are chosen.
       Use transaction_nature='INVENTORY' for resale stock, 'FIXED_ASSET' for
       business equipment/furniture. Line items require description, quantity,
       and unit cost (or total amount divided across quantity).
     * Capitalization Threshold: Fixed assets >= PKR 50,000 (or $500 USD) with
       useful life > 1 year capitalize to PPE (e.g. Account 1500 Office Furniture
       & Fixtures) upon delivery/invoice; consumables/minor items expense immediately.
     * Compliance: Flag Section 73 (> PKR 50,000 must use banking channel) and
       Section 153 WHT (5% corporate / 5.5% individual on goods).

2. CREDIT PURCHASE BILLS, SETTLEMENTS & DEBIT NOTES:
   - create_purchase_bill: Used for purchases on credit (ON_CREDIT). Supplier
     name is REQUIRED. Preserve distinct line items; sum(qty * unit_price) must
     reconcile with stated subtotal/total.
   - record_supplier_payment / record_payment: Settle open vendor bills
     (SETTLE_EXISTING_PAYABLE); supports wht_rate_percent / wht_amount u/s 153.
   - create_purchase_return (Debit Note): Reverses purchase & shrinks AP.
""".strip()

_DEPRECIATION_RULES = """
FIXED ASSETS & DEPRECIATION RULES (IAS 16 & 3RD SCHEDULE ITO 2001):
1. REGISTRATION & CAPITALIZATION (register_fixed_asset):
   - Capitalize only tangible assets held for > 1 year above threshold (typically
     >= PKR 50,000). Consumables are NEVER fixed assets.
   - Required facts: asset name, purchase_cost, transaction_date, and stated
     payment_method (CASH, BANK, or CREDIT with supplier_name).
   - Post to category-level PPE accounts (Furniture & Fixtures, Computer
     Equipment, Vehicles, Plant & Machinery, Buildings).

2. 3RD SCHEDULE ITO 2001 REDUCING BALANCE RATES:
   - Buildings: 10% | Furniture & Fixtures: 15% | Plant & Machinery: 15%
   - Motor Vehicles: 20% | Computer Hardware & IT Equipment: 30%
   - Depreciation posts via record_asset_depreciation (Dr Depreciation Expense,
     Cr Accumulated Depreciation).

3. DISPOSAL & DERECOGNITION (dispose_fixed_asset):
   - Inspect existing asset record first: cost, accumulated depreciation, net
     book value (NBV), and whether already disposed.
   - Distinguish disposal proceeds from acquisition cost; recognize gain/loss
     on disposal against NBV.
""".strip()

_LOAN_RULES = """
LOAN, BORROWING & EQUITY ACCOUNTING RULES:
1. SUBSTANCE CHECK (LIABILITY VS CAPITAL VS DRAWING):
   - Verify from records and user intent whether cash movement is a third-party
     loan, director/shareholder loan, equity capital injection, or owner drawing.
   - Never book loan principal receipts as revenue or loan repayments as operating
     expenses.

2. AMORTIZATION & INTEREST ACCRUAL:
   - Loan Origination: Dr Cash/Bank, Cr Loan Payable (Liability).
   - Repayment Split: Separate principal reduction (Dr Loan Payable) from
     accrued/incurred finance cost (Dr Interest / Finance Cost Expense) so
     amortization schedules and outstanding principal remain accurate.
   - Interest Accrual: Accrue unpaid interest at period end (Dr Finance Cost,
     Cr Accrued Interest Payable) in accordance with the loan schedule.
""".strip()

_PAYROLL_RULES = """
PAYROLL, SECTION 149 TAX & LEAVE POLICY RULES (ITO 2001 & IAS 19):
1. EMPLOYEE MASTER & PAYROLL EXECUTION:
   - create_employee: Register personnel (full_name, date_of_joining, basic_salary).
     Zero journal impact.
   - run_payroll: Compute gross-to-net payroll under Section 149 & IAS 19.
     Set apply_income_tax=True (or withholding_tax=True) to apply annual
     progressive salary tax slabs (1% to 35% across 8 slabs). Posts Dr Gross
     Salaries Expense (5000/5010) / Cr WHT Payable u/s 149 (2121) / Cr Accrued
     Salaries (2130) (or Cr Bank if payment_method=PAID).
   - pay_employee_salary: Settle individual salary accrual (Dr Accrued Salaries
     2130 / Cr Bank 1010), or pass apply_income_tax=True for direct salary.

2. ORGANIZATION LEAVE POLICY & PRO-RATION:
   - Inspect organization leave policy via get_organization_leave_policy (default:
     2 paid leaves/month, 27/year, 30 working days/month).
   - If absences <= monthly allowed leaves: 100% full month salary is paid.
   - If absences > monthly allowed leaves: deduct ONLY excess absent days
     (absences - allowed) pro-rated at (Monthly Gross / 30) per excess day.
   - Pro-rate taxable gross for unpaid leave before applying Section 149 slabs.
""".strip()

#: Full combined rules retained for backward-compatible inspection/tests.
_SYSTEM_RULES = "\n\n".join(
    [
        _BASE_SYSTEM_RULES,
        _TAX_COMPLIANCE_RULES,
        _PROCUREMENT_RULES,
        _DEPRECIATION_RULES,
        _LOAN_RULES,
        _PAYROLL_RULES,
    ]
)

_CONTEXT_MODULES: Dict[str, str] = {
    "tax": _TAX_COMPLIANCE_RULES,
    "procurement": _PROCUREMENT_RULES,
    "depreciation": _DEPRECIATION_RULES,
    "loans": _LOAN_RULES,
    "payroll": _PAYROLL_RULES,
}

_SECTION_TO_MODULES: Dict[str, tuple[str, ...]] = {
    "tax": ("tax",),
    "compliance": ("tax",),
    "gst": ("tax",),
    "wht": ("tax",),
    "sales": ("tax",),
    "revenue": ("tax",),
    "receivables": ("tax",),
    "invoicing": ("tax",),
    "expenses": ("tax",),
    "purchases": ("procurement",),
    "procurement": ("procurement",),
    "payables": ("procurement",),
    "orders": ("procurement",),
    "purchase_orders": ("procurement",),
    "fixed_assets": ("depreciation",),
    "fixed-assets": ("depreciation",),
    "assets": ("depreciation",),
    "depreciation": ("depreciation",),
    "loans": ("loans",),
    "loan": ("loans",),
    "borrowing": ("loans",),
    "payroll": ("payroll",),
    "employees": ("payroll",),
    "hr": ("payroll",),
    "salary": ("payroll",),
}

_INTENT_TO_MODULES: Dict[str, tuple[str, ...]] = {
    "create_purchase_order": ("procurement",),
    "update_purchase_order_status": ("procurement",),
    "create_purchase_bill": ("procurement",),
    "record_purchase": ("procurement",),
    "record_cash_purchase": ("procurement", "tax"),
    "record_credit_purchase": ("procurement",),
    "create_purchase_return": ("procurement",),
    "record_supplier_payment": ("tax", "procurement"),
    "record_payment": ("tax",),
    "create_invoice": ("tax",),
    "record_credit_sale": ("tax",),
    "record_cash_sale": ("tax",),
    "create_credit_note": ("tax",),
    "set_organization_tax_profile": ("tax",),
    "get_organization_tax_profile": ("tax",),
    "record_expense": ("tax",),
    "register_fixed_asset": ("depreciation",),
    "record_asset_depreciation": ("depreciation",),
    "dispose_fixed_asset": ("depreciation",),
    "record_loan": ("loans",),
    "record_loan_repayment": ("loans",),
    "accrue_loan_interest": ("loans",),
    "create_employee": ("payroll",),
    "run_payroll": ("payroll",),
    "pay_employee_salary": ("payroll",),
    "set_organization_leave_policy": ("payroll",),
    "get_organization_leave_policy": ("payroll",),
}


def assemble_system_rules(
    section: Optional[str] = None,
    intent: Optional[str] = None,
) -> str:
    """Assemble base system rules plus only the relevant on-demand context module(s)."""
    selected: List[str] = []
    if section:
        key = str(section).strip().lower()
        for mod in _SECTION_TO_MODULES.get(key, ()):
            if mod not in selected:
                selected.append(mod)
    if intent:
        ikey = str(intent).strip().lower()
        for mod in _INTENT_TO_MODULES.get(ikey, ()):
            if mod not in selected:
                selected.append(mod)
    parts = [_BASE_SYSTEM_RULES]
    for mod in selected:
        block = _CONTEXT_MODULES.get(mod)
        if block:
            parts.append(block)
    return "\n\n".join(parts)

_PRELIMINARY_LABEL = (
    "PRELIMINARY EXTRACTION — may be corrected after accounting review"
)
#: The disclosure fields a mutation proposal MUST carry.  A proposal that omits
#: any of them is refused by Python (never executed).
REQUIRED_PROPOSAL_FIELDS = (
    "interpretation",
    "affected_records",
    "accounting_impact",
    "not_affected",
    "unresolved_uncertainty",
)

#: Accepted spellings of each disclosure field.
_PROPOSAL_FIELD_ALIASES = {
    "interpretation": ("interpretation", "business_interpretation"),
    "affected_records": ("affected_records",),
    "accounting_impact": ("accounting_impact",),
    "not_affected": ("not_affected",),
    "unresolved_uncertainty": ("unresolved_uncertainty",),
}


def _stated_disclosures(raw_proposal: Any) -> List[str]:
    """Which mandatory disclosures the model actually PROVIDED.

    Presence — not non-emptiness — is what the enforcement layer checks.  An
    explicit empty list is a statement ("nothing else is affected", "no
    unresolved uncertainty"), whereas an omitted key is silence.  Requiring a
    non-empty value would push the model to invent uncertainty, which this
    architecture forbids.
    """
    if not isinstance(raw_proposal, dict):
        return []
    return [
        name
        for name, aliases in _PROPOSAL_FIELD_ALIASES.items()
        if any(alias in raw_proposal for alias in aliases)
    ]


_RESPONSE_SHAPE = """
RESPONSE FORMAT — output ONLY this JSON object, no prose:

{
  "understanding": {
    "economic_event": "<the real-world event, in accounting terms>",
    "what_user_wants": "<the outcome the user is trying to achieve>",
    "basis": "<which records or wording support this reading>",
    "event_type": "new_event|correction|settlement|allocation|transfer|adjustment|disposal|reversal|report"
  },
  "evidence_requests": [
    {"kind": "<evidence kind>", "why": "<why the accounting decision needs it>",
     "args": {"terms": ["..."]}}
  ],
  "missing_material_facts": [
    {"fact": "<what is missing>", "why_material": "<why it blocks a correct posting>",
     "question": "<the question to ask the user>"}
  ],
  "question": null,
  "decision": {"intent": "<planner intent>", "treatment": "<nature>", "document_nature": "<GOODS|SERVICE|ASSET_DISPOSAL|OTHER_INCOME>"},
  "entities": {
    "amount": null,
    "currency": null,
    "item_description": null,
    "transaction_purpose": null,
    "supplier_name": null,
    "customer_name": null,
    "quantity": null,
    "line_items": [
      {"description": "<item or service name>", "quantity": <number|null>, "unit_price": <number|null>, "total_amount": <number|null>}
    ],
    "payment_method": "CASH|BANK|CREDIT",
    "settlement_position": "PAID_NOW|ON_CREDIT|SETTLE_EXISTING_PAYABLE|SETTLE_EXISTING_RECEIVABLE",
    "account_name": null,
    "transaction_date": null
  },
  "prerequisites": [{"name": "", "status": "present|missing|ambiguous", "resolution": "reuse|create|ask"}],
OPTIONAL BLOCK: "decision" and "prerequisites" are observation metadata. Use ONLY canonical values (a planner intent, a nature from your own vocabulary) — omit them rather than invent one.
  "proposal": {
    "interpretation": "<the business interpretation you are proposing>",
    "affected_records": ["<record/ledger that will change>"],
    "accounting_impact": [
      {"account": "<account name or code from the chart of accounts>",
       "debit": 0, "credit": 0, "reason": "<why>"}
    ],
    "not_affected": ["<record/dimension that will deliberately NOT change>"],
    "unresolved_uncertainty": ["<anything still uncertain>"],
    "tools": [{"tool_name": "<registered tool>", "arguments": {}}],
    "confirmation": "<the exact sentence to show the user asking to proceed>"
  },
  "refusal": null,
  "complete": false
}

CHOOSING THE STEP — exactly one of these must be non-null/non-empty:
  a) "evidence_requests" non-empty -> you need the books before deciding.
     Request the lookups you need. Do not guess in the meantime.
  b) "question" non-null -> a material fact only the user can supply, asked in
     the context of the actual records (never a generic template question).
     "missing_material_facts" lists what that question resolves.
     The questionnaire is written in THIS SAME response — understanding,
     missing facts and the questions are ONE output; question-writing is
     never deferred to another call.
     CONSOLIDATED QUESTIONNAIRE: ask EVERY material unknown in ONE round,
     FIXED FORMAT:
     "question": {"text": "<intro>\n1. <q1>\n2. <q2>", "questions": [
       {"field": "<erp field>", "kind": "choice|date|money|number|text",
        "question": "<the numbered line>",
        "options": [{"value": "<recorded>", "label": "<chip>"}],
        "answer_hint": "<how>", "why": "<why>"}]}
     Rules: text and questions list the SAME questions in order; field
     must be an ERP field — transaction_date, payment_type,
     transaction_nature, amount, supplier_name, customer_name,
     item_description, quantity, asset_name, useful_life_years,
     depreciation_method, salvage_value, account_name,
     transaction_purpose, capitalization_decision, settlement_position,
     disposal_type, proceeds_amount, period, note; never re-ask a stated
     fact ("yesterday" is resolved); 2-6 {value,label} options per finite
     choice else []; plain lines, no markdown.
     Every question carries tap-ready "options" when the answer set is
     finite — quick, actionable answers the user can tap.
     Never drip-feed one unknown per round.
  c) "proposal" non-null -> you have enough evidence to propose a concrete next
     step. Every proposal MUST include interpretation, affected_records,
     accounting_impact, not_affected and unresolved_uncertainty.
     While "missing_material_facts" is non-empty a proposal is INVALID:
     those facts block the posting — choose (b) and write the questionnaire
     in this same response ("unresolved_uncertainty" covers only
     NON-blocking unknowns).
  d) "refusal" non-null -> the request is unsafe, unsupported, or must not be
     executed; explain what is missing and what the safe alternative is.
  e) "complete": true -> the requested outcome is already achieved and verified
     by the actual records; explain what the records show.

RULES FOR PROPOSALS:
  - Tool names must come from the offered tool list; never invent one.
  - The accounting engine computes and enforces the final debits/credits and
    balancing. Your accounting_impact is the PROPOSED impact, stated so the
    user can see the consequence; it is verified, not trusted blindly.
  - List what will NOT be affected whenever a plausible misunderstanding exists
    (e.g. "no customer ledger will be created").
  - State unresolved uncertainty honestly; an empty list is a claim.
  - The confirmation sentence must be specific: which records, which amounts,
    which accounts, and what will not change.

AUDITOR MINDSET FOR EVERY AREA:
  - Cash/bank: which account, which direction, is the counterparty real?
  - Receivables/payables: does an open item exist, and is this settlement,
    advance, refund, or a new document?
  - Inventory/catalog: goods vs service vs asset; does the item exist?
  - Fixed assets: registered? cost, accumulated depreciation, book value,
    already disposed? Is the amount proceeds or acquisition value?
  - Accruals/prepayments: is the expense already recorded, or being recorded
    now, and in which period?
  - Loans/equity/drawings: is the cash movement a liability, capital, or a
    withdrawal?
  - Taxes: is a tax liability or recovery involved, and is a rate known?
  - Periods: is the intended date inside an OPEN period? If not, say so.
  - Corrections: prefer reversal + correct entry over silent edits.
""".strip()


@dataclass
class ReasoningFacts:
    """Everything the reasoning layer is allowed to see (already fetched)."""

    user_request: str = ""
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    preliminary: Dict[str, Any] = field(default_factory=dict)
    organization: Dict[str, Any] = field(default_factory=dict)
    accounting_period: Dict[str, Any] = field(default_factory=dict)
    org_policies: Dict[str, str] = field(default_factory=dict)
    economic_hints: Dict[str, Any] = field(default_factory=dict)
    prohibitions: List[str] = field(default_factory=list)
    previous_tool_results: List[Dict[str, Any]] = field(default_factory=list)
    previous_confirmations: List[Dict[str, Any]] = field(default_factory=list)
    today: str = ""


@dataclass
class ReasoningOutcome:
    """The parsed, validated decision of one reasoning round."""

    status: str
    understanding: Dict[str, Any] = field(default_factory=dict)
    evidence_requests: List[EvidenceRequest] = field(default_factory=list)
    evidence_results: List[EvidenceResult] = field(default_factory=list)
    rejected_evidence: List[str] = field(default_factory=list)
    question: Optional[Dict[str, Any]] = None
    missing_facts: List[Dict[str, Any]] = field(default_factory=list)
    proposal: Optional[Dict[str, Any]] = None
    #: Mandatory disclosures the model actually provided (presence, so an
    #: explicit empty list counts as the statement it is).
    stated_disclosures: List[str] = field(default_factory=list)
    refusal: Optional[Dict[str, Any]] = None
    entities: Dict[str, Any] = field(default_factory=dict)
    #: Wave A observation block (AUDIT_REPORT §7) — parsed and compared against
    #: the legacy intent, but NEVER consumed by execution_plan until Wave B,
    #: once the A→B gate (§8) has measured divergence on real turns.
    decision: Dict[str, Any] = field(default_factory=dict)
    prerequisites: List[Dict[str, Any]] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    provider_failed: bool = False
    #: True when the provider was actually CALLED and failed (timeout, error,
    #: unparseable). False when the loop never got that far (no orchestrator,
    #: feature disabled, empty request) — the caller retries a provider only
    #: when it has NOT just failed in the same request.
    provider_attempted: bool = False
    rounds: int = 0
    #: WHY the stage gave up: "timeout" | "provider_error" | "empty_answer" |
    #: "total_budget".  The user-facing wording keys off it — "did not answer
    #: in time" is factually WRONG when the provider did answer but produced
    #: no usable content (finish_reason=length, 0 content chars; see
    #: docs/EMPTY_ANSWER_ROOT_CAUSE.md).
    failure_reason: Optional[str] = None

    @property
    def usable(self) -> bool:
        return not self.provider_failed

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "understanding": self.understanding,
            "entities": self.entities,
            "evidence_requested": [r.kind for r in self.evidence_requests],
            "evidence": render_evidence_compact(self.evidence_results),
            "question": self.question,
            "proposal_tools": [
                t.get("tool_name") for t in (self.proposal or {}).get("tools", [])
            ],
            "violations": self.violations,
            "decision": self.decision,
            "prerequisite_count": len(self.prerequisites),
            "provider_failed": self.provider_failed,
            "rounds": self.rounds,
        }


# ---------------------------------------------------------------------------
# Prompt assembly — every block is labelled for what it actually is
# ---------------------------------------------------------------------------


def _render_history(history: Sequence[Dict[str, str]]) -> str:
    if not history:
        return "(none)"
    lines = []
    for qa in history[-8:]:
        lines.append(f"  Q: {qa.get('question', '')}")
        lines.append(f"  A: {qa.get('answer', '')}")
    return "\n".join(lines)


def _render_dict_block(data: Dict[str, Any], limit: int = 40) -> str:
    if not data:
        return "(none provided)"
    lines = []
    for idx, (key, value) in enumerate(data.items()):
        if idx >= limit:
            lines.append("  …")
            break
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str, ensure_ascii=False)[:400]
        lines.append(f"  - {key}: {value}")
    return "\n".join(lines)


def _contract_line(
    tool_name: str,
    contract: Dict[str, Any],
    alias_pairs: Sequence[str],
) -> str:
    """One compact line per tool: accepted names, required subset, aliases."""
    accepted = ", ".join(contract.get("accepted") or ())
    required = ", ".join(contract.get("required") or ())
    parts = [f"  {tool_name}: {accepted or '(no arguments)'}"]
    if required:
        parts.append(f" [required: {required}]")
    if alias_pairs:
        parts.append(f" [reference aliases accepted: {', '.join(alias_pairs)}]")
    return "".join(parts)


def _render_tool_contracts_block(
    offered_tools: Sequence[str],
    tool_contracts: Optional[Dict[str, Dict[str, Any]]],
) -> List[str]:
    """Real executable signatures for OFFERED MUTATION tools only.

    Why this exists (forensic latency report, P0-②): the prompt used to list
    tool SLUGS ONLY, so the model composed argument keys from whatever
    vocabulary it could see (evidence rows, entity field names) and Python
    rejected the proposal AFTER a full generation round — production session
    3ea794a0 burned ~10.7s on exactly that rejection before its rounds were
    exhausted.  Rendering the signature-derived contract up front raises
    first-pass success WITHOUT weakening validation: the deterministic gate
    (``validate_outcome`` → ``tool_contract.validate_calls``) still runs
    unchanged afterwards.

    Deliberate size rules (report §6, prompt latency budget):
    * mutation tools only — read-only mis-namings are rare and the rejection
      message names them precisely; never the whole 49-tool registry;
    * names come from ``tool_contracts()`` (inspect()-derived at import time,
      never hand-maintained) and only alias keys the GATE accepts
      (``declared_reference_inputs``) are advertised, so every name shown is
      actually executable.
    """
    if not tool_contracts:
        return []
    try:
        from app.plan_materialization import declared_reference_inputs
        from app.tool_execution import is_read_only_tool

        ref_inputs = declared_reference_inputs()
    except Exception:  # noqa: BLE001 — prompt assembly must never break
        log.warning("accounting_reasoning.contracts_block_unavailable")
        return []
    lines: List[str] = []
    for slug in sorted(set(offered_tools or ())):
        contract = tool_contracts.get(slug)
        if not contract or is_read_only_tool(slug):
            continue
        pairs = [
            f"{alias}->{param}"
            for param, aliases in (ref_inputs.get(slug) or {}).items()
            for alias in (aliases or ())
        ]
        lines.append(_contract_line(slug, contract, pairs))
    if not lines:
        return []
    return [
        "TOOL ARGUMENT CONTRACTS — the REAL executable signatures. Compose "
        "arguments with EXACTLY these parameter names: Python rejects any "
        "other name BEFORE anything executes. 'alias->param' names a "
        "reference input the gate accepts; Python resolves it to the "
        "canonical id before execution:",
        *lines,
        "",
    ]


def build_reasoning_prompt(
    facts: Optional[ReasoningFacts] = None,
    *,
    evidence_block: str = "",
    violations: Sequence[str] = (),
    offered_tools: Sequence[str] = (),
    tool_contracts: Optional[Dict[str, Dict[str, Any]]] = None,
    section: Optional[str] = None,
    intent: Optional[str] = None,
) -> str:
    """Assemble the labelled reasoning prompt.

    When ``facts`` is omitted, returns only the assembled system rules
    (``_BASE_SYSTEM_RULES`` plus any module matching ``section``/``intent``).
    When ``facts`` is provided, the labels are contractual: deterministic Python
    output is always labelled PRELIMINARY, and retrieved records are always
    labelled LIVE BOOKS EVIDENCE.
    """
    rules_text = assemble_system_rules(section=section, intent=intent)
    if facts is None:
        return rules_text

    parts: List[str] = [rules_text, ""]

    parts.append(
        "ORIGINAL USER REQUEST (preserve this wording — it is the "
        "authoritative statement of what the user wants):"
    )
    parts.append(f"  {facts.user_request or '(empty)'}")
    parts.append("")

    parts.append(
        "CONVERSATION HISTORY (questions already asked and answers already "
        "given — never ask these again):"
    )
    parts.append(_render_history(facts.conversation_history))
    parts.append("")

    parts.append(f"{_PRELIMINARY_LABEL}:")
    parts.append(_render_dict_block(facts.preliminary or {}))
    parts.append("")

    parts.append("ORGANIZATION PROFILE:")
    parts.append(_render_dict_block(facts.organization or {}))
    parts.append("")

    parts.append("ACCOUNTING PERIOD:")
    parts.append(_render_dict_block(facts.accounting_period or {}))
    parts.append("")

    if facts.org_policies:
        parts.append(
            "LEARNED ANSWERS FROM PAST SESSIONS (context only — NOT standing policy):"
        )
        parts.append(_render_dict_block(facts.org_policies))
        parts.append(
            "Each value above was the user's answer for ONE earlier transaction. "
            "It is not a fact about the current request and never a standing "
            "default: settlement (cash/bank/credit), nature and dates come from "
            "THIS request or a fresh question — never from these rows."
        )
        parts.append("")

    if facts.economic_hints:
        parts.append(
            "TRANSACTION CLASSIFICATION HINTS (preliminary, deterministic — "
            "override them if the records say otherwise):"
        )
        parts.append(_render_dict_block(facts.economic_hints))
        parts.append("")

    if facts.prohibitions:
        parts.append(
            "KNOWN PROHIBITIONS (enforced by the executor — do not propose "
            "these):"
        )
        for item in facts.prohibitions[:10]:
            parts.append(f"  · {item}")
        parts.append("")

    if offered_tools:
        parts.append("OFFERED TOOLS (the only tool names a proposal may use):")
        parts.append("  " + ", ".join(sorted(offered_tools)))
        parts.append("")

    # P0-②: first-pass success — the model sees each offered mutation tool's
    # REAL argument contract before generating, so proposals bind on attempt 1
    # instead of paying a ~6-11s reject-and-retry round.  Validation itself is
    # untouched and still runs after every generation.
    parts.extend(_render_tool_contracts_block(offered_tools, tool_contracts))

    parts.append(evidence_catalog_text())
    parts.append("")

    # P2-⑫ (forensic report ⑫): STATIC PREFIX contract — everything above
    # (and TODAY here) is byte-stable across rounds; the first dynamic byte
    # is the LIVE BOOKS evidence block below. Prefix/KV-caching providers
    # reuse the static head (≈10-14KB) on rounds 2+. _RESPONSE_SHAPE stays
    # deliberately LAST (recency aids format compliance; re-sent per call
    # by design — documented, not accidental).
    parts.append(f"TODAY: {facts.today or '(unset)'}")
    parts.append("")

    if evidence_block:
        parts.append(evidence_block)
        parts.append("")
        parts.append(
            "The section above is LIVE BOOKS EVIDENCE retrieved from this "
            "organization's books. Reassess the request against it. If it "
            "contradicts the preliminary extraction, follow the records."
        )
        parts.append("")

    if facts.previous_tool_results:
        parts.append(
            "PREVIOUS TOOL RESULTS (actual outcomes of already-executed "
            "operations — read them before proposing anything new):"
        )
        parts.append(_render_dict_block({"results": facts.previous_tool_results}))
        parts.append("")

    if facts.previous_confirmations:
        parts.append("PREVIOUS CONFIRMATIONS (what the user already approved):")
        parts.append(_render_dict_block({"confirmed": facts.previous_confirmations}))
        parts.append("")

    if violations:
        parts.append(
            "REJECTED BY THE EXECUTION LAYER (your previous answer was refused "
            "by Python; correct it — do not repeat it):"
        )
        for item in violations:
            parts.append(f"  · {item}")
        parts.append("")

    # P2-⑫: TODAY is a STATIC value — it now renders BEFORE the dynamic
    # evidence/violations tail (moved up in build_reasoning_prompt); this
    # tail-only duplicate is removed so the static prefix stays intact.
    parts.append(_RESPONSE_SHAPE)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parsing + Python validation of the model's decision
# ---------------------------------------------------------------------------

_JSON_START = re.compile(r"\{", re.S)


def parse_reasoning_response(raw: Any) -> Optional[Dict[str, Any]]:
    """Extract the JSON decision object from a provider response.

    Tolerates code fences and surrounding prose; returns None when no JSON
    object can be found (the caller treats that as a provider failure and
    degrades to the deterministic path rather than inventing a decision).
    """
    text = raw if isinstance(raw, str) else ""
    text = text.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001 — fall through to brace scanning
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    match = _JSON_START.search(text)
    if not match:
        return None
    depth = 0
    for idx in range(match.start(), len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    candidate = json.loads(text[match.start(): idx + 1])
                except Exception:  # noqa: BLE001
                    return None
                return candidate if isinstance(candidate, dict) else None
    return None


def _clean_list(value: Any, limit: int = 12, item_limit: int = 300) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            item = (
                item.get("name")
                or item.get("text")
                or json.dumps(item, default=str, ensure_ascii=False)
            )
        text = str(item or "").strip()
        if text:
            out.append(text[:item_limit])
    return out


def _clean_question(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        text = raw.strip()
        return (
            {"text": text, "options": [], "options_per_part": []}
            if text
            else None
        )
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or raw.get("question") or "").strip()
    if not text:
        return None
    # 360° questionnaire: per-numbered-line quick choices, ALIGNED to the
    # "1. … 2. …" lines of `text` (the UI renders one answer box + chips
    # per line).  Anything unaligned/unshaped is dropped, never guessed.
    parts = raw.get("options_per_part")
    clean_parts: List[List[str]] = []
    if isinstance(parts, list):
        for part in parts[:12]:
            if isinstance(part, list):
                clean_parts.append(_clean_list(part, 6, 60))
            elif isinstance(part, str) and part.strip():
                clean_parts.append([part.strip()[:60]])

    # FIXED-FORMAT QUESTIONNAIRE: the model's own structured questions
    # (field/kind/text/options).  Structurally cleaned HERE; the field
    # vocabulary + already-known-fact filter is enforced by
    # app.questionnaire.validate_authored_questions at the response site
    # (only there are the request's known facts available).
    clean_questions: List[Dict[str, Any]] = []
    raw_questions = raw.get("questions")
    if isinstance(raw_questions, list):
        for entry in raw_questions[:12]:
            if not isinstance(entry, dict):
                continue
            field_name = str(entry.get("field") or "").strip().lower()
            question_text = str(entry.get("question") or "").strip()
            if not field_name or not question_text:
                continue
            kind = str(entry.get("kind") or "text").strip().lower()
            options: List[Dict[str, str]] = []
            raw_options = entry.get("options")
            if isinstance(raw_options, list):
                for opt in raw_options[:6]:
                    if isinstance(opt, dict):
                        value = str(opt.get("value") or "").strip()[:60]
                        label = str(opt.get("label") or value).strip()[:60]
                    else:
                        value = label = str(opt or "").strip()[:60]
                    if value:
                        options.append({"value": value, "label": label or value})
            clean_questions.append(
                {
                    "field": field_name,
                    "kind": kind,
                    "question": question_text[:300],
                    "options": options,
                    "answer_hint": str(entry.get("answer_hint") or "").strip()[:120]
                    or None,
                    "why": str(entry.get("why") or "").strip()[:160] or None,
                }
            )
    # Derive the per-line tap options from the structured questions when the
    # model did not send options_per_part (ONE payload shape downstream).
    if clean_questions and not clean_parts:
        clean_parts = [
            [opt["label"] for opt in q.get("options") or []][:6]
            for q in clean_questions
        ]
    return {
        "text": text[:1500],
        "options": _clean_list(raw.get("options"), 6, 80),
        "options_per_part": clean_parts,
        "questions": clean_questions,
    }


def _clean_tool_calls(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool_name") or item.get("name") or "").strip()
        if not name:
            continue
        args = item.get("arguments")
        out.append(
            {"tool_name": name, "arguments": args if isinstance(args, dict) else {}}
        )
    return out


def _clean_impact(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw[:20]:
        if not isinstance(item, dict):
            continue
        account = str(item.get("account") or item.get("account_name") or "").strip()
        if not account:
            continue
        entry: Dict[str, Any] = {"account": account[:200]}
        for side in ("debit", "credit"):
            value = item.get(side)
            if isinstance(value, (int, float)):
                entry[side] = float(value)
        reason = str(item.get("reason") or "").strip()
        if reason:
            entry["reason"] = reason[:200]
        out.append(entry)
    return out


def _clean_proposal(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    return {
        "interpretation": str(
            raw.get("interpretation") or raw.get("business_interpretation") or ""
        ).strip()[:1500],
        "affected_records": _clean_list(raw.get("affected_records")),
        "accounting_impact": _clean_impact(raw.get("accounting_impact")),
        "not_affected": _clean_list(raw.get("not_affected")),
        "unresolved_uncertainty": _clean_list(raw.get("unresolved_uncertainty")),
        "tools": _clean_tool_calls(raw.get("tools") or raw.get("tool_calls")),
        "confirmation": str(
            raw.get("confirmation") or raw.get("confirmation_request") or ""
        ).strip()[:1500],
    }


def validate_outcome(
    outcome: ReasoningOutcome,
    *,
    offered_tools: Sequence[str] = (),
    forbidden_tools: Sequence[str] = (),
    tool_contracts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Deterministic enforcement of a decision.  Returns violation messages.

    A violation means the decision is NOT executed; it is fed back to the model
    (bounded by the round budget) instead of being repaired silently.
    """
    violations: List[str] = []
    proposal = outcome.proposal or {}
    tools = _clean_tool_calls(proposal.get("tools"))

    if outcome.status == NEEDS_EVIDENCE:
        if not outcome.evidence_requests:
            violations.append(
                "Status NEEDS_EVIDENCE requires at least one evidence request."
            )
        return violations

    if outcome.status == NEEDS_INPUT:
        if not outcome.question or not str(outcome.question.get("text") or "").strip():
            violations.append("Status NEEDS_INPUT requires a question for the user.")
        return violations

    if outcome.status == PROPOSAL:
        # SINGLE-CALL CONTRACT: material facts BLOCK the posting, so a
        # proposal that still declares them is fed back to the model — the
        # SAME response must carry the consolidated questionnaire (step b),
        # never defer the ask to a later pipeline stage (which would cost
        # the user a second provider round-trip for the questions).
        if outcome.missing_facts:
            violations.append(
                "missing_material_facts is non-empty, so a proposal is "
                "invalid — write the consolidated questionnaire (step b) "
                "in this SAME response instead."
            )
        if not tools:
            violations.append(
                "A proposal must name at least one tool from the offered list."
            )
        allowed = set(offered_tools or ())
        if allowed:
            for call in tools:
                if call["tool_name"] not in allowed:
                    violations.append(
                        f"Tool '{call['tool_name']}' is not in the offered tool "
                        "list — propose only offered tools."
                    )
        forbidden = set(forbidden_tools or ())
        for call in tools:
            if call["tool_name"] in forbidden:
                violations.append(
                    f"Tool '{call['tool_name']}' is prohibited for this economic "
                    "event by the organization's accounting policy."
                )
        # The proposed ARGUMENTS must bind against the Python contract of the
        # tool that will receive them.  The model is offered tool NAMES only,
        # so it composes argument keys from the vocabulary it can see (entity
        # fields, org preferences): a plan may propose create_invoice with
        # 'line_items' / 'customer_name' / 'tax_category', the user approves it,
        # and the call then dies at CALL-BINDING time with no database work at
        # all.  Python therefore
        # rejects the un-bindable call HERE — before any confirmation snapshot
        # exists — and feeds the precise message back to the model.
        from app.plan_materialization import (
            declared_reference_inputs as _declared_reference_inputs,
        )
        from app.tool_contract import validate_calls as _validate_calls

        violations.extend(
            _validate_calls(
                tools,
                tool_contracts,
                # The DECLARED alias inputs are legal here: plan materialization
                # resolves them into canonical ids before execution.  A model
                # cannot supply the id of a record that does not exist yet, and
                # inventing one is forbidden — so these must pass the gate.
                reference_inputs=_declared_reference_inputs(),
            )
        )
        stated = set(outcome.stated_disclosures)
        for field_name in REQUIRED_PROPOSAL_FIELDS:
            if field_name not in stated:
                violations.append(
                    f"A proposal must state '{field_name}'. Every proposal "
                    "must disclose its interpretation, the records it affects, "
                    "its proposed accounting impact, what it deliberately does "
                    "NOT affect, and its unresolved uncertainty — an empty "
                    "list is a claim, an omitted field is silence."
                )
        if not str(proposal.get("interpretation") or "").strip():
            violations.append(
                "A proposal must state its business interpretation in words."
            )
        if not str(proposal.get("confirmation") or "").strip():
            violations.append(
                "A proposal that changes records must include the exact "
                "confirmation sentence to show the user."
            )
        return violations

    return violations


def proposed_mutation_tools(outcome: ReasoningOutcome) -> List[Dict[str, Any]]:
    """The proposed tool calls that would CHANGE records.

    Read-only tools are identified from the trusted registry — never from the
    model's own claim about what a tool does.
    """
    from app.tool_execution import is_read_only_tool

    tools = _clean_tool_calls((outcome.proposal or {}).get("tools"))
    return [call for call in tools if not is_read_only_tool(call["tool_name"])]


# ---------------------------------------------------------------------------
# The loop — request evidence, reassess, decide (bounded, never raising)
# ---------------------------------------------------------------------------


def _status_from_decision(parsed: Dict[str, Any]) -> str:
    """Map the model's decision to exactly one outcome kind.

    Precedence is deliberate: an explicit refusal or completion wins, then a
    proposal, then a question, then a request for evidence.  The model cannot
    smuggle two decisions in one payload — the first applicable one is used.
    """
    refusal = parsed.get("refusal")
    if isinstance(refusal, dict) and (
        refusal.get("reason") or refusal.get("explanation")
    ):
        return REFUSAL
    if parsed.get("complete") is True:
        return COMPLETE
    if isinstance(parsed.get("proposal"), dict) and parsed["proposal"]:
        return PROPOSAL
    if parsed.get("question"):
        return NEEDS_INPUT
    if parsed.get("evidence_requests"):
        return NEEDS_EVIDENCE
    if parsed.get("missing_material_facts"):
        return NEEDS_INPUT
    return UNSUPPORTED


def _clean_entities(raw: Any) -> Dict[str, Any]:
    """Parse and sanitize extracted entities from the LLM reasoning response."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}

    amt = raw.get("amount")
    if amt is not None:
        try:
            val = float(str(amt).replace(",", "").strip())
            if val >= 0:
                out["amount"] = val
        except (ValueError, TypeError):
            pass

    for key in (
        "item_description",
        "transaction_purpose",
        "supplier_name",
        "customer_name",
        "account_name",
        "transaction_date",
        "payment_method",
        "settlement_position",
        "currency",
        "notes",
    ):
        v = raw.get(key)
        if v is not None:
            s = str(v).strip()
            if s and s.lower() not in ("null", "none"):
                out[key] = s[:200]

    qty = raw.get("quantity")
    if qty is not None:
        try:
            q_val = float(qty)
            out["quantity"] = int(q_val) if q_val.is_integer() else q_val
        except (ValueError, TypeError):
            pass

    raw_lines = raw.get("line_items")
    if isinstance(raw_lines, list) and raw_lines:
        clean_lines = []
        for itm in raw_lines:
            if not isinstance(itm, dict):
                continue
            desc = str(itm.get("description") or itm.get("product_name") or itm.get("name") or "").strip()
            if not desc:
                continue
            entry: Dict[str, Any] = {"description": desc[:120]}
            qty_val = itm.get("quantity")
            if qty_val is not None:
                try:
                    q = float(qty_val)
                    entry["quantity"] = int(q) if q.is_integer() else q
                except (ValueError, TypeError):
                    pass
            unit_p = itm.get("unit_price") or itm.get("price") or itm.get("rate")
            if unit_p is not None:
                try:
                    p = float(unit_p)
                    if p >= 0:
                        entry["unit_price"] = p
                except (ValueError, TypeError):
                    pass
            tot_a = itm.get("total_amount") or itm.get("total") or itm.get("amount")
            if tot_a is not None:
                try:
                    t = float(tot_a)
                    if t >= 0:
                        entry["total_amount"] = t
                except (ValueError, TypeError):
                    pass
            clean_lines.append(entry)
        if clean_lines:
            out["line_items"] = clean_lines

    # Ensure transaction_purpose has a fallback from item_description if absent
    if "item_description" in out and "transaction_purpose" not in out:
        out["transaction_purpose"] = out["item_description"]

    return out


def _clean_decision(raw: Any) -> Dict[str, str]:
    """Parse the optional Wave A ``decision`` block (strings only, bounded).

    Deliberately NO vocabulary check here: canonicality is evaluated by the
    DIVERGENCE COMPARISON in agent.py, so a non-canonical value is recorded as
    MODEL_NONCANONICAL instead of silently dropped — and instead of rejecting
    the whole proposal, which would change behavior in an observation-only
    Wave (AUDIT_REPORT §7/§8).  Wave B turns canonicality into a violation.
    """
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    intent = str(raw.get("intent") or "").strip().lower()
    if intent:
        out["intent"] = intent[:64]
    for key in ("treatment", "document_nature"):
        value = str(raw.get(key) or "").strip().upper()
        if value:
            out[key] = value[:40]
    return out


def _clean_prerequisites(raw: Any) -> List[Dict[str, str]]:
    """Parse the optional Wave A ``prerequisites`` block (bounded, no action).

    Recorded only — no prerequisite is created, resolved or skipped by this
    block.  Acting on it is Wave C work (AUDIT_REPORT §7).
    """
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, str]] = []
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:80]
        if not name:
            continue
        entry = {"name": name}
        for key in ("status", "resolution"):
            value = str(item.get(key) or "").strip().lower()[:24]
            if value:
                entry[key] = value
        why = str(item.get("why") or "").strip()[:200]
        if why:
            entry["why"] = why
        out.append(entry)
    return out


def _outcome_from_parsed(parsed: Dict[str, Any], *, rounds: int) -> ReasoningOutcome:
    status = _status_from_decision(parsed)
    understanding = parsed.get("understanding")
    return ReasoningOutcome(
        status=status,
        understanding=understanding if isinstance(understanding, dict) else {},
        entities=_clean_entities(parsed.get("entities")),
        evidence_requests=parse_evidence_requests(parsed.get("evidence_requests")),
        question=_clean_question(parsed.get("question")),
        missing_facts=[
            {
                "fact": str(f.get("fact") or "")[:200],
                "why_material": str(f.get("why_material") or f.get("why") or "")[:300],
                "question": str(f.get("question") or "")[:500],
            }
            for f in (parsed.get("missing_material_facts") or [])
            if isinstance(f, dict)
        ][:6],
        proposal=_clean_proposal(parsed.get("proposal")),
        stated_disclosures=_stated_disclosures(parsed.get("proposal")),
        decision=_clean_decision(parsed.get("decision")),
        prerequisites=_clean_prerequisites(parsed.get("prerequisites")),
        refusal=parsed.get("refusal") if isinstance(parsed.get("refusal"), dict) else None,
        rounds=rounds,
    )


def refusal_text(refusal: Optional[Dict[str, Any]]) -> str:
    """Human-readable refusal/conclusion text from the model's payload."""
    if not refusal:
        return ""
    return str(
        refusal.get("reason")
        or refusal.get("explanation")
        or refusal.get("message")
        or ""
    ).strip()


def _evidence_cache_key(request: EvidenceRequest) -> tuple:
    """Loop-local evidence cache key: (kind, canonical argument JSON).

    Why this needs NO invalidation machinery (forensic latency report,
    P0-③): the reasoning loop runs BEFORE any execution, so no mutation can
    change the books while it lives — identical (kind, args) reads against
    the same organization always return the same rows.  The dict is local to
    one ``run_reasoning_loop`` call and the org is fixed by the caller, so
    scope, freshness and tenant isolation hold by construction.  Args are
    canonicalized with ``sort_keys``; anything un-keyable falls back to
    ``repr`` — an exotic value may MISS the cache, and a miss is always
    safe; only a wrong HIT would be a correctness bug, so keying fails
    toward re-fetching.
    """
    kind = (request.kind or "").strip().lower()
    try:
        args_key = json.dumps(request.args or {}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 — never break the loop on keying
        args_key = repr(request.args or {})
    return (kind, args_key)


#: P1-⑩ (forensic latency report §5): preliminary subject-area HINTS → the
#: evidence kinds they most often imply. Hints only — nothing here decides a
#: treatment; a miss just costs a cheap read-only query that runs in
#: parallel with the round-1 model call anyway.
_PREFETCH_KIND_MAP: Dict[str, str] = {
    "receivables": "open_receivables",
    "payables": "open_payables",
    "fixed_assets": "fixed_assets",
    "bank": "bank_accounts",
    "cash": "bank_accounts",
    "purchases": "purchase_orders",
    "procurement": "purchase_orders",
    "orders": "purchase_orders",
}
_PREFETCH_MAX_KINDS = 3


def _prefetch_requests(
    facts: Any,
    evidence_cache: Dict[tuple, EvidenceResult],
) -> List[EvidenceRequest]:
    """Speculative round-1 prefetch requests (default args only).

    Registered kinds only, at most ``_PREFETCH_MAX_KINDS``, and never a kind
    already served by the P1-⑤ seed (same cache keys — a seeded kind would
    be a pointless duplicate fetch).
    """
    preliminary = getattr(facts, "preliminary", None) or {}
    areas = [str(a or "") for a in (preliminary.get("candidate_subject_areas") or [])]
    requests: List[EvidenceRequest] = []
    seen: set = set()
    for area in areas:
        kind = _PREFETCH_KIND_MAP.get(area)
        if not kind or kind in seen or kind not in EVIDENCE_KINDS:
            continue
        request = EvidenceRequest(
            kind=kind, why="speculative prefetch (preliminary subject-area hint)"
        )
        if _evidence_cache_key(request) in evidence_cache:
            continue
        seen.add(kind)
        requests.append(request)
        if len(requests) >= _PREFETCH_MAX_KINDS:
            break
    return requests


def _reap_prefetch(task: "asyncio.Task") -> None:
    """Reap a never-consumed prefetch task (fire-and-forget hygiene).

    The read-only task completes on its own; only its exception, if any,
    must not surface later as 'Task exception was never retrieved'.
    """
    if task.cancelled():
        return
    try:
        task.exception()
    except Exception:  # noqa: BLE001 — reaping must never raise
        pass


def serialize_evidence_memo(
    results: Sequence[EvidenceResult],
) -> List[Dict[str, Any]]:
    """P1-⑤: durable form of this turn's cacheable evidence for the NEXT
    turn of the same conversation (freshness is checked at LOAD time).

    Bounded by construction: at most 12 entries and the whole payload kept
    under ~90KB, so the step writer's raised cap never shears it into
    invalid JSON (a truncated memo fails soft at load = plain refetch).
    """
    entries: List[Dict[str, Any]] = []
    for res in list(results or []):
        if res is None or res.error is not None:
            continue
        entries.append(
            {
                "kind": res.kind,
                "args": dict(getattr(res, "args", None) or {}),
                "result": {
                    "kind": res.kind,
                    "title": res.title,
                    "why": res.why,
                    "records": res.records,
                    "source": res.source,
                    "truncated": bool(res.truncated),
                    "rejected": bool(res.rejected),
                },
            }
        )
    out = entries[:12]
    while out and len(json.dumps({"evidence_full": out}, default=str)) > 90_000:
        out.pop()
    return out


def deserialize_evidence_memo(payload: Any) -> List[EvidenceResult]:
    """Inverse of ``serialize_evidence_memo``.

    FAIL SOFT: any malformed / sheared payload returns ``[]`` — the caller
    simply re-fetches (a miss is always safe; only a wrong HIT would be a
    correctness bug, so loading fails toward re-fetching).
    """
    try:
        data = json.loads(payload) if isinstance(payload, str) else (payload or {})
        raw_entries = data.get("evidence_full") if isinstance(data, dict) else None
        if not isinstance(raw_entries, list):
            return []
        out: List[EvidenceResult] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            raw = entry.get("result") or {}
            res = EvidenceResult(
                kind=str(raw.get("kind") or entry.get("kind") or ""),
                title=str(raw.get("title") or ""),
                why=str(raw.get("why") or ""),
                records=[r for r in (raw.get("records") or []) if isinstance(r, dict)],
                source=str(raw.get("source") or ""),
                error=raw.get("error"),
                truncated=bool(raw.get("truncated")),
                rejected=bool(raw.get("rejected")),
            )
            if res.error is not None:
                continue
            res.args = dict(entry.get("args") or {})
            out.append(res)
        return out
    except Exception:  # noqa: BLE001 — a memo load must never break a turn
        log.warning("accounting_reasoning.evidence_memo_unreadable")
        return []


def _observe_two_call(
    parsed: Dict[str, Any],
    *,
    round_index: int,
    elapsed_ms: Optional[int],
    notify: Any,
) -> None:
    """STAGE 2 — two-call OBSERVATION (diagnostic only, fail-closed).

    Projects the EXISTING authoritative response onto the future Call A /
    Call B contracts and forwards the projection to the audit hook.  Gated by
    ``settings.two_call_observation_enabled`` (default False): with the flag
    off this returns before anything two-call related is imported, so today's
    runtime is unchanged.  Returns nothing, never raises, and its payload is
    never read back — an observation failure must leave the transaction path
    exactly as it was (§13).
    """
    try:
        from app.config import get_settings

        if not bool(getattr(get_settings(), "two_call_observation_enabled", False)):
            return
        from app.two_call_observation import build_two_call_observation

        notify(
            "TWO_CALL_OBSERVATION",
            build_two_call_observation(
                parsed, round_index=round_index, elapsed_ms=elapsed_ms
            ),
        )
    except Exception as exc:  # noqa: BLE001 — observation must never break a turn
        log.warning(
            "accounting_reasoning.two_call_observation_failed", error=str(exc)[:200]
        )


async def run_reasoning_loop(
    facts: ReasoningFacts,
    *,
    organization_id: uuid.UUID,
    auth: Any = None,
    session_id: Optional[uuid.UUID] = None,
    orchestrator: Any = None,
    offered_tools: Sequence[str] = (),
    forbidden_tools: Sequence[str] = (),
    max_rounds: int = MAX_REASONING_ROUNDS,
    timeout_seconds: Optional[float] = None,
    step_logger: Any = None,
    tool_contracts: Optional[Dict[str, Dict[str, Any]]] = None,
    prior_evidence: Sequence[EvidenceResult] = (),
    prefetch_enabled: bool = False,
    section: Optional[str] = None,
    intent: Optional[str] = None,
) -> ReasoningOutcome:
    """Run the LLM accounting reasoning loop against the live books.

    Returns a :class:`ReasoningOutcome`.  Provider unavailability (disabled,
    down, timeout, unparseable) yields ``provider_failed=True`` so the caller
    keeps its deterministic behaviour instead of fabricating a decision.
    """
    import asyncio
    import time

    from app.config import get_settings

    log.warning("accounting_reasoning.legacy_path_invoked")
    settings = get_settings()
    budget = (
        timeout_seconds
        if timeout_seconds is not None
        else float(getattr(settings, "accounting_reasoning_timeout", 90.0))
    )
    total_budget = float(
        getattr(settings, "accounting_reasoning_total_timeout", 135.0)
    )
    # Optional dedicated model chain for this one call (see the config field).
    # It is passed ONLY to providers that declare it, so the stage keeps working
    # with any orchestrator implementation (and with test doubles).
    chain = [
        m.strip()
        for m in str(getattr(settings, "accounting_reasoning_model_chain", "") or "").split(",")
        if m.strip()
    ]
    generate = getattr(orchestrator, "generate_text", None) if orchestrator else None
    chain_supported = False
    thinking_off_supported = False
    if callable(generate):
        try:
            import inspect

            params = inspect.signature(generate).parameters
            if chain:
                chain_supported = "model_chain" in params or any(
                    p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
                )
            # The empty-answer retry passes `thinking_off` only when the
            # transport actually takes it (Qwen does; stubs and test doubles
            # may not).
            thinking_off_supported = "thinking_off" in params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
        except (TypeError, ValueError):  # pragma: no cover - exotic callables
            chain_supported = False
            thinking_off_supported = False
    if not callable(generate) or not facts.user_request.strip():
        return ReasoningOutcome(status=UNSUPPORTED, provider_failed=True)

    def _notify(event: str, payload: Dict[str, Any]) -> None:
        """Best-effort audit hook — never allowed to break the loop."""
        if not callable(step_logger):
            return
        try:
            step_logger(event, payload)
        except Exception:  # noqa: BLE001
            log.warning("accounting_reasoning.step_logger_failed", event=event)

    evidence_block = ""
    gathered: List[EvidenceResult] = []
    # P0-③: cross-round evidence cache — see _evidence_cache_key.
    evidence_cache: Dict[tuple, EvidenceResult] = {}
    # P1-⑤: seed from this conversation's earlier PARKED turn (the caller
    # has already proved it mutation-free). Same keying as P0-③, so a
    # re-request this turn is a cache hit with ZERO database reads.
    for _res in prior_evidence or ():
        if _res is None or _res.error is not None:
            continue
        _key = _evidence_cache_key(
            EvidenceRequest(
                kind=_res.kind, why=_res.why,
                args=getattr(_res, "args", None) or {},
            )
        )
        if _key not in evidence_cache:
            evidence_cache[_key] = _res
            gathered.append(_res)
    if gathered:
        _notify("EVIDENCE_SEEDED", {"kinds": [r.kind for r in gathered]})
    # P1-⑩ (forensic report §5): start hinted read-only loaders NOW, in
    # parallel with the round-1 model call (6-11s). If the model asks for
    # them they are served instantly — the common settlement flow becomes a
    # 1-round decision; if not, only cheap read-only queries were spent and
    # the task is reaped. Flag: accounting_reasoning_prefetch.
    prefetch_task: Optional["asyncio.Task"] = None
    prefetch_requests: List[EvidenceRequest] = []
    prefetch_pool: Dict[tuple, EvidenceResult] = {}
    if prefetch_enabled:
        prefetch_requests = _prefetch_requests(facts, evidence_cache)
        if prefetch_requests:
            prefetch_task = asyncio.create_task(
                gather_evidence(
                    prefetch_requests,
                    organization_id=organization_id,
                    auth=auth,
                    session_id=session_id,
                )
            )
            prefetch_task.add_done_callback(_reap_prefetch)
            _notify(
                "EVIDENCE_PREFETCH",
                {"kinds": [r.kind for r in prefetch_requests]},
            )
    rejected: List[str] = []
    violations: List[str] = []
    outcome = ReasoningOutcome(status=UNSUPPORTED)
    rounds_used = 0
    # ONE bounded retry for the measured empty-answer failure: a thinking model
    # whose hidden reasoning consumed the whole output cap returned nothing
    # usable (finish_reason=length, 0 content chars).  The retry runs the SAME
    # round with thinking disabled — measured to return valid JSON in ~5.7s —
    # and only when the stage's own deadline still allows it.
    empty_answer_retry_used = False
    thinking_off_next = False
    # The whole stage is bounded, not just each round: three slow rounds must
    # never add up to a minute of user-visible waiting.
    deadline = asyncio.get_running_loop().time() + total_budget

    for round_index in range(max(1, max_rounds)):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0.5:
            log.warning(
                "accounting_reasoning.failed",
                reason="total_budget_exhausted",
                round=round_index + 1,
            )
            return ReasoningOutcome(
                status=UNSUPPORTED,
                provider_failed=True,
                provider_attempted=rounds_used > 0,
                evidence_results=gathered,
                rounds=rounds_used,
                failure_reason="total_budget",
            )
        round_budget = min(budget, remaining)
        rounds_used = round_index + 1
        round_started = time.monotonic()
        prompt = build_reasoning_prompt(
            facts,
            evidence_block=evidence_block,
            violations=violations,
            offered_tools=offered_tools,
            # P0-②: pass the SAME inspect()-derived contracts the validation
            # gate enforces — the model proposes against the real signature.
            tool_contracts=tool_contracts,
            section=section,
            intent=intent,
        )
        try:
            call_kwargs: Dict[str, Any] = {"prompt": prompt}
            if chain and chain_supported:
                call_kwargs["model_chain"] = chain
            if thinking_off_next and thinking_off_supported:
                # The empty-answer retry: same prompt, no hidden reasoning.
                call_kwargs["thinking_off"] = True
            raw = await asyncio.wait_for(
                generate(**call_kwargs), timeout=round_budget
            )
        except asyncio.TimeoutError:
            log.warning(
                "accounting_reasoning.failed",
                reason="timeout",
                round=rounds_used,
                budget_s=round(round_budget, 2),
            )
            return ReasoningOutcome(
                status=UNSUPPORTED,
                provider_failed=True,
                provider_attempted=True,
                evidence_results=gathered,
                rounds=rounds_used,
                failure_reason="timeout",
            )
        except Exception as exc:  # noqa: BLE001 — the stage must never raise
            # BUSY vs BROKEN: an orchestrator that exhausted every provider on
            # throttling raises AllProvidersRateLimited, and the run must report
            # "rate limited" instead of a generic outage (the user would
            # otherwise be told the AI "did not answer in time").
            from app.ai_orchestrator import _is_rate_limited

            _reason = "rate_limited" if _is_rate_limited(exc) else "provider_error"
            log.warning(
                "accounting_reasoning.failed",
                reason=_reason,
                detail=str(exc)[:200],
                round=rounds_used,
            )
            return ReasoningOutcome(
                status=UNSUPPORTED,
                provider_failed=True,
                provider_attempted=True,
                evidence_results=gathered,
                rounds=rounds_used,
                failure_reason=_reason,
            )

        parsed = parse_reasoning_response(raw)
        if not parsed:
            # The provider ANSWERED but produced nothing parseable.  Retry
            # once with thinking disabled (measured fix); if the deadline or
            # the round budget forbids it, fail with the honest reason.
            if (
                not empty_answer_retry_used
                and round_index + 1 < max_rounds
                and (deadline - asyncio.get_running_loop().time()) > 1.0
            ):
                empty_answer_retry_used = True
                thinking_off_next = True
                log.info(
                    "accounting_reasoning.empty_answer_retry",
                    round=rounds_used,
                    elapsed_ms=int((time.monotonic() - round_started) * 1000),
                )
                continue
            log.info("accounting_reasoning.failed", reason="unparseable_response")
            return ReasoningOutcome(
                status=UNSUPPORTED,
                provider_failed=True,
                provider_attempted=True,
                evidence_results=gathered,
                rounds=rounds_used,
                failure_reason="empty_answer",
            )

        outcome = _outcome_from_parsed(parsed, rounds=rounds_used)
        outcome.evidence_results = list(gathered)

        # STAGE 2: two-call observation (flag-gated, diagnostic only — the
        # payload is forwarded to the audit hook and nothing is read back).
        _observe_two_call(
            parsed,
            round_index=rounds_used,
            elapsed_ms=int((time.monotonic() - round_started) * 1000),
            notify=_notify,
        )

        # (a) The model wants the books before deciding.
        if outcome.status == NEEDS_EVIDENCE:
            valid: List[EvidenceRequest] = []
            for request in outcome.evidence_requests:
                problem = validate_evidence_request(request)
                if problem:
                    rejected.append(problem)
                else:
                    valid.append(request)
            outcome.rejected_evidence = list(rejected)
            if not valid:
                # Every request was refused — tell the model exactly why and let
                # it choose again rather than silently substituting a lookup.
                violations = list(rejected) or [
                    "No usable evidence request was provided."
                ]
                continue
            _notify(
                "EVIDENCE_REQUESTED",
                {"round": rounds_used, "kinds": [r.kind for r in valid]},
            )
            # P0-③ (forensic report): cross-round dedupe.  No mutation can
            # run INSIDE this loop, so (kind, args) names one immutable
            # snapshot of the books for the whole request — a repeat request
            # is served from this request's own fetch: no duplicate database
            # read and no duplicate rows re-rendered into later prompts
            # (production 3ea794a0 re-fetched bank_accounts in round 3).
            # Results carrying an error are NOT cached, so a transient loader
            # failure or a permission denial can be retried next round.
            misses: List[EvidenceRequest] = []
            cached_kinds: List[str] = []
            staged: set = set()
            for request in valid:
                key = _evidence_cache_key(request)
                if key in evidence_cache or key in staged:
                    cached_kinds.append(request.kind)
                else:
                    staged.add(key)
                    misses.append(request)
            fetched: List[EvidenceResult] = []
            prefetched_kinds: List[str] = []
            # P1-⑩: harvest the speculative pool FIRST (started before the
            # round-1 model call), then fetch only what is still missing.
            if prefetch_task is not None:
                try:
                    prefetch_results = await prefetch_task
                except Exception:  # noqa: BLE001 — prefetch is best-effort
                    prefetch_results = []
                prefetch_task = None
                for req0, res0 in zip(prefetch_requests, prefetch_results or []):
                    # P1-⑤ keying: prefetch uses default args ({}).
                    res0.args = dict(req0.args or {})
                    if res0.error is None:
                        prefetch_pool[_evidence_cache_key(req0)] = res0
            if prefetch_pool and misses:
                still_missing: List[EvidenceRequest] = []
                for request in misses:
                    hit = prefetch_pool.pop(_evidence_cache_key(request), None)
                    if hit is not None:
                        evidence_cache[_evidence_cache_key(request)] = hit
                        fetched.append(hit)
                        prefetched_kinds.append(request.kind)
                    else:
                        still_missing.append(request)
                misses = still_missing
            if misses:
                fresh = await gather_evidence(
                    misses,
                    organization_id=organization_id,
                    auth=auth,
                    session_id=session_id,
                )
                for req, res in zip(misses, fresh):
                    # P1-⑤: remember WHICH args this snapshot answered so
                    # the cross-turn memo reuses the same (kind, args) key.
                    res.args = dict(req.args or {})
                    if res.error is None:
                        evidence_cache[_evidence_cache_key(req)] = res
                fetched.extend(fresh)
            gathered.extend(fetched)
            evidence_block = render_evidence(gathered)
            if cached_kinds:
                evidence_block += (
                    "\n  · NOTE: "
                    + ", ".join(sorted(set(cached_kinds)))
                    + " served from THIS request's own fetch — no new "
                    "database read (the books cannot change while reasoning "
                    "is in progress)."
                )
            if prefetched_kinds:
                evidence_block += (
                    "\n  · NOTE: "
                    + ", ".join(sorted(set(prefetched_kinds)))
                    + " prefetched in parallel with this round's model call "
                    "(speculative read-only lookup)."
                )
            # AUDIT_REPORT §7: the per-round cap must never make a requested
            # lookup disappear silently — name what was deferred so the model
            # can re-ask explicitly (the cap itself is unchanged).
            deferred_kinds = deferred_evidence_requests(
                parsed.get("evidence_requests")
            )
            if deferred_kinds:
                evidence_block += (
                    "\n  · NOTE: "
                    + ", ".join(sorted(set(deferred_kinds)))
                    + " requested BEYOND this round's evidence cap and were "
                    "DEFERRED, not fetched — re-request them explicitly if you "
                    "still need them."
                )
            _notify(
                "EVIDENCE_RETURNED",
                {
                    "round": rounds_used,
                    "summary": render_evidence_compact(fetched),
                    "label": EVIDENCE_LABEL,
                    # P0-③ observability: loader invocations vs requested
                    # kinds — the report's dedupe metric, durable per run.
                    "requested_kinds": [r.kind for r in valid],
                    "fetched_kinds": [r.kind for r in misses],
                    "cached_kinds": cached_kinds,
                    # P1-⑩ observability: served from the speculative pool.
                    "prefetched_kinds": prefetched_kinds,
                },
            )
            violations = []
            continue

        # (b) Python enforces the decision before it is used.
        violations = validate_outcome(
            outcome,
            offered_tools=offered_tools,
            forbidden_tools=forbidden_tools,
            tool_contracts=tool_contracts,
        )
        if violations:
            _notify(
                "DECISION_REJECTED",
                {
                    "round": rounds_used,
                    "status": outcome.status,
                    "violations": violations,
                },
            )
            outcome.violations = list(violations)
            if round_index + 1 < max_rounds:
                continue
            outcome.status = UNSUPPORTED
            outcome.evidence_results = list(gathered)
            return outcome

        # (c) Accepted decision.
        outcome.evidence_results = list(gathered)
        _notify(
            "REASONING_DECISION",
            {
                "round": rounds_used,
                "status": outcome.status,
                "understanding": outcome.understanding,
                "evidence": render_evidence_compact(gathered),
            },
        )
        return outcome

    # Round budget exhausted without an accepted decision.  This is a
    # TERMINAL outcome: there are no rounds left to satisfy a dangling
    # NEEDS_EVIDENCE, and falling off the end of the function would implicitly
    # return None, which crashes the caller with AttributeError: 'NoneType'
    # object has no attribute 'as_dict'.  Every reachable terminal path must return
    # a populated ReasoningOutcome.
    outcome.evidence_results = list(gathered)
    outcome.rounds = rounds_used
    if violations:
        outcome.violations = list(violations)
    outcome.status = UNSUPPORTED
    return outcome


# ---------------------------------------------------------------------------
# Preliminary extraction — LITERALS ONLY, never a final accounting decision
# ---------------------------------------------------------------------------


def preliminary_extraction(
    user_message: str,
    *,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract only obviously-literal values from the user's own words.

    This is the ONLY deterministic interpretation the architecture permits
    before the LLM sees the books.  Everything here is:

    * PRESERVED WORDING — the original request is carried verbatim;
    * LITERAL VALUES — an amount, a date, a named party, an item, a payment
      channel, a document reference, taken from the text itself;
    * CANDIDATE SUBJECT AREAS — hints that tell the model which areas of the
      books might be relevant.  They are explicitly NOT a workflow decision.

    The returned ``label`` is contractual: it is rendered into the reasoning
    prompt so the model knows this section is provisional and overridable.
    """
    from datetime import date as _date

    message = (user_message or "").strip()
    literals: Dict[str, Any] = {}
    subject_areas: List[str] = []
    provisional_intent: Optional[str] = None

    try:
        from app.planner import (
            _extract_amount,
            _extract_date,
            _extract_item,
            _extract_payment_method,
            _identify_intent,
        )

        msg_lower = message.lower()
        amount = _extract_amount(message)
        if amount is not None:
            literals["amount"] = amount
        txn_date = _extract_date(message, msg_lower)
        if txn_date:
            literals["transaction_date"] = txn_date
        item = _extract_item(message)
        if item:
            literals["item_description"] = item
        channel = _extract_payment_method(msg_lower)
        if channel:
            literals["payment_channel"] = channel
        provisional_intent = _identify_intent(msg_lower)
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        log.info("accounting_reasoning.preliminary_helpers_unavailable", error=str(exc)[:120])

    # Named parties are reported as CANDIDATES for the model's own lookup, not
    # as a resolved party: the model must confirm them against the books.
    candidates: List[str] = []
    try:
        from app.semantic_context import extract_candidate_terms

        candidates = extract_candidate_terms(message)[:5]
    except Exception as exc:  # noqa: BLE001
        log.info("accounting_reasoning.candidate_terms_unavailable", error=str(exc)[:120])
    if candidates:
        literals["named_parties_or_items_candidates"] = candidates

    reference = None
    invoice_number = None
    for token in re.findall(
        r"\b(?:INV|BILL|PUR|CRN|RET|RCPT|PAY|PO|JV)[-/\s]?\d{2,}\b",
        message,
        re.I,
    ):
        reference = token.strip()
        # Only an INV-prefixed token IS an invoice number; the other document
        # kinds keep document_reference alone (a bill ref is never seeded as
        # an invoice number).
        if reference.upper().startswith("INV"):
            invoice_number = reference
        break
    if not reference:
        # Loose human phrasing — "invoice no.12" / "invoice number 12" /
        # "invoice #7". Capture the number as the user's own literal
        # (labelled PRELIMINARY): the LLM planning stage receives it alongside
        # the verbatim message and the books, and can reason to the REAL
        # invoice ("no.12" -> INV-000011); approval-time exact-match
        # resolution validates whatever number is finally proposed — Python
        # never guesses a canonical form.  Strict form required (the
        # no./number/# qualifier) so "invoice for 50000" is never a reference.
        loose = re.search(
            r"\binvoice\s+(?:(?:no\.?|number|#)\s*[-#:]?\s*|#\s*)(\d{1,6})\b",
            message,
            re.I,
        )
        if not loose:
            loose = re.search(
                r"\binvoice\s+(\d{1,6})\b",
                message,
                re.I,
            )
        if loose:
            reference = loose.group(1)
            invoice_number = reference
        loose_bill = re.search(
            r"\b(?:bill|purchase\s*bill|po|pur)\s+(?:(?:no\.?|number|#)\s*[-#:]?\s*|#\s*)([A-Za-z0-9_-]+)\b",
            message,
            re.I,
        )
        if not loose_bill:
            loose_bill = re.search(
                r"\b(?:bill|purchase\s*bill|po|pur)\s+(\d{1,6})\b",
                message,
                re.I,
            )
        if loose_bill:
            reference = loose_bill.group(1)
            literals["bill_number"] = reference
    if reference:
        literals["document_reference"] = reference
    if invoice_number:
        literals["invoice_number"] = invoice_number
    # PUR-prefixed references ARE purchase-bill numbers (2026-10-19: the
    # debit-note lane must carry bill_number so the return links to its
    # source bill — "against purchase bill PUR-000013" extracted NOTHING).
    if reference and (reference.upper().startswith(("PUR", "BILL")) or "bill_number" in literals):
        literals["bill_number"] = literals.get("bill_number") or reference
    # "with reason <text>" — the user's OWN words for the return documents
    # (2026-10-19: both return tools REQUIRE a reason; neither the planner
    # nor the semantic stage reliably carried it — the DN execution died
    # with 'Purchase return requires a reason.').
    reason_m = re.search(
        r"\b(?:with\s+)?reason\s+(?:of\s+|:\s*)?([^\.,;!?]+)",
        message,
        re.I,
    )
    if reason_m:
        candidate = reason_m.group(1).strip()
        if 3 <= len(candidate) <= 120:
            literals["reason"] = candidate

    # Candidate subject areas — HINTS ONLY.  They tell the model where to look
    # first; they never decide the treatment, the workflow, or the accounts.
    for token, area in (
        ("asset", "fixed_assets"),
        ("depreciat", "fixed_assets"),
        ("sold", "revenue"),
        ("sale", "revenue"),
        ("supplied", "revenue"),
        ("invoice", "receivables"),
        ("receipt", "receivables"),
        ("received", "receivables"),
        ("paid", "payables"),
        ("payment", "payables"),
        ("bill", "payables"),
        ("expense", "expenses"),
        ("bought", "purchases"),
        ("purchase", "purchases"),
        ("loan", "loans"),
        ("capital", "equity"),
        ("drawing", "equity"),
        ("tax", "tax"),
        ("bank", "bank"),
        ("cash", "cash"),
    ):
        if token in message.lower() and area not in subject_areas:
            subject_areas.append(area)

    return {
        "label": _PRELIMINARY_LABEL,
        "original_request": message,
        "literals": literals,
        "candidate_subject_areas": subject_areas,
        "provisional_intent_hint": provisional_intent,
        "note": (
            "Provisional only. The accounting treatment must be determined by "
            "reading the live books — correct any of this that the records "
            "contradict."
        ),
        "today": today or _date.today().isoformat(),
    }