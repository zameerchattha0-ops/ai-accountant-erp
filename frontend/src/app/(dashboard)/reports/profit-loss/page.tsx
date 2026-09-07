"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";
import type { StatementRow } from "@/lib/types/entities";

interface StatementEntry {
  account_code: string;
  account_name: string;
  display: number;
}

function Section({
  title,
  entries,
  total,
  totalLabel,
  currency,
}: {
  title: string;
  entries: StatementEntry[];
  total: number;
  totalLabel: string;
  currency?: string;
}) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
      <div className="px-4 py-3 bg-bg-muted/60 border-b border-border-subtle">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {entries.length === 0 ? (
            <tr>
              <td className="px-4 py-4 text-text-muted text-xs">No activity yet</td>
              <td className="px-4 py-4" />
            </tr>
          ) : (
            entries.map((r) => (
              <tr key={r.account_code} className="border-b border-border-subtle/60 last:border-0">
                <td className="px-4 py-2.5">
                  <span className="tabular-nums text-text-secondary mr-2 text-xs">{r.account_code}</span>
                  <span className="text-text-primary">{r.account_name}</span>
                </td>
                <td className="px-4 py-2.5 text-right text-text-primary tabular-nums w-40">
                  {formatCurrency(r.display, currency)}
                </td>
              </tr>
            ))
          )}
          <tr className="border-t-2 border-border-default bg-bg-muted/50">
            <td className="px-4 py-3 font-semibold text-text-primary">{totalLabel}</td>
            <td className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
              {formatCurrency(total, currency)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function ProfitLossPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<StatementRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .rpc("get_income_statement", { target_org: org.organization_id });
    // Sort client-side by account code (RPC result, reporting-year scoped).
    const sorted = [...(data ?? [])].sort((a, b) =>
      String(a.account_code).localeCompare(String(b.account_code))
    );
    if (dbError) setError(dbError.message);
    else setRows(sorted as StatementRow[]);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  // net_amount = debit - credit. Revenue is credit-normal (negative) → flip sign for display.
  const { revenueRows, expenseRows, totalRevenue, totalExpenses } = useMemo(() => {
    const all = rows ?? [];
    const revenueRows = all
      .filter((r) => r.account_type === "REVENUE" && Math.abs(r.net_amount) > 0.005)
      .map((r) => ({ ...r, display: -r.net_amount }));
    const expenseRows = all
      .filter((r) => r.account_type === "EXPENSE" && Math.abs(r.net_amount) > 0.005)
      .map((r) => ({ ...r, display: r.net_amount }));
    return {
      revenueRows,
      expenseRows,
      totalRevenue: revenueRows.reduce((s, r) => s + r.display, 0),
      totalExpenses: expenseRows.reduce((s, r) => s + r.display, 0),
    };
  }, [rows]);

  const netProfit = totalRevenue - totalExpenses;
  const currency = org?.base_currency_code;
  const hasActivity = revenueRows.length > 0 || expenseRows.length > 0;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <PageHeader
        title="Profit & Loss"
        subtitle="Revenue and expenses since your books began (posted entries only)"
        logoUrl={org?.logo_url}
        actions={
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-bg-surface border border-border-subtle text-sm font-medium text-text-secondary hover:text-text-primary hover:border-ai-200 transition-colors"
          >
            <Printer className="w-4 h-4" /> Print
          </button>
        }
      />

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton rows={8} cols={2} />
      ) : error ? (
        <ErrorState message={error} />
      ) : !hasActivity ? (
        <EmptyState
          title="No income or expense activity yet"
          hint="Record transactions via the AI agent or the Journal page - revenue and expenses will appear here."
        />
      ) : (
        <>
          <Section
            title="Revenue"
            entries={revenueRows}
            total={totalRevenue}
            totalLabel="Total Revenue"
            currency={currency}
          />
          <Section
            title="Expenses"
            entries={expenseRows}
            total={totalExpenses}
            totalLabel="Total Expenses"
            currency={currency}
          />

          <div className={cn(
            "flex items-center justify-between rounded-2xl px-5 py-4 border",
            netProfit >= 0
              ? "bg-success-50 border-success-200"
              : "bg-error-50 border-error-200"
          )}>
            <div>
              <p className="text-sm font-semibold text-text-primary">
                {netProfit >= 0 ? "Net Profit" : "Net Loss"}
              </p>
              <p className="text-xs text-text-secondary mt-0.5">
                Total revenue minus total expenses
              </p>
            </div>
            <p className={cn(
              "text-2xl font-semibold tabular-nums",
              netProfit >= 0 ? "text-success-700" : "text-error-700"
            )}>
              {formatCurrency(netProfit, currency)}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
