"""Compound split journal helpers and single-hop governance gates for app.agent."""
from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from app.models.schemas import (
    AffectedEntity,
    AgentResponse,
    ExecutionStatus,
    ToolCall,
    ToolResult,
)

log = structlog.get_logger(__name__)


async def register_compound_split_fixed_assets(
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    entities: Dict[str, Any],
    tool_results: Sequence[ToolResult],
    tool_calls: Sequence[ToolCall] = (),
) -> Tuple[List[str], List[AffectedEntity], int, str]:
    """Dual-register IAS 16 fixed-asset split lines after a successful compound journal."""
    comp_tr = next(
        (
            tr
            for tr in (tool_results or [])
            if tr.success and tr.tool_name == "create_compound_journal" and isinstance(tr.data, dict)
        ),
        None,
    )
    if comp_tr is None:
        return [], [], 0, "STRAIGHT_LINE"

    from app.multi_item_disaggregator import (
        extract_line_item_amount,
        format_item_with_quantity,
    )
    from app.date_parser import coerce_iso_date
    from app.services.fixed_asset_service import register_asset_from_split_line
    from app.conversational_manager import _match_asset_category

    j_entry_id = comp_tr.data.get("journal_entry_id")
    raw_items: List[Dict[str, Any]] = list(
        entities.get("line_items") or entities.get("disaggregated_items") or []
    )
    if not raw_items:
        for tc in tool_calls or ():
            if tc.tool_name == "create_compound_journal" and isinstance(tc.arguments, dict):
                raw_items = [
                    row
                    for row in (tc.arguments.get("lines") or [])
                    if isinstance(row, dict) and float(row.get("debit") or 0.0) > 0
                ]
                if raw_items:
                    break

    u_life_explicit = entities.get("useful_life_years") or entities.get("useful_life")
    dep_m = str(entities.get("depreciation_method") or "STRAIGHT_LINE")
    iso_dt = coerce_iso_date(entities.get("transaction_date"))
    applied_life = 0
    capitalized_assets: List[str] = []
    extra_entities: List[AffectedEntity] = []

    try:
        for ri in raw_items:
            if not isinstance(ri, dict):
                continue
            d_desc_raw = str(ri.get("description") or "").strip()
            d_desc = format_item_with_quantity(d_desc_raw or "Fixed Asset", ri.get("quantity"))
            line_amt = extract_line_item_amount(ri) or float(ri.get("debit") or 0.0)
            cat_m = _match_asset_category(d_desc_raw)
            is_fa = (
                str(ri.get("nature") or "").upper() == "FIXED_ASSET"
                or "IAS 16" in str(ri.get("ifrs_standard") or "").upper()
                or ri.get("is_fixed_asset")
                or cat_m in ("IT_EQUIPMENT", "FURNITURE", "VEHICLE", "MACHINERY")
                or str(ri.get("account_code") or "").startswith("15")
            )
            if not (is_fa and line_amt > 0):
                continue
            if u_life_explicit:
                try:
                    item_life = int(float(str(u_life_explicit).split()[0]))
                except (ValueError, TypeError):
                    item_life = 3 if cat_m == "IT_EQUIPMENT" else (10 if cat_m == "MACHINERY" else 5)
            else:
                item_life = 3 if cat_m == "IT_EQUIPMENT" else (10 if cat_m == "MACHINERY" else 5)
            applied_life = item_life
            reg = await register_asset_from_split_line(
                organization_id=organization_id,
                name=d_desc or "Fixed Asset",
                purchase_cost=line_amt,
                transaction_date=iso_dt,
                journal_entry_id=uuid.UUID(str(j_entry_id)) if j_entry_id else None,
                useful_life_years=item_life,
                depreciation_method=dep_m,
                account_code=ri.get("account_code"),
                account_name=ri.get("account_name"),
                created_by=user_id,
            )
            capitalized_assets.append(f"{d_desc} (PKR {line_amt:,.2f})")
            reg_dict = reg if isinstance(reg, dict) else {}
            extra_entities.append(AffectedEntity(
                type="fixed_asset",
                action="created",
                id=str(reg_dict["id"]) if reg_dict.get("id") else None,
                number=reg_dict.get("asset_number"),
                name=d_desc or "Fixed Asset",
                total=line_amt,
            ))
    except Exception as _fa_exc:
        log.warning("agent.compound_asset_registration_failed", error=str(_fa_exc)[:200])

    return capitalized_assets, extra_entities, (applied_life or 3), dep_m


