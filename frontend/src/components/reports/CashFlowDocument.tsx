"use client";

import React from "react";
import ReportDocumentShell, { formatAccountingAmount } from "./ReportDocumentShell";
import type { OrgContext } from "@/lib/hooks/useOrg";
import type { CashFlowRow, CategoryTotals } from "@/lib/reports/cash-flow";

export interface CashFlowDocumentProps {
  rows: CashFlowRow[];
  totals: CategoryTotals;
  openingCash?: number;
  closingCash?: number;
  netCashChange?: number;
  fromDate?: string;
  toDate?: string;
  org?: OrgContext | null;
  currency?: string;
}

export default function CashFlowDocument({
  rows,
  totals,
  openingCash = 0,
  closingCash = 0,
  netCashChange = 0,
  fromDate,
  toDate,
  org,
  currency,
}: CashFlowDocumentProps) {
  const curr = currency || org?.base_currency_code || "PKR";
  const periodLabel =
    fromDate && toDate ? `For the period from ${fromDate} to ${toDate}` : undefined;

  const operatingRows = rows.filter((r) => r.cash_flow_category === "OPERATING");
  const investingRows = rows.filter((r) => r.cash_flow_category === "INVESTING");
  const financingRows = rows.filter((r) => r.cash_flow_category === "FINANCING");

  const computedNet = totals.OPERATING + totals.INVESTING + totals.FINANCING;
  const netChange = netCashChange || computedNet;
  const finalClosing = closingCash || openingCash + netChange;

  return (
    <ReportDocumentShell
      title="Statement of Cash Flows"
      subtitle="Operating, Investing and Financing Activities"
      periodLabel={periodLabel}
      org={org}
      currency={curr}
    >
      <div className="overflow-x-auto print:overflow-visible space-y-6">
        <table className="report-table w-full text-xs sm:text-sm border-collapse">
          <thead>
            <tr className="border-b-2 border-slate-800 text-slate-700 text-left font-serif uppercase tracking-wider text-[11px]">
              <th className="py-2.5 px-3 font-bold">Cash Flow Activity</th>
              <th className="py-2.5 px-2 font-bold w-28">Contra Code</th>
              <th className="py-2.5 px-3 font-bold">Contra Account</th>
              <th className="py-2.5 px-3 text-right font-bold w-40">Amount ({curr})</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100 text-slate-800 font-sans">
            {/* ======================================================== */}
            {/* 1. OPERATING ACTIVITIES                                  */}
            {/* ======================================================== */}
            <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
              <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                1. Cash Flows from Operating Activities
              </td>
            </tr>
            {operatingRows.length === 0 ? (
              <tr>
                <td className="py-1.5 px-6 text-slate-400 italic" colSpan={3}>
                  No operating cash flows recorded in this period
                </td>
                <td className="py-1.5 px-3 text-right text-slate-400 font-mono">-</td>
              </tr>
            ) : (
              operatingRows.map((r, i) => {
                const amt = Number(r.net_amount) || 0;
                return (
                  <tr key={`${r.journal_number}-${i}`} className="hover:bg-slate-50/50">
                    <td className="py-1.5 px-6 text-slate-700">{r.entry_description || r.cash_account_name}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{r.contra_account_code}</td>
                    <td className="py-1.5 px-3 text-slate-600 text-xs">{r.contra_account_name}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-slate-700">
                      {formatAccountingAmount(amt, curr, { showSymbol: false })}
                    </td>
                  </tr>
                );
              })
            )}
            <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/40">
              <td colSpan={3} className="py-2 px-3 text-right font-semibold">
                Net Cash Flow from Operating Activities:
              </td>
              <td className="py-2 px-3 text-right font-mono font-bold text-slate-900">
                {formatAccountingAmount(totals.OPERATING, curr, { showSymbol: false })}
              </td>
            </tr>

            {/* ======================================================== */}
            {/* 2. INVESTING ACTIVITIES                                  */}
            {/* ======================================================== */}
            <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
              <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                2. Cash Flows from Investing Activities
              </td>
            </tr>
            {investingRows.length === 0 ? (
              <tr>
                <td className="py-1.5 px-6 text-slate-400 italic" colSpan={3}>
                  No investing cash flows recorded in this period
                </td>
                <td className="py-1.5 px-3 text-right text-slate-400 font-mono">-</td>
              </tr>
            ) : (
              investingRows.map((r, i) => {
                const amt = Number(r.net_amount) || 0;
                return (
                  <tr key={`${r.journal_number}-${i}`} className="hover:bg-slate-50/50">
                    <td className="py-1.5 px-6 text-slate-700">{r.entry_description || r.cash_account_name}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{r.contra_account_code}</td>
                    <td className="py-1.5 px-3 text-slate-600 text-xs">{r.contra_account_name}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-slate-700">
                      {formatAccountingAmount(amt, curr, { showSymbol: false })}
                    </td>
                  </tr>
                );
              })
            )}
            <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/40">
              <td colSpan={3} className="py-2 px-3 text-right font-semibold">
                Net Cash Flow from Investing Activities:
              </td>
              <td className="py-2 px-3 text-right font-mono font-bold text-slate-900">
                {formatAccountingAmount(totals.INVESTING, curr, { showSymbol: false })}
              </td>
            </tr>

            {/* ======================================================== */}
            {/* 3. FINANCING ACTIVITIES                                  */}
            {/* ======================================================== */}
            <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
              <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                3. Cash Flows from Financing Activities
              </td>
            </tr>
            {financingRows.length === 0 ? (
              <tr>
                <td className="py-1.5 px-6 text-slate-400 italic" colSpan={3}>
                  No financing cash flows recorded in this period
                </td>
                <td className="py-1.5 px-3 text-right text-slate-400 font-mono">-</td>
              </tr>
            ) : (
              financingRows.map((r, i) => {
                const amt = Number(r.net_amount) || 0;
                return (
                  <tr key={`${r.journal_number}-${i}`} className="hover:bg-slate-50/50">
                    <td className="py-1.5 px-6 text-slate-700">{r.entry_description || r.cash_account_name}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{r.contra_account_code}</td>
                    <td className="py-1.5 px-3 text-slate-600 text-xs">{r.contra_account_name}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-slate-700">
                      {formatAccountingAmount(amt, curr, { showSymbol: false })}
                    </td>
                  </tr>
                );
              })
            )}
            <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/40">
              <td colSpan={3} className="py-2 px-3 text-right font-semibold">
                Net Cash Flow from Financing Activities:
              </td>
              <td className="py-2 px-3 text-right font-mono font-bold text-slate-900">
                {formatAccountingAmount(totals.FINANCING, curr, { showSymbol: false })}
              </td>
            </tr>

            {/* ======================================================== */}
            {/* 4. NET CHANGE & RECONCILIATION                           */}
            {/* ======================================================== */}
            <tr className="border-t-2 border-slate-800 bg-slate-100 font-bold text-slate-950">
              <td colSpan={3} className="py-2.5 px-3 uppercase tracking-wider text-xs">
                Net Increase / (Decrease) in Cash & Cash Equivalents
              </td>
              <td className="py-2.5 px-3 text-right font-mono text-sm sm:text-base">
                {formatAccountingAmount(netChange, curr, { showSymbol: true })}
              </td>
            </tr>

            <tr className="bg-white font-medium text-slate-700">
              <td colSpan={3} className="py-2 px-3 text-xs">
                Cash and Cash Equivalents at Beginning of Period
              </td>
              <td className="py-2 px-3 text-right font-mono">
                {formatAccountingAmount(openingCash, curr, { showSymbol: false })}
              </td>
            </tr>

            {/* CLOSING CASH DOUBLE UNDERLINE */}
            <tr className="border-t-2 border-slate-900 border-b-4 border-double border-slate-900 bg-slate-100/90 font-bold text-slate-950">
              <td colSpan={3} className="py-3 px-3 uppercase tracking-wider text-xs sm:text-sm">
                Cash and Cash Equivalents at End of Period
              </td>
              <td className="py-3 px-3 text-right font-mono text-sm sm:text-base">
                {formatAccountingAmount(finalClosing, curr, { showSymbol: true })}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </ReportDocumentShell>
  );
}
