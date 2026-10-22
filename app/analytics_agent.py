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
# Computed answer shapes: exactly which arithmetic Python is allowed to do
# on aggregate results (never anything else, never by the model).
_FORMULAS = ("op1_minus_op2",)

# The "RIGHT PATH" map: every business module the planner may target, with
# LIVE-VERIFIED columns (checked against the database 2026-10-19 — the old
# catalog carried unverified columns like payments.status guesses).
CATALOG: Dict[str, Dict[str, Any]] = {
    # ---- SALES module -------------------------------------------------
    "invoices": {
        "desc": "SALES invoices to customers (module: Sales)",
        "cols": ["invoice_number", "invoice_date", "due_date", "subtotal",
                 "tax_total", "total", "amount_paid", "status", "customer_id",
                 "paid_at", "voided_at", "created_at"],
    },
    "invoice_items": {
        "desc": "SALES invoice lines - what was sold (qty/price per line)",
        "cols": ["invoice_id", "description", "product_id", "quantity",
                 "unit_price", "discount_amount", "tax_amount", "line_total",
                 "created_at"],
    },
    "credit_notes": {
        "desc": "SALES RETURNS (credit notes) issued to customers",
        "cols": ["credit_note_number", "credit_note_date", "customer_id",
                 "invoice_id", "subtotal", "tax_total", "total", "reason",
                 "status", "journal_entry_id", "created_at"],
    },
    "credit_note_items": {
        "desc": "SALES RETURN lines (what a customer returned)",
        "cols": ["credit_note_id", "description", "product_id", "quantity",
                 "unit_price", "tax_amount", "line_total", "created_at"],
    },
    # ---- PURCHASES module ---------------------------------------------
    "purchase_bills": {
        "desc": "PURCHASES from suppliers (bills/payables)",
        "cols": ["bill_number", "bill_date", "due_date", "supplier_id",
                 "supplier_invoice_ref", "subtotal", "tax_total", "total",
                 "amount_paid", "status", "notes", "paid_at", "voided_at",
                 "journal_entry_id", "created_at"],
    },
    "purchase_bill_items": {
        "desc": "PURCHASE lines - what was bought (qty/price per line)",
        "cols": ["bill_id", "description", "product_id", "expense_account_id",
                 "fixed_asset_id", "quantity", "unit_price", "discount_amount",
                 "tax_amount", "line_total", "created_at"],
    },
    "purchase_returns": {
        "desc": "PURCHASE RETURNS (debit notes) sent back to suppliers",
        "cols": ["return_number", "return_date", "bill_id", "supplier_id",
                 "subtotal", "tax_total", "total", "reason", "status",
                 "journal_entry_id", "created_at"],
    },
    "purchase_return_items": {
        "desc": "PURCHASE RETURN lines (what was sent back to a supplier)",
        "cols": ["return_id", "bill_item_id", "description", "product_id",
                 "quantity", "unit_price", "tax_amount", "line_total",
                 "created_at"],
    },
    # ---- INVENTORY module ---------------------------------------------
    "inventory_movements": {
        "desc": "INVENTORY stock ledger: quantity in/out per product "
                "(direction IN/OUT)",
        "cols": ["movement_date", "direction", "quantity", "unit_cost",
                 "value", "product_id", "source_type", "source_id",
                 "description", "created_at"],
    },
    "products": {
        "desc": "CATALOGUE products (stock-tracked items, prices, costs)",
        "cols": ["product_code", "name", "unit", "is_stock_tracked",
                 "unit_price", "cost_price", "is_active", "category_id",
                 "created_at"],
    },
    # ---- PAYMENTS module ----------------------------------------------
    "payments": {
        "desc": "PAYMENTS recorded (supplier payments/outflows & transfers)",
        "cols": ["payment_number", "payment_date", "direction",
                 "payment_method", "amount", "supplier_id", "expense_id",
                 "bank_account_id", "cash_account_id", "status", "reference",
                 "journal_entry_id", "created_at"],
    },
    # ---- JOURNAL module -----------------------------------------------
    "journal_entries": {
        "desc": "JOURNAL entries (one per posting: JV numbers, totals)",
        "cols": ["journal_number", "transaction_date", "description",
                 "reference", "source_type", "total_debit", "total_credit",
                 "status", "posted_at", "created_at"],
    },
    "journal_lines": {
        "desc": "GENERAL LEDGER lines (the books' truth); account_code/"
                "account_type are resolved by the system against the chart",
        "cols": ["entry_id", "account_id", "account_code", "account_type",
                 "debit", "credit", "description", "customer_id",
                 "supplier_id", "created_at"],
    },
    "accounts": {
        "desc": "CHART OF ACCOUNTS (codes, names, types)",
        "cols": ["code", "name", "account_type", "normal_balance",
                 "is_active", "is_control_account"],
    },
    # ---- PARTIES module -----------------------------------------------
    "customers": {
        "desc": "CUSTOMER masters",
        "cols": ["customer_code", "name", "is_active", "credit_limit",
                 "created_at"],
    },
    "suppliers": {
        "desc": "SUPPLIER masters",
        "cols": ["supplier_code", "name", "is_active", "credit_limit",
                 "created_at"],
    },
}

