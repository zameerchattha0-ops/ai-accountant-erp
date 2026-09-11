"""
ERP AI Agent — Intelligent Transaction Classifier
===================================================
Deterministically classifies the ECONOMIC NATURE of a transaction BEFORE
accounting execution, following the authority hierarchy:

    1. USER_ANSWER          — an explicit answer to a classification question
    2. ERP_CONFIGURATION    — products/services/item mappings in the database
    3. ITEM_MAPPING         — a uniquely matching Chart-of-Accounts account
    4. DETERMINISTIC_RULE   — keyword/business rules (utilities, resale, …)
    5. INFERENCE            — LOW confidence; if the ambiguity is MATERIAL
                              (e.g. laptop: fixed asset vs expense) the agent
                              must ASK instead of guessing.

The classifier NEVER picks accounts for the journal — it only proposes an
account HINT that the Accounting Engine validates before use.  The LLM
receives the classification as authoritative context; the Accounting
Engine + Validator remain the execution authority.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.models.schemas import TransactionClassification

log = structlog.get_logger(__name__)

# Canonical natures
INVENTORY = "INVENTORY"
FIXED_ASSET = "FIXED_ASSET"
OPERATING_EXPENSE = "OPERATING_EXPENSE"
SERVICE = "SERVICE"
CONSUMABLE = "CONSUMABLE"
PREPAYMENT = "PREPAYMENT"
DEPOSIT_ADVANCE = "DEPOSIT_ADVANCE"
INTANGIBLE_ASSET = "INTANGIBLE_ASSET"
OTHER = "OTHER"

NATURES = {
    INVENTORY, FIXED_ASSET, OPERATING_EXPENSE, SERVICE, CONSUMABLE,
    PREPAYMENT, DEPOSIT_ADVANCE, INTANGIBLE_ASSET, OTHER,
}

# Unambiguous operating expenses: never ask asset-vs-expense.
_EXPENSE_RULES = [
    ("electricity|electric bill|power bill|utility|utilities|water bill|gas bill",
     "Utilities expense"),
    ("rent", "Rent expense"),
    ("salary|salaries|wages|payroll", "Salaries & wages"),
    ("internet|phone bill|telecom|mobile bill", "Communication expense"),
    ("fuel|petrol|diesel|transport|travel|flight|hotel", "Travel & transport"),
    ("insurance", "Insurance expense"),
    ("bank charge|bank fee|service charge", "Bank charges"),
    # "advertising" is deliberately covered: a named advertising/marketing
    # classification must NEVER silently fall through to the first/default
    # expense account (live defect: "Facebook advertising campaign" was
    # debited to 6140 Utilities Expense).
    ("marketing|advertis|advertisment|ad spend|ad campaign",
     "Marketing & advertising expense"),
]

# Consumables — expense, reuse existing supplies accounts; never ask.
_CONSUMABLE_RULES = (
    "toner|ink|cartridge|stationery|office suppl|printing paper|cleaning suppl"
)

# Services — use the organisation's service/expense treatment.
_SERVICE_RULES = (
    "consultant|consultancy|software development|development service|"
    "freelancer|contractor service|legal service|accounting service|"
    "subscription|saas|license|licence|maintenance service"
)

# Prepayments / advances / deposits — potential pre-paid asset treatment.
_PREPAID_RULES = (r"\badvance\b|\bprepaid\b|pre-payment|pre payment|\bdeposit\b")

# Inventory indicators — resale intent.
_INVENTORY_RULES = (r"for resale|for resell|for our shop|for the shop|"
                    r"for stock|for inventory|to resell|resale")

# Durable goods — POTENTIALLY fixed assets; materially ambiguous when the
# ERP has no authoritative mapping.  These trigger a targeted clarification
# instead of a default expense classification.
# \ba/?c\b|\bacs\b cover the everyday abbreviation ("I buy 2 ac") with word
# boundaries — safe against "account"/"trace" false positives.
_DURABLE_GOODS = (
    "laptop|notebook|desktop|computer|printer|scanner|monitor|server|"
    "furniture|desk|chair|cabinet|machinery|machine|vehicle|car|van|"
    "motorbike|motorcycle|camera|phone|smartphone|equipment|building|"
    "air conditioner|air.?conditioning|ac unit|\\ba/?c\\b|\\bacs\\b|hvac|"
    "generator"
)

# Account-name search terms per nature (used against the live COA).
_ACCOUNT_SEARCH_TERMS = {
    FIXED_ASSET: [
        "computer equipment", "office equipment", "equipment", "fixed asset",
        "furniture", "vehicle", "machinery", "building", "laptop",
    ],
    OPERATING_EXPENSE: [
        "utilities", "electricity", "rent", "salaries", "wages",
        "office supplies", "supplies", "communication", "travel",
        "marketing", "advertising", "advertisement", "insurance",
        "bank charges", "expense",
    ],
    INVENTORY: ["inventory", "stock"],
    INTANGIBLE_ASSET: ["software", "intangible", "license", "licence", "patent"],
    PREPAYMENT: ["prepaid", "prepayment", "advance"],
    DEPOSIT_ADVANCE: ["deposit", "advance"],
    SERVICE: ["service"],
    CONSUMABLE: ["supplies", "consumable"],
}


def _account_matches_expense_label(
    account: Optional[Dict[str, Any]], label: Optional[str]
) -> bool:
    """True when *account* plausibly IS the expense category in *label*.

    "Marketing & advertising expense" matches an account named
    "Advertising & Marketing" (first significant words overlap) but NOT
    "Utilities Expense" — the silent-default defect this prevents.
    """
    if not account or not label:
        return False
    name = (account.get("name") or "").lower()
    if not name:
        return False
    stop = {"expense", "expenses", "account", "&", "and", "the"}
    label_words = [w for w in re.split(r"[\s&]+", label.lower()) if w and w not in stop]
    if not label_words:
        return False
    return any(word in name for word in label_words)


def _matched_expense_label(text: str) -> Optional[str]:
    """Return the expense-rule category governing *text*, if any.

    Consumables map to the supplies accounts; named expense rules map to
    their category (e.g. "electricity" → "Utilities expense").  Used to
    keep the nature-level COA search item-relevant instead of dependent
    on which category account happens to be searched first.
    """
    if re.search(_CONSUMABLE_RULES, text):
        return "supplies"
    for pattern, label in _EXPENSE_RULES:
        if re.search(pattern, text):
            return label
    return None


# CONFIGURATION-GAP RESOLVER (owner directive): every KNOWN, unambiguous
# expense category must hit its OWN income-statement ledger.  When the
# chart of accounts has no account for the category, the agent CREATES
# it deterministically (never silently defaulting to the generic
# "General Operating Expense" account, never bouncing the user with a
# question for a category that is already certain).
_EXPENSE_ACCOUNT_SEEDS: Dict[str, tuple[str, str]] = {
    "utilities expense": ("Utilities Expense", "6130"),
    "rent expense": ("Rent Expense", "6140"),
    "salaries & wages": ("Salaries & Wages", "6010"),
    "communication expense": ("Communication Expense", "6150"),
    "travel & transport": ("Travel & Transport Expense", "6160"),
    "insurance expense": ("Insurance Expense", "6170"),
    "bank charges": ("Bank Charges", "6300"),
    "marketing & advertising expense": (
        "Marketing & Advertising Expense", "6180",
    ),
    "supplies": ("Supplies Expense", "6190"),
}


async def _ensure_expense_account(
    organization_id: uuid.UUID, rule_label: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Ensure the COA has an account for the KNOWN expense *rule_label*.

    Returns the matching/created account row, or None when the label is
    unknown (caller keeps its existing clarify-or-default behaviour).
    Creation is idempotent: an exact-name EXPENSE account short-circuits.
    """
    from app.repositories import account_repository as a_repo

    key = (rule_label or "").strip().lower()
    seed = _EXPENSE_ACCOUNT_SEEDS.get(key)
    if not seed:
        return None
    name, base_code = seed

    # Idempotency: an exact-name active EXPENSE account wins.
    try:
        existing = await a_repo.search_accounts(organization_id, query=name)
    except Exception as exc:  # noqa: BLE001 — COA search is best-effort
        log.warning("classifier.ensure_account_search_failed", error=str(exc))
        existing = []
    for acc in existing or []:
        nm = (acc.get("name") or "").strip().lower()
        if (
            nm == name.lower()
            and acc.get("account_type") in (None, "EXPENSE")
            and acc.get("is_active") is not False
        ):
            return acc

    try:
        code = await a_repo.next_available_code(organization_id, base_code)
        created = await a_repo.create_account(
            organization_id=organization_id,
            code=code,
            name=name,
            account_type="EXPENSE",
            normal_balance="DEBIT",
            description=(
                f"Auto-created by the AI agent for '{rule_label}' entries"
            ),
        )
        log.info(
            "classifier.expense_account_created",
            name=name,
            code=code,
            label=rule_label,
        )
        return created
    except Exception as exc:  # noqa: BLE001 — creation must never kill a run
        log.warning(
            "classifier.expense_account_create_failed",
            label=rule_label,
            error=str(exc)[:200],
        )
        return None


