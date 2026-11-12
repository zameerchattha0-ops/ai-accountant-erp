"""
ERP AI Agent — Tool Router
============================
Safely routes Gemini tool calls to backend implementations.

Flow:  Gemini → Tool Call → Registry → Permission Check → Organisation
Scope → Parameter Validation → Risk Check → Validator → Service →
Repository → Supabase

Never executes an arbitrary tool name received from Gemini.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import date
from typing import Any, Dict, Optional

import structlog

from app.auth import AuthContext
from app.database import fetch_many
from app.date_parser import parse_transaction_date
import app.error_normalizer as error_norm
from app import idempotency as idem
from app.error_normalizer import normalize_error
from app.models.schemas import ToolCall, ToolResult
from app.permissions import authorize_tool
from app.tools import derive_live_parameter_schema, get_handler, list_tools, resolve_tool_alias
from app.validator import validate_operation

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool-definition cache.  Definitions are cached per section key in-process
# for 5 minutes and cleared via invalidate_tool_definition_cache().
# ---------------------------------------------------------------------------
_TOOL_DEFS_TTL_SECONDS = 300.0
_TOOL_DEFS_CACHE: Optional[Dict[Optional[str], tuple[float, list[Dict[str, Any]]]]] = None

# ---------------------------------------------------------------------------
# 2-Tier Dynamic Tool Loading
# ---------------------------------------------------------------------------
# Tier 1: Always-loaded read & discovery tools (~15 tools).
TIER_1_TOOLS: frozenset[str] = frozenset({
    "discover_erp_capabilities",
    "get_trial_balance",
    "get_profit_loss",
    "get_balance_sheet",
    "get_cash_flow",
    "get_open_payables",
    "get_open_receivables",
    "get_supplier_ledger",
    "get_customer_ledger",
    "search_account",
    "get_chart_of_accounts",
    "list_bank_accounts",
    "search_customer",
    "search_supplier",
    "get_inventory_status",
})

# Maps ERP_MODULES task names in app/erp_endpoints.py that differ from
# canonical _TOOL_REGISTRY slugs.
_ERP_TASK_TO_TOOL_SLUG: Dict[str, str] = {
    "record_payment": "record_supplier_payment",
    "record_receipt": "record_customer_receipt",
    "record_expense": "create_expense",
    "generate_trial_balance": "get_trial_balance",
    "generate_balance_sheet": "get_balance_sheet",
    "generate_profit_loss": "get_profit_loss",
    "generate_cash_flow": "get_cash_flow",
    "generate_general_ledger": "get_general_ledger",
    "project_profitability": "get_project_profitability",
    "record_credit_sale": "create_invoice",
    "record_credit_purchase": "create_purchase_bill",
    "customer_balance": "get_open_receivables",
    "supplier_balance": "get_open_payables",
}

_SECTION_ALIASES: Dict[str, str] = {
    "payroll": "employees",
    "hr": "employees",
    "inventory": "catalogue",
    "products": "catalogue",
    "services": "catalogue",
    "assets": "fixed_assets",
    "fixed_asset": "fixed_assets",
    "bank": "banking",
    "cash": "banking",
    "finance": "accounting",
    "journal": "accounting",
    "journals": "accounting",
    "gl": "accounting",
    "vat": "tax",
    "gst": "tax",
    "wht": "tax",
    "purchase": "purchases",
    "procurement": "purchases",
    "sale": "sales",
    "revenue": "sales",
    "expense": "expenses",
    "loan": "loans",
    "project": "projects",
    "report": "reports",
    "customer": "customers",
    "supplier": "suppliers",
}

_EXTRA_SECTION_TOOLS: Dict[str, frozenset[str]] = {
    "accounting": frozenset({"validate_journal", "create_compound_journal"}),
    "purchases": frozenset({
        "create_purchase_order",
        "get_purchase_order",
        "get_purchase_bill",
        "create_supplier",
        "get_supplier",
        "update_document_status",
    }),
    "sales": frozenset({
        "get_invoice",
        "create_customer",
        "get_customer",
        "update_document_status",
    }),
    "expenses": frozenset({"classify_expense"}),
    "employees": frozenset({
        "get_organization_leave_policy",
        "set_organization_leave_policy",
    }),
    "catalogue": frozenset({"update_document_status"}),
    "reports": frozenset({"generate_report"}),
    "customers": frozenset({"get_open_receivables"}),
    "suppliers": frozenset({"get_open_payables"}),
    "tax": frozenset({
        "get_organization_tax_profile",
        "set_organization_tax_profile",
    }),
}


def get_section_tools(section: str) -> frozenset[str]:
    """Return Tier 2 tool slugs for *section* using ``ERP_MODULES``."""
    from app.erp_endpoints import ERP_MODULES

    norm = section.strip().lower().replace("-", "_").replace(" ", "_")
    norm = _SECTION_ALIASES.get(norm, norm)

    registered = set(list_tools())
    resolved: set[str] = set()

    mod = ERP_MODULES.get(norm)
    if mod:
        for task in mod.get("tasks", []):
            mapped = _ERP_TASK_TO_TOOL_SLUG.get(task, task)
            canonical = resolve_tool_alias(mapped)
            if canonical in registered:
                resolved.add(canonical)

    for extra in _EXTRA_SECTION_TOOLS.get(norm, ()):
        if extra in registered:
            resolved.add(extra)

    return frozenset(resolved)


def _resolve_json_schema_node(node: Any, defs: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Pydantic JSON-Schema property node for Gemini/OpenAI compatibility."""
    if not isinstance(node, dict):
        return {"type": "string"}

    if "$ref" in node:
        ref = str(node["$ref"])
        ref_name = ref.rsplit("/", 1)[-1]
        target = defs.get(ref_name, {})
        merged = dict(target)
        for k, v in node.items():
            if k != "$ref":
                merged[k] = v
        node = merged

    # Unwrap Optional[...] anyOf / oneOf variants, dropping null.
    for union_key in ("anyOf", "oneOf"):
        if union_key in node and isinstance(node[union_key], list):
            non_null = [
                sub for sub in node[union_key]
                if not (isinstance(sub, dict) and sub.get("type") == "null")
            ]
            if non_null:
                chosen = _resolve_json_schema_node(non_null[0], defs)
                result = dict(chosen)
                if node.get("description") and not result.get("description"):
                    result["description"] = node["description"]
                return result

    schema_type = node.get("type", "string")
    if isinstance(schema_type, list):
        non_null_types = [t for t in schema_type if t != "null"]
        schema_type = non_null_types[0] if non_null_types else "string"

    out: Dict[str, Any] = {"type": schema_type}
    if node.get("description"):
        out["description"] = node["description"]
    if "enum" in node:
        out["enum"] = list(node["enum"])

    if schema_type == "array":
        raw_items = node.get("items")
        if isinstance(raw_items, dict):
            out["items"] = _resolve_json_schema_node(raw_items, defs)
        else:
            out["items"] = {"type": "object"}
    elif schema_type == "object":
        raw_props = node.get("properties")
        if isinstance(raw_props, dict) and raw_props:
            out["properties"] = {
                pk: _resolve_json_schema_node(pv, defs)
                for pk, pv in raw_props.items()
            }
            if node.get("required"):
                out["required"] = [
                    r for r in node["required"] if r in out["properties"]
                ]

    return out


