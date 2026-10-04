"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Search } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { useServerList } from "@/lib/hooks/useServerList";
import { documentOrFilter, ilikeAny, sanitizeSearch } from "@/lib/lists/logic";
import { loadPartyTotals, type PartyTotals } from "@/lib/payments/summary";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import Pagination from "@/components/shared/Pagination";
import StatusBadge from "@/components/shared/StatusBadge";
import PartyCombobox from "@/components/shared/PartyCombobox";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Receipt, BankAccount, Invoice } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

const today = () => new Date().toISOString().slice(0, 10);

type ReceiptRow = Receipt & {
  customer?: { name?: string } | null;
  bank_account?: { account_name?: string } | null;
};
type BankOption = Pick<BankAccount, "id" | "account_name" | "bank_name" | "is_default">;
type InvoiceOption = Pick<Invoice, "id" | "invoice_number" | "total" | "amount_paid">;

interface ReceiptForm {
  customer_id: string;
  receipt_date: string;
  amount: string;
  payment_method: string;
  bank_account_id: string;
  reference: string;
  notes: string;
  invoice_id: string;
}

const EMPTY_FORM: ReceiptForm = {
  customer_id: "", receipt_date: today(), amount: "",
  payment_method: "BANK_TRANSFER", bank_account_id: "",
  reference: "", notes: "", invoice_id: "",
};

