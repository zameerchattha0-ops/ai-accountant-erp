"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Search, Trash2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { useServerList } from "@/lib/hooks/useServerList";
import { documentOrFilter, ilikeAny, sanitizeSearch } from "@/lib/lists/logic";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import Pagination from "@/components/shared/Pagination";
import StatusMenu from "@/components/shared/StatusMenu";
import PartyCombobox from "@/components/shared/PartyCombobox";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";

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
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [invoices, setInvoices] = useState<{ id: string; invoice_number: string }[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [form, setForm] = useState<CreditNoteForm>({
    customer_id: "",
    invoice_id: "",
    credit_note_date: today(),
    reason: "",
    lines: [{ description: "", quantity: "1", unit_price: "" }],
  });

  // SERVER-SIDE LIST: status + search (note number, reason, matching customer)
  // run in the database; the browser holds exactly one page of rows (§4–§6).
  const {
    rows, error, refreshing, search, setSearch,
    page, setPage, pageSize, count, refresh,
  } = useServerList<CreditNoteRow>({
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
        .from("credit_notes")
        .select(
          "id, credit_note_number, credit_note_date, status, reason, total, customer_id, invoice_id, created_at, customer:customers(name)",
          { count: "exact" }
        )
        .eq("organization_id", org.organization_id)
        .order("created_at", { ascending: false })
        .order("id", { ascending: true })
        .range(page * pageSize, page * pageSize + pageSize - 1)
        .abortSignal(signal);
      if (statusFilter !== "ALL") query = query.eq("status", statusFilter);
      const expr = documentOrFilter(
        ["credit_note_number", "reason"],
        "customer_id",
        search,
        partyIds
      );
      if (expr) query = query.or(expr);
      const { data, error: dbError, count: total } = await query;
      if (dbError) throw dbError;
      const mapped = ((data ?? []) as unknown as (CreditNoteRow & {
        customer: { name?: string } | { name?: string }[] | null;
      })[]).map((r) => ({
        ...r,
        customer_name: Array.isArray(r.customer)
          ? r.customer[0]?.name ?? ""
          : r.customer?.name ?? "",
      }));
      return { rows: mapped, count: total ?? null };
    },
  });

  const shownError = error ?? actionError;
  const afterMutation = () => {
    setActionError(null);
    refresh();
  };

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
  };

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
    refresh();
  }, [org, form, totals, refresh]);

  if (orgLoading || (!rows && !shownError)) {
    return (
      <div className="space-y-4">
        <TableSkeleton rows={6} cols={5} />
      </div>
    );
  }
  if (shownError) return <ErrorState message={shownError} onRetry={afterMutation} />;

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
            aria-label="Search credit notes"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={`${inputCls} sm:w-44`}
          aria-label="Filter by status"
        >
          <option value="ALL">All statuses</option>
          <option value="DRAFT">Draft</option>
          <option value="ISSUED">Issued</option>
          <option value="VOIDED">Voided</option>
        </select>
      </div>

      {/* Table */}
      <div className={`bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden transition-opacity ${refreshing ? "opacity-60" : ""}`}>
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
              {(rows ?? []).length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10">
                    <EmptyState
                      title={
                        search || statusFilter !== "ALL"
                          ? "No credit notes match your filters"
                          : "No credit notes yet"
                      }
                      hint={
                        search || statusFilter !== "ALL"
                          ? undefined
                          : "Ask the AI: “Issue a credit note against invoice INV-000001 for Rs. 50,000” — or create one above."
                      }
                    />
                  </td>
                </tr>
              )}
              {(rows ?? []).map((r) => (
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
                      onUpdated={afterMutation}
                      onError={setActionError}
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

      <Pagination
        page={page}
        pageSize={pageSize}
        count={count}
        onPageChange={setPage}
        refreshing={refreshing}
      />

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
            <label htmlFor="credit-note-customer" className="text-xs font-medium text-text-secondary">Customer</label>
            <div className="mt-1.5">
              <PartyCombobox
                kind="customer"
                organizationId={org?.organization_id ?? ""}
                value={form.customer_id}
                onChange={(id) =>
                  setForm((f) => ({ ...f, customer_id: id, invoice_id: "" }))
                }
                inputId="credit-note-customer"
                label="Customer"
                baseCurrency={org?.base_currency_code}
              />
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