def _pydantic_schema_to_gemini_parameters(args_model: Any) -> Optional[Dict[str, Any]]:
    """Build Gemini-compatible ``parameters`` dict from a Pydantic ``BaseModel``."""
    raw = args_model.model_json_schema()
    defs = raw.get("$defs") or {}
    raw_props = raw.get("properties") or {}
    ignored = {"organization_id", "created_by", "ai_execution_id"}

    properties: Dict[str, Any] = {}
    for pname, pschema in raw_props.items():
        if pname in ignored:
            continue
        prop = _resolve_json_schema_node(pschema, defs)
        if not prop.get("description"):
            prop["description"] = pschema.get("title") or pname
        properties[pname] = prop

    if not properties:
        return None

    required = [
        req for req in (raw.get("required") or [])
        if req in properties
    ]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }

# ---------------------------------------------------------------------------
# transaction-date protocol.  Mutation tools whose native
# date parameter the model must supply.  When the model omits it, the
# router maps a supplied ``transaction_date`` through the deterministic
# parser onto the native parameter, or defaults to TODAY and flags the
# result with ``date_defaulted: true`` so the response can state the
# assumed date honestly (never a silent guess).
# ---------------------------------------------------------------------------
_TXN_DATE_PARAM: Dict[str, str] = {
    "create_invoice": "invoice_date",
    "create_purchase_bill": "bill_date",
    "create_expense": "expense_date",
    "create_quotation": "quotation_date",
    "create_credit_note": "credit_note_date",
    "create_purchase_return": "return_date",
    "record_customer_receipt": "receipt_date",
    "record_supplier_payment": "payment_date",
    "record_expense_payment": "payment_date",
    "record_bank_transfer": "transfer_date",
    "record_cash_sale": "transaction_date",
    "register_fixed_asset": "transaction_date",
    "dispose_fixed_asset": "transaction_date",
    "record_asset_depreciation": "transaction_date",
}