def _classification_text(item_description: Optional[str], entities: Dict[str, Any]) -> str:
    return " ".join(
        str(part) for part in (
            item_description,
            entities.get("item_description"),
            entities.get("description"),
        ) if part
    ).lower()


def rule_based_nature(
    item_description: Optional[str],
    entities: Dict[str, Any],
) -> tuple[Optional[str], str]:
    """Pure rule engine (no DB): returns (nature, confidence).

    Confidence is HIGH for unambiguous rules, LOW for durable goods that
    need configuration or a user decision (nature None).
    """
    text = _classification_text(item_description, entities)
    quantity = entities.get("quantity")

    # 1. Inventory: explicit resale/stock intent wins.
    if re.search(_INVENTORY_RULES, text):
        return INVENTORY, "HIGH"

    # 2. Prepayments / advances / deposits.
    if re.search(_PREPAID_RULES, text):
        if "rent" in text:
            return PREPAYMENT, "HIGH"
        return DEPOSIT_ADVANCE, "MEDIUM"

    # 3. Unambiguous operating-expense categories.
    for pattern, _label in _EXPENSE_RULES:
        if re.search(pattern, text):
            return OPERATING_EXPENSE, "HIGH"

    # 4. Services — use the organisation's service/expense treatment.
    if re.search(_SERVICE_RULES, text):
        return SERVICE, "HIGH"

    # 5. Consumables — expense treatment, reuse existing supplies accounts.
    if re.search(_CONSUMABLE_RULES, text):
        return OPERATING_EXPENSE, "HIGH"

    # 6. Durable goods — potentially fixed assets.  Bulk quantities lean
    #    inventory; a single unit is MATERIALLY AMBIGUOUS (fixed asset vs
    #    expense) unless ERP configuration resolves it — the caller checks
    #    the COA before asking the user.
    if re.search(_DURABLE_GOODS, text):
        try:
            if quantity is not None and float(quantity) >= 10:
                return INVENTORY, "MEDIUM"
        except (TypeError, ValueError):
            pass
        return None, "LOW"  # durable ambiguity → COA mapping or clarify

    # 7. Unknown items default to the conservative operating-expense
    #    treatment (matching the accounting engine's default) — the user is
    #    NOT quizzed about everyday unmapped items.
    return OPERATING_EXPENSE, "MEDIUM"


