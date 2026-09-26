"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Search, Trash2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusMenu from "@/components/shared/StatusMenu";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Customer } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface LineDraft {
  description: string;
  quantity: string;
  unit_price: string;
}

interface CreditNoteForm {
  customer_id: string;
  invoice_id: string;
  credit_note_date: string;
  reason: string;
  lines: LineDraft[];
}

const today = () => new Date().toISOString().slice(0, 10);

/** Business-valid status transitions (invoice_status enum). */
const CN_TRANSITIONS: Record<string, string[]> = {
  DRAFT: ["ISSUED", "VOIDED"],
  ISSUED: ["VOIDED"],
};

type CustomerOption = Pick<Customer, "id" | "name">;

interface CreditNoteRow {
  id: string;
  credit_note_number: string;
  credit_note_date: string;
  status: string;
  reason: string | null;
  total: number;
  customer_id: string;
  invoice_id: string | null;
  customer_name?: string;
}

export default function CreditNotesPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<CreditNoteRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [customers, setCustomers] = useState<CustomerOption[]>([]);
  const [invoices, setInvoices] = useState<{ id: string; invoice_number: string }[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [newCustomerName, setNewCustomerName] = useState("");
  const [creatingCustomer, setCreatingCustomer] = useState(false);
  const [form, setForm] = useState<CreditNoteForm>({
    customer_id: "",
    invoice_id: "",
    credit_note_date: today(),
    reason: "",
    lines: [{ description: "", quantity: "1", unit_price: "" }],
  });

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("credit_notes")
      .select("*, customer:customers(name)")
      .eq("organization_id", org.organization_id)
      .order("created_at", { ascending: false });
    if (dbError) setError(dbError.message);
    else {
      setRows(
        ((data ?? []) as (CreditNoteRow & { customer: { name?: string } | null })[]).map(
          (r) => ({
            ...r,
            customer_name: r.customer?.name ?? "",
          })
        )
      );
    }
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

  // Invoices of the selected customer — the reference is optional but
  // grounds the credit note against the original sale.
  useEffect(() => {
    if (!org || !form.customer_id) {
      setInvoices([]);
      return;
    }
    const supabase = createClient();
    supabase
      .from("invoices")
      .select("id, invoice_number")
      .eq("organization_id", org.organization_id)
      .eq("customer_id", form.customer_id)
      .order("invoice_number", { ascending: false })
      .then(({ data }) =>
        setInvoices(
          (data as { id: string; invoice_number: string }[]) ?? []
        )
      );
  }, [org, form.customer_id]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (rows ?? []).filter((r) => {
      if (statusFilter !== "ALL" && r.status !== statusFilter) return false;
      if (!q) return true;
      return (
        r.credit_note_number?.toLowerCase().includes(q) ||
        (r.customer_name ?? "").toLowerCase().includes(q) ||
        (r.reason ?? "").toLowerCase().includes(q)
      );
    });
  }, [rows, search, statusFilter]);

  const totals = useMemo(() => {
    const subtotal = form.lines.reduce(
      (s, l) =>
        s + (parseFloat(l.quantity || "0") || 0) * (parseFloat(l.unit_price || "0") || 0),
      0
    );
    return { subtotal, total: subtotal };
  }, [form.lines]);

  const setLine = (i: number, patch: Partial<LineDraft>) =>
    setForm((f) => ({
      ...f,
      lines: f.lines.map((l, idx) => (idx === i ? { ...l, ...patch } : l)),
    }));

  const resetForm = () => {
    setForm({
      customer_id: "",
      invoice_id: "",
      credit_note_date: today(),
      reason: "",
      lines: [{ description: "", quantity: "1", unit_price: "" }],
    });
    setFormError(null);
    setNewCustomerName("");
  };

  // Inline customer creation — never a detour to the Customers page.
  const handleCreateCustomer = useCallback(async () => {
    const name = newCustomerName.trim();
    if (!name || !org || creatingCustomer) return;
    setCreatingCustomer(true);
    setFormError(null);
    const supabase = createClient();
    const { data, error: insError } = await supabase
      .from("customers")
      .insert({ organization_id: org.organization_id, name, is_active: true })
      .select("id, name")
      .single();
    setCreatingCustomer(false);
    if (insError || !data) {
      setFormError(insError?.message ?? "Could not create the customer.");
      return;
    }
    setCustomers((c) =>
      [...c, data as CustomerOption].sort((a, b) => a.name.localeCompare(b.name))
    );
    setForm((f) => ({ ...f, customer_id: (data as { id: string }).id, invoice_id: "" }));
    setNewCustomerName("");
  }, [newCustomerName, org, creatingCustomer]);

  const handleSave = useCallback(async () => {
    if (!org) return;
    const validLines = form.lines.filter(
      (l) =>
        l.description.trim() &&
        (parseFloat(l.quantity || "0") || 0) > 0 &&
        (parseFloat(l.unit_price || "0") || 0) >= 0
    );
    if (!form.customer_id) {
      setFormError("Select a customer.");
      return;
    }
    if (!form.reason.trim()) {
      setFormError("A reason is required — refund, discount or correction.");
      return;
    }
    if (validLines.length === 0) {
      setFormError("Add at least one line with a description and quantity.");
      return;
    }
    setSaving(true);
    setFormError(null);
    const supabase = createClient();
    const { data: authData } = await supabase.auth.getUser();
    // credit_note_number is assigned by the DB trigger (CN-####).
    const { data: note, error: noteError } = await supabase
      .from("credit_notes")
      .insert({
        organization_id: org.organization_id,
        customer_id: form.customer_id,
        invoice_id: form.invoice_id || null,
        credit_note_date: form.credit_note_date,
        reason: form.reason.trim(),
        status: "DRAFT",
        subtotal: totals.subtotal,
        discount_total: 0,
        tax_total: 0,
        total: totals.total,
        currency_code: org.base_currency_code ?? "PKR",
        created_by: authData.user?.id ?? null,
      })
      .select()
      .single();
    if (noteError || !note) {
      setSaving(false);
      setFormError(noteError?.message ?? "Could not create the credit note.");
      return;
    }
    const itemRows = validLines.map((l, i) => {
      const quantity = parseFloat(l.quantity || "0") || 0;
      const unit_price = parseFloat(l.unit_price || "0") || 0;
      return {
        organization_id: org.organization_id,
        credit_note_id: (note as { id: string }).id,
        line_number: i + 1,
        description: l.description.trim(),
        quantity,
        unit_price,
        line_total: quantity * unit_price,
      };
    });
    const { error: itemsError } = await supabase
      .from("credit_note_items")
      .insert(itemRows);
    setSaving(false);
    if (itemsError) {
      setFormError(itemsError.message);
      return;
    }
    setModalOpen(false);
    resetForm();
    await load();
  }, [org, form, totals, load]);

  if (orgLoading || rows === null) {
    return (
      <div className="space-y-4">
        <TableSkeleton rows={6} cols={5} />
      </div>
    );
  }
  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Credit Notes"
        subtitle="Issue credit notes against issued invoices — refunds, discounts and corrections. Every note reverses revenue and adjusts the customer's balance."
        actions={
          <button
            onClick={() => {
              resetForm();
              setModalOpen(true);
            }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New Credit Note
          </button>
        }
      />

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by note number, customer or reason…"
            className={`${inputCls} pl-9`}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={`${inputCls} sm:w-44`}
        >
          <option value="ALL">All statuses</option>
          <option value="DRAFT">Draft</option>
          <option value="ISSUED">Issued</option>
          <option value="VOIDED">Voided</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Note #</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Reason</th>
                <th className="px-4 py-3 font-medium text-right">Amount</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10">
                    <EmptyState
                      title="No credit notes yet"
                      hint="Ask the AI: “Issue a credit note against invoice INV-000001 for Rs. 50,000” — or create one above."
                    />
                  </td>
                </tr>
              )}
              {filtered.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-border-subtle last:border-0 hover:bg-bg-muted/50 transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-text-primary tabular-nums">
                    {r.credit_note_number}
                  </td>
                  <td className="px-4 py-3 text-text-secondary tabular-nums">
                    {r.credit_note_date}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {r.customer_name || "—"}
                  </td>
                  <td className="px-4 py-3 text-text-secondary max-w-[260px] truncate">
                    {r.reason || "—"}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums font-medium text-text-primary">
                    {formatCurrency(Number(r.total), org?.base_currency_code)}
                  </td>
                  <td className="px-4 py-3">
                    <StatusMenu
                      table="credit_notes"
                      documentId={r.id}
                      status={r.status}
                      transitions={CN_TRANSITIONS}
                      onUpdated={load}
                      onError={setError}
                    />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/sales/credit-notes/${r.id}`}
                      className="text-xs font-medium text-ai-600 hover:text-ai-700"
                    >
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* New credit note modal */}
      <Modal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          resetForm();
        }}
        title="New Credit Note"
        wide
      >
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium text-text-secondary">Customer</label>
            <select
              className={`${inputCls} mt-1.5`}
              value={form.customer_id}
              onChange={(e) =>
                setForm((f) => ({ ...f, customer_id: e.target.value, invoice_id: "" }))
              }
            >
              <option value="">Select customer…</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <div className="flex gap-2 mt-2">
              <input
                className={inputCls}
                placeholder="…or create a new customer"
                value={newCustomerName}
                onChange={(e) => setNewCustomerName(e.target.value)}
              />
              <button
                onClick={handleCreateCustomer}
                disabled={creatingCustomer || !newCustomerName.trim()}
                className="px-3.5 py-2 rounded-xl bg-bg-muted border border-border-subtle text-sm font-medium text-text-secondary hover:text-text-primary disabled:opacity-40 transition-colors shrink-0"
              >
                {creatingCustomer ? "Adding…" : "Add"}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Against invoice (optional)
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.invoice_id}
                onChange={(e) =>
                  setForm((f) => ({ ...f, invoice_id: e.target.value }))
                }
              >
                <option value="">No invoice reference</option>
                {invoices.map((inv) => (
                  <option key={inv.id} value={inv.id}>
                    {inv.invoice_number}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Note date</label>
              <input
                type="date"
                className={`${inputCls} mt-1.5`}
                value={form.credit_note_date}
                onChange={(e) =>
                  setForm((f) => ({ ...f, credit_note_date: e.target.value }))
                }
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary">
              Reason (required — refund, discount or correction)
            </label>
            <textarea
              className={`${inputCls} mt-1.5 min-h-16 resize-y`}
              placeholder="e.g. Returned 1 damaged chair — agreed refund"
              value={form.reason}
              onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-text-secondary">Lines</label>
              <button
                onClick={() =>
                  setForm((f) => ({
                    ...f,
                    lines: [...f.lines, { description: "", quantity: "1", unit_price: "" }],
                  }))
                }
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
                    type="number"
                    min="0"
                    step="any"
                    placeholder="Qty"
                    value={line.quantity}
                    onChange={(e) => setLine(i, { quantity: e.target.value })}
                  />
                  <input
                    className={`${inputCls} col-span-3 text-right`}
                    type="number"
                    min="0"
                    step="any"
                    placeholder="Unit price"
                    value={line.unit_price}
                    onChange={(e) => setLine(i, { unit_price: e.target.value })}
                  />
                  <button
                    onClick={() =>
                      setForm((f) => ({
                        ...f,
                        lines: f.lines.filter((_, idx) => idx !== i),
                      }))
                    }
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

          <div className="flex items-center justify-between rounded-xl bg-bg-muted px-4 py-3 text-sm">
            <span className="text-text-secondary">Adjusted total</span>
            <span className="font-semibold text-text-primary tabular-nums">
              {formatCurrency(totals.total, org?.base_currency_code)}
            </span>
          </div>

          <p className="text-[11px] text-text-muted">
            Credit notes are created in DRAFT. Issue it from the note page — the
            reversal journal (revenue ↓, receivable ↓) then posts through the AI
            agent with double-entry enforced by the database.
          </p>
          {formError && (
            <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">
              {formError}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <button
              onClick={() => {
                setModalOpen(false);
                resetForm();
              }}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? "Creating…" : "Create Draft Credit Note"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}





