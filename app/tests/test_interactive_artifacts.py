"""Unit & Hermetic Tests for Interactive In-Chat Artifacts & Bidirectional Visual Drafts.

Verifies:
1. Interactive Voucher Artifact Schema (Account pills, depreciation slider, WHT toggle, buttons).
2. Bidirectional Synchronization & Rebalancing (apply_artifact_action).
3. Zero-loss double-entry debit == credit accounting invariant across all actions.
"""

import pytest
from app.living_draft import (
    LivingDraft,
    VoucherLinePreview,
    DepreciationSchedulePreview,
    build_living_draft,
)
from app.interactive_artifacts import (
    AccountOption,
    SliderConfig,
    ToggleConfig,
    ActionButton,
    InteractiveControl,
    ArtifactPayload,
    ArtifactAction,
    build_interactive_artifact,
    apply_artifact_action,
)


@pytest.fixture
def sample_fixed_asset_draft() -> LivingDraft:
    """Fixture creating a standard 300,000 PKR laptop capitalization draft."""
    entities = {
        "amount": 300000.0,
        "payment_method": "bank_transfer",
        "bank_name": "Meezan Bank",
        "supplier_name": "Dell Technologies",
        "description": "2 Dell XPS Laptops",
        "transaction_nature": "FIXED_ASSET",
        "useful_life_years": 3,
        "depreciation_method": "STRAIGHT_LINE",
        "salvage_value": 0.0,
    }
    return build_living_draft(
        intent="record_purchase",
        entities=entities,
        missing_fields=[],
    )


def test_build_interactive_artifact_structure(sample_fixed_asset_draft: LivingDraft):
    """Verify artifact payload constructs all controls with active state."""
    artifact = build_interactive_artifact(sample_fixed_asset_draft)

    assert isinstance(artifact, ArtifactPayload)
    assert artifact.artifact_type == "interactive_voucher"
    assert len(artifact.controls) == 4

    ctrl_ids = [c.control_id for c in artifact.controls]
    assert "account_pill_selector" in ctrl_ids
    assert "depreciation_slider" in ctrl_ids
    assert "wht_toggle" in ctrl_ids
    assert "action_button_group" in ctrl_ids

    # 1. Account pills
    pill_ctrl = next(c for c in artifact.controls if c.control_id == "account_pill_selector")
    assert pill_ctrl.account_pills is not None
    assert any(p.account_code == "1510" and p.is_selected for p in pill_ctrl.account_pills)

    # 2. Depreciation slider
    slider_ctrl = next(c for c in artifact.controls if c.control_id == "depreciation_slider")
    assert slider_ctrl.slider is not None
    assert slider_ctrl.slider.current_value == 3
    assert 3 in slider_ctrl.slider.live_calculated_values
    assert slider_ctrl.slider.live_calculated_values[3]["annual"] == 100000.0
    assert slider_ctrl.slider.live_calculated_values[3]["monthly"] == 8333.33

    # 3. WHT toggle
    toggle_ctrl = next(c for c in artifact.controls if c.control_id == "wht_toggle")
    assert toggle_ctrl.toggle is not None
    assert toggle_ctrl.toggle.is_enabled is False
    assert toggle_ctrl.toggle.gross_amount == 300000.0

    # 4. Action buttons
    btn_ctrl = next(c for c in artifact.controls if c.control_id == "action_button_group")
    assert btn_ctrl.buttons is not None
    btn_ids = [b.action_id for b in btn_ctrl.buttons]
    assert "post_to_ledger" in btn_ids
    assert "modify_terms" in btn_ids
    assert "run_scenario" in btn_ids


def test_apply_action_switch_asset_to_expense(sample_fixed_asset_draft: LivingDraft):
    """Verify selecting an Operating Expense pill removes depreciation and updates voucher."""
    mutated = apply_artifact_action(
        sample_fixed_asset_draft,
        action_type="select_account",
        action_payload={"account_code": "5100", "account_name": "5100 - General Operating Expenses"},
    )

    # Debit line updated to expense
    assert "5100" in mutated.voucher_preview[0].account_name
    assert mutated.voucher_preview[0].debit == 300000.0

    # Depreciation schedule removed
    assert mutated.depreciation_schedule is None

    # Document type updated
    assert "Expense" in mutated.document_type

    # Double entry balance
    tot_debit = sum(line.debit for line in mutated.voucher_preview)
    tot_credit = sum(line.credit for line in mutated.voucher_preview)
    assert tot_debit == tot_credit == 300000.0