_PERIOD_GUIDANCE = (
    "reopen the period in Settings or choose a date within an open "
    "accounting period"
)


def _is_closed_period_error(message: str) -> bool:
    """Detect a closed/missing accounting-period refusal from the DB."""
    low = (message or "").lower()
    return "period" in low and (
        "closed" in low or "no open" in low or "not open" in low
    )


async def _terminalise_claim(
    op_id: Optional[uuid.UUID], exc: BaseException
) -> None:
    """Release a financial-mutation claim on a FAILED path.

    If the generic ``except Exception`` returns a ToolResult WITHOUT
    releasing the claim, the ``public.financial_operations`` row stays
    ``IN_PROGRESS`` with ``error = NULL`` — a claim that both hides the cause
    and blocks the legitimate retry until the stale window expires.

    The RAW exception type and message are stored, not the sanitised
    model-facing sentence: the user-facing text is deliberately generic
    ("An unexpected error occurred while executing this operation."), so the
    claim is the ONLY durable place the real cause can survive. A FAILED claim
    is reclaimable — ``claim_financial_operation`` resets it on the next
    attempt — so recording the failure never wedges a retry.
    """
    if op_id is None:
        return
    await idem.safe_complete(op_id, error=f"{type(exc).__name__}: {exc}")


def invalidate_tool_definition_cache() -> None:
    """Explicitly drop the cached Gemini tool definitions.

    Call after seeding/updating ``ai.tools`` / ``ai.tool_parameters`` so the
    next request rebuilds the declarations from the database.
    """
    _invalidate_tool_definition_cache_internal()


def _invalidate_tool_definition_cache_internal() -> None:
    """Test/internal hook: clears the cache regardless of TTL."""
    global _TOOL_DEFS_CACHE
    _TOOL_DEFS_CACHE = None



