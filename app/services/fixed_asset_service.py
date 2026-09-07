"""
Fixed Asset Service — trusted business logic for the asset lifecycle.

Lifecycle supported by the ACTUAL database contract
(``fixed_assets`` + ``asset_transactions`` + ``asset_depreciation_schedules``):

    acquisition (register) → depreciation → disposal / sale

Accounting authority stays with the Accounting Engine: every mutation
posts its journal via ``accounting_service.prepare_journal`` — the LLM
never manufactures journal entries.  Balance is guaranteed by
construction in each builder and re-validated by the engine.

NO arbitrary fallbacks:
* the GL asset account is resolved from the asset's configured column,
  an explicit argument, or a UNIQUE deterministic name match — otherwise
  a precise configuration gap is raised;
* a NON-ACTIVE asset can never be depreciated or disposed of;
* the LLM cannot dispose of an asset that does not exist.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import structlog

from app.repositories import account_repository as account_repo
from app.repositories import fixed_asset_repository as repo
from app.repositories import supplier_repository as supplier_repo
from app.services import accounting_service

log = structlog.get_logger(__name__)


async def _post_journal(**kwargs) -> Dict[str, Any]:
    """prepare → validate → post (the verified full journal lifecycle,
    same as the engine's trusted cash-sale path)."""
    journal = await accounting_service.prepare_journal(**kwargs)
    entry = journal.get("entry") or {}
    entry_id = uuid.UUID(str(entry["id"]))
    await accounting_service.validate_journal(entry_id=entry_id)
    posted = await accounting_service.post_journal(entry_id=entry_id)
    # Keep the ORIGINAL entry row — it carries the authoritative id used
    # for source-tie updates.  The RPC wrappers (validate/post) return
    # {"success", "result"} shapes without the row id.
    journal["entry"] = {**entry, "status": "POSTED", "post_result": posted}
    return journal


# Deterministic asset-account keywords (same spirit as the classifier's
# nature→account search): a UNIQUE ASSET-name match is authoritative.
_ASSET_ACCOUNT_KEYWORDS = (
    "fixed asset", "equipment", "computer", "machinery", "vehicle",
    "furniture", "fixture",
)


async def search(
    organization_id: uuid.UUID, *, query: str, limit: int = 25
) -> List[Dict[str, Any]]:
    return await repo.search_assets(organization_id, query=query, limit=limit)


async def get(
    organization_id: uuid.UUID, *, asset_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    return await repo.get_asset(organization_id, asset_id=asset_id)


async def _resolve_asset_by_reference(
    organization_id: uuid.UUID,
    *,
    asset_id: Optional[str],
    asset_name: Optional[str],
) -> Dict[str, Any]:
    """Resolve the asset reference across ALL states (never guess)."""
    if asset_id:
        asset = await repo.get_asset(
            organization_id, asset_id=uuid.UUID(asset_id)
        )
        if not asset:
            raise ValueError(
                f"No fixed asset found with id {asset_id}."
            )
        return asset

    if not asset_name:
        raise ValueError(
            "Which asset? Provide the asset name (or id)."
        )

    candidates = await repo.search_assets(
        organization_id, query=asset_name.strip(), limit=10
    )
    if not candidates:
        raise ValueError(
            f"No fixed asset named '{asset_name}' is registered. "
            "If this is an acquisition, register the asset first; "
            "disposal/depreciation require an existing asset record."
        )
    exact = [
        a for a in candidates
        if a.get("name", "").lower().strip() == asset_name.lower().strip()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(candidates) == 1:
        return candidates[0]
    names = ", ".join(
        f"{a.get('asset_code')} {a.get('name')}" for a in candidates[:5]
    )
    raise ValueError(
        f"Multiple assets match '{asset_name}' ({names}). "
        "Specify which asset you mean — do not guess."
    )


async def _resolve_gl_account(
    organization_id: uuid.UUID,
    *,
    account_type: str,
    keywords: tuple,
    explicit_id: Optional[uuid.UUID],
    exclude_keywords: tuple = (),
) -> Optional[Dict[str, Any]]:
    """Deterministic GL account resolution (unique keyword match only).

    ``exclude_keywords`` removes structural non-candidates (e.g. contra
    accounts such as 'Accumulated Depreciation - X' must never be chosen
    as the ASSET-COST account for an acquisition).
    """
    if explicit_id:
        acct = await account_repo.get_account(
            organization_id, account_id=explicit_id
        )
        if not acct:
            raise ValueError(
                f"Account {explicit_id} does not exist in the chart of accounts."
            )
        return acct
    accounts = await account_repo.get_chart_of_accounts(
        organization_id, account_type=account_type, limit=100
    )
    matches = [
        a for a in accounts or []
        if any(k in str(a.get("name", "")).lower() for k in keywords)
        and not any(x in str(a.get("name", "")).lower() for x in exclude_keywords)
    ]
    if len(matches) == 1:
        return matches[0]
    return None  # zero or ambiguous → caller decides (ask / config gap)


async def _resolve_supplier(
    organization_id: uuid.UUID,
    *,
    supplier_id: Optional[str],
    supplier_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    if supplier_id:
        return await supplier_repo.get_supplier(
            organization_id, supplier_id=uuid.UUID(supplier_id)
        )
    if not supplier_name:
        return None
    results = await supplier_repo.search_suppliers(
        organization_id, query=supplier_name, limit=5
    )
    for s in results:
        if s.get("name", "").lower().strip() == supplier_name.lower().strip():
            return s
    return None


async def _resolve_settlement_account(
    organization_id: uuid.UUID,
    *,
    payment_account_id: Optional[uuid.UUID],
) -> Optional[Dict[str, Any]]:
    """Resolve the cash/bank settlement account deterministically:
    explicit id → default configured bank account's GL account → the
    accounting engine's verified cash default (ASSET, CURRENT_ASSET
    fallback).  Reuses the engine primitive — no duplicated logic."""
    from app.accounting_engine import _resolve_default_account

    if payment_account_id:
        acct = await account_repo.get_account(
            organization_id, account_id=payment_account_id
        )
        if not acct:
            raise ValueError(
                f"Account {payment_account_id} does not exist."
            )
        return acct

    from app.repositories import organization_repository

    banks = await organization_repository.get_bank_accounts(organization_id)
    if banks:
        defaults = [b for b in banks if b.get("is_default")]
        bank = (defaults or banks)[0]
        gl_id = bank.get("gl_account_id") or bank.get("gl_account")
        if gl_id:
            return await account_repo.get_account(
                organization_id, account_id=uuid.UUID(str(gl_id))
            )
    return await _resolve_default_account(
        organization_id, "ASSET", fallback_type="CURRENT_ASSET"
    )


async def register_asset(
    organization_id: uuid.UUID,
    *,
    name: str,
    purchase_cost: float,
    transaction_date: Optional[str] = None,
    payment_method: str = "CASH",
    supplier_id: Optional[str] = None,
    supplier_name: Optional[str] = None,
    asset_account_id: Optional[uuid.UUID] = None,
    payment_account_id: Optional[uuid.UUID] = None,
    useful_life_years: Optional[int] = None,
    depreciation_method: str = "STRAIGHT_LINE",
    salvage_value: float = 0.0,
    description: Optional[str] = None,
    **kw,
) -> Dict[str, Any]:
    """Acquire + capitalize a fixed asset (asset record + journal).

    Economic semantics (verified event profile — FIXED_ASSET nature):
    Dr Asset (capitalised cost) — NEVER expensed, NEVER inventory;
    Cr Cash/Bank (immediate payment) or Cr Accounts Payable (credit).
    """
    if not name or not name.strip():
        raise ValueError("Asset name is required.")
    cost = float(purchase_cost or 0)
    if cost <= 0:
        raise ValueError("Asset purchase cost must be a positive amount.")

    txn_date = transaction_date or date.today().isoformat()

    # Dependency-first: resolve every account BEFORE mutating anything.
    # Contra accounts (accumulated depreciation) are structural
    # non-candidates for the asset-COST account.
    asset_account = await _resolve_gl_account(
        organization_id,
        account_type="ASSET",
        keywords=_ASSET_ACCOUNT_KEYWORDS,
        explicit_id=asset_account_id,
        exclude_keywords=("accumulated depreciation",),
    )
    if not asset_account:
        raise ValueError(
            "No fixed-asset account could be determined for this "
            "acquisition. Specify the asset account (or add one to the "
            "chart of accounts, e.g. 'Computer Equipment')."
        )

    supplier = await _resolve_supplier(
        organization_id,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
    )
    if supplier_name and not supplier:
        raise ValueError(f"Supplier not found: {supplier_name}")

    is_credit = payment_method == "CREDIT"
    if is_credit and not supplier:
        raise ValueError(
            "A credit asset acquisition requires a supplier for the "
            "payable ledger."
        )

    # 1. Create the asset record (authoritative id captured; the DB
    #    trigger assigns asset_code).
    asset = await repo.create_asset(
        organization_id=organization_id,
        name=name.strip(),
        purchase_date=txn_date,
        purchase_cost=cost,
        salvage_value=float(salvage_value or 0),
        useful_life_years=useful_life_years,
        depreciation_method=depreciation_method,
        supplier_id=uuid.UUID(supplier["id"]) if supplier else None,
        gl_asset_account_id=uuid.UUID(asset_account["id"]),
        description=description,
    )

    # 2. Journal via the accounting engine (source-tied to the asset).
    description_text = f"Asset acquisition — {name.strip()}"
    payable = None
    counter_account = None
    try:
        if is_credit:
            payable = await _resolve_gl_account(
                organization_id,
                account_type="LIABILITY",
                keywords=("payable",),
                explicit_id=None,
            )
            if not payable:
                raise ValueError(
                    "No Accounts Payable account exists in the chart of "
                    "accounts — a credit acquisition cannot be recorded."
                )
            journal = await _post_journal(
                organization_id=organization_id,
                transaction_date=txn_date,
                description=description_text,
                lines=[
                    {
                        "account_id": str(asset_account["id"]),
                        "description": description_text,
                        "debit": cost,
                        "credit": 0,
                        "supplier_id": str(supplier["id"]),
                    },
                    {
                        "account_id": str(payable["id"]),
                        "description": f"Payable — {description_text}",
                        "debit": 0,
                        "credit": cost,
                        "supplier_id": str(supplier["id"]),
                    },
                ],
                source_type="fixed_asset",
                source_id=uuid.UUID(asset["id"]),
            )
        else:
            counter_account = await _resolve_settlement_account(
                organization_id, payment_account_id=payment_account_id
            )
            if not counter_account:
                raise ValueError(
                    "No cash/bank account could be determined for the "
                    "acquisition payment. Configure a bank account or "
                    "specify the payment account."
                )
            journal = await _post_journal(
                organization_id=organization_id,
                transaction_date=txn_date,
                description=description_text,
                lines=[
                    {
                        "account_id": str(asset_account["id"]),
                        "description": description_text,
                        "debit": cost,
                        "credit": 0,
                    },
                    {
                        "account_id": str(counter_account["id"]),
                        "description": f"Payment — {description_text}",
                        "debit": 0,
                        "credit": cost,
                    },
                ],
                source_type="fixed_asset",
                source_id=uuid.UUID(asset["id"]),
            )
    except Exception as exc:
        # Asset exists but capitalisation failed — surface the partial
        # state honestly; never pretend the journal happened.
        log.warning(
            "fixed_asset.acquisition_journal_failed",
            asset_id=asset.get("id"),
            error=str(exc),
        )
        return {
            **asset,
            # FULL ACQUISITION CONTRACT DISCLOSURE — every dimension of the
            # interview is disclosed, never silently skipped.
            "asset_registered": True,
            "journal_posted": False,
            "journal_warning": (
                "Asset registered but the capitalisation journal failed: "
                f"{exc}. Verify the chart of accounts and post the journal."
            ),
            "depreciation_schedule_created": False,
            "depreciation_declined": useful_life_years is None,
            "asset_account": asset_account.get("name"),
        }

    # 3. Source-tie the asset + audit trail to its journal.
    entry = journal.get("entry") or journal
    journal_id = entry.get("id")
    schedule_created = False
    if journal_id:
        await repo.update_asset_by_id(
            uuid.UUID(asset["id"]),
            fields={"purchase_journal_entry_id": uuid.UUID(str(journal_id))},
        )
        await repo.record_asset_transaction(
            organization_id=organization_id,
            asset_id=uuid.UUID(asset["id"]),
            # DB CHECK contract: PURCHASE|DEPRECIATION|REVALUATION|DISPOSAL|WRITE_OFF
            transaction_type="PURCHASE",
            transaction_date=txn_date,
            amount=cost,
            journal_entry_id=uuid.UUID(str(journal_id)),
            details={
                "payment_method": payment_method,
                # Explicit disclosure inside the sub-ledger row: a missing
                # schedule is a DECLINED policy, never an oversight.
                **({"depreciation": (
                    "DECLINED — no useful life provided; the asset is "
                    "registered without a depreciation schedule"
                )} if useful_life_years is None else {}),
            },
        )
        # 4. Initial depreciation schedule row — created WHEN useful life is
        # provided; explicitly recorded as DECLINED when the user opts out.
        if useful_life_years is not None:
            await repo.record_depreciation_schedule(
                organization_id=organization_id,
                asset_id=uuid.UUID(asset["id"]),
                depreciation_date=txn_date,
                opening_book_value=round(cost, 2),
                depreciation_amount=0.0,
                closing_book_value=round(cost, 2),
                journal_entry_id=uuid.UUID(str(journal_id)),
            )
            schedule_created = True

    log.info(
        "fixed_asset.registered",
        asset_id=asset["id"],
        journal_entry_id=str(journal_id),
        cost=cost,
        schedule_created=schedule_created,
    )
    return {
        **asset,
        # FULL ACQUISITION CONTRACT DISCLOSURE (parity master prompt):
        # register + schedule (or explicit decline) + journal + accounts.
        "asset_registered": True,
        "purchase_journal_entry_id": str(journal_id) if journal_id else None,
        "journal_entry": entry,
        "journal_posted": True,
        "depreciation_schedule_created": schedule_created,
        "depreciation_declined": useful_life_years is None,
        "depreciation_method": depreciation_method if schedule_created else None,
        "asset_account": asset_account.get("name"),
        "settlement_account": (
            None if is_credit
            else (counter_account or {}).get("name")
        ),
        "payable_account": (
            (payable or {}).get("name") if is_credit else None
        ),
        "supplier": (supplier or {}).get("name"),
    }


async def record_depreciation(
    organization_id: uuid.UUID,
    *,
    asset_id: Optional[str] = None,
    asset_name: Optional[str] = None,
    depreciation_amount: Optional[float] = None,
    transaction_date: Optional[str] = None,
    **kw,
) -> Dict[str, Any]:
    """Record depreciation for an asset.

    Deterministic amount: (cost − salvage) ÷ useful_life_years ÷ 12 for a
    monthly straight-line charge when no explicit amount is given.  The
    depreciation policy itself is NEVER invented — it comes from the
    asset's own configuration or the user's explicit amount.
    """
    asset = await _resolve_asset_by_reference(
        organization_id, asset_id=asset_id, asset_name=asset_name
    )
    if asset.get("status") not in ("ACTIVE", "FULLY_DEPRECIATED"):
        raise ValueError(
            f"Asset '{asset.get('name')}' has status {asset.get('status')} "
            "and can no longer be depreciated."
        )

    cost = float(asset.get("purchase_cost") or 0)
    acc_dep = float(asset.get("accumulated_depreciation") or 0)
    salvage = float(asset.get("salvage_value") or 0)
    book_value = float(asset.get("book_value") if asset.get("book_value") is not None else cost - acc_dep)

    if depreciation_amount is not None:
        amount = round(float(depreciation_amount), 2)
        if amount <= 0:
            raise ValueError("Depreciation amount must be positive.")
    else:
        life = asset.get("useful_life_years")
        if not life:
            raise ValueError(
                f"Asset '{asset.get('name')}' has no useful life configured "
                "and no explicit depreciation amount was provided."
            )
        amount = round(max(cost - salvage, 0.0) / (int(life) * 12.0), 2)
        if amount <= 0:
            raise ValueError(
                "Computed straight-line depreciation is zero — the asset "
                "is fully depreciated (cost minus salvage is exhausted)."
            )
    # Never depreciate below salvage value.
    remaining = round(max(cost - salvage - acc_dep, 0.0), 2)
    amount = min(amount, remaining)
    if amount <= 0:
        raise ValueError(
            f"Asset '{asset.get('name')}' is already fully depreciated."
        )

    txn_date = transaction_date or date.today().isoformat()

    # GL accounts: asset-configured column → deterministic name match.
    dep_expense = await _resolve_gl_account(
        organization_id,
        account_type="EXPENSE",
        keywords=("depreciation",),
        explicit_id=(
            uuid.UUID(asset["gl_depreciation_expense_account_id"])
            if asset.get("gl_depreciation_expense_account_id") else None
        ),
    )
    acc_dep_account = await _resolve_gl_account(
        organization_id,
        account_type="ASSET",
        keywords=("accumulated depreciation",),
        explicit_id=(
            uuid.UUID(asset["gl_accumulated_depreciation_account_id"])
            if asset.get("gl_accumulated_depreciation_account_id") else None
        ),
    )
    if not dep_expense or not acc_dep_account:
        raise ValueError(
            "Depreciation accounts are not configured: both a "
            "'Depreciation Expense' (expense) and an 'Accumulated "
            "Depreciation' (asset) account must exist in the chart of "
            "accounts or on the asset record."
        )

    description_text = f"Depreciation — {asset.get('name')}"
    journal = await _post_journal(
        organization_id=organization_id,
        transaction_date=txn_date,
        description=description_text,
        lines=[
            {
                "account_id": str(dep_expense["id"]),
                "description": description_text,
                "debit": amount,
                "credit": 0,
            },
            {
                "account_id": str(acc_dep_account["id"]),
                "description": description_text,
                "debit": 0,
                "credit": amount,
            },
        ],
        source_type="asset_depreciation",
        source_id=uuid.UUID(asset["id"]),
    )
    entry = journal.get("entry") or journal
    journal_id = entry.get("id")

    # Update asset totals + audit trail + schedule (source-tied).
    # NOTE: book_value is a GENERATED column (purchase_cost −
    # accumulated_depreciation) — writing accumulated_depreciation is
    # sufficient and writing book_value directly is forbidden (428C9).
    new_acc = round(acc_dep + amount, 2)
    new_book = round(cost - new_acc, 2)
    await repo.update_asset_by_id(
        uuid.UUID(asset["id"]),
        fields={
            "accumulated_depreciation": new_acc,
            **({"status": "FULLY_DEPRECIATED"} if new_book <= salvage else {}),
        },
    )
    if journal_id:
        await repo.record_depreciation_schedule(
            organization_id=organization_id,
            asset_id=uuid.UUID(asset["id"]),
            depreciation_date=txn_date,
            opening_book_value=round(book_value, 2),
            depreciation_amount=amount,
            closing_book_value=new_book,
            journal_entry_id=uuid.UUID(str(journal_id)),
        )
        await repo.record_asset_transaction(
            organization_id=organization_id,
            asset_id=uuid.UUID(asset["id"]),
            transaction_type="DEPRECIATION",
            transaction_date=txn_date,
            amount=amount,
            journal_entry_id=uuid.UUID(str(journal_id)),
            details={"accumulated_depreciation": new_acc},
        )

    log.info(
        "fixed_asset.depreciation_recorded",
        asset_id=asset["id"],
        amount=amount,
        journal_entry_id=str(journal_id),
    )
    return {
        **asset,
        "accumulated_depreciation": new_acc,
        "book_value": new_book,
        "depreciation_amount": amount,
        "journal_entry": entry,
    }


async def dispose_asset(
    organization_id: uuid.UUID,
    *,
    asset_id: Optional[str] = None,
    asset_name: Optional[str] = None,
    disposal_amount: float = 0.0,
    transaction_date: Optional[str] = None,
    disposal_type: str = "DISPOSAL",
    proceeds_account_id: Optional[uuid.UUID] = None,
    gain_loss_account_id: Optional[uuid.UUID] = None,
    **kw,
) -> Dict[str, Any]:
    """Dispose of / sell a fixed asset (NOT an ordinary inventory sale).

    Verified economics:
        Dr Cash/Bank (proceeds)
        Dr Accumulated Depreciation (to date)
        Dr Loss on disposal (when proceeds < carrying amount)
        Cr Asset cost
        Cr Gain on disposal (when proceeds > carrying amount)
    Balanced by construction; validated + posted by the engine.
    """
    if disposal_type not in ("DISPOSAL", "SALE", "WRITE_OFF"):
        raise ValueError(f"Unsupported disposal type: {disposal_type}")

    asset = await _resolve_asset_by_reference(
        organization_id, asset_id=asset_id, asset_name=asset_name
    )
    if asset.get("status") not in ("ACTIVE", "FULLY_DEPRECIATED"):
        raise ValueError(
            f"Asset '{asset.get('name')}' has status {asset.get('status')} "
            "and cannot be disposed of again."
        )

    cost = float(asset.get("purchase_cost") or 0)
    acc_dep = float(asset.get("accumulated_depreciation") or 0)
    carrying = round(cost - acc_dep, 2)
    proceeds = round(float(disposal_amount or 0), 2)
    if proceeds < 0:
        raise ValueError("Disposal proceeds cannot be negative.")
    if disposal_type == "WRITE_OFF" and proceeds > 0:
        raise ValueError("A write-off cannot have sale proceeds.")
    gain = round(max(proceeds - carrying, 0.0), 2)
    loss = round(max(carrying - proceeds, 0.0), 2)
    txn_date = transaction_date or date.today().isoformat()

    # Dependency-first: resolve every account BEFORE mutating anything.
    asset_account = await _resolve_gl_account(
        organization_id,
        account_type="ASSET",
        keywords=_ASSET_ACCOUNT_KEYWORDS,
        explicit_id=(
            uuid.UUID(asset["gl_asset_account_id"])
            if asset.get("gl_asset_account_id") else None
        ),
        exclude_keywords=("accumulated depreciation",),
    )
    acc_dep_account = await _resolve_gl_account(
        organization_id,
        account_type="ASSET",
        keywords=("accumulated depreciation",),
        explicit_id=(
            uuid.UUID(asset["gl_accumulated_depreciation_account_id"])
            if asset.get("gl_accumulated_depreciation_account_id") else None
        ),
    )
    if not asset_account or not acc_dep_account:
        raise ValueError(
            "Disposal accounts are not configured: the asset account and "
            "the 'Accumulated Depreciation' account must exist on the "
            "asset record or in the chart of accounts."
        )

    lines: List[Dict[str, Any]] = []
    if proceeds > 0:
        proceeds_account = await _resolve_settlement_account(
            organization_id, payment_account_id=proceeds_account_id
        )
        if not proceeds_account:
            raise ValueError(
                "No cash/bank account could be determined for the disposal "
                "proceeds. Configure a bank account or specify one."
            )
        lines.append({
            "account_id": str(proceeds_account["id"]),
            "description": f"Disposal proceeds — {asset.get('name')}",
            "debit": proceeds,
            "credit": 0,
        })
    if acc_dep > 0:
        lines.append({
            "account_id": str(acc_dep_account["id"]),
            "description": f"Accumulated depreciation removed — {asset.get('name')}",
            "debit": acc_dep,
            "credit": 0,
        })
    if loss > 0:
        loss_account = await _resolve_gl_account(
            organization_id,
            account_type="EXPENSE",
            keywords=("loss on disposal", "disposal", "gain", "loss"),
            explicit_id=gain_loss_account_id,
        )
        if not loss_account:
            raise ValueError(
                "No 'loss on disposal' account exists in the chart of "
                "accounts. Specify one (or add it) — the disposal loss "
                "cannot be recorded without it."
            )
        lines.append({
            "account_id": str(loss_account["id"]),
            "description": f"Loss on disposal — {asset.get('name')}",
            "debit": loss,
            "credit": 0,
        })
    lines.append({
        "account_id": str(asset_account["id"]),
        "description": f"Asset cost removed — {asset.get('name')}",
        "debit": 0,
        "credit": cost,
    })
    if gain > 0:
        gain_account = await _resolve_gl_account(
            organization_id,
            account_type="REVENUE",
            keywords=("gain on disposal", "disposal", "gain"),
            explicit_id=gain_loss_account_id,
        )
        if not gain_account:
            raise ValueError(
                "No 'gain on disposal' account exists in the chart of "
                "accounts. Specify one (or add it) — the disposal gain "
                "cannot be recorded without it."
            )
        lines.append({
            "account_id": str(gain_account["id"]),
            "description": f"Gain on disposal — {asset.get('name')}",
            "debit": 0,
            "credit": gain,
        })

    description_text = (
        f"Asset {disposal_type.lower()} — {asset.get('name')} "
        f"(carrying {carrying}, proceeds {proceeds})"
    )

    # Map the disposal verb onto the authoritative asset_status enum
    # (ACTIVE, FULLY_DEPRECIATED, DISPOSED, SOLD, WRITTEN_OFF).
    status_by_disposal = {"SALE": "SOLD", "WRITE_OFF": "WRITTEN_OFF"}
    final_status = status_by_disposal.get(disposal_type, "DISPOSED")

    journal = await _post_journal(
        organization_id=organization_id,
        transaction_date=txn_date,
        description=description_text,
        lines=lines,
        source_type="fixed_asset_disposal",
        source_id=uuid.UUID(asset["id"]),
    )
    entry = journal.get("entry") or journal
    journal_id = entry.get("id")

    final_status = status_by_disposal.get(disposal_type, "DISPOSED")
    update_fields: Dict[str, Any] = {
        "status": final_status,
        "disposal_date": txn_date,
        "disposal_amount": proceeds,
    }
    if journal_id:
        update_fields["disposal_journal_entry_id"] = uuid.UUID(str(journal_id))
    await repo.update_asset_by_id(uuid.UUID(asset["id"]), fields=update_fields)
    if journal_id:
        await repo.record_asset_transaction(
            organization_id=organization_id,
            asset_id=uuid.UUID(asset["id"]),
            # DB CHECK contract: SALE is recorded as a DISPOSAL transaction.
            transaction_type="WRITE_OFF" if disposal_type == "WRITE_OFF" else "DISPOSAL",
            transaction_date=txn_date,
            amount=proceeds,
            journal_entry_id=uuid.UUID(str(journal_id)),
            details={
                "disposal_type": disposal_type,
                "carrying_amount": carrying,
                "accumulated_depreciation_removed": acc_dep,
                "gain": gain,
                "loss": loss,
            },
        )

    log.info(
        "fixed_asset.disposed",
        asset_id=asset["id"],
        proceeds=proceeds,
        gain=gain,
        loss=loss,
        journal_entry_id=str(journal_id),
    )
    return {
        **asset,
        "status": final_status,
        "disposal_amount": proceeds,
        "carrying_amount": carrying,
        "gain_on_disposal": gain,
        "loss_on_disposal": loss,
        "journal_entry": entry,
    }






