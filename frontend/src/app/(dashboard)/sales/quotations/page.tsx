"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Search, Trash2, Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { useServerList } from "@/lib/hooks/useServerList";
import { documentOrFilter, ilikeAny, sanitizeSearch } from "@/lib/lists/logic";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import Pagination from "@/components/shared/Pagination";
import DraftDeleteButton from "@/components/shared/DraftDeleteButton";
import StatusMenu from "@/components/shared/StatusMenu";
import PartyCombobox from "@/components/shared/PartyCombobox";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Quotation } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface LineDraft {
  description: string;
  quantity: string;
  unit_price: string;
}

interface QuotationForm {
  customer_id: string;
  quotation_date: string;
  valid_until: string;
  terms: string;
  notes: string;
  lines: LineDraft[];
}

const today = () => new Date().toISOString().slice(0, 10);

const addDays = (dateStr: string, days: number) => {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

type QuotationRow = Quotation & {
  customer?: { name?: string } | { name?: string }[] | null;
};

export default function QuotationsPage() {
  const { org, loading: orgLoading } = useOrg();
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [busyId, setBusyId] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [form, setForm] = useState<QuotationForm>({
    customer_id: "",
    quotation_date: today(),
    valid_until: addDays(today(), 30),
    terms: "",
    notes: "",
    lines: [{ description: "", quantity: "1", unit_price: "" }],
  });

  // SERVER-SIDE LIST: status + search (quotation number or matching customer)
  // run in the database; the browser holds exactly one page of rows (§4–§6).
  const {
    rows, error, refreshing, search, setSearch,
    page, setPage, pageSize, count, refresh,
  } = useServerList<QuotationRow>({
    enabled: !!org,
    filters: [statusFilter],
    fetchPage: async ({ page, pageSize, search, signal }) => {
      if (!org) return { rows: [], count: 0 };
      const supabase = createClient();

      // Party-name matches resolve to a bounded id set first (PostgREST can't
      // OR a root column with an embedded one).
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
        .from("quotations")
        .select(
          "id, quotation_number, revision, customer_id, status, quotation_date, valid_until, total, currency_code, created_at, customer:customers(name)",
          { count: "exact" }
        )
        .eq("organization_id", org.organization_id)
        .order("created_at", { ascending: false })
        .order("id", { ascending: true })
        .range(page * pageSize, page * pageSize + pageSize - 1)
        .abortSignal(signal);
      if (statusFilter !== "ALL") query = query.eq("status", statusFilter);
      const expr = documentOrFilter(
        ["quotation_number"],
        "customer_id",
        search,
        partyIds
      );
      if (expr) query = query.or(expr);
      const { data, error: dbError, count: total } = await query;
      if (dbError) throw dbError;
      return { rows: (data ?? []) as unknown as QuotationRow[], count: total ?? null };
    },
  });

  const shownError = error ?? actionError;
  const afterMutation = () => {
    setActionError(null);
    refresh();
  };

  const total = useMemo(
    () =>
      form.lines.reduce(
        (sum, l) => sum + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0),
        0
      ),
    [form.lines]
  );

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
    if (validLines.length === 0) {
      setFormError("Add at least one line with a description, quantity and price");
      return;
    }

    setSaving(true);
    setFormError(null);
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    const subtotal = validLines.reduce((s, l) => s + Number(l.quantity) * Number(l.unit_price), 0);

    const { data: quotation, error: insertError } = await supabase
      .from("quotations")
      .insert({
        organization_id: org.organization_id,
        customer_id: form.customer_id,
        status: "DRAFT",
        quotation_date: form.quotation_date,
        valid_until: form.valid_until || null,
        currency_code: org.base_currency_code,
        subtotal,
        discount_total: 0,
        tax_total: 0,
        total: subtotal,
        terms: form.terms.trim() || null,
        notes: form.notes.trim() || null,
        created_by: user?.id ?? null,
      })
      .select("id")
      .single();

    if (insertError || !quotation) {
      setSaving(false);
      setFormError(insertError?.message ?? "Failed to create quotation");
      return;
    }

    const { error: itemsError } = await supabase.from("quotation_items").insert(
      validLines.map((l, i) => ({
        organization_id: org.organization_id,
        quotation_id: quotation.id,
        line_number: i + 1,
        description: l.description.trim(),
        quantity: Number(l.quantity),
        unit_price: Number(l.unit_price),
        discount_amount: 0,
        tax_amount: 0,
        line_total: Number(l.quantity) * Number(l.unit_price),
      }))
    );

    setSaving(false);
    if (itemsError) { setFormError(itemsError.message); return; }
    setModalOpen(false);
    setForm({
      customer_id: "", quotation_date: today(), valid_until: addDays(today(), 30),
      terms: "", notes: "", lines: [{ description: "", quantity: "1", unit_price: "" }],
    });
    refresh();
  };

  const updateStatus = async (
    id: string,
    status: "SENT" | "ACCEPTED",
    timestampField: "sent_at" | "accepted_at"
  ) => {
    setBusyId(id);
    const supabase = createClient();
    const { error: updError } = await supabase
      .from("quotations")
      .update({ status, [timestampField]: new Date().toISOString() })
      .eq("id", id);
    setBusyId(null);
    if (updError) setActionError(updError.message);
    else afterMutation();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Quotations"
        subtitle="Offers and price quotes sent to customers"
        actions={
          <button
            onClick={() => { setFormError(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New Quotation
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
            aria-label="Search quotations"
          />
        </div>
        <select
          className={`${inputCls} max-w-40`}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
        >
          {["ALL", "DRAFT", "SENT", "ACCEPTED", "REJECTED", "EXPIRED", "CONVERTED"].map((s) => (
            <option key={s} value={s}>{s === "ALL" ? "All statuses" : s}</option>
          ))}
        </select>
      </div>

      {orgLoading || (!rows && !shownError) ? (
        <TableSkeleton cols={6} />
      ) : shownError ? (
        <ErrorState message={shownError} onRetry={afterMutation} />
      ) : (rows ?? []).length === 0 ? (
        <EmptyState
          title={search || statusFilter !== "ALL" ? "No quotations match your filters" : "No quotations yet"}
          hint={search ? undefined : "Create one here, or tell the AI: \"Prepare a quotation for ABC Technologies for 40 hours of development at Rs. 5,000/hour\"."}
        />
      ) : (
        <div className={`bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto transition-opacity ${refreshing ? "opacity-60" : ""}`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Number</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Valid Until</th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((q) => {
                const customerName = Array.isArray(q.customer) ? q.customer[0]?.name : q.customer?.name;
                return (
                  <tr key={q.id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-text-primary tabular-nums">
                      {q.quotation_number}
                      {q.revision > 1 && (
                        <span className="text-text-muted font-normal"> rev {q.revision}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-text-primary">{customerName ?? "-"}</td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums">{q.quotation_date}</td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums">{q.valid_until ?? "-"}</td>
                    <td className="px-4 py-3 text-right text-text-primary tabular-nums font-medium">
                      {formatCurrency(q.total, q.currency_code)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusMenu
                        table="quotations"
                        documentId={q.id}
                        status={q.status}
                        transitions={{
                          DRAFT: ["SENT"],
                          SENT: ["ACCEPTED", "REJECTED"],
                        }}
                        onUpdated={afterMutation}
                        onError={setActionError}
                      />
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {q.status === "DRAFT" && (
                        <div className="inline-flex items-center gap-2">
                          <button
                            onClick={() => updateStatus(q.id, "SENT", "sent_at")}
                            disabled={busyId === q.id}
                            className="text-xs font-medium text-ai-600 hover:text-ai-700 disabled:opacity-50"
                          >
                            Mark sent
                          </button>
                          <DraftDeleteButton
                            table="quotations"
                            documentId={q.id}
                            label="draft quotation"
                            onDeleted={afterMutation}
                            onError={setActionError}
                          />
                        </div>
                      )}
                      {q.status === "SENT" && (
                        <button
                          onClick={() => updateStatus(q.id, "ACCEPTED", "accepted_at")}
                          disabled={busyId === q.id}
                          className="text-xs font-medium text-success-700 hover:text-success-800 disabled:opacity-50"
                        >
                          Mark accepted
                        </button>
                      )}
                      <Link
                        href={`/sales/quotations/${q.id}`}
                        aria-label={`Print quotation ${q.quotation_number}`}
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

      <Pagination
        page={page}
        pageSize={pageSize}
        count={count}
        onPageChange={setPage}
        refreshing={refreshing}
      />

      {/* New Quotation Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="New Quotation" wide>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="quotation-customer" className="text-xs font-medium text-text-secondary">Customer *</label>
              <div className="mt-1.5">
                <PartyCombobox
                  kind="customer"
                  organizationId={org?.organization_id ?? ""}
                  value={form.customer_id}
                  onChange={(id) => setForm((f) => ({ ...f, customer_id: id }))}
                  inputId="quotation-customer"
                  label="Customer"
                  baseCurrency={org?.base_currency_code}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-text-secondary">Quotation date</label>
                <input type="date" className={`${inputCls} mt-1.5`} value={form.quotation_date}
                  onChange={(e) => setForm({ ...form, quotation_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-medium text-text-secondary">Valid until</label>
                <input type="date" className={`${inputCls} mt-1.5`} value={form.valid_until}
                  onChange={(e) => setForm({ ...form, valid_until: e.target.value })} />
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

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Terms</label>
              <input className={`${inputCls} mt-1.5`} value={form.terms}
                onChange={(e) => setForm({ ...form, terms: e.target.value })}
                placeholder="e.g. 50% advance, 50% on delivery" />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Notes</label>
              <input className={`${inputCls} mt-1.5`} value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="Internal notes" />
            </div>
          </div>

          <div className="flex items-center justify-between rounded-xl bg-bg-muted px-4 py-3 text-sm">
            <span className="text-text-secondary">Total</span>
            <span className="font-semibold text-text-primary tabular-nums">
              {formatCurrency(total, org?.base_currency_code)}
            </span>
          </div>

          <p className="text-[11px] text-text-muted">
            Quotations don&apos;t touch the ledger. When a customer accepts, ask the
            AI to convert it into an invoice - the journal entry is posted there.
          </p>
          {formError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{formError}</p>}

          <div className="flex justify-end gap-2">
            <button onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {saving ? "Creating…" : "Create Quotation"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