def test_apply_action_switch_expense_to_asset():
    """Verify switching from an expense head to a fixed asset initializes depreciation."""
    entities = {
        "amount": 200000.0,
        "payment_method": "bank_transfer",
        "description": "Executive Desk Set",
        "transaction_nature": "OPERATING_EXPENSE",
    }
    expense_draft = build_living_draft(
        intent="record_expense",
        entities=entities,
        missing_fields=[],
    )
    assert expense_draft.depreciation_schedule is None

    mutated = apply_artifact_action(
        expense_draft,
        action_type="select_account",
        action_payload={"account_code": "1520", "account_name": "1520 - Furniture & Fixtures"},
    )

    # Debit line updated to 1520
    assert "1520" in mutated.voucher_preview[0].account_name
    assert "Capitalization" in mutated.voucher_preview[0].description

    # Depreciation schedule initialized with 5-year default for furniture
    assert mutated.depreciation_schedule is not None
    assert mutated.depreciation_schedule.useful_life_years == 5
    assert mutated.depreciation_schedule.annual_depreciation == 40000.0
    assert mutated.depreciation_schedule.monthly_depreciation == 3333.33

    # Document type updated
    assert "Fixed Asset" in mutated.document_type


def test_apply_action_adjust_depreciation_slider(sample_fixed_asset_draft: LivingDraft):
    """Verify adjusting the slider updates useful life and recomputes monthly charge."""
    mutated = apply_artifact_action(
        sample_fixed_asset_draft,
        action_type="adjust_slider",
        action_payload={"slider_value": 5},
    )

    assert mutated.depreciation_schedule is not None
    assert mutated.depreciation_schedule.useful_life_years == 5
    # 300,000 / 5 = 60,000 annual, 5,000 monthly
    assert mutated.depreciation_schedule.annual_depreciation == 60000.0
    assert mutated.depreciation_schedule.monthly_depreciation == 5000.0

    # Compliance note updated
    assert any("5 years straight line" in n for n in mutated.compliance_notes)


def test_apply_action_toggle_wht_on_and_off(sample_fixed_asset_draft: LivingDraft):
    """Verify Section 153 WHT toggle rebalances credit lines and maintains double-entry balance."""
    # 1. Toggle ON @ 5%
    with_wht = apply_artifact_action(
        sample_fixed_asset_draft,
        action_type="toggle_wht",
        action_payload={"is_enabled": True, "rate_percent": 5.0},
    )

    # Lines: Debit Asset 300,000; Credit WHT 15,000; Credit Bank 285,000
    assert len(with_wht.voucher_preview) == 3
    debit_line = with_wht.voucher_preview[0]
    wht_line = with_wht.voucher_preview[1]
    settle_line = with_wht.voucher_preview[2]

    assert debit_line.debit == 300000.0
    assert "2120" in wht_line.account_name
    assert wht_line.credit == 15000.0
    assert settle_line.credit == 285000.0

    # Strict double-entry balance: 300,000 == 15,000 + 285,000
    tot_debit = sum(l.debit for l in with_wht.voucher_preview)
    tot_credit = sum(l.credit for l in with_wht.voucher_preview)
    assert tot_debit == tot_credit == 300000.0

    # 2. Toggle OFF
    without_wht = apply_artifact_action(
        with_wht,
        action_type="toggle_wht",
        action_payload={"is_enabled": False},
    )

    assert len(without_wht.voucher_preview) == 2
    assert not any("2120" in l.account_name for l in without_wht.voucher_preview)
    assert without_wht.voucher_preview[1].credit == 300000.0
    tot_debit_off = sum(l.debit for l in without_wht.voucher_preview)
    tot_credit_off = sum(l.credit for l in without_wht.voucher_preview)
    assert tot_debit_off == tot_credit_off == 300000.0


def test_apply_action_trigger_buttons(sample_fixed_asset_draft: LivingDraft):
    """Verify action buttons execute status changes and scenario comparisons."""
    # Post to ledger
    posted = apply_artifact_action(
        sample_fixed_asset_draft,
        action_type="trigger_button",
        action_payload={"action_id": "post_to_ledger"},
    )
    assert posted.status == "posted"
    assert any("Posted to General Ledger" in n for n in posted.compliance_notes)

    # Modify terms
    modified = apply_artifact_action(
        sample_fixed_asset_draft,
        action_type="trigger_button",
        action_payload={"action_id": "modify_terms"},
    )
    assert modified.status == "awaiting_input"
    assert "terms_revision" in modified.missing_fields

    # Run scenario
    scenario = apply_artifact_action(
        sample_fixed_asset_draft,
        action_type="trigger_button",
        action_payload={"action_id": "run_scenario"},
    )
    assert any("What-If Scenario" in n for n in scenario.compliance_notes)


def test_artifact_action_pydantic_model():
    """Verify ArtifactAction validates typed input payloads."""
    act = ArtifactAction(
        action_type="select_account",
        target_control_id="account_pill_selector",
        payload={"account_code": "1510"},
    )
    assert act.action_type == "select_account"
    assert act.payload["account_code"] == "1510"