# Pseudo-columns: REAL values the executor derives (never fetched raw).
# journal_lines stores account_id (uuid); the planner thinks in account
# CODES/TYPES ("sum credits on REVENUE accounts") - the system resolves the
# join deterministically. They are excluded from the DB select and evaluated
# in Python after the join.
PSEUDO_COLS: Dict[str, set] = {
    "journal_lines": {"account_code", "account_type"},
}



_QUESTION_RE = re.compile(
    r"^\s*(how\s+much|how\s+many|what\s+is|what'?s\s+my|what\s+are|show\s+me|"
    r"list|report|balance|total|which)\b", re.I,
)
_IMPERATIVE_RE = re.compile(
    r"\b(record|create|add|book|register|pay|send|issue|delete|mark)\b", re.I,
)


def _pattern_gate(question: str) -> bool:
    """Pure pattern: question-form AND NOT an imperative. No flags - this is
    the ROUTING judgement, independent of feature availability."""
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


def analytics_gate(question: str) -> bool:
    """Deterministic gate (feature switch + pattern) - kept as the direct
    contract and as the documented fallback shape."""
    from app.config import get_settings

    if not getattr(get_settings(), "analytics_agent_enabled", False):
        return False
    return _pattern_gate(question)


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
    if shape not in ("table", "timeseries", "single_value", "list",
                     "computed"):
        return None, [f"unknown answer_shape {shape!r}"]
    formula = "op1_minus_op2"
    if shape == "computed":
        # Cross-checks: exactly two aggregations, whitelisted formula.
        # (The profit recipe: op1 - op2, computed HERE, never by the model.)
        formula = str(payload.get("formula") or "op1_minus_op2")
        if formula not in _FORMULAS:
            return None, [f"unknown formula {formula!r}"]
        if len(ops) != 2:
            return None, ["computed needs exactly 2 operations"]
        if not all(isinstance(o, dict) and o.get("aggregate") for o in ops):
            return None, ["computed needs an aggregate in both operations"]
        # Deterministic floor for the profit recipe: each journal_lines op
        # MUST pin an account_type (REVENUE/EXPENSE). Without it, summing
        # credits vs debits across ALL lines is the balance identity
        # (always zero) - caught live 2026-10-20 when the model skipped
        # the recipe's filter.
        for i, o in enumerate(ops):
            if str(o.get("source") or "") != "journal_lines":
                continue
            pinned = any(
                str(f.get("col") or "") == "account_type"
                and str(f.get("op") or "") == "eq"
                and str(f.get("value") or "").upper() in ("REVENUE", "EXPENSE")
                for f in (o.get("filters") or [])
            )
            if not pinned:
                return None, [
                    f"op{i}: computed profit needs a filter "
                    "col=account_type op=eq value=REVENUE (op1) or "
                    "EXPENSE (op2) on journal_lines"
                ]
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
        cols_ok = set(spec["cols"]) | PSEUDO_COLS.get(src, set())
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
    return {"operations": clean, "answer_shape": shape,
            "formula": formula}, []



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
    "You plan READ-ONLY accounting queries over the business's database "
    "modules (Sales, Purchases, Returns, Inventory, Payments, Journal, "
    "Parties). Reply with ONLY JSON:\n"
    '{"operations": [{"source": "<catalog source>", '
    '"columns": ["<col>", ...] or ["*"], '
    '"filters": [{"col": "<col>", "op": "eq|neq|ilike|gte|lte|between|in", '
    '"value": <scalar or [a,b]>}], '
    '"aggregate": "sum|count|avg|min|max"|null, "column": "<col for '
    'aggregate>", "order": "<col> asc|desc"|null, "limit": <int<=200>}], '
    '"answer_shape": "table|timeseries|single_value|list|computed", '
    '"formula": "op1_minus_op2"}\n'
    "RULES: at most 3 operations; use explicit dates (YYYY-MM-DD) derived "
    "from TODAY; never invent columns; *_id columns reference another "
    "source - plan a second operation for names if needed; pick the "
    "NARROWEST query that answers the question (targeted path, minimal "
    "rows).\n"
    "FORMULA (only for answer_shape computed): exactly two aggregate "
    "operations; the system subtracts op2 from op1 in Python "
    "(op1_minus_op2). Never use computed for anything else.\n"
    "MODULE RECIPES (targeted paths - pick the one matching the question):\n"
    "- PROFIT / LOSS / earnings for a period: op1 = journal_lines, "
    "aggregate sum, column credit, filter account_type eq REVENUE plus the "
    "date filters; op2 = journal_lines, aggregate sum, column debit, filter "
    "account_type eq EXPENSE plus the same date filters; answer_shape "
    "computed, formula op1_minus_op2. (account_code/account_type are "
    "resolved automatically against the chart.) NEVER compute profit by "
    "summing ALL credits vs ALL debits - that is the balance identity and "
    "always equals zero; the account_type filter is mandatory.\n"
    "- DOCUMENT-DATE periods (this month / since DATE): prefer document "
    "modules with their own dates - invoices.invoice_date, "
    "purchase_bills.bill_date, credit_notes.credit_note_date, "
    "purchase_returns.return_date, payments.payment_date, "
    "inventory_movements.movement_date, journal_entries.transaction_date.\n"
    "- RETURNS: sales returns = credit_notes (+credit_note_items); purchase "
    "returns/debit notes = purchase_returns (+purchase_return_items).\n"
    "- INVENTORY on hand: products (is_stock_tracked) + inventory_movements "
    "per product.\n"
    "Use computed ONLY for two-aggregate differences like profit."
)

