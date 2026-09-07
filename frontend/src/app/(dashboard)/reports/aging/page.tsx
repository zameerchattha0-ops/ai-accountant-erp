"use client";

import { useCallback, useEffect, useState } from "react";
import { Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";
import type { AgingRow } from "@/lib/types/entities";

type Tab = "receivables" | "payables";

const BUCKETS: { key: keyof AgingRow; label: string }[] = [
  { key: "bucket_current", label: "Current" },
  { key: "bucket_1_30", label: "1-30 days" },
  { key: "bucket_31_60", label: "31-60 days" },
  { key: "bucket_61_90", label: "61-90 days" },
  { key: "bucket_90_plus", label: "90+ days" },
];

export default function AgingReportPage() {
  const { org, loading: orgLoading } = useOrg();
  const [tab, setTab] = useState<Tab>("receivables");
  const [rows, setRows] = useState<AgingRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const view = tab === "receivables" ? "v_customer_aging" : "v_supplier_aging";
    const { data, error: dbError } = await supabase
      .from(view)
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("total_outstanding", { ascending: false });
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org, tab]);

  useEffect(() => { setRows(null); load(); }, [load]);

  const currency = org?.base_currency_code;
  const partyLabel = (r: AgingRow) =>
    tab === "receivables" ? r.customer_name ?? "-" : r.supplier_name ?? "-";
  const columnTotal = (key: keyof AgingRow) =>
    (rows ?? []).reduce((s, r) => s + (r[key] as number), 0);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Aging"
        subtitle="Outstanding receivables and payables by age bucket"
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

      <div className="flex items-center gap-2 print:hidden">
        <div className="flex items-center rounded-xl bg-bg-surface border border-border-subtle p-0.5">
          {([
            { id: "receivables" as Tab, label: "Receivables (customers owe you)" },
            { id: "payables" as Tab, label: "Payables (you owe suppliers)" },
          ]).map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors",
                tab === t.id ? "bg-ai-500 text-white" : "text-text-secondary hover:text-text-primary"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton rows={6} cols={7} />
      ) : error ? (
        <ErrorState message={error} />
      ) : (rows ?? []).length === 0 ? (
        <EmptyState
          title={tab === "receivables" ? "No outstanding receivables" : "No outstanding payables"}
          hint={
            tab === "receivables"
              ? "Unpaid issued invoices will appear here with their age."
              : "Unpaid open purchase bills will appear here with their age."
          }
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">
                  {tab === "receivables" ? "Customer" : "Supplier"}
                </th>
                {BUCKETS.map((b) => (
                  <th key={b.key} className="px-4 py-3 font-medium text-right">{b.label}</th>
                ))}
                <th className="px-4 py-3 font-medium text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((r) => (
                <tr key={tab === "receivables" ? r.customer_id : r.supplier_id}
                  className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                  <td className="px-4 py-3 text-text-primary font-medium">{partyLabel(r)}</td>
                  {BUCKETS.map((b) => {
                    const v = r[b.key] as number;
                    return (
                      <td key={b.key} className={cn(
                        "px-4 py-3 text-right tabular-nums",
                        v > 0.005
                          ? b.key === "bucket_90_plus" || b.key === "bucket_61_90"
                            ? "text-error-600 font-medium"
                            : "text-text-primary"
                          : "text-text-muted"
                      )}>
                        {v > 0.005 ? formatCurrency(v, currency) : "-"}
                      </td>
                    );
                  })}
                  <td className="px-4 py-3 text-right text-text-primary tabular-nums font-semibold">
                    {formatCurrency(r.total_outstanding, currency)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border-default bg-bg-muted/50">
                <td className="px-4 py-3 font-semibold text-text-primary">Total</td>
                {BUCKETS.map((b) => (
                  <td key={b.key} className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
                    {formatCurrency(columnTotal(b.key), currency)}
                  </td>
                ))}
                <td className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
                  {formatCurrency(columnTotal("total_outstanding"), currency)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <p className="text-xs text-text-muted print:hidden">
        Aging is based on issued/open documents with a remaining balance, bucketed
        by days past the due date.
      </p>
    </div>
  );
}
