"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import { ErrorState, TableSkeleton, EmptyState } from "@/components/shared/States";
import type { CashFlowRow } from "@/lib/types/entities";

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

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("v_cash_flow")
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("transaction_date", { ascending: false })
      .limit(500);
    if (dbError) setError(dbError.message);
    else setRows((data as CashFlowRow[]) ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  // Compute per-category totals
  const categoryTotals = useMemo(() => {
    const totals: Record<Category, number> = { OPERATING: 0, INVESTING: 0, FINANCING: 0 };
    (rows ?? []).forEach((r) => {
      totals[r.cash_flow_category] = (totals[r.cash_flow_category] ?? 0) + Number(r.net_amount);
    });
    return totals;
  }, [rows]);

  const netCashFlow = categoryTotals.OPERATING + categoryTotals.INVESTING + categoryTotals.FINANCING;

  const filtered = activeCategory === "ALL"
    ? (rows ?? [])
    : (rows ?? []).filter((r) => r.cash_flow_category === activeCategory);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader title="Cash Flow Statement" subtitle="Classified by operating, investing, and financing activities" />

      {/* Category summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        {(["OPERATING", "INVESTING", "FINANCING"] as Category[]).map((cat) => {
          const meta = CATEGORY_META[cat];
          const total = categoryTotals[cat];
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
              <p className={`text-xl font-semibold tabular-nums mt-1 ${total >= 0 ? "text-text-primary" : "text-error-600"}`}>
                {formatCurrency(total, org?.base_currency_code)}
              </p>
            </button>
          );
        })}
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Net Cash Flow</p>
          <p className={`text-xl font-semibold tabular-nums mt-1 ${netCashFlow >= 0 ? "text-success-600" : "text-error-600"}`}>
            {formatCurrency(netCashFlow, org?.base_currency_code)}
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
        <ErrorState message={error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No cash flow data"
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
