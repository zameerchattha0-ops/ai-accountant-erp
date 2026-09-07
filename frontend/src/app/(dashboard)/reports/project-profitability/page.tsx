"use client";

import { useCallback, useEffect, useState } from "react";
import { Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";
import type { ProjectProfitabilityRow } from "@/lib/types/entities";

export default function ProjectProfitabilityPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<ProjectProfitabilityRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("v_project_profitability")
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("project_name");
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  const currency = org?.base_currency_code;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Project P&L"
        subtitle="Revenue, cost and margin per project (posted entries only)"
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
        <TableSkeleton rows={6} cols={7} />
      ) : error ? (
        <ErrorState message={error} />
      ) : (rows ?? []).length === 0 ? (
        <EmptyState
          title="No projects yet"
          hint={"Projects are created via the AI agent (\"Set up a project called Mobile App for XYZ Client\") - their P&L appears here."}
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Project</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Budget</th>
                <th className="px-4 py-3 font-medium text-right">Revenue</th>
                <th className="px-4 py-3 font-medium text-right">Costs</th>
                <th className="px-4 py-3 font-medium text-right">Gross Profit</th>
                <th className="px-4 py-3 font-medium text-right">Margin</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((r) => (
                <tr key={r.project_id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                  <td className="px-4 py-3 text-text-primary">
                    <span className="tabular-nums text-text-secondary mr-2 text-xs">{r.project_code}</span>
                    {r.project_name}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                  <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                    {r.budget != null ? formatCurrency(r.budget, currency) : "-"}
                  </td>
                  <td className="px-4 py-3 text-right text-text-primary tabular-nums">
                    {formatCurrency(r.project_revenue, currency)}
                  </td>
                  <td className="px-4 py-3 text-right text-text-primary tabular-nums">
                    {formatCurrency(r.project_costs, currency)}
                  </td>
                  <td className={cn(
                    "px-4 py-3 text-right tabular-nums font-medium",
                    r.gross_profit >= 0 ? "text-success-700" : "text-error-600"
                  )}>
                    {formatCurrency(r.gross_profit, currency)}
                  </td>
                  <td className="px-4 py-3 text-right text-text-primary tabular-nums">
                    {r.margin_percent != null ? `${r.margin_percent}%` : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-text-muted print:hidden">
        Revenue and costs come from journal lines tagged with the project.
        Tag lines by telling the AI which project a transaction belongs to.
      </p>
    </div>
  );
}
