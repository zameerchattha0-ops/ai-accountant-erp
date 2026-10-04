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

interface DebitNoteForm {
  supplier_id: string;
  bill_id: string;
  return_date: string;
  reason: string;
  lines: LineDraft[];
}

const today = () => new Date().toISOString().slice(0, 10);

/** Business-valid transitions (bill_status enum — no ISSUED value). */
const DN_TRANSITIONS: Record<string, string[]> = {
  DRAFT: ["OPEN", "VOIDED"],
  OPEN: ["VOIDED"],
};

interface DebitNoteRow {
  id: string;
  return_number: string;
  return_date: string;
  status: string;
  reason: string | null;
  total: number;
  supplier_id: string | null;
  bill_id: string | null;
  supplier_name?: string;
}

export default function PurchaseReturnsPage() {
  const { org, loading: orgLoading } = useOrg();
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [bills, setBills] = useState<{ id: string; bill_number: string }[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [form, setForm] = useState<DebitNoteForm>({
    supplier_id: "",
    bill_id: "",
    return_date: today(),
    reason: "",
    lines: [{ description: "", quantity: "1", unit_price: "" }],
  });

  // SERVER-SIDE LIST: status + search (note number, reason, matching
  // supplier) run in the database; the browser holds one page of rows (§4–§6).
  const {
    rows, error, refreshing, search, setSearch,
    page, setPage, pageSize, count, refresh,
  } = useServerList<DebitNoteRow>({
    enabled: !!org,
    filters: [statusFilter],
    fetchPage: async ({ page, pageSize, search, signal }) => {
      if (!org) return { rows: [], count: 0 };
      const supabase = createClient();

      let partyIds: string[] = [];
      if (sanitizeSearch(search)) {
        const { data: matches } = await supabase
          .from("suppliers")
          .select("id")
          .eq("organization_id", org.organization_id)
          .or(ilikeAny(["name", "supplier_code"], search))
          .limit(200)
          .abortSignal(signal);
        partyIds = (matches ?? []).map((m) => (m as { id: string }).id);
      }

      let query = supabase
        .from("purchase_returns")
        .select(
          "id, return_number, return_date, status, reason, total, supplier_id, bill_id, created_at, supplier:suppliers(name)",
          { count: "exact" }
        )
        .eq("organization_id", org.organization_id)
        .order("created_at", { ascending: false })
        .order("id", { ascending: true })
        .range(page * pageSize, page * pageSize + pageSize - 1)
        .abortSignal(signal);
      if (statusFilter !== "ALL") query = query.eq("status", statusFilter);
      const expr = documentOrFilter(
        ["return_number", "reason"],
        "supplier_id",
        search,
        partyIds
      );
      if (expr) query = query.or(expr);
      const { data, error: dbError, count: total } = await query;
      if (dbError) throw dbError;
      const mapped = ((data ?? []) as unknown as (DebitNoteRow & {
        supplier: { name?: string } | { name?: string }[] | null;
      })[]).map((r) => ({
        ...r,
        supplier_name: Array.isArray(r.supplier)
          ? r.supplier[0]?.name ?? ""
          : r.supplier?.name ?? "",
      }));
      return { rows: mapped, count: total ?? null };
    },
  });

  const shownError = error ?? actionError;
  const afterMutation = () => {
    setActionError(null);
    refresh();
  };

  // Bills of the selected supplier — the reference is optional but grounds
  // the debit note against the original purchase.
  useEffect(() => {
    if (!org || !form.supplier_id) {
      setBills([]);
      return;
    }
    const supabase = createClient();
    supabase
      .from("purchase_bills")
      .select("id, bill_number")
      .eq("organization_id", org.organization_id)
      .eq("supplier_id", form.supplier_id)
      .order("bill_number", { ascending: false })
      .then(({ data }) =>
        setBills((data as { id: string; bill_number: string }[]) ?? [])
      );
  }, [org, form.supplier_id]);

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
      supplier_id: "",
      bill_id: "",
      return_date: today(),
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
    if (!form.supplier_id) {
      setFormError("Select a supplier.");
      return;
    }
    if (!form.reason.trim()) {
      setFormError("A reason is required — which goods are going back and why.");
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
    // return_number is assigned by the DB trigger (DN-#### style prefix).
    const { data: note, error: noteError } = await supabase
      .from("purchase_returns")
      .insert({
        organization_id: org.organization_id,
        supplier_id: form.supplier_id,
        bill_id: form.bill_id || null,
        return_date: form.return_date,
        reason: form.reason.trim(),
        status: "DRAFT",
        subtotal: totals.subtotal,
        tax_total: 0,
        total: totals.total,
        currency_code: org.base_currency_code ?? "PKR",
        created_by: authData.user?.id ?? null,
      })
      .select()
      .single();
    if (noteError || !note) {
      setSaving(false);
      setFormError(noteError?.message ?? "Could not create the debit note.");
      return;
    }
    const itemRows = validLines.map((l, i) => {
      const quantity = parseFloat(l.quantity || "0") || 0;
      const unit_price = parseFloat(l.unit_price || "0") || 0;
      return {
        organization_id: org.organization_id,
        return_id: (note as { id: string }).id,
        line_number: i + 1,
        description: l.description.trim(),
        quantity,
        unit_price,
        line_total: quantity * unit_price,
      };
    });
    const { error: itemsError } = await supabase
      .from("purchase_return_items")
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
        title="Debit Notes"
        subtitle="Goods returned to suppliers (purchase returns) — every debit note shrinks the payable and reverses the purchase."
        actions={
          <button
            onClick={() => {
              resetForm();
              setModalOpen(true);
            }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New Debit Note
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
            placeholder="Search by note number, supplier or reason…"
            className={`${inputCls} pl-9`}
            aria-label="Search debit notes"
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
          <option value="OPEN">Open</option>
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
                <th className="px-4 py-3 font-medium">Supplier</th>
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
                          ? "No debit notes match your filters"
                          : "No debit notes yet"
                      }
                      hint={
                        search || statusFilter !== "ALL"
                          ? undefined
                          : "Ask the AI: “Return the laptop to ABC Computers” — or create one above."
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
                    {r.return_number}
                  </td>
                  <td className="px-4 py-3 text-text-secondary tabular-nums">
                    {r.return_date}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {r.supplier_name || "—"}
                  </td>
                  <td className="px-4 py-3 text-text-secondary max-w-[260px] truncate">
                    {r.reason || "—"}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums font-medium text-text-primary">
                    {formatCurrency(Number(r.total), org?.base_currency_code)}
                  </td>
                  <td className="px-4 py-3">
                    <StatusMenu
                      table="purchase_returns"
                      documentId={r.id}
                      status={r.status}
                      transitions={DN_TRANSITIONS}
                      onUpdated={afterMutation}
                      onError={setActionError}
                    />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/purchases/returns/${r.id}`}
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

      {/* New debit note modal */}
      <Modal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          resetForm();
        }}
        title="New Debit Note"
        wide
      >
        <div className="space-y-4">
          <div>
            <label htmlFor="debit-note-supplier" className="text-xs font-medium text-text-secondary">Supplier</label>
            <div className="mt-1.5">
              <PartyCombobox
                kind="supplier"
                organizationId={org?.organization_id ?? ""}
                value={form.supplier_id}
                onChange={(id) =>
                  setForm((f) => ({ ...f, supplier_id: id, bill_id: "" }))
                }
                inputId="debit-note-supplier"
                label="Supplier"
                baseCurrency={org?.base_currency_code}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Against bill (optional)
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.bill_id}
                onChange={(e) => setForm((f) => ({ ...f, bill_id: e.target.value }))}
              >
                <option value="">No bill reference</option>
                {bills.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.bill_number}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Return date</label>
              <input
                type="date"
                className={`${inputCls} mt-1.5`}
                value={form.return_date}
                onChange={(e) =>
                  setForm((f) => ({ ...f, return_date: e.target.value }))
                }
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary">
              Reason (required — which goods go back, and why)
            </label>
            <textarea
              className={`${inputCls} mt-1.5 min-h-16 resize-y`}
              placeholder="e.g. 1 laptop returned — defective on arrival"
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
            Debit notes are created in DRAFT. Open it from the note page — the
            reversal journal (payable ↓, purchase ↓) then posts through the AI
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
              {saving ? "Creating…" : "Create Draft Debit Note"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}





