"use client";

import React from "react";
import ReportDocumentShell, { formatAccountingAmount } from "./ReportDocumentShell";
import type { OrgContext } from "@/lib/hooks/useOrg";
import type { PlStatement } from "@/lib/reports/pl-structure";

export interface ProfitLossDocumentProps {
  statement: PlStatement;
  org?: OrgContext | null;
  periodLabel?: string;
  currency?: string;
}

export default function ProfitLossDocument({
  statement,
  org,
  periodLabel,
  currency,
}: ProfitLossDocumentProps) {
  const curr = currency || org?.base_currency_code || "PKR";

  return (
    <ReportDocumentShell
      title="Statement of Profit or Loss"
      subtitle="Comprehensive Multi-Step Income Statement"
      periodLabel={periodLabel}
      org={org}
      currency={curr}
    >
      <div className="overflow-x-auto print:overflow-visible">
        <table className="report-table w-full text-xs sm:text-sm border-collapse">
          <thead>
            <tr className="border-b-2 border-slate-800 text-slate-700 text-left font-serif uppercase tracking-wider text-[11px]">
              <th className="py-2.5 px-3 font-bold">Particulars / Account</th>
              <th className="py-2.5 px-2 font-bold w-24">Code</th>
              <th className="py-2.5 px-3 text-right font-bold w-36">Details ({curr})</th>
              <th className="py-2.5 px-3 text-right font-bold w-40">Amount ({curr})</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100 text-slate-800 font-sans">
            {/* ========================================================== */}
            {/* 1. OPERATING REVENUE                                      */}
            {/* ========================================================== */}
            <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
              <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                Revenue from Operations
              </td>
            </tr>
            {statement.sections.operating_revenue.rows.length === 0 ? (
              <tr>
                <td className="py-1.5 px-6 text-slate-400 italic" colSpan={3}>
                  No operating revenue recorded for this period
                </td>
                <td className="py-1.5 px-3 text-right text-slate-400 font-mono">-</td>
              </tr>
            ) : (
              statement.sections.operating_revenue.rows.map((row) => (
                <tr key={row.code} className="hover:bg-slate-50/50">
                  <td className="py-1.5 px-6 text-slate-700">{row.name}</td>
                  <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{row.code}</td>
                  <td className="py-1.5 px-3 text-right font-mono text-slate-600">
                    {formatAccountingAmount(row.amount, curr, { showSymbol: false })}
                  </td>
                  <td className="py-1.5 px-3" />
                </tr>
              ))
            )}
            <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/30">
              <td colSpan={3} className="py-2 px-3 text-right">
                Total Operating Revenue:
              </td>
              <td className="py-2 px-3 text-right font-mono font-bold">
                {formatAccountingAmount(statement.operating_revenue, curr, { showSymbol: false })}
              </td>
            </tr>

            {/* ========================================================== */}
            {/* 2. COST OF SALES                                          */}
            {/* ========================================================== */}
            <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
              <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                Less: Cost of Sales
              </td>
            </tr>
            {statement.sections.cost_of_sales.rows.length === 0 ? (
              <tr>
                <td className="py-1.5 px-6 text-slate-400 italic" colSpan={3}>
                  No direct cost of sales recorded
                </td>
                <td className="py-1.5 px-3 text-right text-slate-400 font-mono">-</td>
              </tr>
            ) : (
              statement.sections.cost_of_sales.rows.map((row) => (
                <tr key={row.code} className="hover:bg-slate-50/50">
                  <td className="py-1.5 px-6 text-slate-700">{row.name}</td>
                  <td className="py-1.5 px-2 text-slate-400 font-mono text-xs">{row.code}</td>
                  <td className="py-1.5 px-3 text-right font-mono text-slate-600">
                    {formatAccountingAmount(-Math.abs(row.amount), curr, { showSymbol: false })}
                  </td>
                  <td className="py-1.5 px-3" />
                </tr>
              ))
            )}
            <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/30">
              <td colSpan={3} className="py-2 px-3 text-right">
                Total Cost of Sales:
              </td>
              <td className="py-2 px-3 text-right font-mono font-bold text-slate-800">
                {formatAccountingAmount(-Math.abs(statement.cost_of_sales), curr, { showSymbol: false })}
              </td>
            </tr>

            {/* ========================================================== */}
            {/* 3. GROSS PROFIT                                           */}
            {/* ========================================================== */}
            <tr className="border-t-2 border-b-2 border-slate-800 bg-slate-100/80 font-bold text-slate-950">
              <td colSpan={3} className="py-2.5 px-3 uppercase tracking-wider text-xs">
                Gross Profit
              </td>
              <td className="py-2.5 px-3 text-right font-mono text-sm sm:text-base">
                {formatAccountingAmount(statement.gross_profit, curr, { showSymbol: true })}
              </td>
            </tr>

            {/* ========================================================== */}
            {/* 4. OPERATING EXPENSES                                     */}
            {/* ========================================================== */}
            <tr className="bg-slate-50/70 font-semibold text-slate-900 border-t border-slate-300">
              <td colSpan={4} className="py-2 px-3 tracking-wide uppercase text-xs">
                Less: Operating Expenses
              </td>
            </tr>
            {statement.operating_expenses.categories.map((category) => (
              <React.Fragment key={category.label}>
                <tr className="bg-slate-50/40 text-[11px] font-semibold text-slate-700">
                  <td colSpan={4} className="py-1 px-5 italic">
                    {category.label}
                  </td>
                </tr>
                {category.rows.length === 0 ? (
                  <tr>
                    <td className="py-1 px-8 text-slate-400 text-xs italic" colSpan={3}>
                      No expenses in this category
                    </td>
                    <td className="py-1 px-3 text-right text-slate-400 font-mono text-xs">-</td>
                  </tr>
                ) : (
                  category.rows.map((row) => (
                    <tr key={row.code} className="hover:bg-slate-50/50">
                      <td className="py-1 px-8 text-slate-700">{row.name}</td>
                      <td className="py-1 px-2 text-slate-400 font-mono text-xs">{row.code}</td>
                      <td className="py-1 px-3 text-right font-mono text-slate-600">
                        {formatAccountingAmount(-Math.abs(row.amount), curr, { showSymbol: false })}
                      </td>
                      <td className="py-1 px-3" />
                    </tr>
                  ))
                )}
              </React.Fragment>
            ))}

            <tr className="border-t border-slate-300 font-semibold text-slate-900 bg-slate-50/30">
              <td colSpan={3} className="py-2 px-3 text-right">
                Total Operating Expenses:
              </td>
              <td className="py-2 px-3 text-right font-mono font-bold text-slate-800">
                {formatAccountingAmount(-Math.abs(statement.operating_expenses.total), curr, { showSymbol: false })}
              </td>
            </tr>

            {/* ========================================================== */}
            {/* 5. OPERATING PROFIT (EBIT)                                */}
            {/* ========================================================== */}
            <tr className="border-t border-b border-slate-700 bg-slate-50 font-bold text-slate-900">
              <td colSpan={3} className="py-2.5 px-3 uppercase tracking-wider text-xs">
                Operating Profit (EBIT)
              </td>
              <td className="py-2.5 px-3 text-right font-mono font-bold">
                {formatAccountingAmount(statement.operating_profit, curr, { showSymbol: true })}
              </td>
            </tr>

            {/* ========================================================== */}
            {/* 6. OTHER INCOME, FINANCE COSTS, TAX                       */}
            {/* ========================================================== */}
            {statement.sections.other_income.rows.length > 0 && (
              <>
                <tr className="bg-slate-50/50 font-semibold text-slate-800">
                  <td colSpan={4} className="py-1.5 px-3 text-xs uppercase">
                    Add: Other Income
                  </td>
                </tr>
                {statement.sections.other_income.rows.map((row) => (
                  <tr key={row.code} className="hover:bg-slate-50/50">
                    <td className="py-1 px-6 text-slate-700">{row.name}</td>
                    <td className="py-1 px-2 text-slate-400 font-mono text-xs">{row.code}</td>
                    <td className="py-1 px-3 text-right font-mono text-slate-600">
                      {formatAccountingAmount(row.amount, curr, { showSymbol: false })}
                    </td>
                    <td className="py-1 px-3" />
                  </tr>
                ))}
                <tr className="border-t border-slate-200 font-semibold text-slate-900">
                  <td colSpan={3} className="py-1.5 px-3 text-right text-xs">Total Other Income:</td>
                  <td className="py-1.5 px-3 text-right font-mono">
                    {formatAccountingAmount(statement.other_income, curr, { showSymbol: false })}
                  </td>
                </tr>
              </>
            )}

            {statement.sections.finance_costs.rows.length > 0 && (
              <>
                <tr className="bg-slate-50/50 font-semibold text-slate-800">
                  <td colSpan={4} className="py-1.5 px-3 text-xs uppercase">
                    Less: Finance Costs
                  </td>
                </tr>
                {statement.sections.finance_costs.rows.map((row) => (
                  <tr key={row.code} className="hover:bg-slate-50/50">
                    <td className="py-1 px-6 text-slate-700">{row.name}</td>
                    <td className="py-1 px-2 text-slate-400 font-mono text-xs">{row.code}</td>
                    <td className="py-1 px-3 text-right font-mono text-slate-600">
                      {formatAccountingAmount(-Math.abs(row.amount), curr, { showSymbol: false })}
                    </td>
                    <td className="py-1 px-3" />
                  </tr>
                ))}
                <tr className="border-t border-slate-200 font-semibold text-slate-900">
                  <td colSpan={3} className="py-1.5 px-3 text-right text-xs">Total Finance Costs:</td>
                  <td className="py-1.5 px-3 text-right font-mono">
                    {formatAccountingAmount(-Math.abs(statement.finance_costs), curr, { showSymbol: false })}
                  </td>
                </tr>
              </>
            )}

            {statement.sections.tax_expense.rows.length > 0 && (
              <>
                <tr className="bg-slate-50/50 font-semibold text-slate-800">
                  <td colSpan={4} className="py-1.5 px-3 text-xs uppercase">
                    Less: Tax Expense
                  </td>
                </tr>
                {statement.sections.tax_expense.rows.map((row) => (
                  <tr key={row.code} className="hover:bg-slate-50/50">
                    <td className="py-1 px-6 text-slate-700">{row.name}</td>
                    <td className="py-1 px-2 text-slate-400 font-mono text-xs">{row.code}</td>
                    <td className="py-1 px-3 text-right font-mono text-slate-600">
                      {formatAccountingAmount(-Math.abs(row.amount), curr, { showSymbol: false })}
                    </td>
                    <td className="py-1 px-3" />
                  </tr>
                ))}
                <tr className="border-t border-slate-200 font-semibold text-slate-900">
                  <td colSpan={3} className="py-1.5 px-3 text-right text-xs">Total Tax Expense:</td>
                  <td className="py-1.5 px-3 text-right font-mono">
                    {formatAccountingAmount(-Math.abs(statement.tax_expense), curr, { showSymbol: false })}
                  </td>
                </tr>
              </>
            )}

            {/* ========================================================== */}
            {/* 7. NET PROFIT / (LOSS) — THE AUDITED DOUBLE-UNDERLINE     */}
            {/* ========================================================== */}
            <tr className="border-t-2 border-slate-900 border-b-4 border-double border-slate-900 bg-slate-100 font-bold text-slate-950">
              <td colSpan={3} className="py-3 px-3 uppercase tracking-wider text-xs sm:text-sm">
                {statement.is_loss ? "Net Loss for the Period" : "Net Profit for the Period"}
              </td>
              <td className="py-3 px-3 text-right font-mono text-base sm:text-lg">
                {formatAccountingAmount(statement.net_profit, curr, { showSymbol: true })}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </ReportDocumentShell>
  );
}

