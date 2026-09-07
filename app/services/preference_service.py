"""
ERP AI Agent - Organization Preference Service (Work Stream F)
===============================================================
Learns durable per-organization defaults from clarification answers and
serves them back as authoritative context.  Writers are the trusted
service layer ONLY (ai.org_preferences is service-role-only, migration
053); clients never touch the table.

A preference is captured only from clearly preference-shaped answers -
never guessed from free-form text:

* payment mode      - "Was this paid in cash or on credit?"  -> payment_method
* nature decision   - "fixed asset / consumable / operating expense"
                      answers for a recurring item              -> transaction_nature
* tax category      - explicit tax-category answers             -> tax_category
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

import structlog

from app.database import fetch_many, fetch_one, insert_one, update_one

log = structlog.get_logger(__name__)

# database.py routes "ai_"-prefixed table names to the ai schema.
_TABLE = "ai_org_preferences"

# Preference-shaped question detectors (deterministic, no LLM).
_PAYMENT_RE = re.compile(r"cash or credit|paid in cash|on credit", re.I)
_NATURE_RE = re.compile(
    r"fixed asset|consumable|operating expense|inventory", re.I
)
_TAX_RE = re.compile(r"tax category|tax rate|inclusive|exclusive", re.I)
# Work Stream R3.2 — the capitalization decision question ("ORDINARY
# EXPENSE or CAPITALIZED ...") is preference-shaped PER PURPOSE: the
# purpose label appears inside the question text, so recurring purposes
# (e.g. repairs) stop re-asking once answered.
_CAPITALIZATION_RE = re.compile(r"ordinary expense or capitalized", re.I)

# Canonical preference keys.
KEY_PAYMENT_METHOD = "payment_method"
KEY_TRANSACTION_NATURE = "transaction_nature"
KEY_TAX_CATEGORY = "tax_category"
# Prefixed key namespace: capitalization:<PURPOSE_VALUE>.
CAPITALIZATION_KEY_PREFIX = "capitalization:"


def capture_preference_from_answer(
    question: str, answer: str
) -> Optional[Dict[str, str]]:
    """Map a clarification answer to a (key, value) preference, if shaped.

    Returns ``None`` for anything that is not a durable org-level default
    (amounts, party names and one-off details are never preferences).
    """
    text = (answer or "").strip()
    if not text or len(text) > 60:
        return None
    low = text.lower()

    if _PAYMENT_RE.search(question or ""):
        if "credit" in low or "on account" in low:
            return {"key": KEY_PAYMENT_METHOD, "value": "CREDIT"}
        if "cash" in low:
            return {"key": KEY_PAYMENT_METHOD, "value": "CASH"}
        return None

    # Work Stream R3.2 — capitalization decision, learned PER PURPOSE.
    # Checked BEFORE the nature detector: the capitalization question
    # text itself contains "fixed asset", which would otherwise be
    # mistaken for a nature answer.
    if _CAPITALIZATION_RE.search(question or ""):
        from app.reasoning import purpose_for_label

        purpose_value = purpose_for_label(question or "")
        if not purpose_value:
            return None
        if low in ("a", "1") or "subscription" in low or "ordinary" in low or "expense" in low:
            value = "EXPENSE"
        elif low in ("b", "c", "2", "3") or "capitali" in low or "asset" in low:
            value = "CAPITALIZE"
        else:
            return None
        return {
            "key": f"{CAPITALIZATION_KEY_PREFIX}{purpose_value}",
            "value": value,
        }

    if _NATURE_RE.search(question or ""):
        if "fixed asset" in low:
            return {"key": KEY_TRANSACTION_NATURE, "value": "FIXED_ASSET"}
        if "consumable" in low:
            return {"key": KEY_TRANSACTION_NATURE, "value": "CONSUMABLE"}
        if "operating expense" in low or "expense" in low:
            return {"key": KEY_TRANSACTION_NATURE, "value": "OPERATING_EXPENSE"}
        if "inventory" in low or "stock" in low:
            return {"key": KEY_TRANSACTION_NATURE, "value": "INVENTORY"}
        return None

    if _TAX_RE.search(question or ""):
        return {"key": KEY_TAX_CATEGORY, "value": text}

    return None


def preference_key_for_question(question: str) -> Optional[str]:
    """Which preference key (if any) a clarification question asks about."""
    q = question or ""
    # R3.2: the capitalization question is checked BEFORE the nature
    # detector (its text contains "fixed asset").
    if _CAPITALIZATION_RE.search(q):
        from app.reasoning import purpose_for_label

        purpose_value = purpose_for_label(q)
        if purpose_value:
            return f"{CAPITALIZATION_KEY_PREFIX}{purpose_value}"
    if _PAYMENT_RE.search(q):
        return KEY_PAYMENT_METHOD
    if _NATURE_RE.search(q):
        return KEY_TRANSACTION_NATURE
    if _TAX_RE.search(q):
        return KEY_TAX_CATEGORY
    return None


async def get_preference(
    organization_id: Any, key: str
) -> Optional[Dict[str, Any]]:
    """Return the stored preference row for (org, key) or None."""
    rows = await fetch_many(
        _TABLE,
        filters={"organization_id": str(organization_id), "key": key},
        limit=1,
    )
    return rows[0] if rows else None


async def get_all_preferences(organization_id: Any) -> Dict[str, str]:
    """All learned preferences for the org as a flat {key: value} map."""
    rows = await fetch_many(
        _TABLE,
        filters={"organization_id": str(organization_id)},
        order="updated_at.desc",
        limit=100,
    )
    return {r["key"]: r["value"] for r in rows if r.get("key") and r.get("value")}


async def set_preference(
    organization_id: Any,
    key: str,
    value: str,
    *,
    source: str = "learned",
    confidence: float = 0.8,
) -> Dict[str, Any]:
    """Upsert a preference - search-before-insert, never a blind insert.

    An explicit user answer (source='user_set') always overwrites a
    learned one; a learned answer never overwrites a user-set one.
    """
    existing = await get_preference(organization_id, key)
    if existing:
        if existing.get("source") == "user_set" and source != "user_set":
            log.info(
                "preference.user_set_kept",
                key=key,
                org=str(organization_id),
            )
            return existing
        return await update_one(
            _TABLE,
            row_id=existing["id"],
            data={
                "value": value,
                "source": source,
                "confidence": confidence,
                "updated_at": "now()",
            },
        )
    return await insert_one(
        _TABLE,
        data={
            "organization_id": str(organization_id),
            "key": key,
            "value": value,
            "source": source,
            "confidence": confidence,
        },
    )


async def record_answer_preference(
    organization_id: Any,
    question: str,
    answer: str,
) -> Optional[Dict[str, Any]]:
    """Capture hook: store the preference when the answer is shaped for it.

    Called by the agent when a clarification round completes.  Never
    raises - a preference-capture failure must not affect the run.
    """
    try:
        shaped = capture_preference_from_answer(question, answer)
        if not shaped:
            return None
        row = await set_preference(
            organization_id, shaped["key"], shaped["value"], source="learned"
        )
        log.info(
            "preference.captured",
            org=str(organization_id),
            key=shaped["key"],
            value=shaped["value"],
        )
        return row
    except Exception as exc:  # noqa: BLE001 - capture is best-effort
        log.warning("preference.capture_failed", error=str(exc)[:200])
        return None
