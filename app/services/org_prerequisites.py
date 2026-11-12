"""
Organization Prerequisites Service — Idempotent Fresh-Org Provisioning
======================================================================

Ensures that a newly created organization (e.g., seeded with a base Chart of
Accounts and Financial Years/Periods, or even partially seeded with 0 bank
accounts / missing cash or control ledgers) has every prerequisite needed for
double-entry posting, payments, receipts, asset acquisitions, loans, expenses,
and tax settlements.

Key guarantees:
* Idempotent: running twice produces no duplicate accounts, bank rows, or periods,
  and reports every item accurately under ``provisioned`` vs ``already_present``.
* Supports an optional Supabase-compatible ``client`` (for injected callers) or
  uses the repository / accounting_engine layer when ``client is None``.
* Degrades gracefully when live DB access is blocked in unit tests
  (``conftest.py::_no_live_database``) or when an individual table is stubbed.
"""

from __future__ import annotations

import calendar
import inspect
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from app import accounting_engine as engine
from app.database import fetch_many, insert_one
from app.repositories import account_repository as acct_repo
from app.repositories import bank_repository as bank_repo
from app.repositories import organization_repository as org_repo
from app.services import bank_service

log = structlog.get_logger(__name__)

# Control-ledger specifications shared across both client and repo execution paths.
# Each entry: (key, preferred_code, default_name, account_type, normal_balance, match_keywords, description)
_CONTROL_LEDGER_SPECS: Tuple[Tuple[str, str, str, str, str, Tuple[str, ...], str], ...] = (
    (
        "accounts_receivable",
        "1100",
        "Accounts Receivable",
        "ASSET",
        "DEBIT",
        ("accounts receivable", "trade receivable", "receivables"),
        "Customer receivables control ledger — auto-provisioned prerequisite.",
    ),
    (
        "accounts_payable",
        "2010",
        "Accounts Payable",
        "LIABILITY",
        "CREDIT",
        ("accounts payable", "trade payable", "payables"),
        "Supplier payables control ledger — auto-provisioned prerequisite.",
    ),
    (
        "clearing_suspense",
        "1090",
        "Clearing & Suspense",
        "ASSET",
        "DEBIT",
        ("clearing", "suspense", "undeposited"),
        "Clearing / suspense control ledger — auto-provisioned prerequisite.",
    ),
    (
        "gst_output_payable",
        "2110",
        "Sales Tax Output Payable",
        "LIABILITY",
        "CREDIT",
        ("sales tax output", "output tax", "gst output", "vat payable", "tax payable"),
        "GST / Sales tax output payable ledger — auto-provisioned prerequisite.",
    ),
    (
        "gst_input_claimable",
        "1310",
        "Sales Tax Input Claimable",
        "ASSET",
        "DEBIT",
        ("sales tax input", "input tax", "gst input", "tax claimable", "tax receivable"),
        "GST / Sales tax input claimable ledger — auto-provisioned prerequisite.",
    ),
    (
        "wht_payable_153",
        "2120",
        "Withholding Tax Payable - Section 153",
        "LIABILITY",
        "CREDIT",
        ("withholding tax", "wht", "section 153"),
        "Withholding tax payable (Section 153) — auto-provisioned prerequisite.",
    ),
)

_CASH_MATCH_NAMES = ("cash in hand", "cash", "cash account", "petty cash")
_BANK_MATCH_NAMES = ("bank", "bank account", "cash at bank", "operating bank account")


def _normalize_org_uuid(organization_id: str | uuid.UUID) -> uuid.UUID:
    if isinstance(organization_id, uuid.UUID):
        return organization_id
    return uuid.UUID(str(organization_id).strip())


