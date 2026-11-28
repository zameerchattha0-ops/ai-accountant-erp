"""
Accounting Service — orchestration of the accounting engine and journal repository.

This is the authoritative service for all accounting operations.
The accounting engine is deterministic — it does NOT depend on Gemini
to calculate debit/credit.  Gemini may *propose* accounts; this service
resolves and validates them.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import journal_repository as j_repo
from app.repositories import account_repository as a_repo
from app.repositories import organization_repository as org_repo

log = structlog.get_logger(__name__)


async def prepare_journal(
    *,
    organization_id: uuid.UUID,
    transaction_date: str,
    description: str,
    lines: List[Dict[str, Any]],
    source_type: Optional[str] = None,
    source_id: Optional[uuid.UUID] = None,
    currency_code: str = "PKR",
) -> Dict[str, Any]:
    """Prepare a DRAFT journal entry with lines.

    Each line must have: account_id, description, debit, credit.
    Optional: customer_id, supplier_id, project_id.

    Validates balance (total debit == total credit) before returning.
    """
    # Validate lines
    total_debit = sum(float(l.get("debit", 0)) for l in lines)
    total_credit = sum(float(l.get("credit", 0)) for l in lines)

    if len(lines) < 2:
        raise ValueError("Journal entry requires at least 2 lines")
    if abs(total_debit - total_credit) > 0.01:
        raise ValueError(
            f"Journal is not balanced: debit={total_debit}, credit={total_credit}"
        )
    if total_debit <= 0:
        raise ValueError("Journal amounts must be positive")

    # Create journal entry
    entry = await j_repo.create_journal_entry(
        organization_id=organization_id,
        transaction_date=transaction_date,
        description=description,
        source_type=source_type,
        source_id=source_id,
        currency_code=currency_code,
    )

    # Add lines
    created_lines = await j_repo.add_journal_lines(
        entry_id=uuid.UUID(entry["id"]),
        organization_id=organization_id,
        lines=lines,
    )

    log.info(
        "accounting.journal_prepared",
        entry_id=entry["id"],
        total_debit=total_debit,
        line_count=len(lines),
    )

    return {
        "entry": entry,
        "lines": created_lines,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }


async def validate_journal(*, entry_id: uuid.UUID) -> Dict[str, Any]:
    """Validate a DRAFT journal entry (transitions to VALIDATED)."""
    return await j_repo.validate_journal_entry(entry_id=entry_id)


async def post_journal(*, entry_id: uuid.UUID) -> Dict[str, Any]:
    """Post a VALIDATED journal entry (transitions to POSTED)."""
    return await j_repo.post_journal_entry(entry_id=entry_id)


async def _sync_reversed_linked_fixed_assets(
    *,
    entry_id: uuid.UUID,
    reversal_id: Optional[uuid.UUID],
    reversal_date: Optional[str],
    reason: Optional[str],
) -> List[Dict[str, Any]]:
    """Retire un-depreciated ACTIVE fixed assets whose purchase journal was reversed."""
    from datetime import date
    from app.database import fetch_many
    from app.repositories import fixed_asset_repository as fa_repo

    try:
        linked = await fetch_many(
            "fixed_assets",
            filters={"purchase_journal_entry_id": str(entry_id)},
            limit=100,
        )
    except Exception:
        return []

    if not isinstance(linked, list) or not linked:
        return []

    rev_date_iso = str(reversal_date or date.today().isoformat())[:10]
    synced: List[Dict[str, Any]] = []
    for asset in linked:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("status") or "").upper() != "ACTIVE":
            continue
        if float(asset.get("accumulated_depreciation") or 0.0) > 0:
            continue
        try:
            asset_uuid = uuid.UUID(str(asset["id"]))
            org_uuid = uuid.UUID(str(asset["organization_id"]))
            base_desc = str(asset.get("description") or asset.get("name") or "").strip()
            new_desc = (
                base_desc
                if "[Purchase Journal Reversed]" in base_desc
                else f"{base_desc} [Purchase Journal Reversed]".strip()
            )
            update_fields: Dict[str, Any] = {
                "status": "WRITTEN_OFF",
                "disposal_date": rev_date_iso,
                "disposal_amount": 0.0,
                "description": new_desc,
            }
            if reversal_id:
                update_fields["disposal_journal_entry_id"] = reversal_id
            await fa_repo.update_asset_by_id(asset_uuid, fields=update_fields)
            await fa_repo.record_asset_transaction(
                organization_id=org_uuid,
                asset_id=asset_uuid,
                transaction_type="WRITE_OFF",
                transaction_date=rev_date_iso,
                amount=float(asset.get("purchase_cost") or 0.0),
                journal_entry_id=reversal_id,
                details={
                    "source": "journal_reversal",
                    "reversed_journal_entry_id": str(entry_id),
                    "reason": reason or "Journal Reversed",
                },
            )
            synced.append({"id": str(asset_uuid), "name": asset.get("name"), "status": "WRITTEN_OFF"})
        except Exception as exc:  # noqa: BLE001 - reversal itself already succeeded in DB
            log.warning("accounting.reverse_asset_sync_failed", error=str(exc)[:160])
    return synced


async def reverse_journal(
    *,
    entry_id: uuid.UUID,
    reason: Optional[str] = None,
    reversal_date: Optional[str] = None,
    reversed_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Reverse a POSTED journal entry and synchronize linked un-depreciated fixed assets."""
    rev_res = await j_repo.reverse_journal_entry(
        entry_id=entry_id,
        reason=reason,
        reversal_date=reversal_date,
        reversed_by=reversed_by,
    )
    raw_rev_id = rev_res.get("result") if isinstance(rev_res, dict) else None
    rev_uuid: Optional[uuid.UUID] = None
    if isinstance(raw_rev_id, str) and raw_rev_id.strip():
        try:
            rev_uuid = uuid.UUID(raw_rev_id.strip())
        except ValueError:
            rev_uuid = None
    reversed_assets = await _sync_reversed_linked_fixed_assets(
        entry_id=entry_id,
        reversal_id=rev_uuid,
        reversal_date=reversal_date,
        reason=reason,
    )
    if isinstance(rev_res, dict) and reversed_assets:
        return {**rev_res, "reversed_assets": reversed_assets}
    return rev_res


