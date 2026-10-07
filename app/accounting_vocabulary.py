"""Canonical accounting vocabularies — SINGLE SOURCE OF TRUTH (Wave A).

Decision record: ``E:\\Qoder\\AUDIT_REPORT.md`` §3 (four-vocabulary problem)
and §7 (Wave A).

Why this module exists
----------------------
The ERP answered "what nature is this?" in three incompatible vocabularies
(semantic ``document nature``, classifier ``treatment nature``, decision
natures) plus an account-shape map that silently defaulted ANY unknown value to
an operating expense::

    _ACCOUNT_SHAPES.get(nature, _DEFAULT_SHAPE)   # ("EXPENSE", "DEBIT", "6100")

``account_shape("ASSET_DISPOSAL")`` therefore quietly produced a plausible
expense shape: the system did not know what the transaction was and confidently
posted it as an expense.

WAVE A RULE (absolute — see AUDIT_REPORT §3.1)::

    def account_shape(nature):
        try:
            return ACCOUNT_SHAPES[nature]
        except KeyError:
            raise InvalidAccountingNature(...)

**Never return a default. Reject instead.**

The two axes are deliberately kept DISTINCT — ``transaction_nature`` used to
mean all of them at once, which is how a document-nature value reached a
treatment-only code path.

Observation-only: nothing in this module feeds ``execution_plan.intent``
(Wave A does not change behavior; AUDIT_REPORT §7 / §8).
"""

from __future__ import annotations

from typing import Dict, FrozenSet, NamedTuple, Optional, Tuple

__all__ = [
    "DOCUMENT_NATURES",
    "TREATMENTS",
    "CANONICAL_INTENTS",
    "ACCOUNT_SHAPES",
    "NATURE_LEDGER_NAMES",
    "AccountShape",
    "InvalidAccountingNature",
    "account_shape",
    "is_supported_treatment",
    "is_document_nature",
    "is_canonical_intent",
    "LEGACY_TRANSACTION_NATURE_FIELD",
    "MODEL_ONLY_INTENTS",
    "EVENT_TYPE_INTENT_COVERAGE",
]


# ---------------------------------------------------------------------------
# Axis A — DOCUMENT NATURE: what kind of thing moved (semantic axis)
# ---------------------------------------------------------------------------
DOCUMENT_NATURES: FrozenSet[str] = frozenset(
    {"GOODS", "SERVICE", "ASSET_DISPOSAL", "OTHER_INCOME"}
)


# ---------------------------------------------------------------------------
# Axis B ∪ C — TREATMENT: which ledger axis a posting belongs to
# ---------------------------------------------------------------------------
# ``OTHER`` is a legal TREATMENT value (the deliberate escape hatch in
# app/llm_classification.py:101-103) but it has NO determined account shape on
# purpose: an undetermined treatment must be rejected/asked, never defaulted to
# an expense.  Same for every Axis-A value.
TREATMENTS: FrozenSet[str] = frozenset(
    {
        "INVENTORY",
        "FIXED_ASSET",
        "OPERATING_EXPENSE",
        "SERVICE",
        "CONSUMABLE",
        "PREPAYMENT",
        "DEPOSIT_ADVANCE",
        "INTANGIBLE_ASSET",
        "REVENUE",
        "LIABILITY",
        "EQUITY",
        "OTHER",
    }
)


#: The legacy single-field name (Axis A and Axis B were both written here).
#: Kept so Wave A stays observation-only; renaming the questionnaire field is a
#: Wave B change (it is pinned by the fixed-schema questionnaire test).
LEGACY_TRANSACTION_NATURE_FIELD = "transaction_nature"


class AccountShape(NamedTuple):
    """What a treatment implies for a ledger: type, normal balance, code series."""

    account_type: str
    normal_balance: str
    base_code: str
    ifrs_hint: str


class InvalidAccountingNature(ValueError):
    """Raised when a treatment has no determined account shape.

    Deterministic rejection (AUDIT_REPORT §3.1). Callers must convert this into
    a rejection/question — never into a plausible default.
    """


