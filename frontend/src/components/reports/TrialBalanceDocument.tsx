"use client";

import React from "react";
import ReportDocumentShell, { formatAccountingAmount } from "./ReportDocumentShell";
import type { OrgContext } from "@/lib/hooks/useOrg";
import type { TrialBalanceRow } from "@/lib/types/entities";

export interface TrialBalanceDocumentProps {
  rows: TrialBalanceRow[];
  totalDebit: number;
  totalCredit: number;
  balanced: boolean;
  org?: OrgContext | null;
  asOfDate?: string;
  currency?: string;
}

export default function TrialBalanceDocument({
  rows,
  totalDebit,
  totalCredit,
  balanced,
  org,
  asOfDate,
  currency,
}: TrialBalanceDocumentProps) {
  const curr = currency || org?.base_currency_code || "PKR";

  return (
    <ReportDocumentShell
      title="Trial Balance"
      subtitle="Summary of General Ledger Balances · Double-Entry Integrity"
      asOfDate={asOfDate}
      org={org}
      currency={curr}
    >
      <div className="overflow-x-auto print:overflow-visible">
        <table className="report-table w-full text-xs sm:text-sm border-collapse">
          <thead>
            <tr className="border-b-2 border-slate-800 text-slate-700 text-left font-serif uppercase tracking-wider text-[11px]">
              <th className="py-2.5 px-3 font-bold w-24">Code</th>
              <th className="py-2.5 px-3 font-bold">Account Title</th>
              <th className="py-2.5 px-3 font-bold w-32">Type</th>
              <th className="py-2.5 px-3 text-right font-bold w-36">Debit ({curr})</th>
              <th className="py-2.5 px-3 text-right font-bold w-36">Credit ({curr})</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100 text-slate-800 font-sans">
            {rows.length === 0 ? (
              <tr>
                <td className="py-4 px-6 text-slate-400 italic" colSpan={5}>
                  No posted accounts in trial balance
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.account_id} className="hover:bg-slate-50/50">
                  <td className="py-2 px-3 font-mono font-medium text-slate-600">
                    {row.account_code}
                  </td>
                  <td className="py-2 px-3 text-slate-800 font-medium">{row.account_name}</td>
                  <td className="py-2 px-3 text-xs text-slate-500 font-mono">
                    {row.account_type}
                  </td>
                  <td className="py-2 px-3 text-right font-mono text-slate-700">
                    {row.total_debit > 0
                      ? formatAccountingAmount(row.total_debit, curr, { showSymbol: false })
                      : "-"}
                  </td>
                  <td className="py-2 px-3 text-right font-mono text-slate-700">
                    {row.total_credit > 0
                      ? formatAccountingAmount(row.total_credit, curr, { showSymbol: false })
                      : "-"}
                  </td>
                </tr>
              ))
            )}

            {/* GRAND TOTAL ROW WITH DOUBLE UNDERLINE */}
            <tr className="border-t-2 border-slate-900 border-b-4 border-double border-slate-900 bg-slate-100 font-bold text-slate-950">
              <td colSpan={3} className="py-3 px-3 uppercase tracking-wider text-xs sm:text-sm">
                Total Trial Balance:
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm sm:text-base">
                {formatAccountingAmount(totalDebit, curr, { showSymbol: true })}
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm sm:text-base">
                {formatAccountingAmount(totalCredit, curr, { showSymbol: true })}
              </td>
            </tr>
          </tbody>
        </table>

        {/* Balancing validation alert */}
        <div className="mt-4 p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600 flex items-center justify-between">
          <span className="font-medium">
            {balanced
              ? "✓ The Trial Balance is in balance (Total Debits = Total Credits)."
              : `⚠ Note: Imbalance of ${formatAccountingAmount(Math.abs(totalDebit - totalCredit), curr)} detected.`}
          </span>
          <span className="font-mono text-[11px] text-slate-500">
            {rows.length} Active Accounts Reported
          </span>
        </div>
      </div>
    </ReportDocumentShell>
  );
}

