"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";
import type { TrialBalanceRow } from "@/lib/types/entities";

export default function TrialBalancePage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<TrialBalanceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .rpc("get_trial_balance", { target_org: org.organization_id });
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  const totalDebit = (rows ?? []).reduce((s, r) => s + r.total_debit, 0);
  const totalCredit = (rows ?? []).reduce((s, r) => s + r.total_credit, 0);
  const balanced = Math.abs(totalDebit - totalCredit) < 0.005;
  const currency = org?.base_currency_code;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Trial Balance"
        subtitle="Total debits and credits per account - posted entries only"
        logoUrl={org?.logo_url}
      />

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton rows={10} cols={6} />
      ) : error ? (
        <ErrorState message={error} />
      ) : (rows ?? []).length === 0 ? (
        <EmptyState
          title="No posted journal activity yet"
          hint={"The trial balance fills in as soon as journal entries are posted. Try telling the AI: \"I bought a laptop from ABC Computers for Rs. 150,000 on credit\"."}
        />
      ) : (
        <>
          <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                  <th className="px-4 py-3 font-medium w-28">Code</th>
                  <th className="px-4 py-3 font-medium">Account</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium text-right">Total Debit</th>
                  <th className="px-4 py-3 font-medium text-right">Total Credit</th>
                  <th className="px-4 py-3 font-medium text-right">Balance</th>
                </tr>
              </thead>
              <tbody>
                {(rows ?? []).map((r) => (
                  <tr key={r.account_id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-text-primary tabular-nums">{r.account_code}</td>
                    <td className="px-4 py-3 text-text-primary">{r.account_name}</td>
                    <td className="px-4 py-3 text-text-secondary">{r.account_type}</td>
                    <td className="px-4 py-3 text-right text-text-primary tabular-nums">
                      {r.total_debit > 0.005 ? formatCurrency(r.total_debit, currency) : "-"}
                    </td>
                    <td className="px-4 py-3 text-right text-text-primary tabular-nums">
                      {r.total_credit > 0.005 ? formatCurrency(r.total_credit, currency) : "-"}
                    </td>
                    <td className={cn(
                      "px-4 py-3 text-right tabular-nums font-medium",
                      r.balance >= 0 ? "text-text-primary" : "text-text-secondary"
                    )}>
                      {formatCurrency(Math.abs(r.balance), currency)}
                      <span className="text-[11px] text-text-muted ml-1">
                        {r.normal_balance === "DEBIT" ? "Dr" : "Cr"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border-default bg-bg-muted/50">
                  <td colSpan={3} className="px-4 py-3 font-semibold text-text-primary">Totals</td>
                  <td className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
                    {formatCurrency(totalDebit, currency)}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
                    {formatCurrency(totalCredit, currency)}
                  </td>
                  <td className="px-4 py-3" />
                </tr>
              </tfoot>
            </table>
          </div>

          <div className={cn(
            "flex items-center gap-2 rounded-xl px-4 py-3 text-sm",
            balanced
              ? "bg-success-50 text-success-700"
              : "bg-error-50 text-error-700"
          )}>
            {balanced ? (
              <CheckCircle2 className="w-4 h-4" />
            ) : (
              <XCircle className="w-4 h-4" />
            )}
            {balanced
              ? "In balance - total debits equal total credits."
              : `Out of balance by ${formatCurrency(totalDebit - totalCredit, currency)}. This should never happen; the database rejects unbalanced postings.`}
          </div>
        </>
      )}
    </div>
  );
}
