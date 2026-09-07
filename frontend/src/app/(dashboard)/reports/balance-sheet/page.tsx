"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Printer, XCircle } from "lucide-react";
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
  currentEarnings = 0,
}: {
  title: string;
  entries: StatementEntry[];
  total: number;
  totalLabel: string;
  currency?: string;
  currentEarnings?: number;
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
          {title === "Equity" && Math.abs(currentEarnings) > 0.005 && (
            <tr className="border-b border-border-subtle/60">
              <td className="px-4 py-2.5 text-text-secondary italic">Current earnings (this year)</td>
              <td className="px-4 py-2.5 text-right text-text-primary tabular-nums">
                {formatCurrency(currentEarnings, currency)}
              </td>
            </tr>
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

export default function BalanceSheetPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<StatementRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("v_balance_sheet")
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("account_code");
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  /*
   * net_amount = debit - credit per account.
   *   ASSET     → debit-normal  → display as-is
   *   LIABILITY → credit-normal → display -net_amount
   *   EQUITY    → credit-normal → display -net_amount
   * Current earnings (net profit) comes from the P&L view: revenue + expenses
   * in debit-credit terms; net profit = -(revenue_net + expense_net).
   */
  const { assets, liabilities, equity, totalAssets, totalLiabilities, totalEquityBase } =
    useMemo(() => {
      const all = rows ?? [];
      const flip = (r: StatementRow) => ({ ...r, display: -r.net_amount });
      const keep = (r: StatementRow) => ({ ...r, display: r.net_amount });
      const nz = (r: { net_amount: number }) => Math.abs(r.net_amount) > 0.005;
      const assets = all.filter((r) => r.account_type === "ASSET" && nz(r)).map(keep);
      const liabilities = all.filter((r) => r.account_type === "LIABILITY" && nz(r)).map(flip);
      const equity = all.filter((r) => r.account_type === "EQUITY" && nz(r)).map(flip);
      return {
        assets,
        liabilities,
        equity,
        totalAssets: assets.reduce((s, r) => s + r.display, 0),
        totalLiabilities: liabilities.reduce((s, r) => s + r.display, 0),
        totalEquityBase: equity.reduce((s, r) => s + r.display, 0),
      };
    }, [rows]);

  // Current earnings = -(revenue_net + expense_net) computed from the P&L view
  const [currentEarnings, setCurrentEarnings] = useState(0);
  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase
      .rpc("get_income_statement", { target_org: org.organization_id })
      .then(({ data }) => {
        const rows = (data ?? []) as { net_amount: number }[];
        const sum = rows.reduce(
          (s: number, r: { net_amount: number }) => s + r.net_amount,
          0
        );
        setCurrentEarnings(-sum);
      });
  }, [org, rows]);

  const currency = org?.base_currency_code;
  const totalEquity = totalEquityBase + currentEarnings;
  const rhs = totalLiabilities + totalEquity;
  const balanced = Math.abs(totalAssets - rhs) < 0.005;
  const hasActivity = rows !== null && rows.some((r) => Math.abs(r.net_amount) > 0.005);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <PageHeader
        title="Balance Sheet"
        subtitle="Assets, liabilities and equity - posted entries only, as of today"
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
          title="No balance sheet activity yet"
          hint="Record transactions via the AI agent or the Journal page - balances will build up here."
        />
      ) : (
        <>
          <Section title="Assets" entries={assets} total={totalAssets} totalLabel="Total Assets" currency={currency} />

          <div className="grid gap-6">
            <Section
              title="Liabilities"
              entries={liabilities}
              total={totalLiabilities}
              totalLabel="Total Liabilities"
              currency={currency}
            />
            <Section
              title="Equity"
              entries={equity}
              total={totalEquity}
              totalLabel="Total Equity"
              currency={currency}
              currentEarnings={currentEarnings}
            />
          </div>

          <div className="bg-bg-surface rounded-2xl border border-border-subtle p-5 space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">Total Assets</span>
              <span className="font-semibold text-text-primary tabular-nums">
                {formatCurrency(totalAssets, currency)}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">Liabilities + Equity</span>
              <span className="font-semibold text-text-primary tabular-nums">
                {formatCurrency(rhs, currency)}
              </span>
            </div>
            <div
              className={cn(
                "flex items-center gap-2 rounded-xl px-4 py-3 text-sm",
                balanced ? "bg-success-50 text-success-700" : "bg-error-50 text-error-700"
              )}
            >
              {balanced ? (
                <CheckCircle2 className="w-4 h-4" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              {balanced
                ? "The balance sheet balances."
                : `Out of balance by ${formatCurrency(totalAssets - rhs, currency)}. The database rejects unbalanced postings - this should never happen.`}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