def _classification_question(classification: TransactionClassification) -> str:
    entity = classification.entity
    subject = f"'{entity}'" if entity else "this item"
    # The SAME 4-way decision tree the reasoning layer asks — consistent
    # wording across the deterministic and model paths.
    from app.reasoning import NATURE_DECISION_QUESTION

    return f"For {subject}: {NATURE_DECISION_QUESTION}"


async def _candidate_expense_accounts(organization_id: uuid.UUID) -> List[str]:
    """Suggest existing EXPENSE accounts the user may classify under when
    no dedicated account matches (e.g. 'bonus' → Salaries / Wages …)."""
    from app.repositories import account_repository as a_repo

    try:
        accounts = await a_repo.get_chart_of_accounts(
            organization_id, account_type="EXPENSE", limit=15,
        )
    except Exception as exc:  # noqa: BLE001 — suggestions are best-effort
        log.warning("classifier.candidate_accounts_failed", error=str(exc))
        return []
    names: List[str] = []
    for acc in accounts or []:
        name = (acc.get("name") or "").strip()
        if not name:
            continue
        low = name.lower()
        if "accumulated" in low or "depreciation" in low:
            continue
        names.append(name)
    return names[:5]


async def _search_account_by_nature(
    organization_id: uuid.UUID,
    nature: str,
    item_description: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Search the live Chart of Accounts for the best account for *nature*.

    Tries nature-specific name terms first, then (for expenses) falls back
    to the first active EXPENSE account.  Returns None when nothing matches.
    """
    from app.repositories import account_repository as a_repo

    item = (item_description or "").lower()

    # Purchases for expense natures must debit EXPENSE accounts — never
    # revenue accounts (e.g. the term "service" would otherwise match
    # "Services Revenue" and a purchase would credit-side revenue).
    expense_nature = nature in (OPERATING_EXPENSE, CONSUMABLE, SERVICE)

    # For expense natures a generic category match must be tied to the
    # item by a deterministic rule — otherwise whichever category account
    # the search hits first (e.g. Utilities) would capture every unmapped
    # expense instead of the general default account.
    rule_label = _matched_expense_label(item) if expense_nature else None

    def _usable(acc: Dict[str, Any]) -> bool:
        """Reject contra-accounts (e.g. Accumulated Depreciation) and
        inactive accounts — they must never receive purchase debits."""
        name = (acc.get("name") or "").lower()
        if "accumulated" in name or "depreciation" in name:
            return False
        if acc.get("is_active") is False:
            return False
        if expense_nature and acc.get("account_type") not in (None, "EXPENSE"):
            return False
        return True

    for term in _ACCOUNT_SEARCH_TERMS.get(nature, []):
        try:
            matches = await a_repo.search_accounts(organization_id, query=term)
        except Exception as exc:  # noqa: BLE001 — COA search is best-effort
            log.warning("classifier.coa_search_failed", term=term, error=str(exc))
            continue
        matches = [m for m in matches if _usable(m)]
        if not matches:
            continue
        # Prefer an account whose name also relates to the item itself.
        for m in matches:
            if item and item.split()[0] in (m.get("name") or "").lower():
                return m
        if expense_nature and item:
            if rule_label is None:
                continue
            lw = rule_label.lower()
            tw = term.lower()
            if tw.split()[0] not in lw and lw.split()[0] not in tw:
                continue
        return matches[0]

    # Fallback for expense-type natures: ONLY a genuinely GENERIC expense
    # account (name contains general/other/miscellaneous/sundry/operating).
    # NEVER "whichever EXPENSE account sorts first" — live defect: a chair
    # purchase was debited to 6010 Salaries because it happened to sort
    # first.  When no generic account exists the caller must clarify or
    # create one — a silent wrong-category default is worse than a question.
    if nature in (OPERATING_EXPENSE, SERVICE, CONSUMABLE):
        accounts = await a_repo.get_chart_of_accounts(
            organization_id, account_type="EXPENSE", limit=100,
        )
        generic_terms = ("general", "other", "miscellaneous", "sundry", "operating")
        for acc in accounts:
            name = (acc.get("name") or "").lower()
            if _usable(acc) and any(t in name for t in generic_terms):
                return acc
        log.warning(
            "classifier.no_generic_expense_account",
            nature=nature,
            hint="no generic expense account — clarification required",
        )
    return None


async def classify_transaction(
    *,
    organization_id: uuid.UUID,
    intent: str,
    entities: Dict[str, Any],
    message: Optional[str] = None,
) -> TransactionClassification:
    """Classify the transaction using the authority hierarchy (see module doc).

    Purely deterministic — no LLM involvement.  Returns a structured
    ``TransactionClassification``; ``requires_clarification=True`` means the
    ambiguity is MATERIAL and the agent must ask instead of guessing.

    Payment/transfer intents (record_expense_payment, record_payment,
    record_receipt, record_bank_transfer) are never held for classification:
    their underlying expense/bill was already classified when created, and
    there is no classifiable item in the payment itself.
    """
    item = (
        entities.get("item_description")
        or entities.get("description")
        or entities.get("entity_name")
    )
    entity_name = (
        entities.get("entity_name") or item or entities.get("supplier_name")
    )

    # Payment intents: no item to classify — never pause for classification.
    _PAYMENT_INTENTS = (
        "record_expense_payment", "record_payment", "record_receipt",
        "record_bank_transfer", "record_supplier_payment", "record_customer_receipt",
    )
    if intent in _PAYMENT_INTENTS:
        return TransactionClassification(
            transaction_nature=None,
            confidence="LOW",
            source="INFERENCE",
            entity=item or entity_name,
            requires_clarification=False,
        )

    # Asset-lifecycle intents are deterministically FIXED_ASSET — the
    # economic nature is decided by the event itself, never inferred from
    # price or physical appearance.
    _ASSET_LIFECYCLE_INTENTS = (
        "register_fixed_asset", "dispose_fixed_asset",
        "record_asset_depreciation",
    )
    if intent in _ASSET_LIFECYCLE_INTENTS:
        account = await _search_account_by_nature(organization_id, FIXED_ASSET, item)
        return TransactionClassification(
            transaction_nature=FIXED_ASSET,
            confidence="HIGH",
            source="DETERMINISTIC_RULE",
            entity=item or entity_name,
            account_hint_id=account.get("id") if account else None,
            account_hint_code=account.get("code") if account else None,
            account_hint_name=account.get("name") if account else None,
            requires_clarification=False,
        )

    # Item-less recording requests also cannot be classified further — the
    # model proceeds with its own (validated) handling.
    if not item and not message:
        return TransactionClassification(
            transaction_nature=None,
            confidence="LOW",
            source="INFERENCE",
            entity=entity_name,
            requires_clarification=False,
        )

    # --- 1. USER_ANSWER: an explicit treatment answer always wins. --------
    explicit = entities.get("transaction_nature")
    if explicit:
        nature = str(explicit).upper()
        if nature not in NATURES:
            nature = FIXED_ASSET if "ASSET" in nature else OPERATING_EXPENSE
        account = await _search_account_by_nature(organization_id, nature, item)
        if not account and nature in (FIXED_ASSET, INTANGIBLE_ASSET):
            # NO arbitrary asset-account fallback: picking "the first
            # non-cash ASSET account" could route a laptop to Warehouse or
            # any unrelated asset.  A missing fixed-asset account is a
            # CONFIGURATION gap → targeted configuration clarification.
            return TransactionClassification(
                transaction_nature=nature,
                confidence="HIGH",
                source="USER_ANSWER",
                entity=item or entity_name,
                account_hint_id=None,
                account_hint_code=None,
                account_hint_name=None,
                requires_clarification=True,
                clarification_reason=(
                    "No fixed-asset account (e.g. Computer Equipment) exists "
                    "in the chart of accounts — the account must be created "
                    "or explicitly selected"
                ),
            )
        return TransactionClassification(
            transaction_nature=nature,
            confidence="HIGH",
            source="USER_ANSWER",
            entity=item or entity_name,
            account_hint_id=account.get("id") if account else None,
            account_hint_code=account.get("code") if account else None,
            account_hint_name=account.get("name") if account else None,
            requires_clarification=False,
        )

    # --- 2. ERP_CONFIGURATION: products/services item mapping. ------------
    if item:
        try:
            from app.database import fetch_many

            products = await fetch_many(
                "products",
                filters={"organization_id": str(organization_id)},
                select="id,name,is_stock_tracked,revenue_account_id",
                limit=50,
            )
            for p in products or []:
                if (p.get("name") or "").lower() in item or item in (p.get("name") or "").lower():
                    if p.get("is_stock_tracked"):
                        nature = INVENTORY
                    elif re.search(_DURABLE_GOODS, item, re.IGNORECASE):
                        # NO silent guess: a durable catalog product that is
                        # NOT marked stock-tracked is materially ambiguous —
                        # fixed asset vs consumable expense vs resale
                        # inventory vs service.  The catalog flag alone must
                        # never decide INVENTORY vs OPERATING_EXPENSE.
                        from app.reasoning import NATURE_DECISION_QUESTION

                        return TransactionClassification(
                            transaction_nature=None,
                            confidence="MEDIUM",
                            source="ERP_CONFIGURATION",
                            entity=item,
                            requires_clarification=True,
                            clarification_reason=(
                                "Catalog product matched but is not marked "
                                "stock-tracked while being durable in nature "
                                f"— {NATURE_DECISION_QUESTION}"
                            ),
                        )
                    else:
                        nature = OPERATING_EXPENSE
                    return TransactionClassification(
                        transaction_nature=nature,
                        confidence="HIGH",
                        source="ERP_CONFIGURATION",
                        entity=item,
                        requires_clarification=False,
                        clarification_reason=None,
                    )
        except Exception as exc:  # noqa: BLE001 — config lookup is best-effort
            log.warning("classifier.product_lookup_failed", error=str(exc))

    # --- 3+4. DETERMINISTIC_RULES (incl. COA item mapping for natures). ---
    # The rules see the item AND the original message (e.g. "for resale",
    # "advance", "electricity bill" often live outside the extracted item).
    nature, confidence = rule_based_nature(
        " ".join(x for x in (item, message) if x), entities
    )
    if nature:
        classification_text = " ".join(x for x in (item, message) if x)
        rule_label = (
            _matched_expense_label(classification_text)
            if nature == OPERATING_EXPENSE else None
        )
        account = await _search_account_by_nature(organization_id, nature, item)
        # CONFIGURATION GAP (P4): a SPECIFIC expense category was identified
        # (e.g. Marketing & advertising, Rent) but the chart of accounts has
        # no account matching that category.  The first/default expense
        # account (e.g. Utilities) must NEVER silently capture it — surface
        # the gap and let the account be created or explicitly selected.
        if (
            nature == OPERATING_EXPENSE
            and rule_label
            and not _account_matches_expense_label(account, rule_label)
        ):
            # OWNER DIRECTIVE: a KNOWN specific expense category (rent,
            # utilities, marketing, …) must hit its OWN income-statement
            # ledger.  When the account doesn't exist, CREATE it right
            # here — never silently default to the generic "General
            # Operating Expense" account and never bounce the user with a
            # question for a category that is already certain.
            ensured = await _ensure_expense_account(organization_id, rule_label)
            if ensured is not None:
                account = ensured
            else:
                # Unknown label or creation failed → keep the explicit
                # clarification fallback (never a silent wrong default).
                return TransactionClassification(
                    transaction_nature=nature,
                    confidence=confidence,
                    source="DETERMINISTIC_RULE",
                    entity=item or entity_name,
                    account_hint_id=None,
                    account_hint_code=None,
                    account_hint_name=None,
                    requires_clarification=True,
                    clarification_reason=(
                        f"No '{rule_label}' account exists in the chart of "
                        "accounts and it could not be created "
                        "automatically — it must be created or explicitly "
                        "selected"
                    ),
                )
        if account is None:
            # Nature decided but NO account hint (no category match and no
            # generic default).  OFFER relevant existing accounts + the
            # option to create a dedicated one — never post to a guessed
            # account (live defect: 'bonus' would have landed in Salaries).
            candidates = await _candidate_expense_accounts(organization_id)
            suggestion = ", ".join(f"'{c}'" for c in candidates[:4])
            return TransactionClassification(
                transaction_nature=nature,
                confidence=confidence,
                source="DETERMINISTIC_RULE",
                entity=item or entity_name,
                candidate_accounts=candidates or None,
                requires_clarification=True,
                clarification_reason=(
                    f"No dedicated account matches "
                    f"'{item or entity_name or 'this entry'}'. "
                    + (
                        f"Use an existing account ({suggestion}) or create "
                        "a new dedicated account."
                        if candidates
                        else "Create a dedicated account or pick an "
                        "existing one."
                    )
                ),
            )
        return TransactionClassification(
            transaction_nature=nature,
            confidence=confidence,
            source="DETERMINISTIC_RULE",
            entity=item or entity_name,
            account_hint_id=account.get("id") if account else None,
            account_hint_code=account.get("code") if account else None,
            account_hint_name=account.get("name") if account else None,
            requires_clarification=False,
        )

    # --- 4b. ITEM_MAPPING: a durable item matched to an existing COA
    # fixed-asset account is authoritatively classified (e.g. laptop →
    # 1500 Computer Equipment) — no clarification needed.
    if not nature and item:
        asset = await _search_account_by_nature(organization_id, FIXED_ASSET, item)
        if asset and asset.get("account_type") == "ASSET":
            return TransactionClassification(
                transaction_nature=FIXED_ASSET,
                confidence="HIGH",
                source="ITEM_MAPPING",
                entity=item or entity_name,
                account_hint_id=asset.get("id"),
                account_hint_code=asset.get("code"),
                account_hint_name=asset.get("name"),
                requires_clarification=False,
            )

    # --- 5. INFERENCE: material ambiguity (e.g. laptop with no COA
    # mapping) → ASK.  Never default to a generic expense account.
    return TransactionClassification(
        transaction_nature=None,
        confidence="LOW",
        source="INFERENCE",
        entity=item or entity_name,
        requires_clarification=True,
        clarification_reason=(
            "Materially ambiguous fixed-asset-versus-expense treatment and "
            "no authoritative ERP configuration exists"
        ),
    )


