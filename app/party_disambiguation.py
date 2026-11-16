"""Party Role & Relationship Disambiguator (Forensic Evidentiary Audit).

Implements the 5-Stage Evidentiary Audit and Money-Flow Vector Evaluation:
    Role = Ψ(PartyName, MoneyDirection, OpenReceivables, OpenPayables, Employees, OrgOfficers)

Specification Reference:
    - docs/ACCOUNTING_SPECIFICATION_LLM_REASONING.md §4 (Party Role & Relationship Disambiguation)
    - IAS 32.42 Offsetting Prohibition (Dual-Role Counterparties)
    - Section 153 & Section 149 Income Tax Ordinance, 2001 (Statutory Withholding Rules)

Core Invariants:
1. Evidentiary Audit Hierarchy (Money OUT):
   - Stage 1: Matches open purchase bill / Accounts Payable -> supplier (settlement u/s 153).
   - Stage 2: Matches active payroll roster -> employee (salary / advance u/s 149 / IAS 19).
   - Stage 3: Matches equity / officers / partners -> owner (drawings / director loan).
   - Stage 4: Matches open receivables -> customer (advance refund).
   - Stage 5: Genuinely ambiguous or novel party -> requires_clarification = True with smart options.
2. Evidentiary Audit Hierarchy (Money IN):
   - Stage 1: Matches open sales invoice / Accounts Receivable -> customer (trade collection IFRS 9).
   - Stage 2: Matches equity / officers / partners -> owner (capital injection / director loan).
   - Stage 3: Matches open payables -> supplier (supplier refund / rebate).
   - Stage 4: Matches employee roster -> employee (advance recovery).
   - Stage 5: Genuinely ambiguous or novel party -> requires_clarification = True with smart options.
3. IAS 32 Dual-Role Counterparty Segregation:
   - Receivables (1110) and Payables (2010) must NEVER be silently netted.
   - Money OUT settles the supplier role; Money IN settles the customer role.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import structlog

from app.name_matching import name_key, normalized_matches

log = structlog.get_logger(__name__)

# Statutory WHT and Standard rules
WHT_SUPPLIER_RULE = "Deduct Section 153 WHT (Goods 5%/5.5%, Services 14%/15%, IT 4%)"
WHT_EMPLOYEE_RULE = "Subject to Section 149 Progressive Monthly Slabs"
WHT_OWNER_DRAWINGS_RULE = "No WHT on drawings u/s 3200; Dividends subject to Section 150 (15%)"
WHT_OWNER_CAPITAL_RULE = "Capital injection / Director loan (No WHT deduction on equity inflow)"
WHT_CUSTOMER_REFUND_RULE = "No WHT deduction on customer refunds"
WHT_CUSTOMER_COLLECTION_RULE = "Subject to customer deduction at source under S. 153 if prescribed withholding agent"


@dataclass
class PartyRoleResult:
    """Forensic result of party role and relationship disambiguation."""

    party_name: str
    role: str  # "supplier" | "customer" | "employee" | "owner" | "unknown"
    confidence: float  # 0.0 to 1.0
    requires_clarification: bool  # True iff confidence < 0.65 or role == "unknown"
    clarification_options: List[str] = field(default_factory=list)
    clarification_question: Optional[str] = None
    matched_record: Optional[Dict[str, Any]] = None
    account_head: Optional[str] = None
    statutory_wht_rule: Optional[str] = None
    standard_reference: Optional[str] = None
    reasoning: str = ""
    decision_source: str = "deterministic_hierarchy"  # deterministic_hierarchy | llm

    def to_dict(self) -> Dict[str, Any]:
        return {
            "party_name": self.party_name,
            "role": self.role,
            "confidence": round(self.confidence, 4),
            "requires_clarification": self.requires_clarification,
            "clarification_options": self.clarification_options,
            "clarification_question": self.clarification_question,
            "matched_record": self.matched_record,
            "account_head": self.account_head,
            "statutory_wht_rule": self.statutory_wht_rule,
            "standard_reference": self.standard_reference,
            "reasoning": self.reasoning,
            "decision_source": self.decision_source,
        }


def _normalize_direction(direction: str) -> str:
    """Normalize money-flow direction to 'OUT' or 'IN'."""
    d = str(direction or "").strip().upper()
    if d in ("OUT", "OUTFLOW", "PAYMENT", "PAID", "DISBURSEMENT", "EXPENSE", "DEBIT"):
        return "OUT"
    if d in ("IN", "INFLOW", "RECEIPT", "RECEIVED", "COLLECTION", "INCOME", "CREDIT"):
        return "IN"
    return "OUT" if "OUT" in d else ("IN" if "IN" in d else "OUT")


def _find_matches_in_records(
    needle: str,
    records: List[Dict[str, Any]],
    candidate_fields: List[str],
) -> List[Dict[str, Any]]:
    """Match needle against records using separator-insensitive name_key."""
    if not needle or not records:
        return []
    q_key = name_key(needle)
    if not q_key:
        return []

    # 1. Exact name_key match
    exact_matches: List[Dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        for field_name in candidate_fields:
            val = r.get(field_name)
            if val and name_key(val) == q_key:
                exact_matches.append(r)
                break
    if exact_matches:
        return exact_matches

    # 2. Normalized ranked matches fallback
    for field_name in candidate_fields:
        hits = normalized_matches(records, needle, field=field_name, min_key_length=3)
        if hits:
            return hits

    return []


def _disambiguate_party_deterministic(
    party_name: str,
    norm_direction: str,
    open_receivables: List[Dict[str, Any]],
    open_payables: List[Dict[str, Any]],
    employees: List[Dict[str, Any]],
    org_officers: List[Dict[str, Any]],
) -> PartyRoleResult:
    """Evaluate party relationship using the 5-stage skeptical hierarchy."""
    clean_name = str(party_name or "").strip()
    if not clean_name:
        return PartyRoleResult(
            party_name="",
            role="unknown",
            confidence=0.0,
            requires_clarification=True,
            clarification_question="Party or counterparty name is missing. Please specify who the transaction is with.",
            clarification_options=[
                "Supplier / Vendor (trade purchase or bill payment)",
                "Employee (payroll salary, advance, or reimbursement)",
                "Owner / Director (drawings or capital contribution)",
                "Customer (sales invoice collection or advance)",
            ],
            reasoning="Cannot evaluate party role without an entity or counterparty name.",
            decision_source="deterministic_hierarchy",
        )

    # Search in all 4 evidence registers
    matched_payables = _find_matches_in_records(
        clean_name, open_payables, ["party_name", "supplier_name", "vendor_name", "name", "contact_name"]
    )
    matched_employees = _find_matches_in_records(
        clean_name, employees, ["full_name", "name", "employee_name", "employee_code"]
    )
    matched_officers = _find_matches_in_records(
        clean_name, org_officers, ["full_name", "name", "officer_name", "director_name", "partner_name", "owner_name"]
    )
    matched_receivables = _find_matches_in_records(
        clean_name, open_receivables, ["party_name", "customer_name", "client_name", "name"]
    )

    is_in_payables = bool(matched_payables)
    is_in_employees = bool(matched_employees)
    is_in_officers = bool(matched_officers)
    is_in_receivables = bool(matched_receivables)

    # Dual-Role check: Counterparty has active open records in BOTH AP and AR (e.g. Alpha Logistics)
    is_dual_role = is_in_payables and is_in_receivables

    # Conflict check: Registered as both employee and officer/director
    is_employee_officer_conflict = is_in_employees and is_in_officers and not is_in_payables and not is_in_receivables

    # -------------------------------------------------------------------------
    # CASE 1: MONEY OUT (Disbursements, Payments, Settlements)
    # -------------------------------------------------------------------------
    if norm_direction == "OUT":
        # Conflict: Employee and Officer without explicit indicator
        if is_employee_officer_conflict:
            return PartyRoleResult(
                party_name=clean_name,
                role="unknown",
                confidence=0.50,  # Ambiguous between payroll and equity drawing
                requires_clarification=True,
                clarification_question=(
                    f"'{clean_name}' is registered as both an Employee and an Officer/Owner. "
                    "Is this payment employee payroll salary (IAS 19) or owner drawings (IAS 1)?"
                ),
                clarification_options=[
                    "Employee (monthly salary, allowance, or travel reimbursement)",
                    "Owner / Director (personal drawings or distribution from profits)",
                    "Director Loan Repayment (company repaying loan to director)",
                ],
                matched_record=matched_employees[0],
                account_head="2150 Salaries Payable / 3200 Drawings",
                statutory_wht_rule="Subject to verification: S. 149 if salary, S. 150 if dividend",
                standard_reference="IAS 19 / IAS 1",
                reasoning=(
                    f"Party '{clean_name}' holds dual internal status as both an employee and an officer/owner. "
                    "Forensic auditing requires explicit user confirmation to avoid misclassifying drawings as deductible payroll expenses."
                ),
                decision_source="deterministic_hierarchy",
            )

        # Stage 1: Open Payable (Trade Supplier)
        if is_in_payables:
            dual_note = (
                " Note: Counterparty also has customer receivables, but under IAS 32.42 offsetting prohibition, "
                "money OUT settles Accounts Payable (2010) independently without silent contra netting."
                if is_dual_role else ""
            )
            return PartyRoleResult(
                party_name=clean_name,
                role="supplier",
                confidence=0.95,
                requires_clarification=False,
                clarification_options=[],
                clarification_question=None,
                matched_record=matched_payables[0],
                account_head="2010 Accounts Payable / Trade Creditors",
                statutory_wht_rule=WHT_SUPPLIER_RULE,
                standard_reference="IFRS 9 Financial Instruments",
                reasoning=(
                    f"Party '{clean_name}' matches open payable bills. Outflow represents settlement of trade liability "
                    f"(DR 2010 Accounts Payable, CR 1020 Bank).{dual_note}"
                ),
                decision_source="deterministic_hierarchy",
            )

        # Stage 2: Active Employee Roster
        if is_in_employees:
            return PartyRoleResult(
                party_name=clean_name,
                role="employee",
                confidence=0.92,
                requires_clarification=False,
                clarification_options=[],
                clarification_question=None,
                matched_record=matched_employees[0],
                account_head="2150 Salaries & Wages Payable",
                statutory_wht_rule=WHT_EMPLOYEE_RULE,
                standard_reference="IAS 19 Employee Benefits",
                reasoning=(
                    f"Party '{clean_name}' matches active employee roster. Outflow represents salary payment, "
                    "payroll advance, or staff reimbursement (DR 2150 Salaries Payable / DR 1450 Salary Advance, CR 1020 Bank)."
                ),
                decision_source="deterministic_hierarchy",
            )

        # Stage 3: Equity / Officers / Partners
        if is_in_officers:
            return PartyRoleResult(
                party_name=clean_name,
                role="owner",
                confidence=0.90,
                requires_clarification=False,
                clarification_options=[],
                clarification_question=None,
                matched_record=matched_officers[0],
                account_head="3200 Owner's Drawings / Distributions",
                statutory_wht_rule=WHT_OWNER_DRAWINGS_RULE,
                standard_reference="IAS 1 Presentation of Financial Statements / Equity",
                reasoning=(
                    f"Party '{clean_name}' matches registered company officer/owner/partner. Outflow represents "
                    "owner drawings or director loan withdrawal (DR 3200 Owner Drawings / DR 2200 Director Loan, CR 1020 Bank)."
                ),
                decision_source="deterministic_hierarchy",
            )

        # Stage 4: Open Receivables (Customer Refund)
        if is_in_receivables:
            return PartyRoleResult(
                party_name=clean_name,
                role="customer",
                confidence=0.85,
                requires_clarification=False,
                clarification_options=[],
                clarification_question=None,
                matched_record=matched_receivables[0],
                account_head="2190 Customer Advance Refund",
                statutory_wht_rule=WHT_CUSTOMER_REFUND_RULE,
                standard_reference="IFRS 15 / IFRS 9",
                reasoning=(
                    f"Party '{clean_name}' matches registered trade customer with money OUT. Interpreted as refund "
                    "of customer overpayment, security deposit, or advance (DR 2190 Customer Refund, CR 1020 Bank)."
                ),
                decision_source="deterministic_hierarchy",
            )

        # Stage 5: Genuinely Ambiguous or Novel Party with Zero History
        return PartyRoleResult(
            party_name=clean_name,
            role="unknown",
            confidence=0.30,  # < 0.65 triggers clarification
            requires_clarification=True,
            clarification_question=(
                f"Who is '{clean_name}' and what is the accounting nature of this outgoing payment?"
            ),
            clarification_options=[
                "Trade Supplier / Vendor (settlement of purchase bill or goods/services)",
                "Employee (salary payment, expense reimbursement, or payroll advance)",
                "Owner / Director (proprietor drawings or director loan)",
                "Customer (refund of customer advance or overpayment)",
                "Other business expenditure / operating expense",
            ],
            matched_record=None,
            account_head=None,
            statutory_wht_rule="To be determined upon role resolution",
            standard_reference="IAS 1 / IFRS 9",
            reasoning=(
                f"Naked party name '{clean_name}' has zero matching records in open payables, employee roster, "
                "officer register, or customer receivables. Mandatory clarification required under skeptical accounting rules."
            ),
            decision_source="deterministic_hierarchy",
        )

    # -------------------------------------------------------------------------
    # CASE 2: MONEY IN (Collections, Receipts, Inflows)
    # -------------------------------------------------------------------------
    # Stage 1: Open Receivables (Trade Customer)
    if is_in_receivables:
        dual_note = (
            " Note: Counterparty also has supplier payables, but under IAS 32.42 offsetting prohibition, "
            "money IN settles Accounts Receivable (1110) independently without silent contra netting."
            if is_dual_role else ""
        )
        return PartyRoleResult(
            party_name=clean_name,
            role="customer",
            confidence=0.95,
            requires_clarification=False,
            clarification_options=[],
            clarification_question=None,
            matched_record=matched_receivables[0],
            account_head="1110 Accounts Receivable / Trade Debtors",
            statutory_wht_rule=WHT_CUSTOMER_COLLECTION_RULE,
            standard_reference="IFRS 9 Financial Instruments",
            reasoning=(
                f"Party '{clean_name}' matches open customer sales invoices. Inflow represents trade debt collection "
                f"(DR 1020 Bank, CR 1110 Accounts Receivable).{dual_note}"
            ),
            decision_source="deterministic_hierarchy",
        )

    # Stage 2: Equity / Officers / Partners (Capital Injection)
    if is_in_officers:
        return PartyRoleResult(
            party_name=clean_name,
            role="owner",
            confidence=0.90,
            requires_clarification=False,
            clarification_options=[],
            clarification_question=None,
            matched_record=matched_officers[0],
            account_head="3010 Share Capital / Partner's Capital Account",
            statutory_wht_rule=WHT_OWNER_CAPITAL_RULE,
            standard_reference="IAS 1 Presentation of Financial Statements / Equity",
            reasoning=(
                f"Party '{clean_name}' matches company officer/owner/partner with incoming funds. Represents capital "
                "injection or director loan contribution to enterprise (DR 1020 Bank, CR 3010 Share Capital / 2200 Director Loan)."
            ),
            decision_source="deterministic_hierarchy",
        )

    # Stage 3: Open Payables (Supplier Refund / Credit)
    if is_in_payables:
        return PartyRoleResult(
            party_name=clean_name,
            role="supplier",
            confidence=0.85,
            requires_clarification=False,
            clarification_options=[],
            clarification_question=None,
            matched_record=matched_payables[0],
            account_head="2010 Accounts Payable / Supplier Credit",
            statutory_wht_rule="Supplier refund / credit adjustment",
            standard_reference="IAS 2 / IFRS 9",
            reasoning=(
                f"Party '{clean_name}' matches registered trade supplier with incoming payment. Inflow represents "
                "supplier refund, volume rebate, or credit return (DR 1020 Bank, CR 2010 Accounts Payable)."
            ),
            decision_source="deterministic_hierarchy",
        )

    # Stage 4: Employee Advance Recovery
    if is_in_employees:
        return PartyRoleResult(
            party_name=clean_name,
            role="employee",
            confidence=0.85,
            requires_clarification=False,
            clarification_options=[],
            clarification_question=None,
            matched_record=matched_employees[0],
            account_head="1450 Employee Salary Advance",
            statutory_wht_rule="Recovery of payroll advance / employee loan",
            standard_reference="IAS 19 Employee Benefits",
            reasoning=(
                f"Party '{clean_name}' matches active employee with incoming funds. Inflow represents recovery "
                "of payroll advance or return of unspent expense imprest (DR 1020 Bank, CR 1450 Salary Advance)."
            ),
            decision_source="deterministic_hierarchy",
        )

    # Stage 5: Genuinely Ambiguous or Novel Party with Zero History
    return PartyRoleResult(
        party_name=clean_name,
        role="unknown",
        confidence=0.30,  # < 0.65 triggers clarification
        requires_clarification=True,
        clarification_question=(
            f"Who is '{clean_name}' and what is the source/nature of this incoming payment?"
        ),
        clarification_options=[
            "Customer (collection for sales invoice or customer advance)",
            "Owner / Director (equity capital injection or director loan to company)",
            "Supplier (refund, volume rebate, or credit note payment)",
            "Other income / non-operating receipt",
        ],
        matched_record=None,
        account_head=None,
        statutory_wht_rule="To be determined upon role resolution",
        standard_reference="IFRS 9 / IFRS 15",
        reasoning=(
            f"Counterparty '{clean_name}' has zero matching records in receivables, payables, employees, "
            "or officer registers. Mandatory clarification required under skeptical accounting rules."
        ),
        decision_source="deterministic_hierarchy",
    )


async def disambiguate_party_role(
    party_name: str,
    money_direction: str,
    open_receivables: List[Dict[str, Any]],
    open_payables: List[Dict[str, Any]],
    employees: List[Dict[str, Any]],
    org_officers: List[Dict[str, Any]],
    *,
    client: Any = None,
    timeout: Optional[float] = None,
) -> PartyRoleResult:
    """Disambiguate party role using the 5-Stage Skeptical Evidentiary Hierarchy.

    Evaluates the money-flow vector:
        - Money OUT + open payable -> supplier (settlement u/s 153).
        - Money OUT + employee roster -> employee (salary / advance u/s 149).
        - Money OUT + owner/director -> owner (drawings / loan).
        - Money IN + open receivable -> customer (trade collection IFRS 9).
        - Dual-role (AR and AP) -> respect IAS 32 offsetting prohibition.
        - Genuinely ambiguous / zero history -> requires_clarification = True with smart options.

    Args:
        party_name: Name of the party or counterparty.
        money_direction: Flow of money ('OUT'/'OUTFLOW' or 'IN'/'INFLOW').
        open_receivables: List of open customer receivables / invoices.
        open_payables: List of open vendor payables / bills.
        employees: List of registered active employees.
        org_officers: List of registered officers, owners, directors, partners.
        client: Optional LLM client (if LLM-assisted disambiguation is enabled).
        timeout: Timeout in seconds for LLM call before falling back.

    Returns:
        PartyRoleResult with grounded role, confidence, account head, and statutory rules.
    """
    clean_name = str(party_name or "").strip()
    norm_direction = _normalize_direction(money_direction)

    from app.config import get_settings

    settings = get_settings()
    llm_enabled = getattr(settings, "llm_party_disambiguation_enabled", False)

    if not llm_enabled or not clean_name:
        return _disambiguate_party_deterministic(
            party_name=clean_name,
            norm_direction=norm_direction,
            open_receivables=open_receivables,
            open_payables=open_payables,
            employees=employees,
            org_officers=org_officers,
        )

    # If LLM enabled, execute with fail-safe degradation
    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()

        prompt = (
            "YOU ARE THE FORENSIC ACCOUNTING AUDITOR & FINANCIAL CONTROLLER.\n"
            "Disambiguate the role of the party for this transaction using live ledger evidence.\n\n"
            f"PARTY NAME: {clean_name}\n"
            f"MONEY DIRECTION: {norm_direction}\n"
            f"OPEN RECEIVABLES (Customers): {len(open_receivables)} records\n"
            f"OPEN PAYABLES (Suppliers): {len(open_payables)} records\n"
            f"ACTIVE EMPLOYEES: {len(employees)} records\n"
            f"ORG OFFICERS / OWNERS: {len(org_officers)} records\n\n"
            "RULES:\n"
            "1. Money OUT + matches open payable -> supplier.\n"
            "2. Money OUT + matches employee roster -> employee.\n"
            "3. Money OUT + matches owner/director -> owner.\n"
            "4. Money IN + matches open receivable -> customer.\n"
            "5. If party has zero history across all registers -> requires_clarification=true (confidence < 0.65).\n"
            "6. Respect IAS 32 offsetting prohibition: do not net AR and AP.\n\n"
            "Reply with STRICT JSON ONLY matching:\n"
            "{\n"
            '  "role": "supplier|customer|employee|owner|unknown",\n'
            '  "confidence": <float 0.0 to 1.0>,\n'
            '  "requires_clarification": <true|false>,\n'
            '  "clarification_question": "<question or null>",\n'
            '  "clarification_options": ["option1", "option2"],\n'
            '  "account_head": "<ledger code and name>",\n'
            '  "statutory_wht_rule": "<applicable tax withholding rule>",\n'
            '  "standard_reference": "<accounting standard>",\n'
            '  "reasoning": "<forensic reasoning narrative>"\n'
            "}"
        )

        call_timeout = timeout or getattr(settings, "llm_party_disambiguation_timeout", 8.0)
        raw_reply = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt),
            timeout=call_timeout,
        )

        match = re.search(r"\{.*\}", str(raw_reply or ""), re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            role = str(parsed.get("role") or "unknown").strip().lower()
            confidence = float(parsed.get("confidence") or 0.5)
            req_clarify = bool(parsed.get("requires_clarification"))
            if confidence >= 0.65:
                req_clarify = False
            elif confidence < 0.65:
                req_clarify = True

            matched_rec = None
            if role == "supplier" and open_payables:
                matches = _find_matches_in_records(clean_name, open_payables, ["party_name", "supplier_name", "vendor_name", "name", "contact_name"])
                matched_rec = matches[0] if matches else None
            elif role == "customer" and open_receivables:
                matches = _find_matches_in_records(clean_name, open_receivables, ["party_name", "customer_name", "client_name", "name"])
                matched_rec = matches[0] if matches else None
            elif role == "employee" and employees:
                matches = _find_matches_in_records(clean_name, employees, ["full_name", "name", "employee_name", "employee_code"])
                matched_rec = matches[0] if matches else None
            elif role == "owner" and org_officers:
                matches = _find_matches_in_records(clean_name, org_officers, ["full_name", "name", "officer_name", "director_name", "partner_name", "owner_name"])
                matched_rec = matches[0] if matches else None

            return PartyRoleResult(
                party_name=clean_name,
                role=role,
                confidence=confidence,
                requires_clarification=req_clarify,
                clarification_options=parsed.get("clarification_options") or [],
                clarification_question=parsed.get("clarification_question"),
                matched_record=matched_rec,
                account_head=parsed.get("account_head"),
                statutory_wht_rule=parsed.get("statutory_wht_rule"),
                standard_reference=parsed.get("standard_reference"),
                reasoning=str(parsed.get("reasoning") or "").strip(),
                decision_source="llm",
            )
    except Exception as exc:  # noqa: BLE001 — fail-safe degradation
        log.warning("party_disambiguation.llm_fallback", error=str(exc)[:160])

    return _disambiguate_party_deterministic(
        party_name=clean_name,
        norm_direction=norm_direction,
        open_receivables=open_receivables,
        open_payables=open_payables,
        employees=employees,
        org_officers=org_officers,
    )
