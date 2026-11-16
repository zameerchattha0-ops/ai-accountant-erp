"""Contextual Accounting Nature Classifier (IAS 16 vs IAS 2 vs IAS 1 vs IFRS 15).

Implements the 4-Dimensional Convergence Engine:
    Accounting Nature = Φ(Q_Query, P_OrgProfile, C_ProductCatalog, R_AssetRegister)

Specification Reference:
    - docs/ACCOUNTING_SPECIFICATION_LLM_REASONING.md §2 (Contextual Accounting Nature Classification)
    - AUDIT_REPORT.md / TECHNICAL_AUDIT_AND_ROADMAP.md (offline test mocking, fail-safe degradation)

Core Invariants:
1. Economic Substance over Form:
   - For Service / Software / Digital / Legal / Consulting firms, acquiring office furniture / IT equipment
     is NEVER classified as INVENTORY (resale goods). It is classified as FIXED_ASSET (PPE, IAS 16) if
     at or above the capitalization threshold, or OPERATING_EXPENSE (IAS 1) if below threshold and non-bulk.
   - For Trading / Retail firms, items matching their active product catalog are classified as INVENTORY (IAS 2).
2. Capitalization Thresholds:
   - Single item >= PKR 50,000 -> Capitalize to PPE (IAS 16).
   - Single item < PKR 50,000, but Bulk Acquisition >= PKR 100,000 -> Capitalize as aggregated block (IAS 16.9).
   - Single item < PKR 50,000 and Non-Bulk (< PKR 100,000) -> Direct expense (IAS 1).
   - Consumables (stationery, printer paper, pantry, cleaning) -> Never capitalize -> OPERATING_EXPENSE (IAS 1).
3. Explicit Purpose:
   - Explicit "for resale" / "to resell" -> INVENTORY (IAS 2).
   - Explicit "for office use" / "for internal use" / "for staff" -> FIXED_ASSET / OPERATING_EXPENSE.
4. Clarification Gating:
   - When confidence >= 0.65 -> requires_clarification = False (no patronizing questions).
   - Only when confidence < 0.65 (e.g. IT reseller buying laptops without stated purpose) -> requires_clarification = True.
5. Deterministic Fail-safe:
   - Authoritative deterministic fallback when LLM is unavailable or disabled.
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

# Statutory & Materiality Thresholds (PKR)
CAPITALIZATION_SINGLE_ITEM_THRESHOLD_PKR: float = 50_000.0
CAPITALIZATION_BULK_THRESHOLD_PKR: float = 100_000.0
CLARIFICATION_CONFIDENCE_THRESHOLD: float = 0.65

# Service / Agency business indicators
SERVICE_BUSINESS_KEYWORDS: frozenset[str] = frozenset({
    "software",
    "software_house",
    "software house",
    "digital",
    "digital_creators",
    "digital creators",
    "agency",
    "media",
    "consulting",
    "consultancy",
    "legal",
    "law",
    "law firm",
    "advocate",
    "marketing",
    "digital marketing",
    "clinic",
    "medical",
    "hospital",
    "accounting",
    "audit",
    "tax",
    "studio",
    "design",
    "it_services",
    "it services",
    "education",
    "school",
    "saas",
    "creative",
})

# Trading / Retail business indicators
TRADING_BUSINESS_KEYWORDS: frozenset[str] = frozenset({
    "trading",
    "retail",
    "retailer",
    "wholesale",
    "wholesaler",
    "distributor",
    "dealer",
    "reseller",
    "shop",
    "store",
    "supermarket",
    "mart",
    "showroom",
    "merchandise",
    "hardware store",
    "electronics store",
    "furniture showroom",
    "furniture store",
})

# Durable Office Equipment & IT Hardware (IAS 16 PPE candidates)
DURABLE_FURNITURE_KEYWORDS: frozenset[str] = frozenset({
    "table", "tables", "desk", "desks", "chair", "chairs", "workstation",
    "workstations", "cabinet", "cabinets", "shelf", "shelves", "sofa",
    "sofas", "furniture", "conference table", "reception desk",
})

DURABLE_IT_KEYWORDS: frozenset[str] = frozenset({
    "laptop", "laptops", "computer", "computers", "pc", "pcs", "macbook",
    "monitor", "monitors", "screen", "screens", "server", "servers",
    "printer", "printers", "scanner", "scanners", "router", "routers",
    "switch", "switches", "networking equipment", "ups", "projector",
})

DURABLE_MACHINERY_KEYWORDS: frozenset[str] = frozenset({
    "air conditioner", "ac", "generator", "refrigerator", "fridge",
    "photocopier", "water dispenser", "camera", "studio light",
})

ALL_DURABLE_ITEMS: frozenset[str] = (
    DURABLE_FURNITURE_KEYWORDS | DURABLE_IT_KEYWORDS | DURABLE_MACHINERY_KEYWORDS
)

# Consumable Office Supplies (Never capitalize under IAS 1)
CONSUMABLE_KEYWORDS: frozenset[str] = frozenset({
    "paper", "ream", "reams", "a4", "stationery", "pen", "pens", "pencil",
    "toner", "cartridge", "ink", "cleaning", "detergent", "tea", "coffee",
    "sugar", "pantry", "stapler", "staples", "tape", "markers", "folders",
    "envelopes", "supplies", "notebook", "notebooks", "tissue", "tissues",
})

# Explicit purpose regexes
_RESALE_PURPOSE_REGEX = re.compile(
    r"\b(for\s+resale|to\s+resell|resale\s+stock|for\s+showroom|for\s+retail|for\s+stock|for\s+clients?\s+resale|merchandise\s+for\s+sale)\b",
    re.IGNORECASE,
)
_OFFICE_PURPOSE_REGEX = re.compile(
    r"\b(for\s+office\s+use|for\s+office|for\s+internal\s+use|for\s+our\s+studio|for\s+staff|for\s+employees?|for\s+administrative\s+use|for\s+business\s+use|operational\s+use)\b",
    re.IGNORECASE,
)
_PERSONAL_PURPOSE_REGEX = re.compile(
    r"\b(for\s+personal\s+use|for\s+home|for\s+owner|drawings?|personal\s+expense)\b",
    re.IGNORECASE,
)


@dataclass
class ContextualNatureResult:
    """The result of contextual accounting nature classification."""

    nature: str  # FIXED_ASSET | INVENTORY | OPERATING_EXPENSE | CONSUMABLE | SERVICE | EQUITY_DRAWING
    standard: str  # IAS 16 | IAS 2 | IAS 1 | IAS 38 | IFRS 15
    confidence: float  # 0.0 to 1.0
    requires_clarification: bool  # True iff confidence < 0.65
    clarification_question: Optional[str] = None
    reasoning: str = ""
    matched_catalog_item: Optional[Dict[str, Any]] = None
    matched_asset_item: Optional[Dict[str, Any]] = None
    is_capitalized: bool = False
    capitalization_threshold_applied: Optional[str] = None
    decision_source: str = "deterministic_fallback"  # llm | deterministic_fallback

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nature": self.nature,
            "standard": self.standard,
            "confidence": round(self.confidence, 4),
            "requires_clarification": self.requires_clarification,
            "clarification_question": self.clarification_question,
            "reasoning": self.reasoning,
            "matched_catalog_item": self.matched_catalog_item,
            "matched_asset_item": self.matched_asset_item,
            "is_capitalized": self.is_capitalized,
            "capitalization_threshold_applied": self.capitalization_threshold_applied,
            "decision_source": self.decision_source,
        }


def _extract_amount_and_quantity(
    query: str, preliminary: Dict[str, Any]
) -> Tuple[float, int, float]:
    """Extract total amount, quantity, and computed single item amount."""
    total_amount: float = 0.0
    quantity: int = 1

    # Check preliminary first
    raw_amount = preliminary.get("amount") or preliminary.get("total_amount")
    if raw_amount is not None:
        try:
            total_amount = float(raw_amount)
        except (ValueError, TypeError):
            total_amount = 0.0

    raw_qty = preliminary.get("quantity")
    if raw_qty is not None:
        try:
            quantity = max(1, int(raw_qty))
        except (ValueError, TypeError):
            quantity = 1

    # Fallback to regex extraction from query if preliminary is empty
    if total_amount <= 0:
        # Match PKR amounts: Rs. 150,000, 150000, 150k
        k_match = re.search(r"(?:rs\.?|pkr)?\s*([0-9]+(?:\.[0-9]+)?)\s*k\b", query, re.I)
        if k_match:
            try:
                total_amount = float(k_match.group(1)) * 1000.0
            except ValueError:
                pass
        else:
            amt_match = re.search(r"(?:rs\.?|pkr)?\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]{4,}(?:\.[0-9]+)?)", query, re.I)
            if amt_match:
                try:
                    total_amount = float(amt_match.group(1).replace(",", ""))
                except ValueError:
                    pass

    if quantity == 1 and raw_qty is None:
        # Check text words for numbers: "5 tables", "two tables", "10 laptops"
        words_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "twelve": 12, "dozen": 12, "twenty": 20,
        }
        word_qty_match = re.search(r"\b(" + "|".join(words_num.keys()) + r")\s+([a-zA-Z]+)", query, re.I)
        if word_qty_match:
            quantity = words_num[word_qty_match.group(1).lower()]
        else:
            num_qty_match = re.search(r"\b([0-9]+)\s+(?:units?|pieces?|desks?|tables?|chairs?|laptops?|pcs?|monitors?|boxes?|cartons?|reams?)", query, re.I)
            if num_qty_match:
                try:
                    quantity = max(1, int(num_qty_match.group(1)))
                except ValueError:
                    quantity = 1

    single_amount = total_amount / quantity if (quantity >= 1 and total_amount > 0) else total_amount
    return total_amount, quantity, single_amount


def _is_service_org(org_profile: Dict[str, Any]) -> bool:
    """Detect if the organization operates in service, agency, or digital sector."""
    b_type = str(org_profile.get("business_type") or "").lower()
    industry = str(org_profile.get("industry") or "").lower()
    name = str(org_profile.get("name") or "").lower()
    desc = str(org_profile.get("description") or "").lower()

    combined = f"{b_type} {industry} {name} {desc}"
    for kw in SERVICE_BUSINESS_KEYWORDS:
        if kw in combined:
            return True
    return False


def _is_trading_org(org_profile: Dict[str, Any]) -> bool:
    """Detect if the organization operates in retail, wholesale, or trading."""
    b_type = str(org_profile.get("business_type") or "").lower()
    industry = str(org_profile.get("industry") or "").lower()
    name = str(org_profile.get("name") or "").lower()
    desc = str(org_profile.get("description") or "").lower()

    combined = f"{b_type} {industry} {name} {desc}"
    for kw in TRADING_BUSINESS_KEYWORDS:
        if kw in combined:
            return True
    return False


def _match_catalog(item_text: str, catalog_items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Match item against registered catalog products."""
    if not item_text or not catalog_items:
        return None
    q_key = name_key(item_text)
    if not q_key:
        return None

    # Exact key match
    for prod in catalog_items:
        p_name = prod.get("name") or ""
        p_code = prod.get("product_code") or ""
        if name_key(p_name) == q_key or (p_code and name_key(p_code) == q_key):
            return prod

    # Normalized match
    matches = normalized_matches(catalog_items, item_text, field="name", min_key_length=3)
    if matches:
        return matches[0]
    return None


