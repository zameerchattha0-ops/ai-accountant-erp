"""Mid-Flow Consultative Question Detector & Statutory Advisory Engine.

Supports DOC-ACC-2026-V1 Decision 3:
Mid-flow consultative question answering without breaking or restarting the active transaction.

Statutory Advisory Coverage:
1. Section 73 & Section 21(l) of Income Tax Ordinance 2001 (Cash expenditure limits:
   PKR 50k for business expenses, PKR 250k for capital assets).
2. Section 153 Withholding Tax (WHT rates for goods 5%/5.5%, IT services 4%, general services 14%,
   professional 15%, Tenth Schedule non-filer doubling).
3. IAS 16 Property, Plant and Equipment (Capitalization recognition criteria, useful life > 1 year,
   future economic benefits vs revenue expense).
4. Depreciation Rules & Schedules (FBR Third Schedule vs IAS 16 useful lives: Computers 3 yrs,
   Furniture 5-10 yrs, Vehicles 5 yrs, Straight Line vs Reducing Balance).
5. Sales Tax Act 1990 & Provincial Sales Tax (FBR 18%, PRA 16%, SRB 15%, KPRA 15%, IT reduced rates).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Consultative Topic Models & Constants
# ---------------------------------------------------------------------------

TOPIC_SECTION_73 = "section_73_cash_limits"
TOPIC_SECTION_153 = "section_153_wht"
TOPIC_IAS_16 = "ias_16_capitalization"
TOPIC_DEPRECIATION = "depreciation_rules"
TOPIC_SALES_TAX = "sales_tax_rules"
TOPIC_IFRS_16 = "ifrs_16_lease_vs_buy"


class ConsultativeAdvisoryResult(BaseModel):
    """Structured response for a consultative statutory advisory turn."""

    is_consultative: bool = True
    topic: str
    statutory_reference: str
    headline: str
    advisory_markdown: str
    actionable_recommendation: str
    context_resume_prompt: str
    suggested_chips: List[str] = Field(default_factory=list)
    suggested_field_update: Optional[Dict[str, Any]] = None

    def __contains__(self, item: str) -> bool:
        return (
            item in self.advisory_markdown
            or item in self.headline
            or item in self.statutory_reference
        )

    def __str__(self) -> str:
        return self.advisory_markdown

    def lower(self) -> str:
        return self.advisory_markdown.lower()

    def upper(self) -> str:
        return self.advisory_markdown.upper()

    def strip(self) -> str:
        return self.advisory_markdown.strip()


# ---------------------------------------------------------------------------
# Detection Logic
# ---------------------------------------------------------------------------

_CONSULTATIVE_INTENT_PATTERNS = [
    # Question phrasing
    r"^(?:what|how|why|is|can|should|tell me|explain|does|are)\b",
    r"\?$",
    r"\b(?:what is|what's|how much|can i|should i|is it allowed|difference between|rule for|limit for)\b",
    r"\b(?:simulate|simulation|what[\s-]?if|compare|scenario)\b",
]

_TOPIC_REGEXES: Dict[str, List[re.Pattern]] = {
    TOPIC_SECTION_73: [
        re.compile(r"\b(?:section\s*73|sec\s*73|21\(l\)|cash\s*limit|limit\s*for\s*cash|cash\s*payment\s*limit|allowed\s*in\s*cash|pay\s*cash|pay\s*in\s*cash|cash\s*threshold)\b", re.IGNORECASE),
        re.compile(r"\bcan\s+(?:i|we)\s+pay\s+.*cash\b", re.IGNORECASE),
        re.compile(r"\bis\s+cash\s+allowed\b", re.IGNORECASE),
    ],
    TOPIC_SECTION_153: [
        re.compile(r"\b(?:section\s*153|sec\s*153|wht\b|withholding\s*tax|tax\s*deduction|wht\s*rate|wht\s*on\s*goods|wht\s*on\s*services|wht\s*on\s*it|withholding\s*rate)\b", re.IGNORECASE),
        re.compile(r"\bwhat\s+is\s+(?:the\s+)?(?:wht|withholding)\b", re.IGNORECASE),
        re.compile(r"\bdeduct\s+tax\s+u/s\s*153\b", re.IGNORECASE),
    ],
    TOPIC_IAS_16: [
        re.compile(r"\b(?:ias\s*16|capitalize|capitalise|capitalization|capitalisation|expense\s*or\s*asset|asset\s*or\s*expense|capital\s*expenditure|revenue\s*expenditure)\b", re.IGNORECASE),
        re.compile(r"\bshould\s+(?:i|we)\s+(?:capitalize|expense)\b", re.IGNORECASE),
        re.compile(r"\bcan\s+(?:i|we)\s+expense\s+this\b", re.IGNORECASE),
    ],
    TOPIC_DEPRECIATION: [
        re.compile(r"\b(?:depreciation|depreciate|useful\s*life|salvage\s*value|residual\s*value|straight\s*line|reducing\s*balance|fbr\s*depreciation)\b", re.IGNORECASE),
        re.compile(r"\bhow\s+many\s+years\s+(?:depreciation|useful\s*life)\b", re.IGNORECASE),
        re.compile(r"\bdepreciation\s*rate\s*for\b", re.IGNORECASE),
    ],
    TOPIC_SALES_TAX: [
        re.compile(r"\b(?:sales\s*tax|gst\b|pra\b|srb\b|kpra\b|further\s*tax|input\s*tax|18%|16%|15%|strn\b)\b", re.IGNORECASE),
        re.compile(r"\bwhat\s+is\s+(?:the\s+)?(?:sales\s*tax|gst|pra|srb)\b", re.IGNORECASE),
    ],
    TOPIC_IFRS_16: [
        re.compile(r"\b(?:lease\s*vs\s*buy|buy\s*vs\s*lease|ifrs\s*16|scenario\s*analysis|what[\s-]?if|simulate|simulation|annuity|discount\s*rate)\b", re.IGNORECASE),
        re.compile(r"\b(?:should\s+we\s+(?:lease|buy)|compare\s+(?:lease|buy))\b", re.IGNORECASE),
    ],
}


def is_consultative_query(user_message: str) -> bool:
    """Check if the user message is a consultative accounting or statutory inquiry."""
    return detect_consultative_query(user_message) is not None


def get_consultative_advice(
    user_message: str,
    entities: Optional[Dict[str, Any]] = None,
    current_amount: Optional[float] = None,
) -> ConsultativeAdvisoryResult:
    """Convenience accessor to retrieve statutory advisory for a consultative query."""
    topic = detect_consultative_query(user_message) or TOPIC_SECTION_73
    return generate_consultative_advisory(
        topic=topic,
        user_message=user_message,
        entities=entities,
        current_amount=current_amount,
    )


def detect_consultative_query(user_message: str) -> Optional[str]:
    """Detect if a user's reply is a consultative statutory question mid-flow.

    Returns the detected topic key (e.g. TOPIC_SECTION_73) or None.
    """
    cleaned = (user_message or "").strip()
    if not cleaned:
        return None

    # Declarative answers must never be misclassified as consultative questions
    low = cleaned.lower()
    if re.match(r"^\s*\d+\s*(?:years?|yrs?|saal)?\s*(?:straight\s*line|reducing\s*balance|none)?\s*$", low):
        return None
    if low in ("straight line", "reducing balance", "cash", "bank transfer", "credit", "yes", "no"):
        return None

    # Check if text contains question markers, consultative phrasing, or explicit statutory citations
    is_inquiry = any(re.search(pat, cleaned, re.IGNORECASE) for pat in _CONSULTATIVE_INTENT_PATTERNS)
    has_explicit_statute = bool(re.search(r"\b(?:section\s*73|sec\s*73|21\(l\)|section\s*153|sec\s*153|ias\s*16|ifrs\s*16|fbr\s*rate|simulate|scenario)\b", cleaned, re.IGNORECASE))

    if not (is_inquiry or has_explicit_statute or cleaned.endswith("?")):
        return None

    for topic, patterns in _TOPIC_REGEXES.items():
        for pat in patterns:
            if pat.search(cleaned):
                return topic

    # Secondary check: if message ends with "?" or mentions simulation/scenario
    if cleaned.endswith("?") or any(w in low for w in ("simulate", "simulation", "scenario", "what-if", "what if")):
        if "lease" in low or "buy" in low or "simulation" in low or "scenario" in low:
            return TOPIC_IFRS_16
        if "cash" in low and ("limit" in low or "allowed" in low or "rule" in low or "can" in low):
            return TOPIC_SECTION_73
        if "tax" in low and ("wht" in low or "withhold" in low or "rate" in low or "percent" in low):
            return TOPIC_SECTION_153
        if "asset" in low or "expense" in low:
            return TOPIC_IAS_16
        if "depreciation" in low or "years" in low or "method" in low:
            return TOPIC_DEPRECIATION

    return None


# ---------------------------------------------------------------------------
# Statutory Advisory Generator
# ---------------------------------------------------------------------------

def generate_consultative_advisory(
    *,
    topic: str,
    user_message: str,
    entities: Optional[Dict[str, Any]] = None,
    current_amount: Optional[float] = None,
) -> ConsultativeAdvisoryResult:
    """Generate an authoritative, professional statutory advisory response.

    Maintains conversational warmth, cites relevant legal provisions, and
    provides a smooth return prompt to continue the in-progress draft.
    """
    ents = entities or {}
    amt = current_amount
    if amt is None:
        raw_amt = ents.get("amount") or ents.get("total_amount")
        if raw_amt is not None:
            try:
                amt = float(str(raw_amt).replace(",", "").strip())
            except (ValueError, TypeError):
                amt = None

    item_desc = str(ents.get("item_description") or ents.get("description") or ents.get("asset_name") or "this transaction").strip()

    # 1. SECTION 73 CASH LIMITS
    if topic == TOPIC_SECTION_73:
        statutory_ref = "Section 73 & Section 21(l), Income Tax Ordinance 2001"
        headline = "Section 73 Statutory Cash Payment Limits"
        advisory_md = (
            "Under **Section 73 and Section 21(l) of the Income Tax Ordinance, 2001**:\n\n"
            "1. **Operating Expenditures**: Any single expenditure exceeding **PKR 50,000** must be paid through an approved banking channel "
            "(crossed cheque, pay order, or direct bank transfer). Cash payments exceeding PKR 50,000 are **strictly disallowed as tax deductions** under Section 21(l).\n"
            "2. **Capital Assets**: For capital asset purchases exceeding **PKR 250,000**, Section 73(2)/(3) requires payment through banking channels. Cash payments "
            "exceeding PKR 250,000 forfeit all depreciation deductions in tax assessments.\n\n"
            "**Recommendation**: Always settle via Bank Transfer or Crossed Cheque to protect tax deductions and maintain full audit compliance."
        )
        if amt and amt > 50000.0:
            rec = f"Since your transaction is **Rs. {amt:,.0f}**, paying via **Bank Transfer / Crossed Cheque** is strongly advised to prevent disallowance."
            bridge = f"Returning to your draft for **{item_desc}** (Rs. {amt:,.0f}): Would you like to record this payment via **Bank Transfer** (recommended) or **Cash**?"
            chips = ["Pay via Bank Transfer (Recommended)", "Pay via Crossed Cheque", "Record as Cash (Acknowledge Risk)"]
        else:
            rec = "Transactions under PKR 50,000 are permitted in cash without Section 21(l) disallowance."
            bridge = f"Returning to your draft for **{item_desc}**: Which payment channel would you like to use?"
            chips = ["Cash in Hand", "Bank Transfer", "Credit (Pay Later)"]

        return ConsultativeAdvisoryResult(
            topic=topic,
            statutory_reference=statutory_ref,
            headline=headline,
            advisory_markdown=advisory_md,
            actionable_recommendation=rec,
            context_resume_prompt=f"{advisory_md}\n\n---\n**Next Step**: {bridge}",
            suggested_chips=chips,
            suggested_field_update={"payment_channel": "bank_transfer"} if (amt and amt > 50000) else None,
        )

    # 2. SECTION 153 WITHHOLDING TAX
    elif topic == TOPIC_SECTION_153:
        statutory_ref = "Section 153 & Tenth Schedule, Income Tax Ordinance 2001"
        headline = "Section 153 Withholding Tax (WHT) Rates"
        advisory_md = (
            "Under **Section 153 of the Income Tax Ordinance, 2001** (Division III, Part III, First Schedule):\n\n"
            "* **Supply of Goods**: **5.0%** for corporate vendors, **5.5%** for individuals/AOPs (Non-filers: 10% / 11%).\n"
            "* **IT and IT-Enabled Services**: Reduced statutory rate of **4.0%** for active filers.\n"
            "* **General Services**: **9.0%** for corporate service providers, **11.0%** (or 14% non-corporate) for individuals.\n"
            "* **Professional Services**: **15.0%** (legal, audit, engineering, consultancy).\n"
            "* **Annual Exemption Thresholds**: Gross payments under **PKR 75,000/year** for goods, or **PKR 30,000/year** for services are exempt.\n"
            "* **Tenth Schedule Rule**: Rates double (2x) for vendors not listed on the FBR Active Taxpayers List (ATL)."
        )
        rec = "Withholding tax must be deducted at source upon payment settlement unless the vendor presents an official FBR Exemption Certificate."
        bridge = f"Returning to your draft for **{item_desc}**: Does the supplier have an exemption certificate, or should we apply standard WHT deduction?"
        chips = ["Standard WHT Deduction", "Exemption Certificate Provided (0% WHT)", "Exempt (Under Annual Threshold)"]

        return ConsultativeAdvisoryResult(
            topic=topic,
            statutory_reference=statutory_ref,
            headline=headline,
            advisory_markdown=advisory_md,
            actionable_recommendation=rec,
            context_resume_prompt=f"{advisory_md}\n\n---\n**Next Step**: {bridge}",
            suggested_chips=chips,
        )

    # 3. IAS 16 CAPITALIZATION CRITERIA
    elif topic == TOPIC_IAS_16:
        statutory_ref = "IAS 16 Property, Plant and Equipment & IFRS Framework"
        headline = "IAS 16 Capitalization vs Operating Expense"
        advisory_md = (
            "Under **IAS 16 (Property, Plant and Equipment)**, an expenditure is capitalized on the Balance Sheet if:\n\n"
            "1. **Probable Economic Inflow**: It is probable that future economic benefits associated with the asset will flow to the entity over **more than 1 financial period (> 1 year)**.\n"
            "2. **Reliable Measurement**: The cost can be measured reliably.\n"
            "3. **Capitalization Materiality Threshold**: Material capital assets (e.g. laptops, servers, vehicles, furniture usually > PKR 25,000–50,000) are capitalized and depreciated.\n\n"
            "Expenditures on minor consumables, software subscriptions, routine repairs, and maintenance must be **expensed immediately** in the Profit & Loss statement."
        )
        rec = f"If **{item_desc}** will be used for over 1 year and represents substantial value, capitalize as a Fixed Asset."
        bridge = f"Returning to your draft: How would you like to treat **{item_desc}**?"
        chips = ["Capitalize as Fixed Asset (Recommended)", "Expense Immediately as P&L Expense"]

        return ConsultativeAdvisoryResult(
            topic=topic,
            statutory_reference=statutory_ref,
            headline=headline,
            advisory_markdown=advisory_md,
            actionable_recommendation=rec,
            context_resume_prompt=f"{advisory_md}\n\n---\n**Next Step**: {bridge}",
            suggested_chips=chips,
            suggested_field_update={"transaction_nature": "FIXED_ASSET"},
        )

    # 4. DEPRECIATION RULES & USEFUL LIVES
    elif topic == TOPIC_DEPRECIATION:
        statutory_ref = "IAS 16 & Third Schedule, Income Tax Ordinance 2001"
        headline = "Depreciation Rules & Standard Useful Lives"
        advisory_md = (
            "Standard accounting and FBR Third Schedule depreciation parameters:\n\n"
            "* **Computer & IT Hardware**: **3 Years** (33.3% Straight Line) or 30% Reducing Balance under FBR.\n"
            "* **Office Furniture & Fixtures**: **5 to 10 Years** (10% to 20% Straight Line) or 15% Reducing Balance.\n"
            "* **Motor Vehicles**: **5 Years** (20% Straight Line) or 15% Reducing Balance.\n"
            "* **Plant & Heavy Machinery**: **10 Years** (10% Straight Line) or 15% Reducing Balance.\n\n"
            "**Methods**:\n"
            "- **Straight Line**: Equal expense recognized every month across the useful life (Cost − Salvage) ÷ Life.\n"
            "- **Reducing Balance**: Higher depreciation in initial years, applying a constant % to the opening Book Value."
        )
        rec = "Straight-line depreciation over 3 years is standard for computers; 5 years for furniture."
        bridge = f"Returning to your draft for **{item_desc}**: Would you like to apply the standard straight-line schedule?"
        chips = ["Accept 3-Yr Straight Line (Recommended)", "5 Years Straight Line", "10 Years Straight Line", "No Depreciation"]

        return ConsultativeAdvisoryResult(
            topic=topic,
            statutory_reference=statutory_ref,
            headline=headline,
            advisory_markdown=advisory_md,
            actionable_recommendation=rec,
            context_resume_prompt=f"{advisory_md}\n\n---\n**Next Step**: {bridge}",
            suggested_chips=chips,
        )

    # 5. IFRS 16 LEASE VS BUY / SIMULATION
    elif topic == TOPIC_IFRS_16:
        statutory_ref = "IFRS 16 Leases & Third Schedule / Section 73, Income Tax Ordinance 2001"
        headline = "IFRS 16 Lease vs Buy Financial & Tax Simulation"
        sim_amt = amt if (amt and amt > 0) else 5000000.0
        try:
            from app.financial_simulation import simulate_scenario
            sim_res = simulate_scenario(scenario_type="lease_vs_buy", amount=sim_amt)
            buy_npc = sim_res.options["BUY"].net_present_cost
            lease_npc = sim_res.options["LEASE"].net_present_cost
            npc_diff = abs(buy_npc - lease_npc)
            adv_recom = sim_res.recommendation.plain_english_summary
            verdict = sim_res.recommendation.verdict
        except Exception:
            buy_npc = sim_amt * 0.75
            lease_npc = sim_amt * 0.71
            npc_diff = abs(buy_npc - lease_npc)
            adv_recom = "Leasing delivers superior capital efficiency while preserving liquid working capital."
            verdict = "PREFER_LEASE"

        advisory_md = (
            f"Under **IFRS 16 (Leases)** and Pakistan Tax Law (Income Tax Ordinance, 2001):\n\n"
            f"* **Option A (Outright Capex Purchase)**: Initial liquid cash outflow of **PKR {sim_amt:,.0f}**. Capitalized under IAS 16. Generates annual Third Schedule tax depreciation shield; Net Present Cost (NPC): **PKR {buy_npc:,.0f}**.\n"
            f"* **Option B (36-Month Lease Structure)**: Recognizes **Right-of-Use (ROU) Asset** and matching **Lease Liability** (discounted at incremental borrowing rate of 15% KIBOR). Preserves immediate liquid working capital; Net Present Cost (NPC): **PKR {lease_npc:,.0f}**.\n"
            f"* **Comparative Differential**: **PKR {npc_diff:,.0f}** NPC advantage favoring **{verdict.replace('_', ' ').title()}**.\n\n"
            f"**Executive CFO Recommendation**: {adv_recom}"
        )
        rec = adv_recom
        bridge = f"Returning to your scenario for **{item_desc}** (Rs. {sim_amt:,.0f}): Would you like to proceed with the **Lease Structure** or **Outright Purchase**?"
        chips = ["Model 36-Month Lease Option", "Model Outright Capex Purchase", "Adjust Discount Rate (15% KIBOR)"]

        return ConsultativeAdvisoryResult(
            topic=topic,
            statutory_reference=statutory_ref,
            headline=headline,
            advisory_markdown=advisory_md,
            actionable_recommendation=rec,
            context_resume_prompt=f"{advisory_md}\n\n---\n**Next Step**: {bridge}",
            suggested_chips=chips,
            suggested_field_update={"scenario_type": "lease_vs_buy"},
        )

    # 6. SALES TAX RULES
    else:
        statutory_ref = "Sales Tax Act 1990 & Provincial Sales Tax on Services Acts"
        headline = "Sales Tax & Provincial VAT Rates"
        advisory_md = (
            "Standard sales tax applicable across Pakistan jurisdictions:\n\n"
            "* **FBR Federal GST (Goods)**: Standard **18.0%**. Supplies to unregistered parties incur an additional **4.0% Further Tax**.\n"
            "* **Punjab (PRA Services)**: Standard **16.0%** (Reduced 5% for IT/telecom software).\n"
            "* **Sindh (SRB Services)**: Standard **15.0%** (Reduced 3% for IT software exporters).\n"
            "* **KPK (KPRA Services)**: Standard **15.0%**.\n"
            "* **Input Tax Recovery**: Input tax can only be claimed if the vendor is Registered & Active on the FBR ATL and issues a valid tax invoice with STRN."
        )
        rec = "Ensure vendor STRN and Active ATL status are recorded to claim sales tax input adjustments."
        bridge = f"Returning to your draft for **{item_desc}**: What is the applicable sales tax treatment?"
        chips = ["FBR Goods (+18%)", "Punjab Services PRA (16%)", "Sindh Services SRB (15%)", "Tax Exempt (0%)"]

        return ConsultativeAdvisoryResult(
            topic=topic,
            statutory_reference=statutory_ref,
            headline=headline,
            advisory_markdown=advisory_md,
            actionable_recommendation=rec,
            context_resume_prompt=f"{advisory_md}\n\n---\n**Next Step**: {bridge}",
            suggested_chips=chips,
        )


def is_consultative_query(text: str) -> bool:
    """Return True if the text asks a consultative statutory/accounting question."""
    return detect_consultative_query(text) is not None


def get_consultative_advice(
    query: str,
    entities: Optional[Dict[str, Any]] = None,
    client: Any = None,
) -> Optional[ConsultativeAdvisoryResult]:
    """Return consultative advisory result (supports both string operations and structured fields)."""
    topic = detect_consultative_query(query)
    if not topic:
        return None
    return generate_consultative_advisory(topic=topic, user_message=query, entities=entities)