#: ONLY treatments with a determined shape.  Missing on purpose: ``OTHER`` and
#: every Axis-A value (GOODS / SERVICE-document / ASSET_DISPOSAL / OTHER_INCOME).
#: LIABILITY and EQUITY are also absent — inventing a numbering series for them
#: would be Python inventing accounting facts; the model must name the account
#: instead.  (Recorded as a Wave B follow-up in AUDIT_REPORT §3.2.)
ACCOUNT_SHAPES: Dict[str, AccountShape] = {
    "FIXED_ASSET": AccountShape(
        "ASSET", "DEBIT", "1500", "IFRS: property, plant and equipment"
    ),
    "INTANGIBLE_ASSET": AccountShape(
        "ASSET", "DEBIT", "1510", "IFRS: intangible assets"
    ),
    "INVENTORY": AccountShape("ASSET", "DEBIT", "1200", "IFRS: inventories"),
    "PREPAYMENT": AccountShape("ASSET", "DEBIT", "1400", "IFRS: prepayments"),
    "DEPOSIT_ADVANCE": AccountShape(
        "ASSET", "DEBIT", "1410", "IFRS: deposits and advances"
    ),
    "OPERATING_EXPENSE": AccountShape(
        "EXPENSE", "DEBIT", "6100", "IFRS: operating / administrative expenses"
    ),
    "CONSUMABLE": AccountShape(
        "EXPENSE", "DEBIT", "6190", "IFRS: consumables (operating expenses)"
    ),
    "SERVICE": AccountShape("EXPENSE", "DEBIT", "6100", "IFRS: operating expenses"),
    "REVENUE": AccountShape(
        "REVENUE", "CREDIT", "4100", "IFRS 15: revenue from contracts with customers"
    ),
    "OTHER_INCOME": AccountShape("REVENUE", "CREDIT", "4200", "IFRS: other income"),
}


#: Canonical LEDGER NAME for a nature whose standard chart entry has exactly
#: one unambiguous name.  Used when a YES account-creation approval carries no
#: parseable name (production 2026-10-07, Zameer Labs session afcfecae: the
#: model's free-form "Should I create a new inventory account?" question
#: cannot satisfy planner's ``no '<name>' account`` merge contract, so
#: "Yes, Create Inventory Account" folded nothing and the ``create_account``
#: tool was never granted).
#:
#: Deliberately PARTIAL: a nature whose ledger name depends on the ITEM's
#: category (FIXED_ASSET -> "Vehicles" vs "Furniture & Fixtures") has NO
#: canonical name and must never guess one here — the merge falls back to the
#: answer's own wording or leaves the question open instead.
NATURE_LEDGER_NAMES: Dict[str, str] = {
    "INVENTORY": "Inventory",
}


# ---------------------------------------------------------------------------
# Canonical planner intents (what a model MAY name in ``decision.intent``)
# ---------------------------------------------------------------------------
# Derived from ``planner._INTENT_PATTERNS`` + ``planner._tools_for_intent``.
# ``test_single_owner_wave_a.py`` fails if this set and the planner disagree,
# so the two can never drift apart silently.  ``unknown`` is deliberately NOT
# canonical: a non-canonical model value is recorded as MODEL_NONCANONICAL
# rather than silently accepted (AUDIT_REPORT §8 metric).
CANONICAL_INTENTS: FrozenSet[str] = frozenset(
    {
        "record_sale", "record_credit_sale", "record_cash_sale",
        "record_purchase", "record_credit_purchase", "record_cash_purchase",
        "record_expense", "record_receipt", "record_payment",
        "record_expense_payment", "record_bank_transfer",
        "create_invoice", "create_quotation", "convert_quotation",
        "create_credit_note", "create_purchase_return", "create_purchase_bill",
        "create_bank_account", "create_product", "create_service",
        # Project setup — non-financial, but it is a first-class operation
        # with its own intent, field ladder and tool (production 2026-10-01:
        # "Set up a project …" had no intent at all).
        "create_project",
        "register_fixed_asset", "dispose_fixed_asset", "record_asset_depreciation",
        "run_payroll",
        "generate_trial_balance", "generate_balance_sheet", "generate_profit_loss",
        "generate_cash_flow", "generate_general_ledger",
        "generate_customer_ledger", "generate_supplier_ledger",
        "project_profitability", "customer_balance", "supplier_balance",
        "list_expenses", "list_bank_accounts",
        # §12.8 expressibility repair — model-only, no planner routing yet
        # (see MODEL_ONLY_INTENTS; coverage for reversal/correction/adjustment).
        "reverse_journal", "record_correction", "record_adjustment",
    }
)