export default function ReceiptsPage() {
  const { org, loading: orgLoading } = useOrg();
  const [statusFilter, setStatusFilter] = useState("ALL");

  const [bankAccounts, setBankAccounts] = useState<BankOption[]>([]);
  const [invoices, setInvoices] = useState<InvoiceOption[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState<ReceiptForm>(EMPTY_FORM);

  // SERVER-SIDE LIST: status + search (receipt number, reference, matching
  // customer) run in the database; the browser holds one page of rows (§4–§6).
  const {
    rows, error, refreshing, search, setSearch,
    page, setPage, pageSize, count, refresh,
  } = useServerList<ReceiptRow>({
    enabled: !!org,
    filters: [statusFilter],
    fetchPage: async ({ page, pageSize, search, signal }) => {
      if (!org) return { rows: [], count: 0 };
      const supabase = createClient();

      let partyIds: string[] = [];
      if (sanitizeSearch(search)) {
        const { data: matches } = await supabase
          .from("customers")
          .select("id")
          .eq("organization_id", org.organization_id)
          .or(ilikeAny(["name", "customer_code"], search))
          .limit(200)
          .abortSignal(signal);
        partyIds = (matches ?? []).map((m) => (m as { id: string }).id);
      }

      let query = supabase
        .from("receipts")
        .select(
          "id, receipt_number, receipt_date, payment_method, amount, currency_code, reference, status, customer_id, bank_account_id, created_at, customer:customers(name)",
          { count: "exact" }
        )
        .eq("organization_id", org.organization_id)
        .order("created_at", { ascending: false })
        .order("id", { ascending: true })
        .range(page * pageSize, page * pageSize + pageSize - 1)
        .abortSignal(signal);
      if (statusFilter !== "ALL") query = query.eq("status", statusFilter);
      const expr = documentOrFilter(
        ["receipt_number", "reference"],
        "customer_id",
        search,
        partyIds
      );
      if (expr) query = query.or(expr);
      const { data, error: dbError, count: total } = await query;
      if (dbError) throw dbError;
      return { rows: (data ?? []) as unknown as ReceiptRow[], count: total ?? null };
    },
  });

  // KPI totals come from ONE aggregate (migration 089 RPC) — never from
  // reducing the fetched rows, which would turn tiles into page-local lies.
  const [totals, setTotals] = useState<PartyTotals | null>(null);
  const loadTotals = useCallback(async () => {
    if (!org) return;
    try {
      const t = await loadPartyTotals(
        createClient(),
        org.organization_id,
        "receipt"
      );
      setTotals(t);
    } catch {
      /* keep the last good totals; the list itself surfaces its own errors */
    }
  }, [org]);
  useEffect(() => {
    loadTotals();
  }, [loadTotals]);

  // Load bank accounts for the modal (bounded — the org owns few of them).
  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase.from("bank_accounts").select("id, account_name, bank_name, is_default")
      .eq("organization_id", org.organization_id)
      .eq("is_active", true).order("account_name")
      .then(({ data }) => setBankAccounts((data as BankOption[]) ?? []));
  }, [org]);

  // Load open invoices for selected customer
  useEffect(() => {
    if (!org || !form.customer_id) { setInvoices([]); return; }
    const supabase = createClient();
    supabase.from("invoices").select("id, invoice_number, total, amount_paid")
      .eq("organization_id", org.organization_id)
      .eq("customer_id", form.customer_id)
      .in("status", ["ISSUED", "PARTIALLY_PAID"])
      .order("invoice_date", { ascending: false })
      .then(({ data }) => setInvoices((data as InvoiceOption[]) ?? []));
  }, [org, form.customer_id]);

  const handleSave = async () => {
    if (!org) return;
    const amt = parseFloat(form.amount);
    if (!form.customer_id) { setFormError("Select a customer"); return; }
    if (!amt || amt <= 0) { setFormError("Enter a valid amount"); return; }

    setSaving(true); setFormError(null);
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();

    const { data: receipt, error: insertError } = await supabase
      .from("receipts")
      .insert({
        organization_id: org.organization_id,
        receipt_number: `RCT-${Date.now().toString(36).toUpperCase()}`,
        receipt_date: form.receipt_date,
        payment_method: form.payment_method,
        bank_account_id: form.bank_account_id || null,
        customer_id: form.customer_id,
        amount: amt,
        currency_code: org.base_currency_code,
        reference: form.reference.trim() || null,
        notes: form.notes.trim() || null,
        status: "COMPLETED",
        created_by: user?.id ?? null,
      })
      .select("id")
      .single();

    if (insertError || !receipt) {
      setSaving(false);
      setFormError(insertError?.message ?? "Failed to record receipt");
      return;
    }

    // If an invoice was selected, create allocation + update invoice amount_paid
    if (form.invoice_id) {
      await supabase.from("receipt_allocations").insert({
        organization_id: org.organization_id,
        receipt_id: receipt.id,
        invoice_id: form.invoice_id,
        amount_allocated: amt,
      });
      const inv = invoices.find((i) => i.id === form.invoice_id);
      if (inv) {
        const newPaid = Number(inv.amount_paid) + amt;
        const newStatus = newPaid >= Number(inv.total) ? "PAID" : "PARTIALLY_PAID";
        await supabase.from("invoices")
          .update({ amount_paid: newPaid, status: newStatus })
          .eq("id", form.invoice_id);
      }
    }

    setSaving(false);
    setModalOpen(false);
    setForm(EMPTY_FORM);
    refresh();
    loadTotals();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Receipts"
        subtitle="Customer payments received"
        actions={
          <button
            onClick={() => { setFormError(null); setForm(EMPTY_FORM); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> Record Receipt
          </button>
        }
      />

      {/* Summary cards — org-wide aggregates from ONE SQL pass (see
          lib/payments/summary.ts); "—" when the fallback scan was capped. */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Total Received</p>
          <p className="text-xl font-semibold text-success-600 tabular-nums mt-1"
            title={totals?.degraded ? "Dataset too large to total safely — narrow it or apply migration 089" : undefined}>
            {totals && !totals.degraded ? formatCurrency(totals.paid, org?.base_currency_code) : "—"}
          </p>
        </div>
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Pending</p>
          <p className="text-xl font-semibold text-warning-600 tabular-nums mt-1"
            title={totals?.degraded ? "Dataset too large to total safely — narrow it or apply migration 089" : undefined}>
            {totals && !totals.degraded ? formatCurrency(totals.pending, org?.base_currency_code) : "—"}
          </p>
        </div>
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Total Receipts</p>
          <p className="text-xl font-semibold text-text-primary tabular-nums mt-1">
            {totals && !totals.degraded ? totals.count : "—"}
          </p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input className={`${inputCls} pl-9`} placeholder="Search by number or customer…"
            value={search} onChange={(e) => setSearch(e.target.value)}
            aria-label="Search receipts" />
        </div>
        <select className={`${inputCls} max-w-40`} value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status">
          {["ALL", "COMPLETED", "PENDING", "CANCELLED", "REVERSED"].map((s) => (
            <option key={s} value={s}>{s === "ALL" ? "All statuses" : s}</option>
          ))}
        </select>
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton cols={6} />
      ) : error ? (
        <ErrorState message={error} onRetry={refresh} />
      ) : (rows ?? []).length === 0 ? (
        <EmptyState
          title={search || statusFilter !== "ALL" ? "No receipts match your filters" : "No receipts recorded yet"}
          hint={search ? undefined : "Record a customer receipt here, or tell the AI: \"I received Rs. 100,000 from ABC Corp\"."}
        />
      ) : (
        <div className={`bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto transition-opacity ${refreshing ? "opacity-60" : ""}`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Number</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Method</th>
                <th className="px-4 py-3 font-medium text-right">Amount</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((r) => (
                <tr key={r.id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                  <td className="px-4 py-3 font-medium text-text-primary tabular-nums">{r.receipt_number}</td>
                  <td className="px-4 py-3 text-text-primary">{r.customer?.name ?? "-"}</td>
                  <td className="px-4 py-3 text-text-secondary tabular-nums">{r.receipt_date}</td>
                  <td className="px-4 py-3 text-text-secondary">{r.payment_method}</td>
                  <td className="px-4 py-3 text-right text-text-primary tabular-nums font-medium">
                    {formatCurrency(Number(r.amount), r.currency_code ?? org?.base_currency_code)}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                </tr>
              ))}
            </tbody>
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

      {/* Record Receipt Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Record Customer Receipt" wide>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="receipt-customer" className="text-xs font-medium text-text-secondary">Customer *</label>
              <div className="mt-1.5">
                <PartyCombobox
                  kind="customer"
                  organizationId={org?.organization_id ?? ""}
                  value={form.customer_id}
                  onChange={(id) => setForm((f) => ({ ...f, customer_id: id, invoice_id: "" }))}
                  inputId="receipt-customer"
                  label="Customer"
                  baseCurrency={org?.base_currency_code}
                />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Receipt date</label>
              <input type="date" className={`${inputCls} mt-1.5`} value={form.receipt_date}
                onChange={(e) => setForm({ ...form, receipt_date: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Amount *</label>
              <input type="number" min="0" step="any" className={`${inputCls} mt-1.5`} placeholder="0.00"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Method</label>
              <select className={`${inputCls} mt-1.5`} value={form.payment_method}
                onChange={(e) => setForm({ ...form, payment_method: e.target.value })}>
                {["BANK_TRANSFER", "CASH", "CHEQUE", "CARD", "ONLINE", "OTHER"].map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Bank account</label>
              <select className={`${inputCls} mt-1.5`} value={form.bank_account_id}
                onChange={(e) => setForm({ ...form, bank_account_id: e.target.value })}>
                <option value="">Select account…</option>
                {bankAccounts.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.account_name} ({b.bank_name}){b.is_default ? " ★" : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {invoices.length > 0 && (
            <div>
              <label className="text-xs font-medium text-text-secondary">Allocate to invoice (optional)</label>
              <select className={`${inputCls} mt-1.5`} value={form.invoice_id}
                onChange={(e) => setForm({ ...form, invoice_id: e.target.value })}>
                <option value="">No allocation</option>
                {invoices.map((inv) => {
                  const balance = Number(inv.total) - Number(inv.amount_paid);
                  return (
                    <option key={inv.id} value={inv.id}>
                      {inv.invoice_number} - balance: {formatCurrency(balance, org?.base_currency_code)}
                    </option>
                  );
                })}
              </select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Reference</label>
              <input className={`${inputCls} mt-1.5`} placeholder="Cheque / txn ref"
                value={form.reference}
                onChange={(e) => setForm({ ...form, reference: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Notes</label>
              <input className={`${inputCls} mt-1.5`}
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
          </div>

          <p className="text-[11px] text-text-muted">
            The journal entry (Dr Bank, Cr Receivable) will be created by the AI agent. This records the receipt for tracking.
          </p>
          {formError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{formError}</p>}
          <div className="flex justify-end gap-2">
            <button onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {saving ? "Recording…" : "Record Receipt"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
