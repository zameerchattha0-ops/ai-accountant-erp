"use client";

import React from "react";
import ReportDocumentShell, { formatAccountingAmount } from "./ReportDocumentShell";
import type { OrgContext } from "@/lib/hooks/useOrg";

export interface BalanceSheetEntry {
  account_code: string;
  account_name: string;
  display: number;
}

export interface BalanceSheetDocumentProps {
  assets: BalanceSheetEntry[];
  liabilities: BalanceSheetEntry[];
  equity: BalanceSheetEntry[];
  totalAssets: number;
  totalLiabilities: number;
  totalEquity: number;
  currentEarnings?: number;
  balanced: boolean;
  org?: OrgContext | null;
  asOfDate?: string;
  currency?: string;
}

export default function BalanceSheetDocument({
  assets,
  liabilities,
  equity,
  totalAssets,
  totalLiabilities,
  totalEquity,
  currentEarnings = 0,
  balanced,
  org,
  asOfDate,
  currency,
}: BalanceSheetDocumentProps) {
  const curr = currency || org?.base_currency_code || "PKR";
  const totalLiabilitiesAndEquity = totalLiabilities + totalEquity;

  return (
    <ReportDocumentShell
      title="Statement of Financial Position"
      subtitle="Balance Sheet · Posted Double-Entry Accounts"
      asOfDate={asOfDate}
      org={org}
      currency={curr}
    >
      <div className="overflow-x-auto print:overflow-visible space-y-8">
        {/* ============================================================ */}
        {/* ASSETS SECTION                                               */}
        {/* ============================================================ */}
        <div className="report-section break-inside-avoid">
          <table className="report-table w-full text-xs sm:text-sm border-collapse">
            <thead>
              <tr className="border-b-2 border-slate-800 text-slate-700 text-left font-serif uppercase tracking-wider text-[11px]">
                <th className="py-2.5 px-3 font-bold">Assets</th>
                <th className="py-2.5 px-2 font-bold w-24">Code</th>
                <th className="py-2.5 px-3 text-right font-bold w-36">Details ({curr})</th>
                <th className="py-2.5 px-3 text-right font-bold w-40">Amount ({curr})</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-800 font-sans">
              {assets.length === 0 ? (
                <tr>
                  <td className="py-3 px-6 text-slate-400 italic" colSpan={3}>
                    No asset accounts recorded
                  </td>
                  <td className="py-3 px-3 text-right text-slate-400 font-mono">-</td>
                </tr>
              ) : (
                assets.map((r) => (
                  <tr key={r.account_code} className="hover:bg-slate-50/50">
                    <td className="py-1.5 px-6 text-slate-700">{r.account_name}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{r.account_code}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-slate-600">
                      {formatAccountingAmount(r.display, curr, { showSymbol: false })}
                    </td>
                    <td className="py-1.5 px-3" />
                  </tr>
                ))
              )}

              {/* TOTAL ASSETS DOUBLE UNDERLINE */}
              <tr className="border-t-2 border-slate-900 border-b-4 border-double border-slate-900 bg-slate-100/90 font-bold text-slate-950">
                <td colSpan={3} className="py-2.5 px-3 uppercase tracking-wider text-xs sm:text-sm">
                  Total Assets
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-sm sm:text-base">
                  {formatAccountingAmount(totalAssets, curr, { showSymbol: true })}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* ============================================================ */}
        {/* LIABILITIES AND EQUITY SECTION                               */}
        {/* ============================================================ */}
        <div className="report-section break-inside-avoid">
          <table className="report-table w-full text-xs sm:text-sm border-collapse">
            <thead>
              <tr className="border-b-2 border-slate-800 text-slate-700 text-left font-serif uppercase tracking-wider text-[11px]">
                <th className="py-2.5 px-3 font-bold">Equity & Liabilities</th>
                <th className="py-2.5 px-2 font-bold w-24">Code</th>
                <th className="py-2.5 px-3 text-right font-bold w-36">Details ({curr})</th>
                <th className="py-2.5 px-3 text-right font-bold w-40">Amount ({curr})</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-800 font-sans">
              {/* LIABILITIES SUBSECTION */}
              <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
                <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                  Liabilities
                </td>
              </tr>
              {liabilities.length === 0 ? (
                <tr>
                  <td className="py-1.5 px-6 text-slate-400 italic" colSpan={3}>
                    No liabilities recorded
                  </td>
                  <td className="py-1.5 px-3 text-right text-slate-400 font-mono">-</td>
                </tr>
              ) : (
                liabilities.map((r) => (
                  <tr key={r.account_code} className="hover:bg-slate-50/50">
                    <td className="py-1.5 px-6 text-slate-700">{r.account_name}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{r.account_code}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-slate-600">
                      {formatAccountingAmount(r.display, curr, { showSymbol: false })}
                    </td>
                    <td className="py-1.5 px-3" />
                  </tr>
                ))
              )}
              <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/30">
                <td colSpan={3} className="py-2 px-3 text-right">
                  Total Liabilities:
                </td>
                <td className="py-2 px-3 text-right font-mono font-bold">
                  {formatAccountingAmount(totalLiabilities, curr, { showSymbol: false })}
                </td>
              </tr>

              {/* EQUITY SUBSECTION */}
              <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
                <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                  Equity
                </td>
              </tr>
              {equity.map((r) => (
                <tr key={r.account_code} className="hover:bg-slate-50/50">
                  <td className="py-1.5 px-6 text-slate-700">{r.account_name}</td>
                  <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{r.account_code}</td>
                  <td className="py-1.5 px-3 text-right font-mono text-slate-600">
                    {formatAccountingAmount(r.display, curr, { showSymbol: false })}
                  </td>
                  <td className="py-1.5 px-3" />
                </tr>
              ))}

              {Math.abs(currentEarnings) > 0.005 && (
                <tr className="hover:bg-slate-50/50">
                  <td className="py-1.5 px-6 text-slate-700 italic">
                    Current Year Profit / (Loss)
                  </td>
                  <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">P&L</td>
                  <td className="py-1.5 px-3 text-right font-mono text-slate-600">
                    {formatAccountingAmount(currentEarnings, curr, { showSymbol: false })}
                  </td>
                  <td className="py-1.5 px-3" />
                </tr>
              )}

              <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/30">
                <td colSpan={3} className="py-2 px-3 text-right">
                  Total Equity:
                </td>
                <td className="py-2 px-3 text-right font-mono font-bold">
                  {formatAccountingAmount(totalEquity, curr, { showSymbol: false })}
                </td>
              </tr>

              {/* TOTAL LIABILITIES & EQUITY DOUBLE UNDERLINE */}
              <tr className="border-t-2 border-slate-900 border-b-4 border-double border-slate-900 bg-slate-100/90 font-bold text-slate-950">
                <td colSpan={3} className="py-2.5 px-3 uppercase tracking-wider text-xs sm:text-sm">
                  Total Equity and Liabilities
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-sm sm:text-base">
                  {formatAccountingAmount(totalLiabilitiesAndEquity, curr, { showSymbol: true })}
                </td>
              </tr>
            </tbody>
          </table>

          {/* Statement balancing verification note */}
          <div className="mt-4 p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600 flex items-center justify-between">
            <span className="font-medium">
              {balanced
                ? "✓ The Balance Sheet is in balance (Total Assets = Total Equity + Liabilities)."
                : `⚠ Note: Imbalance of ${formatAccountingAmount(totalAssets - totalLiabilitiesAndEquity, curr)} detected.`}
            </span>
            <span className="font-mono text-[11px] text-slate-500">
              Fundamental Accounting Equation Verified
            </span>
          </div>
        </div>
      </div>
    </ReportDocumentShell>
  );
}

