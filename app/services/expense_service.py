"""
Expense Service — business logic for expense recording and classification.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import expense_repository as repo

log = structlog.get_logger(__name__)


async def create_expense(
    *,
    organization_id: uuid.UUID,
    expense_date: Optional[str] = None,
    payee_name: Optional[str] = None,
    description: str,
    subtotal: float,
    currency_code: str = "PKR",
    tax_total: float = 0.0,
    total: Optional[float] = None,
    supplier_id: Optional[uuid.UUID] = None,
    category_id: Optional[uuid.UUID] = None,
    payment_mode: str = "CASH",
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    exp_date = expense_date or date.today().isoformat()
    expense = await repo.create_expense(
        organization_id=organization_id,
        expense_date=exp_date,
        payee_name=payee_name or "",
        description=description,
        subtotal=subtotal,
        currency_code=currency_code,
        tax_total=tax_total,
        total=total,
        supplier_id=supplier_id,
        category_id=category_id,
        payment_mode=payment_mode,
        created_by=created_by,
    )
    log.info("expense.created", expense_id=expense["id"], total=expense.get("total"))
    return expense


async def get_expense(
    organization_id: uuid.UUID, *, expense_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_expense(organization_id, expense_id=expense_id)


async def classify_expense(
    *,
    description: str,
    amount: float,
    organization_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Classify an expense by description — returns suggested account type.

    Uses LLM reasoning against the organization's live Chart of Accounts when
    available, falling back safely to deterministic heuristics.
    """
    desc_clean = (description or "").strip()
    desc_lower = desc_clean.lower()

    # 1. LLM-first classification against the organization's live COA
    if organization_id:
        try:
            import asyncio
            import json
            import re
            from app.database import fetch_many
            from app.ai_orchestrator import get_client

            accounts = await fetch_many(
                "accounts",
                filters={"organization_id": str(organization_id), "account_type": "EXPENSE", "is_active": True},
                limit=100,
            )
            if accounts:
                client = get_client()
                if client:
                    account_summaries = [f"{a.get('code')}: {a.get('name')}" for a in accounts]
                    prompt = (
                        "You are an expert accounting ERP classifier. Select the best matching expense account "
                        f"for the transaction description: '{desc_clean}' (amount: {amount}).\n"
                        "Available Expense Accounts:\n"
                        + "\n".join(f"- {s}" for s in account_summaries[:40])
                        + "\n\nReply with ONLY a JSON object: {\"category\": \"<account_name>\", \"code\": \"<account_code>\", \"account_type\": \"EXPENSE\"}\n"
                        "If none of the existing accounts fit, return the best specific category name for a new sub-account "
                        "(e.g. 'Cleaning Expense', 'Office Refreshments') and set 'suggested_code': '6160'."
                    )
                    raw = await asyncio.wait_for(client.generate_text_light(prompt=prompt), timeout=4.0)
                    m = re.search(r"\{[^{}]*\}", str(raw or ""))
                    if m:
                        parsed = json.loads(m.group(0))
                        cat = str(parsed.get("category") or "").strip()
                        if cat:
                            res = {"category": cat, "account_type": "EXPENSE"}
                            if parsed.get("code"):
                                res["code"] = str(parsed.get("code"))
                            elif parsed.get("suggested_code"):
                                res["suggested_code"] = str(parsed.get("suggested_code"))
                            return res
        except Exception as exc:
            log.warning("classify_expense.llm_fallback", error=str(exc)[:160])

    # 2. Deterministic Fallback Heuristics
    if any(w in desc_lower for w in ["salary", "wage", "payroll"]):
        return {"category": "Salaries & Wages", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["rent", "lease"]):
        return {"category": "Rent", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["internet", "phone", "telecom"]):
        return {"category": "Communication", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["electricity", "gas", "water", "utility"]):
        return {"category": "Utilities", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["travel", "flight", "hotel", "transport", "uber", "ride", "taxi"]):
        return {"category": "Travel", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["computer", "laptop", "equipment", "hardware"]):
        return {"category": "Computer Equipment", "account_type": "ASSET"}
    if any(w in desc_lower for w in ["software", "subscription", "saas", "license"]):
        return {"category": "Software & Subscriptions", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["advert", "marketing", "promotion", "facebook", "post", "social media"]):
        return {"category": "Advertising Expense", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["clean", "cleaning", "janitor"]):
        return {"category": "Cleaning Expense", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["repair", "maintenance", "ac repair", "servicing"]):
        return {"category": "Repairs & Maintenance", "account_type": "EXPENSE"}
    if any(w in desc_lower for w in ["office", "stationery", "supply", "tea", "refreshment", "sugar"]):
        return {"category": "Office Supplies", "account_type": "EXPENSE"}
    return {"category": "General Expense", "account_type": "EXPENSE"}