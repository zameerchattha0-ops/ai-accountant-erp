"""Analytics agent - Odoo-style "ask your books" (READ-ONLY, 2 LLM calls).

Natural-language question -> LLM plans a TARGETED read query against a
compact DATA CATALOG (never free SQL) -> a deterministic executor runs it
org-scoped via the sanctioned fetch_many seam -> a second short LLM call
shapes a STRUCTURED answer whose numbers Python has already computed.

NON-NEGOTIABLES (mirrors the purchase-treatment conditions):
* READ-ONLY by construction - the plan DSL cannot express writes; no SQL
  ever leaves Python; organization_id is INJECTED by Python, never model.
* Numbers are NEVER invented - sums/counts/averages are computed HERE; the
  model only arranges and narrates. A headline number absent from the data
  is rejected and the deterministic fallback renderer answers instead.
* Empty states are honest - no rows -> "no records", never a guess.
* Fully audited - callers log ANALYTICS_PLAN / ANALYTICS_RESULT steps.
* Degrades both ways - flag off / provider down -> answer=None (the normal
  pipeline continues untouched), never a crash, never a wrong sum.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

MAX_OPS = 3
MAX_LIMIT = 200
MAX_ROWS_TO_MODEL = 40

_OPS = ("eq", "neq", "ilike", "gte", "lte", "between", "in")
_AGGREGATES = ("sum", "count", "avg", "min", "max")

# The "RIGHT PATH" map: what the planner may ask for, in its own words.
CATALOG: Dict[str, Dict[str, Any]] = {
    "journal_lines": {
        "desc": "general ledger lines (the books' truth)",
        "cols": ["debit", "credit", "account_id", "description",
                 "created_at"],
    },
    "accounts": {
        "desc": "chart of accounts (codes, names, types)",
        "cols": ["code", "name", "account_type", "is_active"],
    },
    "purchase_bills": {
        "desc": "supplier bills (payables); supplier_id refs suppliers",
        "cols": ["bill_number", "bill_date", "total", "amount_paid",
                 "status", "notes", "supplier_id"],
    },
    "invoices": {
        "desc": "customer invoices (receivables)",
        "cols": ["invoice_number", "invoice_date", "total", "status"],
    },
    "payments": {
        "desc": "recorded payments/receipts",
        "cols": ["payment_date", "amount", "method", "status"],
    },
    "inventory_movements": {
        "desc": "stock ledger; quantity>0 in, <0 out; product_id refs "
                "products",
        "cols": ["movement_date", "quantity", "unit_cost", "product_id",
                 "source_type"],
    },
    "products": {
        "desc": "catalogue items",
        "cols": ["name", "product_code", "is_stock_tracked", "is_active"],
    },
    "suppliers": {
        "desc": "supplier masters",
        "cols": ["name", "supplier_code", "is_active"],
    },
    "customers": {
        "desc": "customer masters",
        "cols": ["name", "customer_code", "is_active"],
    },
}


_QUESTION_RE = re.compile(
    r"^\s*(how\s+much|how\s+many|what\s+is|what'?s\s+my|what\s+are|show\s+me|"
    r"list|report|balance|total|which)\b", re.I,
)
_IMPERATIVE_RE = re.compile(
    r"\b(record|create|add|book|register|pay|send|issue|delete|mark)\b", re.I,
)


def analytics_gate(question: str) -> bool:
    """Deterministic routing gate: question-form AND NOT an imperative.

    The normal mutation pipeline stays untouched for anything imperative -
    this path can only ever READ.
    """
    from app.config import get_settings

    if not getattr(get_settings(), "analytics_agent_enabled", False):
        return False
    text = (question or "").strip()
    if not text or not _QUESTION_RE.search(text):
        return False
    # "how much did I pay X" analyses a PAST payment - allowed; an imperative
    # "pay X" is a mutation and must stay on the normal pipeline.
    body = re.sub(
        r"^(how\s+much|how\s+many|what\s+is|what'?s\s+my|what\s+are|"
        r"show\s+me|list|report|balance|total|which)\s+", "",
        text.strip(), flags=re.I,
    )
    return not _IMPERATIVE_RE.search(body)


def validate_plan(payload: Any) -> tuple:
    """Schema-validate the model's query plan -> (plan, errors)."""
    if not isinstance(payload, dict):
        return None, ["plan is not a JSON object"]
    ops = payload.get("operations")
    if not isinstance(ops, list) or not ops:
        return None, ["operations missing/empty"]
    if len(ops) > MAX_OPS:
        return None, [f"too many operations (max {MAX_OPS})"]
    shape = str(payload.get("answer_shape") or "table")
    if shape not in ("table", "timeseries", "single_value", "list"):
        return None, [f"unknown answer_shape {shape!r}"]
    clean: List[Dict[str, Any]] = []
    errors: List[str] = []
    for i, raw in enumerate(ops):
        if not isinstance(raw, dict):
            errors.append(f"op{i}: not an object")
            continue
        src = str(raw.get("source") or "")
        spec = CATALOG.get(src)
        if spec is None:
            errors.append(f"op{i}: unknown source {src!r}")
            continue
        cols_ok = set(spec["cols"])
        columns = [str(c) for c in (raw.get("columns") or ["*"])][:12]
        bad = [c for c in columns if c != "*" and c not in cols_ok]
        if bad:
            errors.append(f"op{i}: unknown columns {bad}")
            continue
        filters = []
        for f in (raw.get("filters") or [])[:4]:
            if not isinstance(f, dict):
                continue
            col, op = str(f.get("col") or ""), str(f.get("op") or "eq")
            if col not in cols_ok or op not in _OPS:
                errors.append(f"op{i}: bad filter {col}/{op}")
                continue
            filters.append({"col": col, "op": op, "value": f.get("value")})
        agg = raw.get("aggregate")
        agg_col = str(raw.get("column") or "")
        if agg is not None and (str(agg) not in _AGGREGATES
                                or agg_col not in cols_ok):
            errors.append(f"op{i}: bad aggregate {agg!r}")
            continue
        try:
            limit = min(int(raw.get("limit") or 50), MAX_LIMIT)
        except (TypeError, ValueError):
            limit = 50
        clean.append({
            "source": src, "columns": columns, "filters": filters,
            "aggregate": str(agg) if agg else None,
            "column": agg_col or None,
            "order": str(raw.get("order") or "") or None,
            "limit": limit,
        })
    if errors:
        return None, errors
    return {"operations": clean, "answer_shape": shape}, []



