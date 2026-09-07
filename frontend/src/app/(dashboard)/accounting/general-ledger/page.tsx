"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Account, GeneralLedgerRow } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

type AccountOption = Pick<Account, "id" | "code" | "name">;

export default function GeneralLedgerPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<GeneralLedgerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [accountFilter, setAccountFilter] = useState("ALL");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    let query = supabase
      .from("v_general_ledger")
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("transaction_date", { ascending: true })
      .order("journal_number", { ascending: true })
      .order("line_number", { ascending: true });
    if (accountFilter !== "ALL") query = query.eq("account_id", accountFilter);
    if (fromDate) query = query.gte("transaction_date", fromDate);
    if (toDate) query = query.lte("transaction_date", toDate);
    const { data, error: dbError } = await query;
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org, accountFilter, fromDate, toDate]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase
      .from("accounts")
      .select("id, code, name")
      .eq("organization_id", org.organization_id)
      .eq("is_active", true)
      .order("code")
      .then(({ data }) => setAccounts((data as AccountOption[]) ?? []));
  }, [org]);

  const filtered = useMemo(() => {
    if (!search) return rows ?? [];
    const q = search.toLowerCase();
    return (rows ?? []).filter(
      (r) =>
        r.journal_number.toLowerCase().includes(q) ||
        r.account_code.toLowerCase().includes(q) ||
        r.account_name.toLowerCase().includes(q) ||
        (r.line_description ?? "").toLowerCase().includes(q) ||
        r.entry_description.toLowerCase().includes(q)
    );
  }, [rows, search]);

  const totalDebit = filtered.reduce((s, r) => s + r.debit, 0);
  const totalCredit = filtered.reduce((s, r) => s + r.credit, 0);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="General Ledger"
        subtitle="Every posted journal line, account by account"
      />

      <div className="flex flex-col lg:flex-row gap-3">
        <select className={`${inputCls} lg:max-w-64`} value={accountFilter}
          onChange={(e) => setAccountFilter(e.target.value)}>
          <option value="ALL">All accounts</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.code} - {a.name}</option>
          ))}
        </select>
        <div className="flex items-center gap-2">
          <input type="date" className={`${inputCls} w-40`} value={fromDate}
            onChange={(e) => setFromDate(e.target.value)} aria-label="From date" />
          <span className="text-xs text-text-muted">to</span>
          <input type="date" className={`${inputCls} w-40`} value={toDate}
            onChange={(e) => setToDate(e.target.value)} aria-label="To date" />
        </div>
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            className={`${inputCls} pl-9`}
            placeholder="Search description or number…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton rows={10} cols={6} />
      ) : error ? (
        <ErrorState message={error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No posted ledger lines match your filters"
          hint="The general ledger only includes POSTED journal entries. Post an entry from the Journal page or via the AI agent."
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Entry</th>
                <th className="px-4 py-3 font-medium">Account</th>
                <th className="px-4 py-3 font-medium">Description</th>
                <th className="px-4 py-3 font-medium text-right">Debit</th>
                <th className="px-4 py-3 font-medium text-right">Credit</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.journal_line_id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                  <td className="px-4 py-3 text-text-secondary tabular-nums whitespace-nowrap">{r.transaction_date}</td>
                  <td className="px-4 py-3 text-text-primary tabular-nums">{r.journal_number}</td>
                  <td className="px-4 py-3 text-text-primary whitespace-nowrap">
                    <span className="tabular-nums text-text-secondary mr-1.5">{r.account_code}</span>
                    {r.account_name}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {r.line_description ?? r.entry_description}
                  </td>
                  <td className="px-4 py-3 text-right text-text-primary tabular-nums">
                    {r.debit > 0.005 ? formatCurrency(r.debit, org?.base_currency_code) : "-"}
                  </td>
                  <td className="px-4 py-3 text-right text-text-primary tabular-nums">
                    {r.credit > 0.005 ? formatCurrency(r.credit, org?.base_currency_code) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border-default bg-bg-muted/50">
                <td colSpan={4} className="px-4 py-3 font-semibold text-text-primary">
                  {filtered.length} lines
                </td>
                <td className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
                  {formatCurrency(totalDebit, org?.base_currency_code)}
                </td>
                <td className="px-4 py-3 text-right font-semibold text-text-primary tabular-nums">
                  {formatCurrency(totalCredit, org?.base_currency_code)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
