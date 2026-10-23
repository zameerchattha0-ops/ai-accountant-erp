"use client";

import React from "react";
import ReportDocumentShell, { formatAccountingAmount } from "./ReportDocumentShell";
import type { OrgContext } from "@/lib/hooks/useOrg";
import type { AgingRow } from "@/lib/types/entities";

export interface AgingDocumentProps {
  type: "receivables" | "payables";
  rows: AgingRow[];
  org?: OrgContext | null;
  asOfDate?: string;
  currency?: string;
}

export default function AgingDocument({
  type,
  rows,
  org,
  asOfDate,
  currency,
}: AgingDocumentProps) {
  const curr = currency || org?.base_currency_code || "PKR";
  const title =
    type === "receivables"
      ? "Accounts Receivable Aging Schedule"
      : "Accounts Payable Aging Schedule";
  const subtitle =
    type === "receivables"
      ? "Analysis of Customer Receivables by Due Date Brackets"
      : "Analysis of Supplier Payables by Due Date Brackets";

  const totalCurrent = rows.reduce((s, r) => s + (r.bucket_current || 0), 0);
  const total1_30 = rows.reduce((s, r) => s + (r.bucket_1_30 || 0), 0);
  const total31_60 = rows.reduce((s, r) => s + (r.bucket_31_60 || 0), 0);
  const total61_90 = rows.reduce((s, r) => s + (r.bucket_61_90 || 0), 0);
  const total90Plus = rows.reduce((s, r) => s + (r.bucket_90_plus || 0), 0);
  const totalOutstanding = rows.reduce((s, r) => s + (r.total_outstanding || 0), 0);

  const partyName = (r: AgingRow) =>
    type === "receivables" ? r.customer_name || "Unknown Customer" : r.supplier_name || "Unknown Supplier";

  return (
    <ReportDocumentShell
      title={title}
      subtitle={subtitle}
      asOfDate={asOfDate}
      org={org}
      currency={curr}
    >
      <div className="overflow-x-auto print:overflow-visible">
        <table className="report-table w-full text-xs sm:text-sm border-collapse">
          <thead>
            <tr className="border-b-2 border-slate-800 text-slate-700 text-left font-serif uppercase tracking-wider text-[11px]">
              <th className="py-2.5 px-3 font-bold">
                {type === "receivables" ? "Customer" : "Supplier"} Name
              </th>
              <th className="py-2.5 px-2 text-right font-bold w-24">Current</th>
              <th className="py-2.5 px-2 text-right font-bold w-24">1-30 Days</th>
              <th className="py-2.5 px-2 text-right font-bold w-24">31-60 Days</th>
              <th className="py-2.5 px-2 text-right font-bold w-24">61-90 Days</th>
              <th className="py-2.5 px-2 text-right font-bold w-24">90+ Days</th>
              <th className="py-2.5 px-3 text-right font-bold w-32">Total ({curr})</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100 text-slate-800 font-sans">
            {rows.length === 0 ? (
              <tr>
                <td className="py-4 px-6 text-slate-400 italic" colSpan={7}>
                  No outstanding aging balances found
                </td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr key={`${partyName(r)}-${i}`} className="hover:bg-slate-50/50">
                  <td className="py-2 px-3 font-medium text-slate-800">{partyName(r)}</td>
                  <td className="py-2 px-2 text-right font-mono text-slate-600">
                    {r.bucket_current > 0 ? formatAccountingAmount(r.bucket_current, curr, { showSymbol: false }) : "-"}
                  </td>
                  <td className="py-2 px-2 text-right font-mono text-slate-600">
                    {r.bucket_1_30 > 0 ? formatAccountingAmount(r.bucket_1_30, curr, { showSymbol: false }) : "-"}
                  </td>
                  <td className="py-2 px-2 text-right font-mono text-slate-600">
                    {r.bucket_31_60 > 0 ? formatAccountingAmount(r.bucket_31_60, curr, { showSymbol: false }) : "-"}
                  </td>
                  <td className="py-2 px-2 text-right font-mono text-slate-600">
                    {r.bucket_61_90 > 0 ? formatAccountingAmount(r.bucket_61_90, curr, { showSymbol: false }) : "-"}
                  </td>
                  <td className="py-2 px-2 text-right font-mono text-rose-700 font-medium">
                    {r.bucket_90_plus > 0 ? formatAccountingAmount(r.bucket_90_plus, curr, { showSymbol: false }) : "-"}
                  </td>
                  <td className="py-2 px-3 text-right font-mono font-bold text-slate-900">
                    {formatAccountingAmount(r.total_outstanding, curr, { showSymbol: false })}
                  </td>
                </tr>
              ))
            )}

            {/* GRAND TOTAL ROW WITH DOUBLE UNDERLINE */}
            <tr className="border-t-2 border-slate-900 border-b-4 border-double border-slate-900 bg-slate-100 font-bold text-slate-950">
              <td className="py-3 px-3 uppercase tracking-wider text-xs">
                Total Outstanding:
              </td>
              <td className="py-3 px-2 text-right font-mono">
                {formatAccountingAmount(totalCurrent, curr, { showSymbol: false })}
              </td>
              <td className="py-3 px-2 text-right font-mono">
                {formatAccountingAmount(total1_30, curr, { showSymbol: false })}
              </td>
              <td className="py-3 px-2 text-right font-mono">
                {formatAccountingAmount(total31_60, curr, { showSymbol: false })}
              </td>
              <td className="py-3 px-2 text-right font-mono">
                {formatAccountingAmount(total61_90, curr, { showSymbol: false })}
              </td>
              <td className="py-3 px-2 text-right font-mono text-rose-700">
                {formatAccountingAmount(total90Plus, curr, { showSymbol: false })}
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm sm:text-base">
                {formatAccountingAmount(totalOutstanding, curr, { showSymbol: true })}
              </td>
            </tr>
          </tbody>
        </table>

        {/* Schedule metadata footer */}
        <div className="mt-4 p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600 flex items-center justify-between">
          <span className="font-medium">
            Overdue items (&gt;90 days): {formatAccountingAmount(total90Plus, curr)}
          </span>
          <span className="font-mono text-[11px] text-slate-500">
            {rows.length} Parties Analyzed
          </span>
        </div>
      </div>
    </ReportDocumentShell>
  );
}