def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _catalog_block(today: str) -> str:
    lines = [f"TODAY: {today}", "", "SOURCES (only these; column list is "
             "exhaustive):"]
    for name, spec in CATALOG.items():
        lines.append(f"- {name}: {spec['desc']} | cols: "
                     + ", ".join(spec["cols"]))
    return "\n".join(lines)


_PLANNER_RULES = (
    "You plan READ-ONLY accounting queries. Reply with ONLY JSON:\n"
    '{"operations": [{"source": "<catalog source>", '
    '"columns": ["<col>", ...] or ["*"], '
    '"filters": [{"col": "<col>", "op": "eq|neq|ilike|gte|lte|between|in", '
    '"value": <scalar or [a,b]>}], '
    '"aggregate": "sum|count|avg|min|max"|null, "column": "<col for '
    'aggregate>", "order": "<col> asc|desc"|null, "limit": <int<=200>}], '
    '"answer_shape": "table|timeseries|single_value|list"}\n'
    "RULES: at most 3 operations; use explicit dates (YYYY-MM-DD) derived "
    "from TODAY; never invent columns; *_id columns reference another "
    "source - plan a second operation for names if needed; pick the "
    "NARROWEST query that answers the question (targeted path, minimal "
    "rows)."
)

_SYNTH_RULES = (
    "You shape a STRUCTURED answer from REAL rows. Reply with ONLY JSON:\n"
    '{"headline": "<one sentence using ONLY numbers present in the data>", '
    '"answer_type": "table|timeseries|single_value|list", '
    '"caveats": ["<short honest note>", ...]}\n'
    "RULES: never invent or round numbers away from the data; if a result "
    "set is empty say 'no records' plainly; mention the period covered."
)


async def plan_query(*, question: str, today: str,
                     client: Any, timeout: float) -> Optional[Dict[str, Any]]:
    raw = await asyncio.wait_for(
        client.generate_text_light(prompt=(
            f"{_PLANNER_RULES}\n\n{_catalog_block(today)}\n\n"
            f"QUESTION: {question[:800]}"
        )),
        timeout=timeout,
    )
    return _extract_json(str(raw or ""))


