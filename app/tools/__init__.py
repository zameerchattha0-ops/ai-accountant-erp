"""

ERP AI Agent — Tool Registry

===============================

Maps the 36 registered ``ai.tools`` slugs to actual Python implementations.



Each tool handler receives ``(organization_id, **kwargs)`` and returns a

``ToolResult``.  Tools that are read-only are marked ``read_only=True``.

"""



from __future__ import annotations



import uuid

from typing import Any, Callable, Coroutine, Dict, Optional



import structlog



from app.repositories import account_repository as account_repo

from app.models.schemas import ToolResult

from app.services import (

    customer_service,

    supplier_service,

    invoice_service,

    purchase_service,

    expense_service,

    payment_service,

    project_service,

    accounting_service,

    reporting_service,

    quotation_service,

    credit_note_service,

    purchase_return_service,

    bank_service,

    product_service,

    fixed_asset_service,

    service_service,

    employee_service,

    payroll_service,

    inventory_service,

    loan_service,

)

from datetime import date



from app.accounting_engine import (

    auto_journal,

    ensure_cash_account,

    prepare_cogs_for_items,

    record_cash_purchase,

    record_cash_sale,

)

from app.tool_contract import contract_from_callable



log = structlog.get_logger(__name__)



# Type alias for a tool handler

ToolHandler = Callable[..., Coroutine[Any, Any, ToolResult]]



# Registry: slug -> (handler, read_only, description)

_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}





def register(

    slug: str,

    *,

    handler: ToolHandler,

    read_only: bool = False,

    description: str = "",

    contract: Optional[Dict[str, Any]] = None,

):

    """Register a tool handler.



    ``contract`` is the tool's ARGUMENT contract, derived from the Python

    callable that consumes the arguments (``contract_from_callable``).  It is

    what lets Python reject an un-bindable call BEFORE the user is asked to

    approve it.  A tool that declares no contract is simply not validated.

    """

    _TOOL_REGISTRY[slug] = {

        "handler": handler,

        "read_only": read_only,

        "description": description,

        "contract": contract,

    }





_TOOL_ALIASES: Dict[str, str] = {
    # Inventory / Stock status lookups
    "get_inventory": "get_inventory_status",
    "check_stock": "get_inventory_status",
    "view_inventory": "get_inventory_status",
    "fetch_inventory": "get_inventory_status",
    "list_inventory": "get_inventory_status",
    "inventory_status": "get_inventory_status",
    "check_inventory": "get_inventory_status",
    "stock_status": "get_inventory_status",
    "get_stock": "get_inventory_status",
    "get_stock_status": "get_inventory_status",
    "view_stock": "get_inventory_status",
    # Products & Services
    "search_products": "search_product",
    "list_products": "search_product",
    "get_products": "search_product",
    "find_product": "search_product",
    "search_services": "search_service",
    "list_services": "search_service",
    "get_services": "search_service",
    "find_service": "search_service",
    # Chart of Accounts
    "get_accounts": "get_chart_of_accounts",
    "list_accounts": "get_chart_of_accounts",
    "chart_of_accounts": "get_chart_of_accounts",
    "fetch_chart_of_accounts": "get_chart_of_accounts",
    "search_accounts": "search_account",
    "find_account": "search_account",
    # Customers & Suppliers
    "search_customers": "search_customer",
    "find_customer": "search_customer",
    "search_suppliers": "search_supplier",
    "find_supplier": "search_supplier",
    # Assets
    "search_assets": "search_fixed_asset",
    "search_fixed_assets": "search_fixed_asset",
    "get_fixed_assets": "search_fixed_asset",
    "list_fixed_assets": "search_fixed_asset",
    # Employees
    "search_employees": "search_employee",
    "find_employee": "search_employee",
    # Banks
    "get_bank_accounts": "list_bank_accounts",
    "search_bank_accounts": "list_bank_accounts",
}


def resolve_tool_alias(slug: str) -> str:
    """Map a tool alias or synonym to its canonical registered slug."""
    return _TOOL_ALIASES.get(slug, slug)


def get_handler(slug: str) -> Dict[str, Any] | None:

    """Return the registered entry for *slug*, resolving aliases if needed."""

    canonical = _TOOL_ALIASES.get(slug, slug)
    return _TOOL_REGISTRY.get(canonical)





def list_tools() -> list[str]:

    """Return all registered tool slugs."""

    return list(_TOOL_REGISTRY.keys())





def tool_contracts() -> Dict[str, Dict[str, Any]]:

    """Every DECLARED argument contract, keyed by tool slug.



    Used by the reasoning layer to validate a proposed plan against the

    callables that will execute it (see app/tool_contract.py).  Tools without a

    declared contract are absent — never validated, never assumed strict.

    """

    return {

        slug: entry["contract"]

        for slug, entry in _TOOL_REGISTRY.items()

        if entry.get("contract")

    }





# ===================================================================

# CUSTOMER TOOLS

# ===================================================================



