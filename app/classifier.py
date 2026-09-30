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

# Built-in capitalization threshold (mirrors reasoning.CAPITAL_AMOUNT_
# THRESHOLD; lazy import at use site keeps the module graph acyclic).

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
    # expense account (an "advertising campaign" must never be debited to
    # an unrelated account such as Utilities).
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
    "Utilities Expense" — the silent mis-classification this prevents.
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


async def _propose_expense_account(
    organization_id: uuid.UUID, rule_label: Optional[str]
) -> Optional[tuple[str, str]]:
    """PROPOSE (never silently create) the COA account for a KNOWN expense
    *rule_label*.

    Returns ``(name, next_free_code)`` for the canonical seed account, or
    None when the label is unknown.  Idempotency: an exact-name active
    EXPENSE account short-circuits to itself — the caller treats it as the
    hint.  CREATION IS NEVER DONE HERE: the missing account is surfaced as
    a configuration-gap clarification and the user confirms creation (or
    names an existing account) — the account-creation confirmation policy.
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
        log.warning("classifier.propose_account_search_failed", error=str(exc))
        existing = []
    for acc in existing or []:
        nm = (acc.get("name") or "").strip().lower()
        if (
            nm == name.lower()
            and acc.get("account_type") in (None, "EXPENSE")
            and acc.get("is_active") is not False
        ):
            return (name, str(acc.get("code") or base_code))

    try:
        code = await a_repo.next_available_code(organization_id, base_code)
    except Exception as exc:  # noqa: BLE001 — code resolution is best-effort
        log.warning("classifier.propose_account_code_failed", label=rule_label, error=str(exc)[:200])
        return None
    return (name, str(code))


async def _confirmed_account_code(
    organization_id: uuid.UUID, nature: str, name: str
) -> str:
    """Free code in the nature's numbering series for a CONFIRMED creation.

    Seed accounts (utilities, rent, …) keep their canonical code series; the
    rest take the nature's base series probed for the next free code —
    ``create_account`` re-resolves collisions again at execution time.
    """
    from app.account_resolution import InvalidAccountingNature, account_shape
    from app.repositories import account_repository as a_repo

    seed = next(
        (
            (seed_name, seed_code)
            for seed_name, seed_code in _EXPENSE_ACCOUNT_SEEDS.values()
            if seed_name.lower() == str(name or "").strip().lower()
        ),
        None,
    )
    if seed:
        base = seed[1]
    else:
        try:
            base = account_shape(nature)[2]
        except InvalidAccountingNature:
            # Wave A (AUDIT_REPORT §3.1): no determined code series for this
            # treatment.  An empty code is a REJECTION, not an invented 6100
            # expense series — create_account resolves a free code itself, and
            # the account-shape guards downstream refuse to guess a section.
            log.warning(
                "classifier.unsupported_treatment_code",
                nature=str(nature)[:40],
                name=str(name)[:60],
            )
            return ""
    try:
        return str(await a_repo.next_available_code(organization_id, base))
    except Exception as exc:  # noqa: BLE001 — best-effort; the tool re-resolves
        log.warning("classifier.confirmed_code_failed", error=str(exc)[:200])
        return str(base)


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

    # 7. Unknown items: the conservative default is operating-expense ONLY
    #    for immaterial amounts (everyday unmapped items are never quizzed).
    #    A MATERIAL amount on an item no rule recognises is exactly where
    #    auto-expense fails at scale — a multi-national business deals in
    #    thousands of item types across hundreds of trades, and a keyword
    #    vocabulary can never be exhaustive.  The AMOUNT decides skepticism:
    #    at or above the org's capitalization threshold the nature decision
    #    must be ASKED (fixed asset / inventory / expense / prepaid),
    #    never guessed.
    from app.reasoning import CAPITAL_AMOUNT_THRESHOLD

    try:
        threshold = float(
            entities.get("capitalization_threshold")
            or CAPITAL_AMOUNT_THRESHOLD
        )
    except (TypeError, ValueError):
        threshold = CAPITAL_AMOUNT_THRESHOLD
    amount = entities.get("amount")
    try:
        material = amount is not None and float(amount) >= threshold
    except (TypeError, ValueError):
        material = False
    if material:
        return None, "MEDIUM"  # material-unknown → ASK (skips loose COA mapping)
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


async def _llm_decision(
    organization_id: uuid.UUID,
    *,
    intent: str,
    entities: Dict[str, Any],
    message: Optional[str],
    nature_hint: Optional[str] = None,
) -> Optional[TransactionClassification]:
    """Consult the LLM decision layer (app/llm_classification.py).

    The model DECIDES nature + account from Python-gathered candidates;
    Python has already validated the pick before it gets here. Returns
    ``None`` when the layer is disabled, unreachable, or its reply failed
    validation — the caller then falls back to the deterministic chain.
    Never swallows AssertionError (test no-LLM guards stay loud).
    """
    try:
        from app import llm_classification

        return await llm_classification.decide(
            organization_id=organization_id,
            intent=intent,
            entities=entities,
            message=message,
            nature_hint=nature_hint,
        )
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001 — degrade to the rule chain
        log.warning("classifier.llm_decision_failed", error=str(exc)[:200])
        return None


def _fold_token(word: str) -> str:
    """Trivially plural-folded lowercase form for anchor comparison."""
    w = word.lower()
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


# Words that carry no item identity in an anchor comparison.
_ANCHOR_STOPWORDS = frozenset({
    "the", "a", "an", "for", "of", "and", "or", "new", "old", "used",
    "bought", "buy", "buying", "purchase", "purchased", "from", "with",
    "some", "one", "two", "three", "four", "five", "units", "unit",
    "pcs", "pc", "nos", "no", "set", "sets", "paid", "cash", "credit",
    "amount", "worth",
})


def _item_anchor_tokens(item: str) -> List[str]:
    """Significant folded words of the ITEM — its identity tokens."""
    tokens: List[str] = []
    for raw in re.split(r"[^a-z0-9]+", (item or "").lower()):
        if len(raw) < 3 or raw in _ANCHOR_STOPWORDS:
            continue
        folded = _fold_token(raw)
        if folded and folded not in tokens:
            tokens.append(folded)
    return tokens


def _account_anchors_item(account: Dict[str, Any], item: str) -> bool:
    """True when the item's OWN words name the account — a measurable fact.

    "3 computers" anchors "1500 Computer Equipment"; "motorbike" can never
    anchor it.  Category semantics (motorbike → Vehicles) require judgement
    and belong to the LLM decision layer; this helper only proves the
    trivial case where the chart literally carries the item's name.
    """
    account_tokens = {
        _fold_token(w)
        for w in re.split(r"[^a-z0-9]+", (account.get("name") or "").lower())
        if w
    }
    if not account_tokens:
        return False
    return any(tok in account_tokens for tok in _item_anchor_tokens(item))


async def _search_account_by_nature(
    organization_id: uuid.UUID,
    nature: str,
    item_description: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Search the live Chart of Accounts for an account the ITEM names.

    ACCEPTANCE IS ANCHORED, NEVER TERM-ORDERED: an account is returned only
    when (a) the item's own words name it ("3 computers" → "Computer
    Equipment"), or (b) a curated expense rule ties the item to the
    account's category ("electricity" → Utilities Expense).  A bare term
    match on an item nothing anchors (a "motorbike" against "Computer
    Equipment") is a SEMANTIC call — the LLM decision layer's — so this
    helper returns None and the caller clarifies/creates instead of
    silently debiting the wrong account.  Returns None when nothing
    anchors.
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
        # (a) ITEM ANCHOR — the item's own words name the account: a fact,
        #     usable for ANY nature.
        for m in matches:
            if _account_anchors_item(m, item):
                return m
        # (b) CURATED expense-category mapping: an expense rule ties the
        #     item to a category (e.g. "electricity" → Utilities expense)
        #     and the account must plausibly BE that category — never a
        #     neighbouring account caught by term order.
        if expense_nature and item and rule_label:
            lw = rule_label.lower()
            tw = term.lower()
            if tw.split()[0] in lw or lw.split()[0] in tw:
                for m in matches:
                    if _account_matches_expense_label(m, rule_label):
                        return m
        # NO `return matches[0]` — term ORDER must never pick the account
        # (that is how a motorbike was debited to Computer Equipment). An
        # unanchored category is a semantic judgement: the LLM decision
        # layer decides it when reachable, and the flow clarifies/creates
        # when it is not.

    # Fallback for expense-type natures: ONLY a genuinely GENERIC expense
    # account (name contains general/other/miscellaneous/sundry/operating).
    # NEVER "whichever EXPENSE account sorts first" — an unrelated purchase
    # must never land in e.g. 6010 Salaries just because it sorts first.
    # When no generic account exists the caller must clarify or
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
    # P1-⑧ (forensic latency report ⑧): account-hint / config-gap resolution
    # is the classifier's DB-heavy part (up to ~6 round-trips). Its consumers
    # — the deterministic fast path, the Phase-4 account-hint prompt and the
    # config-gap question — do NOT run when a validated reasoning proposal or
    # an approved plan owns the plan. NATURE-AFFECTING lookups (products
    # mapping, 4b COA item mapping) always run: build_event_profile consumes
    # transaction_nature for the executor's prohibited-tools guard.
    resolve_account_hints: bool = True,
    explicit_nature_source: Optional[str] = None,
) -> TransactionClassification:
    """Classify the transaction using the authority hierarchy (see module doc).

    Purely deterministic — no LLM involvement.  Returns a structured
    ``TransactionClassification``; ``requires_clarification=True`` means the
    ambiguity is MATERIAL and the agent must ask instead of guessing.

    With ``resolve_account_hints=False`` (P1-⑧, proposal/approved paths)
    every ACCOUNT-HINT lookup and its configuration-gap branches are
    skipped; the NATURE decision itself is unchanged (explicit answer,
    asset-lifecycle rule, products mapping, deterministic rules and 4b COA
    item mapping all still run) — so ``build_event_profile`` keeps the
    nature it needs for the executor's prohibited-set guard.

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

    # ---- EXECUTION-AGENT LOOP (user-confirmed account creation) ----------
    # The account-creation clarification was answered YES — the answer-merge
    # folded the confirmed name into entities["create_account"].  EVERY
    # intent family routes through here (fixed asset, invoice, purchase,
    # expense, journal, any new activity): the classification marks the
    # creation as a USER_ANSWER so the prompt orders create_account FIRST
    # and the executor's tool-order guard blocks the recording mutation
    # until the ledger exists.  A name that already exists degrades to a
    # plain account hint (create_account reuses it — never a duplicate).
    confirmed_account = str(entities.get("create_account") or "").strip()
    if confirmed_account:
        if intent in (
            "register_fixed_asset", "dispose_fixed_asset",
            "record_asset_depreciation",
        ):
            nature = FIXED_ASSET
        else:
            nature = str(entities.get("transaction_nature") or "").upper()
            if nature not in NATURES:
                nature = None
        if nature is None:
            nature, _confirmed_conf = rule_based_nature(
                " ".join(x for x in (item, message) if x), entities
            )
        if nature is None:
            nature = OPERATING_EXPENSE
        from app.account_resolution import account_exists

        existing = await account_exists(organization_id, confirmed_account)
        if existing:
            return TransactionClassification(
                transaction_nature=nature,
                confidence="HIGH",
                source="USER_ANSWER",
                entity=item or entity_name,
                account_hint_id=str(existing.get("id") or "") or None,
                account_hint_code=str(existing.get("code") or "") or None,
                account_hint_name=str(existing.get("name") or "") or None,
                requires_clarification=False,
            )
        code = await _confirmed_account_code(
            organization_id, nature, confirmed_account
        )
        # PARENT PLACEMENT: the confirmation question carried
        # "under '<head>'" -> entities["create_parent_name"].  Resolved HERE
        # so the injected create_account lands the child under the right
        # statement heading - type-checked against the nature's shape, a
        # heading from the wrong section never parents this ledger.
        parent_id = parent_name = None
        _req_parent = str(entities.get("create_parent_name") or "").strip()
        if _req_parent:
            from app.account_resolution import account_shape, is_category_parent

            try:
                _prow = await account_exists(organization_id, _req_parent)
            except Exception:  # noqa: BLE001 - parent lookup is best-effort
                _prow = None
            # Wave A (AUDIT_REPORT §3.1): an undetermined treatment cannot
            # certify a statement section, so no parent is asserted — the
            # account is created top-level rather than under a guessed heading.
            try:
                _expected_type = account_shape(nature)[0]
            except InvalidAccountingNature:
                log.warning(
                    "classifier.unsupported_treatment_parent",
                    nature=str(nature)[:40],
                )
                _expected_type = None
            if (
                _prow
                and _expected_type
                and str(_prow.get("account_type") or "").upper() == _expected_type
                and is_category_parent(_prow, nature=nature)
            ):
                parent_id = str(_prow.get("id") or "") or None
                parent_name = (
                    str(_prow.get("name") or "").strip() or _req_parent
                )
        return TransactionClassification(
            transaction_nature=nature,
            confidence="HIGH",
            source="USER_ANSWER",
            entity=item or entity_name,
            proposed_account_name=confirmed_account,
            proposed_account_code=code,
            proposed_parent_id=parent_id,
            proposed_parent_name=parent_name,
            create_account_confirmed=True,
            requires_clarification=False,
        )

    # ---- USER AGREED TO USE AN EXISTING ACCOUNT (informed consent) ------
    # The RELATED-treatment round offered the closest existing ledger
    # ("use Vehicles") and the user AGREED - the answer-merge folded their
    # choice into entities["account_name"].  Their explicit choice is a
    # FACT of the same rank as entities["create_account"]: pin it as the
    # hint (USER_ANSWER) so the entry posts to the account they approved,
    # never to a re-guessed one.  A name the chart does not hold - or one
    # whose section contradicts the nature - falls through to the normal
    # chain, which asks again instead of guessing.
    named_account = str(entities.get("account_name") or "").strip()
    if named_account:
        from app.account_resolution import account_exists, account_shape

        named_row = await account_exists(organization_id, named_account)
        if named_row:
            named_nature = (
                FIXED_ASSET
                if intent in (
                    "register_fixed_asset",
                    "dispose_fixed_asset",
                    "record_asset_depreciation",
                )
                else str(entities.get("transaction_nature") or "").upper()
            )
            if named_nature not in NATURES:
                named_nature, _named_conf = rule_based_nature(
                    " ".join(x for x in (item, message) if x), entities
                )
            # Wave A (AUDIT_REPORT §3.1): an undetermined treatment cannot
            # prove the named ledger's section, so the match FAILS and the run
            # falls through to the chain that asks again — never a silent
            # "close enough" acceptance against a defaulted expense shape.
            _named_section = None
            if named_nature:
                try:
                    _named_section = account_shape(named_nature)[0]
                except InvalidAccountingNature:
                    log.warning(
                        "classifier.unsupported_treatment_named_account",
                        nature=str(named_nature)[:40],
                    )
            if (
                not named_nature
                or (
                    _named_section is not None
                    and str(named_row.get("account_type") or "").upper()
                    == _named_section
                )
            ):
                return TransactionClassification(
                    transaction_nature=named_nature,
                    confidence="HIGH",
                    source="USER_ANSWER",
                    entity=item or entity_name,
                    account_hint_id=str(named_row.get("id") or "") or None,
                    account_hint_code=str(named_row.get("code") or "") or None,
                    account_hint_name=str(named_row.get("name") or "") or None,
                    requires_clarification=False,
                )

    # Asset-lifecycle intents are deterministically FIXED_ASSET — the
    # economic nature is decided by the event itself, never inferred from
    # price or physical appearance.  The NATURE is a fact of the intent;
    # the ACCOUNT that receives it is a judgment call, so the LLM decision
    # layer picks it (validated against the candidate set).  When the layer
    # is off/unreachable the ANCHORED COA mapping is the degraded fallback
    # (only an account the item itself names); when nothing anchors, the
    # flow clarifies — term order never decides.
    _ASSET_LIFECYCLE_INTENTS = (
        "register_fixed_asset", "dispose_fixed_asset",
        "record_asset_depreciation",
    )
    if intent in _ASSET_LIFECYCLE_INTENTS:
        if resolve_account_hints:
            decision = await _llm_decision(
                organization_id, intent=intent, entities=entities,
                message=message, nature_hint=FIXED_ASSET,
            )
            if decision is not None:
                return decision
        account = (
            await _search_account_by_nature(organization_id, FIXED_ASSET, item)
            if resolve_account_hints
            else None
        )
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
        # RC-4a (production 2026-09-24, "3 computers" incident): the plan
        # carries the TRUE provenance of the nature (planner:
        # USER_ANSWER vs PREFERENCE vs DETERMINISTIC_RULE).  Reporting a
        # learned org preference as USER_ANSWER upgraded a default into
        # "the user said so" (the CLASSIFICATION step showed source:
        # USER_ANSWER for a nature the user never answered).  Honest
        # provenance only — the nature DECISION itself is unchanged.
        # Legacy callers without the param keep the historical label.
        _raw_src = str(explicit_nature_source or "").strip().upper()
        explicit_source = (
            _raw_src
            if _raw_src in ("USER_ANSWER", "PREFERENCE", "DETERMINISTIC_RULE")
            else "USER_ANSWER"
        )
        # The NATURE is the user's fact (forced via nature_hint); WHICH
        # account receives it is judgment — the LLM picks from candidates
        # (validated against THIS nature); the anchored COA mapping is the
        # degraded fallback and an unanchored item escalates to a question.
        if resolve_account_hints:
            decision = await _llm_decision(
                organization_id, intent=intent, entities=entities,
                message=message, nature_hint=nature,
            )
            if decision is not None:
                # Keep the honest provenance of the USER's nature choice —
                # only the account came from the model.
                decision.source = explicit_source
                decision.confidence = "HIGH"
                if decision.account_hint_id or decision.requires_clarification:
                    return decision
                # Model decided nothing usable → keep its nature, no hint.
                return TransactionClassification(
                    transaction_nature=nature,
                    confidence="HIGH",
                    source=explicit_source,
                    entity=item or entity_name,
                    requires_clarification=False,
                )
        account = (
            await _search_account_by_nature(organization_id, nature, item)
            if resolve_account_hints
            else None
        )
        if (
            resolve_account_hints
            and not account
            and nature in (FIXED_ASSET, INTANGIBLE_ASSET)
        ):
            # NO arbitrary asset-account fallback: picking "the first
            # non-cash ASSET account" could route a laptop to Warehouse or
            # any unrelated asset.  A missing fixed-asset account is a
            # CONFIGURATION gap → targeted configuration clarification.
            return TransactionClassification(
                transaction_nature=nature,
                confidence="HIGH",
                source=explicit_source,
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
            source=explicit_source,
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

    # --- LLM DECISION LAYER (nature + account — the JUDGMENT zone) -------
    # Everything above this line is FACTS (user answers, ERP configuration,
    # the intent itself). From here on the classifier used to guess with
    # keyword rules and search-term order — which is how a motorbike got
    # debited to Computer Equipment ("computer equipment" was simply the
    # first term with a match). The model now DECIDES nature + account from
    # the live candidate set; the deterministic chain below is the FALLBACK
    # when the layer is disabled/unreachable/invalid — never a co-author.
    if resolve_account_hints:
        decision = await _llm_decision(
            organization_id, intent=intent, entities=entities,
            message=message, nature_hint=None,
        )
        if decision is not None:
            return decision

    # --- 3+4. DETERMINISTIC_RULES (incl. COA item mapping for natures). ---
    # The rules see the item AND the original message (e.g. "for resale",
    # "advance", "electricity bill" often live outside the extracted item).
    nature, confidence = rule_based_nature(
        " ".join(x for x in (item, message) if x), entities
    )
    # Material-unknown (rule 7 with a material amount): an item the ERP
    # cannot authoritatively classify at a material amount must be ASKED.
    # The loose first-match COA shortcut (4b) must NEVER decide it — that
    # is how "2 industrial pumps" ended up capitalised to "Computer
    # Equipment" and "2 ac" silently expensed.  Durable items keep their
    # (None, LOW) path and remain 4b-eligible.
    material_unknown = nature is None and confidence == "MEDIUM"
    if material_unknown:
        return TransactionClassification(
            transaction_nature=None,
            confidence="MEDIUM",
            source="INFERENCE",
            entity=item or entity_name,
            requires_clarification=True,
            clarification_reason=(
                f"'{item or entity_name or 'this entry'}' is a material "
                "amount the ERP cannot authoritatively classify — the "
                "purpose/treatment decision must be explicit (fixed asset, "
                "resale inventory, expense, or prepaid), never assumed"
            ),
        )
    if nature:
        classification_text = " ".join(x for x in (item, message) if x)
        rule_label = (
            _matched_expense_label(classification_text)
            if nature == OPERATING_EXPENSE else None
        )
        account = (
            await _search_account_by_nature(organization_id, nature, item)
            if resolve_account_hints
            else None
        )
        # CONFIGURATION GAP (P4): a SPECIFIC expense category was identified
        # (e.g. Marketing & advertising, Rent) but the chart of accounts has
        # no account matching that category.  The first/default expense
        # account (e.g. Utilities) must NEVER silently capture it — surface
        # the gap and let the account be created or explicitly selected.
        if (
            resolve_account_hints
            and nature == OPERATING_EXPENSE
            and rule_label
            and not _account_matches_expense_label(account, rule_label)
        ):
            # OWNER POLICY (account-creation confirmation): a KNOWN specific
            # expense category (rent, utilities, marketing, …) must hit its
            # OWN income-statement ledger — never the generic "General
            # Operating Expense" account, and never a SILENTLY created one.
            # The classifier PROPOSES the canonical account (name + free
            # code); the user confirms creation (or names an existing
            # account) in the clarification round.  When the proposal was
            # already confirmed, it is an explicit USER_ANSWER: execution
            # runs create_account FIRST, then records (tool-order guard).
            proposal = await _propose_expense_account(organization_id, rule_label)
            confirmed_name = (entities.get("create_account") or "").strip()
            if confirmed_name and proposal is not None:
                return TransactionClassification(
                    transaction_nature=nature,
                    confidence="HIGH",
                    source="USER_ANSWER",
                    entity=item or entity_name,
                    proposed_account_name=proposal[0],
                    proposed_account_code=proposal[1],
                    create_account_confirmed=True,
                    requires_clarification=False,
                )
            candidates = await _candidate_expense_accounts(organization_id)
            return TransactionClassification(
                transaction_nature=nature,
                confidence=confidence,
                source="DETERMINISTIC_RULE",
                entity=item or entity_name,
                candidate_accounts=candidates or None,
                proposed_account_name=proposal[0] if proposal else None,
                proposed_account_code=proposal[1] if proposal else None,
                requires_clarification=True,
                clarification_reason=(
                    f"No '{rule_label}' account exists in your chart of "
                    + (
                        f"accounts. Create '{proposal[0]}' (code {proposal[1]})? "
                        "Reply YES to create it, or name an existing account "
                        "to use instead."
                        if proposal
                        else "accounts — a dedicated account must be created "
                        "(with your confirmation) or an existing one selected."
                    )
                ),
            )
        if resolve_account_hints and account is None:
            # Nature decided but NO account hint (no category match and no
            # generic default).  OFFER relevant existing accounts + the
            # option to create a dedicated one — never post to a guessed
            # account (e.g. a 'bonus' must not land in Salaries).
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

    # --- 4b. ITEM_MAPPING: a durable item whose OWN words name an existing
    # COA fixed-asset account is a fact ("3 computers" → 1500 Computer
    # Equipment) — no clarification needed.  An unanchored item is a
    # semantic call the LLM decision layer owns; never term-order.
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