async def route_tool_call(
    tool_call: ToolCall,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: Optional[uuid.UUID] = None,
    auth: Optional[AuthContext] = None,
) -> ToolResult:
    """Route a tool call through security and validation layers.

    1. Verify the tool is registered
    2. Check permissions (via ai.permissions)
    3. Validate parameters
    4. Run business validator for mutations
    5. Execute the tool handler
    """
    slug = tool_call.tool_name
    canonical_slug = resolve_tool_alias(slug)
    if canonical_slug != slug:
        log.info("tool_router.alias_resolved", requested=slug, canonical=canonical_slug)
        slug = canonical_slug
        tool_call.tool_name = canonical_slug

    arguments = tool_call.arguments or {}

    # 1. Check registry
    entry = get_handler(slug)
    if not entry:
        log.warning("tool_router.unknown_tool", tool=slug)
        return ToolResult(
            tool_name=slug,
            success=False,
            error=f"Unknown tool: {slug}",
        )

    handler = entry["handler"]
    read_only = entry["read_only"]

    # 1x. ATTRIBUTION IS ROUTER-OWNED (same class as organization_id): the
    # model has no way to know the executing user's id, and a model-authored
    # value dies at the uuid cast — production 2026-09-24 16:30 (session
    # 66d1dbb6): ``created_by: "user"`` -> 22P02 invalid input syntax for
    # type uuid, bannered as "Something went wrong".  A SUPPLIED value is
    # rebound to the REAL actor (or dropped when the tool cannot carry it);
    # an ABSENT value stays absent — no silent injection.  Runs before
    # validation and the idempotency claim so the stored request hash sees
    # exactly what will execute.
    if "created_by" in arguments:
        contract = entry.get("contract") or {}
        accepted = set(contract.get("accepted") or ())
        arguments = {k: v for k, v in arguments.items() if k != "created_by"}
        if not contract or "created_by" in accepted or contract.get("accepts_extra"):
            arguments["created_by"] = str(user_id)
            log.info("tool_router.created_by_rebound", tool=slug, user=str(user_id))
        else:
            log.warning("tool_router.created_by_dropped", tool=slug)

    # 2. Permission check (via ai.permissions)
    if auth is None:
        # SECURITY: a MUTATION must never execute without an authorization
        # context.  The AI worker used to pass auth=None, which skipped BOTH
        # the permission check and the parameter validation below, so a
        # queued job could create financial documents with no authorization
        # at all.  Fail closed instead.
        if not read_only:
            log.error("tool_router.missing_auth_for_mutation", tool=slug)
            return ToolResult(
                tool_name=slug,
                success=False,
                error=(
                    "Authorization context missing: mutations cannot run "
                    "without an authenticated user."
                ),
            )
        log.warning("tool_router.read_without_auth", tool=slug)
    else:
        # Run authorization and business validation in parallel for mutations (saves 1 round-trip)
        if not read_only:
            permitted, validation = await asyncio.gather(
                authorize_tool(slug, auth=auth),
                validate_operation(
                    organization_id=organization_id,
                    operation=slug,
                    data=arguments,
                ),
            )
            if not permitted:
                log.warning(
                    "tool_router.permission_denied",
                    tool=slug,
                    user=str(user_id),
                    role=auth.role_code,
                )
                return ToolResult(
                    tool_name=slug,
                    success=False,
                    error=f"Permission denied: your role ({auth.role_code}) cannot use {slug}.",
                )
            if not validation.valid:
                log.warning(
                    "tool_router.validation_failed",
                    tool=slug,
                    errors=validation.errors,
                )
                return ToolResult(
                    tool_name=slug,
                    success=False,
                    error=f"Validation failed: {'; '.join(validation.errors)}",
                )
        else:
            permitted = await authorize_tool(slug, auth=auth)
            if not permitted:
                log.warning(
                    "tool_router.permission_denied",
                    tool=slug,
                    user=str(user_id),
                    role=auth.role_code,
                )
                return ToolResult(
                    tool_name=slug,
                    success=False,
                    error=f"Permission denied: your role ({auth.role_code}) cannot use {slug}.",
                )

    # 3b. EXACTLY-ONCE PROTECTION for financial mutations (migration 075).
    #
    # Replaces the previous amount-based guard, which covered ONE tool slug in
    # ONE session with no persistence and treated two legitimately identical
    # transactions as one — i.e. it could suppress a real financial record.
    #
    #   replay      -> identical retry: return the ORIGINAL stored result
    #   in_progress -> an identical request is already running
    #   40001       -> the key was reused with DIFFERENT parameters
    op_id: Optional[uuid.UUID] = None
    if not read_only and slug in idem.FINANCIAL_MUTATION_TOOLS:
        arguments = dict(arguments)
        explicit_key = arguments.pop("idempotency_key", None)
        key = idem.derive_key(
            explicit=explicit_key, session_id=session_id, operation=slug
        )
        if key:
            try:
                outcome = await idem.claim(
                    organization_id=organization_id,
                    operation=slug,
                    key=key,
                    arguments=arguments,
                    user_id=user_id,
                )
                state = (outcome or {}).get("state")
                if state == "replay":
                    log.info("tool_router.idempotent_replay", tool=slug)
                    log.info(
                        "mutation_idempotency_hit",
                        tool=slug,
                        session_id=str(session_id) if session_id else None,
                    )
                    replayed = outcome.get("result") or {}
                    return ToolResult(
                        tool_name=slug,
                        success=True,
                        data={**replayed, "replayed": True},
                    )
                if state == "in_progress":
                    log.warning("tool_router.idempotent_in_progress", tool=slug)
                    return ToolResult(
                        tool_name=slug,
                        success=False,
                        error=(
                            "An identical request is already being processed. "
                            "Not repeating it, to avoid a duplicate document."
                        ),
                    )
                op_id = outcome.get("id")
            except Exception as exc:  # noqa: BLE001 — never block on guard failure
                if idem.is_key_conflict(exc):
                    log.warning("tool_router.idempotency_key_conflict", tool=slug)
                    return ToolResult(
                        tool_name=slug,
                        success=False,
                        error=(
                            "This request key was already used for a different "
                            "request. Use a new key for a new operation."
                        ),
                    )
                log.warning(
                    "tool_router.idempotency_claim_failed", error=str(exc)[:200]
                )

    # 3b. map a resolved
    #     transaction_date onto the tool's native date parameter; when the
    #     model supplied none, default to TODAY and flag the result so the
    #     response states the assumed date honestly (never a silent guess).
    date_param = None if read_only else _TXN_DATE_PARAM.get(slug)
    date_defaulted = False

    # 4. Execute.  The attempt is guarded from the DATE MAPPING onwards (not
    #    only from the handler call) so that EVERY failure after the claim
    #    lands in one of the two handlers below — the only places that can
    #    release the claim.  Anything that escapes this block would leave the
    #    claim IN_PROGRESS forever (see ``_terminalise_claim``).
    try:
        if date_param:
            arguments = dict(arguments)
            supplied = arguments.get(date_param) or arguments.get("transaction_date")
            parsed = parse_transaction_date(str(supplied)) if supplied else None
            if parsed and parsed.ok:
                arguments[date_param] = parsed.iso_date
            else:
                arguments[date_param] = date.today().isoformat()
                date_defaulted = True
        # Argument Sanitization: strip unaccepted extra keyword arguments if contract is declared
        contract = entry.get("contract") or {}
        accepted = set(contract.get("accepted") or ())
        if accepted and not contract.get("accepts_extra"):
            sanitized_args = {k: v for k, v in arguments.items() if k in accepted or k in ("organization_id", "created_by")}
            dropped = set(arguments.keys()) - set(sanitized_args.keys())
            if dropped:
                log.info("tool_router.sanitized_extra_kwargs", tool=slug, dropped=sorted(dropped))
            arguments = sanitized_args

        result = await handler(organization_id, **arguments)
        if date_defaulted and result.success:
            if isinstance(result.data, dict):
                result.data["date_defaulted"] = True
                result.data["transaction_date"] = arguments[date_param]
            else:
                result.data = {
                    "date_defaulted": True,
                    "transaction_date": arguments[date_param],
                }
        # Record the outcome LAST, so the stored result is exactly what the
        # caller saw — including the honest date disclosure above.  A replay
        # must not report a different payload from the original attempt.
        if op_id is not None:
            await idem.safe_complete(
                op_id,
                result=(result.data if result.success else None),
                error=(None if result.success else result.error),
            )
        log.info(
            "tool_router.executed",
            tool=slug,
            success=result.success,
            session_id=str(session_id) if session_id else None,
        )
        return result
    except ValueError as exc:
        log.warning("tool_router.value_error", tool=slug, error=str(exc))
        normalized = normalize_error(exc, operation=slug)
        message = str(exc)
        if _is_closed_period_error(message):
            message = f"{message} Guidance: {_PERIOD_GUIDANCE}."
        await _terminalise_claim(op_id, exc)
        return ToolResult(
            tool_name=slug,
            success=False,
            error=message,
            error_category=normalized["category"],
            error_details=normalized,
        )
    except Exception as exc:
        log.error(
            "tool_router.unexpected_error",
            tool=slug,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        normalized = normalize_error(exc, operation=slug)
        # Model-facing message: for recoverable categories give the model an
        # actionable instruction (e.g. reuse an existing record); genuine
        # infrastructure failures keep the generic system-failure text.
        if normalized["category"] == error_norm.DUPLICATE_RECORD:
            model_message = error_norm.build_duplicate_guidance(normalized.get("entity"))
        elif normalized["category"] == error_norm.INFRASTRUCTURE_ERROR:
            model_message = "An unexpected error occurred while executing this operation."
        elif normalized.get("requires_user_input"):
            model_message = (
                f"{normalized['reason']}. This value must be supplied by the "
                "user — do not guess or use a default."
            )
        else:
            model_message = "An unexpected error occurred while executing this operation."
        if _is_closed_period_error(str(exc)):
            model_message = (
                f"{str(exc)} Guidance: {_PERIOD_GUIDANCE}."
            )
        await _terminalise_claim(op_id, exc)
        return ToolResult(
            tool_name=slug,
            success=False,
            error=model_message,
            error_category=normalized["category"],
            error_details=normalized,
        )


async def get_gemini_tool_definitions(
    section: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Return tool definitions formatted for Gemini's function-calling API.

    Uses ``handler._args_model.model_json_schema()`` as the single source of
    truth whenever a handler declares a Pydantic ``Args`` model, eliminating
    the ``ai.tools`` / ``ai.tool_parameters`` DB split-brain. Falls back to
    DB + AST inspection only for handlers without ``_args_model``.

    Supports 2-tier dynamic tool loading via *section*:
    - ``section=None`` (or ``"all"``): returns all tools (backward compat).
    - ``section="tier1"``: returns Tier 1 read/discovery tools only.
    - ``section="<module>"``: returns Tier 1 + that ERP module's Tier 2 tools.
    """
    global _TOOL_DEFS_CACHE
    norm_section: Optional[str] = None
    if section is not None:
        cleaned = section.strip().lower().replace("-", "_").replace(" ", "_")
        if cleaned and cleaned != "all":
            norm_section = _SECTION_ALIASES.get(cleaned, cleaned)

    now = time.monotonic()
    if isinstance(_TOOL_DEFS_CACHE, dict) and norm_section in _TOOL_DEFS_CACHE:
        loaded_at, tools_cached = _TOOL_DEFS_CACHE[norm_section]
        if now - loaded_at < _TOOL_DEFS_TTL_SECONDS:
            return tools_cached

    all_slugs = list_tools()
    if norm_section is None:
        target_slugs = all_slugs
    elif norm_section in ("tier1", "tier_1", "core", "discovery"):
        target_slugs = [s for s in all_slugs if s in TIER_1_TOOLS]
    else:
        allowed = TIER_1_TOOLS | get_section_tools(norm_section)
        target_slugs = [s for s in all_slugs if s in allowed]

    # Only query ai.tools / ai.tool_parameters when at least one selected
    # handler lacks a Pydantic _args_model (backward-compatibility fallback).
    needs_db_fallback = any(
        getattr((get_handler(slug) or {}).get("handler"), "_args_model", None) is None
        for slug in target_slugs
    )

    slug_to_id: Dict[str, Any] = {}
    tool_params: Dict[str, list] = {}
    if needs_db_fallback:
        all_tool_rows = await fetch_many(
            "ai_tools",
            filters={"status": "IMPLEMENTED"},
            select="id,slug",
            limit=200,
        )
        slug_to_id = {r["slug"]: r["id"] for r in all_tool_rows}
        if slug_to_id:
            tool_ids = list(slug_to_id.values())
            from app.database import _execute, get_service_client

            param_rows = (
                (
                    await _execute(
                        get_service_client()
                        .schema("ai")
                        .table("tool_parameters")
                        .select("tool_id,parameter_name,description,data_type,required,position")
                        .in_("tool_id", tool_ids)
                        .limit(2000)
                    )
                ).data
                or []
            )
            for row in param_rows:
                tool_params.setdefault(row["tool_id"], []).append(row)

    tools: list[Dict[str, Any]] = []
    for slug in target_slugs:
        entry = get_handler(slug)
        if not entry:
            continue

        handler = entry.get("handler")
        args_model = getattr(handler, "_args_model", None)

        declaration: Dict[str, Any] = {
            "name": slug,
            "description": entry.get("description", slug),
        }

        if args_model is not None:
            parameters = _pydantic_schema_to_gemini_parameters(args_model)
            if parameters:
                declaration["parameters"] = parameters
            tools.append(declaration)
            continue

        # Fallback: DB + AST inspection for handlers without _args_model.
        tool_id = slug_to_id.get(slug)
        params = tool_params.get(tool_id, []) if tool_id else []
        params.sort(key=lambda p: p.get("position") or 999)

        live_schema = derive_live_parameter_schema(slug)
        live_props = dict(live_schema.get("properties") or {})
        live_required = list(live_schema.get("required") or [])
        strict_contract = bool(live_schema.get("strict_contract"))

        properties: Dict[str, Any] = {}
        required_fields: list[str] = []

        for p in params:
            pname = p["parameter_name"]
            if pname in ("organization_id", "created_by", "ai_execution_id"):
                continue
            if strict_contract and pname not in live_props:
                continue
            properties[pname] = {
                "type": p.get("data_type", "string"),
                "description": p.get("description", ""),
            }
            if p.get("required"):
                required_fields.append(pname)

        for pname, lprop in live_props.items():
            if pname not in properties:
                properties[pname] = dict(lprop)
            elif not properties[pname].get("description") and lprop.get("description"):
                properties[pname]["description"] = lprop["description"]
        for req in live_required:
            if req not in required_fields and req in properties:
                required_fields.append(req)

        if properties:
            declaration["parameters"] = {
                "type": "object",
                "properties": properties,
                "required": required_fields,
            }
        tools.append(declaration)

    if not isinstance(_TOOL_DEFS_CACHE, dict):
        _TOOL_DEFS_CACHE = {}
    _TOOL_DEFS_CACHE[norm_section] = (time.monotonic(), tools)
    return tools