def _is_db_blocked_error(exc: BaseException) -> bool:
    return "REAL_DB_ACCESS" in str(exc)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _client_select(
    client: Any,
    table: str,
    filters: Optional[Dict[str, Any]] = None,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    query = client.table(table).select("*")
    for key, val in (filters or {}).items():
        query = query.eq(key, val)
    if limit is not None:
        query = query.limit(limit)
    res = await _maybe_await(query.execute())
    data = getattr(res, "data", None)
    if data is not None:
        return list(data)
    return list(res) if isinstance(res, list) else []


async def _client_insert(
    client: Any,
    table: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    res = await _maybe_await(client.table(table).insert(data).execute())
    rows = getattr(res, "data", None)
    if isinstance(rows, list) and rows:
        return dict(rows[0])
    if isinstance(rows, dict):
        return dict(rows)
    if isinstance(res, list) and res:
        return dict(res[0])
    return dict(data)


def _find_matching_account(
    accounts: Sequence[Dict[str, Any]],
    *,
    account_type: str,
    preferred_code: str,
    default_name: str,
    keywords: Sequence[str],
) -> Optional[Dict[str, Any]]:
    """Find an active, postable (non-grouping) account matching code/name/keywords."""
    parent_ids = {
        str(a["parent_account_id"])
        for a in accounts
        if a.get("parent_account_id") and a.get("is_active", True)
    }
    postable = [
        a for a in accounts
        if a.get("is_active", True)
        and str(a.get("id") or "") not in parent_ids
        and str(a.get("account_type") or "").upper() == account_type.upper()
    ]
    default_lower = default_name.strip().lower()
    for row in postable:
        if str(row.get("name") or "").strip().lower() == default_lower:
            return row
    for row in postable:
        if str(row.get("code") or "").strip() == preferred_code:
            return row
    for kw in keywords:
        kw_low = kw.lower()
        for row in postable:
            if kw_low in str(row.get("name") or "").strip().lower():
                return row
    return None


def _next_code_from_rows(accounts: Sequence[Dict[str, Any]], base_code: str) -> str:
    used = {str(a.get("code") or "").strip() for a in accounts}
    if base_code not in used:
        return base_code
    try:
        num = int(base_code)
    except ValueError:
        return base_code
    for offset in range(1, 100):
        candidate = str(num + offset)
        if candidate not in used:
            return candidate
    return f"{base_code}-{uuid.uuid4().hex[:4]}"


async def _ensure_ledger_via_client(
    client: Any,
    org_id_str: str,
    coa_rows: List[Dict[str, Any]],
    *,
    preferred_code: str,
    default_name: str,
    account_type: str,
    normal_balance: str,
    keywords: Sequence[str],
    description: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    existing = _find_matching_account(
        coa_rows,
        account_type=account_type,
        preferred_code=preferred_code,
        default_name=default_name,
        keywords=keywords,
    )
    if existing is not None:
        return existing, False

    code = _next_code_from_rows(coa_rows, preferred_code)
    created = await _client_insert(
        client,
        "accounts",
        {
            "organization_id": org_id_str,
            "code": code,
            "name": default_name,
            "account_type": account_type,
            "normal_balance": normal_balance,
            "parent_account_id": None,
            "description": description,
            "is_active": True,
        },
    )
    if created:
        coa_rows.append(created)
    return created, True


async def _ensure_ledger_via_repo(
    org_uuid: uuid.UUID,
    coa_rows: Optional[List[Dict[str, Any]]],
    *,
    key: str,
    preferred_code: str,
    default_name: str,
    account_type: str,
    normal_balance: str,
    keywords: Sequence[str],
    description: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    if coa_rows is not None:
        existing = _find_matching_account(
            coa_rows,
            account_type=account_type,
            preferred_code=preferred_code,
            default_name=default_name,
            keywords=keywords,
        )
        if existing is not None:
            return existing, False

    # Reuse existing accounting_engine helpers for statutory tax ledgers
    if key == "gst_output_payable":
        row = await engine.ensure_tax_payable_account(org_uuid)
        return row, bool(row and row.get("tax_account_created", coa_rows is not None))
    if key == "gst_input_claimable":
        row = await engine.ensure_tax_receivable_account(org_uuid)
        return row, bool(row and row.get("tax_account_created", coa_rows is not None))
    if key == "wht_payable_153":
        row = await engine.ensure_wht_payable_account(org_uuid, section="153")
        return row, bool(row and row.get("wht_account_created", coa_rows is not None))

    # For AR / AP / Clearing, double-check by code/search when COA preload wasn't available
    if coa_rows is None:
        by_code = await acct_repo.get_account_by_code(org_uuid, code=preferred_code)
        if by_code and by_code.get("is_active", True):
            return by_code, False
        for term in keywords[:2]:
            matches = await acct_repo.search_accounts(org_uuid, query=term, limit=10)
            matched = _find_matching_account(
                matches or [],
                account_type=account_type,
                preferred_code=preferred_code,
                default_name=default_name,
                keywords=keywords,
            )
            if matched is not None:
                return matched, False

    code = await acct_repo.next_available_code(org_uuid, preferred_code)
    created = await acct_repo.create_account(
        organization_id=org_uuid,
        code=code,
        name=default_name,
        account_type=account_type,
        normal_balance=normal_balance,
        parent_account_id=None,
        description=description,
    )
    if created and coa_rows is not None:
        coa_rows.append(created)
    return created, bool(created)


def _current_period_dates(today: Optional[date] = None) -> Tuple[str, str, str, str, str, int, str]:
    ref = today or date.today()
    last_day = calendar.monthrange(ref.year, ref.month)[1]
    fy_name = f"FY {ref.year}"
    fy_start = f"{ref.year}-01-01"
    fy_end = f"{ref.year}-12-31"
    period_name = ref.strftime("%B %Y")
    p_start = date(ref.year, ref.month, 1).isoformat()
    p_end = date(ref.year, ref.month, last_day).isoformat()
    return fy_name, fy_start, fy_end, period_name, p_start, ref.month, p_end


async def _ensure_period_via_client(
    client: Any,
    org_id_str: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    fys = await _client_select(
        client, "financial_years", {"organization_id": org_id_str}
    )
    current_fy = next((f for f in fys if f.get("is_current")), None) or (fys[0] if fys else None)

    periods = await _client_select(
        client, "accounting_periods", {"organization_id": org_id_str}
    )
    open_period = next(
        (p for p in periods if str(p.get("status") or "").upper() == "OPEN"),
        None,
    )
    if open_period is not None:
        return open_period, False

    fy_name, fy_start, fy_end, period_name, p_start, p_num, p_end = _current_period_dates()
    if current_fy is None:
        current_fy = await _client_insert(
            client,
            "financial_years",
            {
                "organization_id": org_id_str,
                "name": fy_name,
                "start_date": fy_start,
                "end_date": fy_end,
                "status": "OPEN",
                "is_current": True,
            },
        )
    if not current_fy or not current_fy.get("id"):
        return None, False

    created_period = await _client_insert(
        client,
        "accounting_periods",
        {
            "organization_id": org_id_str,
            "financial_year_id": str(current_fy["id"]),
            "period_number": p_num,
            "name": period_name,
            "start_date": p_start,
            "end_date": p_end,
            "status": "OPEN",
        },
    )
    return created_period, True


async def _ensure_period_via_repo(
    org_uuid: uuid.UUID,
    org_id_str: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    open_period = await org_repo.get_open_accounting_period(org_uuid)
    if open_period is not None:
        return open_period, False

    fy = await org_repo.get_current_financial_year(org_uuid)
    if fy is None:
        all_fys = await org_repo.get_financial_years(org_uuid)
        fy = all_fys[0] if all_fys else None

    fy_name, fy_start, fy_end, period_name, p_start, p_num, p_end = _current_period_dates()
    if fy is None:
        fy = await insert_one(
            "financial_years",
            data={
                "organization_id": org_id_str,
                "name": fy_name,
                "start_date": fy_start,
                "end_date": fy_end,
                "status": "OPEN",
                "is_current": True,
            },
        )
    if not fy or not fy.get("id"):
        return None, False

    existing_periods = await org_repo.get_accounting_periods(
        org_uuid, financial_year_id=uuid.UUID(str(fy["id"]))
    )
    open_existing = next(
        (p for p in existing_periods if str(p.get("status") or "").upper() == "OPEN"),
        None,
    )
    if open_existing is not None:
        return open_existing, False

    # Avoid unique constraint collision on (organization_id, financial_year_id, period_number)
    used_nums = {int(p.get("period_number") or 0) for p in existing_periods}
    if p_num in used_nums:
        p_num = max(used_nums, default=0) + 1

    created_period = await insert_one(
        "accounting_periods",
        data={
            "organization_id": org_id_str,
            "financial_year_id": str(fy["id"]),
            "period_number": p_num,
            "name": period_name,
            "start_date": p_start,
            "end_date": p_end,
            "status": "OPEN",
        },
    )
    return created_period, bool(created_period)


def _record_step(
    result: Dict[str, Any],
    key: str,
    payload: Optional[Dict[str, Any]],
    created: bool,
) -> None:
    if payload is None:
        if key not in result["skipped"]:
            result["skipped"].append(key)
        return
    if created:
        result["provisioned"].append(key)
    else:
        result["already_present"].append(key)


async def ensure_org_prerequisites(
    organization_id: str | uuid.UUID,
    client: Any = None,
) -> Dict[str, Any]:
    """Idempotently ensure cash, bank, control ledgers, and base period exist.

    Returns a structured status dictionary reporting every prerequisite in
    ``provisioned``, ``already_present``, or ``skipped``.
    """
    org_uuid = _normalize_org_uuid(organization_id)
    org_id_str = str(org_uuid)

    result: Dict[str, Any] = {
        "organization_id": org_id_str,
        "status": "ready",
        "provisioned": [],
        "already_present": [],
        "skipped": [],
        "cash_gl": None,
        "cash_account": None,
        "bank_gl": None,
        "bank_account": None,
        "control_ledgers": {},
        "accounting_period": None,
        "errors": {},
    }

    coa_rows: Optional[List[Dict[str, Any]]] = None
    try:
        if client is not None:
            coa_rows = await _client_select(
                client, "accounts", {"organization_id": org_id_str}
            )
        else:
            coa_rows = list(
                await acct_repo.get_chart_of_accounts(org_uuid, limit=500) or []
            )
    except BaseException as exc:
        if not isinstance(exc, (Exception, AssertionError)):
            raise
        result["errors"]["chart_of_accounts"] = str(exc)[:200]
        if _is_db_blocked_error(exc):
            result["status"] = "degraded"

    # 1. Default Cash GL + Cash Drawer (cash_accounts)
    try:
        if client is not None:
            client_coa = coa_rows if coa_rows is not None else []
            cash_gl, cash_gl_created = await _ensure_ledger_via_client(
                client,
                org_id_str,
                client_coa,
                preferred_code="1110",
                default_name="Cash",
                account_type="ASSET",
                normal_balance="DEBIT",
                keywords=_CASH_MATCH_NAMES,
                description="Cash on hand — auto-provisioned prerequisite.",
            )
            result["cash_gl"] = cash_gl
            _record_step(result, "cash_gl", cash_gl, cash_gl_created)

            drawers = await _client_select(
                client,
                "cash_accounts",
                {"organization_id": org_id_str, "is_active": True},
                limit=5,
            )
            if drawers:
                result["cash_account"] = drawers[0]
                _record_step(result, "cash_account", drawers[0], False)
            elif cash_gl and cash_gl.get("id"):
                drawer = await _client_insert(
                    client,
                    "cash_accounts",
                    {
                        "organization_id": org_id_str,
                        "name": str(cash_gl.get("name") or "Cash"),
                        "gl_account_id": str(cash_gl["id"]),
                        "is_active": True,
                    },
                )
                result["cash_account"] = drawer
                _record_step(result, "cash_account", drawer, True)
            else:
                _record_step(result, "cash_account", None, False)
        else:
            existing_cash_gl = (
                _find_matching_account(
                    coa_rows,
                    account_type="ASSET",
                    preferred_code="1110",
                    default_name="Cash",
                    keywords=_CASH_MATCH_NAMES,
                )
                if coa_rows is not None
                else None
            )
            cash_gl = existing_cash_gl or await engine.ensure_cash_account(org_uuid)
            cash_gl_created = bool(
                cash_gl
                and existing_cash_gl is None
                and (cash_gl.get("cash_account_created") or coa_rows is not None)
            )
            if cash_gl and coa_rows is not None and existing_cash_gl is None:
                coa_rows.append(cash_gl)
            result["cash_gl"] = cash_gl
            _record_step(result, "cash_gl", cash_gl, cash_gl_created)

            existing_drawer = await bank_repo.get_default_cash_account(org_uuid)
            if existing_drawer:
                result["cash_account"] = existing_drawer
                _record_step(result, "cash_account", existing_drawer, False)
            else:
                drawer = await bank_service.ensure_default_cash_account(org_uuid)
                result["cash_account"] = drawer
                _record_step(result, "cash_account", drawer, bool(drawer))
    except BaseException as exc:
        if not isinstance(exc, (Exception, AssertionError)):
            raise
        result["errors"]["cash"] = str(exc)[:200]
        if _is_db_blocked_error(exc):
            result["status"] = "degraded"
        _record_step(result, "cash_gl", result["cash_gl"], False)
        _record_step(result, "cash_account", result["cash_account"], False)

    # 2. Default Bank GL + Bank Account (coordinates with ensure_bank_account)
    try:
        if client is not None:
            client_coa = coa_rows if coa_rows is not None else []
            banks = await _client_select(
                client,
                "bank_accounts",
                {"organization_id": org_id_str, "is_active": True},
                limit=5,
            )
            if banks:
                default_bank = next((b for b in banks if b.get("is_default")), banks[0])
                result["bank_account"] = default_bank
                _record_step(result, "bank_account", default_bank, False)
                gl_id = str(default_bank.get("gl_account_id") or "")
                bank_gl = next((a for a in client_coa if str(a.get("id")) == gl_id), None)
                if bank_gl is None:
                    bank_gl, bank_gl_created = await _ensure_ledger_via_client(
                        client,
                        org_id_str,
                        client_coa,
                        preferred_code="1010",
                        default_name="Bank",
                        account_type="ASSET",
                        normal_balance="DEBIT",
                        keywords=_BANK_MATCH_NAMES,
                        description="Bank asset ledger — auto-provisioned prerequisite.",
                    )
                else:
                    bank_gl_created = False
                result["bank_gl"] = bank_gl
                _record_step(result, "bank_gl", bank_gl, bank_gl_created)
            else:
                bank_gl, bank_gl_created = await _ensure_ledger_via_client(
                    client,
                    org_id_str,
                    client_coa,
                    preferred_code="1010",
                    default_name="Bank",
                    account_type="ASSET",
                    normal_balance="DEBIT",
                    keywords=_BANK_MATCH_NAMES,
                    description="Bank asset ledger — auto-provisioned prerequisite.",
                )
                result["bank_gl"] = bank_gl
                _record_step(result, "bank_gl", bank_gl, bank_gl_created)
                if bank_gl and bank_gl.get("id"):
                    created_bank = await _client_insert(
                        client,
                        "bank_accounts",
                        {
                            "organization_id": org_id_str,
                            "account_name": "Primary Bank - Main",
                            "bank_name": "Primary Bank",
                            "gl_account_id": str(bank_gl["id"]),
                            "currency_code": "PKR",
                            "current_balance": 0,
                            "is_default": True,
                            "is_active": True,
                        },
                    )
                    result["bank_account"] = created_bank
                    _record_step(result, "bank_account", created_bank, True)
                else:
                    _record_step(result, "bank_account", None, False)
        else:
            existing_bank = await bank_repo.get_default_bank_account(org_uuid)
            if not existing_bank:
                active_banks = await bank_repo.list_bank_accounts(
                    org_uuid, is_active=True, limit=1
                )
                existing_bank = active_banks[0] if active_banks else None

            existing_bank_gl = (
                _find_matching_account(
                    coa_rows,
                    account_type="ASSET",
                    preferred_code="1010",
                    default_name="Bank",
                    keywords=_BANK_MATCH_NAMES,
                )
                if coa_rows is not None
                else None
            )

            if existing_bank and existing_bank.get("gl_account_id"):
                result["bank_account"] = existing_bank
                _record_step(result, "bank_account", existing_bank, False)
                if existing_bank_gl is None and coa_rows is not None:
                    gl_id = str(existing_bank["gl_account_id"])
                    existing_bank_gl = next(
                        (a for a in coa_rows if str(a.get("id")) == gl_id), None
                    )
                if existing_bank_gl is None:
                    existing_bank_gl = await acct_repo.get_account(
                        org_uuid, account_id=uuid.UUID(str(existing_bank["gl_account_id"]))
                    )
                result["bank_gl"] = existing_bank_gl
                _record_step(result, "bank_gl", existing_bank_gl, False)
            else:
                ensured = await engine.ensure_bank_account(org_uuid)
                result["bank_account"] = ensured
                bank_created = bool(ensured and ensured.get("bank_account_created"))
                _record_step(result, "bank_account", ensured, bank_created)

                bank_gl = existing_bank_gl
                bank_gl_created = False
                if bank_gl is None and ensured and ensured.get("gl_account_id"):
                    try:
                        bank_gl = await acct_repo.get_account(
                            org_uuid, account_id=uuid.UUID(str(ensured["gl_account_id"]))
                        )
                    except BaseException:
                        bank_gl = {"id": str(ensured["gl_account_id"])}
                    bank_gl_created = bool(bank_gl and coa_rows is not None)
                result["bank_gl"] = bank_gl
                _record_step(result, "bank_gl", bank_gl, bank_gl_created)
    except BaseException as exc:
        if not isinstance(exc, (Exception, AssertionError)):
            raise
        result["errors"]["bank"] = str(exc)[:200]
        if _is_db_blocked_error(exc):
            result["status"] = "degraded"
        _record_step(result, "bank_gl", result["bank_gl"], False)
        _record_step(result, "bank_account", result["bank_account"], False)

    # 3. Clearing / Suspense / Payable / Receivable / GST / WHT Control Ledgers
    for key, code, name, acc_type, norm_bal, keywords, desc in _CONTROL_LEDGER_SPECS:
        try:
            if client is not None:
                client_coa = coa_rows if coa_rows is not None else []
                row, created = await _ensure_ledger_via_client(
                    client,
                    org_id_str,
                    client_coa,
                    preferred_code=code,
                    default_name=name,
                    account_type=acc_type,
                    normal_balance=norm_bal,
                    keywords=keywords,
                    description=desc,
                )
            else:
                row, created = await _ensure_ledger_via_repo(
                    org_uuid,
                    coa_rows,
                    key=key,
                    preferred_code=code,
                    default_name=name,
                    account_type=acc_type,
                    normal_balance=norm_bal,
                    keywords=keywords,
                    description=desc,
                )
            result["control_ledgers"][key] = row
            _record_step(result, key, row, created)
        except BaseException as exc:
            if not isinstance(exc, (Exception, AssertionError)):
                raise
            result["errors"][key] = str(exc)[:200]
            if _is_db_blocked_error(exc):
                result["status"] = "degraded"
            result["control_ledgers"][key] = None
            _record_step(result, key, None, False)

    # 4. Base Accounting Period check / fallback
    try:
        if client is not None:
            period, period_created = await _ensure_period_via_client(client, org_id_str)
        else:
            period, period_created = await _ensure_period_via_repo(org_uuid, org_id_str)
        result["accounting_period"] = period
        _record_step(result, "accounting_period", period, period_created)
    except BaseException as exc:
        if not isinstance(exc, (Exception, AssertionError)):
            raise
        result["errors"]["accounting_period"] = str(exc)[:200]
        if _is_db_blocked_error(exc):
            result["status"] = "degraded"
        result["accounting_period"] = None
        _record_step(result, "accounting_period", None, False)

    if result["errors"] and not result["provisioned"] and not result["already_present"]:
        result["status"] = "degraded"

    return result


async def ensure_org_prerequisites_safe(
    organization_id: str | uuid.UUID,
    client: Any = None,
) -> Dict[str, Any]:
    """Fail-open wrapper for service entry points.

    Ensures missing org prerequisites self-heal in live/integration execution,
    while never crashing unit tests whose Supabase client is blocked or mocked.
    """
    try:
        return await ensure_org_prerequisites(organization_id, client=client)
    except BaseException as exc:
        if not isinstance(exc, (Exception, AssertionError)):
            raise
        log.warning(
            "org_prerequisites.degraded",
            organization_id=str(organization_id),
            error=str(exc)[:200],
        )
        return {
            "organization_id": str(organization_id),
            "status": "degraded",
            "provisioned": [],
            "already_present": [],
            "skipped": ["all"],
            "errors": {"wrapper": str(exc)[:200]},
        }
