"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";
import {
  buildStatement,
  classifyRows,
  type PlStatementRow,
} from "@/lib/reports/pl-structure";

interface SectionEntry {
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
  deduction = false,
}: {
  title: string;
  entries: SectionEntry[];
  total: number;
  totalLabel: string;
  currency?: string;
  /** A deduction section renders its rows and total in parentheses. */
  deduction?: boolean;
}) {
  const shownTotal = deduction ? -Math.abs(total) : total;
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
              <tr key={`${r.account_code}-${r.account_name}`} className="border-b border-border-subtle/60 last:border-0">
                <td className="px-4 py-2.5">
                  <span className="tabular-nums text-text-secondary mr-2 text-xs">{r.account_code}</span>
                  <span className="text-text-primary">{r.account_name}</span>
                </td>
                <td className="px-4 py-2.5 text-right text-text-primary tabular-nums w-40">
                  {formatCurrency(deduction ? -Math.abs(r.display) : r.display, currency)}
                </td>
              </tr>
            ))
          )}
          <tr className="border-t-2 border-border-default bg-bg-muted/50">
            <td className="px-4 py-3 font-semibold text-text-primary">{totalLabel}</td>
            <td className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
              {formatCurrency(shownTotal, currency)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** A subtotal bar (Gross Profit / Operating Profit) between statement steps. */
function Subtotal({ label, value, currency }: { label: string; value: number; currency?: string }) {
  return (
    <div className="flex items-center justify-between rounded-2xl px-5 py-3.5 border border-border-default bg-bg-muted/60">
      <p className="text-sm font-semibold text-text-primary">{label}</p>
      <p className="text-lg font-semibold text-text-primary tabular-nums">
        {formatCurrency(value, currency)}
      </p>
    </div>
  );
}

export default function ProfitLossPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<PlStatementRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .rpc("get_income_statement", { target_org: org.organization_id });
    if (dbError) setError(dbError.message);
    else setRows((data ?? []) as PlStatementRow[]);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  // Classify rows into statement sections and compute every subtotal from
  // the SAME buckets (never independently — the totals can never disagree).
  const statement = useMemo(
    () => (rows ? buildStatement(classifyRows(rows)) : null),
    [rows]
  );

  const currency = org?.base_currency_code;
  const hasActivity = useMemo(() => {
    if (!statement) return false;
    return (
      Object.values(statement.sections).some((s) => s.rows.length > 0) ||
      statement.operating_expenses.categories.some((c) => c.rows.length > 0)
    );
  }, [statement]);

  const toEntries = (rows: { code: string; name: string; amount: number }[]): SectionEntry[] =>
    rows.map((r) => ({ account_code: r.code, account_name: r.name, display: r.amount }));

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <PageHeader
        title="Profit & Loss"
        subtitle="Multi-step statement: Operating Revenue → Cost of Sales → Gross Profit → Operating Expenses → Operating Profit → Other Income / Finance Costs / Tax Expense → Net Profit"
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
      ) : !hasActivity || !statement ? (
        <EmptyState
          title="No income or expense activity yet"
          hint="Record transactions via the AI agent or the Journal page - revenue and expenses will appear here."
        />
      ) : (
        <>
          {/* 1. Operating Revenue */}
          <Section
            title="Operating Revenue"
            entries={toEntries(statement.sections.operating_revenue.rows)}
            total={statement.operating_revenue}
            totalLabel="Total Operating Revenue"
            currency={currency}
          />

          {/* 2. Less: Cost of Sales → GROSS PROFIT */}
          <Section
            title="Less: Cost of Sales"
            entries={toEntries(statement.sections.cost_of_sales.rows)}
            total={statement.cost_of_sales}
            totalLabel="Total Cost of Sales"
            currency={currency}
            deduction
          />
          <Subtotal label="Gross Profit" value={statement.gross_profit} currency={currency} />

          {/* 3. Less: Operating Expenses (4 categories) → OPERATING PROFIT */}
          {statement.operating_expenses.categories.map((cat) => (
            <Section
              key={cat.label}
              title={`Less: ${cat.label}`}
              entries={toEntries(cat.rows)}
              total={cat.total}
              totalLabel={`Total ${cat.label}`}
              currency={currency}
              deduction
            />
          ))}
          <Subtotal label="Total Operating Expenses" value={-statement.operating_expenses.total} currency={currency} />
          <Subtotal label="Operating Profit" value={statement.operating_profit} currency={currency} />

          {/* 4. Other Income — deliberately OUTSIDE operating revenue */}
          <Section
            title="Add: Other Income"
            entries={toEntries(statement.sections.other_income.rows)}
            total={statement.other_income}
            totalLabel="Total Other Income"
            currency={currency}
          />

          {/* 5. Finance Costs & Tax Expense — separate line items */}
          <Section
            title="Less: Finance Costs"
            entries={toEntries(statement.sections.finance_costs.rows)}
            total={statement.finance_costs}
            totalLabel="Total Finance Costs"
            currency={currency}
            deduction
          />
          <Section
            title="Less: Tax Expense"
            entries={toEntries(statement.sections.tax_expense.rows)}
            total={statement.tax_expense}
            totalLabel="Total Tax Expense"
            currency={currency}
            deduction
          />

          {/* 6. NET PROFIT */}
          <div
            className={cn(
              "flex items-center justify-between rounded-2xl px-5 py-4 border",
              statement.is_loss
                ? "bg-error-50 border-error-200"
                : "bg-success-50 border-success-200"
            )}
          >
            <div>
              <p className="text-sm font-semibold text-text-primary">
                {statement.is_loss ? "Net Loss" : "Net Profit"}
              </p>
              <p className="text-xs text-text-secondary mt-0.5">
                Operating Profit + Other Income − Finance Costs − Tax Expense
              </p>
            </div>
            <p
              className={cn(
                "text-2xl font-semibold tabular-nums",
                statement.is_loss ? "text-error-700" : "text-success-700"
              )}
            >
              {formatCurrency(statement.net_profit, currency)}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