def format_compound_journal_summary(
    *,
    tool_result_data: Any,
    entities: Dict[str, Any],
    capitalized_assets: Sequence[str],
    useful_life_years: int,
    depreciation_method: str,
) -> str:
    """Format canonical completion summary for a posted split compound journal."""
    data_dict = tool_result_data if isinstance(tool_result_data, dict) else {}
    tot = float(data_dict.get("total_debit") or entities.get("amount") or 0.0)
    n_lines = len(
        entities.get("line_items")
        or entities.get("disaggregated_items")
        or data_dict.get("lines")
        or []
    )
    entry_num = data_dict.get("entry_number")
    fa_summary = ""
    if capitalized_assets:
        fa_summary = (
            f"* **Capitalized in Fixed Assets:** {', '.join(capitalized_assets)} "
            f"({useful_life_years}-Year {str(depreciation_method).replace('_', ' ').title()})\n"
        )
    entry_ref_str = f"* **Journal Entry:** `{entry_num}`\n" if entry_num else ""
    return (
        f"### ✅ Multi-Entity Split Entry Posted (Compound Journal)\n\n"
        f"{entry_ref_str}"
        f"* **Total Amount:** **Rs. {tot:,.2f}**\n"
        f"* **Allocated Lines:** {n_lines} Segregated Items (IAS 16 / IAS 38 / Opex)\n"
        f"{fa_summary}"
        f"* **Status:** Posted to General Ledger"
        + (" & Fixed Assets Register" if capitalized_assets else "")
        + "\n\n"
        f"[View in General Ledger →](/accounting/journal)"
        + (" | [View in Fixed Assets →](/accounting/fixed-assets)" if capitalized_assets else "")
    )


async def single_hop_treatment_review_gate(
    *,
    organization_id: uuid.UUID,
    session_id: uuid.UUID,
    intent: str,
    entities: Dict[str, Any],
    single_hop_call: ToolCall,
    create_clarification_fn: Callable[..., Awaitable[Any]],
    update_status_fn: Callable[..., Awaitable[Any]],
    log_step_fn: Callable[..., Awaitable[Any]],
) -> Optional[AgentResponse]:
    """Run pre-commit accounting treatment review before single-hop execution."""
    try:
        from app.treatment_review import review_plan_treatment

        review = await review_plan_treatment(
            organization_id=organization_id,
            intent=str(intent or ""),
            classification=None,
            entities=dict(entities or {}),
            calls=[single_hop_call],
        )
        await log_step_fn(session_id, "TREATMENT_REVIEW", review.audit)
        if review.blocked:
            await create_clarification_fn(
                session_id=session_id,
                question=review.question[:1500],
                required_fields=["resolution"],
            )
            await update_status_fn(session_id, ExecutionStatus.AWAITING_CLARIFICATION)
            await log_step_fn(
                session_id,
                "AWAITING_CLARIFICATION",
                {
                    "source": "treatment_review",
                    "flags": review.flags,
                    "question": review.question[:500],
                },
            )
            return AgentResponse(
                status=ExecutionStatus.AWAITING_CLARIFICATION,
                execution_id=session_id,
                question=review.question[:1500],
                required_information=["resolution"],
                requires_user_input=True,
            )
    except Exception as exc:  # noqa: BLE001 - review never crashes single-hop
        log.warning("agent.single_hop_treatment_review_failed", error=str(exc)[:200])
    return None
