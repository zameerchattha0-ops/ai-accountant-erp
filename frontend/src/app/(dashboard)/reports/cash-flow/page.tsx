"use client";

import { useEffect, useMemo, useState } from "react";
import { Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import {
  computeCategoryTotals,
  fetchCashFlowRows,
  loadCashFlowSummary,
  netOf,
  type CashFlowRow,
  type CategoryTotals,
} from "@/lib/reports/cash-flow";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import { ErrorState, TableSkeleton, EmptyState } from "@/components/shared/States";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

type Category = "OPERATING" | "INVESTING" | "FINANCING";

const CATEGORY_META: Record<Category, { label: string; color: string; bg: string }> = {
  OPERATING:   { label: "Operating",   color: "text-info-700",     bg: "bg-info-50" },
  INVESTING:   { label: "Investing",   color: "text-warning-700",  bg: "bg-warning-50" },
  FINANCING:   { label: "Financing",   color: "text-ai-700",       bg: "bg-ai-50" },
};

export default function CashFlowReportPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<CashFlowRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<"ALL" | Category>("ALL");
  // Period scope — defaults to the CURRENT reporting year (shown as editable
  // date inputs, consistent with the P&L's reporting-year scoping).
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [truncated, setTruncated] = useState(false);
  // Exact category totals from one SQL aggregate (migration 090); null while
  // unavailable → see the fallback rules below.
  const [sqlTotals, setSqlTotals] = useState<CategoryTotals | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  // Default the range to the current financial year, once it resolves.
  useEffect(() => {
    if (!org) return;
    let alive = true;
    createClient()
      .from("financial_years")
      .select("start_date, end_date")
      .eq("organization_id", org.organization_id)
      .eq("is_current", true)
      .maybeSingle()
      .then(({ data }) => {
        if (alive && data) {
          setFromDate((v) => v || data.start_date);
          setToDate((v) => v || data.end_date);
        }
      });
    return () => {
      alive = false;
    };
  }, [org]);

  // Load the movements (chunked, bounded, ABORTABLE) and the exact SQL totals
  // in parallel. No silent 500-row cap — the old page summed whatever it had
  // fetched, which made the statement wrong past 500 rows (audit B3, P0).
  useEffect(() => {
    if (!org) return;
    let alive = true;
    const controller = new AbortController();
    const supabase = createClient();
    const opts = {
      from: fromDate || null,
      to: toDate || null,
      signal: controller.signal,
    };
    Promise.allSettled([
      fetchCashFlowRows(supabase, org.organization_id, opts),
      loadCashFlowSummary(supabase, org.organization_id, opts),
    ]).then(([rowsResult, totalsResult]) => {
      if (!alive) return;
      if (rowsResult.status === "rejected") {
        const err = rowsResult.reason as { name?: string; message?: string };
        if (err?.name === "AbortError") return;
        setError(err?.message ?? "Couldn't load the cash flow statement");
        return;
      }
      setRows(rowsResult.value.rows);
      setTruncated(rowsResult.value.truncated);
      setSqlTotals(totalsResult.status === "fulfilled" ? totalsResult.value : null);
      setError(null);
    });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [org, fromDate, toDate, reloadTick]);

  // Totals policy: exact SQL aggregate > sum of a COMPLETE load > nothing.
  // A partial load must never produce a partial number (show "—" instead).
  const fallbackTotals =
    rows !== null && !truncated ? computeCategoryTotals(rows) : null;
  const categoryTotals = sqlTotals ?? fallbackTotals;
  const netCashFlow = categoryTotals ? netOf(categoryTotals) : null;
  const totalsResolved = sqlTotals !== null || rows !== null;

  const filtered = useMemo(
    () =>
      activeCategory === "ALL"
        ? (rows ?? [])
        : (rows ?? []).filter((r) => r.cash_flow_category === activeCategory),
    [rows, activeCategory]
  );

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Cash Flow Statement"
        subtitle="Classified by operating, investing, and financing activities"
        actions={
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-bg-surface border border-border-subtle text-sm font-medium text-text-secondary hover:text-text-primary hover:border-ai-200 transition-colors"
          >
            <Printer className="w-4 h-4" /> Print
          </button>
        }
      />

      {/* Period scope — defaults to the current reporting year; editable.
          Screen-only: date pickers have no place on paper. */}
      <div className="flex flex-wrap items-end gap-3 print:hidden">
        <div>
          <label htmlFor="cf-from" className="text-xs font-medium text-text-secondary">From</label>
          <input id="cf-from" type="date" className={`${inputCls} w-40 mt-1.5`} value={fromDate}
            onChange={(e) => setFromDate(e.target.value)} />
        </div>
        <div>
          <label htmlFor="cf-to" className="text-xs font-medium text-text-secondary">To</label>
          <input id="cf-to" type="date" className={`${inputCls} w-40 mt-1.5`} value={toDate}
            onChange={(e) => setToDate(e.target.value)} />
        </div>
        {(fromDate || toDate) && (
          <button
            onClick={() => { setFromDate(""); setToDate(""); }}
            className="px-3 py-2 rounded-xl text-xs font-medium text-text-secondary hover:text-text-primary border border-border-subtle bg-bg-surface transition-colors mb-0.5"
          >
            All time
          </button>
        )}
      </div>

      {truncated && (
        <div className="rounded-xl bg-warning-50 border border-warning-200 px-4 py-3 text-xs text-warning-700 print:hidden">
          Showing the most recent {(rows ?? []).length.toLocaleString()} movements in
          this range{sqlTotals
            ? " — category totals above are complete."
            : " — narrow the dates: totals cannot be verified for the whole period until migration 090 is applied."}
        </div>
      )}

      {/* Category summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        {(["OPERATING", "INVESTING", "FINANCING"] as Category[]).map((cat) => {
          const meta = CATEGORY_META[cat];
          const total = categoryTotals?.[cat] ?? null;
          return (
            <button
              key={cat}
              onClick={() => setActiveCategory(activeCategory === cat ? "ALL" : cat)}
              className={`bg-bg-surface rounded-2xl border px-5 py-4 text-left transition-all ${
                activeCategory === cat
                  ? "border-ai-300 ring-2 ring-ai-100"
                  : "border-border-subtle hover:border-border-default"
              }`}
            >
              <p className={`text-[11px] uppercase tracking-wide font-medium ${meta.color}`}>{meta.label}</p>
              <p className={`text-xl font-semibold tabular-nums mt-1 ${(total ?? 0) >= 0 ? "text-text-primary" : "text-error-600"}`}>
                {total !== null
                  ? formatCurrency(total, org?.base_currency_code)
                  : totalsResolved
                    ? "—"
                    : "…"}
              </p>
            </button>
          );
        })}
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Net Cash Flow</p>
          <p className={`text-xl font-semibold tabular-nums mt-1 ${(netCashFlow ?? 0) >= 0 ? "text-success-600" : "text-error-600"}`}
            title={netCashFlow === null && totalsResolved
              ? "Totals unavailable for this range — narrow the dates or apply migration 090"
              : undefined}>
            {netCashFlow !== null
              ? formatCurrency(netCashFlow, org?.base_currency_code)
              : totalsResolved
                ? "—"
                : "…"}
          </p>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex gap-2">
        <button
          onClick={() => setActiveCategory("ALL")}
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
            activeCategory === "ALL"
              ? "bg-ai-500 text-white"
              : "bg-bg-muted text-text-secondary hover:text-text-primary"
          }`}
        >
          All
        </button>
        {(["OPERATING", "INVESTING", "FINANCING"] as Category[]).map((cat) => {
          const meta = CATEGORY_META[cat];
          return (
            <button
              key={cat}
              onClick={() => setActiveCategory(activeCategory === cat ? "ALL" : cat)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                activeCategory === cat
                  ? "bg-ai-500 text-white"
                  : `bg-bg-muted text-text-secondary hover:text-text-primary`
              }`}
            >
              {meta.label}
            </button>
          );
        })}
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton cols={7} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => setReloadTick((t) => t + 1)} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={fromDate || toDate ? "No cash movements in this period" : "No cash flow data"}
          hint="Cash flow entries appear once journal entries involving bank/cash accounts are posted. Record a receipt or payment first."
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Journal</th>
                <th className="px-4 py-3 font-medium">Category</th>
                <th className="px-4 py-3 font-medium">Cash Account</th>
                <th className="px-4 py-3 font-medium">Contra Account</th>
                <th className="px-4 py-3 font-medium text-right">Net Amount</th>
                <th className="px-4 py-3 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => {
                const meta = CATEGORY_META[r.cash_flow_category] ?? CATEGORY_META.OPERATING;
                return (
                  <tr key={`${r.journal_entry_id}-${r.cash_account_id}-${i}`}
                    className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                    <td className="px-4 py-3 text-text-secondary tabular-nums">{r.transaction_date}</td>
                    <td className="px-4 py-3 text-text-secondary text-xs">{r.journal_number}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${meta.bg} ${meta.color}`}>
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-text-primary text-xs">
                      <span className="text-text-muted">{r.cash_account_code}</span> {r.cash_account_name}
                    </td>
                    <td className="px-4 py-3 text-text-primary text-xs">
                      <span className="text-text-muted">{r.contra_account_code}</span> {r.contra_account_name}
                    </td>
                    <td className={`px-4 py-3 text-right tabular-nums font-medium ${
                      Number(r.net_amount) >= 0 ? "text-success-600" : "text-error-600"
                    }`}>
                      {formatCurrency(Number(r.net_amount), org?.base_currency_code)}
                    </td>
                    <td className="px-4 py-3 text-text-secondary text-xs max-w-[200px] truncate">
                      {r.entry_description}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
