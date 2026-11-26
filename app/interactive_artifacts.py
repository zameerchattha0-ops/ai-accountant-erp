"""Interactive In-Chat Artifacts & Bidirectional Visual Drafts.

Supports Frontier Recommendation 1:
1. Interactive Voucher Artifact Schema:
   - Tappable account pills (suggesting alternative COA heads, e.g. 1510 IT vs 1520 Furniture vs 5100 Opex).
   - Depreciation life slider configuration (3 to 10 years, reactive monthly depreciation formula).
   - Statutory WHT toggle switch (Section 153 5% goods / 4% services on/off with immediate credit recalculation).
   - Action buttons: "Post to Ledger", "Modify Terms", "Run Scenario".
2. Bidirectional Synchronization:
   - `apply_artifact_action(current_draft, action_type, action_payload)` deterministically mutates
     and rebalances the double-entry voucher when an artifact control is interacted with.
   - Pydantic v2 models for `ArtifactAction`, `InteractiveControl`, `ArtifactPayload`.
3. Quality Standards:
   - Modern, elegant Python 3.12+, fully typed, zero AI slop, no database dependencies.
   - Hermetic and self-contained double-entry balance guarantees.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Literal, Optional, Sequence, Union
from pydantic import BaseModel, Field, model_validator

from app.living_draft import (
    LivingDraft,
    VoucherLinePreview,
    DepreciationSchedulePreview,
    LivingDraftCounterparty,
    LivingDraftLineItem,
)

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pre-defined Chart of Account Candidates for Tappable Pills
# ---------------------------------------------------------------------------

DEFAULT_COA_PILLS: List[Dict[str, str]] = [
    {
        "account_code": "1510",
        "account_name": "1510 - Computer & IT Equipment",
        "category": "Fixed Asset",
        "description": "Laptops, servers, workstations, network hardware (IAS 16)",
    },
    {
        "account_code": "1520",
        "account_name": "1520 - Furniture & Fixtures",
        "category": "Fixed Asset",
        "description": "Office chairs, conference tables, executive desks (IAS 16)",
    },
    {
        "account_code": "1530",
        "account_name": "1530 - Motor Vehicles",
        "category": "Fixed Asset",
        "description": "Delivery vans, company automobiles, motorcycles (IAS 16)",
    },
    {
        "account_code": "5100",
        "account_name": "5100 - General Operating Expenses",
        "category": "Operating Expense",
        "description": "Immediate P&L expense write-off (IAS 1)",
    },
    {
        "account_code": "5200",
        "account_name": "5200 - Utilities & Internet Expense",
        "category": "Operating Expense",
        "description": "Electricity, fiber internet, phone bills",
    },
    {
        "account_code": "1200",
        "account_name": "1200 - Merchandise Inventory",
        "category": "Inventory",
        "description": "Goods held for resale (IAS 2)",
    },
]


# ---------------------------------------------------------------------------
# Pydantic v2 Artifact Models
# ---------------------------------------------------------------------------

class AccountOption(BaseModel):
    """Tappable account pill representation for chart-of-accounts selection."""

    account_code: str
    account_name: str
    category: str  # "Fixed Asset" | "Operating Expense" | "Inventory" | "Other"
    description: Optional[str] = None
    is_selected: bool = False


class SliderConfig(BaseModel):
    """Depreciation life slider with reactive pre-calculated schedule points."""

    control_id: str = "depreciation_slider"
    min_value: int = 1
    max_value: int = 10
    step: int = 1
    current_value: int = 3
    unit: str = "years"
    reactive_target: str = "monthly_depreciation"
    formula_hint: str = "Monthly = (Cost - Salvage) / (Years * 12)"
    live_calculated_values: Dict[int, Dict[str, float]] = Field(default_factory=dict)


class ToggleConfig(BaseModel):
    """Statutory Withholding Tax (Section 153) toggle switch with immediate rebalancing."""

    control_id: str = "wht_toggle"
    is_enabled: bool = False
    label: str = "Deduct Section 153 Withholding Tax (WHT)"
    statutory_section: str = "Section 153, Income Tax Ordinance 2001"
    rate_percent: float = 5.0
    applicable_category: str = "GOODS"  # GOODS (5%) | IT_SERVICES (4%) | GENERAL_SERVICES (9%/14%)
    gross_amount: float = 0.0
    wht_deduction_amount: float = 0.0
    net_payable_amount: float = 0.0
    withholding_account_head: str = "2120 - Withholding Tax Payable (u/s 153)"


class ActionButton(BaseModel):
    """Action button rendered on the interactive voucher artifact."""

    action_id: str  # "post_to_ledger" | "modify_terms" | "run_scenario"
    label: str
    variant: Literal["primary", "secondary", "outline", "danger"] = "primary"
    enabled: bool = True
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None


class InteractiveControl(BaseModel):
    """Container for interactive controls attached to a voucher artifact."""

    control_id: str
    control_type: Literal[
        "account_pill_selector",
        "depreciation_slider",
        "wht_toggle",
        "action_button_group",
    ]
    label: str
    help_text: Optional[str] = None
    account_pills: Optional[List[AccountOption]] = None
    slider: Optional[SliderConfig] = None
    toggle: Optional[ToggleConfig] = None
    buttons: Optional[List[ActionButton]] = None


class ArtifactPayload(BaseModel):
    """Complete interactive in-chat artifact payload for UI sidebar/preview pane."""

    artifact_id: str = Field(default_factory=lambda: f"art_{uuid.uuid4().hex[:12]}")
    artifact_type: str = "interactive_voucher"
    title: str = "Interactive Journal Voucher"
    version: int = 1
    controls: List[InteractiveControl] = Field(default_factory=list)
    recalculation_summary: Dict[str, Any] = Field(default_factory=dict)


class ArtifactAction(BaseModel):
    """User interaction event received from the frontend artifact."""

    action_type: Literal[
        "select_account",
        "adjust_slider",
        "toggle_wht",
        "trigger_button",
    ]
    target_control_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Control Builders
# ---------------------------------------------------------------------------

def _build_account_pills(draft: LivingDraft) -> InteractiveControl:
    """Construct tappable account pills matching the current draft state."""
    current_account = ""
    if draft.voucher_preview:
        current_account = draft.voucher_preview[0].account_name

    pills: List[AccountOption] = []
    for candidate in DEFAULT_COA_PILLS:
        is_sel = (
            candidate["account_code"] in current_account
            or candidate["account_name"].lower() in current_account.lower()
        )
        pills.append(AccountOption(
            account_code=candidate["account_code"],
            account_name=candidate["account_name"],
            category=candidate["category"],
            description=candidate.get("description"),
            is_selected=is_sel,
        ))

    # If currently selected is not in defaults, prepend it
    if current_account and not any(p.is_selected for p in pills):
        code_part = current_account.split("-")[0].strip() if "-" in current_account else "Custom"
        pills.insert(0, AccountOption(
            account_code=code_part,
            account_name=current_account,
            category="Custom Head",
            description="Active voucher debit head",
            is_selected=True,
        ))

    return InteractiveControl(
        control_id="account_pill_selector",
        control_type="account_pill_selector",
        label="Account Classification (COA Head)",
        help_text="Tap to change the debit ledger head. Switching between Asset and Expense dynamically updates depreciation.",
        account_pills=pills,
    )


def _build_depreciation_slider(draft: LivingDraft) -> Optional[InteractiveControl]:
    """Construct reactive useful life slider (3 to 10 years) for fixed assets."""
    is_asset = "Asset" in draft.document_type or draft.depreciation_schedule is not None
    if not is_asset:
        return None

    cost = (
        draft.depreciation_schedule.cost
        if draft.depreciation_schedule and getattr(draft.depreciation_schedule, "cost", None)
        else (draft.total_amount or 0.0)
    )
    salvage = draft.depreciation_schedule.salvage_value if draft.depreciation_schedule else 0.0
    depreciable = max(0.0, cost - salvage)

    current_val = 3
    if draft.depreciation_schedule and draft.depreciation_schedule.useful_life_years:
        current_val = min(10, max(1, draft.depreciation_schedule.useful_life_years))

    # Precalculate reactive points for 1..10 years so client-side scrubbing has 0ms latency
    points: Dict[int, Dict[str, float]] = {}
    for yr in range(1, 11):
        ann = round(depreciable / yr, 2)
        mon = round(ann / 12.0, 2)
        points[yr] = {"annual": ann, "monthly": mon}

    slider = SliderConfig(
        control_id="depreciation_slider",
        min_value=1,
        max_value=10,
        step=1,
        current_value=current_val,
        unit="years",
        live_calculated_values=points,
    )

    return InteractiveControl(
        control_id="depreciation_slider",
        control_type="depreciation_slider",
        label="IAS 16 Useful Life & Depreciation Schedule",
        help_text="Adjust useful life slider to reactively preview monthly and annual straight-line depreciation charges.",
        slider=slider,
    )


def _build_wht_toggle(draft: LivingDraft) -> InteractiveControl:
    """Construct Section 153 Withholding Tax toggle switch."""
    gross = draft.total_amount or 0.0

    # Determine default rate by item/nature
    rate = 5.0  # default goods
    category = "GOODS"
    desc_low = " ".join(
        [draft.document_type]
        + [itm.description for itm in draft.line_items]
        + [note for note in draft.compliance_notes]
    ).lower()

    if any(k in desc_low for k in ("it ", "software", "license", "cloud", "developer", "tech")):
        rate = 4.0
        category = "IT_SERVICES"
    elif any(k in desc_low for k in ("service", "consulting", "audit", "legal", "maintenance")):
        rate = 9.0
        category = "GENERAL_SERVICES"

    # Check if WHT is already present in voucher lines
    has_wht = any("2120" in line.account_name or "Withholding" in line.account_name for line in draft.voucher_preview)
    wht_amt = round(gross * (rate / 100.0), 2) if has_wht else 0.0
    net_amt = round(gross - wht_amt, 2)

    toggle = ToggleConfig(
        control_id="wht_toggle",
        is_enabled=has_wht,
        label=f"Deduct Section 153 WHT ({rate}% - {category})",
        statutory_section="Section 153(1), Income Tax Ordinance 2001",
        rate_percent=rate,
        applicable_category=category,
        gross_amount=gross,
        wht_deduction_amount=wht_amt,
        net_payable_amount=net_amt,
    )

    return InteractiveControl(
        control_id="wht_toggle",
        control_type="wht_toggle",
        label="Statutory Tax Deduction (Section 153)",
        help_text="Toggle on to withhold tax at source. Rebalances credit lines to WHT Payable and Net Settlement.",
        toggle=toggle,
    )


def _build_action_buttons(draft: LivingDraft) -> InteractiveControl:
    """Construct action buttons: Post to Ledger, Modify Terms, Run Scenario."""
    can_post = draft.status in ("ready_for_confirmation", "drafting", "awaiting_input") and (draft.total_amount or 0) > 0

    buttons: List[ActionButton] = [
        ActionButton(
            action_id="post_to_ledger",
            label="Post to Ledger",
            variant="primary",
            enabled=can_post,
            requires_confirmation=True,
            confirmation_message="Are you sure you want to commit this journal voucher to the General Ledger?",
        ),
        ActionButton(
            action_id="modify_terms",
            label="Modify Terms",
            variant="secondary",
            enabled=True,
        ),
        ActionButton(
            action_id="run_scenario",
            label="Run What-If Scenario",
            variant="outline",
            enabled=True,
        ),
    ]

    return InteractiveControl(
        control_id="action_button_group",
        control_type="action_button_group",
        label="Voucher Actions",
        help_text="Commit transaction directly or test financial scenarios.",
        buttons=buttons,
    )


def build_interactive_artifact(draft: LivingDraft) -> ArtifactPayload:
    """Construct an interactive in-chat artifact payload from a LivingDraft."""
    controls: List[InteractiveControl] = []

    # 1. Tappable account pills
    controls.append(_build_account_pills(draft))

    # 2. Depreciation slider (if asset)
    slider_ctrl = _build_depreciation_slider(draft)
    if slider_ctrl:
        controls.append(slider_ctrl)

    # 3. Section 153 WHT toggle
    controls.append(_build_wht_toggle(draft))

    # 4. Action buttons
    controls.append(_build_action_buttons(draft))

    # Recalculation summary
    summary: Dict[str, Any] = {
        "total_amount": draft.total_amount,
        "currency": draft.currency,
        "debit_total": sum(line.debit for line in draft.voucher_preview),
        "credit_total": sum(line.credit for line in draft.voucher_preview),
        "is_balanced": abs(
            sum(line.debit for line in draft.voucher_preview)
            - sum(line.credit for line in draft.voucher_preview)
        ) < 0.01,
        "has_depreciation": draft.depreciation_schedule is not None,
    }

    return ArtifactPayload(
        title=f"Interactive Voucher — {draft.document_type}",
        controls=controls,
        recalculation_summary=summary,
    )


# ---------------------------------------------------------------------------
# Bidirectional Synchronization & Rebalancing
# ---------------------------------------------------------------------------

def apply_artifact_action(
    current_draft: LivingDraft,
    action_type: str,
    action_payload: Optional[Dict[str, Any]] = None,
) -> LivingDraft:
    """Deterministically mutate and rebalance the LivingDraft in response to user interaction.

    Guarantees:
    - Pure, deterministic function without database calls.
    - Double-entry debit == credit invariant maintained at all times.
    - Reactive updates to depreciation schedules, tax liabilities, and compliance notes.
    """
    payload = dict(action_payload or {})
    mutated = current_draft.model_copy(deep=True)
    gross_total = float(mutated.total_amount or 0.0)

    # -----------------------------------------------------------------------
    # ACTION 1: SELECT ACCOUNT (Tappable Pill)
    # -----------------------------------------------------------------------
    if action_type == "select_account":
        target_account = str(payload.get("account_name") or payload.get("account_code") or "").strip()
        if not target_account:
            return mutated

        # Match to candidate if code only
        for cand in DEFAULT_COA_PILLS:
            if target_account == cand["account_code"]:
                target_account = cand["account_name"]
                break

        is_becoming_asset = any(k in target_account for k in ("1510", "1520", "1530", "Fixed Asset", "Equipment", "Furniture"))
        is_becoming_expense = any(k in target_account for k in ("5100", "5200", "5300", "Expense"))

        # Update primary debit voucher line
        if mutated.voucher_preview:
            mutated.voucher_preview[0].account_name = target_account
            if is_becoming_asset:
                mutated.voucher_preview[0].description = f"Capitalization: {mutated.voucher_preview[0].description or 'Asset'}"
            elif is_becoming_expense:
                mutated.voucher_preview[0].description = f"Expense: {mutated.voucher_preview[0].description or 'Operating expense'}"

        # Update line items
        if mutated.line_items:
            mutated.line_items[0].account_name = target_account

        # If switching Asset -> Expense: remove depreciation schedule, update document type
        if is_becoming_expense:
            mutated.depreciation_schedule = None
            channel = mutated.payment_channel or "cash"
            mutated.document_type = (
                "Cash Payment Voucher (Operating Expense)" if channel == "cash"
                else ("Bank Payment Voucher (Operating Expense)" if channel in ("bank_transfer", "bank")
                else "Expense Voucher")
            )
            # Remove asset notes and add expense notes
            mutated.compliance_notes = [
                n for n in mutated.compliance_notes
                if "IAS 16" not in n and "capital asset" not in n
            ]
            mutated.compliance_notes.append("ℹ️ IAS 1 Operating Expense: Immediate P&L recognition.")

        # If switching Expense -> Asset: initialize standard depreciation schedule
        elif is_becoming_asset:
            channel = mutated.payment_channel or "bank_transfer"
            mutated.document_type = (
                "Bank Payment Voucher (Fixed Asset Capitalization)" if channel in ("bank_transfer", "bank")
                else ("Cash Payment Voucher (Fixed Asset Capitalization)" if channel == "cash"
                else "Fixed Asset Capitalization Voucher")
            )
            # Determine standard life: 3 yrs for IT (1510), 5 yrs for Furniture (1520) / Vehicles (1530)
            life = 3 if "1510" in target_account else 5
            ann_dep = round(gross_total / life, 2) if gross_total > 0 else 0.0
            mon_dep = round(ann_dep / 12.0, 2)
            mutated.depreciation_schedule = DepreciationSchedulePreview(
                useful_life_years=life,
                method="STRAIGHT_LINE",
                cost=gross_total,
                salvage_value=0.0,
                depreciable_amount=gross_total,
                annual_depreciation=ann_dep,
                monthly_depreciation=mon_dep,
            )
            mutated.compliance_notes = [
                n for n in mutated.compliance_notes if "Operating Expense" not in n
            ]
            mutated.compliance_notes.append("ℹ️ IAS 16 Capitalization: Multi-year useful life recognized.")

    # -----------------------------------------------------------------------
    # ACTION 2: ADJUST SLIDER (Useful Life)
    # -----------------------------------------------------------------------
    elif action_type in ("adjust_slider", "change_depreciation_life"):
        raw_val = payload.get("useful_life_years") or payload.get("slider_value") or payload.get("years")
        if raw_val is not None:
            try:
                new_years = max(1, min(25, int(raw_val)))
            except (ValueError, TypeError):
                new_years = 3

            salvage = mutated.depreciation_schedule.salvage_value if mutated.depreciation_schedule else 0.0
            method = mutated.depreciation_schedule.method if mutated.depreciation_schedule else "STRAIGHT_LINE"
            depreciable = max(0.0, gross_total - salvage)
            ann_dep = round(depreciable / new_years, 2)
            mon_dep = round(ann_dep / 12.0, 2)

            mutated.depreciation_schedule = DepreciationSchedulePreview(
                useful_life_years=new_years,
                method=method,
                cost=gross_total,
                salvage_value=salvage,
                depreciable_amount=depreciable,
                annual_depreciation=ann_dep,
                monthly_depreciation=mon_dep,
            )

            # Update compliance notes with schedule change
            mutated.compliance_notes = [
                n for n in mutated.compliance_notes if "Schedule adjusted" not in n
            ]
            mutated.compliance_notes.append(
                f"✓ Depreciation Schedule updated: {new_years} years straight line (PKR {mon_dep:,.2f}/month)."
            )

    # -----------------------------------------------------------------------
    # ACTION 3: TOGGLE WHT (Section 153 Withholding Tax)
    # -----------------------------------------------------------------------
    elif action_type == "toggle_wht":
        is_enabled = bool(payload.get("is_enabled", payload.get("enabled", False)))
        rate = float(payload.get("rate_percent") or 5.0)

        # Clear existing WHT lines and settlement lines
        wht_account = "2120 - Withholding Tax Payable (u/s 153)"
        non_wht_lines = [
            line for line in mutated.voucher_preview
            if "2120" not in line.account_name and "Withholding" not in line.account_name
        ]

        if not non_wht_lines and gross_total > 0:
            non_wht_lines = [
                VoucherLinePreview(
                    account_name="1510 - Computer & IT Equipment",
                    debit=gross_total,
                    credit=0.0,
                    description="Voucher line item",
                )
            ]

        # Primary debit line (cost)
        debit_line = non_wht_lines[0]
        debit_line.debit = gross_total
        debit_line.credit = 0.0

        # Settlement Account Name
        channel = mutated.payment_channel or "cash"
        bank = mutated.bank_name
        if channel == "cash":
            settlement_acc = "1000 - Cash on Hand"
        elif channel in ("bank_transfer", "cheque"):
            settlement_acc = f"1010 - {bank or 'Bank Account'} (Current)"
        elif channel == "credit":
            c_name = mutated.counterparty.name if mutated.counterparty else "Supplier"
            settlement_acc = f"2000 - Accounts Payable ({c_name})"
        else:
            settlement_acc = "Settlement Clearing Account"

        if is_enabled and gross_total > 0:
            wht_deduction = round(gross_total * (rate / 100.0), 2)
            net_payable = round(gross_total - wht_deduction, 2)

            mutated.voucher_preview = [
                debit_line,
                VoucherLinePreview(
                    account_name=wht_account,
                    account_code="2120",
                    debit=0.0,
                    credit=wht_deduction,
                    description=f"WHT deduction u/s 153 @ {rate}%",
                ),
                VoucherLinePreview(
                    account_name=settlement_acc,
                    debit=0.0,
                    credit=net_payable,
                    description=f"Net payment via {channel}",
                ),
            ]
            mutated.compliance_notes = [
                n for n in mutated.compliance_notes if "Section 153 WHT" not in n
            ]
            mutated.compliance_notes.append(
                f"✓ Section 153 WHT applied @ {rate}%: PKR {wht_deduction:,.2f} withheld; Net payable: PKR {net_payable:,.2f}."
            )
        else:
            # Full gross settlement
            mutated.voucher_preview = [
                debit_line,
                VoucherLinePreview(
                    account_name=settlement_acc,
                    debit=0.0,
                    credit=gross_total,
                    description=f"Settlement in full via {channel}",
                ),
            ]
            mutated.compliance_notes = [
                n for n in mutated.compliance_notes if "Section 153 WHT applied" not in n
            ]

    # -----------------------------------------------------------------------
    # ACTION 4: TRIGGER BUTTON (Post to Ledger / Modify Terms / Scenario)
    # -----------------------------------------------------------------------
    elif action_type == "trigger_button":
        btn_id = str(payload.get("action_id") or payload.get("button_id") or "").strip()

        if btn_id == "post_to_ledger":
            mutated.status = "posted"
            mutated.compliance_notes = [
                n for n in mutated.compliance_notes if "Posted to General Ledger" not in n
            ]
            mutated.compliance_notes.append("✓ Status: Posted to General Ledger and journalized.")

        elif btn_id == "modify_terms":
            mutated.status = "awaiting_input"
            mutated.missing_fields = ["terms_revision"]

        elif btn_id == "run_scenario":
            # Append scenario comparison note
            if mutated.depreciation_schedule:
                curr_life = mutated.depreciation_schedule.useful_life_years
                alt_life = 5 if curr_life == 3 else 3
                alt_mon = round(gross_total / alt_life / 12.0, 2)
                curr_mon = mutated.depreciation_schedule.monthly_depreciation
                diff = round(curr_mon - alt_mon, 2)
                mutated.compliance_notes.append(
                    f"📊 What-If Scenario: At {alt_life} years, monthly charge would be PKR {alt_mon:,.2f} "
                    f"({'saving' if diff > 0 else 'increasing'} PKR {abs(diff):,.2f}/mo vs current {curr_life}-year plan)."
                )

    # Re-attach freshly built artifact
    try:
        artifact = build_interactive_artifact(mutated)
        if hasattr(mutated, "interactive_artifact"):
            mutated.interactive_artifact = artifact.model_dump()
    except Exception as exc:
        log.warning("interactive_artifacts.sync_failed", error=str(exc)[:160])

    return mutated
