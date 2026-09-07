"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Search } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Supplier } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface SupplierForm {
  name: string;
  email: string;
  phone: string;
  tax_number: string;
  payment_terms_days: string;
  credit_limit: string;
  notes: string;
}

const EMPTY_FORM: SupplierForm = {
  name: "", email: "", phone: "", tax_number: "",
  payment_terms_days: "30", credit_limit: "", notes: "",
};

export default function SuppliersPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<Supplier[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<SupplierForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("suppliers")
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("created_at", { ascending: false });
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  const filtered = (rows ?? []).filter((s) =>
    !search ||
    s.name.toLowerCase().includes(search.toLowerCase()) ||
    (s.supplier_code ?? "").toLowerCase().includes(search.toLowerCase()) ||
    (s.email ?? "").toLowerCase().includes(search.toLowerCase())
  );

  const handleSave = async () => {
    if (!org || form.name.trim().length < 2) return;
    setSaving(true);
    setFormError(null);
    const supabase = createClient();
    const { error: insertError } = await supabase.from("suppliers").insert({
      organization_id: org.organization_id,
      name: form.name.trim(),
      email: form.email.trim() || null,
      phone: form.phone.trim() || null,
      tax_number: form.tax_number.trim() || null,
      payment_terms_days: form.payment_terms_days ? Number(form.payment_terms_days) : null,
      credit_limit: form.credit_limit ? Number(form.credit_limit) : null,
      currency_code: org.base_currency_code,
      notes: form.notes.trim() || null,
    });
    setSaving(false);
    if (insertError) { setFormError(insertError.message); return; }
    setModalOpen(false);
    setForm(EMPTY_FORM);
    load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Suppliers"
        subtitle="Vendors you buy from and pay"
        actions={
          <button
            onClick={() => { setForm(EMPTY_FORM); setFormError(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> Add Supplier
          </button>
        }
      />

      <div className="relative max-w-sm">
        <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          className={`${inputCls} pl-9`}
          placeholder="Search suppliers…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton cols={5} />
      ) : error ? (
        <ErrorState message={error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={search ? "No suppliers match your search" : "No suppliers yet"}
          hint={search ? undefined : "Add your first supplier, or just tell the AI agent: \"Add supplier ABC Computers\"."}
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Code</th>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Phone</th>
                <th className="px-4 py-3 font-medium text-right">Credit Limit</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.id} className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors">
                  <td className="px-4 py-3 text-text-secondary tabular-nums">{s.supplier_code ?? "-"}</td>
                  <td className="px-4 py-3 font-medium text-text-primary">{s.name}</td>
                  <td className="px-4 py-3 text-text-secondary">{s.email ?? "-"}</td>
                  <td className="px-4 py-3 text-text-secondary">{s.phone ?? "-"}</td>
                  <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                    {s.credit_limit != null ? formatCurrency(s.credit_limit, s.currency_code ?? undefined) : "-"}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={s.is_active ? "ACTIVE" : "VOIDED"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Add Supplier">
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium text-text-secondary">Name *</label>
            <input className={`${inputCls} mt-1.5`} value={form.name} autoFocus
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. ABC Computers" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Email</label>
              <input className={`${inputCls} mt-1.5`} type="email" value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Phone</label>
              <input className={`${inputCls} mt-1.5`} value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Tax number</label>
              <input className={`${inputCls} mt-1.5`} value={form.tax_number}
                onChange={(e) => setForm({ ...form, tax_number: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Terms (days)</label>
              <input className={`${inputCls} mt-1.5`} type="number" min={0} value={form.payment_terms_days}
                onChange={(e) => setForm({ ...form, payment_terms_days: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Credit limit</label>
              <input className={`${inputCls} mt-1.5`} type="number" min={0} value={form.credit_limit}
                onChange={(e) => setForm({ ...form, credit_limit: e.target.value })} />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Notes</label>
            <textarea className={`${inputCls} mt-1.5 min-h-16 resize-y`} value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          {formError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{formError}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving || form.name.trim().length < 2}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {saving ? "Saving…" : "Save Supplier"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