async def _search_customer(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await customer_service.search(organization_id, query=kw.get("query", ""), limit=kw.get("limit", 25))

    return ToolResult(tool_name="search_customer", success=True, data=data)



async def _get_customer(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await customer_service.get(organization_id, customer_id=uuid.UUID(kw["customer_id"]))

    return ToolResult(tool_name="get_customer", success=True, data=data)



async def _create_customer(organization_id: uuid.UUID, **kw) -> ToolResult:

    if "customer_name" in kw and "name" not in kw:
        kw["name"] = kw.pop("customer_name")

    data = await customer_service.create(organization_id, **kw)

    return ToolResult(tool_name="create_customer", success=True, data=data)



async def _get_customer_ledger(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await customer_service.get_ledger(organization_id, customer_id=uuid.UUID(kw["customer_id"]))

    return ToolResult(tool_name="get_customer_ledger", success=True, data=data)



# ===================================================================

# SUPPLIER TOOLS

# ===================================================================



async def _search_supplier(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await supplier_service.search(organization_id, query=kw.get("query", ""), limit=kw.get("limit", 25))

    return ToolResult(tool_name="search_supplier", success=True, data=data)



async def _get_supplier(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await supplier_service.get(organization_id, supplier_id=uuid.UUID(kw["supplier_id"]))

    return ToolResult(tool_name="get_supplier", success=True, data=data)



async def _create_supplier(organization_id: uuid.UUID, **kw) -> ToolResult:

    if "supplier_name" in kw and "name" not in kw:
        kw["name"] = kw.pop("supplier_name")

    data = await supplier_service.create(organization_id, **kw)

    return ToolResult(tool_name="create_supplier", success=True, data=data)



async def _get_supplier_ledger(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await supplier_service.get_ledger(organization_id, supplier_id=uuid.UUID(kw["supplier_id"]))

    return ToolResult(tool_name="get_supplier_ledger", success=True, data=data)



# ===================================================================

# ACCOUNT TOOLS

# ===================================================================



async def _search_account(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await account_repo.search_accounts(organization_id, query=kw.get("query", ""))

    return ToolResult(tool_name="search_account", success=True, data=data)



async def _get_chart_of_accounts(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await account_repo.get_chart_of_accounts(organization_id, account_type=kw.get("account_type"))

    return ToolResult(tool_name="get_chart_of_accounts", success=True, data=data)



#: Normal balance by account type — used only when creating a MISSING

#: section HEADING for ``parent_account_name``; the heading's shape

#: defaults to the child's type (a parent is never invented from thin air).

_NORMAL_BY_TYPE = {

    "ASSET": "DEBIT",

    "EXPENSE": "DEBIT",

    "LIABILITY": "CREDIT",

    "EQUITY": "CREDIT",

    "REVENUE": "CREDIT",

}





async def _create_account(organization_id: uuid.UUID, **kw) -> ToolResult:

    # Explicit account-creation requests MUST NOT fail on a colliding code

    # (a suggested code such as 6150 may already exist; the unique constraint

    # would fire and the operation would silently degrade to the default

    # expense account).  Resolve a free code in the same numbering

    # series BEFORE the insert; the DB unique constraint remains the

    # last line of defence.

    requested_code = str(kw.get("code") or "").strip()

    requested_name = str(kw.get("name") or "").strip()

    _child_type = str(kw.get("account_type") or "").strip().upper()

    if not requested_code or requested_code.upper() == "AUTO":
        _DEFAULT_STARTING_CODES = {
            "ASSET": "1500",
            "LIABILITY": "2100",
            "EQUITY": "3100",
            "REVENUE": "4100",
            "EXPENSE": "6100",
        }
        requested_code = _DEFAULT_STARTING_CODES.get(_child_type, "6100")
        kw["code"] = requested_code

    if not kw.get("normal_balance") and _child_type in _NORMAL_BY_TYPE:
        kw["normal_balance"] = _NORMAL_BY_TYPE[_child_type]



    # Search-before-create (P2): an exact (case/trim-insensitive) name match

    # means the requested ledger already exists — REUSE it.  The unique

    # constraint only guards (organization_id, code); without this check an

    # explicit "create Rent Expense - Building A" request could create a

    # second ledger with the same name under a different code.

    if requested_name:

        try:

            candidates = await account_repo.search_accounts(

                organization_id, query=requested_name, limit=25

            )

        except Exception as exc:  # noqa: BLE001 — search is best-effort

            log.warning("tools.create_account.search_failed", error=str(exc)[:200])

            candidates = []

        exact = [

            c for c in candidates

            if (c.get("name") or "").strip().lower() == requested_name.lower()

        ]

        if exact:

            existing = exact[0]

            log.info(

                "tools.create_account.reused_existing",

                name=requested_name,

                code=existing.get("code"),

            )

            return ToolResult(

                tool_name="create_account",

                success=True,

                data={

                    **existing,

                    "reused_existing": True,

                    "note": (

                        f"An account named '{requested_name}' already exists "

                        f"(code {existing.get('code')}) — it was reused; no "

                        "duplicate ledger was created."

                    ),

                },

            )



    # MISSING-HEAD PREREQUISITE: an explicitly named parent that does not

    # exist yet is CREATED FIRST (a grouping account of the child's type),

    # so "create X under <heading>" never fails on a sparse chart.  An

    # EXISTING parent must MATCH the child's type — an expense must never

    # hang under an asset heading (production 2026-09-30).  No name, an

    # unknown child type, or a type clash -> the parent is ignored and the

    # child is created top-level (a parent is never invented).

    requested_parent = str(kw.pop("parent_account_name", "") or "").strip()

    parent_heading: Optional[Dict[str, Any]] = None

    if requested_parent and not kw.get("parent_account_id"):

        _child_type = str(kw.get("account_type") or "").strip().upper()

        try:

            parent_hits = await account_repo.search_accounts(

                organization_id, query=requested_parent, limit=25

            )

        except Exception as exc:  # noqa: BLE001 — search is best-effort

            log.warning(

                "tools.create_account.parent_search_failed",

                error=str(exc)[:200],

            )

            parent_hits = []

        _name_row = next(

            (

                row for row in parent_hits or ()

                if str(row.get("name") or "").strip().lower()

                == requested_parent.lower()

            ),

            None,

        )

        if (

            _name_row is not None

            and str(_name_row.get("account_type") or "").upper() == _child_type

        ):

            # Exact-name match of the SAME type — reuse it.

            kw["parent_account_id"] = str(_name_row["id"])

            parent_heading = {

                "id": str(_name_row["id"]),

                "name": _name_row.get("name"),

                "created": False,

            }

        elif (

            _name_row is None

            and _child_type in _NORMAL_BY_TYPE

            and str(kw.get("code") or "").strip()

        ):

            # The heading is absent — create it as a top-level GROUPING

            # account of the child's type (it becomes a heading the moment

            # the child is parented under it), then parent the child.

            _heading_normal = (

                str(kw.get("normal_balance") or "").strip()

                or _NORMAL_BY_TYPE[_child_type]

            )

            _heading = None

            try:

                _heading_code = await account_repo.next_available_code(

                    organization_id, str(kw.get("code") or "").strip()

                )

                _heading = await account_repo.create_account(

                    organization_id=organization_id,

                    code=_heading_code,

                    name=requested_parent,

                    account_type=_child_type,

                    normal_balance=_heading_normal,

                    description=(

                        "Section heading created automatically for a new "

                        "account."

                    ),

                )

            except Exception as exc:  # noqa: BLE001 — never fatal to the child

                log.warning(

                    "tools.create_account.parent_heading_failed",

                    error=str(exc)[:200],

                )

                _heading = None

            if isinstance(_heading, dict) and _heading.get("id"):

                kw["parent_account_id"] = str(_heading["id"])

                parent_heading = {

                    "id": str(_heading["id"]),

                    "name": _heading.get("name"),

                    "created": True,

                }



    try:

        resolved_code = await account_repo.next_available_code(

            organization_id, requested_code

        )

    except Exception as exc:  # noqa: BLE001 — surfaced to the agent

        return ToolResult(

            tool_name="create_account",

            success=False,

            error=(

                f"Could not resolve a free account code near '{requested_code}': {exc}. "

                "Ask the user which account code series to use."

            ),

        )

    if resolved_code != requested_code:

        log.info(

            "tools.create_account.code_resolved",

            requested=requested_code,

            resolved=resolved_code,

        )

        kw = {**kw, "code": resolved_code}

    data = await account_repo.create_account(organization_id=organization_id, **kw)

    if resolved_code != requested_code:

        data["code_resolved_from"] = requested_code

    if parent_heading is not None:

        # Audit trail: the agent's narrative can state whether the heading

        # was REUSED or CREATED — never silently.

        data["parent_heading"] = parent_heading

    return ToolResult(tool_name="create_account", success=True, data=data)





async def _derive_purchase_nature(

    organization_id: uuid.UUID, kw: Dict[str, Any]

) -> str:

    """``"INVENTORY"`` when the bill's OWN data proves resale stock, else ``""``.



    Two deterministic signals, in order of authority (audit fix — the fast

    path and a minimal model reply may omit ``transaction_nature``):



    1. a line already linked to a ``is_stock_tracked`` catalogue product —

       the catalogue flag IS the user's resale answer (authoritative);

    2. the intent family's OWN wording rules (``derive_nature_from_text`` —

       the exact function the planner applies to the request), limited to

       the INVENTORY outcome: other natures remain the classifier's job.



    Never raises; never guesses: no signal → ``""`` → the caller keeps

    whatever it was given (status quo behaviour).

    """

    # 1. Authoritative product flag.

    for line in kw.get("items") or ():

        if not isinstance(line, dict):

            continue

        pid = line.get("product_id")

        if not pid:

            continue

        try:

            product = await product_service.get(

                organization_id, product_id=uuid.UUID(str(pid))

            )

        except Exception:  # noqa: BLE001 — per line, never fatal

            product = None

        if product and product.get("is_stock_tracked"):

            return "INVENTORY"



    # 2. The family's wording rules over the bill's own text.

    text = " ".join(

        str(x)

        for x in (

            kw.get("notes"),

            *(

                str(l.get("description") or "")

                for l in kw.get("items") or ()

                if isinstance(l, dict)

            ),

        )

        if x

    )

    if not text.strip():

        return ""

    try:

        from app.reasoning import derive_nature_from_text



        for intent in ("create_purchase_bill", "record_purchase"):

            nature = derive_nature_from_text(intent, text)

            if str(nature or "").upper() == "INVENTORY":

                return "INVENTORY"

    except Exception as exc:  # noqa: BLE001 — recovery is best-effort

        log.warning(

            "tools.create_purchase_bill.nature_recovery_failed",

            error=str(exc)[:200],

        )

    return ""





async def _link_products_to_items(

    organization_id: uuid.UUID, items: Optional[List[Dict[str, Any]]]

) -> None:

    """Attach ``product_id`` to SALE lines by catalogue match.



    The perpetual-inventory COGS trigger only values lines that reference a

    product; the sale paths (fast path, model, form) describe the item in

    TEXT and historically never linked it — so revenue posted while Cost of

    Sales was silently skipped (audit finding).  Read-only, best-effort: an

    unmatched line keeps its text and the engine's honest per-line handling

    decides.



    MATCH LADDER (2026-10-20, per-item decrement fix): EXACT case-insensitive

    name first (the safe deterministic floor); then the LLM CATALOGUE ANALYST

    over the fetched candidates — "is this sale line the SAME product as an

    existing stock-tracked entry?" is a semantic judgment, so the model

    decides and only the exact-name floor remains as the disabled/unavailable

    fallback.  A sale worded differently than the purchase ("office chairs"

    vs catalogue "chair") still links to the SAME product and decrements THAT

    item's stock.  Unmatched -> keeps its text; the engine's honest per-line

    handling decides.

    """

    from app.catalogue_matching import exact_name_match, llm_match_catalogue_item



    for item in items or ():

        if not isinstance(item, dict) or item.get("product_id"):

            continue

        name = str(item.get("description") or "").strip()

        if not name:

            continue

        try:

            hits = await product_service.search(

                organization_id, query=name, limit=25

            ) or []

        except Exception as exc:  # noqa: BLE001 — linkage is best-effort

            log.warning(

                "tools.sale.product_link_search_failed",

                error=str(exc)[:200],

            )

            continue

        # Exact-name floor first — the safest link, no model needed.

        chosen = await exact_name_match(name, hits)

        if not (chosen and chosen.get("id")):

            # LLM analyst — only against STOCK-TRACKED candidates, so a sale

            # of a non-stock line never links (and never issues stock).

            tracked = [p for p in hits if p.get("is_stock_tracked")]

            word = await llm_match_catalogue_item(name, tracked)

            if word and word.get("id"):

                chosen = word

                log.info(

                    "tools.sale.product_linked_by_llm_match",

                    description=name, matched=str(word.get("name")),

                    product_code=word.get("product_code"),

                )

        if chosen and chosen.get("id"):

            item["product_id"] = str(chosen["id"])





async def _record_cash_sale(organization_id: uuid.UUID, **kw) -> ToolResult:

    """Trusted cash-sale domain operation.



    The model NEVER assembles this journal manually: the tool resolves the

    Cash and Revenue accounts deterministically from the organisation's

    chart of accounts, delegates journal construction to the accounting

    engine, and auto-validates + auto-posts (same convention as

    create_expense / create_purchase_bill).  Session-level duplicate

    protection lives in the tool router.

    """

    amount = float(kw["amount"])

    transaction_date = kw.get("transaction_date") or date.today().isoformat()

    description = kw.get("description") or f"Cash sale {amount:,.2f}"

    log.info(

        "sale_tool_started",

        organization_id=str(organization_id),

        tool="record_cash_sale",

        amount=amount,

    )



    cash = await accounting_service.resolve_account(

        organization_id, account_name="Cash"

    )

    if not cash:

        cash = await accounting_service.resolve_account(

            organization_id, account_name="Cash Account"

        )

    if not cash:

        assets = await account_repo.get_chart_of_accounts(

            organization_id, account_type="ASSET", limit=5

        )

        cash = assets[0] if assets else None

    # ---- REVENUE ACCOUNT -------------------------------------------------

    # DIRECTIVE: never "the first REVENUE account in the chart".  See

    # app/services/revenue_ledger_service.py — an unresolved revenue stream is

    # a QUESTION for the user, not a coin toss.  The previous fuzzy fallback

    # credited a MOBILE PHONE sale to *Software Development Revenue* purely

    # because that account sorted first in a software house's chart.

    from app.services import revenue_ledger_service



    # A REVIEWED account is authoritative: the user approved a dedicated stream

    # ledger (or named an existing one), so use exactly that account.  Only when

    # nothing was reviewed does the service resolve one deliberately.

    revenue = None

    revenue_source = "reviewed"

    stream = revenue_ledger_service.stream_label(description)

    override_id = kw.get("revenue_account_id")

    if override_id:

        rows = await account_repo.get_chart_of_accounts(

            organization_id, account_type="REVENUE", limit=200

        )

        revenue = next(

            (r for r in (rows or []) if str(r.get("id")) == str(override_id)),

            None,

        )

        if revenue is None:

            return ToolResult(

                tool_name="record_cash_sale",

                success=False,

                error=(

                    "The reviewed revenue account is not present in this "

                    "organisation's chart of accounts. Ask the user which "

                    "revenue account to use."

                ),

            )

    else:

        revenue, stream, revenue_source = (

            await revenue_ledger_service.resolve_revenue_account(

                organization_id, description

            )

        )

    if revenue is None:

        if stream:

            ask = (

                "This sale has no dedicated revenue ledger. Ask the user "

                "whether to create a dedicated revenue ledger named "

                f"'{revenue_ledger_service.suggest_ledger_name(stream)}' for "

                f"'{stream}', and which existing revenue account it should "

                "belong under — or which existing revenue account to use "

                "instead. Never choose a revenue account silently."

            )

        else:

            ask = (

                "The item sold was not specific enough to name a revenue "

                "ledger, and the chart has more than one revenue account. "

                "Ask the user which revenue account this sale belongs to."

            )

        log.warning(

            "sale_tool_failed",

            organization_id=str(organization_id),

            tool="record_cash_sale",

            stage="revenue_resolution",

        )

        return ToolResult(

            tool_name="record_cash_sale", success=False, error=ask

        )

    if not cash:

        log.warning(

            "sale_tool_failed",

            organization_id=str(organization_id),

            tool="record_cash_sale",

            stage="cash_resolution",

        )

        return ToolResult(

            tool_name="record_cash_sale",

            success=False,

            error=(

                "Cannot resolve the Cash account in the chart of accounts. "

                "Ask the user which asset account to use."

            ),

        )



    customer_id = kw.get("customer_id")

    # Stock-tracked lines the customer actually bought.  PERPETUAL INVENTORY:

    # the SALE triggers cost recognition (Dr Cost of Sales / Cr Inventory) —

    # never the purchase.  Optional: a service-only cash sale carries no items

    # and behaves exactly as before.  AUDIT FIX: link lines to their catalogue

    # product (EXACT name match) first — the COGS engine only values lines

    # carrying product_id, so an unlinked line posted revenue with NO cost.

    items = kw.get("items") or None

    if not items and (kw.get("product_id") or kw.get("quantity") or kw.get("item_description")):

        raw_qty = kw.get("quantity") or 1.0

        try:

            quantity = float(raw_qty) if raw_qty is not None else 1.0

        except (TypeError, ValueError):

            quantity = 1.0

        if quantity <= 0:

            quantity = 1.0

        item_desc = str(kw.get("item_description") or description)

        items = [{

            "description": item_desc,

            "quantity": quantity,

            "unit_price": round(amount / quantity, 2),

            "product_id": kw.get("product_id"),

        }]

    if items:

        try:

            await _link_products_to_items(organization_id, items)

        except Exception as exc:  # noqa: BLE001 — never block the sale

            log.warning("tools.record_cash_sale.product_link_failed",

                        error=str(exc)[:200])

    result = await record_cash_sale(

        organization_id=organization_id,

        cash_account_id=uuid.UUID(str(cash["id"])),

        revenue_account_id=uuid.UUID(str(revenue["id"])),

        amount=amount,

        transaction_date=transaction_date,

        description=description,

        customer_id=(

            uuid.UUID(str(customer_id)) if customer_id else None

        ),

        items=items,

    )

    # Auto-validate + auto-post — same convention as the other trusted

    # document tools (deterministic backend calls, never an LLM decision).

    # NOTE: record_cash_sale returns prepare_journal's dict directly:

    # {"entry": <row>, "lines": [...], "total_debit", "total_credit"} —

    # the row is at result["entry"], NOT nested one level deeper.

    entry = result.get("entry") or {}

    if entry.get("id"):

        try:

            entry_id = uuid.UUID(entry["id"])

            await accounting_service.validate_journal(entry_id=entry_id)

            await accounting_service.post_journal(entry_id=entry_id)

            result["journal_posted"] = True

        except Exception as exc:  # noqa: BLE001 — never fake success

            log.warning(

                "tools.record_cash_sale.post_journal_failed",

                entry_id=str(entry.get("id")),

                error=str(exc)[:300],

            )

            result["journal_posted"] = False

            result["journal_warning"] = f"Journal prepared but posting failed: {exc}"

    # PERPETUAL INVENTORY: a posted CASH SALE also triggers cost recognition

    # — the same Dr Cost of Sales / Cr Inventory entry the invoice path

    # prepares, derived from the stock-tracked lines (if any).  A pure

    # service cash sale passes no items and simply has no COGS.  Any failure

    # is a warning; the revenue entry already stands (C4).

    if result.get("journal_posted"):

        cogs_items = items or kw.get("items") or []

        if cogs_items:

            cogs = await prepare_cogs_for_items(

                organization_id,

                items=cogs_items,

                transaction_date=transaction_date,

                description=description,

            )

            result.update(cogs)

            await _post_cogs_and_issue_stock(

                organization_id,

                result,

                source_type="cash_sale",

                movement_date=transaction_date,

                description=description,

                source_id=(

                    uuid.UUID(entry["id"]) if entry.get("id") else None

                ),

            )

    result["cash_account"] = cash.get("name")

    result["revenue_account"] = revenue.get("name")

    # Audit trail: HOW the revenue account was chosen (stream / only-one), so a

    # reviewer can see it was resolved deliberately rather than by sort order.

    result["revenue_account_source"] = revenue_source

    if stream:

        result["revenue_stream"] = stream



    log.info(

        "sale_tool_succeeded",

        organization_id=str(organization_id),

        tool="record_cash_sale",

        journal_posted=bool(result.get("journal_posted")),

        revenue_account_id=str(revenue.get("id")),

        reviewed=bool(kw.get("revenue_account_id")),

    )

    return ToolResult(tool_name="record_cash_sale", success=True, data=result)



# ===================================================================

# CASH PURCHASE TOOL (2026-10-20)

# ===================================================================

async def _record_cash_purchase(organization_id: uuid.UUID, **kw) -> ToolResult:

    """Trusted cash-purchase domain operation — NO bill, NO payable.



    A CASH purchase is settled the moment it happens, so it is a DIRECT

    two-line journal, never a supplier invoice:

        Dr  Inventory (resale stock) / fixed-asset / expense  — the debit

        Cr  Cash or Bank                                      — the money out

    The old path created a purchase BILL row then marked it PAID (a phantom

    payable document).  Here NO `purchase_bills` row is written and no

    Accounts-Payable ledger is touched.



    * CASH LEDGER — resolved by NAME and CREATED on demand when the chart has

      none (``ensure_cash_account``): the credit lands on a real Cash/Bank

      asset, never silently on "first ASSET" (= Accounts Receivable).

      Creation is disclosed as ``cash_account_created``.

    * DEBIT LEDGER — same ladder as the bill path: INVENTORY debits the

      Inventory valuation account (created on demand) and syncs the catalogue

      + receives stock UNITS (settlement-agnostic: cash AND credit track

      units); otherwise a validated asset/expense hint or the generic default.

    * auto-validates + auto-posts the journal (deterministic, never LLM).

    """

    amount = float(kw.get("amount") or 0)

    if amount <= 0:

        return ToolResult(

            tool_name="record_cash_purchase", success=False,

            error="A cash purchase needs a positive amount.",

        )

    transaction_date = kw.get("transaction_date") or date.today().isoformat()

    description = kw.get("description") or f"Cash purchase {amount:,.2f}"

    transaction_nature = str(kw.get("transaction_nature") or "").strip()

    is_inventory = transaction_nature.upper() == "INVENTORY"



    from app import accounting_engine as _engine



    # ---- DEBIT LEDGER -----------------------------------------------------

    account_hint = _safe_account_hint(kw.get("account_id"))

    inventory_ledger = None

    if is_inventory:

        try:

            inventory_ledger = await _engine.ensure_inventory_account(

                organization_id, hint_account=account_hint

            )

        except Exception as exc:  # noqa: BLE001 — lookup failure ≠ absence

            log.warning(

                "tools.record_cash_purchase.inventory_resolve_failed",

                error=str(exc)[:200],

            )

            inventory_ledger = None

        if not inventory_ledger:

            return ToolResult(

                tool_name="record_cash_purchase", success=False,

                error=(

                    "INVENTORY cash purchase refused: no postable 'Inventory' "

                    "ASSET ledger exists and one could not be created. NOTHING "

                    "was recorded. Create an Inventory asset account, then "

                    "repeat the purchase."

                ),

            )

        debit_account = inventory_ledger

    else:

        debit_account = None

        if account_hint and account_hint.get("account_type") in ("EXPENSE", "ASSET"):

            debit_account = account_hint

        if not debit_account:

            try:

                debit_account = await _engine._resolve_default_account(

                    organization_id, "EXPENSE"

                )

            except Exception:  # noqa: BLE001

                debit_account = None

        if not debit_account:

            return ToolResult(

                tool_name="record_cash_purchase", success=False,

                error=(

                    "Cannot resolve the debit account (expense/asset) for this "

                    "cash purchase. Ask the user which account to debit, then "

                    "repeat it."

                ),

            )



    # ---- CASH LEDGER (resolve, CREATE when missing) -----------------------

    cash_account = await ensure_cash_account(organization_id)

    if not cash_account:

        return ToolResult(

            tool_name="record_cash_purchase", success=False,

            error=(

                "Cannot resolve (or create) a Cash/Bank asset ledger for this "

                "cash purchase. Ask the user which asset account holds cash, "

                "then repeat it."

            ),

        )



    # ---- JOURNAL: Dr debit / Cr cash — prepared, validated, posted --------

    try:

        prepared = await record_cash_purchase(

            organization_id=organization_id,

            asset_account_id=uuid.UUID(str(debit_account["id"])),

            cash_account_id=uuid.UUID(str(cash_account["id"])),

            amount=amount,

            transaction_date=transaction_date,

            description=description,

        )

    except Exception as exc:  # noqa: BLE001 — never crash the turn

        log.warning(

            "tools.record_cash_purchase.prepare_failed", error=str(exc)[:300]

        )

        return ToolResult(

            tool_name="record_cash_purchase", success=False,

            error=f"Could not prepare the cash-purchase journal: {exc}",

        )



    result: Dict[str, Any] = dict(prepared)

    entry = prepared.get("entry") or {}

    if entry.get("id"):

        try:

            entry_id = uuid.UUID(entry["id"])

            await accounting_service.validate_journal(entry_id=entry_id)

            await accounting_service.post_journal(entry_id=entry_id)

            result["journal_posted"] = True

        except Exception as exc:  # noqa: BLE001 — never fake success

            log.warning(

                "tools.record_cash_purchase.post_journal_failed",

                entry_id=str(entry.get("id")), error=str(exc)[:300],

            )

            result["journal_posted"] = False

            result["journal_warning"] = (

                f"Journal prepared but posting failed: {exc}"

            )



    result["debit_account"] = debit_account.get("name")

    result["cash_account"] = cash_account.get("name")

    if cash_account.get("cash_account_created"):

        # HONEST WRITE DISCLOSURE: the Cash ledger creation WAS a database

        # write — reported, never disguised as a read.

        result["cash_account_created"] = True

    result["transaction_nature"] = (

        "INVENTORY" if is_inventory

        else (transaction_nature or debit_account.get("account_type"))

    )



    # ---- PERPETUAL INVENTORY: catalogue sync + stock receipt --------------

    # Settlement-agnostic (cash AND credit both receive units).  Only after a

    # posted journal — an unposted journal never moved value into Inventory,

    # so the quantity ledger must not move either.

    if is_inventory and result.get("journal_posted") and kw.get("items"):

        stock_warnings: list = []

        received: list = []

        synced_items: list = []

        for raw in kw["items"]:

            item = dict(raw)

            if not item.get("product_id") and item.get("description"):

                try:

                    product = await inventory_service.find_or_create_catalogue_product(

                        organization_id,

                        name=str(item["description"]),

                        quantity=float(item.get("quantity") or 0),

                        unit_cost=float(item.get("unit_price") or 0),

                    )

                except Exception as exc:  # noqa: BLE001 — never fatal

                    product = None

                    log.warning(

                        "tools.record_cash_purchase.catalogue_sync_failed",

                        error=str(exc)[:200],

                    )

                if product and product.get("id"):

                    item["product_id"] = str(product["id"])

                else:

                    stock_warnings.append(

                        f"Catalogue sync failed for '{item.get('description')}' "

                        "— the stock ledger cannot track this line."

                    )

            pid = item.get("product_id")

            if pid:

                try:

                    qty = float(item.get("quantity") or 0)

                    gross = qty * float(item.get("unit_price") or 0)

                    discount = float(item.get("discount_amount") or 0)

                    unit_cost = (gross - discount) / qty if qty else 0.0

                    movement = await inventory_service.receive_stock(

                        organization_id,

                        product_id=uuid.UUID(str(pid)),

                        quantity=qty,

                        unit_cost=round(unit_cost, 4),

                        source_type="cash_purchase",

                        source_id=(

                            uuid.UUID(str(entry["id"])) if entry.get("id") else None

                        ),

                        movement_date=transaction_date,

                        description=item.get("description"),

                    )

                    received.append({

                        "product_id": str(pid),

                        "quantity": qty,

                        "unit_cost": round(unit_cost, 4),

                        "movement_id": str(movement.get("id")),

                    })

                except Exception as exc:  # noqa: BLE001 — never fatal

                    stock_warnings.append(

                        f"Stock receipt failed for line "

                        f"'{item.get('description')}': {exc}"

                    )

            synced_items.append(item)

        result["items"] = synced_items

        if received:

            result["stock_received"] = received

        if stock_warnings:

            result["stock_warning"] = " ".join(stock_warnings)



    log.info(

        "cash_purchase_tool_succeeded",

        organization_id=str(organization_id),

        journal_posted=bool(result.get("journal_posted")),

        debit_account=str(debit_account.get("name")),

        cash_account=str(cash_account.get("name")),

        cash_account_created=bool(cash_account.get("cash_account_created")),

    )

    return ToolResult(tool_name="record_cash_purchase", success=True, data=result)



# ===================================================================

# INVOICE TOOLS

# ===================================================================



async def _create_invoice(organization_id: uuid.UUID, **kw) -> ToolResult:

    if "customer_id" in kw and isinstance(kw["customer_id"], str):
        kw["customer_id"] = uuid.UUID(kw["customer_id"])
    elif "customer_id" not in kw and kw.get("customer_name"):
        cname = str(kw.pop("customer_name")).strip()
        found = await customer_service.search(organization_id, query=cname, limit=1)
        if found:
            kw["customer_id"] = uuid.UUID(str(found[0]["id"]))
        else:
            created = await customer_service.create(organization_id, name=cname)
            kw["customer_id"] = uuid.UUID(str(created["id"]))

    if not kw.get("items") and (kw.get("total") or kw.get("amount")):
        tot = float(kw.get("total") or kw.get("amount") or 0.0)
        desc = kw.get("description") or "Sales"
        kw["items"] = [{"description": desc, "quantity": 1.0, "unit_price": tot, "total": tot}]
        kw["total"] = tot
        kw["subtotal"] = tot

    # PERPETUAL INVENTORY (audit fix): link every sale line to its catalogue

    # product (EXACT name match) BEFORE persistence — the COGS trigger only

    # values lines carrying product_id, and the atomic posting RPC persists

    # the same payload, so journal + lines + stock issue all see the link.

    if kw.get("items"):

        try:

            await _link_products_to_items(organization_id, kw["items"])

        except Exception as exc:  # noqa: BLE001 — never block the revenue doc

            log.warning("tools.create_invoice.product_link_failed",

                        error=str(exc)[:200])

    data = await invoice_service.create_invoice(organization_id=organization_id, **kw)

    # C3+C4: Atomic document + journal creation

    amount = float(data.get("total", 0))

    if amount > 0:

        journal_result = await auto_journal(

            organization_id=organization_id,

            document_type="invoice",

            document=data,

            amount=amount,

            transaction_date=data.get("invoice_date", ""),

            description=f"Invoice {data.get('invoice_number', data.get('id', ''))}",

            customer_id=kw.get("customer_id"),

            project_id=kw.get("project_id"),

        )

        data.update(journal_result)

        # Auto-validate + auto-post the invoice journal — same convention as

        # create_purchase_bill / payment_service / create_expense: a recorded

        # invoice is a real receivable event; the ledger must reflect it

        # immediately instead of leaving a DRAFT journal behind (a recorded

        # invoice must never leave a DRAFT journal). Deterministic backend

        # calls — never an LLM decision.

        prepared = journal_result.get("journal_entry") or {}

        entry = prepared.get("entry") or {}

        if entry.get("id"):

            try:

                entry_id = uuid.UUID(entry["id"])

                await accounting_service.validate_journal(entry_id=entry_id)

                await accounting_service.post_journal(entry_id=entry_id)

                # Source-tie the journal back to the invoice row and leave

                # DRAFT — mirrors quotation_service.convert_quotation. A

                # posted invoice journal is a real receivable event: the

                # invoice must carry journal_entry_id and sit in ISSUED so

                # v_open_receivables / v_customer_aging reflect it (they

                # filter out DRAFT): a POSTED journal with the invoice left

                # DRAFT and a NULL journal_entry_id would show a receivable

                # in the ledger that the aging views hide.

                from app.repositories import invoice_repository as inv_repo

                await inv_repo.link_journal_to_invoice(

                    invoice_id=uuid.UUID(str(data["id"])),

                    journal_entry_id=entry_id,

                )

                await inv_repo.mark_issued(

                    invoice_id=uuid.UUID(str(data["id"]))

                )

                data["journal_entry_id"] = str(entry_id)

                data["status"] = "ISSUED"

                data["journal_posted"] = True

            except Exception as exc:  # noqa: BLE001 — never fake success

                log.warning(

                    "tools.create_invoice.post_journal_failed",

                    entry_id=str(entry.get("id")),

                    error=str(exc)[:300],

                )

                data["journal_posted"] = False

                data["journal_warning"] = (

                    f"Journal prepared but posting failed: {exc}"

                )

        if data.get("journal_posted"):

            # PERPETUAL INVENTORY: the posted sale triggers cost recognition

            # (the engine prepared the COGS journal inside auto_journal from

            # the stock-tracked lines) — post it and issue the stock.

            await _post_cogs_and_issue_stock(

                organization_id,

                data,

                source_type="invoice",

                movement_date=data.get("invoice_date"),

                description=f"Invoice {data.get('invoice_number', data.get('id', ''))}",

            )

    return ToolResult(tool_name="create_invoice", success=True, data=data)



async def _get_invoice(organization_id: uuid.UUID, **kw) -> ToolResult:

    """Fetch by id OR by the human number (the only form a user speaks).



    "invoice no.12" / "INV-000011" resolve read-only, org-scoped, EXACT-match

    (invoice_repository.get_invoice_by_number) — never a fuzzy guess; a miss

    returns a named question the model can act on instead of the KeyError

    this handler used to raise on a number-keyed call (no by-number reader

    existed — the gap that killed the production credit-note turns).

    """

    invoice_id = kw.get("invoice_id")

    # REFERENCE-SHAPED ID (2026-10-19): models pass the document NUMBER in

    # the id field ("INV-000014") — the uuid coercion below then died with

    # "badly formed hexadecimal UUID string" (read-only, but the lookup

    # evidence was lost).  A non-uuid id is resolved AS the number here.

    if invoice_id:

        try:

            uuid.UUID(str(invoice_id))

        except (ValueError, TypeError):

            kw["invoice_number"] = kw.get("invoice_number") or str(invoice_id)

            invoice_id = None

    if not invoice_id:

        number = str(kw.get("invoice_number") or "").strip()

        if not number:

            return ToolResult(

                tool_name="get_invoice",

                success=False,

                error="get_invoice needs invoice_id or invoice_number.",

            )

        from app.repositories import invoice_repository



        row = await invoice_repository.get_invoice_by_number(

            organization_id, invoice_number=number

        )

        if not row:

            # Wire the BOOKS into the retry without rendering anything into

            # prompts: name the closest REFERENCE candidates (org-scoped,

            # newest invoices) so the model — or its clarifying question —

            # can carry a REAL number the user will recognise ("no.12" ->

            # did you mean INV-000011?).  Numbers + minimal identity only;

            # the invoice itself only ever arrives as a get_invoice RESULT.

            try:

                from app.repositories import invoice_repository



                recent = await invoice_repository.list_invoices(

                    organization_id, limit=5

                )

            except Exception:  # noqa: BLE001 — candidates are best-effort

                recent = []

            candidates = "; ".join(

                f"{r.get('invoice_number')} ({r.get('invoice_date')}, {r.get('total')})"

                for r in (recent or []) if r.get("invoice_number")

            )

            suffix = (

                f"  Recent invoices in your books: {candidates} — use the "

                "exact number (e.g. INV-000011) or ask the user which "

                "invoice they mean; never invent an invoice id."

                if candidates else

                " Check the number (e.g. INV-000011) or read the customer "

                "ledger first; never invent an invoice id."

            )

            return ToolResult(

                tool_name="get_invoice",

                success=False,

                error=f"No invoice numbered {number!r} exists in your books. {suffix}",

            )

        invoice_id = str(row["id"])

    data = await invoice_service.get_invoice(organization_id, invoice_id=uuid.UUID(str(invoice_id)))

    return ToolResult(tool_name="get_invoice", success=True, data=data)



# ===================================================================

# PURCHASE TOOLS

# ===================================================================



def _safe_account_hint(value: Any) -> Optional[uuid.UUID]:

    """Parse an optional account hint (account_id) from tool arguments."""

    if not value:

        return None

    try:

        return uuid.UUID(str(value))

    except (ValueError, TypeError, AttributeError):

        return None





async def _post_cogs_and_issue_stock(

    organization_id: uuid.UUID,

    data: Dict[str, Any],

    *,

    source_type: str,

    movement_date: Optional[str] = None,

    description: str = "",

    source_id: Optional[uuid.UUID] = None,

) -> None:

    """Post the prepared Cost-of-Sales journal, then issue the stock.



    ORDER MATTERS (skeptical by design): stock leaves the ledger only when

    the COGS journal actually POSTED — a prepared-but-unposted journal never

    hit the GL, so the quantity ledger must not move either (GL/ledger

    divergence is the one failure a perpetual system cannot survive).

    Every failure becomes an honest key on *data*; never raises.

    """

    cogs_prepared = data.get("cogs_entry") or {}

    cogs_entry = cogs_prepared.get("entry") or {}

    if cogs_entry.get("id"):

        try:

            cogs_id = uuid.UUID(cogs_entry["id"])

            await accounting_service.validate_journal(entry_id=cogs_id)

            await accounting_service.post_journal(entry_id=cogs_id)

            data["cogs_journal_posted"] = True

            data["cogs_journal_entry_id"] = str(cogs_id)

        except Exception as exc:  # noqa: BLE001 — never fake success

            log.warning(

                "tools.sale.cogs_post_failed",

                entry_id=str(cogs_entry.get("id")),

                error=str(exc)[:300],

            )

            data["cogs_journal_posted"] = False

            data["cogs_warning"] = (

                "The revenue entry posted, but the Cost-of-Sales journal "

                f"could NOT be posted: {exc}. Inventory was NOT relieved — "

                "record the cost recognition after fixing the accounts."

            )

            return  # NO stock issue for an unposted COGS journal

    else:

        # LIVE-CAUGHT (E2E 2026-10-13): valuations exist but NO journal was

        # ever prepared (chart lacked the Cost of Sales head and creation

        # failed).  Issuing stock here would move the quantity ledger

        # WITHOUT moving value in the GL — the divergence a perpetual system

        # cannot survive.  Block the issue; keep prepare's honest warning.

        if data.get("cogs_lines"):

            data["cogs_journal_posted"] = False

            data.setdefault(

                "cogs_warning",

                "The Cost-of-Sales journal was never prepared — inventory "

                "was NOT relieved (no GL/ledger divergence).",

            )

        return



    failed_lines: list = []

    doc_source_id = (

        source_id

        or (uuid.UUID(str(data["id"])) if data.get("id") else None)

    )

    for line in data.get("cogs_lines") or ():

        try:

            await inventory_service.issue_stock(

                organization_id,

                product_id=uuid.UUID(str(line["product_id"])),

                quantity=float(line["quantity"]),

                unit_cost=float(line["unit_cost"]),

                source_type=source_type,

                source_id=doc_source_id,

                movement_date=movement_date,

                description=description or None,

            )

        except Exception as exc:  # noqa: BLE001 — per line, never fatal

            failed_lines.append(str(exc))

    if failed_lines:

        data["cogs_warning"] = " ".join(failed_lines)





async def _create_purchase_bill(organization_id: uuid.UUID, **kw) -> ToolResult:

    # Arguments the HANDLER consumes (declared as extra contract arguments):

    #   account_id         — journal hint, validated by the accounting engine;

    #   transaction_nature — INVENTORY routes the debit to the Inventory

    #                        valuation account (perpetual inventory) and

    #                        triggers catalogue + stock-ledger sync;

    #   payment_method     — CASH credits Bank/Cash directly at creation

    #                        (the bill is then marked PAID so a later

    #                        supplier payment can never double-credit cash).

    account_hint = _safe_account_hint(kw.pop("account_id", None))

    transaction_nature = str(kw.pop("transaction_nature", "") or "").strip()

    payment_method = str(kw.pop("payment_method", "") or "").strip()

    # DETERMINISTIC NATURE RECOVERY (audit finding): the fast path and a

    # minimal model reply may omit transaction_nature.  Without it the

    # engine falls to the expense default and the catalogue/stock sync is

    # skipped — the exact "purchase silently polluted the P&L" failure the

    # perpetual-inventory requirement forbids.  Derive INVENTORY from the

    # bill's OWN data (authoritative stock-tracked product link, else the

    # intent family's resale/stock wording rules — planner parity).

    if not transaction_nature:

        transaction_nature = await _derive_purchase_nature(organization_id, kw)

        if transaction_nature:

            log.info(

                "tools.create_purchase_bill.nature_recovered",

                transaction_nature=transaction_nature,

                bill_number=kw.get("bill_number"),

            )

    is_inventory = transaction_nature.upper() == "INVENTORY"



    catalogue_notes: list = []

    if is_inventory and kw.get("items"):

        # PERPETUAL INVENTORY: the purchase simultaneously creates/finds the

        # catalogue product (SKU, Inventory category, cost) and links the

        # bill line to it — the stock ledger and the COGS trigger both hang

        # off this product_id.  Failures are warnings, never blockers.

        synced_items = []

        for raw in kw["items"]:

            item = dict(raw)

            if not item.get("product_id") and item.get("description"):

                product = await inventory_service.find_or_create_catalogue_product(

                    organization_id,

                    name=str(item["description"]),

                    quantity=float(item.get("quantity") or 0),

                    unit_cost=float(item.get("unit_price") or 0),

                )

                if product and product.get("id"):

                    item["product_id"] = str(product["id"])

                    if product.get("reused"):

                        catalogue_notes.append(

                            f"Reused catalogue product '{product.get('name')}' "

                            f"({product.get('product_code')})."

                        )

                    else:

                        catalogue_notes.append(

                            f"Created catalogue product '{product.get('name')}' "

                            f"with SKU {product.get('product_code')}."

                        )

                else:

                    catalogue_notes.append(

                        f"Catalogue sync failed for '{item.get('description')}' "

                        "— the product was NOT created; the stock ledger "

                        "cannot track this line."

                    )

            synced_items.append(item)

        kw["items"] = synced_items



    # ★ INVARIANT PRE-WRITE (production 2026-10-18, session a2af6ba1): an

    # INVENTORY-classified purchase must be ABLE to debit the Inventory

    # valuation ledger.  Resolve that ledger BEFORE any bill/journal/stock

    # write, in three honest steps:

    #   1. RESOLVE (read-only) — the genuine zero-writes path;

    #   2. if the chart lacks the ledger, CREATE it as an EXPLICIT, separate

    #      operation — the result reports inventory_account_created=true

    #      (a database write is never disguised as a read);

    #   3. still nothing → fail BEFORE the bill exists: no bill, no journal,

    #      no stock movement, nothing to roll back.

    inventory_ledger = None

    inventory_account_created = False

    if is_inventory:

        from app import accounting_engine as _engine



        try:

            inventory_ledger = await _engine.resolve_inventory_account(

                organization_id

            )

        except Exception as exc:  # noqa: BLE001 — lookup failure ≠ absence

            log.warning(

                "tools.create_purchase_bill.inventory_resolve_failed",

                error=str(exc)[:200],

            )

            inventory_ledger = None

        if not inventory_ledger:

            try:

                inventory_ledger = await _engine.ensure_inventory_account(

                    organization_id

                )

                inventory_account_created = inventory_ledger is not None

            except Exception as exc:  # noqa: BLE001

                log.warning(

                    "tools.create_purchase_bill.inventory_ensure_failed",

                    error=str(exc)[:200],

                )

                inventory_ledger = None

        if not inventory_ledger:

            return ToolResult(

                tool_name="create_purchase_bill",

                success=False,

                error=(

                    "INVENTORY purchase refused: the chart of accounts has no "

                    "postable 'Inventory' ASSET ledger and one could not be "

                    "created. NOTHING was recorded — no bill, no journal, no "

                    "stock movement. Create an Inventory asset account, then "

                    "repeat the purchase."

                ),

            )



    data = await purchase_service.create_purchase_bill(organization_id=organization_id, **kw)

    # C3+C4: Atomic document + journal creation

    amount = float(data.get("total", 0))

    if catalogue_notes:

        data["catalogue_notes"] = catalogue_notes

    if inventory_account_created:

        # HONEST WRITE DISCLOSURE: the Inventory ledger creation above WAS a

        # database write — it is reported, never disguised as a read.

        data["inventory_account_created"] = True

    if amount > 0:

        journal_result = await auto_journal(

            organization_id=organization_id,

            document_type="purchase_bill",

            document=data,

            amount=amount,

            transaction_date=data.get("bill_date", ""),

            description=f"Purchase bill {data.get('bill_number', data.get('id', ''))}",

            supplier_id=kw.get("supplier_id"),

            account_hint_id=account_hint,

            transaction_nature=transaction_nature or None,

            payment_method=payment_method or None,

        )

        data.update(journal_result)

        # Auto-validate + auto-post the bill journal — same convention as

        # payment_service (receipts/payments) and create_expense: a recorded

        # bill is a real payable event; the ledger must reflect it

        # immediately instead of leaving a DRAFT journal that verification

        # would still call "balanced → VERIFIED". Deterministic backend

        # calls — never an LLM decision.

        # prepare_journal returns {"entry": <row>, "lines": [...]} — DB contract first.

        prepared = journal_result.get("journal_entry") or {}

        entry = prepared.get("entry") or {}

        if entry.get("id") and is_inventory:

            # ★ POSTING INVARIANT (fail closed) — verify the ACTUAL debit line

            # of the PREPARED entry.  An INVENTORY-classified purchase may

            # NEVER become a posted operating expense because metadata was

            # lost somewhere upstream: if the debit is not the Inventory

            # valuation ledger, this entry is NOT posted, ever.

            prepared_lines = prepared.get("lines") or []

            debit_ids = {

                str(line.get("account_id"))

                for line in prepared_lines

                if float(line.get("debit") or 0) > 0

            }

            expected = str(inventory_ledger.get("id")) if inventory_ledger else ""

            if not prepared_lines or expected not in debit_ids:

                # Cleanup ONLY where supported: a DRAFT entry may be deleted

                # (the DB guard protects POSTED/reversed entries only).  A

                # cleanup failure is reported honestly — never swallowed.

                cleanup = "not attempted"

                try:

                    from app.database import delete_one as _delete_one



                    await _delete_one(

                        "journal_entries",

                        row_id=uuid.UUID(str(entry["id"])),

                        organization_id=organization_id,

                    )

                    cleanup = "draft deleted"

                except Exception as cleanup_exc:  # noqa: BLE001

                    cleanup = f"draft DELETE FAILED: {str(cleanup_exc)[:160]}"

                    log.warning(

                        "tools.create_purchase_bill.invariant_draft_cleanup_failed",

                        entry_id=str(entry.get("id")),

                        error=str(cleanup_exc)[:200],

                    )

                log.warning(

                    "tools.create_purchase_bill.posting_invariant_refused",

                    entry_id=str(entry.get("id")),

                    expected_inventory_account=expected,

                    prepared_debit_accounts=sorted(debit_ids),

                    cleanup=cleanup,

                )

                return ToolResult(

                    tool_name="create_purchase_bill",

                    success=False,

                    error=(

                        "POSTING INVARIANT REFUSED: the journal for this "

                        "INVENTORY purchase would debit "

                        f"{sorted(debit_ids) or 'no debit line'} instead of the "

                        f"Inventory valuation ledger {expected or '(unresolved)'}"

                        f". The entry was NOT posted ({cleanup}). The bill "

                        "record exists but is NOT journalised or verified — "

                        "do not treat this transaction as recorded; report it "

                        "for reconciliation."

                    ),

                )

        if entry.get("id"):

            try:

                entry_id = uuid.UUID(entry["id"])

                await accounting_service.validate_journal(entry_id=entry_id)

                await accounting_service.post_journal(entry_id=entry_id)

                data["journal_posted"] = True

            except Exception as exc:  # noqa: BLE001 — never fake success

                log.warning(

                    "tools.create_purchase_bill.post_journal_failed",

                    entry_id=str(entry.get("id")),

                    error=str(exc)[:300],

                )

                data["journal_posted"] = False

                data["journal_warning"] = (

                    f"Journal prepared but posting failed: {exc}"

                )



        if data.get("journal_posted"):

            # CASH settlement: the journal credited Bank/Cash directly —

            # mark the bill settled so a later supplier payment cannot

            # credit cash a second time (double-payment hazard).

            if journal_result.get("settlement") == "CASH":

                try:

                    await purchase_service.mark_bill_paid(

                        organization_id,

                        bill_id=uuid.UUID(str(data["id"])),

                        amount=amount,

                    )

                    data["bill_marked_paid"] = True

                except Exception as exc:  # noqa: BLE001 — surface, don't fail

                    log.warning(

                        "tools.create_purchase_bill.mark_paid_failed",

                        bill_id=str(data.get("id")),

                        error=str(exc)[:300],

                    )

                    data["journal_warning"] = (

                        "The cash journal posted but the bill could not be "

                        f"marked paid: {exc}. Record NO second payment for "

                        "this bill or cash will be credited twice."

                    )



            # PERPETUAL INVENTORY: record the RECEIPT movements with EXACTLY

            # the quantities/costs on the persisted bill lines.  Only after a

            # posted journal — an unposted journal never moved value into

            # Inventory, so the quantity ledger must not move either.

            if is_inventory:

                stock_warnings: list = []

                received: list = []

                lines = data.get("items") or kw.get("items") or []

                for line in lines:

                    pid = line.get("product_id")

                    if not pid:

                        stock_warnings.append(

                            f"Line '{line.get('description')}' has no linked "

                            "catalogue product — its quantity was NOT added "

                            "to the stock ledger."

                        )

                        continue

                    try:

                        qty = float(line.get("quantity") or 0)

                        gross = qty * float(line.get("unit_price") or 0)

                        discount = float(line.get("discount_amount") or 0)

                        unit_cost = (gross - discount) / qty if qty else 0.0

                        movement = await inventory_service.receive_stock(

                            organization_id,

                            product_id=uuid.UUID(str(pid)),

                            quantity=qty,

                            unit_cost=round(unit_cost, 4),

                            source_type="purchase_bill",

                            source_id=uuid.UUID(str(data["id"])),

                            movement_date=data.get("bill_date"),

                            description=line.get("description"),

                        )

                        received.append({

                            "product_id": str(pid),

                            "quantity": qty,

                            "unit_cost": round(unit_cost, 4),

                            "movement_id": str(movement.get("id")),

                        })

                    except Exception as exc:  # noqa: BLE001 — never fatal

                        stock_warnings.append(

                            f"Stock receipt failed for line "

                            f"'{line.get('description')}': {exc}"

                        )

                if received:

                    data["stock_received"] = received

                if stock_warnings:

                    data["stock_warning"] = " ".join(stock_warnings)

    return ToolResult(tool_name="create_purchase_bill", success=True, data=data)



async def _get_purchase_bill(organization_id: uuid.UUID, **kw) -> ToolResult:

    # REFERENCE-SHAPED ID (2026-10-19, same class as get_invoice): a

    # non-uuid bill_id ("PUR-000013") resolves READ-ONLY by number instead

    # of dying inside uuid coercion.

    bill_id = kw.get("bill_id")

    if bill_id:

        try:

            uuid.UUID(str(bill_id))

        except (ValueError, TypeError):

            from app.database import fetch_many as _fm



            rows = await _fm(

                "purchase_bills",

                filters={"organization_id": str(organization_id),

                         "bill_number": str(bill_id).strip()},

                limit=1,

            ) or []

            if not rows:

                return ToolResult(

                    tool_name="get_purchase_bill",

                    success=False,

                    error=(

                        f"No purchase bill numbered {str(bill_id)!r} exists "

                        "in your books."

                    ),

                )

            bill_id = str(rows[0]["id"])

    data = await purchase_service.get_purchase_bill(

        organization_id, bill_id=uuid.UUID(str(bill_id))

    )

    return ToolResult(tool_name="get_purchase_bill", success=True, data=data)



# ===================================================================

# EXPENSE TOOLS

# ===================================================================



async def _create_expense(organization_id: uuid.UUID, **kw) -> ToolResult:

    # account_id is a JOURNAL hint (validated by the accounting engine),

    # not an expense column — pop it before the service call.

    account_hint = _safe_account_hint(kw.pop("account_id", None))

    data = await expense_service.create_expense(organization_id=organization_id, **kw)

    # C3+C4: Atomic document + journal creation

    amount = float(data.get("total", 0) or data.get("subtotal", 0))

    if amount > 0:

        journal_result = await auto_journal(

            organization_id=organization_id,

            document_type="expense",

            document=data,

            amount=amount,

            transaction_date=data.get("expense_date", ""),

            description=data.get("description", f"Expense {data.get('id', '')}"),

            supplier_id=kw.get("supplier_id"),

            account_hint_id=account_hint,

        )

        data.update(journal_result)

        # Auto-validate + auto-post the expense journal — the SAME

        # convention payment_service already implements for receipts and

        # payments: a confirmed expense is a final financial event, so

        # the ledger must reflect it immediately.  Without this the

        # journal stayed DRAFT while the session claimed VERIFIED.

        # Deterministic backend calls — never an LLM decision.

        # prepare_journal returns {"entry": <row>, "lines": [...]} —

        # the entry row is nested under "entry" (mirrors payment_service).

        prepared = journal_result.get("journal_entry") or {}

        entry = prepared.get("entry") or {}

        if entry.get("id"):

            try:

                entry_id = uuid.UUID(entry["id"])

                await accounting_service.validate_journal(entry_id=entry_id)

                await accounting_service.post_journal(entry_id=entry_id)

                data["journal_posted"] = True

            except Exception as exc:  # noqa: BLE001 — posting failure must

                # not fake success: surface it as a warning; verification

                # will re-read the actual status from the database.

                log.warning(

                    "tools.create_expense.post_journal_failed",

                    entry_id=str(entry.get("id")),

                    error=str(exc)[:300],

                )

                data["journal_posted"] = False

                data["journal_warning"] = (

                    f"Journal prepared but posting failed: {exc}"

                )

        else:

            log.warning(

                "tools.create_expense.journal_entry_missing",

                keys=list(journal_result.keys()),

            )

    return ToolResult(tool_name="create_expense", success=True, data=data)



async def _classify_expense(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await expense_service.classify_expense(

        description=kw.get("description", ""),

        amount=kw.get("amount", 0),

        organization_id=organization_id,

    )

    return ToolResult(tool_name="classify_expense", success=True, data=data)



# ===================================================================

# PAYMENT TOOLS

# ===================================================================



async def _record_customer_receipt(organization_id: uuid.UUID, **kw) -> ToolResult:

    # Wire invoice_id / bill_id through if present

    invoice_id = kw.pop("invoice_id", None)

    if invoice_id:

        kw["invoice_id"] = uuid.UUID(str(invoice_id))

    if "customer_id" in kw and isinstance(kw["customer_id"], str):
        kw["customer_id"] = uuid.UUID(kw["customer_id"])
    elif "customer_id" not in kw and kw.get("customer_name"):
        cname = str(kw.pop("customer_name")).strip()
        found = await customer_service.search(organization_id, query=cname, limit=1)
        if found:
            kw["customer_id"] = uuid.UUID(str(found[0]["id"]))
        else:
            created = await customer_service.create(organization_id, name=cname)
            kw["customer_id"] = uuid.UUID(str(created["id"]))
    if "payment_mode" in kw and "payment_method" not in kw:
        kw["payment_method"] = kw.pop("payment_mode")

    data = await payment_service.record_customer_receipt(organization_id=organization_id, **kw)

    return ToolResult(tool_name="record_customer_receipt", success=True, data=data)



async def _record_supplier_payment(organization_id: uuid.UUID, **kw) -> ToolResult:

    bill_id = kw.pop("bill_id", None)

    if bill_id:

        kw["bill_id"] = uuid.UUID(str(bill_id))

    if "supplier_id" in kw and isinstance(kw["supplier_id"], str):
        kw["supplier_id"] = uuid.UUID(kw["supplier_id"])
    elif "supplier_id" not in kw and kw.get("supplier_name"):
        sname = str(kw.pop("supplier_name")).strip()
        found = await supplier_service.search(organization_id, query=sname, limit=1)
        if found:
            kw["supplier_id"] = uuid.UUID(str(found[0]["id"]))
        else:
            created = await supplier_service.create(organization_id, name=sname)
            kw["supplier_id"] = uuid.UUID(str(created["id"]))
    if "payment_mode" in kw and "payment_method" not in kw:
        kw["payment_method"] = kw.pop("payment_mode")

    data = await payment_service.record_supplier_payment(organization_id=organization_id, **kw)

    return ToolResult(tool_name="record_supplier_payment", success=True, data=data)



# ===================================================================

# BANK TOOLS

# ===================================================================



async def _list_bank_accounts(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await bank_service.list_bank_accounts(organization_id, is_active=kw.get("is_active"))

    return ToolResult(tool_name="list_bank_accounts", success=True, data=data)



async def _create_bank_account(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await bank_service.create_bank_account(organization_id=organization_id, **kw)

    return ToolResult(tool_name="create_bank_account", success=True, data=data)



async def _record_bank_transfer(organization_id: uuid.UUID, **kw) -> ToolResult:

    # Resolve bank account UUIDs from names if needed

    src = kw.get("source_bank_account_id")

    dst = kw.get("destination_bank_account_id")

    if src and not _is_uuid(src):

        resolved = await bank_service.resolve_bank_account(organization_id, name=src)

        if not resolved:

            return ToolResult(tool_name="record_bank_transfer", success=False, error=f"Cannot resolve source bank account: {src}")

        kw["source_bank_account_id"] = resolved["id"]

    if dst and not _is_uuid(dst):

        resolved = await bank_service.resolve_bank_account(organization_id, name=dst)

        if not resolved:

            return ToolResult(tool_name="record_bank_transfer", success=False, error=f"Cannot resolve destination bank account: {dst}")

        kw["destination_bank_account_id"] = resolved["id"]

    data = await payment_service.record_bank_transfer(organization_id=organization_id, **kw)

    return ToolResult(tool_name="record_bank_transfer", success=True, data=data)





def _is_uuid(val) -> bool:

    """Check if a string is a valid UUID."""

    try:

        uuid.UUID(str(val))

        return True

    except (ValueError, AttributeError):

        return False



# ===================================================================

# JOURNAL TOOLS

# ===================================================================



async def _prepare_journal(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await accounting_service.prepare_journal(organization_id=organization_id, **kw)

    return ToolResult(tool_name="prepare_journal", success=True, data=data)



async def _validate_journal(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await accounting_service.validate_journal(entry_id=uuid.UUID(kw["entry_id"]))

    return ToolResult(tool_name="validate_journal", success=True, data=data)



async def _post_journal(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await accounting_service.post_journal(entry_id=uuid.UUID(kw["entry_id"]))

    return ToolResult(tool_name="post_journal", success=True, data=data)



async def _reverse_journal(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await accounting_service.reverse_journal(entry_id=uuid.UUID(kw["entry_id"]), reason=kw.get("reason"))

    return ToolResult(tool_name="reverse_journal", success=True, data=data)



# ===================================================================

# REPORTING TOOLS

# ===================================================================



async def _get_general_ledger(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await reporting_service.get_general_ledger(organization_id, **kw)

    return ToolResult(tool_name="get_general_ledger", success=True, data=data)



async def _get_trial_balance(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await reporting_service.get_trial_balance(organization_id)

    return ToolResult(tool_name="get_trial_balance", success=True, data=data)



async def _get_profit_loss(organization_id: uuid.UUID, **kw) -> ToolResult:

    # Multi-step statement from the accounting hierarchy: Operating Revenue →

    # Cost of Sales → Gross Profit → Operating Expenses (Administrative /

    # Selling & Marketing / Distribution / Other Operating) → Operating Profit

    # → Other Income → Finance Costs → Tax Expense → Net Profit.

    # ``rows`` remains the flat per-account list, so every existing consumer

    # keeps working unchanged.

    data = await reporting_service.get_profit_loss_statement(organization_id)

    return ToolResult(tool_name="get_profit_loss", success=True, data=data)



async def _get_balance_sheet(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await reporting_service.get_balance_sheet(organization_id)

    return ToolResult(tool_name="get_balance_sheet", success=True, data=data)



async def _get_cash_flow(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await reporting_service.get_cash_flow(organization_id)

    return ToolResult(tool_name="get_cash_flow", success=True, data=data)



async def _list_expenses(organization_id: uuid.UUID, **kw) -> ToolResult:

    """List recorded expenses (read-only).  Supports optional

    ``from_date``/``to_date`` (ISO) — used by the deterministic

    expense-details fast path ("details of this month's expenses")."""

    from app.repositories import expense_repository



    rows = await expense_repository.list_expenses(organization_id, limit=100)

    from_date = kw.get("from_date")

    to_date = kw.get("to_date")

    if from_date:

        rows = [r for r in rows if (r.get("expense_date") or "") >= str(from_date)]

    if to_date:

        rows = [r for r in rows if (r.get("expense_date") or "") <= str(to_date)]

    return ToolResult(tool_name="list_expenses", success=True, data=rows)



async def _generate_report(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await reporting_service.generate_report(organization_id, **kw)

    return ToolResult(tool_name="generate_report", success=True, data=data)



# ===================================================================

# PROJECT TOOLS

# ===================================================================



async def _create_project(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await project_service.create(organization_id, **kw)

    return ToolResult(tool_name="create_project", success=True, data=data)



async def _get_project(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await project_service.get(organization_id, project_id=uuid.UUID(kw["project_id"]))

    return ToolResult(tool_name="get_project", success=True, data=data)



async def _get_project_profitability(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await project_service.get_profitability(organization_id, project_id=uuid.UUID(kw["project_id"]))

    return ToolResult(tool_name="get_project_profitability", success=True, data=data)



# ===================================================================

# QUOTATION TOOLS

# ===================================================================



async def _create_quotation(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await quotation_service.create_quotation(organization_id=organization_id, **kw)

    return ToolResult(tool_name="create_quotation", success=True, data=data)



async def _convert_quotation(organization_id: uuid.UUID, **kw) -> ToolResult:

    # Quotation → Invoice cross-module lifecycle: creates the invoice with

    # quotation source linkage, posts the receivable journal via the

    # deterministic accounting engine, then marks the quotation CONVERTED.

    if kw.get("quotation_id") and not isinstance(kw["quotation_id"], uuid.UUID):

        kw["quotation_id"] = uuid.UUID(str(kw["quotation_id"]))

    data = await quotation_service.convert_quotation(organization_id=organization_id, **kw)

    return ToolResult(tool_name="convert_quotation", success=True, data=data)



# ===================================================================

# CREDIT NOTE TOOLS

# ===================================================================



async def _normalize_return_args(

    organization_id: uuid.UUID, kw: Dict[str, Any], *, kind: str

) -> Dict[str, Any]:

    """FAITHFUL CARRY + SCHEMA GATE for the two return-document tools.



    (2026-10-19, stage-0 lanes: the executed credit note lost its

    ``invoice_id`` and line prices — total 0, no reversal journal; the

    debit note failed with an unresolvable supplier.)



    * ``invoice_number`` / ``bill_number`` are RESOLVED into the uuid the

      service requires (a reference the user typed must survive to the row);

    * missing line prices are DERIVED arithmetically from the stated total

      and quantity (the derivable-half doctrine — arithmetic, never a guess);

    * a document that would carry a ZERO total is REFUSED before any write,

      with the exact value the user must state — never a hollow document

      that claims success while reversing nothing.



    Consumed helper keys are stripped so they never reach the repository.

    """

    kw = dict(kw or {})



    def _uuid_ok(value: Any) -> bool:

        try:

            uuid.UUID(str(value))

            return True

        except (ValueError, TypeError):

            return False



    # REFERENCE-SHAPED ID FIX (live 2026-10-19): models sometimes write the

    # document NUMBER into the uuid field ("INV-000014" as invoice_id) —

    # the service's uuid coercion then died with "badly formed hexadecimal

    # UUID string" AFTER the validator already approved the call.  A

    # non-uuid value in *_id is resolved AS the number instead.

    # Cross-kind hygiene: the other document's reference never rides along.

    num = ""

    if kind == "credit_note":

        kw.pop("bill_id", None)

        kw.pop("bill_number", None)

        num = str(kw.pop("invoice_number", "") or "").strip()

        raw_inv = kw.pop("invoice_id", None)

        if raw_inv and not _uuid_ok(raw_inv):

            num = num or str(raw_inv).strip()

            raw_inv = None

        if raw_inv:

            kw["invoice_id"] = str(raw_inv)

        if not kw.get("invoice_id") and num:

            from app.database import fetch_many as _fm



            rows = await _fm(

                "invoices",

                filters={"organization_id": str(organization_id),

                         "invoice_number": num},

                limit=1,

            ) or []

            if rows:

                kw["invoice_id"] = str(rows[0]["id"])

    else:

        kw.pop("invoice_id", None)

        kw.pop("invoice_number", None)

        bill_no = str(kw.pop("bill_number", "") or "").strip()

        raw_bill = kw.pop("bill_id", None)

        if raw_bill and not _uuid_ok(raw_bill):

            bill_no = bill_no or str(raw_bill).strip()

            raw_bill = None

        if raw_bill:

            kw["bill_id"] = str(raw_bill)

        if not kw.get("bill_id") and bill_no:

            from app.database import fetch_many as _fm



            rows = await _fm(

                "purchase_bills",

                filters={"organization_id": str(organization_id),

                         "bill_number": bill_no},

                limit=1,

            ) or []

            if rows:

                kw["bill_id"] = str(rows[0]["id"])



    amount = kw.pop("amount", None)

    try:

        amount = float(amount) if amount is not None else None

    except (TypeError, ValueError):

        amount = None

    qty_raw = kw.pop("quantity", None)

    description = (

        kw.pop("item_description", None) or kw.pop("description", None)

    )

    items = kw.get("items") or []

    if not items and description:

        qty = float(qty_raw) if qty_raw not in (None, "", 0) else 1.0

        unit_price = (

            round(amount / qty, 2)

            if amount and qty and amount > 0

            else None

        )

        items = [{"description": str(description).strip(),

                  "quantity": qty, "unit_price": unit_price}]

    priced = []

    for raw_line in items or ():

        line = dict(raw_line)

        if (line.get("unit_price") in (None, "", 0)

                and amount and amount > 0):

            line_qty = float(line.get("quantity") or 1) or 1.0

            line["unit_price"] = round(amount / line_qty, 2)

        # LINE PARITY (live 2026-10-19, CRN-000003): the credit-note /

        # purchase-return repositories compute the document total from

        # ``line_total`` — a line carrying only quantity × unit_price

        # stored a ZERO-total document while the validator approved the

        # call.  The invoice service has this parity law; the return lanes

        # never did.  Compute it here so BOTH tools inherit it.

        if line.get("line_total") in (None, ""):

            try:

                line_qty = float(line.get("quantity") or 0)

                line_unit = float(line.get("unit_price") or 0)

            except (TypeError, ValueError):

                line_qty, line_unit = 0.0, 0.0

            if line_qty > 0 and line_unit > 0:

                line["line_total"] = round(line_qty * line_unit, 2)

        priced.append(line)

    if priced:

        kw["items"] = priced



    total = 0.0

    for line in kw.get("items") or ():

        try:

            total += float(line.get("quantity") or 0) * float(

                line.get("unit_price") or 0)

        except (TypeError, ValueError):

            continue

    if total <= 0:

        raise ValueError(

            f"This {kind.replace('_', ' ')} would record a ZERO amount — "

            "no document was created. State the amount (and quantity if "

            "more than one unit) and I will record it properly."

        )

    return kw





async def _create_credit_note(organization_id: uuid.UUID, **kw) -> ToolResult:

    kw = await _normalize_return_args(organization_id, kw, kind="credit_note")

    data = await credit_note_service.create_credit_note(organization_id=organization_id, **kw)

    # C3+C4 (mirrors create_invoice): a customer return is a real

    # receivable event — the REVERSAL journal (Dr revenue / Cr receivable)

    # is built deterministically from the document, auto-validated,

    # auto-posted, source-tied back to the note, and the note leaves DRAFT

    # so receivables/aging views reflect the credit.  Never an LLM choice.

    amount = float(data.get("total", 0))

    if amount > 0:

        journal_result = await auto_journal(

            organization_id=organization_id,

            document_type="credit_note",

            document=data,

            amount=amount,

            transaction_date=data.get("credit_note_date", ""),

            description=(

                f"Credit note {data.get('credit_note_number', data.get('id', ''))}"

            ),

            customer_id=(

                uuid.UUID(str(data["customer_id"]))

                if data.get("customer_id") else None

            ),

        )

        data.update(journal_result)

        prepared = journal_result.get("journal_entry") or {}

        entry = prepared.get("entry") or {}

        if entry.get("id"):

            try:

                entry_id = uuid.UUID(entry["id"])

                await accounting_service.validate_journal(entry_id=entry_id)

                await accounting_service.post_journal(entry_id=entry_id)

                from app.repositories import credit_note_repository as cn_repo



                await cn_repo.link_journal_to_credit_note(

                    credit_note_id=uuid.UUID(str(data["id"])),

                    journal_entry_id=entry_id,

                )

                await cn_repo.mark_issued(

                    credit_note_id=uuid.UUID(str(data["id"]))

                )

                data["journal_entry_id"] = str(entry_id)

                data["status"] = "ISSUED"

                data["journal_posted"] = True

            except Exception as exc:  # noqa: BLE001 — never fake success

                log.warning(

                    "tools.create_credit_note.post_journal_failed",

                    entry_id=str(entry.get("id")),

                    error=str(exc)[:300],

                )

                data["journal_posted"] = False

                data["journal_warning"] = (

                    f"Journal prepared but posting failed: {exc}"

                )

    return ToolResult(tool_name="create_credit_note", success=True, data=data)



# ===================================================================

# PURCHASE RETURN TOOLS

# ===================================================================



async def _create_purchase_return(organization_id: uuid.UUID, **kw) -> ToolResult:

    kw = await _normalize_return_args(

        organization_id, kw, kind="purchase_return"

    )

    data = await purchase_return_service.create_purchase_return(organization_id=organization_id, **kw)

    # C3+C4 (mirrors create_invoice / create_purchase_bill): a goods

    # return to the supplier is a real payable event — the REVERSAL journal

    # (Dr payable / Cr expense-asset) is built deterministically from the

    # document, auto-validated, auto-posted, source-tied back to the row,

    # and the return leaves DRAFT (OPEN) so payables/aging views reflect

    # it.  Never an LLM choice.

    amount = float(data.get("total", 0))

    if amount > 0:

        journal_result = await auto_journal(

            organization_id=organization_id,

            document_type="purchase_return",

            document=data,

            amount=amount,

            transaction_date=data.get("return_date", ""),

            description=(

                f"Purchase return {data.get('return_number', data.get('id', ''))}"

            ),

            supplier_id=(

                uuid.UUID(str(data["supplier_id"]))

                if data.get("supplier_id") else None

            ),

        )

        data.update(journal_result)

        prepared = journal_result.get("journal_entry") or {}

        entry = prepared.get("entry") or {}

        if entry.get("id"):

            try:

                entry_id = uuid.UUID(entry["id"])

                await accounting_service.validate_journal(entry_id=entry_id)

                await accounting_service.post_journal(entry_id=entry_id)

                from app.repositories import purchase_return_repository as pr_repo



                await pr_repo.link_journal_to_purchase_return(

                    return_id=uuid.UUID(str(data["id"])),

                    journal_entry_id=entry_id,

                )

                await pr_repo.mark_open(

                    return_id=uuid.UUID(str(data["id"]))

                )

                data["journal_entry_id"] = str(entry_id)

                data["status"] = "OPEN"

                data["journal_posted"] = True

            except Exception as exc:  # noqa: BLE001 — never fake success

                log.warning(

                    "tools.create_purchase_return.post_journal_failed",

                    entry_id=str(entry.get("id")),

                    error=str(exc)[:300],

                )

                data["journal_posted"] = False

                data["journal_warning"] = (

                    f"Journal prepared but posting failed: {exc}"

                )

    return ToolResult(tool_name="create_purchase_return", success=True, data=data)



# ===================================================================

# EXPENSE PAYMENT TOOL

# ===================================================================



async def _record_expense_payment(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await payment_service.record_supplier_payment(organization_id=organization_id, **kw)

    return ToolResult(tool_name="record_expense_payment", success=True, data=data)



# ===================================================================

# EMPLOYEE TOOLS

# ===================================================================

# Quick-entry module: ONLY full_name + date_of_joining + basic_salary are

# mandatory.  Allowances are NEVER parsed in Python — the model structures

# the user's natural-language sentence into allowances=[{description,

# amount, frequency, allowance_type, effective_from}] and the service

# validates each entry and writes the rows.  Validation failures come back

# as success=False with a message written FOR THE MODEL to act on (it names

# what to ask the user).



async def _search_employee(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await employee_service.search(

        organization_id, query=kw.get("query", ""), limit=kw.get("limit", 25)

    )

    return ToolResult(tool_name="search_employee", success=True, data=data)





async def _get_employee(organization_id: uuid.UUID, **kw) -> ToolResult:

    try:

        data = await employee_service.get(

            organization_id,

            employee=kw.get("employee"),

            employee_id=kw.get("employee_id"),

        )

    except employee_service.EmployeeInputError as exc:

        return ToolResult(tool_name="get_employee", success=False, error=str(exc))

    return ToolResult(tool_name="get_employee", success=True, data=data)





async def _create_employee(organization_id: uuid.UUID, **kw) -> ToolResult:

    try:
        if "name" in kw and "full_name" not in kw:
            kw["full_name"] = kw.pop("name")
        if "employee_name" in kw and "full_name" not in kw:
            kw["full_name"] = kw.pop("employee_name")
        if "salary" in kw and "basic_salary" not in kw:
            kw["basic_salary"] = kw.pop("salary")
        if "date_of_joining" not in kw:
            from datetime import date
            kw["date_of_joining"] = date.today().isoformat()
        if "basic_salary" not in kw:
            kw["basic_salary"] = 0.0

        data = await employee_service.create(organization_id, **kw)

    except employee_service.EmployeeInputError as exc:

        return ToolResult(tool_name="create_employee", success=False, error=str(exc))

    return ToolResult(tool_name="create_employee", success=True, data=data)





async def _set_employee_allowances(organization_id: uuid.UUID, **kw) -> ToolResult:

    try:

        data = await employee_service.set_allowances(organization_id, **kw)

    except employee_service.EmployeeInputError as exc:

        return ToolResult(

            tool_name="set_employee_allowances", success=False, error=str(exc)

        )

    return ToolResult(tool_name="set_employee_allowances", success=True, data=data)





# Payroll — Phase 2 of the Employees module.  The service COMPUTES each salary

# from the records (basic + active monthly allowances − deductions) and posts

# the journal; the model only supplies what it read from the user.  A run whose

# journal failed is reported as a FAILED call (never a silent success), and the

# computation is always returned so the agent can explain the real state.

async def _run_payroll(organization_id: uuid.UUID, **kw) -> ToolResult:

    try:

        data = await payroll_service.run_payroll(organization_id, **kw)

    except payroll_service.PayrollInputError as exc:

        return ToolResult(tool_name="run_payroll", success=False, error=str(exc))

    if not data.get("journal_posted"):

        return ToolResult(

            tool_name="run_payroll",

            success=False,

            error=(

                "The payroll journal could not be posted: "

                f"{data.get('journal_error')} — report this to the user; the "

                "run is NOT recorded."

            ),

            data=data,

        )

    return ToolResult(tool_name="run_payroll", success=True, data=data)





async def _pay_employee_salary(organization_id: uuid.UUID, **kw) -> ToolResult:

    try:

        data = await payroll_service.pay_employee_salary(organization_id, **kw)

    except payroll_service.PayrollInputError as exc:

        return ToolResult(

            tool_name="pay_employee_salary", success=False, error=str(exc)

        )

    if not data.get("journal_posted"):

        return ToolResult(

            tool_name="pay_employee_salary",

            success=False,

            error=(

                "The salary-payment journal could not be posted: "

                f"{data.get('journal_error')} — report this to the user; the "

                "payment is NOT recorded."

            ),

            data=data,

        )

    return ToolResult(tool_name="pay_employee_salary", success=True, data=data)



# ===================================================================

# REGISTER ALL TOOLS

# ===================================================================



# Customer

register("search_customer", handler=_search_customer, read_only=True, description="Search customers by name or code")

register("get_customer", handler=_get_customer, read_only=True, description="Get customer details")

register("create_customer", handler=_create_customer, read_only=False, contract=contract_from_callable(customer_service.create), description="Create a new customer")

register("get_customer_ledger", handler=_get_customer_ledger, read_only=True, description="Get customer ledger")



# Employee — quick-entry master data (mandatory: full_name, date_of_joining,

# basic_salary).  Allowances arrive already STRUCTURED by the model; the

# service validates each component and writes one row per part.

register("search_employee", handler=_search_employee, read_only=True, description="Search employees by name, code, department or designation")

register("get_employee", handler=_get_employee, read_only=True, description="Get one employee's full details plus allowance records")

register("create_employee", handler=_create_employee, read_only=False, contract=contract_from_callable(employee_service.create), description="Create an employee: mandatory full_name, date_of_joining, basic_salary; every other detail is optional")

register("set_employee_allowances", handler=_set_employee_allowances, read_only=False, contract=contract_from_callable(employee_service.set_allowances), description="Record an employee's allowances: structure the user's natural-language sentence into allowances=[{description, amount, frequency(monthly|one-time|annual), allowance_type, effective_from}] and pass raw_text; Python validates each entry and writes the rows (rejections name what to ask the user)")



# Payroll — the model decides WHICH tool and the settlement treatment; the

# service computes every amount from the employee records and posts the journal.

register("run_payroll", handler=_run_payroll, read_only=False, contract=contract_from_callable(payroll_service.run_payroll), description="Run payroll for every active employee: computes each one's salary (basic + monthly allowances − deductions recorded on the employee) and posts ONE journal — Dr Salaries / Cr Accrued Salaries, or Cr bank when payment_method=PAID. Pass payment_method=PAID when the user says the salaries are/were actually paid, ACCRUED when they are owed/accrued (default). One-time/annual components are excluded and reported back")

register("pay_employee_salary", handler=_pay_employee_salary, read_only=False, contract=contract_from_callable(payroll_service.pay_employee_salary), description="Pay ONE employee's salary (settles the accrual): resolves the employee by code/name, debits Accrued Salaries (or the Salaries expense account when no accrual ledger exists) and credits bank/cash. Pass the amount only when the user stated a figure — otherwise it is computed from the employee's records")



# Supplier

register("search_supplier", handler=_search_supplier, read_only=True, description="Search suppliers by name or code")

register("get_supplier", handler=_get_supplier, read_only=True, description="Get supplier details")

register("create_supplier", handler=_create_supplier, read_only=False, contract=contract_from_callable(supplier_service.create), description="Create a new supplier")

register("get_supplier_ledger", handler=_get_supplier_ledger, read_only=True, description="Get supplier ledger")



# Account

register("search_account", handler=_search_account, read_only=True, description="Search chart of accounts")

register("get_chart_of_accounts", handler=_get_chart_of_accounts, read_only=True, description="Get full chart of accounts")

register("create_account", handler=_create_account, read_only=False, description="Create a new account. Optionally pass parent_account_name to file it under a section heading (e.g. 'Operating Expenses', 'Current Assets'); an existing heading of the same account type is reused, and a missing one is created automatically as a grouping account — the account never fails on a sparse chart")



# Invoice

register("create_invoice", handler=_create_invoice, read_only=False, contract=contract_from_callable(invoice_service.create_invoice), description="Create a sales invoice with line items: pass items=[{description, quantity, unit_price, ...}] — lines are validated and their totals computed by the service (never invent amounts)")

register("get_invoice", handler=_get_invoice, read_only=True, description="Get invoice details — pass invoice_id (uuid) OR invoice_number (the human number, e.g. INV-000011; exact match against this organization's books)")



# Purchase

register("create_purchase_bill", handler=_create_purchase_bill, read_only=False,

         contract=contract_from_callable(purchase_service.create_purchase_bill,

                                         extra_arguments=("account_id", "transaction_nature", "payment_method")),

         description="Create a purchase bill (supplier invoice). For INVENTORY purchases (resale stock) pass transaction_nature='INVENTORY' so the debit lands on the Inventory asset account, the product is created/linked in the catalogue, and the stock ledger records the receipt; pass payment_method='CASH' when the goods were paid for immediately (Cash/Bank is credited and the bill is marked paid)")

register("get_purchase_bill", handler=_get_purchase_bill, read_only=True, description="Get purchase bill details")



# Expense

register("create_expense", handler=_create_expense, read_only=False, contract=contract_from_callable(expense_service.create_expense, extra_arguments=("account_id",)), description="Record an expense")

register("classify_expense", handler=_classify_expense, read_only=True, description="Classify expense category")



# Payment

register("record_customer_receipt", handler=_record_customer_receipt, read_only=False, contract=contract_from_callable(payment_service.record_customer_receipt), description="Record customer receipt with journal and allocation")

register("record_supplier_payment", handler=_record_supplier_payment, read_only=False, contract=contract_from_callable(payment_service.record_supplier_payment), description="Record supplier payment with journal and allocation")



# Bank

register("list_bank_accounts", handler=_list_bank_accounts, read_only=True, description="List bank accounts")

register("create_bank_account", handler=_create_bank_account, read_only=False, description="Create a new bank account with linked GL account")

register("record_bank_transfer", handler=_record_bank_transfer, read_only=False, description="Record bank-to-bank transfer with journal")



# Journal

register("prepare_journal", handler=_prepare_journal, read_only=False, contract=contract_from_callable(accounting_service.prepare_journal), description="Prepare a draft journal entry")

register("validate_journal", handler=_validate_journal, read_only=False, contract=contract_from_callable(accounting_service.validate_journal), description="Validate a journal entry")

register("post_journal", handler=_post_journal, read_only=False, contract=contract_from_callable(accounting_service.post_journal), description="Post a validated journal entry")

register("reverse_journal", handler=_reverse_journal, read_only=False, description="Reverse a posted journal entry")



# Sales — trusted cash-sale domain operation (deterministic journal)

# NOTE: record_cash_sale deliberately has NO argument contract.  It is a

# trusted domain operation whose signature (app/accounting_engine.record_cash_sale)

# carries BACKEND-RESOLVED parameters (cash_account_id, revenue_account_id,

# transaction_date, description) that the model must never supply.  Deriving a

# contract from that signature would (a) mark those resolved fields REQUIRED and

# reject the model's natural {"total": ...} call, and (b) add a contract line to

# the primed reasoning prompt, over its measured latency budget.  Validation is

# intentionally skipped ("cannot judge" -> never reject); the handler reads the

# optional items=[{product_id, quantity}] straight from **kw, and the perpetual

# inventory COGS trigger hangs off it (see _record_cash_sale).

register("record_cash_sale", handler=_record_cash_sale, read_only=False,

         description="Record an immediate cash sale: resolves the Cash and Revenue accounts, prepares, validates and posts the journal via the accounting engine. For sales of stock-tracked goods pass items=[{product_id, quantity}] so the accounting engine also posts the Cost-of-Sales entry (Dr Cost of Sales / Cr Inventory) and relieves the stock ledger at weighted-average cost")



# CASH PURCHASE — a settled-acquisition journal, NEVER a bill/payable.  The

# handler resolves (or CREATES) the Cash/Bank ledger, debits Inventory/asset/

# expense, auto-validates + auto-posts, and for INVENTORY goods syncs the

# catalogue and receives stock units (cash purchases track units too).

register("record_cash_purchase", handler=_record_cash_purchase, read_only=False,

         description="Record an immediate CASH purchase (settled now — NOT a supplier bill, no payable is created): Dr Inventory (resale stock) / fixed-asset / expense and Cr Cash-or-Bank, resolving the debit and cash ledgers deterministically (creating a Cash account when the chart lacks one). For stock-resale goods pass transaction_nature='INVENTORY' and items=[{description, quantity, unit_price}] so the product is created/linked in the catalogue and the stock ledger receives the units")



# =====================================================================

# LOANS & FINANCING — controlled accounting objects (schedule = truth)

# =====================================================================



async def _record_loan(organization_id: uuid.UUID, **kw) -> ToolResult:

    """Record a borrowing (direction=BORROWED) or lending (GIVEN).



    The service gathers terms, builds the amortization schedule, creates a

    DEDICATED ledger named with the unique narration, posts the initial

    journal (proceeds/advance) and auto-posts it — deterministic backend

    calls, never an LLM decision.

    """

    try:

        data = await loan_service.create_loan(

            organization_id,

            direction=kw.get("direction"),

            narration=kw.get("narration"),

            counterparty=kw.get("counterparty"),

            principal=kw.get("principal"),

            loan_date=kw.get("loan_date") or date.today().isoformat(),

            first_payment_date=kw.get("first_payment_date"),

            tenure_months=kw.get("tenure_months"),

            frequency=kw.get("frequency") or "MONTHLY",

            interest_rate=kw.get("interest_rate") or 0.0,

            interest_method=kw.get("interest_method") or "REDUCING",

            custom_interval_months=kw.get("custom_interval_months"),

            grace_months=kw.get("grace_months") or 0,

            balloon_amount=kw.get("balloon_amount") or 0.0,

            fees_charges=kw.get("fees_charges") or 0.0,

            purpose=kw.get("purpose"),

            currency_code=kw.get("currency_code") or "PKR",

            cash_account_id=_safe_account_hint(kw.pop("cash_account_id", None)),

            party_id=_safe_account_hint(kw.pop("party_id", None)),

        )

    except ValueError as exc:

        return ToolResult(tool_name="record_loan", success=False, error=str(exc))

    return ToolResult(tool_name="record_loan", success=True, data=data)





async def _record_loan_repayment(organization_id: uuid.UUID, **kw) -> ToolResult:

    try:

        data = await loan_service.record_installment_payment(

            organization_id,

            loan_id=uuid.UUID(str(kw["loan_id"])),

            installment_no=int(kw["installment_no"]),

            amount_paid=kw.get("amount_paid"),

            paid_date=kw.get("paid_date"),

        )

    except ValueError as exc:

        return ToolResult(tool_name="record_loan_repayment", success=False, error=str(exc))

    return ToolResult(tool_name="record_loan_repayment", success=True, data=data)





async def _list_loans(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await loan_service.list_loans(

        organization_id, direction=kw.get("direction"), status=kw.get("status")

    )

    return ToolResult(tool_name="list_loans", success=True, data={"loans": data})





async def _get_loan_schedule(organization_id: uuid.UUID, **kw) -> ToolResult:

    rows = await loan_service.get_schedule(

        organization_id, loan_id=uuid.UUID(str(kw["loan_id"]))

    )

    return ToolResult(tool_name="get_loan_schedule", success=True,

                      data={"schedule": rows})





async def _check_due_loan_installments(organization_id: uuid.UUID, **kw) -> ToolResult:

    """The scheduled-event sweep: installments due/overdue as of a date.

    The agent proposes the segregated journal (principal -> loan ledger,

    interest -> expense/income) for each — posting still obeys the

    confirmation gate (a due date does NOT mean cash was paid)."""

    rows = await loan_service.due_installments(

        organization_id, as_of=kw.get("as_of")

    )

    return ToolResult(tool_name="check_due_loan_installments", success=True,

                      data={"due_installments": rows})







# Loans — controlled accounting objects

register("record_loan", handler=_record_loan, read_only=False,

         contract=contract_from_callable(

             loan_service.create_loan,

             extra_arguments=("cash_account_id", "party_id")),

         description="Record a BORROWING (direction='BORROWED': Dr Bank / Cr Loan ledger) or a LENDING (direction='GIVEN': Dr Loan receivable / Cr Bank). Requires a UNIQUE descriptive narration (e.g. 'Loan - HBL - Vehicle Financing - 2026') that identifies the facility in every journal. Collect the terms up front: counterparty, purpose, principal, loan_date, first_payment_date, tenure_months, frequency (MONTHLY/QUARTERLY/SEMI_ANNUAL/ANNUALLY/CUSTOM), interest_rate (annual %), interest_method (REDUCING or FLAT), optional grace_months/balloon_amount/fees_charges. The service builds the full amortization schedule, creates a dedicated ledger under Long-Term Loans (or Loans Receivable) and posts the initial journal automatically")

register("record_loan_repayment", handler=_record_loan_repayment, read_only=False,

         contract=contract_from_callable(loan_service.record_installment_payment),

         description="Settle one loan installment BY NUMBER. The principal/interest split comes from the schedule (never guessed): BORROWED posts Dr Loan ledger (principal) + Dr Interest Expense / Cr Bank; GIVEN posts Dr Bank / Cr Loan ledger (principal) + Cr Interest Income. Only interest reaches the P&L")

register("list_loans", handler=_list_loans, read_only=True,

         contract=contract_from_callable(loan_service.list_loans),

         description="List loans with schedule-derived position: outstanding principal, current portion (principal due within 12 months), non-current portion, next due date, overdue count. direction='BORROWED' or 'GIVEN' filters")

register("get_loan_schedule", handler=_get_loan_schedule, read_only=True,

         contract=contract_from_callable(loan_service.get_schedule),

         description="Full amortization schedule of one loan: installment no, due date, opening principal, principal, interest, total, closing principal, live status")

register("check_due_loan_installments", handler=_check_due_loan_installments, read_only=True,

         contract=contract_from_callable(loan_service.due_installments),

         description="Scheduled-event sweep: installments DUE or OVERDUE as of a date (default today), across all loans. Use it to propose the segregated installment journals (principal + interest) for confirmation — a due date alone never posts cash")







async def _record_loan_restructure(organization_id: uuid.UUID, **kw) -> ToolResult:

    """Re-amortize the UNPAID future schedule under new terms.  Cash already

    moved (paid/partial installments) is never touched and no journal posts —

    a restructure changes future terms, not the ledger balance."""

    try:

        data = await loan_service.restructure_loan(

            organization_id,

            loan_id=uuid.UUID(str(kw["loan_id"])),

            first_payment_date=kw["first_payment_date"],

            tenure_months=int(kw["tenure_months"]),

            frequency=kw.get("frequency") or "MONTHLY",

            interest_rate=kw.get("interest_rate") or 0.0,

            interest_method=kw.get("interest_method") or "REDUCING",

            custom_interval_months=kw.get("custom_interval_months"),

            grace_months=kw.get("grace_months") or 0,

            balloon_amount=kw.get("balloon_amount") or 0.0,

            reason=kw.get("reason"),

        )

    except ValueError as exc:

        return ToolResult(tool_name="record_loan_restructure", success=False, error=str(exc))

    return ToolResult(tool_name="record_loan_restructure", success=True, data=data)





async def _write_off_loan(organization_id: uuid.UUID, **kw) -> ToolResult:

    """Write off the real remaining principal with a segregated journal

    (forgiveness gain for borrowings, impairment loss for lendings)."""

    try:

        data = await loan_service.write_off_loan(

            organization_id,

            loan_id=uuid.UUID(str(kw["loan_id"])),

            write_off_date=kw.get("write_off_date") or date.today().isoformat(),

            reason=kw.get("reason"),

        )

    except ValueError as exc:

        return ToolResult(tool_name="write_off_loan", success=False, error=str(exc))

    return ToolResult(tool_name="write_off_loan", success=True, data=data)







register("record_loan_restructure", handler=_record_loan_restructure, read_only=False,

         contract=contract_from_callable(loan_service.restructure_loan),

         description="Restructure a loan: re-amortize the UNPAID future installments from a new first_payment_date under new tenure/frequency/rate/method terms. Paid or partial installments are never touched and NO journal posts (a restructure changes future terms, not the ledger balance); the change is recorded in the loan's restructure audit trail with old and new terms plus the reason")

register("write_off_loan", handler=_write_off_loan, read_only=False,

         contract=contract_from_callable(loan_service.write_off_loan),

         description="Write off a loan's real remaining principal with a proper segregated journal: a BORROWED loan posts Dr Loan ledger / Cr Loan Forgiveness Gain (Other Income); a GIVEN loan posts Dr Loan Impairment Loss (Other Expenses) / Cr Loan receivable. Unpaid installments are waived, status flips to WRITTEN_OFF, and every line carries the loan narration. Use only with explicit owner confirmation of the reason")





# Reporting

register("get_general_ledger", handler=_get_general_ledger, read_only=True, description="Get general ledger")

register("get_trial_balance", handler=_get_trial_balance, read_only=True, description="Get trial balance")

register("get_profit_loss", handler=_get_profit_loss, read_only=True, description="Get the multi-step profit & loss statement: Operating Revenue less Cost of Sales = Gross Profit, less Operating Expenses (Administrative / Selling & Marketing / Distribution / Other Operating) = Operating Profit, then plus Other Income, less Finance Costs and Tax Expense = Net Profit. Returns rows (flat per-account) and statement (sections + subtotals)")

register("get_balance_sheet", handler=_get_balance_sheet, read_only=True, description="Get balance sheet")

register("get_cash_flow", handler=_get_cash_flow, read_only=True, description="Get cash flow data")

register("list_expenses", handler=_list_expenses, read_only=True, description="List recorded expenses with dates, payees and totals (supports from_date/to_date)")

register("generate_report", handler=_generate_report, read_only=True, description="Generate a custom report")



# Project

register("create_project", handler=_create_project, read_only=False, contract=contract_from_callable(project_service.create), description="Create a project")

register("get_project", handler=_get_project, read_only=True, description="Get project details")

register("get_project_profitability", handler=_get_project_profitability, read_only=True, description="Get project profitability")



# Quotation

register("create_quotation", handler=_create_quotation, read_only=False, description="Create a sales quotation")

register("convert_quotation", handler=_convert_quotation, read_only=False, contract=contract_from_callable(quotation_service.convert_quotation), description="Convert an accepted quotation into a sales invoice: creates the invoice linked to the source quotation, posts the receivable journal, and marks the quotation CONVERTED (double conversion is refused)")



# Credit Note

# Credit Note — contract mirrors the record_customer_receipt pattern: the

# signature-derived gate advertises `invoice_number->invoice_id` to the

# reasoning prompt and lets the declared alias pass validation (resolution

# itself is DECLARED_REFERENCES, plan_materialization).

register("create_credit_note", handler=_create_credit_note, read_only=False, contract=contract_from_callable(credit_note_service.create_credit_note), description="Create a credit note")



# Purchase Return

register("create_purchase_return", handler=_create_purchase_return, read_only=False, description="Create a purchase return")



# Expense Payment

register("record_expense_payment", handler=_record_expense_payment, read_only=False, description="Record payment for an expense or bill")



# ===================================================================

# PRODUCT CATALOG (item resolution — NO stock ledger exists in the DB)

# ===================================================================



async def _search_product(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await product_service.search(organization_id, query=kw.get("query", ""), limit=kw.get("limit", 25))

    return ToolResult(tool_name="search_product", success=True, data=data)



async def _get_inventory_status(organization_id: uuid.UUID, **kw) -> ToolResult:

    """Get current inventory valuation, stock on hand, inward received, and outward issued."""

    from app.services import inventory_service

    product_name = kw.get("product_name") or kw.get("name") or kw.get("query")

    only_low_stock = bool(kw.get("only_low_stock") or kw.get("out_of_stock") or False)

    data = await inventory_service.get_inventory_status_summary(

        organization_id,

        product_name=str(product_name).strip() if product_name else None,

        only_low_stock=only_low_stock,

    )

    return ToolResult(tool_name="get_inventory_status", success=True, data=data)



async def _create_product(organization_id: uuid.UUID, **kw) -> ToolResult:

    if "sales_price" in kw and "unit_price" not in kw:
        kw["unit_price"] = kw.pop("sales_price")
    if "product_name" in kw and "name" not in kw:
        kw["name"] = kw.pop("product_name")

    data = await product_service.create(organization_id, **kw)

    return ToolResult(tool_name="create_product", success=True, data=data)



async def _search_service(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await service_service.search(organization_id, query=kw.get("query", ""), limit=kw.get("limit", 25))

    return ToolResult(tool_name="search_service", success=True, data=data)



async def _create_service(organization_id: uuid.UUID, **kw) -> ToolResult:

    if "sales_price" in kw and "standard_rate" not in kw:
        kw["standard_rate"] = kw.pop("sales_price")
    if "service_name" in kw and "name" not in kw:
        kw["name"] = kw.pop("service_name")

    data = await service_service.create(organization_id, **kw)

    return ToolResult(tool_name="create_service", success=True, data=data)



# ===================================================================

# FIXED ASSET LIFECYCLE (acquisition → depreciation → disposal/sale)

# ===================================================================




async def _update_product(organization_id: uuid.UUID, **kw) -> ToolResult:
    product_id = kw.get("product_id")
    if not product_id and kw.get("name"):
        existing = await product_service.search(organization_id, query=kw["name"], limit=5)
        for p in existing:
            if p.get("name", "").lower() == kw["name"].lower():
                product_id = p["id"]
                break
    if not product_id:
        return ToolResult(tool_name="update_product", success=False, error="Product not found or product_id required.")
    pid = uuid.UUID(str(product_id))
    changes = {k: v for k, v in kw.items() if k not in ("product_id",)}
    data = await product_service.update(organization_id, product_id=pid, **changes)
    return ToolResult(tool_name="update_product", success=True, data=data)


async def _delete_product(organization_id: uuid.UUID, **kw) -> ToolResult:
    product_id = kw.get("product_id")
    if not product_id and kw.get("name"):
        existing = await product_service.search(organization_id, query=kw["name"], limit=5)
        for p in existing:
            if p.get("name", "").lower() == kw["name"].lower():
                product_id = p["id"]
                break
    if not product_id:
        return ToolResult(tool_name="delete_product", success=False, error="Product not found or product_id required.")
    pid = uuid.UUID(str(product_id))
    try:
        await product_service.delete(organization_id, product_id=pid)
        return ToolResult(tool_name="delete_product", success=True, data={"deleted": True, "product_id": str(pid)})
    except ValueError as ve:
        await product_service.set_active(organization_id, product_id=pid, active=False)
        return ToolResult(tool_name="delete_product", success=True, data={"deactivated": True, "product_id": str(pid), "message": str(ve)})


async def _update_service(organization_id: uuid.UUID, **kw) -> ToolResult:
    service_id = kw.get("service_id")
    if not service_id and kw.get("name"):
        existing = await service_service.search(organization_id, query=kw["name"], limit=5)
        for s in existing:
            if s.get("name", "").lower() == kw["name"].lower():
                service_id = s["id"]
                break
    if not service_id:
        return ToolResult(tool_name="update_service", success=False, error="Service not found or service_id required.")
    sid = uuid.UUID(str(service_id))
    changes = {k: v for k, v in kw.items() if k not in ("service_id",)}
    data = await service_service.update(organization_id, service_id=sid, **changes)
    return ToolResult(tool_name="update_service", success=True, data=data)


async def _delete_service(organization_id: uuid.UUID, **kw) -> ToolResult:
    service_id = kw.get("service_id")
    if not service_id and kw.get("name"):
        existing = await service_service.search(organization_id, query=kw["name"], limit=5)
        for s in existing:
            if s.get("name", "").lower() == kw["name"].lower():
                service_id = s["id"]
                break
    if not service_id:
        return ToolResult(tool_name="delete_service", success=False, error="Service not found or service_id required.")
    sid = uuid.UUID(str(service_id))
    try:
        await service_service.delete(organization_id, service_id=sid)
        return ToolResult(tool_name="delete_service", success=True, data={"deleted": True, "service_id": str(sid)})
    except ValueError as ve:
        await service_service.set_active(organization_id, service_id=sid, active=False)
        return ToolResult(tool_name="delete_service", success=True, data={"deactivated": True, "service_id": str(sid), "message": str(ve)})


async def _search_fixed_asset(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await fixed_asset_service.search(organization_id, query=kw.get("query", ""), limit=kw.get("limit", 25))

    return ToolResult(tool_name="search_fixed_asset", success=True, data=data)



async def _get_fixed_asset(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await fixed_asset_service.get(organization_id, asset_id=uuid.UUID(kw["asset_id"]))

    return ToolResult(tool_name="get_fixed_asset", success=True, data=data)



async def _register_fixed_asset(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await fixed_asset_service.register_asset(organization_id, **kw)

    return ToolResult(tool_name="register_fixed_asset", success=True, data=data)



async def _dispose_fixed_asset(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await fixed_asset_service.dispose_asset(organization_id, **kw)

    return ToolResult(tool_name="dispose_fixed_asset", success=True, data=data)



async def _record_asset_depreciation(organization_id: uuid.UUID, **kw) -> ToolResult:

    data = await fixed_asset_service.record_depreciation(organization_id, **kw)

    return ToolResult(tool_name="record_asset_depreciation", success=True, data=data)



# Product catalog

register("search_product", handler=_search_product, read_only=True, description="Search the product catalog by name (empty result = no product exists yet)")

register("get_inventory_status", handler=_get_inventory_status, read_only=True, description="Get current inventory valuation, quantities on hand, inward received, and outward issued stock across catalogue products")

register("create_product", handler=_create_product, read_only=False, contract=contract_from_callable(product_service.create), description="Create a catalog product (catalog only — the ERP has no stock-quantity ledger). Set is_stock_tracked=true ONLY when the user explicitly answered the inventory question confirming resale stock — never infer it")
register("update_product", handler=_update_product, read_only=False, description="Update an existing product in the catalog (unit_price, cost_price, description, name, is_stock_tracked)")
register("delete_product", handler=_delete_product, read_only=False, description="Delete a product from the catalog, or deactivate it if documents already reference it")



# Service catalog

register("search_service", handler=_search_service, read_only=True, description="Search the service catalog by name (empty result = no service exists yet)")

register("create_service", handler=_create_service, read_only=False, contract=contract_from_callable(service_service.create), description="Create a catalog service (billing unit HOUR/DAY/MONTH/FIXED/ITEM — services never involve stock or assets)")
register("update_service", handler=_update_service, read_only=False, description="Update an existing service in the catalog (standard_rate, description, name, billing_unit)")
register("delete_service", handler=_delete_service, read_only=False, description="Delete a service from the catalog, or deactivate it if documents already reference it")



# Fixed asset lifecycle

register("search_fixed_asset", handler=_search_fixed_asset, read_only=True, description="Search registered fixed assets by name or code (empty result = asset not registered)")

register("get_fixed_asset", handler=_get_fixed_asset, read_only=True, description="Get fixed asset details by id")

register("register_fixed_asset", handler=_register_fixed_asset, read_only=False, contract=contract_from_callable(fixed_asset_service.register_asset), description="Acquire and capitalise a fixed asset: creates the asset record and posts the acquisition journal (Dr asset / Cr cash-bank or payable). Account is EXACTLY ONE of asset_account_id (a fitting ledger already exists — reuse it) or asset_account_name (NONE exists — create it first with a descriptive name, e.g. 'Building - Model Town', then pin it here)")

register("dispose_fixed_asset", handler=_dispose_fixed_asset, read_only=False, contract=contract_from_callable(fixed_asset_service.dispose_asset), description="Dispose of / sell / write off a fixed asset: removes cost and accumulated depreciation, records proceeds and any gain or loss via a posted journal")

register("record_asset_depreciation", handler=_record_asset_depreciation, read_only=False, contract=contract_from_callable(fixed_asset_service.record_depreciation), description="Record asset depreciation: posts the depreciation journal and updates accumulated depreciation and book value")







# ===================================================================

# FINANCIAL HEALTH SCORING

# ===================================================================



async def _calculate_health(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.health_service import calculate_health

    data = await calculate_health(organization_id)

    return ToolResult(tool_name="calculate_health", success=True, data=data)



async def _get_health(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.health_service import get_latest_snapshot, get_history

    latest = await get_latest_snapshot(organization_id)

    history = await get_history(organization_id)

    return ToolResult(tool_name="get_health", success=True, data={"latest": latest, "history": history})



register("calculate_health", handler=_calculate_health, read_only=False, description="Calculate financial health score")

register("get_health", handler=_get_health, read_only=True, description="Get financial health history")





# ===================================================================

# RECURRING TRANSACTIONS

# ===================================================================



async def _create_recurring_template(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.recurring_service import create_template

    data = await create_template(organization_id=organization_id, **kw)

    return ToolResult(tool_name="create_recurring_template", success=True, data=data)



async def _get_recurring_templates(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.recurring_service import list_templates

    data = await list_templates(

        organization_id, status=kw.get("status"), limit=kw.get("limit", 100)

    )

    return ToolResult(tool_name="get_recurring_templates", success=True, data=data)



async def _get_recurring_template(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.recurring_service import get_template

    data = await get_template(

        organization_id, template_id=uuid.UUID(str(kw["template_id"]))

    )

    return ToolResult(tool_name="get_recurring_template", success=True, data=data)



async def _update_recurring_template(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.recurring_service import set_status

    data = await set_status(

        organization_id=organization_id,

        template_id=uuid.UUID(str(kw["template_id"])),

        status=str(kw["status"]),

    )

    return ToolResult(tool_name="update_recurring_template", success=True, data=data)



async def _generate_recurring(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.recurring_service import generate_due

    data = await generate_due(organization_id, as_of=kw.get("as_of"))

    return ToolResult(tool_name="generate_recurring", success=True, data=data)



async def _get_recurring_executions(organization_id: uuid.UUID, **kw) -> ToolResult:

    from app.services.recurring_service import list_executions

    data = await list_executions(

        organization_id,

        template_id=uuid.UUID(str(kw["template_id"])) if kw.get("template_id") else None,

        limit=kw.get("limit", 100),

    )

    return ToolResult(tool_name="get_recurring_executions", success=True, data=data)



register("create_recurring_template", handler=_create_recurring_template, read_only=False, description="Create a recurring transaction template (balanced journal lines + frequency + next due date)")

register("get_recurring_templates", handler=_get_recurring_templates, read_only=True, description="List recurring transaction templates (optionally filter by status)")

register("get_recurring_template", handler=_get_recurring_template, read_only=True, description="Get a single recurring transaction template")

register("update_recurring_template", handler=_update_recurring_template, read_only=False, description="Pause / resume / complete / cancel a recurring template")

register("generate_recurring", handler=_generate_recurring, read_only=False, description="Generate journal entries for every due recurring template (draft unless auto_post); advances next due dates")

register("get_recurring_executions", handler=_get_recurring_executions, read_only=True, description="List recurring executions (generated/failed journal runs)")