_SYNTH_RULES = (
    "You shape a STRUCTURED answer from REAL rows. Reply with ONLY JSON:\n"
    '{"headline": "<one sentence using ONLY numbers present in the data>", '
    '"answer_type": "table|timeseries|single_value|list", '
    '"caveats": ["<short honest note>", ...]}\n'
    "RULES: never invent or round numbers away from the data; if a result "
    "set is empty say 'no records' plainly; mention the period covered; "
    "never echo, prefix, or re-attach the user's question in the headline."
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


async def _enrich_pseudo_cols(*, source: str, rows: List[Dict[str, Any]],
                              organization_id: Any) -> List[Dict[str, Any]]:
    """Deterministic join: journal_lines.account_id -> account_code/type.

    Lets the planner think in ACCOUNT CODES/TYPES (\"sum credits on
    REVENUE accounts\") while the DB stays the single source of truth.
    Org-scoped like every other read; never raises."""
    if source != "journal_lines" or not rows:
        return rows
    try:
        from app.database import fetch_many

        ids = {str(r.get("account_id")) for r in rows if r.get("account_id")}
        amap: Dict[str, Dict[str, Any]] = {}
        if ids:
            accounts = await fetch_many(
                "accounts",
                filters={"organization_id": str(organization_id)},
                select="id,code,account_type", limit=500,
            ) or []
            for a in accounts:
                if str(a.get("id")) in ids:
                    amap[str(a["id"])] = a
        for r in rows:
            acct = amap.get(str(r.get("account_id")) or "")
            r["account_code"] = (acct or {}).get("code")
            r["account_type"] = (acct or {}).get("account_type")
    except Exception as exc:  # noqa: BLE001 - enrichment must never break a read
        log.warning("analytics.pseudo_join_failed", error=str(exc)[:160])
    return rows


async def execute_plan(*, organization_id, plan: Dict[str, Any]) -> List[Any]:
    """Run the validated plan org-scoped. Returns one result per op.

    SEAM CONTRACT: app.database.fetch_many applies filters as PLAIN
    equality only (supabase-py .eq) - operator strings like "eq.x"/"gte.x"
    would be sent as literal values (production bug caught by the live
    E2E run, 2026-10-18). So: equality filters pass through as plain
    values; every OTHER operator is fetched wide and applied in Python.
    """
    from app.database import fetch_many

    results = []
    for op in plan["operations"]:
        # ORG SCOPE INJECTED BY PYTHON - the model can never widen it.
        filters: Dict[str, Any] = {"organization_id": str(organization_id)}
        pseudo = PSEUDO_COLS.get(op["source"], set())
        noneq = []
        for f in op["filters"]:
            # Pseudo-cols are NEVER sent to the database - always Python-side
            # (after the account join below).
            if f["op"] == "eq" and f["col"] not in pseudo:
                filters[f["col"]] = f["value"]
            else:
                noneq.append(f)
        fetch_limit = MAX_LIMIT if noneq else op["limit"]
        # The seam must SEE every column the Python-side filters/sort use - a
        # select of ["total"] plus a bill_date filter trimmed every row (live
        # E2E catch, 2026-10-18). Pseudo-cols are excluded - they are not DB
        # columns and PostgREST would reject them.
        needed = {c for c in op["columns"] if c != "*" and c not in pseudo}
        needed.update(f["col"] for f in op["filters"] if f["col"] not in pseudo)
        if pseudo:
            # The join key MUST be selected or the enrichment sees no
            # account_id and every row filters to nothing (live catch
            # 2026-10-20: profit returned 0 rows with a correct plan).
            needed.add("account_id")
        order_col = op["order"].split()[0].split(".")[0] if op["order"] else ""
        if op["order"] and order_col not in pseudo:
            needed.add(order_col)
        select = ",".join(sorted(needed)) or "*"
        rows = await fetch_many(
            op["source"], filters=filters, select=select,
            order=_norm_order(op["order"]) if order_col not in pseudo else None,
            limit=fetch_limit,
        ) or []
        if pseudo:
            rows = await _enrich_pseudo_cols(
                source=op["source"], rows=rows,
                organization_id=organization_id,
            )
        rows = _apply_noneq(rows, noneq)[: op["limit"]]
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


def _norm_order(order: Optional[str]) -> Optional[str]:
    """Planner emits 'col asc|desc' (prompt format); the fetch_many seam
    expects 'col.direction'. Live E2E catch, 2026-10-18."""
    if not order:
        return None
    parts = str(order).replace(".", " ").split()
    col = parts[0]
    direction = parts[1].lower() if len(parts) > 1 else "asc"
    if direction not in ("asc", "desc"):
        direction = "asc"
    return f"{col}.{direction}"


def _apply_noneq(rows: List[Dict[str, Any]],
                 ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Non-equality operators, evaluated in Python over the fetched rows."""
    out = rows
    for f in ops:
        col, op, val = f["col"], f["op"], f["value"]

        def _num(v: Any) -> Optional[float]:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        if op == "eq":
            # Pseudo-col equality (account_type on journal_lines) lands
            # here - the DB can never answer it. Live catch 2026-10-20:
            # without this branch the profit plan's REVENUE/EXPENSE pin
            # was silently IGNORED and every line was counted.
            out = [r for r in out if str(r.get(col)) == str(val)]
        elif op == "neq":
            out = [r for r in out if str(r.get(col)) != str(val)]
        elif op == "ilike":
            needle = str(val).strip("%").lower()
            out = [r for r in out
                   if needle in str(r.get(col) or "").lower()]
        elif op == "gte":
            nv = _num(val)
            out = [r for r in out if (nv is not None and _num(r.get(col)) is not None
                   and _num(r.get(col)) >= nv)
                   or str(r.get(col) or "") >= str(val)]
        elif op == "lte":
            nv = _num(val)
            out = [r for r in out if (nv is not None and _num(r.get(col)) is not None
                   and _num(r.get(col)) <= nv)
                   or str(r.get(col) or "") <= str(val)]
        elif op == "in":
            allowed = {str(x) for x in (val if isinstance(val, list) else [val])}
            out = [r for r in out if str(r.get(col)) in allowed]
        elif op == "between" and isinstance(val, list) and len(val) == 2:
            out = [r for r in out if str(val[0]) <= str(r.get(col) or "")
                   <= str(val[1])]
    return out





def _data_numbers(results: List[Any]) -> set:
    """Every number the answer is ALLOWED to mention."""
    nums: set = set()

    def _walk(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            nums.add(round(float(v), 2))
        elif isinstance(v, str):
            # Extract numbers from codes like JE-000235, AST-000027, INV-000029, 1001, etc.
            for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", v):
                try:
                    nums.add(round(float(m.group(0).replace(",", "")), 2))
                except ValueError:
                    pass
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, list):
            for x in v:
                _walk(x)

    _walk(results)
    # Natural language counters: row counts (0-50) and recent years (2020-2030)
    for c in range(51):
        nums.add(float(c))
    for y in range(2020, 2031):
        nums.add(float(y))
    return nums


def _headline_numbers_ok(headline: str, allowed: set) -> bool:
    """Guard: every >=3-decimal number in the headline must exist in the
    data (ISO dates 2026-10-01 and document codes JE-000235 are exempt)."""
    text = re.sub(r"\d{4}-\d{2}-\d{2}", "", headline or "")
    # Exempt document codes like JE-000235, INV-000029, BILL-000036
    text = re.sub(r"\b[A-Za-z]{2,}[-_]\d+\b", "", text)
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
    """Deterministic renderer - works with ZERO LLM availability.
    Speaks directly to the findings WITHOUT re-attaching or echoing the user's query."""
    parts = []
    for r in results:
        if "aggregate" in r:
            parts.append(f"{r['aggregate']} of {r.get('column') or 'rows'} is "
                         f"{_money(r.get('value'))} across {r['row_count']} "
                         f"entries")
        else:
            parts.append(f"{r.get('source')}: {r['row_count']} entries")
    headline = "; ".join(parts) if parts else "No entries found."
    return {
        "headline": headline,
        "answer_type": "table",
        "caveats": ["We could not phrase this in one sentence, so the raw "
                    "totals are listed above - they are read straight from "
                    "your books."],
        "synth": "fallback",
    }



def _money(v: Any) -> str:
    """User-facing money: thousands separators, two decimals (never the raw
    float repr ``1047000.0`` a business owner has to squint at)."""
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _human_ts(iso: Any) -> str:
    """``2026-10-19T20:25:08+00:00`` -> ``20 Oct 2026, 2:25 AM UTC``.
    Unparseable input passes through untouched (never raises)."""
    from datetime import datetime as _dt

    try:
        dt = _dt.fromisoformat(str(iso))
        day = f"{dt.day} {dt.strftime('%b %Y')}"
        clock = dt.strftime("%I:%M %p").lstrip("0")
        return f"{day}, {clock} UTC"
    except (TypeError, ValueError):
        return str(iso or "?")


def _op_label(op: Dict[str, Any]) -> Optional[str]:
    """Human label for an op, grounded in its VALIDATED plan filters: the
    account_type it pins (REVENUE -> 'Revenue', EXPENSE -> 'Expenses').
    Never invented - falls back to None so the caller can use the column."""
    for f in op.get("filters") or []:
        if not isinstance(f, dict):
            continue
        if f.get("col") == "account_type" and f.get("op") == "eq":
            t = str(f.get("value") or "").strip().upper()
            if t == "REVENUE":
                return "Revenue"
            if t == "EXPENSE":
                return "Expenses"
            if t:
                return t.capitalize()
    return None


def _computed_answer(*, question: str, results: List[Any],
                     formula: Optional[str] = "op1_minus_op2",
                     labels: Optional[List[Optional[str]]] = None
                     ) -> Dict[str, Any]:
    """Deterministic two-aggregate arithmetic (profit = op1 - op2).

    The arithmetic happens HERE, never in the model. A wrong-shaped result
    falls back honestly - no number is ever invented. The headline speaks the
    business owner's language (Revenue/Expenses, formatted money) - the
    credit/debit column names and the arithmetic provenance are NOT user
    vocabulary (live complaint 2026-10-20)."""
    if (formula != "op1_minus_op2" or len(results) != 2
            or any("aggregate" not in r for r in results)):
        log.warning("analytics.computed_bad_shape")
        return _fallback_answer(question, results)
    try:
        a = float(results[0].get("value") or 0)
        b = float(results[1].get("value") or 0)
    except (TypeError, ValueError):
        return _fallback_answer(question, results)
    diff = round(a - b, 2)
    kind = "Profit" if diff >= 0 else "Loss"
    r1, r2 = results[0], results[1]
    labels = labels or [None, None]
    lab1 = (labels[0] if len(labels) > 0 else None) or r1.get("column") \
        or r1.get("source") or "the first total"
    lab2 = (labels[1] if len(labels) > 1 else None) or r2.get("column") \
        or r2.get("source") or "the second total"
    headline = (
        f"{kind} of {_money(abs(diff))} - {lab1} {_money(a)} "
        f"minus {lab2} {_money(b)}"
    )
    return {
        "headline": headline,
        "answer_type": "single_value",
        "caveats": ["Calculated directly from your posted ledger entries - "
                    "nothing estimated."],
        "synth": "computed",
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
        if plan.get("answer_shape") == "computed":
            # Deterministic arithmetic path (profit/loss) - no model call
            # needed for the difference; Python already has both numbers.
            # Labels come from the plan's account_type pins (Revenue /
            # Expenses) so the headline speaks business, not credit/debit.
            _op_labels = [
                _op_label(o) or o.get("column") or o.get("source")
                for o in plan["operations"]
            ]
            synth = _computed_answer(
                question=question, results=results,
                formula=plan.get("formula"), labels=_op_labels,
            )
        else:
            _op_labels = None
            synth = await synthesize(question=question, results=results,
                                     today=today, client=client, timeout=t)
        answer = {
            "headline": synth["headline"],
            "answer_type": synth["answer_type"],
            "results": results,
            "op_labels": _op_labels,
            "caveats": synth["caveats"],
            "period": today,
            "data_as_of": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "synth": synth["synth"],
        }
        audit["llm"] = {"llm": "ok", "computed": "computed"}.get(
            synth["synth"], "fallback")
        audit["plan"] = plan
        return {"answer": answer, "audit": audit}
    except Exception as exc:  # noqa: BLE001 - analytics never breaks a turn
        audit["llm"] = "failed"
        audit["error"] = str(exc)[:200]
        log.warning("analytics.failed", error=str(exc)[:200])
        return {"answer": None, "audit": audit}



def render_markdown(answer: Dict[str, Any]) -> str:
    """Deterministic card rendering for the chat summary.

    MARKDOWN-FREE by design: the chat card renders this into a plain text
    node with no markdown engine, so raw `**`, backticks and `_` markers were
    reaching the user verbatim ("**Loss: ...**", live complaint 2026-10-20).
    Emphasis is carried by wording and line structure instead of markup. The
    function name is kept (historical import contract) but the OUTPUT is
    clean display text."""
    labels = answer.get("op_labels") or []
    agg_i = 0
    lines = [answer.get("headline", ""), ""]
    for r in answer.get("results") or []:
        if "aggregate" in r:
            # Human label from the plan (Revenue/Expenses) when available;
            # otherwise the aggregate + column in plain words.
            label = None
            if agg_i < len(labels):
                label = labels[agg_i]
            agg_i += 1
            what = label or f"{r.get('aggregate')} of {r.get('column')}"
            rows = r.get("row_count", 0)
            lines.append(f"{what}: {_money(r.get('value'))} across {rows} "
                         f"entries")
        else:
            rows = r.get("rows") or []
            lines.append(f"{r.get('source')}: {r.get('row_count')} entries")
            if rows:
                cols = list(rows[0].keys())[:6]
                lines.append("  " + " | ".join(cols))
                for row in rows[:20]:
                    lines.append("  " + " | ".join(
                        str(row.get(c, ""))[:40] for c in cols))
    if answer.get("caveats"):
        lines.append("")
        lines.extend(answer["caveats"])
    lines.append(f"Data as of {_human_ts(answer.get('data_as_of'))}")
    return "\n".join(lines)



# ---------------------------------------------------------------------------
# LLM-FIRST ROUTING: the model classifies EVERY message; the deterministic
# gate above is only the FALLBACK (flag off / provider down / invalid reply).
# ---------------------------------------------------------------------------

_ROUTER_RULES = (
    "You are a message ROUTER for an accounting app. Reply with ONLY JSON:\n"
    '{"route": "analytics" | "record" | "clarify", '
    '"reason": "<one short sentence>", '
    '"question": "<one targeted clarifying question>" }\n'
    'RULES: "analytics" = the user ASKS about data that already exists '
    '(reporting, totals, lists, balances; past-tense questions like '
    '"how much did I pay X"): they want an ANSWER and nothing may be '
    'recorded. "record" = the user clearly states or commands a BUSINESS '
    'TRANSACTION to be recorded or modified (bought, sold, paid, create, '
    'invoice, expense...): nature/accounts will be identified and it '
    'recorded with confirmation. "clarify" = ONLY when the message is '
    'genuinely torn between the two, too vague to act on, or mixes both '
    'intents: ask ONE targeted question that names the competing readings '
    'and resolves ALL ambiguity at once, so the next answer settles the '
    'route with certainty. Never ask rhetorical or multi-part questions; '
    'never use "clarify" for a clear message; question is "" unless '
    'route is "clarify".'
)


async def route_message(
    *,
    question: str,
    client: Any = None,
    timeout: Optional[float] = None,
) -> tuple:
    """LLM-first routing for every user message ->
    ("analytics"|"record"|"clarify", audit).  Uncertainty does NOT guess:
    the model asks ONE targeted clarifying question (audit carries it).
    Never raises; falls back to the deterministic gate on flag-off,
    provider failure, or an invalid reply - routing NEVER blocks a turn.
    """
    from app.config import get_settings

    settings = get_settings()
    gate = "analytics" if _pattern_gate(question) else "record"
    audit: Dict[str, Any] = {"stage": "routing", "source": "fallback_gate"}
    if not getattr(settings, "llm_router_enabled", False):
        return gate, audit
    try:
        if client is None:
            from app.ai_orchestrator import get_client

            client = get_client()
        t = timeout or getattr(settings, "llm_router_timeout", 6.0)
        raw = await asyncio.wait_for(
            client.generate_text_light(prompt=(
                f"{_ROUTER_RULES}\n\nMESSAGE: {(question or '')[:1500]}"
            )),
            timeout=t,
        )
        payload = _extract_json(str(raw or ""))
        route = str((payload or {}).get("route") or "").strip().lower()
        if route in ("analytics", "record"):
            audit = {
                "stage": "routing", "source": "llm", "route": route,
                "reason": str((payload or {}).get("reason") or "")[:160],
            }
            return route, audit
        if route == "clarify":
            target = str((payload or {}).get("question") or "").strip()
            if 10 <= len(target) <= 500:
                audit = {
                    "stage": "routing", "source": "llm", "route": "clarify",
                    "reason": str((payload or {}).get("reason") or "")[:160],
                    "question": target,
                }
                return "clarify", audit
            log.warning("routing.clarify_without_question")
        audit["source"] = "fallback_gate_invalid_reply"
    except Exception as exc:  # noqa: BLE001 - routing never breaks a turn
        audit["source"] = "fallback_gate_unavailable"
        audit["error"] = str(exc)[:160]
        log.warning("routing.llm_unavailable", error=str(exc)[:160])
    return gate, audit

