"use client";

import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { useServerList } from "@/lib/hooks/useServerList";
import { ilikeAny } from "@/lib/lists/logic";
import { formatCurrency } from "@/lib/utils/currency";
import AccountCombobox from "@/components/shared/AccountCombobox";
import PageHeader from "@/components/shared/PageHeader";
import Pagination from "@/components/shared/Pagination";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Account, GeneralLedgerRow } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

type AccountOption = Pick<
  Account,
  "id" | "code" | "name" | "account_type" | "parent_account_id"
>;

export default function GeneralLedgerPage() {
  const { org, loading: orgLoading } = useOrg();

  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [accountFilter, setAccountFilter] = useState("ALL");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  // SERVER-SIDE PAGING: the ledger is unbounded (target: 500k lines), so
  // account/date/search filters and the page window run in the database —
  // the browser never receives more than one page of lines (§4–§6).
  const {
    rows, error, refreshing, search, setSearch,
    page, setPage, pageSize, count, refresh,
  } = useServerList<GeneralLedgerRow>({
    enabled: !!org,
    filters: [accountFilter, fromDate, toDate],
    fetchPage: async ({ page, pageSize, search, signal }) => {
      if (!org) return { rows: [], count: 0 };
      const supabase = createClient();
      let query = supabase
        .from("v_general_ledger")
        .select(
          "journal_line_id, transaction_date, journal_number, account_id, account_code, account_name, line_description, entry_description, debit, credit",
          { count: "exact" }
        )
        .eq("organization_id", org.organization_id)
        .order("transaction_date", { ascending: true })
        .order("journal_number", { ascending: true })
        .order("line_number", { ascending: true })
        .range(page * pageSize, page * pageSize + pageSize - 1)
        .abortSignal(signal);
      if (accountFilter !== "ALL") query = query.eq("account_id", accountFilter);
      if (fromDate) query = query.gte("transaction_date", fromDate);
      if (toDate) query = query.lte("transaction_date", toDate);
      const expr = ilikeAny(
        [
          "journal_number",
          "account_code",
          "account_name",
          "line_description",
          "entry_description",
        ],
        search
      );
      if (expr) query = query.or(expr);
      const { data, error: dbError, count: total } = await query;
      if (dbError) throw dbError;
      return {
        rows: (data ?? []) as unknown as GeneralLedgerRow[],
        count: total ?? null,
      };
    },
  });

  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase
      .from("accounts")
      .select("id, code, name, account_type, parent_account_id")
      .eq("organization_id", org.organization_id)
      .eq("is_active", true)
      .order("code")
      .then(({ data }) => setAccounts((data as AccountOption[]) ?? []));
  }, [org]);

  // Search/filters run SERVER-SIDE (see the hook above) — the visible set is
  // the fetched page exactly as returned.
  const visible = useMemo(() => rows ?? [], [rows]);

  // Page-scoped totals, honestly labelled: a paged ledger footer cannot claim
  // to sum rows the browser never received (the Pagination row below carries
  // the full filtered count).
  const totalDebit = useMemo(
    () => visible.reduce((s, r) => s + r.debit, 0),
    [visible]
  );
  const totalCredit = useMemo(
    () => visible.reduce((s, r) => s + r.credit, 0),
    [visible]
  );

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="General Ledger"
        subtitle="Every posted journal line, account by account"
      />

      <div className="flex flex-col lg:flex-row gap-3 print:hidden">
        <AccountCombobox
          className="w-full lg:max-w-64"
          inputId="gl-account-filter"
          label="Filter by account"
          placeholder="All accounts"
          accounts={accounts}
          organizationId={org?.organization_id ?? ""}
          value={accountFilter === "ALL" ? "" : accountFilter}
          onChange={(id) => setAccountFilter(id || "ALL")}
          allowClear
          clearLabel="All accounts"
          allowCreate={false}
        />
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
            aria-label="Search ledger lines"
          />
        </div>
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton rows={10} cols={6} />
      ) : error ? (
        <ErrorState message={error} onRetry={refresh} />
      ) : visible.length === 0 ? (
        <EmptyState
          title="No posted ledger lines match your filters"
          hint="The general ledger only includes POSTED journal entries. Post an entry from the Journal page or via the AI agent."
        />
      ) : (
        <div className={`bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto transition-opacity ${refreshing ? "opacity-60" : ""}`}>
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
              {visible.map((r) => (
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
                  Page totals — {visible.length} of {count.toLocaleString()} lines
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

      <Pagination
        page={page}
        pageSize={pageSize}
        count={count}
        onPageChange={setPage}
        refreshing={refreshing}
      />
    </div>
  );
}