def _match_assets(item_text: str, asset_items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Match item against registered fixed assets or asset classes."""
    if not item_text or not asset_items:
        return None
    q_key = name_key(item_text)
    if not q_key:
        return None

    for asset in asset_items:
        a_name = asset.get("name") or ""
        a_class = asset.get("asset_class") or asset.get("category") or ""
        a_code = asset.get("asset_code") or ""
        if (
            name_key(a_name) == q_key
            or (a_class and name_key(a_class) == q_key)
            or (a_code and name_key(a_code) == q_key)
        ):
            return asset

    matches = normalized_matches(asset_items, item_text, field="name", min_key_length=3)
    if matches:
        return matches[0]
    return None


def _extract_item_text(query: str, preliminary: Dict[str, Any]) -> str:
    """Isolate the item description from preliminary or query."""
    item = preliminary.get("item_name") or preliminary.get("item")
    if item:
        return str(item).strip()

    # Heuristic extraction from query: remove common transaction verbs and prices
    cleaned = re.sub(
        r"^(?:purchasing|purchased|bought|buying|paid\s+for|ordered|order|acquired|acquisition\s+of)\s+",
        "",
        query.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:from|to|for|via|by|with)\s+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:rs\.?|pkr)?\s*[0-9,]+.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or query.strip()


def _is_durable_office_item(text: str) -> bool:
    """Check if item text refers to durable furniture, IT equipment, or office machinery."""
    text_lower = text.lower()
    words = re.findall(r"\b[a-zA-Z]+\b", text_lower)
    for w in words:
        if w in ALL_DURABLE_ITEMS:
            return True
    for phrase in ("air conditioner", "water dispenser", "conference table", "reception desk", "studio light"):
        if phrase in text_lower:
            return True
    return False


def _is_consumable_item(text: str) -> bool:
    """Check if item text refers to consumable office supplies."""
    text_lower = text.lower()
    words = re.findall(r"\b[a-zA-Z]+\b", text_lower)
    for w in words:
        if w in CONSUMABLE_KEYWORDS:
            return True
    return False


def _classify_contextual_nature_deterministic(
    query: str,
    org_profile: Dict[str, Any],
    catalog_items: List[Dict[str, Any]],
    asset_items: List[Dict[str, Any]],
    preliminary: Dict[str, Any],
) -> ContextualNatureResult:
    """Authoritative deterministic 4-dimensional convergence classification."""
    item_text = _extract_item_text(query, preliminary)
    total_amount, quantity, single_amount = _extract_amount_and_quantity(query, preliminary)

    matched_cat = _match_catalog(item_text, catalog_items)
    matched_ast = _match_assets(item_text, asset_items)

    is_service = _is_service_org(org_profile)
    is_trading = _is_trading_org(org_profile)
    org_name = org_profile.get("name") or "Entity"

    # 1. EXPLICIT PURPOSE OVERRIDE (Confidence = 1.0)
    if _RESALE_PURPOSE_REGEX.search(query):
        return ContextualNatureResult(
            nature="INVENTORY",
            standard="IAS 2",
            confidence=1.0,
            requires_clarification=False,
            clarification_question=None,
            reasoning=(
                f"Query explicitly states intended purpose for resale ('{item_text}'). "
                "Classified as trading inventory under IAS 2."
            ),
            matched_catalog_item=matched_cat,
            matched_asset_item=matched_ast,
            is_capitalized=False,
            capitalization_threshold_applied=None,
            decision_source="deterministic_fallback",
        )

    if _OFFICE_PURPOSE_REGEX.search(query):
        # Explicit office / operational use
        if _is_consumable_item(item_text):
            return ContextualNatureResult(
                nature="OPERATING_EXPENSE",
                standard="IAS 1",
                confidence=1.0,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Consumable supplies ('{item_text}') explicitly for office use do not meet "
                    "IAS 16 durability criteria (>12 months). Expensed under IAS 1 (Office Supplies)."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=False,
                capitalization_threshold_applied="CONSUMABLE_EXPENSE",
                decision_source="deterministic_fallback",
            )

        # Durable office equipment
        if single_amount >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD_PKR:
            return ContextualNatureResult(
                nature="FIXED_ASSET",
                standard="IAS 16",
                confidence=1.0,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Acquisition of '{item_text}' explicitly for office use exceeds single-item "
                    f"capitalization threshold (PKR {single_amount:,.2f} >= PKR {CAPITALIZATION_SINGLE_ITEM_THRESHOLD_PKR:,.2f}). "
                    "Capitalized to Property, Plant & Equipment (IAS 16)."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=True,
                capitalization_threshold_applied="SINGLE_ITEM_GE_50K",
                decision_source="deterministic_fallback",
            )
        elif total_amount >= CAPITALIZATION_BULK_THRESHOLD_PKR:
            return ContextualNatureResult(
                nature="FIXED_ASSET",
                standard="IAS 16",
                confidence=1.0,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Bulk acquisition of '{item_text}' explicitly for office use exceeds aggregate "
                    f"block capitalization threshold (PKR {total_amount:,.2f} >= PKR {CAPITALIZATION_BULK_THRESHOLD_PKR:,.2f}). "
                    "Capitalized as an aggregated asset block under IAS 16.9."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=True,
                capitalization_threshold_applied="BULK_GE_100K",
                decision_source="deterministic_fallback",
            )
        else:
            return ContextualNatureResult(
                nature="OPERATING_EXPENSE",
                standard="IAS 1",
                confidence=1.0,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Office item '{item_text}' is below single-item capitalization threshold (PKR 50k) "
                    "and non-bulk (< PKR 100k). Expensed directly under IAS 1 materiality convention."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=False,
                capitalization_threshold_applied="DIRECT_EXPENSE_LT_50K",
                decision_source="deterministic_fallback",
            )

    if _PERSONAL_PURPOSE_REGEX.search(query):
        return ContextualNatureResult(
            nature="EQUITY_DRAWING",
            standard="IAS 1",
            confidence=0.95,
            requires_clarification=False,
            clarification_question=None,
            reasoning=f"Query explicitly indicates personal drawing by owner for '{item_text}'. Debit Account 3200 (Owner Drawings).",
            matched_catalog_item=matched_cat,
            matched_asset_item=matched_ast,
            is_capitalized=False,
            capitalization_threshold_applied=None,
            decision_source="deterministic_fallback",
        )

    # 2. CONSUMABLES CHECK (Never capitalize unless held as resale inventory by a stationery dealer)
    if _is_consumable_item(item_text) and not (is_trading and matched_cat):
        return ContextualNatureResult(
            nature="OPERATING_EXPENSE",
            standard="IAS 1",
            confidence=0.95,
            requires_clarification=False,
            clarification_question=None,
            reasoning=(
                f"Item '{item_text}' is consumable office supplies. Under IAS 1 / IAS 16.6, supplies "
                "with useful life < 12 months are expensed directly (Account 6140/6190)."
            ),
            matched_catalog_item=matched_cat,
            matched_asset_item=matched_ast,
            is_capitalized=False,
            capitalization_threshold_applied="CONSUMABLE_EXPENSE",
            decision_source="deterministic_fallback",
        )

    # 3. SERVICE / AGENCY SECTOR REASONING (e.g. Software House, Digital Creators, Legal, Marketing)
    if is_service and _is_durable_office_item(item_text):
        # Service firms do NOT trade furniture or computers. Office equipment is PPE or direct expense.
        if single_amount >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD_PKR:
            return ContextualNatureResult(
                nature="FIXED_ASSET",
                standard="IAS 16",
                confidence=0.95,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Entity '{org_name}' operates as a service/agency business. Primary operations generate "
                    f"service revenue; '{item_text}' is administrative/studio equipment held for operations, "
                    f"not resale stock (IAS 2). Meets single-item capitalization threshold (>= PKR {CAPITALIZATION_SINGLE_ITEM_THRESHOLD_PKR:,.2f}). "
                    "Capitalized as Property, Plant & Equipment (IAS 16) without clarification."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=True,
                capitalization_threshold_applied="SINGLE_ITEM_GE_50K",
                decision_source="deterministic_fallback",
            )
        elif total_amount >= CAPITALIZATION_BULK_THRESHOLD_PKR:
            return ContextualNatureResult(
                nature="FIXED_ASSET",
                standard="IAS 16",
                confidence=0.95,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Entity '{org_name}' operates as a service/agency business. '{item_text}' is operational "
                    f"office equipment. Under IAS 16.9 aggregation principle, bulk acquisition of PKR {total_amount:,.2f} "
                    f"(>= PKR {CAPITALIZATION_BULK_THRESHOLD_PKR:,.2f}) is capitalized as an aggregated asset block (IAS 16) "
                    "without clarification."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=True,
                capitalization_threshold_applied="BULK_GE_100K",
                decision_source="deterministic_fallback",
            )
        elif total_amount > 0 and single_amount < CAPITALIZATION_SINGLE_ITEM_THRESHOLD_PKR and total_amount < CAPITALIZATION_BULK_THRESHOLD_PKR:
            return ContextualNatureResult(
                nature="OPERATING_EXPENSE",
                standard="IAS 1",
                confidence=0.90,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Entity '{org_name}' acquired low-value operational equipment ('{item_text}') below the single-item "
                    f"threshold (PKR {single_amount:,.2f} < PKR 50,000) and non-bulk (< PKR 100,000). Expensed under IAS 1 materiality convention."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=False,
                capitalization_threshold_applied="DIRECT_EXPENSE_LT_50K",
                decision_source="deterministic_fallback",
            )
        else:
            # Amount unspecified but item is durable office equipment for service firm: default capitalize under IAS 16
            return ContextualNatureResult(
                nature="FIXED_ASSET",
                standard="IAS 16",
                confidence=0.90,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Service entity '{org_name}' acquiring durable office/studio equipment ('{item_text}'). "
                    "Classified as Property, Plant & Equipment (IAS 16) without asking intended use."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=True,
                capitalization_threshold_applied="DEFAULT_DURABLE_PPE",
                decision_source="deterministic_fallback",
            )

    # 4. TRADING / RETAIL SECTOR REASONING
    if is_trading:
        # Check if item matches their active catalog or core trading merchandise
        if matched_cat is not None:
            return ContextualNatureResult(
                nature="INVENTORY",
                standard="IAS 2",
                confidence=0.95,
                requires_clarification=False,
                clarification_question=None,
                reasoning=(
                    f"Entity '{org_name}' is a trading/retail business and '{item_text}' matches active product "
                    f"catalog item '{matched_cat.get('name')}'. Held for sale in ordinary course of business under IAS 2."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=False,
                capitalization_threshold_applied=None,
                decision_source="deterministic_fallback",
            )

        # If trading firm is in electronics / IT and buying laptops, or furniture store buying tables:
        # Check for hybrid ambiguity (e.g. IT reseller buying computers where purpose could be stock or internal)
        industry_text = f"{org_profile.get('business_type', '')} {org_profile.get('industry', '')} {org_name}".lower()
        is_it_reseller = any(kw in industry_text for kw in ("it reseller", "computer reseller", "electronics dealer", "hardware dealer", "it trading"))
        is_furniture_dealer = any(kw in industry_text for kw in ("furniture showroom", "furniture dealer", "furniture store", "furniture retail"))

        if (is_it_reseller and _is_durable_office_item(item_text) and any(kw in item_text.lower() for kw in DURABLE_IT_KEYWORDS)) or \
           (is_furniture_dealer and any(kw in item_text.lower() for kw in DURABLE_FURNITURE_KEYWORDS)):
            # Genuinely ambiguous without stated purpose!
            return ContextualNatureResult(
                nature="INVENTORY",
                standard="IAS 2 / IAS 16",
                confidence=0.55,  # < 0.65 triggers clarification
                requires_clarification=True,
                clarification_question=(
                    f"Are these {quantity} units of '{item_text}' intended for client resale stock (Inventory - IAS 2) "
                    "or for internal operational use (Fixed Asset - IAS 16)?"
                ),
                reasoning=(
                    f"Entity '{org_name}' operates as a dealer/reseller of related equipment. The purchase of '{item_text}' "
                    "could represent trading inventory for resale or capital equipment for business use. Clarification required."
                ),
                matched_catalog_item=matched_cat,
                matched_asset_item=matched_ast,
                is_capitalized=False,
                capitalization_threshold_applied=None,
                decision_source="deterministic_fallback",
            )

    # 5. ASSET REGISTER MATCH
    if matched_ast is not None and not is_trading:
        return ContextualNatureResult(
            nature="FIXED_ASSET",
            standard="IAS 16",
            confidence=0.92,
            requires_clarification=False,
            clarification_question=None,
            reasoning=(
                f"Item '{item_text}' matches existing fixed asset / asset class '{matched_ast.get('name')}'. "
                "Classified as Property, Plant & Equipment under IAS 16."
            ),
            matched_catalog_item=matched_cat,
            matched_asset_item=matched_ast,
            is_capitalized=True,
            capitalization_threshold_applied="MATCHED_ASSET_REGISTER",
            decision_source="deterministic_fallback",
        )

    # 6. GENUINELY AMBIGUOUS OR UNRECOGNIZED ITEMS
    # If item is completely novel, no catalog match, no asset match, and not clearly categorized
    return ContextualNatureResult(
        nature="OPERATING_EXPENSE",
        standard="IAS 1",
        confidence=0.50,  # < 0.65 triggers clarification
        requires_clarification=True,
        clarification_question=(
            f"What is the intended economic use for '{item_text}' — resale inventory (IAS 2), "
            "fixed operational asset (IAS 16), or general business operating expense (IAS 1)?"
        ),
        reasoning=(
            f"Item '{item_text}' cannot be unambiguously categorized from organization profile "
            f"('{org_name}') or live registers. Confidence is below statutory threshold (0.65)."
        ),
        matched_catalog_item=matched_cat,
        matched_asset_item=matched_ast,
        is_capitalized=False,
        capitalization_threshold_applied=None,
        decision_source="deterministic_fallback",
    )


async def classify_contextual_nature(
    query: str,
    org_profile: Dict[str, Any],
    catalog_items: List[Dict[str, Any]],
    asset_items: List[Dict[str, Any]],
    preliminary: Dict[str, Any],
    *,
    client: Any = None,
    timeout: Optional[float] = None,
) -> ContextualNatureResult:
    """Classify the accounting nature using the 4-Dimensional Convergence Engine.

    Convergence tensor:
        Accounting Nature = Φ(Q_Query, P_OrgProfile, C_ProductCatalog, R_AssetRegister)

    Args:
        query: Raw user message or transaction text.
        org_profile: Dict containing organization profile, business_type, industry, name.
        catalog_items: List of active products in catalog.
        asset_items: List of registered fixed assets / asset classes.
        preliminary: Preliminary extracted transaction attributes (amount, quantity, etc.).
        client: Optional LLM client (injected or retrieved from orchestrator).
        timeout: Maximum duration before falling back to deterministic classification.

    Returns:
        ContextualNatureResult with authoritative accounting nature, standard, and confidence.
    """
    from app.config import get_settings

    settings = get_settings()
    llm_enabled = (
        getattr(settings, "llm_contextual_nature_enabled", False)
        or getattr(settings, "llm_item_nature_enabled", False)
        or getattr(settings, "llm_classification_enabled", False)
    )

    if not llm_enabled:
        return _classify_contextual_nature_deterministic(
            query=query,
            org_profile=org_profile,
            catalog_items=catalog_items,
            asset_items=asset_items,
            preliminary=preliminary,
        )

    # If LLM is enabled, attempt LLM decision with fail-safe degradation
    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()

        item_text = _extract_item_text(query, preliminary)
        total_amount, quantity, single_amount = _extract_amount_and_quantity(query, preliminary)

        prompt = (
            "YOU ARE THE SENIOR CHARTERED ACCOUNTANT (FCA) & FINANCIAL CONTROLLER.\n"
            "Apply the 4-Dimensional Convergence Engine (IAS 16 vs IAS 2 vs IAS 1) to determine the "
            "economic nature and accounting treatment for this acquisition.\n\n"
            f"TRANSACTION QUERY: {query}\n"
            f"ITEM IDENTIFIED: {item_text} (Qty: {quantity}, Total: PKR {total_amount:,.2f}, Unit: PKR {single_amount:,.2f})\n"
            f"ORGANIZATION PROFILE: {json.dumps(org_profile, default=str)}\n"
            f"CATALOG PRODUCTS (Resale Inventory): {len(catalog_items)} items\n"
            f"FIXED ASSET REGISTER (PPE): {len(asset_items)} asset classes\n\n"
            "MANDATORY ACCOUNTING SPECIFICATIONS:\n"
            "1. Service / Software / Digital / Legal / Marketing firms acquiring office furniture, computers, "
            "or monitors NEVER classify as INVENTORY (resale goods). Classify as FIXED_ASSET (IAS 16) if >= PKR 50,000 "
            "or bulk >= PKR 100,000; otherwise OPERATING_EXPENSE (IAS 1). NEVER ask what is the intended use.\n"
            "2. Trading / Retail firms acquiring catalog goods classify as INVENTORY (IAS 2).\n"
            "3. Explicit 'for resale' -> INVENTORY (IAS 2); explicit 'for office use' -> FIXED_ASSET or OPERATING_EXPENSE.\n"
            "4. Only set requires_clarification=true when confidence < 0.65 (e.g. IT reseller buying laptops without purpose).\n\n"
            "Reply with STRICT JSON ONLY matching:\n"
            "{\n"
            '  "nature": "FIXED_ASSET|INVENTORY|OPERATING_EXPENSE|CONSUMABLE|SERVICE|EQUITY_DRAWING",\n'
            '  "standard": "IAS 16|IAS 2|IAS 1|IAS 38|IFRS 15",\n'
            '  "confidence": <float 0.0 to 1.0>,\n'
            '  "requires_clarification": <true|false>,\n'
            '  "clarification_question": "<question string or null>",\n'
            '  "is_capitalized": <true|false>,\n'
            '  "capitalization_threshold_applied": "<threshold code or null>",\n'
            '  "reasoning": "<accounting rationale narrative>"\n'
            "}"
        )

        call_timeout = timeout or getattr(settings, "llm_contextual_nature_timeout", 10.0)
        raw_reply = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt),
            timeout=call_timeout,
        )

        # Parse JSON
        match = re.search(r"\{.*\}", str(raw_reply or ""), re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            nature = str(parsed.get("nature") or "").strip().upper()
            standard = str(parsed.get("standard") or "").strip().upper()
            confidence = float(parsed.get("confidence") or 0.8)
            requires_clarification = bool(parsed.get("requires_clarification"))
            # Enforce invariant: requires_clarification is True iff confidence < 0.65
            if confidence >= CLARIFICATION_CONFIDENCE_THRESHOLD:
                requires_clarification = False
            elif confidence < CLARIFICATION_CONFIDENCE_THRESHOLD:
                requires_clarification = True

            clarification_question = parsed.get("clarification_question")
            if requires_clarification and not clarification_question:
                clarification_question = (
                    f"What is the intended economic use for '{item_text}' — resale inventory (IAS 2) "
                    "or operational fixed asset (IAS 16)?"
                )

            is_cap = bool(parsed.get("is_capitalized"))
            if nature == "FIXED_ASSET":
                is_cap = True

            return ContextualNatureResult(
                nature=nature,
                standard=standard,
                confidence=confidence,
                requires_clarification=requires_clarification,
                clarification_question=clarification_question if requires_clarification else None,
                reasoning=str(parsed.get("reasoning") or "").strip(),
                matched_catalog_item=_match_catalog(item_text, catalog_items),
                matched_asset_item=_match_assets(item_text, asset_items),
                is_capitalized=is_cap,
                capitalization_threshold_applied=parsed.get("capitalization_threshold_applied"),
                decision_source="llm",
            )
    except Exception as exc:  # noqa: BLE001 — fail-safe degradation to deterministic rules
        log.warning("contextual_nature.llm_fallback", error=str(exc)[:160])

    return _classify_contextual_nature_deterministic(
        query=query,
        org_profile=org_profile,
        catalog_items=catalog_items,
        asset_items=asset_items,
        preliminary=preliminary,
    )