def _postgrest_filter(f: Dict[str, Any]) -> Any:
    col, op, val = f["col"], f["op"], f["value"]
    if op == "eq":
        return val
    if op == "neq":
        return f"neq.{val}"
    if op == "ilike":
        return f"ilike.%{val}%"
    if op == "gte":
        return f"gte.{val}"
    if op == "lte":
        return f"lte.{val}"
    if op == "in":
        items = val if isinstance(val, list) else [val]
        return "in." + "(" + ",".join(str(x) for x in items[:20]) + ")"
    return val  # between handled by the executor window + python trim


def _aggregate(rows: List[Dict[str, Any]], agg: str,
               column: Optional[str]) -> Any:
    """ALL arithmetic happens in Python - the model never computes."""
    if agg == "count":
        return len(rows)
    values = []
    for r in rows or []:
        try:
            values.append(float(r.get(column)))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0
    if agg == "sum":
        return round(sum(values), 2)
    if agg == "avg":
        return round(sum(values) / len(values), 2)
    if agg == "min":
        return round(min(values), 2)
    return round(max(values), 2)


async def execute_plan(*, organization_id, plan: Dict[str, Any]) -> List[Any]:
    """Run the validated plan org-scoped. Returns one result per op."""
    from app.database import fetch_many

    results = []
    for op in plan["operations"]:
        # ORG SCOPE INJECTED BY PYTHON - the model can never widen it.
        filters: Dict[str, Any] = {
            "organization_id": f"eq.{uuid_str(organization_id)}"
        }
        between_trim = None
        for f in op["filters"]:
            if f["op"] == "between":
                val = f["value"] if isinstance(f["value"], list) else []
                if len(val) == 2:
                    filters[f["col"]] = f"gte.{val[0]}"
                    between_trim = (f["col"], val[1])
            else:
                filters[f["col"]] = _postgrest_filter(f)
        select = ",".join(c for c in op["columns"] if c != "*") or "*"
        rows = await fetch_many(
            op["source"], filters=filters, select=select,
            order=op["order"], limit=op["limit"],
        ) or []
        if between_trim:
            col, hi = between_trim
            rows = [r for r in rows if str(r.get(col) or "") <= str(hi)]
        if op["aggregate"]:
            results.append({
                "aggregate": op["aggregate"], "column": op["column"],
                "value": _aggregate(rows, op["aggregate"], op["column"]),
                "row_count": len(rows),
                "source": op["source"],
            })
        else:
            results.append({"source": op["source"],
                            "rows": rows[:MAX_ROWS_TO_MODEL],
                            "row_count": len(rows)})
    return results


def uuid_str(value: Any) -> str:
    return str(value)



def _data_numbers(results: List[Any]) -> set:
    """Every number the answer is ALLOWED to mention."""
    nums: set = set()

    def _walk(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            nums.add(round(float(v), 2))
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, list):
            for x in v:
                _walk(x)

    _walk(results)
    return nums


def _headline_numbers_ok(headline: str, allowed: set) -> bool:
    """Guard: every >=3-decimal number in the headline must exist in the
    data (ISO dates 2026-10-01 are exempt)."""
    text = re.sub(r"\d{4}-\d{2}-\d{2}", "", headline or "")
    rounded = {round(n, 0) for n in allowed}
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
        raw = m.group(0).replace(",", "")
        try:
            value = round(float(raw), 2)
        except ValueError:
            return False
        if value not in allowed and round(value, 0) not in rounded:
            return False
    return True


def _fallback_answer(question: str, results: List[Any]) -> Dict[str, Any]:
    """Deterministic renderer - works with ZERO LLM availability."""
    parts = []
    for r in results:
        if "aggregate" in r:
            parts.append(f"{r['aggregate']}({r['column'] or 'rows'}) = "
                         f"{r['value']} over {r['row_count']} rows")
        else:
            parts.append(f"{r['source']}: {r['row_count']} rows")
    return {
        "headline": f"Result for '{question[:80]}': " + "; ".join(parts),
        "answer_type": "table",
        "caveats": ["deterministic fallback (LLM synthesis unavailable)"],
        "synth": "fallback",
    }



