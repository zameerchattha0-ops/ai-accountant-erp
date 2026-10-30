"""
ERP AI Agent — Permission-Based Tool Routing
===============================================
Checks whether the authenticated user has permission to execute a specific tool.

Flow:
  Tool slug
      ↓
  Load ai.permissions for all capabilities
      ↓
  Check user's role permissions against capability permissions
      ↓
  Check allowed_tools / denied_tools lists
      ↓
  Permit or deny

Role hierarchy (from organization_roles):
  OWNER > ADMIN > ACCOUNTANT > MANAGER > VIEWER

Capability mapping (from ai.permissions):
  sales           → create_quotation, create_invoice, create_credit_note, get_invoice
  purchases       → create_purchase_bill, create_purchase_return, get_purchase_bill
  expenses        → create_expense, classify_expense
  payments        → record_customer_receipt, record_supplier_payment, record_expense_payment
  reporting       → get_general_ledger, get_trial_balance, get_profit_loss, ...
  master_data     → create_customer, create_supplier, create_project, ...
  journal_management → prepare_journal, validate_journal, post_journal, reverse_journal
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Set

import structlog

from app.auth import AuthContext
from app.database import fetch_many

log = structlog.get_logger(__name__)

# Cached permission data, refreshed after _PERMISSIONS_CACHE_TTL_SECONDS.
# A process-lifetime cache meant a permission change (or a role edit) never
# took effect until the process restarted — and the AI worker never restarts,
# so it kept honouring a stale snapshot forever.
_permissions_cache: Optional[List[Dict[str, Any]]] = None
_permissions_cache_at: float = 0.0
_PERMISSIONS_CACHE_TTL_SECONDS = 60.0


async def _load_permissions() -> List[Dict[str, Any]]:
    """Load active permissions from ai.permissions, cached for a short TTL."""
    global _permissions_cache, _permissions_cache_at
    now = time.monotonic()
    if (
        _permissions_cache is not None
        and (now - _permissions_cache_at) < _PERMISSIONS_CACHE_TTL_SECONDS
    ):
        return _permissions_cache

    try:
        rows = await fetch_many(
            "ai_permissions",
            filters={"status": "ACTIVE"},
            limit=100,
        )
    except Exception:  # noqa: BLE001 - must not poison the cache permanently
        # A transient read failure (provider blip, cold start) previously
        # became a permanent failure once the value was cached.  Keep serving
        # the last good snapshot and retry after the TTL instead.
        if _permissions_cache is not None:
            log.warning("permissions.refresh_failed_serving_last_known")
            _permissions_cache_at = now
            return _permissions_cache
        raise

    _permissions_cache = rows
    _permissions_cache_at = now
    return _permissions_cache


_DEFAULT_TOOL_CAPABILITIES: Dict[str, Set[str]] = {
    # Sales
    "create_quotation": {"sales"},
    "create_invoice": {"sales"},
    "create_credit_note": {"sales"},
    "get_invoice": {"sales"},
    "get_quotation": {"sales"},
    # Purchases
    "create_purchase_order": {"purchases"},
    "get_purchase_order": {"purchases"},
    "create_purchase_bill": {"purchases"},
    "create_purchase_return": {"purchases"},
    "get_purchase_bill": {"purchases"},
    "update_document_status": {"purchases", "sales"},
    # Expenses
    "create_expense": {"expenses"},
    "classify_expense": {"expenses"},
    "list_expenses": {"expenses"},
    # Payments
    "record_customer_receipt": {"payments"},
    "record_supplier_payment": {"payments"},
    "record_expense_payment": {"payments"},
    # Master Data
    "create_customer": {"master_data"},
    "update_customer": {"master_data"},
    "create_supplier": {"master_data"},
    "update_supplier": {"master_data"},
    "create_product": {"master_data"},
    "update_product": {"master_data"},
    "delete_product": {"master_data"},
    "create_service": {"master_data"},
    "update_service": {"master_data"},
    "delete_service": {"master_data"},
    "create_project": {"master_data"},
    "create_fixed_asset": {"master_data", "assets"},
    # Journal Management
    "prepare_journal": {"journal_management"},
    "validate_journal": {"journal_management"},
    "post_journal": {"journal_management"},
    "reverse_journal": {"journal_management"},
    "create_compound_journal": {"journal_management"},
    "record_compound_journal": {"journal_management"},
    # Assets & Depreciation
    "run_asset_depreciation": {"assets", "journal_management"},
    "post_asset_disposal": {"assets", "journal_management"},
    # Cash purchases
    "record_cash_purchase": {"purchases", "payments"},
    # Loans Subsystem
    "record_loan": {"loans", "journal_management"},
    "record_loan_repayment": {"loans", "payments", "journal_management"},
    "list_loans": {"loans", "reporting"},
    "get_loan_schedule": {"loans", "reporting"},
    "check_due_loan_installments": {"loans", "reporting"},
    "record_loan_restructure": {"loans", "journal_management"},
    "write_off_loan": {"loans", "journal_management"},
    # Financial Health
    "calculate_health": {"reporting"},
    "get_health": {"reporting"},
    # Recurring Transactions
    "create_recurring_template": {"recurring", "journal_management", "master_data"},
    "get_recurring_templates": {"recurring", "reporting"},
    "get_recurring_template": {"recurring", "reporting"},
    "update_recurring_template": {"recurring", "journal_management", "master_data"},
    "generate_recurring": {"recurring", "journal_management"},
    "get_recurring_executions": {"recurring", "reporting"},
}


def _build_tool_capability_map(permissions: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Build a mapping: tool_slug -> set of capability names that allow it."""
    tool_caps: Dict[str, Set[str]] = {
        tool: set(caps) for tool, caps in _DEFAULT_TOOL_CAPABILITIES.items()
    }
    for perm in permissions:
        capability = perm.get("capability", "")
        allowed = perm.get("allowed_tools", [])
        for tool_slug in allowed:
            tool_caps.setdefault(tool_slug, set()).add(capability)
    return tool_caps


