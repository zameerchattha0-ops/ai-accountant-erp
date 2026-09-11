"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Search, Trash2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import DraftDeleteButton from "@/components/shared/DraftDeleteButton";
import StatusMenu from "@/components/shared/StatusMenu";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Customer, Invoice } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface LineDraft {
  description: string;
  quantity: string;
  unit_price: string;
}

interface InvoiceForm {
  customer_id: string;
  invoice_date: string;
  payment_terms_days: string;
  notes: string;
  lines: LineDraft[];
}

const today = () => new Date().toISOString().slice(0, 10);

const addDays = (dateStr: string, days: number) => {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

type InvoiceRow = Invoice & {
  customer?: { name?: string } | { name?: string }[] | null;
};

type CustomerOption = Pick<Customer, "id" | "name">;

export default function InvoicesPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<InvoiceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");

  const [customers, setCustomers] = useState<CustomerOption[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [newCustomerName, setNewCustomerName] = useState("");
  const [creatingCustomer, setCreatingCustomer] = useState(false);
  const [form, setForm] = useState<InvoiceForm>({
    customer_id: "",
    invoice_date: today(),
    payment_terms_days: "30",
    notes: "",
    lines: [{ description: "", quantity: "1", unit_price: "" }],
  });

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("invoices")
      .select("*, customer:customers(name)")
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
      .from("customers")
      .select("id, name")
      .eq("organization_id", org.organization_id)
      .eq("is_active", true)
      .order("name")
      .then(({ data }) => setCustomers((data as CustomerOption[]) ?? []));
  }, [org]);

  // Inline customer creation — the New Invoice form never forces a detour
  // to the Customers page when the list is empty or the party is new.
  const handleCreateCustomer = useCallback(async () => {
    const name = newCustomerName.trim();
    if (!org || name.length < 2) return;
    setCreatingCustomer(true);
    setFormError(null);
    const supabase = createClient();
    const { data, error: insertError } = await supabase
      .from("customers")
      .insert({
        organization_id: org.organization_id,
        name,
        currency_code: org.base_currency_code,
      })
      .select("id, name")
      .single();
    setCreatingCustomer(false);
    if (insertError || !data) {
      setFormError(insertError?.message ?? "Could not create the customer");
      return;
    }
    const created = data as CustomerOption;
    setCustomers((prev) =>
      [...prev, created].sort((a, b) => a.name.localeCompare(b.name))
    );
    setForm((f) => ({ ...f, customer_id: created.id }));
    setNewCustomerName("");
  }, [org, newCustomerName]);

  const totals = useMemo(() => {
    const subtotal = form.lines.reduce(
      (sum, l) => sum + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0
    );
    return { subtotal, total: subtotal };
  }, [form.lines]);

  const filtered = (rows ?? []).filter((inv) => {
    if (statusFilter !== "ALL" && inv.status !== statusFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    const name = Array.isArray(inv.customer) ? inv.customer[0]?.name : inv.customer?.name;
    return (
      inv.invoice_number.toLowerCase().includes(q) ||
      (name ?? "").toLowerCase().includes(q)
    );
  });

  const setLine = (i: number, patch: Partial<LineDraft>) =>
    setForm((f) => ({
      ...f,
      lines: f.lines.map((l, idx) => (idx === i ? { ...l, ...patch } : l)),
    }));

  const handleSave = async () => {
    if (!org || !form.customer_id) { setFormError("Select a customer"); return; }
    const validLines = form.lines.filter(
      (l) => l.description.trim() && Number(l.quantity) > 0 && Number(l.unit_price) >= 0
    );
    if (validLines.length === 0) { setFormError("Add at least one line with a description, quantity and price"); return; }

    setSaving(true);
    setFormError(null);
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    const subtotal = validLines.reduce((s, l) => s + Number(l.quantity) * Number(l.unit_price), 0);
    const terms = Number(form.payment_terms_days) || 0;

    const { data: invoice, error: insertError } = await supabase
      .from("invoices")
      .insert({
        organization_id: org.organization_id,
        customer_id: form.customer_id,
        status: "DRAFT",
        invoice_date: form.invoice_date,
        due_date: terms > 0 ? addDays(form.invoice_date, terms) : null,
        payment_terms_days: terms > 0 ? terms : null,
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

    if (insertError || !invoice) {
      setSaving(false);
      setFormError(insertError?.message ?? "Failed to create invoice");
      return;
    }

    const { error: itemsError } = await supabase.from("invoice_items").insert(
      validLines.map((l, i) => ({
        organization_id: org.organization_id,
        invoice_id: invoice.id,
        line_number: i + 1,
        description: l.description.trim(),
        quantity: Number(l.quantity),
        unit_price: Number(l.unit_price),
        discount_amount: 0,
        tax_amount: 0,
        line_total: Number(l.quantity) * Number(l.unit_price),
      }))
    );

    if (itemsError) {
      // NEVER claim success on a partial write: roll the header back so no
      // orphan DRAFT invoice without its lines is left behind.
      await supabase.from("invoices").delete().eq("id", invoice.id);
      setSaving(false);
      setFormError(`Failed to save invoice lines: ${itemsError.message}`);
      return;
    }
    setModalOpen(false);
    setForm({
      customer_id: "", invoice_date: today(), payment_terms_days: "30",
      notes: "", lines: [{ description: "", quantity: "1", unit_price: "" }],
    });
    load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Invoices"
        subtitle="Sales invoices you've issued"
        actions={
          <button
            onClick={() => { setFormError(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New Invoice
          </button>
        }
      />

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            className={`${inputCls} pl-9`}
            placeholder="Search by number or customer…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          className={`${inputCls} max-w-40`}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {["ALL", "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "VOIDED", "CREDITED"].map((s) => (
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
          title={search || statusFilter !== "ALL" ? "No invoices match your filters" : "No invoices yet"}
          hint={search ? undefined : "Create one here, or tell the AI: \"Invoice ABC Technologies Rs. 500,000 for software development\"."}
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Number</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Due</th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
                <th className="px-4 py-3 font-medium text-right">Balance</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((inv) => {
                const customerName = Array.isArray(inv.customer) ? inv.customer[0]?.name : inv.customer?.name;
                const balance = inv.total - inv.amount_paid;
                return (
                  <tr key={inv.id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                    <td className="px-4 py-3">
                      <Link href={`/sales/invoices/${inv.id}`} className="font-medium text-ai-600 hover:text-ai-700 tabular-nums">
                        {inv.invoice_number}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-text-primary">{customerName ?? "-"}</td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums">{inv.invoice_date}</td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums">{inv.due_date ?? "-"}</td>
                    <td className="px-4 py-3 text-right text-text-primary tabular-nums font-medium">
                      {formatCurrency(inv.total, inv.currency_code)}
                    </td>
                    <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                      {balance > 0.005 ? formatCurrency(balance, inv.currency_code) : "-"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusMenu
                        table="invoices"
                        documentId={inv.id}
                        status={inv.status}
                        transitions={{
                          DRAFT: ["ISSUED"],
                          ISSUED: ["VOIDED"],
                        }}
                        onUpdated={load}
                        onError={setError}
                      />
                    </td>
                    <td className="px-4 py-3 text-right">
                      {inv.status === "DRAFT" && (
                        <DraftDeleteButton
                          table="invoices"
                          documentId={inv.id}
                          label="draft invoice"
                          onDeleted={load}
                          onError={setError}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* New Invoice Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="New Invoice" wide>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Customer *</label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.customer_id}
                onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
              >
                <option value="">Select customer…</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <div className="flex items-center gap-2 mt-1.5">
                <input
                  className={inputCls}
                  placeholder="New customer name — create it here"
                  value={newCustomerName}
                  onChange={(e) => setNewCustomerName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleCreateCustomer();
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={handleCreateCustomer}
                  disabled={creatingCustomer || newCustomerName.trim().length < 2}
                  className="shrink-0 px-3 py-2 rounded-xl text-xs font-medium text-white bg-ai-600 hover:bg-ai-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {creatingCustomer ? "Creating…" : "+ Create"}
                </button>
              </div>
              {customers.length === 0 && (
                <p className="text-[11px] text-warning-600 mt-1">
                  No customers yet - type a name above to create one without
                  leaving this form.
                </p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-text-secondary">Invoice date</label>
                <input type="date" className={`${inputCls} mt-1.5`} value={form.invoice_date}
                  onChange={(e) => setForm({ ...form, invoice_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-medium text-text-secondary">Terms (days)</label>
                <input type="number" min={0} className={`${inputCls} mt-1.5`} value={form.payment_terms_days}
                  onChange={(e) => setForm({ ...form, payment_terms_days: e.target.value })} />
              </div>
            </div>
          </div>

          {/* Lines */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-text-secondary">Line items</label>
              <button
                onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, { description: "", quantity: "1", unit_price: "" }] }))}
                className="text-xs font-medium text-ai-600 hover:text-ai-700"
              >
                + Add line
              </button>
            </div>
            <div className="space-y-2">
              {form.lines.map((line, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center">
                  <input
                    className={`${inputCls} col-span-6`}
                    placeholder="Description"
                    value={line.description}
                    onChange={(e) => setLine(i, { description: e.target.value })}
                  />
                  <input
                    className={`${inputCls} col-span-2 text-right`}
                    type="number" min="0" step="any" placeholder="Qty"
                    value={line.quantity}
                    onChange={(e) => setLine(i, { quantity: e.target.value })}
                  />
                  <input
                    className={`${inputCls} col-span-3 text-right`}
                    type="number" min="0" step="any" placeholder="Unit price"
                    value={line.unit_price}
                    onChange={(e) => setLine(i, { unit_price: e.target.value })}
                  />
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
            <label className="text-xs font-medium text-text-secondary">Notes (shown on invoice)</label>
            <textarea className={`${inputCls} mt-1.5 min-h-16 resize-y`} value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-bg-muted px-4 py-3 text-sm">
            <span className="text-text-secondary">Total</span>
            <span className="font-semibold text-text-primary tabular-nums">
              {formatCurrency(totals.total, org?.base_currency_code)}
            </span>
          </div>

          <p className="text-[11px] text-text-muted">
            Invoices are created in DRAFT status. Confirming or posting creates
            the accounting entries via the AI agent (double-entry enforced by the database).
          </p>
          {formError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{formError}</p>}

          <div className="flex justify-end gap-2">
            <button onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {saving ? "Creating…" : "Create Draft Invoice"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
