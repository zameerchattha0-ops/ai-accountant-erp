"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Search, ShieldCheck, Lock } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";
import type { Account, AccountType } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

const TYPE_ORDER: AccountType[] = ["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"];

// DB check constraint: normal_balance must match account_type
const normalBalanceFor = (t: AccountType): "DEBIT" | "CREDIT" =>
  t === "ASSET" || t === "EXPENSE" ? "DEBIT" : "CREDIT";

interface AccountForm {
  code: string;
  name: string;
  account_type: AccountType;
  parent_account_id: string;
  description: string;
}

export default function ChartOfAccountsPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<Account[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("ALL");

  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState<AccountForm>({
    code: "",
    name: "",
    account_type: "EXPENSE",
    parent_account_id: "",
    description: "",
  });

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("accounts")
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("code");
    if (dbError) setError(dbError.message);
    else setRows(data ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return (rows ?? []).filter((a) => {
      if (typeFilter !== "ALL" && a.account_type !== typeFilter) return false;
      if (!q) return true;
      return a.code.toLowerCase().includes(q) || a.name.toLowerCase().includes(q);
    });
  }, [rows, search, typeFilter]);

  const grouped = useMemo(() => {
    const map = new Map<AccountType, Account[]>();
    for (const t of TYPE_ORDER) map.set(t, []);
    for (const a of filtered) map.get(a.account_type)?.push(a);
    return map;
  }, [filtered]);

  const parentOptions = useMemo(
    () => (rows ?? []).filter((a) => a.account_type === form.account_type && a.is_active),
    [rows, form.account_type]
  );

  const handleSave = async () => {
    if (!org) return;
    if (!form.code.trim() || !form.name.trim()) {
      setFormError("Code and name are required");
      return;
    }
    setSaving(true);
    setFormError(null);
    const supabase = createClient();
    const { error: insertError } = await supabase.from("accounts").insert({
      organization_id: org.organization_id,
      code: form.code.trim(),
      name: form.name.trim(),
      account_type: form.account_type,
      normal_balance: normalBalanceFor(form.account_type),
      parent_account_id: form.parent_account_id || null,
      description: form.description.trim() || null,
    });
    setSaving(false);
    if (insertError) { setFormError(insertError.message); return; }
    setModalOpen(false);
    setForm({ code: "", name: "", account_type: "EXPENSE", parent_account_id: "", description: "" });
    load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Chart of Accounts"
        subtitle="Your organization's ledger structure"
        actions={
          <button
            onClick={() => { setFormError(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> Add Account
          </button>
        }
      />

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            className={`${inputCls} pl-9`}
            placeholder="Search by code or name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className={`${inputCls} max-w-44`} value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}>
          {["ALL", ...TYPE_ORDER].map((t) => (
            <option key={t} value={t}>{t === "ALL" ? "All types" : t}</option>
          ))}
        </select>
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton rows={10} cols={5} />
      ) : error ? (
        <ErrorState message={error} />
      ) : (
        <div className="space-y-5">
          {TYPE_ORDER.map((t) => {
            const group = grouped.get(t) ?? [];
            if (group.length === 0) return null;
            return (
              <div key={t} className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 bg-bg-muted/60 border-b border-border-subtle">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={t} />
                    <span className="text-xs text-text-muted">
                      {normalBalanceFor(t) === "DEBIT" ? "Debit" : "Credit"} normal balance
                    </span>
                  </div>
                  <span className="text-xs text-text-muted">{group.length} accounts</span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                      <th className="px-4 py-2.5 font-medium w-28">Code</th>
                      <th className="px-4 py-2.5 font-medium">Name</th>
                      <th className="px-4 py-2.5 font-medium">Type</th>
                      <th className="px-4 py-2.5 font-medium">Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.map((a) => (
                      <tr key={a.id} className={cn(
                        "border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors",
                        !a.is_active && "opacity-60"
                      )}>
                        <td className="px-4 py-2.5 font-medium text-text-primary tabular-nums">{a.code}</td>
                        <td className="px-4 py-2.5 text-text-primary">
                          {a.name}
                          {a.description && (
                            <span className="block text-xs text-text-muted mt-0.5">{a.description}</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5"><StatusBadge status={a.account_type} /></td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2 text-[11px] text-text-muted">
                            {a.is_control_account && (
                              <span className="inline-flex items-center gap-1">
                                <ShieldCheck className="w-3.5 h-3.5" /> Control
                              </span>
                            )}
                            {a.is_system && (
                              <span className="inline-flex items-center gap-1">
                                <Lock className="w-3.5 h-3.5" /> System
                              </span>
                            )}
                            {!a.is_active && <span className="text-warning-600">Inactive</span>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
          {filtered.length === 0 && (
            <p className="text-sm text-text-secondary text-center py-8">No accounts match your filters.</p>
          )}
        </div>
      )}

      {/* Add Account Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Add Account">
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-medium text-text-secondary">Code *</label>
              <input className={`${inputCls} mt-1.5`} value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder="e.g. 6005" />
              <p className="text-[11px] text-text-muted mt-1">Unique per organization</p>
            </div>
            <div className="col-span-2">
              <label className="text-xs font-medium text-text-secondary">Name *</label>
              <input className={`${inputCls} mt-1.5`} value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Software Licenses" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-text-secondary">Type *</label>
              <select className={`${inputCls} mt-1.5`} value={form.account_type}
                onChange={(e) =>
                  setForm({ ...form, account_type: e.target.value as AccountType, parent_account_id: "" })
                }>
                {TYPE_ORDER.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <p className="text-[11px] text-text-muted mt-1">
                Normal balance: {normalBalanceFor(form.account_type)}
              </p>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Parent account</label>
              <select className={`${inputCls} mt-1.5`} value={form.parent_account_id}
                onChange={(e) => setForm({ ...form, parent_account_id: e.target.value })}>
                <option value="">None (top level)</option>
                {parentOptions.map((a) => (
                  <option key={a.id} value={a.id}>{a.code} - {a.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary">Description</label>
            <input className={`${inputCls} mt-1.5`} value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>

          <p className="text-[11px] text-text-muted">
            Deleting or deactivating accounts with posted activity should be done
            by the AI agent so ledger history stays intact.
          </p>
          {formError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{formError}</p>}

          <div className="flex justify-end gap-2">
            <button onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {saving ? "Saving…" : "Add Account"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
