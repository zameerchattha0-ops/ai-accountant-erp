"""Conversational Manager — Progressive Dialogue Pacing & Smart Defaults.

Implements DOC-ACC-2026-V1 Decision 1 (Option A):
- Single focused high-leverage question at a time (progressive dialogue pacing).
- Claude-style conversational authoring with smart accounting defaults and recommendations.
- Interactive quick-reply chips for one-tap answers.
- Expansion of smart default answers into comprehensive accounting parameters in a single shot.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ProgressiveQuestion(BaseModel):
    """A single focused conversational question with smart defaults and quick chips."""

    primary_field: str
    question_text: str
    smart_default_value: Optional[str] = None
    chips: List[str] = Field(default_factory=list)
    expanded_fields: Dict[str, Any] = Field(default_factory=dict)
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Smart Default Presets by Item Type
# ---------------------------------------------------------------------------

_IT_KEYWORDS = frozenset({
    "laptop", "dell", "hp", "lenovo", "macbook", "computer", "pc",
    "workstation", "server", "monitor", "printer", "scanner", "ipad", "tablet",
})

_FURNITURE_KEYWORDS = frozenset({
    "furniture", "chair", "chairs", "table", "tables", "desk", "desks",
    "sofa", "cabinet", "shelf", "cupboard", "workstations",
})

_VEHICLE_KEYWORDS = frozenset({
    "vehicle", "car", "van", "truck", "motorcycle", "bike", "pickup", "jeep",
})

_MACHINERY_KEYWORDS = frozenset({
    "generator", "machine", "machinery", "plant", "air conditioner", "ac", "chiller",
})


def _match_asset_category(item_description: str) -> str:
    """Classify the item description into an asset category for smart defaults."""
    low = (item_description or "").lower()
    words = set(re.findall(r"\b[a-z]+\b", low))

    if words & _IT_KEYWORDS:
        return "IT_EQUIPMENT"
    if words & _FURNITURE_KEYWORDS:
        return "FURNITURE"
    if words & _VEHICLE_KEYWORDS:
        return "VEHICLE"
    if words & _MACHINERY_KEYWORDS:
        return "MACHINERY"
    return "GENERAL_ASSET"


# ---------------------------------------------------------------------------
# High-Leverage Question Selection
# ---------------------------------------------------------------------------

# Hierarchy of Question Importance (Highest to Lowest)
_FIELD_PRIORITY_ORDER = [
    # 1. Core Nature / Intent
    "transaction_nature",
    "transaction_intent",
    # 2. Financial Magnitude
    "amount",
    "total_amount",
    # 3. Counterparty
    "supplier_name",
    "customer_name",
    "employee_name",
    "counterparty",
    # 4. Settlement Channel
    "payment_channel",
    "payment_method",
    "payment_type",
    "settlement_position",
    # 5. Fixed Asset Accounting Policy (bundled into smart default)
    "useful_life_years",
    "depreciation_method",
    "salvage_value",
    # 6. Specific document dates
    "transaction_date",
    "expense_date",
    "date_of_joining",
]


def pick_next_leverage_field(missing_fields: Sequence[str]) -> Optional[str]:
    """Select the SINGLE most critical missing field according to accounting hierarchy."""
    clean_missing = {str(f).strip() for f in missing_fields if str(f).strip()}
    if not clean_missing:
        return None

    for candidate in _FIELD_PRIORITY_ORDER:
        if candidate in clean_missing:
            return candidate

    # Return the first remaining missing field if not explicitly in priority ladder
    return sorted(clean_missing)[0]


# ---------------------------------------------------------------------------
# Question Authoring with Smart Accounting Defaults
# ---------------------------------------------------------------------------

def author_single_focused_question(
    *,
    field_to_ask: str,
    entities: Dict[str, Any],
    intent: str = "",
    missing_fields: Sequence[str] = (),
) -> ProgressiveQuestion:
    """Construct a conversational, high-leverage question with smart accounting defaults."""
    ents = dict(entities or {})
    line_items = ents.get("line_items") or ents.get("disaggregated_items")

    # In multi-entity split transactions, if asking about fixed asset depreciation or capitalization,
    # isolate the specific asset line item rather than using the concatenated description of all lines!
    asset_line = None
    if isinstance(line_items, list) and len(line_items) > 1:
        for li in line_items:
            if isinstance(li, dict):
                nature = str(li.get("nature") or "").upper()
                std = str(li.get("ifrs_standard") or "").upper()
                desc_li = str(li.get("description") or "").lower()
                cat = _match_asset_category(desc_li)
                if (
                    nature == "FIXED_ASSET"
                    or "IAS 16" in std
                    or li.get("is_fixed_asset")
                    or cat in ("IT_EQUIPMENT", "FURNITURE", "VEHICLE", "MACHINERY")
                    or any(k in desc_li for k in ("laptop", "computer", "macbook", "server", "equipment", "vehicle", "car", "furniture"))
                ):
                    asset_line = li
                    break

    if asset_line and field_to_ask in ("useful_life_years", "depreciation_method", "salvage_value", "transaction_nature"):
        item_desc = str(asset_line.get("description") or "the asset").strip()
        raw_amt = asset_line.get("amount") or asset_line.get("line_total")
    else:
        item_desc = str(
            ents.get("item_description")
            or ents.get("description")
            or ents.get("asset_name")
            or ents.get("product_name")
            or "the item"
        ).strip()
        raw_amt = ents.get("amount") or ents.get("total_amount")

    amt: Optional[float] = None
    if raw_amt is not None:
        try:
            amt = float(str(raw_amt).replace(",", "").strip())
        except (ValueError, TypeError):
            amt = None

    # -----------------------------------------------------------------------
    # 1. TRANSACTION NATURE / CAPITALIZATION
    # -----------------------------------------------------------------------
    if field_to_ask in ("transaction_nature", "transaction_intent"):
        category = _match_asset_category(item_desc)
        if category in ("IT_EQUIPMENT", "FURNITURE", "VEHICLE", "MACHINERY") or (amt and amt >= 25000.0):
            q_text = (
                f"How would you like to record **{item_desc}**? "
                "Because this item has a multi-year useful life, standard practice under IAS 16 is to "
                "**capitalize as a Fixed Asset** and depreciate over time. Or would you prefer to **expense immediately**?"
            )
            chips = [
                "Capitalize as Fixed Asset (Recommended)",
                "Expense Immediately (P&L)",
                "Inventory for Resale",
            ]
            return ProgressiveQuestion(
                primary_field="transaction_nature",
                question_text=q_text,
                smart_default_value="FIXED_ASSET",
                chips=chips,
                expanded_fields={"transaction_nature": "FIXED_ASSET"},
                rationale="IAS 16 recognition criteria for durable capital assets.",
            )
        else:
            q_text = f"Is **{item_desc}** an operating expense, inventory for resale, or a fixed asset?"
            chips = ["Operating Expense", "Inventory (Resale)", "Fixed Asset"]
            return ProgressiveQuestion(
                primary_field="transaction_nature",
                question_text=q_text,
                chips=chips,
            )

    # -----------------------------------------------------------------------
    # 2. TOTAL AMOUNT
    # -----------------------------------------------------------------------
    if field_to_ask in ("amount", "total_amount"):
        q_text = f"What is the total amount (cost) for **{item_desc}**?"
        chips = ["Rs. 25,000", "Rs. 50,000", "Rs. 100,000"]
        return ProgressiveQuestion(
            primary_field="amount",
            question_text=q_text,
            chips=chips,
            rationale="A financial amount is required to calculate debit and credit journal lines.",
        )

    # -----------------------------------------------------------------------
    # 3. COUNTERPARTY (Supplier / Customer / Employee)
    # -----------------------------------------------------------------------
    if field_to_ask in ("supplier_name", "customer_name", "employee_name", "counterparty"):
        low_intent = (intent or "").lower()
        if "sale" in low_intent or "invoice" in low_intent:
            q_text = "Who is the customer for this invoice?"
            chips = ["Cash Customer", "Walk-in Client"]
            role = "customer"
        elif "payroll" in low_intent or "salary" in low_intent:
            q_text = "What is the employee's name for this payroll disbursement?"
            chips = []
            role = "employee"
        else:
            q_text = f"Who was the supplier or vendor for **{item_desc}**?"
            chips = ["Local Vendor", "Online / Direct Store"]
            role = "supplier"

        return ProgressiveQuestion(
            primary_field=field_to_ask,
            question_text=q_text,
            chips=chips,
            rationale="Party ledger linking for reconciliation and payables.",
        )

    # -----------------------------------------------------------------------
    # 4. PAYMENT CHANNEL & SETTLEMENT (with Section 73 statutory defaults)
    # -----------------------------------------------------------------------
    if field_to_ask in ("payment_channel", "payment_method", "payment_type", "settlement_position"):
        if amt and amt > 50000.0:
            q_text = (
                f"The transaction amount is **Rs. {amt:,.0f}**, which exceeds the PKR 50,000 cash limit under Section 73. "
                "To safeguard tax deductibility under Section 21(l), corporate payments are typically made via "
                "**Bank Transfer / Crossed Cheque**. Which payment method was used?"
            )
            chips = [
                "Bank Transfer (Recommended)",
                "Crossed Cheque",
                "Cash in Hand (Acknowledge Risk)",
                "On Credit (Pay Later)",
            ]
            default_val = "bank_transfer"
        else:
            amt_str = f" of Rs. {amt:,.0f}" if amt else ""
            q_text = f"How was the payment{amt_str} settled for **{item_desc}**?"
            chips = ["Cash in Hand", "Bank Transfer", "On Credit (Pay Later)"]
            default_val = "cash"

        return ProgressiveQuestion(
            primary_field="payment_channel",
            question_text=q_text,
            smart_default_value=default_val,
            chips=chips,
            rationale="Section 73 compliance and cash/bank ledger selection.",
        )

    # -----------------------------------------------------------------------
    # 5. FIXED ASSET DEPRECIATION SCHEDULE (Pre-packaged IAS 16 smart defaults)
    # -----------------------------------------------------------------------
    if field_to_ask in ("useful_life_years", "depreciation_method", "salvage_value"):
        category = _match_asset_category(item_desc)

        amt_phrase = f" (Rs. {amt:,.0f})" if amt else ""
        if category == "IT_EQUIPMENT":
            q_text = (
                f"For IT equipment like **{item_desc}**{amt_phrase}, standard accounting policy under IAS 16 recommends a "
                "**3-year useful life** using straight-line depreciation (with zero residual value). "
                "Would you like to apply this standard schedule?"
            )
            chips = [
                "Accept 3-Yr Straight Line (Recommended)",
                "5 Years Straight Line",
                "Expense Immediately",
                "No Depreciation",
            ]
            expanded = {
                "useful_life_years": "3",
                "depreciation_method": "STRAIGHT_LINE",
                "salvage_value": "0",
            }
        elif category == "FURNITURE":
            q_text = (
                f"For office furniture like **{item_desc}**, corporate accounting policy typically applies a "
                "**5-year straight-line depreciation** schedule (zero residual value). "
                "Would you like to apply this policy?"
            )
            chips = [
                "Accept 5-Yr Straight Line (Recommended)",
                "10 Years Straight Line",
                "Expense Immediately",
                "No Depreciation",
            ]
            expanded = {
                "useful_life_years": "5",
                "depreciation_method": "STRAIGHT_LINE",
                "salvage_value": "0",
            }
        elif category == "VEHICLE":
            q_text = (
                f"For vehicles like **{item_desc}**, standard schedules apply **5 years straight-line** (or 20% reducing balance). "
                "Which schedule would you prefer?"
            )
            chips = [
                "Accept 5-Yr Straight Line (Recommended)",
                "20% Reducing Balance",
                "10 Years Straight Line",
            ]
            expanded = {
                "useful_life_years": "5",
                "depreciation_method": "STRAIGHT_LINE",
                "salvage_value": "0",
            }
        else:
            q_text = (
                f"What useful life should I apply for **{item_desc}**? "
                "Standard straight-line depreciation over **3 years** is recommended."
            )
            chips = [
                "Accept 3-Yr Straight Line (Recommended)",
                "5 Years Straight Line",
                "No Depreciation",
            ]
            expanded = {
                "useful_life_years": "3",
                "depreciation_method": "STRAIGHT_LINE",
                "salvage_value": "0",
            }

        return ProgressiveQuestion(
            primary_field="useful_life_years",
            question_text=q_text,
            smart_default_value="3",
            chips=chips,
            expanded_fields=expanded,
            rationale="IAS 16 depreciation schedule pre-packaged default.",
        )

    # -----------------------------------------------------------------------
    # 6. TRANSACTION DATE
    # -----------------------------------------------------------------------
    if field_to_ask in ("transaction_date", "expense_date", "date_of_joining"):
        q_text = f"What was the transaction date for **{item_desc}**? (Reply Today, Yesterday, or a specific date)"
        chips = ["Today", "Yesterday"]
        return ProgressiveQuestion(
            primary_field="transaction_date",
            question_text=q_text,
            smart_default_value="TODAY",
            chips=chips,
            rationale="Transaction posting date is required for general ledger journal sequencing.",
        )

    # Fallback generic question
    label = field_to_ask.replace("_", " ")
    return ProgressiveQuestion(
        primary_field=field_to_ask,
        question_text=f"Please provide the {label} for **{item_desc}**.",
        chips=[],
    )


# ---------------------------------------------------------------------------
# Answer Expansion for Smart Defaults
# ---------------------------------------------------------------------------

def expand_smart_default_answer(user_answer: str) -> Optional[Dict[str, Any]]:
    """Expand a quick chip or affirmative answer into a complete set of accounting fields."""
    ans = (user_answer or "").strip().lower()

    # 1. Bank transfer / payment channel selection (check before generic 'recommended')
    if any(k in ans for k in ("bank transfer", "online transfer", "wire", "crossed cheque")):
        pm = "CHEQUE" if "cheque" in ans else "BANK"
        return {
            "payment_channel": "bank_transfer" if pm == "BANK" else "cheque",
            "payment_method": pm,
        }

    # 2. Immediate expense selection
    if any(k in ans for k in ("expense immediately", "treat as expense", "p&l expense", "operating expense")):
        return {
            "transaction_nature": "OPERATING_EXPENSE",
            "capitalization_decision": "EXPENSE",
            "useful_life_years": "NONE",
            "depreciation_method": "NONE",
        }

    # 3. Fixed asset capitalization acceptance
    if any(k in ans for k in ("capitalize as fixed asset", "capitalize")):
        return {
            "transaction_nature": "FIXED_ASSET",
            "capitalization_decision": "CAPITALIZE",
        }

    # 4. 3-Year IT Equipment default
    if any(k in ans for k in ("3-yr", "3 yr", "3 year", "3 years", "3-year", "accept 3-yr", "accept 3")):
        return {
            "useful_life_years": "3",
            "depreciation_method": "STRAIGHT_LINE",
            "salvage_value": "0",
        }

    # 5. 5-Year Furniture/Vehicle default
    if any(k in ans for k in ("5-yr", "5 yr", "5 year", "5 years", "5-year", "accept 5-yr", "accept 5")):
        return {
            "useful_life_years": "5",
            "depreciation_method": "STRAIGHT_LINE",
            "salvage_value": "0",
        }

    # 6. 10-Year default
    if any(k in ans for k in ("10-yr", "10 yr", "10 year", "10 years", "10-year")):
        return {
            "useful_life_years": "10",
            "depreciation_method": "STRAIGHT_LINE",
            "salvage_value": "0",
        }

    # 7. General acceptance of defaults
    if any(k in ans for k in ("accept defaults", "standard default", "use default", "apply default", "yes, apply", "recommended defaults")) or ans == "recommended":
        return {
            "useful_life_years": "3",
            "depreciation_method": "STRAIGHT_LINE",
            "salvage_value": "0",
        }

    return None


# Standard schedule affirmative triggers
_STANDARD_SCHEDULE_AFFIRMATIVE = (
    "standard",
    "standard schedule",
    "standard schedule is fine",
    "yes",
    "proceed",
    "ok",
    "okay",
    "sure",
    "fine",
    "recommended",
    "straight line",
    "slm",
    "use standard",
    "adopt standard",
    "default",
    "accept",
    "accept 3-yr straight line (recommended)",
    "accept 3-yr straight line",
    "accept 5-yr straight line (recommended)",
    "accept 5-yr straight line",
    "1",
    "(1)",
    "a",
    "(a)",
)


def is_standard_schedule_acceptance(reply: str) -> bool:
    """Return True if the user reply accepts the standard corporate depreciation schedule."""
    if not reply:
        return False
    norm = reply.strip().lower()
    if any(k in norm for k in (
        "accept 3-yr", "accept 5-yr", "accept 3 yr", "accept 5 yr",
        "accept 3-year", "accept 5-year", "recommended", "standard schedule",
        "straight line (equal monthly)", "accept straight line",
    )):
        return True
    if norm in ("straight line", "straight-line", "straightline"):
        return True
    return any(norm == t or norm.startswith(t + " ") or norm.endswith(" " + t) or norm.startswith(t + ",") for t in _STANDARD_SCHEDULE_AFFIRMATIVE)


def expand_standard_schedule_answers(
    reply: str,
    entities: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """If user accepted the standard depreciation schedule, unpack the corporate defaults."""
    if not is_standard_schedule_acceptance(reply):
        expanded = expand_smart_default_answer(reply)
        if expanded and "useful_life_years" in expanded:
            return {
                "useful_life_years": int(expanded["useful_life_years"]),
                "depreciation_method": expanded["depreciation_method"],
                "salvage_value": float(expanded.get("salvage_value") or 0.0),
            }
        return None

    line_items = entities.get("line_items") or entities.get("disaggregated_items")
    desc = None
    if isinstance(line_items, list) and len(line_items) > 1:
        for li in line_items:
            if isinstance(li, dict):
                nature = str(li.get("nature") or "").upper()
                std = str(li.get("ifrs_standard") or "").upper()
                desc_li = str(li.get("description") or "").lower()
                cat_li = _match_asset_category(desc_li)
                if (
                    nature == "FIXED_ASSET"
                    or "IAS 16" in std
                    or li.get("is_fixed_asset")
                    or cat_li in ("IT_EQUIPMENT", "FURNITURE", "VEHICLE", "MACHINERY")
                    or any(k in desc_li for k in ("laptop", "computer", "macbook", "server", "equipment", "vehicle", "car", "furniture"))
                ):
                    desc = li.get("description")
                    break
    if not desc:
        desc = str(entities.get("item_description") or entities.get("description") or "office furniture")
    cat = _match_asset_category(desc)
    life = 3 if cat == "IT_EQUIPMENT" else (10 if cat == "MACHINERY" else 5)
    return {
        "useful_life_years": life,
        "depreciation_method": "STRAIGHT_LINE",
        "salvage_value": 0.0,
    }


def extract_conversational_corrections(
    user_message: str,
    current_entities: Dict[str, Any],
) -> Dict[str, Any]:
    """Detect and extract out-of-order corrections (quantities, amounts, payment channel, bank)."""
    corrections: Dict[str, Any] = {}
    msg_low = (user_message or "").lower()

    qty_match = re.search(r"\b(?:actually|make\s+that|change\s+to|only)\s+(\d+)\s+([a-zA-Z]+)", msg_low)
    if not qty_match:
        qty_match = re.search(r"\b(\d+)\s+(?:chairs|tables|desks|laptops|computers|units|items)\s+instead\s+of\b", msg_low)
    if qty_match:
        try:
            new_qty = float(qty_match.group(1))
            corrections["quantity"] = new_qty
            old_qty = float(current_entities.get("quantity") or 1.0)
            old_amt = float(current_entities.get("amount") or current_entities.get("total_amount") or 0.0)
            if old_qty > 0 and old_amt > 0:
                unit_price = old_amt / old_qty
                new_amt = round(unit_price * new_qty, 2)
                corrections["amount"] = new_amt
                corrections["total_amount"] = new_amt
        except (ValueError, TypeError):
            pass

    if any(k in msg_low for k in ("meezan", "hbl", "ubl", "mcb", "bank transfer", "online transfer", "via bank")):
        corrections["payment_method"] = "BANK"
        corrections["payment_channel"] = "bank_transfer"
        for b_name in ("Meezan Bank", "HBL", "UBL", "MCB", "Standard Chartered", "Bank Alfalah", "Allied Bank"):
            if b_name.lower() in msg_low:
                corrections["bank_name"] = b_name
                break
        if "bank_name" not in corrections and "meezan" in msg_low:
            corrections["bank_name"] = "Meezan Bank"
    elif "cash" in msg_low and not any(k in msg_low for k in ("not cash", "instead of cash")):
        corrections["payment_method"] = "CASH"
        corrections["payment_channel"] = "cash"
    elif any(k in msg_low for k in ("credit", "on credit", "pay later", "bill me", "payable")):
        corrections["payment_method"] = "CREDIT"
        corrections["payment_channel"] = "credit"

    amt_match = re.search(r"\b(?:total|price|amount|cost)\s+(?:is|was|of)\s+(?:rs\.?|pkr)?\s*([0-9,]+(?:\.\d+)?)\b", msg_low)
    if amt_match:
        try:
            clean_amt = float(amt_match.group(1).replace(",", ""))
            if clean_amt > 0:
                corrections["amount"] = clean_amt
                corrections["total_amount"] = clean_amt
        except (ValueError, TypeError):
            pass

    return corrections


def format_claude_style_progressive_question(
    *,
    intent: str,
    missing_fields: Sequence[str],
    entities: Dict[str, Any],
    nature: Optional[str] = None,
    org_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[str], List[Dict[str, str]]]:
    """Generate a single focused high-leverage question with smart corporate defaults."""
    next_field = pick_next_leverage_field(missing_fields)
    if not next_field:
        return "Could you please confirm the remaining transaction details?", [], []

    q_obj = author_single_focused_question(
        field_to_ask=next_field,
        entities=entities,
        intent=intent,
        missing_fields=missing_fields,
    )
    chips = q_obj.chips
    opts = [{"value": c, "label": c} for c in chips]
    return q_obj.question_text, chips, opts


def compose_consultative_response_with_draft(
    *,
    user_query: str,
    living_draft: Dict[str, Any],
    next_question: str,
    advice: Optional[Any] = None,
) -> str:
    """Compose a cohesive response combining statutory advice, living draft status, and next question."""
    parts: List[str] = []
    if advice:
        if hasattr(advice, "advisory_markdown"):
            parts.append(advice.advisory_markdown)
        else:
            parts.append(str(advice))

    doc_type = living_draft.get("document_type") or "Voucher"
    amt = living_draft.get("total_amount") or 0.0
    channel = living_draft.get("payment_channel") or "Pending"
    bank = living_draft.get("bank_name")
    channel_display = f"{channel.replace('_', ' ').title()}" + (f" ({bank})" if bank else "")

    parts.append(
        f"\n**Current Living Draft Status ({doc_type}):**\n"
        f"• **Total Amount:** Rs. {amt:,.2f}\n"
        f"• **Payment Channel:** {channel_display}\n"
        f"• **Status:** {living_draft.get('status', 'DRAFT')}"
    )
    if next_question:
        parts.append(f"\n{next_question}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Frontier Modules Enrichment Bridge (DOC-CFO-2026-FRONTIER-V1)
# ---------------------------------------------------------------------------

def enrich_frontier_metadata(
    *,
    user_message: Optional[str] = None,
    living_draft: Optional[Dict[str, Any]] = None,
    entities: Optional[Dict[str, Any]] = None,
    intent: Optional[str] = None,
    tool_result_data: Optional[Dict[str, Any]] = None,
    is_completed: bool = False,
    historical_records: Optional[Sequence[Dict[str, Any]]] = None,
    recent_transactions: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Enrich turn payload with the 4 frontier conversational modules (DOC-CFO-2026-FRONTIER-V1).

    1. Interactive Artifacts (Pillar 1):
       - Attaches tappable account pills, reactive depreciation sliders, Section 153 WHT toggle.
    2. "What-If" Financial Simulation (Pillar 2):
       - Evaluates Lease vs Buy (IFRS 16), Cash vs Bank (Section 73 ITO 2001), Capitalize vs Expense (IAS 16).
    3. Episodic Memory & Vendor Fingerprinting (Pillar 3):
       - Identifies vendor payment customs, 30-day ATL freshness check, and 72-hour duplicate/structuring hazards.
    4. Post-Transaction "Next Best Action" (Pillar 4):
       - Monitors budget burn headroom, statutory FBR filing calendars (14th/15th/18th), and cash runway impact.
    """
    out: Dict[str, Any] = {
        "interactive_artifacts": None,
        "simulations": None,
        "vendor_insights": None,
        "next_best_actions": None,
        "intent_progression": None,
    }
    ents = dict(entities or {})
    low_msg = (user_message or "").lower()

    # Live Intent Progression Synthesis
    try:
        prog_status = "completed" if is_completed else ("clarifying" if (living_draft and living_draft.get("missing_fields")) else "reviewing")
        out["intent_progression"] = build_intent_progression(
            intent=intent,
            entities=ents,
            missing_fields=living_draft.get("missing_fields") if living_draft else None,
            status=prog_status,
        )
    except Exception as _prog_exc:
        log.warning("frontier.intent_progression_failed", error=str(_prog_exc)[:160])

    # 1. Interactive Artifacts
    if living_draft:
        art = living_draft.get("interactive_artifact")
        if art:
            out["interactive_artifacts"] = [art]

    # 2. What-If Financial Simulation
    scenario_type = None
    if any(k in low_msg for k in ("lease vs buy", "lease or buy", "ifrs 16", "ifrs16", "rent vs buy")):
        scenario_type = "lease_vs_buy"
    elif any(k in low_msg for k in ("cash vs bank", "cash or bank", "section 73", "sec 73", "cash limit")):
        scenario_type = "cash_vs_bank"
    elif any(k in low_msg for k in ("capitalize vs expense", "capex vs opex", "capitalize or expense", "ias 16", "ias16")):
        scenario_type = "capitalize_vs_expense"

    if scenario_type:
        try:
            from app.financial_simulation import simulate_scenario

            amt = None
            for k in ("amount", "total_amount", "cost", "total"):
                if ents.get(k):
                    try:
                        amt = float(str(ents[k]).replace(",", ""))
                        break
                    except (ValueError, TypeError):
                        pass
            if not amt or amt <= 0:
                m_nums = re.findall(r"\b(\d[\d,]{3,})\b", user_message or "")
                if m_nums:
                    try:
                        amt = float(m_nums[0].replace(",", ""))
                    except Exception:
                        pass
            if not amt or amt <= 0:
                amt = 5000000.0 if scenario_type == "lease_vs_buy" else 150000.0
            sim_res = simulate_scenario(scenario_type=scenario_type, amount=amt)
            out["simulations"] = [sim_res.model_dump()]
        except Exception as _sim_exc:
            log.warning("frontier.simulation_failed", error=str(_sim_exc)[:160])

    # 3. Episodic Memory & Vendor Fingerprinting Guard
    v_name = (
        ents.get("vendor_name")
        or ents.get("supplier_name")
        or ents.get("party_name")
        or (ents.get("counterparty", {}).get("name") if isinstance(ents.get("counterparty"), dict) else None)
    )
    if v_name and isinstance(v_name, str) and v_name.strip():
        try:
            from app.vendor_memory_guard import lookup_vendor_fingerprint, check_duplicate_risk

            amt = 0.0
            for k in ("amount", "total_amount", "total"):
                if ents.get(k):
                    try:
                        amt = float(str(ents[k]).replace(",", ""))
                        break
                    except (ValueError, TypeError):
                        pass

            fp = lookup_vendor_fingerprint(
                vendor_name=v_name,
                historical_records=historical_records or (),
            )
            dup_res = check_duplicate_risk(
                vendor_name=v_name,
                amount=amt,
                invoice_ref=ents.get("invoice_number") or ents.get("bill_number") or ents.get("invoice_ref"),
                recent_transactions=recent_transactions or (),
                payment_method=ents.get("payment_method") or ents.get("payment_channel"),
            )
            v_dict: Dict[str, Any] = {
                "vendor_name": v_name,
                "duplicate_scan": dup_res.model_dump(),
            }
            if fp:
                v_dict["fingerprint"] = fp.model_dump()
                v_dict["suggested_terms_prompt"] = fp.suggest_terms_prompt()
            out["vendor_insights"] = v_dict
        except Exception as _vg_exc:
            log.warning("frontier.vendor_memory_failed", error=str(_vg_exc)[:160])

    # 4. Post-Transaction Next Best Action & Virtual CFO
    if is_completed:
        try:
            from app.next_best_action import generate_next_best_actions

            amt = 0.0
            for k in ("amount", "total_amount", "total"):
                if ents.get(k):
                    try:
                        amt = float(str(ents[k]).replace(",", ""))
                        break
                    except (ValueError, TypeError):
                        pass
            if not amt and living_draft:
                amt = float(living_draft.get("total_amount") or 0.0)

            tx_lines = []
            if living_draft and living_draft.get("voucher_preview"):
                for l in living_draft["voucher_preview"]:
                    if isinstance(l, dict):
                        tx_lines.append(l)
                    elif hasattr(l, "model_dump"):
                        tx_lines.append(l.model_dump())

            tx_payload = {
                "intent": intent,
                "total": amt,
                "amount": amt,
                "date": ents.get("transaction_date") or ents.get("date") or (living_draft.get("transaction_date") if living_draft else None),
                "payment_channel": ents.get("payment_channel") or ents.get("payment_method") or (living_draft.get("payment_channel") if living_draft else None),
                "bank_name": ents.get("bank_name") or (living_draft.get("bank_name") if living_draft else None),
                "vendor_name": v_name,
                "lines": tx_lines,
                "is_capex": (
                    ents.get("transaction_nature") == "FIXED_ASSET"
                    or (living_draft.get("depreciation_schedule") is not None if living_draft else False)
                ),
            }

            nba_res = generate_next_best_actions(
                posted_transaction=tx_payload
            )
            out["next_best_actions"] = [item.model_dump() for item in nba_res.items]
        except Exception as _nba_exc:
            log.warning("frontier.next_best_action_failed", error=str(_nba_exc)[:160])

    return out


