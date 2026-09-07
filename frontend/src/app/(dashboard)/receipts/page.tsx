"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Receipt, Customer, BankAccount, Invoice } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

const today = () => new Date().toISOString().slice(0, 10);

type ReceiptRow = Receipt & {
  customer?: { name?: string } | null;
  bank_account?: { account_name?: string } | null;
};
type CustomerOption = Pick<Customer, "id" | "name">;
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
  const [rows, setRows] = useState<ReceiptRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");

  const [customers, setCustomers] = useState<CustomerOption[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankOption[]>([]);
  const [invoices, setInvoices] = useState<InvoiceOption[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState<ReceiptForm>(EMPTY_FORM);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("receipts")
      .select("*, customer:customers(name), bank_account:bank_accounts(account_name)")
      .eq("organization_id", org.organization_id)
      .order("created_at", { ascending: false });
    if (dbError) setError(dbError.message);
    else setRows((data as ReceiptRow[]) ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  // Load customers and bank accounts for the modal
  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase.from("customers").select("id, name")
      .eq("organization_id", org.organization_id)
      .eq("is_active", true).order("name")
      .then(({ data }) => setCustomers((data as CustomerOption[]) ?? []));
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

  const totalReceived = useMemo(() =>
    (rows ?? []).filter((r) => r.status === "COMPLETED")
      .reduce((s, r) => s + Number(r.amount), 0), [rows]);
  const totalPending = useMemo(() =>
    (rows ?? []).filter((r) => r.status === "PENDING")
      .reduce((s, r) => s + Number(r.amount), 0), [rows]);

  const filtered = (rows ?? []).filter((r) => {
    if (statusFilter !== "ALL" && r.status !== statusFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    const customerName = r.customer?.name ?? "";
    return r.receipt_number.toLowerCase().includes(q) ||
      customerName.toLowerCase().includes(q) ||
      (r.reference ?? "").toLowerCase().includes(q);
  });

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
    load();
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

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Total Received</p>
          <p className="text-xl font-semibold text-success-600 tabular-nums mt-1">
            {formatCurrency(totalReceived, org?.base_currency_code)}
          </p>
        </div>
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Pending</p>
          <p className="text-xl font-semibold text-warning-600 tabular-nums mt-1">
            {formatCurrency(totalPending, org?.base_currency_code)}
          </p>
        </div>
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Total Receipts</p>
          <p className="text-xl font-semibold text-text-primary tabular-nums mt-1">{(rows ?? []).length}</p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input className={`${inputCls} pl-9`} placeholder="Search by number or customer…"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className={`${inputCls} max-w-40`} value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}>
          {["ALL", "COMPLETED", "PENDING", "CANCELLED", "REVERSED"].map((s) => (
            <option key={s} value={s}>{s === "ALL" ? "All statuses" : s}</option>
          ))}
        </select>
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton cols={6} />
      ) : error ? (
        <ErrorState message={error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={search || statusFilter !== "ALL" ? "No receipts match your filters" : "No receipts recorded yet"}
          hint={search ? undefined : "Record a customer receipt here, or tell the AI: \"I received Rs. 100,000 from ABC Corp\"."}
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
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
              {filtered.map((r) => (
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

      {/* Record Receipt Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Record Customer Receipt" wide>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Customer *</label>
              <select className={`${inputCls} mt-1.5`} value={form.customer_id}
                onChange={(e) => setForm({ ...form, customer_id: e.target.value, invoice_id: "" })}>
                <option value="">Select customer…</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
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