#: Model-expressible intents that the DETERMINISTIC planner cannot yet emit.
#:
#: Verified 2026-09-28 (AUDIT_REPORT §12.8): ``reverse_journal`` is a live
#: tool (``app/tools/__init__.py``) with **zero** hits in ``planner.py``, and
#: correction/adjustment have manual-journal operations but no intent.  These
#: are canonical so the divergence study measures the LEGACY gap instead of
#: miscounting the model's correct answer as ``MODEL_NONCANONICAL``.
#:
#: Deliberately vocabulary-only: no planner routing, no authority, no execution
#: change (Wave A freeze, ``fc01502``).  Wiring them into
#: ``planner._INTENT_PATTERNS`` / ``_tools_for_intent`` is Wave B/D work.
MODEL_ONLY_INTENTS: FrozenSet[str] = frozenset(
    {"reverse_journal", "record_correction", "record_adjustment"}
)


#: INVARIANT (AUDIT_REPORT §12.8): every ``event_type`` the reasoning contract
#: offers must have at least one canonical intent capable of representing it.
#:
#: Status per value, VERIFIED against ``planner._INTENT_PATTERNS`` + the tool
#: registry + the services — never inferred from similar names:
#:
#:   COVERED           an intent exists and routes today
#:   COVERED (class.)  event classification, not its own mutation intent
#:   MODEL-ONLY        expressible, but only the model can emit it (see above)
#:
#: ``continuation`` is deliberately ABSENT: it existed **only** in the enum —
#: no definition, tool, intent or service anywhere — so it was removed from the
#: contract rather than given invented meaning.
EVENT_TYPE_INTENT_COVERAGE: Dict[str, Tuple[str, ...]] = {
    "new_event": (
        "record_sale", "record_purchase", "record_expense", "create_invoice",
    ),
    "settlement": ("record_receipt", "record_payment", "record_expense_payment"),
    "transfer": ("record_bank_transfer",),
    "disposal": ("dispose_fixed_asset",),
    # allocation runs INSIDE the receipt/payment services (optional invoice
    # allocation), so it is expressed through the settlement intents.
    "allocation": ("record_receipt", "record_payment"),
    "report": ("generate_trial_balance", "generate_general_ledger", "list_expenses"),
    # model-only until planner routing lands (Wave B/D)
    "reversal": ("reverse_journal",),
    "correction": ("record_correction", "reverse_journal"),
    "adjustment": ("record_adjustment",),
}


def account_shape(nature: Optional[str]) -> AccountShape:
    """Shape for *nature* — or ``InvalidAccountingNature``.  No default, ever."""
    key = str(nature or "").strip().upper()
    try:
        return ACCOUNT_SHAPES[key]
    except KeyError:
        raise InvalidAccountingNature(
            f"Unsupported accounting treatment: {nature!r}. It has no determined "
            "account shape, so no ledger can be inferred — ask which account "
            "applies instead of defaulting to an expense."
        ) from None


def is_supported_treatment(nature: Optional[str]) -> bool:
    """True only when *nature* has a determined shape (i.e. may be posted)."""
    return str(nature or "").strip().upper() in ACCOUNT_SHAPES


def is_document_nature(value: Optional[str]) -> bool:
    return str(value or "").strip().upper() in DOCUMENT_NATURES


def is_canonical_intent(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in CANONICAL_INTENTS