async def get_entry(
    organization_id: uuid.UUID, *, entry_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await j_repo.get_journal_entry(organization_id, entry_id=entry_id)


async def get_lines(
    *, entry_id: uuid.UUID, organization_id: Optional[uuid.UUID] = None
) -> List[Dict[str, Any]]:
    return await j_repo.get_journal_lines(
        entry_id=entry_id, organization_id=organization_id
    )


async def resolve_account(
    organization_id: uuid.UUID,
    *,
    account_type: Optional[str] = None,
    account_code: Optional[str] = None,
    account_name: Optional[str] = None,
    exact_only: bool = False,
    required_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve an account by code or name within the organisation."""
    target_type = (required_type or account_type or "").strip().upper() or None

    if account_code:
        acc = await a_repo.get_account_by_code(organization_id, code=account_code)
        if acc and target_type and str(acc.get("account_type", "")).upper() != target_type:
            return None
        return acc

    if account_name:
        import re

        results = await a_repo.search_accounts(
            organization_id, query=account_name, limit=25
        )
        if target_type:
            results = [r for r in results if str(r.get("account_type", "")).upper() == target_type]

        q_low = account_name.lower().strip()
        # 1. Exact case-insensitive name match
        for r in results:
            if r.get("name", "").lower().strip() == q_low:
                return r

        if exact_only:
            return None

        # 2. Whole-word boundary match (prevents "Rent" matching "curRENT Portion...")
        tokens = [t for t in re.findall(r"[a-z0-9]{2,}", q_low) if t not in ("expense", "account")]
        if tokens:
            for r in results:
                rname = r.get("name", "").lower()
                if all(re.search(rf"\b{re.escape(tok)}", rname) for tok in tokens):
                    return r
            # Single-word token overlap if multi-word query had extras (e.g. "Rent Payable")
            for r in results:
                rname = r.get("name", "").lower()
                if any(re.search(rf"\b{re.escape(tok)}\b", rname) for tok in tokens):
                    return r

        return results[0] if results else None
    return None
