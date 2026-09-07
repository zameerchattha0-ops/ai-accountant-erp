"""
ERP AI Agent — Context Manager
================================
Dynamically retrieves ONLY information relevant to the current request.

The entire database must NEVER be sent to Gemini.

Flow:  Intent → context_rules → context_sources → controlled tools/repos → relevant data
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.database import get_context_sources_for_intent
from app.models.schemas import AgentContext
from app.repositories import (
    account_repository,
    customer_repository,
    organization_repository,
    project_repository,
    report_repository,
    supplier_repository,
)
from app.services import preference_service

log = structlog.get_logger(__name__)


async def build_context(
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    intent: str,
    entity_hints: Optional[Dict[str, Any]] = None,
    clarification_history: Optional[List[Dict[str, str]]] = None,
) -> AgentContext:
    """Build the minimal runtime context for a given intent.

    *entity_hints* may contain pre-resolved entity names/IDs from the Planner
    (e.g. ``{"customer_name": "ABC Technologies", "amount": 20000.0}``).
    They are passed to Gemini as authoritative ``extracted_entities`` so it
    never has to re-parse (or re-ask) values the user already provided.

    *clarification_history* carries prior Q&A from earlier rounds of the
    same conversation — forwarded to Gemini so answered questions are
    never repeated.
    """
    hints = entity_hints or {}
    qa_history = clarification_history or []

    async def _isolated(label: str, factory, default):
        """Per-query error isolation: one failed context source degrades to
        its default (empty/blank) instead of killing the whole build."""
        try:
            return await factory()
        except Exception as exc:  # noqa: BLE001 - context is best-effort
            log.warning(
                "context_manager.source_failed", source=label, error=str(exc)
            )
            return default

    # 1. Organisation context, financial year/period and context rules are
    #    mutually independent - load them CONCURRENTLY (Work Stream A2).
    org, fy, period, ctx_info = await asyncio.gather(
        _isolated(
            "organization",
            lambda: organization_repository.get_organization(
                organization_id=organization_id
            ),
            None,
        ),
        _isolated(
            "financial_year",
            lambda: organization_repository.get_current_financial_year(
                organization_id
            ),
            None,
        ),
        _isolated(
            "accounting_period",
            lambda: organization_repository.get_open_accounting_period(
                organization_id
            ),
            None,
        ),
        _isolated("context_rules", lambda: get_context_sources_for_intent(intent), {}),
    )
    org_data = _safe_dict(org)

    required_slugs: List[str] = []
    if ctx_info.get("rule"):
        required_slugs = ctx_info["rule"].get("required_sources") or []

    # 2. Fetch only relevant data based on intent + hints - the seven
    #    domain fetches are independent of each other, so they run
    #    CONCURRENTLY with per-query error isolation.
    customers, suppliers, accounts, projects, bank_accounts, documents, reports, org_preferences = (
        await asyncio.gather(
            _isolated("customers", lambda: _fetch_customers(organization_id, hints, required_slugs), []),
            _isolated("suppliers", lambda: _fetch_suppliers(organization_id, hints, required_slugs), []),
            _isolated("accounts", lambda: _fetch_accounts(organization_id, hints, required_slugs), []),
            _isolated("projects", lambda: _fetch_projects(organization_id, hints, required_slugs), []),
            _isolated("bank_accounts", lambda: _fetch_bank_accounts(organization_id, required_slugs), []),
            _isolated("documents", lambda: _fetch_documents(organization_id, hints, required_slugs), []),
            _isolated("reports", lambda: _fetch_reports(organization_id, required_slugs), []),
            # Work Stream F: learned org defaults (authoritative context).
            _isolated(
                "org_preferences",
                lambda: preference_service.get_all_preferences(organization_id),
                {},
            ),
        )
    )

    context = AgentContext(
        organization=org_data,
        user={"user_id": str(user_id)},
        financial_year=_safe_dict(fy),
        accounting_period=_safe_dict(period),
        relevant_customers=customers,
        relevant_suppliers=suppliers,
        relevant_accounts=accounts,
        relevant_projects=projects,
        relevant_bank_accounts=bank_accounts,
        relevant_documents=documents,
        relevant_reports=reports,
        extracted_entities=hints,
        clarification_history=qa_history,
        org_preferences=org_preferences,
    )

    log.info(
        "context_manager.built",
        intent=intent,
        customers=len(customers),
        suppliers=len(suppliers),
        accounts=len(accounts),
        projects=len(projects),
        documents=len(documents),
    )
    return context


# ---- Private data-fetch helpers -------------------------------------------

async def _fetch_customers(
    org_id: uuid.UUID, hints: Dict[str, Any], slugs: List[str]
) -> List[Dict[str, Any]]:
    if "customer_master" not in slugs and not hints.get("customer_name"):
        return []
    name = hints.get("customer_name", "")
    if name:
        return await customer_repository.search_customers(org_id, query=name, limit=5)
    return []


async def _fetch_suppliers(
    org_id: uuid.UUID, hints: Dict[str, Any], slugs: List[str]
) -> List[Dict[str, Any]]:
    if "supplier_master" not in slugs and not hints.get("supplier_name"):
        return []
    name = hints.get("supplier_name", "")
    if name:
        return await supplier_repository.search_suppliers(org_id, query=name, limit=5)
    return []


async def _fetch_accounts(
    org_id: uuid.UUID, hints: Dict[str, Any], slugs: List[str]
) -> List[Dict[str, Any]]:
    if "chart_of_accounts" not in slugs:
        return []
    account_type = hints.get("account_type")
    return await account_repository.get_chart_of_accounts(
        org_id, account_type=account_type, limit=50
    )


async def _fetch_projects(
    org_id: uuid.UUID, hints: Dict[str, Any], slugs: List[str]
) -> List[Dict[str, Any]]:
    if "projects" not in slugs and not hints.get("project_name"):
        return []
    name = hints.get("project_name", "")
    if name:
        return await project_repository.search_projects(org_id, query=name, limit=5)
    return []


async def _fetch_bank_accounts(
    org_id: uuid.UUID, slugs: List[str]
) -> List[Dict[str, Any]]:
    # Always load bank accounts for payment/receipt/transfer intents
    payment_intents = {"record_receipt", "record_payment", "record_bank_transfer",
                       "create_bank_account", "list_bank_accounts", "record_expense_payment"}
    if "bank_accounts" not in slugs and not any(s in str(slugs) for s in payment_intents):
        # Fallback: also check if intent was passed as a slug hint
        return []
    return await organization_repository.get_bank_accounts(org_id)


async def _fetch_documents(
    org_id: uuid.UUID, hints: Dict[str, Any], slugs: List[str]
) -> List[Dict[str, Any]]:
    """Fetch relevant invoices / purchase bills if hinted.
    
    For receipt/payment intents, fetch open (unpaid/partially paid) documents
    so the AI can suggest allocation targets.
    """
    docs: List[Dict[str, Any]] = []
    customer_id = hints.get("customer_id")
    supplier_id = hints.get("supplier_id")

    if "invoices" in slugs:
        from app.repositories.invoice_repository import list_invoices
        if customer_id:
            # Fetch specific customer invoices
            invs = await list_invoices(org_id, customer_id=uuid.UUID(str(customer_id)), limit=10)
            docs.extend(invs)
        else:
            # Fetch open invoices for allocation context
            for status in ("ISSUED", "PARTIALLY_PAID"):
                invs = await list_invoices(org_id, status=status, limit=10)
                docs.extend(invs)

    if "purchase_bills" in slugs:
        from app.repositories.purchase_repository import list_purchase_bills
        if supplier_id:
            bills = await list_purchase_bills(org_id, supplier_id=uuid.UUID(str(supplier_id)), limit=10)
            docs.extend(bills)
        else:
            # Fetch open bills for allocation context
            for status in ("OPEN", "PARTIALLY_PAID"):
                bills = await list_purchase_bills(org_id, status=status, limit=10)
                docs.extend(bills)
    return docs


async def _fetch_reports(
    org_id: uuid.UUID, slugs: List[str]
) -> List[Dict[str, Any]]:
    """Pre-fetch report data if the intent requires it."""
    if not any(s in slugs for s in ("trial_balance", "balance_sheet", "income_statement", "general_ledger", "cash_flow")):
        return []
    # Return summary data only — full reports are fetched on demand
    report_data: List[Dict[str, Any]] = []
    if "trial_balance" in slugs:
        tb = await report_repository.get_trial_balance(org_id, limit=50)
        report_data.append({"type": "trial_balance", "data": tb})
    if "cash_flow" in slugs:
        cf = await report_repository.get_cash_flow(org_id, limit=100)
        report_data.append({"type": "cash_flow", "data": cf})
    return report_data if report_data else []


def _safe_dict(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return dict(row) if row else {}
