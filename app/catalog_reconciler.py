"""Semantic Catalog Reconciler.

Reconciles purchased and sold line items against catalog products and services:
- Detects packaging variants (e.g. "Box of 10 Logitech Mice" vs catalog "Logitech Mouse"
  with packaging multiplier 10).
- Distinguishes physical resale goods (product_id) from service offerings (service_id).
- Prevents one-off office expenses (e.g. printer toner, batteries, coffee) from being
  created as catalog products (IAS 1 / Account 6190).
- Recommends matching existing items with high semantic similarity (>= 0.90) rather
  than blindly asking to create new products.
- Enforces strict grounding (1-based candidate indexing, no hallucinated IDs).
- Fail-open graceful degradation to deterministic matching when LLM offline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import difflib
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

log = structlog.get_logger(__name__)


@dataclass
class CatalogReconciliationResult:
    """The result of reconciling an item description against the catalog."""

    action: str  # "match_product" | "match_service" | "create_product" | "create_service" | "expense_only" | "ask"
    matched_id: Optional[str] = None
    matched_name: Optional[str] = None
    matched_type: Optional[str] = None  # "product" | "service"
    product_code: Optional[str] = None
    service_code: Optional[str] = None
    packaging_multiplier: int = 1
    packaging_unit: Optional[str] = None
    base_item_name: Optional[str] = None
    suggested_name: Optional[str] = None
    is_inventory: bool = False
    is_stock_tracked: bool = False
    confidence: float = 1.0
    reasoning: str = ""
    candidate_matches: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# One-off Office Expense & Consumable Patterns (IAS 1 / Account 6190)
# ---------------------------------------------------------------------------
_OFFICE_CONSUMABLE_PATTERNS = re.compile(
    r"\b("
    r"toner|printer toner|cartridge|ink cartridge|printer ink|drum unit|"
    r"batter(?:y|ies)|aaa batteries?|aa batteries?|9v batter(?:y|ies)|"
    r"coffee|coffee beans|tea bags?|green tea|sugar|creamer|milk for office|"
    r"donuts?|cookies?|biscuits?|snacks? for office|water bottles?|drinking water|"
    r"stationery|paper clips?|stapler|staples?|sticky notes?|post-it|"
    r"whiteboard markers?|highlighters?|pens? for office|erasers?|notepads?|"
    r"photocopy paper|printer paper|paper reams?|reams? of paper|a4 paper|"
    r"cleaning detergent|hand soap|bleach|mop|broom|trash bags?|dustbin bags?|paper towels?"
    r")\b",
    re.IGNORECASE,
)

# Service keywords
_SERVICE_KEYWORDS = re.compile(
    r"\b("
    r"service|services|consulting|consultancy|retainer|maintenance|support|"
    r"development|software development|audit|tax advisory|legal advice|training|"
    r"installation|design|marketing agency|cleaning service|security service|"
    r"annual maintenance|sla contract|subscription"
    r")\b",
    re.IGNORECASE,
)

# Common plural-to-singular normalizations
_PLURAL_MAP = {
    "mice": "mouse",
    "pens": "pen",
    "pencils": "pencil",
    "reams": "ream",
    "boxes": "box",
    "chairs": "chair",
    "desks": "desk",
    "tables": "table",
    "cables": "cable",
    "monitors": "monitor",
    "laptops": "laptop",
    "printers": "printer",
    "cartridges": "cartridge",
    "batteries": "battery",
    "mugs": "mug",
    "cups": "cup",
    "bottles": "bottle",
    "cans": "can",
    "units": "unit",
    "items": "item",
    "pieces": "piece",
    "books": "book",
    "notebooks": "notebook",
    "bags": "bag",
    "cartons": "carton",
}

# Conflict categories: words that should never match each other
_CONFLICT_WORDS: List[Set[str]] = [
    {"mouse", "mice", "keyboard"},
    {"laptop", "desktop", "server"},
    {"printer", "scanner"},
    {"chair", "table", "desk", "sofa", "bed"},
    {"honda", "yamaha", "suzuki", "toyota"},
    {"black", "white", "red", "blue"},
]


def _normalize_token(token: str) -> str:
    """Normalize token by lowercasing and stripping plurals."""
    t = token.lower().strip()
    if t in _PLURAL_MAP:
        return _PLURAL_MAP[t]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _tokenize(text: str) -> List[str]:
    """Extract significant lowercase tokens."""
    tokens = []
    for raw in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        if len(raw) < 2:
            continue
        tok = _normalize_token(raw)
        if tok:
            tokens.append(tok)
    return tokens


def _has_conflict(toks1: Set[str], toks2: Set[str]) -> bool:
    """Return True if the two token sets contain conflicting noun/brand tokens."""
    for conflict_set in _CONFLICT_WORDS:
        intersect1 = toks1 & conflict_set
        intersect2 = toks2 & conflict_set
        if intersect1 and intersect2 and intersect1 != intersect2:
            return True
    return False


def compute_semantic_similarity(item_desc: str, candidate_name: str) -> float:
    """Compute semantic similarity (0.0 to 1.0) between an item and a catalog name.

    Accounts for token overlap, sequence similarity, and plural normalization,
    while strictly penalizing conflicting distinct products (e.g. mouse vs keyboard).
    """
    s1 = str(item_desc or "").strip().lower()
    s2 = str(candidate_name or "").strip().lower()

    if not s1 or not s2:
        return 0.0

    if s1 == s2:
        return 1.0

    toks1 = set(_tokenize(s1))
    toks2 = set(_tokenize(s2))

    if not toks1 or not toks2:
        return 0.0

    # Strict conflict check: e.g. "Logitech Mouse" vs "Logitech Keyboard"
    if _has_conflict(toks1, toks2):
        return 0.20

    shared = toks1 & toks2
    total = toks1 | toks2

    # SUBSET CONTAINMENT GATE (as established in product_matching.py):
    # If all significant tokens of the shorter name appear in the longer name
    # without conflict, the item is a match (e.g. "Dell Latitude 5420 Laptop i7"
    # contains all tokens of "Dell Latitude 5420", and "Logitech Wireless Mouse M185"
    # contains "Logitech Mouse").
    if (toks1 <= toks2 or toks2 <= toks1) and len(shared) >= 1:
        score = max(0.92, min(0.98, 0.90 + 0.02 * len(shared)))
        return round(score, 3)

    # Overlap metrics
    jaccard = len(shared) / len(total) if total else 0.0
    dice = (2.0 * len(shared)) / (len(toks1) + len(toks2))

    # Sequence similarity on normalized strings
    seq_ratio = difflib.SequenceMatcher(None, s1, s2).ratio()

    # Weighted combination
    combined = (dice * 0.65) + (seq_ratio * 0.35)
    return round(combined, 3)


def parse_packaging_variant(text: str) -> Tuple[Optional[str], int, Optional[str]]:
    """Parse packaging variants from an item description.

    Returns (packaging_unit, packaging_multiplier, base_item_name).
    Example: "Box of 10 Logitech Mice" -> ("Box", 10, "Logitech Mouse")
    """
    clean = str(text or "").strip()

    # Pattern 1: "Box of 10 Logitech Mice", "Carton of 25 A4 Paper", "Pack of 12 Pens"
    m1 = re.search(
        r"^(?:a\s+|an\s+)?(box|carton|pack|package|bundle|case|dozen|set|ctn|doz|pkg|bag|crate|pallet)"
        r"\s+(?:of\s+)?(\d+)\s*(?:pcs|pieces|units|items|reams|cans|bottles)?\s*(?:of\s+)?(.+)$",
        clean,
        re.IGNORECASE,
    )
    if m1:
        unit = m1.group(1).title()
        mult = int(m1.group(2))
        base = m1.group(3).strip()
        base_norm = _normalize_base_name(base)
        return unit, mult, base_norm

    # Pattern 2: "10-pack USB Cables", "12 pack Pilot Pens", "10x Logitech Mouse"
    m2 = re.search(
        r"^(\d+)\s*(?:-|x|\*|\s+)?(pack|box|carton|case|bundle|doz|pcs)\s+(?:of\s+)?(.+)$",
        clean,
        re.IGNORECASE,
    )
    if m2:
        mult = int(m2.group(1))
        unit = m2.group(2).title()
        base = m2.group(3).strip()
        base_norm = _normalize_base_name(base)
        return unit, mult, base_norm

    # Pattern 3: "Dozen Chairs", "Dozen Coffee Mugs"
    m3 = re.search(r"^(?:a\s+)?dozen\s+(?:of\s+)?(.+)$", clean, re.IGNORECASE)
    if m3:
        base = m3.group(1).strip()
        base_norm = _normalize_base_name(base)
        return "Dozen", 12, base_norm

    # Pattern 4: Suffix variant: "Logitech Mouse (Box of 10)", "Pilot Pens (Pack of 12)"
    m4 = re.search(
        r"^(.+?)\s*[\(\[]?\s*(?:box|carton|pack|package|bundle|case)\s+of\s+(\d+)\s*(?:pcs|pieces|units)?\s*[\)\]]?$",
        clean,
        re.IGNORECASE,
    )
    if m4:
        base = m4.group(1).strip()
        mult = int(m4.group(2))
        base_norm = _normalize_base_name(base)
        return "Box", mult, base_norm

    return None, 1, None


def _normalize_base_name(name: str) -> str:
    """Normalize plural nouns at the end of base item name (e.g. Mice -> Mouse)."""
    words = name.split()
    if not words:
        return name
    last = words[-1].lower()
    if last in _PLURAL_MAP:
        words[-1] = _PLURAL_MAP[last].title()
    elif len(last) > 3 and last.endswith("s") and not last.endswith("ss"):
        words[-1] = last[:-1].title()
    return " ".join(words)


def is_office_consumable_expense(item_description: str) -> bool:
    """Check if item is a one-off office consumable (IAS 1 / Account 6190)."""
    return bool(_OFFICE_CONSUMABLE_PATTERNS.search(item_description or ""))


def is_service_description(item_description: str) -> bool:
    """Check if item description indicates a service offering."""
    return bool(_SERVICE_KEYWORDS.search(item_description or ""))


async def reconcile_catalog_item(
    item_description: str,
    is_inventory: bool,
    catalog_products: List[Dict[str, Any]],
    catalog_services: List[Dict[str, Any]],
    *,
    client: Any = None,
    timeout: Optional[float] = None,
) -> CatalogReconciliationResult:
    """Reconcile an incoming item against existing catalog products and services.

    Handles packaging variants, distinguishes physical goods from services,
    prevents one-off office expense catalog bloat, and matches high similarity (>= 0.90).
    """
    clean_desc = str(item_description or "").strip()
    products = list(catalog_products or [])
    services = list(catalog_services or [])

    # Check LLM availability via config settings
    use_llm = False
    try:
        from app.config import get_settings
        settings = get_settings()
        use_llm = bool(getattr(settings, "semantic_catalog_reconciler_enabled", True))
    except Exception:
        use_llm = False

    # 1. Deterministic reconciliation pass
    det_res = _deterministic_reconcile(clean_desc, is_inventory, products, services)

    # Consumable guard is authoritative under IAS 1 (prevents catalog bloat)
    if det_res.action == "expense_only":
        return det_res

    # If LLM is disabled or offline, return deterministic result
    if not use_llm and client is None:
        return det_res

    # 2. LLM Semantic Analyst pass (if enabled / client provided)
    try:
        if client is None:
            from app.ai_orchestrator import get_client
            client = get_client()

        llm_timeout = timeout or 8.0
        llm_res = await _llm_reconcile(
            item_desc=clean_desc,
            is_inventory=is_inventory,
            products=products,
            services=services,
            client=client,
            timeout=llm_timeout,
        )
        if llm_res is not None:
            return llm_res
    except Exception as exc:
        log.warning("catalog_reconciler.llm_fallback", error=str(exc)[:160])

    return det_res


def _deterministic_reconcile(
    item_desc: str,
    is_inventory: bool,
    products: List[Dict[str, Any]],
    services: List[Dict[str, Any]],
) -> CatalogReconciliationResult:
    """Deterministic, highly accurate catalog reconciliation."""
    # 1. Office Consumable & One-off Expense Guard:
    # Non-trading, one-off purchases (e.g. printer toner, batteries, coffee) must NEVER
    # be registered as permanent inventory products under IAS 1 / Account 6190.
    if is_office_consumable_expense(item_desc):
        has_catalog_match = any(
            compute_semantic_similarity(item_desc, str(p.get("name") or "")) >= 0.85
            for p in products
        )
        if not has_catalog_match:
            return CatalogReconciliationResult(
                action="expense_only",
                matched_id=None,
                matched_name=None,
                matched_type=None,
                packaging_multiplier=1,
                packaging_unit=None,
                base_item_name=item_desc,
                suggested_name=item_desc.title(),
                is_inventory=False,
                is_stock_tracked=False,
                confidence=0.95,
                reasoning="One-off office supply/consumable (IAS 1 / Account 6190). "
                          "Should not be registered as a permanent catalog product.",
            )

    # 2. Packaging Variant Parsing:
    pkg_unit, pkg_mult, base_name = parse_packaging_variant(item_desc)
    search_term = base_name if base_name else item_desc

    # 3. Check for matching products if is_inventory is True or if item is physical
    best_prod_sim = 0.0
    best_prod = None

    for p in products:
        p_name = str(p.get("name") or "")
        sim = compute_semantic_similarity(search_term, p_name)
        if sim > best_prod_sim:
            best_prod_sim = sim
            best_prod = p

    # If packaging variant matched an existing product:
    if best_prod and (best_prod_sim >= 0.85 if base_name else best_prod_sim >= 0.90):
        return CatalogReconciliationResult(
            action="match_product",
            matched_id=str(best_prod.get("id") or ""),
            matched_name=str(best_prod.get("name") or ""),
            matched_type="product",
            product_code=best_prod.get("product_code"),
            packaging_multiplier=pkg_mult,
            packaging_unit=pkg_unit,
            base_item_name=str(best_prod.get("name") or ""),
            suggested_name=str(best_prod.get("name") or ""),
            is_inventory=True,
            is_stock_tracked=bool(best_prod.get("is_stock_tracked", True)),
            confidence=round(best_prod_sim, 2),
            reasoning=(
                f"Matched existing catalog product '{best_prod.get('name')}' "
                f"with high semantic similarity ({best_prod_sim:.2f})"
                + (f" as packaging variant ({pkg_unit} of {pkg_mult})." if pkg_unit else ".")
            ),
        )

    # 4. Service Matching:
    is_service = is_service_description(item_desc) or (not is_inventory and not products)
    if is_service and services:
        best_serv_sim = 0.0
        best_serv = None
        for s in services:
            s_name = str(s.get("name") or "")
            sim = compute_semantic_similarity(item_desc, s_name)
            if sim > best_serv_sim:
                best_serv_sim = sim
                best_serv = s

        if best_serv and best_serv_sim >= 0.90:
            return CatalogReconciliationResult(
                action="match_service",
                matched_id=str(best_serv.get("id") or ""),
                matched_name=str(best_serv.get("name") or ""),
                matched_type="service",
                service_code=best_serv.get("service_code"),
                packaging_multiplier=1,
                packaging_unit=None,
                base_item_name=str(best_serv.get("name") or ""),
                suggested_name=str(best_serv.get("name") or ""),
                is_inventory=False,
                is_stock_tracked=False,
                confidence=round(best_serv_sim, 2),
                reasoning=f"Matched existing service '{best_serv.get('name')}' with high semantic similarity ({best_serv_sim:.2f}).",
            )

    # 5. Fallback Creation Actions
    if is_service and not is_inventory:
        return CatalogReconciliationResult(
            action="create_service",
            matched_id=None,
            matched_name=None,
            matched_type="service",
            packaging_multiplier=1,
            packaging_unit=None,
            base_item_name=item_desc,
            suggested_name=item_desc.title(),
            is_inventory=False,
            is_stock_tracked=False,
            confidence=0.85,
            reasoning="Service offering without matching existing service in catalog; propose creating service.",
        )

    if is_inventory:
        return CatalogReconciliationResult(
            action="create_product",
            matched_id=None,
            matched_name=None,
            matched_type="product",
            packaging_multiplier=pkg_mult,
            packaging_unit=pkg_unit,
            base_item_name=base_name or item_desc,
            suggested_name=(base_name or item_desc).title(),
            is_inventory=True,
            is_stock_tracked=True,
            confidence=0.85,
            reasoning="Physical trading inventory item without matching catalog product; propose creating product.",
        )

    # Consumables / expense item fallback
    if is_office_consumable_expense(item_desc):
        return CatalogReconciliationResult(
            action="expense_only",
            matched_id=None,
            matched_name=None,
            matched_type=None,
            packaging_multiplier=1,
            packaging_unit=None,
            base_item_name=item_desc,
            suggested_name=item_desc.title(),
            is_inventory=False,
            is_stock_tracked=False,
            confidence=0.90,
            reasoning="Office consumable / one-off operating expense.",
        )

    # Default to create product for physical items
    return CatalogReconciliationResult(
        action="create_product",
        matched_id=None,
        matched_name=None,
        matched_type="product",
        packaging_multiplier=pkg_mult,
        packaging_unit=pkg_unit,
        base_item_name=base_name or item_desc,
        suggested_name=(base_name or item_desc).title(),
        is_inventory=is_inventory,
        is_stock_tracked=is_inventory,
        confidence=0.80,
        reasoning="Distinct physical item without matching catalog product; propose creating product.",
    )


async def _llm_reconcile(
    *,
    item_desc: str,
    is_inventory: bool,
    products: List[Dict[str, Any]],
    services: List[Dict[str, Any]],
    client: Any,
    timeout: float,
) -> Optional[CatalogReconciliationResult]:
    """Invoke LLM to analyze catalog item semantic deduplication with strict grounding."""
    prod_lines = [
        f"{i}. Name={p.get('name')!r}, Code={p.get('product_code')}, StockTracked={p.get('is_stock_tracked')}"
        for i, p in enumerate(products[:40], start=1)
    ]
    serv_lines = [
        f"{i}. Name={s.get('name')!r}, Code={s.get('service_code')}"
        for i, s in enumerate(services[:40], start=1)
    ]

    instruction = (
        "You are an expert Catalog Deduplication and Inventory Analyst for an ERP system.\n"
        "Analyze the incoming line item description and reconcile it against existing catalog products and services.\n\n"
        "RULES:\n"
        "1. PACKAGING VARIANTS: Detect packaging variations (e.g. 'Box of 10 Logitech Mice' -> same as 'Logitech Mouse' "
        "with multiplier 10 and unit 'Box').\n"
        "2. ONE-OFF CONSUMABLES: Office expenses (printer toner, batteries, coffee, tea, paper clips) for internal consumption "
        "must be marked 'expense_only' and NEVER created as catalog products.\n"
        "3. HIGH SIMILARITY (>= 0.90): If an existing product or service is the same real-world good/service with minor "
        "wording/plural differences, match it rather than creating a duplicate.\n"
        "4. PRODUCT VS SERVICE: Distinguish physical resale goods (product) from service offerings (service).\n"
        "5. GROUNDING: matched_index must be the 1-based index from the respective list, or null.\n\n"
        "OUTPUT STRICT JSON ONLY:\n"
        '{"action": "<match_product|match_service|create_product|create_service|expense_only>", '
        '"matched_product_index": <1-based int or null>, "matched_service_index": <1-based int or null>, '
        '"packaging_multiplier": <int>, "packaging_unit": "<unit string or null>", '
        '"base_name": "<normalized item name>", "confidence": <float between 0 and 1>, "reasoning": "<short explanation>"}'
    )

    prompt = (
        f"{instruction}\n\n"
        f"ITEM DESCRIPTION: {item_desc}\n"
        f"IS_INVENTORY: {is_inventory}\n\n"
        f"CATALOG PRODUCTS:\n" + ("\n".join(prod_lines) if prod_lines else "(none)") + "\n\n"
        f"CATALOG SERVICES:\n" + ("\n".join(serv_lines) if serv_lines else "(none)")
    )

    raw = await asyncio.wait_for(client.generate_text_light(prompt=prompt), timeout=timeout)
    match = re.search(r"\{.*\}", str(raw or ""), re.S)
    if not match:
        return None

    try:
        payload = json.loads(match.group(0))
    except Exception:
        return None

    action = str(payload.get("action") or "").strip().lower()
    pkg_mult = int(payload.get("packaging_multiplier") or 1)
    pkg_unit = payload.get("packaging_unit")
    base_name = payload.get("base_name")
    confidence = float(payload.get("confidence") or 0.90)
    reasoning = str(payload.get("reasoning") or "").strip()

    if action == "expense_only":
        return CatalogReconciliationResult(
            action="expense_only",
            matched_id=None,
            matched_name=None,
            matched_type=None,
            packaging_multiplier=1,
            packaging_unit=None,
            base_item_name=item_desc,
            suggested_name=item_desc.title(),
            is_inventory=False,
            is_stock_tracked=False,
            confidence=confidence,
            reasoning=reasoning or "Office consumable expense.",
        )

    if action == "match_product":
        idx = payload.get("matched_product_index")
        if idx and isinstance(idx, int) and 1 <= idx <= len(products):
            matched_prod = products[idx - 1]
            return CatalogReconciliationResult(
                action="match_product",
                matched_id=str(matched_prod.get("id") or ""),
                matched_name=str(matched_prod.get("name") or ""),
                matched_type="product",
                product_code=matched_prod.get("product_code"),
                packaging_multiplier=pkg_mult,
                packaging_unit=pkg_unit,
                base_item_name=str(matched_prod.get("name") or ""),
                suggested_name=str(matched_prod.get("name") or ""),
                is_inventory=True,
                is_stock_tracked=bool(matched_prod.get("is_stock_tracked", True)),
                confidence=confidence,
                reasoning=reasoning or f"Matched catalog product '{matched_prod.get('name')}'.",
            )

    if action == "match_service":
        idx = payload.get("matched_service_index")
        if idx and isinstance(idx, int) and 1 <= idx <= len(services):
            matched_serv = services[idx - 1]
            return CatalogReconciliationResult(
                action="match_service",
                matched_id=str(matched_serv.get("id") or ""),
                matched_name=str(matched_serv.get("name") or ""),
                matched_type="service",
                service_code=matched_serv.get("service_code"),
                packaging_multiplier=1,
                packaging_unit=None,
                base_item_name=str(matched_serv.get("name") or ""),
                suggested_name=str(matched_serv.get("name") or ""),
                is_inventory=False,
                is_stock_tracked=False,
                confidence=confidence,
                reasoning=reasoning or f"Matched catalog service '{matched_serv.get('name')}'.",
            )

    if action == "create_service":
        return CatalogReconciliationResult(
            action="create_service",
            matched_id=None,
            matched_name=None,
            matched_type="service",
            packaging_multiplier=1,
            packaging_unit=None,
            base_item_name=base_name or item_desc,
            suggested_name=(base_name or item_desc).title(),
            is_inventory=False,
            is_stock_tracked=False,
            confidence=confidence,
            reasoning=reasoning or "New service creation.",
        )

    if action == "create_product":
        return CatalogReconciliationResult(
            action="create_product",
            matched_id=None,
            matched_name=None,
            matched_type="product",
            packaging_multiplier=pkg_mult,
            packaging_unit=pkg_unit,
            base_item_name=base_name or item_desc,
            suggested_name=(base_name or item_desc).title(),
            is_inventory=is_inventory,
            is_stock_tracked=is_inventory,
            confidence=confidence,
            reasoning=reasoning or "New product creation.",
        )

    return None
