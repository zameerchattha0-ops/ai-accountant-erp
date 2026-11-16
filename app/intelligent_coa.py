"""Intelligent Chart of Accounts (COA) & Category Mapper.

Replaces hardcoded regex heuristics for modern business categories:
- Cloud & Hosting (AWS, GCP, Azure, DigitalOcean) -> 6210/6211 Cloud Infrastructure
- Software Subscriptions & SaaS (Figma, GitHub, Slack, Notion) -> 6220/6221 Software Subscriptions
- Legal & Professional Retainers -> 6310/6311 Legal & Professional
- Inbound Freight & Shipping on goods -> 5120 Inbound Freight (inventoriable under IAS 2.11)
- Annual Insurance -> 1420 Prepayments or 6410 Insurance
- Equipment & Vehicles -> 1510 Furniture, 1520 IT, 1530 Machinery, 1540 Vehicles under PPE

Strictly enforces:
- Statement-Section Invariant: ASSET category ledgers are NEVER parented under
  Current Assets (Receivables, Bank, Cash, Tax, Contra).
- Contra Guard: Contra-asset accounts (accumulated depreciation) are never debited as capital costs.
- Fail-open graceful degradation to existing account_resolution.py logic if LLM offline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

from app.account_resolution import (
    _ITEM_CATEGORY_RULES,
    _NON_CATEGORY_PARENT_PATTERNS,
    _TIE_KEYWORD_FLOOR,
    _category_regex_only,
    account_head,
    descriptive_keyword_match,
    is_category_parent,
    is_ppe_ledger_candidate,
)
from app.accounting_vocabulary import InvalidAccountingNature, account_shape

log = structlog.get_logger(__name__)


@dataclass
class COAResolutionResult:
    """The resolved or proposed General Ledger account mapping."""

    action: str  # "reuse" | "create" | "ask" | "unresolved"
    account_id: Optional[str] = None
    account_code: Optional[str] = None
    account_name: str = ""
    account_type: str = ""  # ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
    normal_balance: str = ""  # DEBIT, CREDIT
    parent_account_id: Optional[str] = None
    parent_account_name: Optional[str] = None
    is_new: bool = False
    category: str = ""
    confidence: float = 1.0
    reasoning: str = ""
    candidates: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Modern Category Definitions & Seeds (4-Tier IFRS Structure)
# ---------------------------------------------------------------------------
_MODERN_CATEGORY_RULES: Tuple[Tuple[str, str, str, str, str, str, str], ...] = (
    # (regex_pattern, category_name, canonical_account_name, base_code, account_type, normal_balance, ifrs_standard)
    (
        r"\b(aws|amazon web services|gcp|google cloud|azure|microsoft azure|digitalocean|digital ocean|linode|vultr|hetzner|cloudflare|heroku|cloud hosting|hosting server|cloud infrastructure|cloud compute|ec2|s3 bucket|vps server)\b",
        "Cloud Infrastructure",
        "Cloud & Hosting Infrastructure",
        "6210",
        "EXPENSE",
        "DEBIT",
        "IAS 1 (Technology & Cloud Infrastructure)",
    ),
    (
        r"\b(figma|github|slack|notion|google workspace|microsoft 365|office 365|adobe|jira|confluence|trello|asana|zoom|canva|saas|software subscription|gitlab|hubspot|datadog|salesforce)\b",
        "Software Subscriptions",
        "Software Subscriptions & SaaS",
        "6220",
        "EXPENSE",
        "DEBIT",
        "IAS 1 (Software Subscriptions & SaaS)",
    ),
    (
        r"\b(statutory audit|audit fees?|tax consultant|tax consultancy)\b",
        "Audit & Tax Consultancy",
        "Audit & Tax Consultancy Fees",
        "6320",
        "EXPENSE",
        "DEBIT",
        "IAS 1 (Audit & Tax Consultancy Fees)",
    ),
    (
        r"\b(legal fees?|lawyer|attorney|advocate|legal counsel|legal retainer|law firm|corporate filing|secp filing|notary|court fees?|litigation)\b",
        "Legal & Professional",
        "Legal & Professional Retainers",
        "6310",
        "EXPENSE",
        "DEBIT",
        "IAS 1 (Legal & Professional Services)",
    ),
    (
        r"\b(inbound freight|ocean freight|air cargo|cargo shipping|customs dut(?:y|ies)|port handling|customs clearance|clearance charges|clearing agent|freight on purchase|freight in|shipping for raw material|shipping for goods|freight on goods|shipping on inventory)\b",
        "Inbound Freight",
        "Inbound Freight & Port Handling",
        "5120",
        "EXPENSE",
        "DEBIT",
        "IAS 2.11 (Inventoriable Inbound Freight & Customs)",
    ),
)


# Specific PPE Sub-categories for IAS 16 (Plural-tolerant)
_PPE_CATEGORY_RULES: Tuple[Tuple[str, str, str, str], ...] = (
    # (regex_pattern, category_name, canonical_account_name, base_code)
    (
        r"\b(beds?|sofas?|couch(?:es)?|chairs?|tables?|desks?|cabinets?|shel(?:f|ves)|cupboards?|wardrobes?|furnitur\w*)\b",
        "Furniture & Fixtures",
        "Furniture & Fixtures",
        "1510",
    ),
    (
        r"\b(laptops?|desktops?|computers?|printers?|scanners?|monitors?|servers?|routers?|\bups\b|it equipment|keyboards?|m[ou]se|mice|macbooks?|thinkpads?|workstations?)\b",
        "Computer & IT Equipment",
        "Computer & IT Equipment",
        "1520",
    ),
    (
        r"\b(generators?|solars?|air conditioners?|\bacs?\b|inverters?|boilers?|pumps?|machiner(?:y|ies)|\bmachines?\b|industrial equipment|compressors?|\bcncs?\b|forklifts?|tractors?|sewing machines?|weighing scales?|\bplants?\b|hvac)\b",
        "Plant, Machinery & Generators",
        "Plant, Machinery & Generators",
        "1530",
    ),
    (
        r"\b(vehicle|vehicl|automobile|\bcars?\b|\bbikes?\b|motorcycles?|scooters?|\bvans?\b|\bbuses?\b|\btrucks?\b|lorr(?:y|ies)|pickups?|\bsuvs?\b|jeeps?|toyota|honda|suzuki|\bkia\b|hyundai|nissan|mitsubishi|mazda|isuzu|hino|mercedes|benz|\bbmw\b|audi|ford|chevrolet|renault|peugeot|volkswagen|\bvw\b|proton|changan|haval|\bjac\b|foton|dfsk|corolla|civic|hilux|fortuner|prado|land cruiser|sportage|tucson|hiace|cultus|mehran|baleno|picanto|elantra|sonata|accord|prius|aqua|vitz|yaris|wagon r|yamaha)\b",
        "Vehicles",
        "Motor Vehicles",
        "1540",
    ),
    (
        r"\b(buildings?|warehouses?|godowns?|factor(?:y|ies)|premises|showrooms?|\bland\b|\bplots?\b|real estate)\b",
        "Buildings & Land",
        "Buildings & Land",
        "1500",
    ),
)


def _is_contra_account(account: Dict[str, Any]) -> bool:
    """True if account is an accumulated depreciation or contra account."""
    name = str(account.get("name") or "").strip().lower()
    if any(p in name for p in ("accumulated depreciation", "contra")):
        return True
    acc_type = str(account.get("account_type") or "").strip().upper()
    normal_bal = str(account.get("normal_balance") or "").strip().upper()
    if acc_type == "ASSET" and normal_bal == "CREDIT":
        return True
    return False


def _next_free_code(base_code: str, chart_of_accounts: List[Dict[str, Any]]) -> str:
    """Find the highest existing code under the Tier-3 parent and increment by 1.

    Adheres to ACCOUNTING_SPECIFICATION_LLM_REASONING.md §3.3:
    If base code is 6210 and 6211 exists, propose 6212.
    If 6210 does not exist, return 6210.
    """
    existing_codes = set()
    for acc in chart_of_accounts or []:
        code = str(acc.get("account_code") or acc.get("code") or "").strip()
        if code.isdigit():
            existing_codes.add(int(code))

    try:
        base_num = int(base_code)
    except ValueError:
        return base_code

    if base_num not in existing_codes:
        return str(base_num)

    # Base code is taken; search higher numbers in the same tier block (e.g. 621x)
    prefix_len = len(base_code) - 1
    prefix = base_code[:prefix_len]
    series_codes = [c for c in existing_codes if str(c).startswith(prefix)]
    if series_codes:
        return str(max(series_codes) + 1)
    return str(base_num + 1)


def _find_valid_asset_parent(chart_of_accounts: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """Find a valid Property, Plant & Equipment / Non-Current Assets parent heading.

    Enforces the Statement-Section Invariant:
    ASSET category ledgers are NEVER parented under Current Assets
    (Receivables, Bank, Cash, Tax, Contra).
    """
    for acc in chart_of_accounts or []:
        if _is_contra_account(acc):
            continue
        acc_type = str(acc.get("account_type") or "").strip().upper()
        if acc_type != "ASSET":
            continue
        acc_name = str(acc.get("name") or "").strip().lower()
        if any(p in acc_name for p in _NON_CATEGORY_PARENT_PATTERNS):
            continue
        # Check for valid PPE headings
        if any(h in acc_name for h in (
            "property, plant", "property plant", "plant and equipment",
            "plant & equipment", "fixed asset", "non-current asset", "tangible asset"
        )):
            return str(acc.get("id") or ""), str(acc.get("name") or "")

    return None, None


def _find_valid_expense_parent(
    chart_of_accounts: List[Dict[str, Any]],
    is_cogs: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """Find a valid Expense parent heading."""
    keywords = ("cost of goods sold", "cogs", "direct cost") if is_cogs else (
        "administrative expense", "operating expense", "general & admin",
        "technology & infrastructure", "operating & admin"
    )
    for acc in chart_of_accounts or []:
        acc_type = str(acc.get("account_type") or "").strip().upper()
        if acc_type != "EXPENSE":
            continue
        acc_name = str(acc.get("name") or "").strip().lower()
        if any(k in acc_name for k in keywords):
            return str(acc.get("id") or ""), str(acc.get("name") or "")
    return None, None


def _match_existing_account(
    chart_of_accounts: List[Dict[str, Any]],
    target_name: str,
    target_type: str,
    category: str,
    item_desc: str,
) -> Optional[Dict[str, Any]]:
    """Match an existing account in chart_of_accounts adhering to contra & section invariants."""
    clean_target = target_name.strip().lower()
    clean_cat = category.strip().lower()

    # 1. Exact match on target name or category name
    for acc in chart_of_accounts or []:
        if target_type == "ASSET" and _is_contra_account(acc):
            continue
        acc_type = str(acc.get("account_type") or "").strip().upper()
        if acc_type != target_type:
            continue
        acc_name = str(acc.get("name") or "").strip().lower()
        if acc_name in (clean_target, clean_cat):
            return acc

    # 2. Substring or keyword containment
    candidates = []
    for acc in chart_of_accounts or []:
        if target_type == "ASSET" and _is_contra_account(acc):
            continue
        acc_type = str(acc.get("account_type") or "").strip().upper()
        if acc_type != target_type:
            continue
        acc_name = str(acc.get("name") or "").strip().lower()
        if clean_cat in acc_name or clean_target in acc_name:
            candidates.append(acc)

    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        # Tie-breaking with descriptive keyword match (> 0.75 floor)
        best_score = 0.0
        best_cand = None
        for cand in candidates:
            score = descriptive_keyword_match(item_desc, cand.get("name"))
            if score > best_score:
                best_score = score
                best_cand = cand
        if best_score > _TIE_KEYWORD_FLOOR and best_cand:
            return best_cand

    return None


async def resolve_or_propose_account(
    item_description: str,
    nature: str,
    chart_of_accounts: List[Dict[str, Any]],
    org_context: Dict[str, Any],
    *,
    client: Any = None,
    timeout: Optional[float] = None,
) -> COAResolutionResult:
    """Resolve an item to an existing chart-of-accounts ledger or propose creating one.

    Replaces hardcoded regex heuristics for modern business categories and enforces
    the Statement-Section Invariant and Contra Account Guard under IFRS.
    """
    item_desc = str(item_description or "").strip()
    clean_nature = str(nature or "").strip().upper()
    chart = list(chart_of_accounts or [])

    # Check LLM availability via config settings
    use_llm = False
    try:
        from app.config import get_settings
        settings = get_settings()
        use_llm = bool(getattr(settings, "intelligent_coa_mapper_enabled", True))
    except Exception:
        use_llm = False

    # 1. Deterministic Analysis First
    res = _deterministic_resolve(item_desc, clean_nature, chart, org_context)

    # If LLM is disabled or offline, or client not passed, return deterministic result
    if not use_llm and client is None:
        return res

    # 2. LLM Reasoning Seam (if enabled / client provided)
    try:
        if client is None:
            from app.ai_orchestrator import get_client
            client = get_client()

        llm_timeout = timeout or 8.0
        llm_result = await _llm_resolve_account(
            item_desc=item_desc,
            nature=clean_nature,
            chart_of_accounts=chart,
            org_context=org_context,
            client=client,
            timeout=llm_timeout,
        )
        if llm_result is not None:
            return llm_result
    except Exception as exc:
        log.warning("intelligent_coa.llm_fallback", error=str(exc)[:160])

    return res


def _deterministic_resolve(
    item_desc: str,
    nature: str,
    chart: List[Dict[str, Any]],
    org_context: Dict[str, Any],
) -> COAResolutionResult:
    """Deterministic, robust fallback resolution adhering to IFRS rules."""
    low_desc = item_desc.lower()

    # Rule 1: Modern Category Checks (Cloud, SaaS, Legal, Inbound Freight)
    for pattern, category, canonical_name, base_code, acc_type, normal_bal, ifrs in _MODERN_CATEGORY_RULES:
        if re.search(pattern, low_desc, re.IGNORECASE):
            existing = _match_existing_account(chart, canonical_name, acc_type, category, item_desc)
            if existing:
                return COAResolutionResult(
                    action="reuse",
                    account_id=str(existing.get("id") or ""),
                    account_code=str(existing.get("account_code") or existing.get("code") or ""),
                    account_name=str(existing.get("name") or ""),
                    account_type=acc_type,
                    normal_balance=normal_bal,
                    parent_account_id=existing.get("parent_account_id"),
                    is_new=False,
                    category=category,
                    confidence=0.98,
                    reasoning=f"Reusing existing ledger '{existing.get('name')}' for {category} ({ifrs}).",
                )

            is_cogs = (base_code.startswith("5"))
            parent_id, parent_name = _find_valid_expense_parent(chart, is_cogs=is_cogs)
            proposed_code = _next_free_code(base_code, chart)
            return COAResolutionResult(
                action="create",
                account_id=None,
                account_code=proposed_code,
                account_name=canonical_name,
                account_type=acc_type,
                normal_balance=normal_bal,
                parent_account_id=parent_id,
                parent_account_name=parent_name,
                is_new=True,
                category=category,
                confidence=0.95,
                reasoning=f"Proposing new ledger '{canonical_name}' (Code: {proposed_code}) under {category} ({ifrs}).",
            )

    # Rule 2: Annual Insurance vs Insurance Expense
    if re.search(r"\b(insurance|fire insurance|marine insurance|health insurance|vehicle insurance|insurance policy)\b", low_desc):
        is_prepaid = nature == "PREPAYMENT" or bool(re.search(r"\b(annual|prepaid|advance|12[- ]month)\b", low_desc))
        if is_prepaid:
            category = "Prepayments"
            canonical_name = "Prepaid Insurance"
            base_code = "1420"
            acc_type = "ASSET"
            normal_bal = "DEBIT"
            ifrs = "IAS 1 (Prepayments & Advances)"
            parent_id, parent_name = None, None  # Current asset, no PPE parent
        else:
            category = "Insurance"
            canonical_name = "Insurance Expense"
            base_code = "6410"
            acc_type = "EXPENSE"
            normal_bal = "DEBIT"
            ifrs = "IAS 1 (Insurance Expense)"
            parent_id, parent_name = _find_valid_expense_parent(chart, is_cogs=False)

        existing = _match_existing_account(chart, canonical_name, acc_type, category, item_desc)
        if existing:
            return COAResolutionResult(
                action="reuse",
                account_id=str(existing.get("id") or ""),
                account_code=str(existing.get("account_code") or existing.get("code") or ""),
                account_name=str(existing.get("name") or ""),
                account_type=acc_type,
                normal_balance=normal_bal,
                parent_account_id=existing.get("parent_account_id"),
                is_new=False,
                category=category,
                confidence=0.95,
                reasoning=f"Reusing existing ledger '{existing.get('name')}' for {category} ({ifrs}).",
            )

        proposed_code = _next_free_code(base_code, chart)
        return COAResolutionResult(
            action="create",
            account_id=None,
            account_code=proposed_code,
            account_name=canonical_name,
            account_type=acc_type,
            normal_balance=normal_bal,
            parent_account_id=parent_id,
            parent_account_name=parent_name,
            is_new=True,
            category=category,
            confidence=0.92,
            reasoning=f"Proposing new ledger '{canonical_name}' (Code: {proposed_code}) under {category} ({ifrs}).",
        )

    # Rule 3: Equipment & Vehicles under PPE (IAS 16)
    if nature == "FIXED_ASSET" or any(re.search(pat, low_desc) for pat, _, _, _ in _PPE_CATEGORY_RULES):
        for pattern, category, canonical_name, base_code in _PPE_CATEGORY_RULES:
            if re.search(pattern, low_desc):
                by_id = {str(a.get("id") or ""): a for a in chart if a.get("id")}
                ppe_candidates = [a for a in chart if is_ppe_ledger_candidate(a, by_id=by_id)]

                matched_ppe = _match_existing_account(ppe_candidates, canonical_name, "ASSET", category, item_desc)
                if matched_ppe:
                    return COAResolutionResult(
                        action="reuse",
                        account_id=str(matched_ppe.get("id") or ""),
                        account_code=str(matched_ppe.get("account_code") or matched_ppe.get("code") or ""),
                        account_name=str(matched_ppe.get("name") or ""),
                        account_type="ASSET",
                        normal_balance="DEBIT",
                        parent_account_id=matched_ppe.get("parent_account_id"),
                        is_new=False,
                        category=category,
                        confidence=0.98,
                        reasoning=f"Reusing existing PPE ledger '{matched_ppe.get('name')}' for {category} (IAS 16).",
                    )

                # Statement-Section Invariant: Must find a valid PPE parent, NEVER parent under Current Assets or Contra
                parent_id, parent_name = _find_valid_asset_parent(chart)
                proposed_code = _next_free_code(base_code, chart)
                return COAResolutionResult(
                    action="create",
                    account_id=None,
                    account_code=proposed_code,
                    account_name=canonical_name,
                    account_type="ASSET",
                    normal_balance="DEBIT",
                    parent_account_id=parent_id,
                    parent_account_name=parent_name,
                    is_new=True,
                    category=category,
                    confidence=0.95,
                    reasoning=f"Proposing new PPE ledger '{canonical_name}' (Code: {proposed_code}) under {category} (IAS 16).",
                )

    # Rule 4: Fallback based on canonical nature shape
    try:
        acc_type, norm_bal, base_code, ifrs = account_shape(nature)
    except InvalidAccountingNature:
        acc_type, norm_bal, base_code, ifrs = "EXPENSE", "DEBIT", "6100", "IAS 1 (General Operating Expense)"

    canonical_name = f"{item_desc.title()} Ledger" if item_desc else "General Operating Expense"
    existing = _match_existing_account(chart, canonical_name, acc_type, "General", item_desc)
    if existing:
        return COAResolutionResult(
            action="reuse",
            account_id=str(existing.get("id") or ""),
            account_code=str(existing.get("account_code") or existing.get("code") or ""),
            account_name=str(existing.get("name") or ""),
            account_type=acc_type,
            normal_balance=norm_bal,
            parent_account_id=existing.get("parent_account_id"),
            is_new=False,
            category="General",
            confidence=0.80,
            reasoning=f"Reusing existing ledger '{existing.get('name')}'.",
        )

    parent_id = None
    parent_name = None
    if acc_type == "ASSET":
        parent_id, parent_name = _find_valid_asset_parent(chart)
    elif acc_type == "EXPENSE":
        parent_id, parent_name = _find_valid_expense_parent(chart)

    proposed_code = _next_free_code(base_code, chart)
    return COAResolutionResult(
        action="create",
        account_id=None,
        account_code=proposed_code,
        account_name=canonical_name,
        account_type=acc_type,
        normal_balance=norm_bal,
        parent_account_id=parent_id,
        parent_account_name=parent_name,
        is_new=True,
        category="General",
        confidence=0.75,
        reasoning=f"Proposing new ledger '{canonical_name}' (Code: {proposed_code}).",
    )


async def _llm_resolve_account(
    *,
    item_desc: str,
    nature: str,
    chart_of_accounts: List[Dict[str, Any]],
    org_context: Dict[str, Any],
    client: Any,
    timeout: float,
) -> Optional[COAResolutionResult]:
    """Invoke LLM to reason on Chart of Accounts mapping under IFRS with strict grounding."""
    chart_lines = []
    by_id = {}
    for i, acc in enumerate(chart_of_accounts[:100], start=1):
        aid = str(acc.get("id") or "")
        by_id[str(i)] = acc
        by_id[aid] = acc
        is_contra = _is_contra_account(acc)
        chart_lines.append(
            f"{i}. Code={acc.get('account_code') or acc.get('code')}, Name={acc.get('name')!r}, "
            f"Type={acc.get('account_type')}, NormalBal={acc.get('normal_balance')}"
            f"{' [CONTRA]' if is_contra else ''}"
        )

    instruction = (
        "You are a Senior Chart of Accounts (COA) Analyst and Financial Controller for an IFRS ERP.\n"
        "Given the item description, accounting nature, organization context, and the chart of accounts, "
        "determine whether to REUSE an existing ledger or PROPOSE CREATING a new one under modern IFRS standards.\n\n"
        "MODERN CATEGORY RULES:\n"
        "- Cloud & Hosting (AWS, GCP, Azure, DigitalOcean) -> 6210/6211 Cloud Infrastructure (EXPENSE, DEBIT)\n"
        "- Software Subscriptions & SaaS (Figma, GitHub, Slack, Notion) -> 6220/6221 Software Subscriptions (EXPENSE, DEBIT)\n"
        "- Legal & Professional Retainers -> 6310/6311 Legal & Professional (EXPENSE, DEBIT)\n"
        "- Inbound Freight & Shipping on goods -> 5120 Inbound Freight (inventoriable under IAS 2.11, EXPENSE/COGS, DEBIT)\n"
        "- Annual Insurance -> 1420 Prepayments (ASSET, DEBIT) or 6410 Insurance Expense (EXPENSE, DEBIT)\n"
        "- Equipment & Vehicles -> 1510 Furniture, 1520 IT, 1530 Machinery, 1540 Vehicles under PPE (ASSET, DEBIT)\n\n"
        "STRICT INVARIANTS:\n"
        "1. STATEMENT-SECTION INVARIANT: An ASSET category ledger must NEVER be parented under Current Assets "
        "(Receivables, Bank, Cash, Tax, Contra). Only PPE / Non-Current headings qualify.\n"
        "2. CONTRA GUARD: Contra-asset accounts (accumulated depreciation) must NEVER be debited for asset acquisition costs.\n"
        "3. GROUNDING: If action is 'reuse', matched_index must be the 1-based index from the chart list below.\n\n"
        "OUTPUT STRICT JSON ONLY:\n"
        '{"action": "<reuse|create>", "matched_index": <1-based int or null>, "account_name": "<name>", '
        '"account_code": "<code>", "account_type": "<ASSET|EXPENSE>", "normal_balance": "<DEBIT|CREDIT>", '
        '"category": "<category name>", "parent_index": <1-based int or null>, "reasoning": "<short explanation>"}'
    )

    prompt = (
        f"{instruction}\n\n"
        f"ITEM: {item_desc}\n"
        f"NATURE: {nature}\n"
        f"ORG CONTEXT: {json.dumps(org_context or {})}\n\n"
        f"CHART OF ACCOUNTS:\n" + "\n".join(chart_lines)
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
    acc_type = str(payload.get("account_type") or "").strip().upper()
    norm_bal = str(payload.get("normal_balance") or "").strip().upper()
    category = str(payload.get("category") or "").strip()
    reasoning = str(payload.get("reasoning") or "").strip()

    if action == "reuse":
        idx = payload.get("matched_index")
        if not idx:
            return None
        try:
            pos = int(idx)
        except (ValueError, TypeError):
            return None
        if not (1 <= pos <= len(chart_of_accounts)):
            return None
        matched = chart_of_accounts[pos - 1]

        # CONTRA & STATEMENT-SECTION CHECK ON LLM OUTPUT
        if acc_type == "ASSET" and _is_contra_account(matched):
            log.warning("intelligent_coa.llm_contra_rejected", account=matched.get("name"))
            return None

        return COAResolutionResult(
            action="reuse",
            account_id=str(matched.get("id") or ""),
            account_code=str(matched.get("account_code") or matched.get("code") or ""),
            account_name=str(matched.get("name") or ""),
            account_type=acc_type or str(matched.get("account_type") or "EXPENSE"),
            normal_balance=norm_bal or str(matched.get("normal_balance") or "DEBIT"),
            parent_account_id=matched.get("parent_account_id"),
            is_new=False,
            category=category,
            confidence=0.95,
            reasoning=reasoning or f"Reused existing account '{matched.get('name')}'.",
        )

    elif action == "create":
        name = str(payload.get("account_name") or item_desc.title())
        code = str(payload.get("account_code") or "")
        parent_id = None
        parent_name = None

        parent_idx = payload.get("parent_index")
        if parent_idx and isinstance(parent_idx, int) and 1 <= parent_idx <= len(chart_of_accounts):
            candidate_parent = chart_of_accounts[parent_idx - 1]
            if acc_type == "ASSET":
                if not _is_contra_account(candidate_parent) and is_category_parent(candidate_parent, nature="ASSET"):
                    parent_id = str(candidate_parent.get("id") or "")
                    parent_name = str(candidate_parent.get("name") or "")
            else:
                parent_id = str(candidate_parent.get("id") or "")
                parent_name = str(candidate_parent.get("name") or "")

        # If model failed to set valid parent for ASSET, run deterministic parent lookup
        if acc_type == "ASSET" and not parent_id:
            parent_id, parent_name = _find_valid_asset_parent(chart_of_accounts)

        # Allocate next free code if needed
        if not code or any(
            str(a.get("account_code") or a.get("code") or "").strip() == code
            for a in chart_of_accounts
        ):
            code = _next_free_code(code or "6100", chart_of_accounts)

        return COAResolutionResult(
            action="create",
            account_id=None,
            account_code=code,
            account_name=name,
            account_type=acc_type or "EXPENSE",
            normal_balance=norm_bal or "DEBIT",
            parent_account_id=parent_id,
            parent_account_name=parent_name,
            is_new=True,
            category=category,
            confidence=0.92,
            reasoning=reasoning or f"Proposed new account '{name}' under {category}.",
        )

    return None