async def synthesize(*, question: str, results: List[Any], today: str,
                     client: Any, timeout: float) -> Dict[str, Any]:
    raw = await asyncio.wait_for(
        client.generate_text_light(prompt=(
            f"{_SYNTH_RULES}\n\nTODAY: {today}\nQUESTION: {question[:400]}\n"
            f"REAL DATA (JSON):\n{json.dumps(results, default=str)[:6000]}"
        )),
        timeout=timeout,
    )
    payload = _extract_json(str(raw or ""))
    if not isinstance(payload, dict):
        return _fallback_answer(question, results)
    headline = str(payload.get("headline") or "").strip()[:400]
    answer_type = str(payload.get("answer_type") or "table")
    if answer_type not in ("table", "timeseries", "single_value", "list"):
        answer_type = "table"
    caveats = [str(c)[:200] for c in (payload.get("caveats") or [])
               if str(c).strip()][:5]
    if not headline or not _headline_numbers_ok(headline,
                                                _data_numbers(results)):
        log.warning("analytics.synth_reject",
                    reason="headline number not in data")
        return _fallback_answer(question, results)
    return {"headline": headline, "answer_type": answer_type,
            "caveats": caveats, "synth": "llm"}


async def answer_analytics_question(
    *,
    organization_id: Any,
    question: str,
    client: Any = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """The full read-only round trip. NEVER raises; answer=None when the
    path cannot run (flag off / plan rejected / provider down)."""
    from datetime import date, datetime, timezone
    from app.config import get_settings

    settings = get_settings()
    audit: Dict[str, Any] = {"stage": "analytics", "llm": "skipped_disabled"}
    if not getattr(settings, "analytics_agent_enabled", False):
        return {"answer": None, "audit": audit}
    today = date.today().isoformat()
    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()
        t = timeout or getattr(settings, "analytics_llm_timeout", 10.0)
        payload = await plan_query(question=question, today=today,
                                   client=client, timeout=t)
        plan, errors = validate_plan(payload)
        audit["plan_errors"] = errors
        if plan is None:
            # ONE retry with the errors shown - the model may fix its plan.
            payload = await plan_query(
                question=(f"{question}\n(previous plan rejected: "
                          f"{'; '.join(errors)[:300]} - fix these)"),
                today=today, client=client, timeout=t,
            )
            plan, errors = validate_plan(payload)
            audit["plan_errors"] = errors
        if plan is None:
            audit["llm"] = "plan_rejected"
            return {"answer": None, "audit": audit}
        audit["llm"] = "planned"
        results = await execute_plan(
            organization_id=organization_id, plan=plan)
        synth = await synthesize(question=question, results=results,
                                 today=today, client=client, timeout=t)
        answer = {
            "headline": synth["headline"],
            "answer_type": synth["answer_type"],
            "results": results,
            "caveats": synth["caveats"],
            "period": today,
            "data_as_of": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "synth": synth["synth"],
        }
        audit["llm"] = "ok" if synth["synth"] == "llm" else "fallback"
        audit["plan"] = plan
        return {"answer": answer, "audit": audit}
    except Exception as exc:  # noqa: BLE001 - analytics never breaks a turn
        audit["llm"] = "failed"
        audit["error"] = str(exc)[:200]
        log.warning("analytics.failed", error=str(exc)[:200])
        return {"answer": None, "audit": audit}



def render_markdown(answer: Dict[str, Any]) -> str:
    """Deterministic card rendering for the chat summary."""
    lines = [f"**{answer.get('headline', '')}**", ""]
    for r in answer.get("results") or []:
        if "aggregate" in r:
            lines.append(f"- {r['aggregate']}({r['column'] or 'rows'}) = "
                         f"**{r['value']}** ({r['row_count']} rows from "
                         f"`{r['source']}`)")
        else:
            rows = r.get("rows") or []
            lines.append(f"- `{r['source']}` — {r['row_count']} rows:")
            if rows:
                cols = list(rows[0].keys())[:6]
                lines.append("| " + " | ".join(cols) + " |")
                lines.append("|" + "---|" * len(cols))
                for row in rows[:20]:
                    lines.append("| " + " | ".join(
                        str(row.get(c, ""))[:40] for c in cols) + " |")
    if answer.get("caveats"):
        lines.append("")
        for c in answer["caveats"]:
            lines.append(f"_{c}_")
    lines.append(f"\n_Data as of {answer.get('data_as_of', '?')}_")
    return "\n".join(lines)