# ---------------------------------------------------------------------------
# Live Intent Progression Builder (DOC-CFO-2026-PROGRESSION-V1)
# ---------------------------------------------------------------------------

def build_intent_progression(
    *,
    intent: Optional[str] = None,
    entities: Optional[Dict[str, Any]] = None,
    missing_fields: Optional[Sequence[str]] = None,
    status: str = "clarifying",
    custom_reasoning: Optional[str] = None,
    active_question: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a clean, live Intent Progression dictionary for UI tracking.

    Returns a structured object showing verified facts, active LLM reasoning,
    and missing details, replacing cluttered interactive voucher cards.
    """
    ents = dict(entities or {})
    missing = [str(f).strip() for f in (missing_fields or []) if str(f).strip()]
    facts: List[Dict[str, str]] = []

    # 1. Counterparty
    party = (
        ents.get("counterparty")
        or ents.get("supplier_name")
        or ents.get("customer_name")
        or ents.get("employee_name")
        or ents.get("vendor_name")
        or ents.get("party_name")
    )
    if isinstance(party, dict):
        party_name = party.get("name")
    else:
        party_name = str(party).strip() if party else None
    if party_name and party_name.lower() not in ("none", "null", ""):
        low_i = (intent or "").lower()
        party_role = "Vendor" if any(k in low_i for k in ("supplier", "purchase", "expense", "asset", "bill", "payable")) else ("Customer" if any(k in low_i for k in ("sale", "invoice", "receipt", "receivable")) else "Counterparty")
        facts.append({"label": party_role, "value": party_name})

    # 1b. Reversal Intent Action (Phase 4B)
    if intent in ("reverse_journal", "reversal") or ents.get("is_reversal"):
        facts.append({"label": "Action", "value": "Journal Reversal (Contra Entry)"})
        v_num = ents.get("journal_number") or ents.get("voucher_number") or ents.get("entry_number") or ents.get("entry_id")
        if v_num:
            facts.append({"label": "Target Voucher", "value": str(v_num)})
        if status == "completed":
            custom_reasoning = f"Journal entry {v_num or ''} has been successfully reversed with offsetting contra entries in the General Ledger."
        elif status == "reviewing":
            custom_reasoning = f"Ready to post double-entry reversing voucher to nullify {v_num or 'target entry'} and restore balances."

    # 2. Total Amount
    raw_amt = ents.get("amount") or ents.get("total_amount") or ents.get("cost")
    if raw_amt not in (None, ""):
        try:
            amt_val = float(str(raw_amt).replace(",", "").strip())
            curr = str(ents.get("currency") or "PKR").upper()
            facts.append({"label": "Amount", "value": f"{curr} {amt_val:,.2f}"})
        except (ValueError, TypeError):
            facts.append({"label": "Amount", "value": str(raw_amt)})

    # 2b. Multi-Entity Split Lines (Phase 4A)
    line_items = ents.get("line_items") or ents.get("disaggregated_items")
    if isinstance(line_items, list) and len(line_items) > 1:
        facts.append({"label": "Split Allocation", "value": f"{len(line_items)} Lines (Segregated)"})
        for idx, li in enumerate(line_items[:4], start=1):
            if isinstance(li, dict):
                desc = li.get("description") or f"Item {idx}"
                amt = li.get("amount") or li.get("line_total")
                cat = li.get("ifrs_standard") or li.get("category") or li.get("nature") or ""
                cat_str = f" [{cat}]" if cat else ""
                if amt is not None:
                    facts.append({"label": f"Line {idx}", "value": f"{desc}: Rs. {float(amt):,.2f}{cat_str}"})

    # 3. Item / Description
    if not (isinstance(line_items, list) and len(line_items) > 1):
        item = ents.get("item_description") or ents.get("description") or ents.get("product_name") or ents.get("asset_name") or ents.get("service_name")
        if item and str(item).strip().lower() not in ("none", "null", ""):
            qty = ents.get("quantity")
            qty_str = f" ({qty:g} units)" if isinstance(qty, (int, float)) and qty > 1 else ""
            facts.append({"label": "Description", "value": f"{str(item).strip()}{qty_str}"})

    # 4. Classification / Nature
    nature = ents.get("transaction_nature")
    if isinstance(line_items, list) and len(line_items) > 1:
        has_capex = any(
            str(li.get("nature") or "").upper() in ("FIXED_ASSET", "CAPEX")
            or "IAS 16" in str(li.get("ifrs_standard") or "").upper()
            or li.get("is_fixed_asset")
            or _match_asset_category(str(li.get("description") or "")) in ("IT_EQUIPMENT", "FURNITURE", "VEHICLE", "MACHINERY")
            or any(k in str(li.get("description") or "").lower() for k in ("laptop", "computer", "macbook", "server", "equipment", "vehicle", "furniture"))
            for li in line_items if isinstance(li, dict)
        )
        has_opex = any(
            str(li.get("nature") or "").upper() in ("OPEX", "EXPENSE", "OPERATING_EXPENSE")
            or "IAS 1" in str(li.get("ifrs_standard") or "").upper()
            or any(k in str(li.get("description") or "").lower() for k in ("rent", "bill", "electricity", "utilit", "office", "expense", "fee"))
            for li in line_items if isinstance(li, dict)
        )
        if has_capex and has_opex:
            facts.append({"label": "Classification", "value": "Multi-Entity Split (Opex + Capex)"})
        elif has_capex:
            facts.append({"label": "Classification", "value": "Capital Asset Acquisition (IAS 16)"})
        else:
            facts.append({"label": "Classification", "value": "Operating Expenses (P&L)"})
    elif nature:
        nature_str = str(nature).upper()
        if "FIXED" in nature_str:
            facts.append({"label": "Classification", "value": "Capital Asset (IAS 16)"})
        elif "INVENTORY" in nature_str:
            facts.append({"label": "Classification", "value": "Inventory for Resale"})
        elif "EXPENSE" in nature_str or "OPERATING" in nature_str:
            facts.append({"label": "Classification", "value": "Operating Expense (P&L)"})
        elif "SERVICE" in nature_str:
            facts.append({"label": "Classification", "value": "Services"})
        else:
            facts.append({"label": "Classification", "value": nature_str.replace("_", " ").title()})

    # 5. Useful Life & Depreciation
    # ZERO-ASSUMPTION RULE: If useful_life_years or depreciation_method is currently in missing_fields,
    # it is unverified and MUST NOT be shown in verified_facts while clarifying!
    is_clarifying_life = (
        status == "clarifying"
        or any(f in missing for f in ("useful_life_years", "depreciation_method", "salvage_value", "policy"))
        or any(k in (active_question or "").lower() for k in ("useful life", "depreciation", "schedule"))
    )
    life = ents.get("useful_life_years") or ents.get("useful_life")
    if life not in (None, "", "NONE") and not is_clarifying_life:
        method = str(ents.get("depreciation_method") or "Straight-Line").replace("_", " ").title()
        facts.append({"label": "Useful Life", "value": f"{life} Years ({method})"})

    # 6. Payment Channel & Bank
    pm = ents.get("payment_channel") or ents.get("payment_method") or ents.get("payment_type")
    bank = ents.get("bank_name")
    if pm:
        pm_str = str(pm).upper()
        if "BANK" in pm_str or "TRANSFER" in pm_str:
            val = "Bank Transfer" + (f" ({bank})" if bank else "")
        elif "CASH" in pm_str:
            val = "Cash in Hand"
        elif "CREDIT" in pm_str or "PAYABLE" in pm_str:
            val = "On Credit (Payable)"
        elif "CHEQUE" in pm_str:
            val = "Crossed Cheque" + (f" ({bank})" if bank else "")
        else:
            val = pm_str.replace("_", " ").title()
        facts.append({"label": "Payment Method", "value": val})

    # 7. Tax / WHT Treatment
    wht_dec = ents.get("wht_decision") or ents.get("wht_status")
    wht_rate = ents.get("wht_rate_percent")
    if wht_dec:
        if str(wht_dec).upper() == "EXEMPT" or ents.get("wht_exempt"):
            facts.append({"label": "WHT Treatment", "value": "Exempt (Valid Certificate)"})
        elif wht_rate is not None:
            facts.append({"label": "WHT Treatment", "value": f"Section 153 Deduct ({wht_rate:g}%)"})
        else:
            facts.append({"label": "WHT Treatment", "value": "Section 153 Applicable"})

    # 8. Transaction Date
    tx_date = ents.get("transaction_date") or ents.get("expense_date")
    if tx_date:
        facts.append({"label": "Posting Date", "value": str(tx_date)})

    # 9. Account Type (for setup / master data tasks)
    acct_type = ents.get("account_type")
    if acct_type:
        facts.append({"label": "Account Type", "value": str(acct_type).upper()})

    # Active Reasoning Synthesis
    if custom_reasoning:
        reasoning = custom_reasoning
    elif status == "completed":
        reasoning = "Transaction verified and successfully posted to the general ledger with balanced entries."
    elif status == "reviewing" or not missing:
        reasoning = "All statutory and accounting requirements verified. Ready for balanced double-entry voucher review."
    else:
        reasons: List[str] = []
        if any(f in missing for f in ("transaction_nature", "transaction_intent")):
            reasons.append("Determining capital expenditure (IAS 16) vs immediate operating expense.")
        if isinstance(ents.get("line_items"), list) and len(ents.get("line_items")) > 1:
            reasons.append(f"Multi-Entity Split: Segregating {len(ents['line_items'])} line items across capital asset (IAS 16) and operating expenses for balanced compound journal posting.")
        if any(f in missing for f in ("useful_life_years", "depreciation_method")):
            reasons.append("Establishing IAS 16 asset useful life and depreciation policy.")
        if any(f in missing for f in ("payment_channel", "payment_method")):
            reasons.append("Checking Section 73 corporate banking channel compliance.")
        if any(f in missing for f in ("wht_certificate", "wht_status", "sales_tax_status")):
            reasons.append("Verifying FBR Section 153 withholding tax rate and ATL filer status.")
        if any(f in missing for f in ("supplier_name", "customer_name", "counterparty")):
            reasons.append("Identifying counterparty ledger for balanced party reconciliation.")
        if any(f in missing for f in ("amount", "total_amount")):
            reasons.append("Establishing total financial value for journal line balancing.")
        if any(f in missing for f in ("transaction_date", "expense_date")):
            reasons.append("Setting transaction posting date for period sequencing.")
        reasoning = " ".join(reasons) if reasons else "Gathering required transaction parameters to ensure true accounting treatment."

    # Missing Info summary
    missing_desc: Optional[str] = None
    if missing:
        field_labels = {
            "useful_life_years": "Useful Life (years)",
            "transaction_nature": "Classification (Capex vs Opex)",
            "payment_channel": "Payment Channel (Bank vs Cash)",
            "payment_method": "Payment Method",
            "supplier_name": "Supplier / Vendor Name",
            "customer_name": "Customer Name",
            "amount": "Total Amount",
            "transaction_date": "Posting Date",
            "account_type": "Account Type (Asset/Expense/etc.)",
            "wht_certificate": "Withholding Tax Certificate Status",
        }
        human_missing = [field_labels.get(f, f.replace("_", " ").title()) for f in missing[:3]]
        missing_desc = ", ".join(human_missing)

    return {
        "intent": intent or "record_transaction",
        "status": status,
        "verified_facts": facts,
        "active_reasoning": reasoning,
        "missing_info": missing_desc,
    }


async def synthesize_cumulative_dialogue_intent(
    *,
    user_request: str,
    history: Optional[List[Dict[str, Any]]] = None,
    current_entities: Optional[Dict[str, Any]] = None,
    latest_question: str = "",
    user_reply: str = "",
    missing_fields: Optional[List[str]] = None,
    client: Optional[Any] = None,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Synthesize user's clarification answer in full cumulative dialogue context with initial query.

    Zero-Assumption Rule: Only record facts explicitly provided or confirmed by the user.
    Analyzes Turn 0 (user request) + Turn 1 (question) + Turn 2 (answer) collectively.
    """
    import asyncio
    import json
    import re
    from app.date_parser import parse_transaction_date

    merged = dict(current_entities or {})
    raw_reply = str(user_reply or "").strip()
    user_req = str(user_request or "").strip()
    comb_text = f"{user_req} {raw_reply}".strip()
    if not comb_text:
        return {"entities": merged, "reasoning": "", "is_complete": False}

    # 1. Early cancel / explicit diversion intent signals from user's latest reply
    raw_low = raw_reply.lower()
    _cancel_phrases = (
        "cancel this", "cancel it", "never mind", "nevermind", "forget it",
        "abort", "stop this", "do not record", "don't record", "dont record",
    )
    if raw_low in ("cancel", "stop", "abort") or any(p in raw_low for p in _cancel_phrases):
        return {
            "entities": merged,
            "is_complete": False,
            "next_action": "CANCEL",
            "reasoning": "User cancelled the pending transaction before posting.",
        }

    # 2. LLM Cumulative Synthesis (Primary Semantic Authority — flexible diversion & goal check)
    llm_extracted: Dict[str, Any] = {}
    llm_next_action: Optional[str] = None
    llm_resolved_intent: Optional[str] = None
    llm_reasoning: str = ""
    llm_diversion_reason: Optional[str] = None
    if client is None:
        try:
            from app.ai_orchestrator import get_client
            client = get_client()
        except Exception:
            client = None

    if client is not None and raw_reply:
        try:
            formatted_history = []
            for h in (history or []):
                q = h.get("question") or h.get("field") or ""
                a = h.get("answer") or ""
                if q or a:
                    formatted_history.append(f"Q: {q}\nA: {a}")
            hist_str = "\n".join(formatted_history) if formatted_history else "None (First clarification round)"
            ents_str = json.dumps(merged, default=str)
            missing_str = ", ".join(missing_fields or [])

            prompt = (
                "You are an expert Chartered Accountant and Autonomous ERP Reasoning Engine.\n"
                "You are evaluating a live multi-turn accounting conversation. Do NOT follow blind fixed steps —\n"
                "reason over authenticity and the user's FINAL GOAL, with full flexibility to proceed, ask,\n"
                "or DIVERT to a different ERP workflow if the user changed direction or asked something new.\n"
                "CRITICAL ZERO-ASSUMPTION RULE: The user's request, confirmed records, and answers are the ONLY\n"
                "source of truth. Never fabricate amounts, dates, or policy choices.\n\n"
                f"INITIAL USER REQUEST:\n\"{user_request}\"\n\n"
                f"PRIOR CONVERSATION TRANSCRIPT:\n{hist_str}\n\n"
                f"CURRENTLY VERIFIED ENTITIES:\n{ents_str}\n\n"
                f"LATEST QUESTION ASKED BY YOU:\n\"{latest_question}\"\n\n"
                f"USER'S LATEST MESSAGE / ANSWER:\n\"{raw_reply}\"\n\n"
                f"FIELDS PREVIOUSLY THOUGHT MISSING:\n{missing_str}\n\n"
                "INSTRUCTIONS:\n"
                "1. Decide the authentic next step based on the user's message & final goal:\n"
                "   - PROCEED: the message supplies/confirms details needed to continue/finalize the transaction.\n"
                "   - ASK_CLARIFICATION: an essential accounting ambiguity still remains.\n"
                "   - DIVERT: the user changed the goal/workflow (e.g., switched from expense to purchase order/invoice/fixed asset,\n"
                "     changed line items structurally, asked to inspect balances/ledger first, or asked to reverse an entry).\n"
                "   - CANCEL: the user explicitly wants to stop or discard the pending action.\n"
                "2. Extract any updated entity fields (e.g., payment_method, bank_name, useful_life_years, depreciation_method, supplier_name, transaction_date, transaction_nature).\n"
                "3. Output STRICT JSON ONLY matching:\n"
                "{\n"
                "  \"next_action\": \"PROCEED|ASK_CLARIFICATION|DIVERT|CANCEL\",\n"
                "  \"resolved_intent\": \"<canonical intent or null>\",\n"
                "  \"diversion_reason\": \"<why diverting or null>\",\n"
                "  \"updated_entities\": {\"<field_name>\": \"<value>\"},\n"
                "  \"reasoning\": \"<1-2 sentences on authentic accounting treatment & goal readiness>\"\n"
                "}"
            )
            raw_llm = await asyncio.wait_for(
                client.generate_text_light(prompt=prompt),
                timeout=timeout,
            )
            match = re.search(r"\{.*\}", str(raw_llm or ""), re.S)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("updated_entities"), dict):
                        llm_extracted = parsed["updated_entities"]
                    raw_na = str(parsed.get("next_action") or "").strip().upper()
                    if raw_na in ("PROCEED", "ASK_CLARIFICATION", "DIVERT", "CANCEL"):
                        llm_next_action = raw_na
                    if parsed.get("resolved_intent"):
                        llm_resolved_intent = str(parsed["resolved_intent"]).strip()
                    if parsed.get("reasoning"):
                        llm_reasoning = str(parsed["reasoning"]).strip()
                    if parsed.get("diversion_reason"):
                        llm_diversion_reason = str(parsed["diversion_reason"]).strip()
        except Exception as exc:
            log.warning("conversational_manager.cumulative_llm_failed", error=str(exc)[:200])

    # Apply LLM-extracted entities first so regex heuristics act strictly as fallback/gap-fillers
    if llm_extracted:
        for k, v in llm_extracted.items():
            if v not in (None, "", "null"):
                if k in ("useful_life_years", "useful_life"):
                    try:
                        merged["useful_life_years"] = int(v)
                        merged["useful_life"] = int(v)
                    except (ValueError, TypeError):
                        pass
                else:
                    merged[k] = v

    # 3. Deterministic extraction & corrections ONLY for gaps not explicitly authored by LLM
    if raw_reply:
        corr = extract_conversational_corrections(raw_reply, merged)
        if corr:
            for ck, cv in corr.items():
                if ck not in llm_extracted or llm_extracted.get(ck) in (None, "", "null"):
                    merged[ck] = cv

        sched = expand_standard_schedule_answers(raw_reply, merged)
        if sched:
            for sk, sv in sched.items():
                if sk not in llm_extracted or llm_extracted.get(sk) in (None, "", "null"):
                    merged[sk] = sv

    # 4. Grounded Field Safeguards (fallback when LLM didn't emit explicit fields)
    text_to_scan = f"{raw_reply} {user_req}".strip()
    scan_up = text_to_scan.upper()
    if "bank_name" not in llm_extracted:
        for b_kw in ("MEEZAN", "HBL", "MCB", "UBL", "ALFALAH", "ALLIED", "STANDARD CHARTERED", "ASKARI", "FAYSAL", "SONERI", "BANK ISLAMI"):
            if b_kw in scan_up:
                merged["bank_name"] = b_kw.title()
                if "payment_method" not in llm_extracted:
                    merged["payment_method"] = "BANK"
                    merged["payment_type"] = "BANK"
                break
    if "CASH" in scan_up and not merged.get("payment_method"):
        merged.setdefault("payment_method", "CASH")
        merged.setdefault("payment_type", "CASH")
    elif any(k in scan_up for k in ("CREDIT", "LATER", "PAYABLE", "ON CREDIT")) and not merged.get("payment_method"):
        merged["payment_method"] = "CREDIT"
        merged["payment_type"] = "CREDIT"
    if merged.get("payment_method") and not merged.get("payment_type"):
        merged["payment_type"] = merged["payment_method"]

    # Date parsing check
    if raw_reply and "transaction_date" not in llm_extracted:
        dt_res = parse_transaction_date(raw_reply)
        if dt_res.ok:
            merged["transaction_date"] = dt_res.iso_date
            merged["expense_date"] = dt_res.iso_date
    elif not merged.get("transaction_date"):
        dt_res = parse_transaction_date(user_req)
        if dt_res.ok:
            merged["transaction_date"] = dt_res.iso_date
            merged["expense_date"] = dt_res.iso_date

    # Useful life integer fallback
    m_life = re.search(r"\b(\d+)\s*(?:years?|yrs?|saal)\b", text_to_scan, re.IGNORECASE)
    if m_life and not merged.get("useful_life_years"):
        merged["useful_life_years"] = int(m_life.group(1))
        merged["useful_life"] = int(m_life.group(1))

    # WHT Exemption Certificate check
    if not merged.get("wht_status") and any(k in text_to_scan.lower() for k in ("exemption certificate", "certificate provided", "exempt", "has certificate", "0% wht", "zero tax", "no deduction")):
        merged["wht_status"] = "EXEMPT"
        merged["wht_decision"] = "EXEMPT"
        merged["wht_exempt"] = True
        merged["wht_rate_percent"] = 0.0

    # Reversal / Undo detection (Phase 4B)
    if any(k in text_to_scan.lower() for k in ("reverse", "reversal", "undo", "void journal", "cancel journal", "cancel entry")):
        merged["is_reversal"] = True
        merged["intent"] = "reverse_journal"
        llm_resolved_intent = llm_resolved_intent or "reverse_journal"
        m_jv = re.search(r"\b(JV-\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", text_to_scan, re.IGNORECASE)
        if m_jv:
            merged["journal_number"] = m_jv.group(1).upper()
            merged["entry_id"] = m_jv.group(1)

    # Multi-item split allocation (Phase 4A)
    if any(k in comb_text.lower() for k in (":", " and bought ", " and paid ", " and rent ", " and software ", " and laptops ", " and electricity ")) and not merged.get("line_items"):
        try:
            from app.multi_item_disaggregator import disaggregate_conversational_items
            disagg = await disaggregate_conversational_items(comb_text, entities=merged, client=client, timeout=timeout)
            if disagg.is_composite and disagg.line_items:
                merged["line_items"] = [item.to_dict() for item in disagg.line_items]
                merged["total_amount"] = disagg.total_amount
                merged["amount"] = disagg.total_amount
                if disagg.payment_method:
                    merged["payment_method"] = disagg.payment_method
                if disagg.bank_name:
                    merged["bank_name"] = disagg.bank_name
        except Exception as exc:
            log.warning("conversational_manager.disaggregate_failed", error=str(exc)[:200])

    # Explicit diversion triggers when user pivots workflow or requests lookup in free text
    if not llm_next_action and raw_reply:
        _pivot_cues = (
            "instead make", "actually make", "switch to", "change to purchase order",
            "create a purchase order", "make it a bill", "check balance", "show balance",
            "check our", "show our", "trial balance", "profit and loss", "balance sheet",
            "skip the ", "remove the ", "only record", "split between", "split it",
        )
        if any(cue in raw_low for cue in _pivot_cues):
            llm_next_action = "DIVERT"
            llm_diversion_reason = "User requested a workflow or scope change."

    return {
        "entities": merged,
        "llm_keys": sorted(llm_extracted.keys()),
        "reasoning": llm_reasoning,
        "next_action": llm_next_action or "PROCEED",
        "resolved_intent": llm_resolved_intent or merged.get("intent"),
        "diversion_reason": llm_diversion_reason,
        "is_complete": not any(merged.get(f) in (None, "", []) for f in (missing_fields or [])),
    }