def _build_tool_deny_set(permissions: List[Dict[str, Any]]) -> Set[str]:
    """Build a set of tool slugs explicitly denied across all capabilities."""
    denied: Set[str] = set()
    for perm in permissions:
        for tool_slug in perm.get("denied_tools", []):
            denied.add(tool_slug)
    return denied


def _role_capability_map(role_permissions: List[str]) -> Set[str]:
    """Map role permission strings to AI capability names.

    Role permissions use format like:
      "accounting:full", "sales:manage", "reports:read", "ai:full"

    These map to AI capabilities:
      accounting:full  → journal_management, master_data
      sales:manage     → sales
      purchases:manage → purchases, expenses
      reports:read     → reporting
      ai:full          → all capabilities
      org:manage       → (org admin, not tool-level)
    """
    caps: Set[str] = set()
    for rp in role_permissions:
        domain, _, access = rp.partition(":")
        if domain == "ai" and access == "full":
            # Full AI access = all capabilities
            caps.update([
                "sales", "purchases", "expenses", "payments",
                "reporting", "master_data", "journal_management",
                "assets", "payroll", "loans", "recurring",
            ])
        elif domain == "accounting":
            caps.update([
                "journal_management", "master_data", "assets", "payroll",
                "loans", "recurring",
            ])
        elif domain == "sales":
            caps.add("sales")
        elif domain == "purchases":
            caps.update(["purchases", "expenses"])
        elif domain == "reports" and access in ("read", "full"):
            caps.add("reporting")
        elif domain == "customers":
            caps.add("master_data")
        elif domain == "suppliers":
            caps.add("master_data")
        elif domain == "projects":
            caps.add("master_data")
        elif domain in ("assets", "inventory", "products"):
            caps.update(["master_data", "assets"])
        elif domain in ("loans", "loan"):
            caps.update(["loans", "journal_management"])
        elif domain in ("recurring", "automation"):
            caps.update(["recurring", "journal_management"])
    return caps


# Tools that are always available (read-only, low-risk)
_ALWAYS_ALLOWED = {
    "search_customer", "get_customer", "get_customer_ledger",
    "search_supplier", "get_supplier", "get_supplier_ledger",
    "search_account", "get_chart_of_accounts",
    "get_invoice", "get_purchase_bill", "get_purchase_order", "get_quotation",
    "classify_expense", "list_expenses",
    "search_product", "search_fixed_asset", "get_fixed_asset",
    "search_service", "get_inventory_status",
    # Employees module: reads only — mutations stay capability-gated
    # (ai.permissions.master_data).
    "search_employee", "get_employee",
    # Loans & Recurring read-only tools
    "list_loans", "get_loan_schedule", "check_due_loan_installments",
    "get_health", "get_recurring_templates", "get_recurring_template",
    "get_recurring_executions",
}


def check_permission(
    tool_slug: str,
    *,
    auth: AuthContext,
    tool_capability_map: Dict[str, Set[str]],
    denied_tools: Set[str],
) -> bool:
    """Check if the authenticated user can execute a tool.

    Returns True if permitted, False if denied.
    """
    # Always allow read-only tools for authenticated users
    if tool_slug in _ALWAYS_ALLOWED:
        return True

    # Explicitly denied?
    if tool_slug in denied_tools:
        return False

    # Owner/Admin with ai:full or OWNER/ADMIN role gets full access to standard tools
    if "ai:full" in auth.role_permissions or auth.role_code in ("OWNER", "ADMIN"):
        return True

    # Find which capabilities allow this tool
    required_caps = tool_capability_map.get(tool_slug, set())
    if not required_caps:
        # Tool not in any capability — deny by default
        log.warning("permissions.no_capability", tool=tool_slug)
        return False

    # Check user's role capabilities
    user_caps = _role_capability_map(auth.role_permissions)

    # Check intersection
    if required_caps & user_caps:
        return True

    log.info(
        "permissions.denied",
        tool=tool_slug,
        user=str(auth.user_id),
        role=auth.role_code,
        required=list(required_caps),
        user_has=list(user_caps),
    )
    return False


async def authorize_tool(
    tool_slug: str,
    *,
    auth: AuthContext,
) -> bool:
    """High-level authorization check for a tool call.

    Loads permissions from DB (cached), builds maps, and checks permission.
    """
    permissions = await _load_permissions()
    tool_cap_map = _build_tool_capability_map(permissions)
    denied = _build_tool_deny_set(permissions)
    return check_permission(
        tool_slug,
        auth=auth,
        tool_capability_map=tool_cap_map,
        denied_tools=denied,
    )


def invalidate_cache():
    """Clear the cached permissions (call after permission changes)."""
    global _permissions_cache, _permissions_cache_at
    _permissions_cache = None
    _permissions_cache_at = 0.0
