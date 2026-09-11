"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Search, Trash2, Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import DraftDeleteButton from "@/components/shared/DraftDeleteButton";
import StatusMenu from "@/components/shared/StatusMenu";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { PurchaseBill, Supplier, Account } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface LineDraft {
  description: string;
  quantity: string;
  unit_price: string;
  expense_account_id: string;
}

interface BillForm {
  supplier_id: string;
  bill_date: string;
  payment_terms_days: string;
  supplier_invoice_ref: string;
  notes: string;
  lines: LineDraft[];
}

const today = () => new Date().toISOString().slice(0, 10);
const addDays = (dateStr: string, days: number) => {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

type BillRow = PurchaseBill & {
  supplier?: { name?: string } | { name?: string }[] | null;
};
type SupplierOption = Pick<Supplier, "id" | "name">;
type AccountOption = Pick<Account, "id" | "code" | "name" | "account_type">;

export default function PurchaseBillsPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<BillRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");

  const [suppliers, setSuppliers] = useState<SupplierOption[]>([]);
  const [expenseAccounts, setExpenseAccounts] = useState<AccountOption[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState<BillForm>({
    supplier_id: "",
    bill_date: today(),
    payment_terms_days: "30",
    supplier_invoice_ref: "",
    notes: "",
    lines: [{ description: "", quantity: "1", unit_price: "", expense_account_id: "" }],
  });

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("purchase_bills")
      .select("*, supplier:suppliers(name)")
      .eq("organization_id", org.organization_id)
      .order("created_at", { ascending: false });
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase
      .from("suppliers")
      .select("id, name")
      .eq("organization_id", org.organization_id)
      .eq("is_active", true)
      .order("name")
      .then(({ data }) => setSuppliers((data as SupplierOption[]) ?? []));
    supabase
      .from("accounts")
      .select("id, code, name, account_type")
      .eq("organization_id", org.organization_id)
      .eq("account_type", "EXPENSE")
      .eq("is_active", true)
      .order("code")
      .then(({ data }) => setExpenseAccounts((data as AccountOption[]) ?? []));
  }, [org]);

  const total = useMemo(
    () => form.lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0),
    [form.lines]
  );

  const filtered = (rows ?? []).filter((bill) => {
    if (statusFilter !== "ALL" && bill.status !== statusFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    const name = Array.isArray(bill.supplier) ? bill.supplier[0]?.name : bill.supplier?.name;
    return (
      bill.bill_number.toLowerCase().includes(q) ||
      (name ?? "").toLowerCase().includes(q) ||
      (bill.supplier_invoice_ref ?? "").toLowerCase().includes(q)
    );
  });

  const setLine = (i: number, patch: Partial<LineDraft>) =>
    setForm((f) => ({
      ...f,
      lines: f.lines.map((l, idx) => (idx === i ? { ...l, ...patch } : l)),
    }));

  const handleSave = async () => {
    if (!org || !form.supplier_id) { setFormError("Select a supplier"); return; }
    const validLines = form.lines.filter(
      (l) => l.description.trim() && Number(l.quantity) > 0 && Number(l.unit_price) >= 0
    );
    if (validLines.length === 0) { setFormError("Add at least one line"); return; }

    setSaving(true);
    setFormError(null);
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    const subtotal = validLines.reduce((s, l) => s + Number(l.quantity) * Number(l.unit_price), 0);
    const terms = Number(form.payment_terms_days) || 0;

    const { data: bill, error: insertError } = await supabase
      .from("purchase_bills")
      .insert({
        organization_id: org.organization_id,
        supplier_id: form.supplier_id,
        status: "DRAFT",
        bill_date: form.bill_date,
        due_date: terms > 0 ? addDays(form.bill_date, terms) : null,
        payment_terms_days: terms > 0 ? terms : null,
        supplier_invoice_ref: form.supplier_invoice_ref.trim() || null,
        currency_code: org.base_currency_code,
        subtotal,
        discount_total: 0,
        tax_total: 0,
        total: subtotal,
        amount_paid: 0,
        notes: form.notes.trim() || null,
        created_by: user?.id ?? null,
      })
      .select("id")
      .single();

    if (insertError || !bill) {
      setSaving(false);
      setFormError(insertError?.message ?? "Failed to create bill");
      return;
    }

    const { error: itemsError } = await supabase.from("purchase_bill_items").insert(
      validLines.map((l, i) => ({
        organization_id: org.organization_id,
        bill_id: bill.id,
        line_number: i + 1,
        description: l.description.trim(),
        quantity: Number(l.quantity),
        unit_price: Number(l.unit_price),
        discount_amount: 0,
        tax_amount: 0,
        line_total: Number(l.quantity) * Number(l.unit_price),
        expense_account_id: l.expense_account_id || null,
      }))
    );

    setSaving(false);
    if (itemsError) { setFormError(itemsError.message); return; }
    setModalOpen(false);
    setForm({
      supplier_id: "", bill_date: today(), payment_terms_days: "30",
      supplier_invoice_ref: "", notes: "",
      lines: [{ description: "", quantity: "1", unit_price: "", expense_account_id: "" }],
    });
    load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Purchase Bills"
        subtitle="Supplier bills you've recorded"
        actions={
          <button
            onClick={() => { setFormError(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New Bill
          </button>
        }
      />

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            className={`${inputCls} pl-9`}
            placeholder="Search by number or supplier…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className={`${inputCls} max-w-40`} value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}>
          {["ALL", "DRAFT", "OPEN", "PARTIALLY_PAID", "PAID", "OVERDUE", "VOIDED"].map((s) => (
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
          title={search || statusFilter !== "ALL" ? "No bills match your filters" : "No purchase bills yet"}
          hint={search ? undefined : "Record one here, or tell the AI: \"I bought a laptop from ABC Computers for Rs. 150,000 on credit\"."}
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Number</th>
                <th className="px-4 py-3 font-medium">Supplier</th>
                <th className="px-4 py-3 font-medium">Ref</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
                <th className="px-4 py-3 font-medium text-right">Balance</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((bill) => {
                const supplierName = Array.isArray(bill.supplier)
                  ? bill.supplier[0]?.name
                  : bill.supplier?.name;
                const balance = bill.total - bill.amount_paid;
                return (
                  <tr key={bill.id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-text-primary tabular-nums">{bill.bill_number}</td>
                    <td className="px-4 py-3 text-text-primary">{supplierName ?? "-"}</td>
                    <td className="px-4 py-3 text-text-secondary">{bill.supplier_invoice_ref ?? "-"}</td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums">{bill.bill_date}</td>
                    <td className="px-4 py-3 text-right text-text-primary tabular-nums font-medium">
                      {formatCurrency(bill.total, bill.currency_code)}
                    </td>
                    <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                      {balance > 0.005 ? formatCurrency(balance, bill.currency_code) : "-"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusMenu
                        table="purchase_bills"
                        documentId={bill.id}
                        status={bill.status}
                        transitions={{
                          DRAFT: ["OPEN"],
                          OPEN: ["VOIDED"],
                        }}
                        onUpdated={load}
                        onError={setError}
                      />
                    </td>
                    <td className="px-4 py-3 text-right">
                      {bill.status === "DRAFT" && (
                        <DraftDeleteButton
                          table="purchase_bills"
                          documentId={bill.id}
                          label="draft bill"
                          onDeleted={load}
                          onError={setError}
                        />
                      )}
                      <Link
                        href={`/purchases/bills/${bill.id}`}
                        aria-label={`Print bill ${bill.bill_number}`}
                        className="inline-flex items-center gap-1 ml-3 text-xs font-medium text-text-muted hover:text-ai-600 transition-colors"
                      >
                        <Printer className="w-3.5 h-3.5" /> Print
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* New Bill Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="New Purchase Bill" wide>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Supplier *</label>
              <select className={`${inputCls} mt-1.5`} value={form.supplier_id}
                onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}>
                <option value="">Select supplier…</option>
                {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              {suppliers.length === 0 && (
                <p className="text-[11px] text-warning-600 mt-1">
                  No suppliers yet - add one on the Suppliers page first.
                </p>
              )}
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-xs font-medium text-text-secondary">Bill date</label>
                <input type="date" className={`${inputCls} mt-1.5`} value={form.bill_date}
                  onChange={(e) => setForm({ ...form, bill_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-medium text-text-secondary">Terms</label>
                <input type="number" min={0} className={`${inputCls} mt-1.5`} value={form.payment_terms_days}
                  onChange={(e) => setForm({ ...form, payment_terms_days: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-medium text-text-secondary">Supplier ref</label>
                <input className={`${inputCls} mt-1.5`} value={form.supplier_invoice_ref}
                  onChange={(e) => setForm({ ...form, supplier_invoice_ref: e.target.value })}
                  placeholder="Their inv #" />
              </div>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-text-secondary">Line items</label>
              <button
                onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, { description: "", quantity: "1", unit_price: "", expense_account_id: "" }] }))}
                className="text-xs font-medium text-ai-600 hover:text-ai-700"
              >
                + Add line
              </button>
            </div>
            <div className="space-y-2">
              {form.lines.map((line, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center">
                  <input className={`${inputCls} col-span-5`} placeholder="Description"
                    value={line.description}
                    onChange={(e) => setLine(i, { description: e.target.value })} />
                  <select className={`${inputCls} col-span-3`} value={line.expense_account_id}
                    onChange={(e) => setLine(i, { expense_account_id: e.target.value })}>
                    <option value="">Expense account…</option>
                    {expenseAccounts.map((a) => (
                      <option key={a.id} value={a.id}>{a.code} - {a.name}</option>
                    ))}
                  </select>
                  <input className={`${inputCls} col-span-1 text-right`} type="number" min="0" step="any" placeholder="Qty"
                    value={line.quantity}
                    onChange={(e) => setLine(i, { quantity: e.target.value })} />
                  <input className={`${inputCls} col-span-2 text-right`} type="number" min="0" step="any" placeholder="Price"
                    value={line.unit_price}
                    onChange={(e) => setLine(i, { unit_price: e.target.value })} />
                  <button
                    onClick={() => setForm((f) => ({ ...f, lines: f.lines.filter((_, idx) => idx !== i) }))}
                    disabled={form.lines.length === 1}
                    className="col-span-1 p-2 rounded-lg text-text-muted hover:text-error-600 hover:bg-error-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    aria-label="Remove line"
                  >
                    <Trash2 className="w-4 h-4 mx-auto" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary">Notes</label>
            <textarea className={`${inputCls} mt-1.5 min-h-16 resize-y`} value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-bg-muted px-4 py-3 text-sm">
            <span className="text-text-secondary">Total</span>
            <span className="font-semibold text-text-primary tabular-nums">
              {formatCurrency(total, org?.base_currency_code)}
            </span>
          </div>

          <p className="text-[11px] text-text-muted">
            Bills are recorded in DRAFT. The payable journal entry is created by
            the AI agent when posting (double-entry enforced by the database).
          </p>
          {formError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{formError}</p>}

          <div className="flex justify-end gap-2">
            <button onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {saving ? "Creating…" : "Create Draft Bill"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
