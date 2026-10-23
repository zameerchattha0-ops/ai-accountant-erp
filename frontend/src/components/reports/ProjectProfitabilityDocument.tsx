"use client";

import React from "react";
import ReportDocumentShell, { formatAccountingAmount } from "./ReportDocumentShell";
import type { OrgContext } from "@/lib/hooks/useOrg";
import type { ProjectProfitabilityRow } from "@/lib/types/entities";

export interface ProjectProfitabilityDocumentProps {
  rows: ProjectProfitabilityRow[];
  org?: OrgContext | null;
  periodLabel?: string;
  currency?: string;
}

export default function ProjectProfitabilityDocument({
  rows,
  org,
  periodLabel,
  currency,
}: ProjectProfitabilityDocumentProps) {
  const curr = currency || org?.base_currency_code || "PKR";

  const totalRevenue = rows.reduce((s, r) => s + (r.project_revenue || 0), 0);
  const totalCost = rows.reduce((s, r) => s + (r.project_costs || 0), 0);
  const totalProfit = rows.reduce((s, r) => s + (r.gross_profit || 0), 0);
  const overallMargin = totalRevenue > 0 ? (totalProfit / totalRevenue) * 100 : 0;

  return (
    <ReportDocumentShell
      title="Project Profitability Statement"
      subtitle="Project Margin and Performance Analysis (Posted Entries Only)"
      periodLabel={periodLabel}
      org={org}
      currency={curr}
    >
      <div className="overflow-x-auto print:overflow-visible">
        <table className="report-table w-full text-xs sm:text-sm border-collapse">
          <thead>
            <tr className="border-b-2 border-slate-800 text-slate-700 text-left font-serif uppercase tracking-wider text-[11px]">
              <th className="py-2.5 px-3 font-bold">Project Name</th>
              <th className="py-2.5 px-2 font-bold w-28">Status</th>
              <th className="py-2.5 px-3 text-right font-bold w-36">Revenue ({curr})</th>
              <th className="py-2.5 px-3 text-right font-bold w-36">Cost ({curr})</th>
              <th className="py-2.5 px-3 text-right font-bold w-36">Gross Profit ({curr})</th>
              <th className="py-2.5 px-3 text-right font-bold w-28">Margin %</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100 text-slate-800 font-sans">
            {rows.length === 0 ? (
              <tr>
                <td className="py-4 px-6 text-slate-400 italic" colSpan={6}>
                  No active projects with posted activity
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.project_id} className="hover:bg-slate-50/50">
                  <td className="py-2 px-3 font-medium text-slate-800">{r.project_name}</td>
                  <td className="py-2 px-2 text-xs font-mono text-slate-500 uppercase">{r.status}</td>
                  <td className="py-2 px-3 text-right font-mono text-slate-700">
                    {formatAccountingAmount(r.project_revenue, curr, { showSymbol: false })}
                  </td>
                  <td className="py-2 px-3 text-right font-mono text-slate-700">
                    {formatAccountingAmount(r.project_costs, curr, { showSymbol: false })}
                  </td>
                  <td className="py-2 px-3 text-right font-mono font-medium text-slate-900">
                    {formatAccountingAmount(r.gross_profit, curr, { showSymbol: false })}
                  </td>
                  <td className="py-2 px-3 text-right font-mono text-xs">
                    {r.margin_percent != null ? `${Number(r.margin_percent).toFixed(1)}%` : "-"}
                  </td>
                </tr>
              ))
            )}

            {/* GRAND TOTAL ROW WITH DOUBLE UNDERLINE */}
            <tr className="border-t-2 border-slate-900 border-b-4 border-double border-slate-900 bg-slate-100 font-bold text-slate-950">
              <td colSpan={2} className="py-3 px-3 uppercase tracking-wider text-xs">
                Total Projects Portfolio:
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm">
                {formatAccountingAmount(totalRevenue, curr, { showSymbol: true })}
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm">
                {formatAccountingAmount(totalCost, curr, { showSymbol: true })}
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm sm:text-base">
                {formatAccountingAmount(totalProfit, curr, { showSymbol: true })}
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm">
                {overallMargin.toFixed(1)}%
              </td>
            </tr>
          </tbody>
        </table>

        {/* Portfolio health notes */}
        <div className="mt-4 p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600 flex items-center justify-between">
          <span className="font-medium">
            Overall Portfolio Margin: {overallMargin.toFixed(1)}%
          </span>
          <span className="font-mono text-[11px] text-slate-500">
            {rows.length} Projects Recorded
          </span>
        </div>
      </div>
    </ReportDocumentShell>
  );
}
