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

        if category == "IT_EQUIPMENT":
            q_text = (
                f"For IT equipment like **{item_desc}**, standard accounting policy under IAS 16 recommends a "
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
    }
    ents = dict(entities or {})
    low_msg = (user_message or "").lower()

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
                amt = 150000.0  # sensible baseline simulation amount
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

