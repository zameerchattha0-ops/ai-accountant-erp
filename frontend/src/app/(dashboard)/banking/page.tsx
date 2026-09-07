"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Search, Star, ChevronDown, ChevronRight, Landmark } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { BankAccount, BankTransaction } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface BankAccountForm {
  account_name: string;
  bank_name: string;
  account_number_masked: string;
  iban: string;
  branch_code: string;
  currency_code: string;
}

const EMPTY_FORM: BankAccountForm = {
  account_name: "", bank_name: "", account_number_masked: "",
  iban: "", branch_code: "", currency_code: "PKR",
};

type BankRow = BankAccount & { gl_account?: { code?: string; name?: string } | null };

export default function BankingPage() {
  const { org, loading: orgLoading } = useOrg();
  const [rows, setRows] = useState<BankRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState<BankAccountForm>(EMPTY_FORM);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [txns, setTxns] = useState<Record<string, BankTransaction[]>>({});
  const [txnsLoading, setTxnsLoading] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("bank_accounts")
      .select("*, gl_account:accounts(code, name)")
      .eq("organization_id", org.organization_id)
      .order("is_default", { ascending: true })
      .order("account_name");
    if (dbError) setError(dbError.message);
    else setRows((data as BankRow[]) ?? []);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  const loadTransactions = useCallback(async (bankAccountId: string) => {
    if (txns[bankAccountId]) return;
    setTxnsLoading(bankAccountId);
    const supabase = createClient();
    const { data } = await supabase
      .from("bank_transactions")
      .select("*")
      .eq("organization_id", org!.organization_id)
      .eq("bank_account_id", bankAccountId)
      .order("transaction_date", { ascending: false })
      .limit(50);
    setTxns((prev) => ({ ...prev, [bankAccountId]: (data as BankTransaction[]) ?? [] }));
    setTxnsLoading(null);
  }, [org, txns]);

  const toggleExpand = (id: string) => {
    if (expandedId === id) { setExpandedId(null); return; }
    setExpandedId(id);
    loadTransactions(id);
  };

  const handleSave = async () => {
    if (!org) return;
    if (!form.account_name.trim() || !form.bank_name.trim()) {
      setFormError("Account name and bank name are required"); return;
    }
    setSaving(true); setFormError(null);
    const supabase = createClient();

    // 1. Resolve the organisation's default chart of accounts
    let chartId: string | null = null;
    const { data: coa } = await supabase
      .from("chart_of_accounts")
      .select("id")
      .eq("organization_id", org.organization_id)
      .eq("is_default", true)
      .limit(1)
      .single();

    if (coa) {
      chartId = coa.id;
    } else {
      // Fallback: just use the first chart_of_accounts
      const { data: anyCoa } = await supabase
        .from("chart_of_accounts").select("id")
        .eq("organization_id", org.organization_id).limit(1).single();
      if (!anyCoa) { setSaving(false); setFormError("No chart of accounts found. Please set one up first."); return; }
      chartId = anyCoa.id;
    }

    // 2. Generate next account code (look at existing BANK-category accounts)
    const { data: existingBankAccounts } = await supabase
      .from("accounts").select("code")
      .eq("organization_id", org.organization_id)
      .eq("account_type", "ASSET")
      .order("code", { ascending: false })
      .limit(1);
    const lastCode = existingBankAccounts?.[0]?.code ?? "1009";
    const nextCode = String(Number(lastCode) + 1);

    // 3. Create the GL account (ASSET / DEBIT / BANK category)
    const { data: glAccount, error: glError } = await supabase
      .from("accounts")
      .insert({
        organization_id: org.organization_id,
        chart_of_accounts_id: chartId,
        code: nextCode,
        name: form.account_name.trim(),
        account_type: "ASSET",
        normal_balance: "DEBIT",
        account_category_id: "88f052f5-d626-48fe-9e6d-6ea2a3c0b822", // BANK
        is_system: false,
        is_control_account: false,
        is_active: true,
        description: `Bank account: ${form.bank_name.trim()}`,
      })
      .select("id")
      .single();

    if (glError || !glAccount) {
      setSaving(false);
      setFormError(glError?.message ?? "Failed to create GL account");
      return;
    }

    // 4. Create the bank_accounts row linked to the GL account
    const { error: insertError } = await supabase.from("bank_accounts").insert({
      organization_id: org.organization_id,
      account_name: form.account_name.trim(),
      bank_name: form.bank_name.trim(),
      account_number_masked: form.account_number_masked.trim() || null,
      iban: form.iban.trim() || null,
      branch_code: form.branch_code.trim() || null,
      currency_code: form.currency_code || org.base_currency_code,
      current_balance: 0,
      is_active: true,
      is_default: false,
      gl_account_id: glAccount.id,
    });
    setSaving(false);
    if (insertError) { setFormError(insertError.message); return; }
    setModalOpen(false); setForm(EMPTY_FORM); load();
  };

  const setDefault = async (id: string) => {
    const supabase = createClient();
    await supabase.from("bank_accounts")
      .update({ is_default: true })
      .eq("id", id)
      .eq("organization_id", org!.organization_id);
    load();
  };

  const totalBalance = (rows ?? []).reduce((s, r) => s + Number(r.current_balance), 0);
  const activeCount = (rows ?? []).filter((r) => r.is_active).length;

  const filtered = (rows ?? []).filter((r) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return r.account_name.toLowerCase().includes(q) ||
      r.bank_name.toLowerCase().includes(q) ||
      (r.account_number_masked ?? "").toLowerCase().includes(q);
  });

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Banking"
        subtitle="Bank accounts and transactions"
        actions={
          <button
            onClick={() => { setFormError(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> Add Account
          </button>
        }
      />

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Total Balance</p>
          <p className="text-xl font-semibold text-text-primary tabular-nums mt-1">
            {formatCurrency(totalBalance, org?.base_currency_code)}
          </p>
        </div>
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Active Accounts</p>
          <p className="text-xl font-semibold text-text-primary tabular-nums mt-1">{activeCount}</p>
        </div>
        <div className="bg-bg-surface rounded-2xl border border-border-subtle px-5 py-4">
          <p className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Default Account</p>
          <p className="text-sm font-medium text-text-primary mt-1 truncate">
            {(rows ?? []).find((r) => r.is_default)?.account_name ?? "None set"}
          </p>
        </div>
      </div>

      <div className="relative max-w-sm">
        <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
        <input className={`${inputCls} pl-9`} placeholder="Search accounts…"
          value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton cols={6} />
      ) : error ? (
        <ErrorState message={error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={search ? "No accounts match your search" : "No bank accounts yet"}
          hint={search ? undefined : "Add your first bank account to start tracking balances."}
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium w-8"></th>
                <th className="px-4 py-3 font-medium">Account</th>
                <th className="px-4 py-3 font-medium">Bank</th>
                <th className="px-4 py-3 font-medium">Account #</th>
                <th className="px-4 py-3 font-medium text-right">Balance</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium w-10"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((acct) => (
                <>
                  <tr
                    key={acct.id}
                    onClick={() => toggleExpand(acct.id)}
                    className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors cursor-pointer"
                  >
                    <td className="px-4 py-3 text-text-muted">
                      {expandedId === acct.id
                        ? <ChevronDown className="w-4 h-4" />
                        : <ChevronRight className="w-4 h-4" />}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Landmark className="w-4 h-4 text-text-muted shrink-0" />
                        <span className="font-medium text-text-primary">{acct.account_name}</span>
                        {acct.is_default && (
                          <span className="px-1.5 py-0.5 rounded-full bg-ai-50 text-ai-700 text-[10px] font-medium">Default</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-text-secondary">{acct.bank_name}</td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums">{acct.account_number_masked ?? "-"}</td>
                    <td className="px-4 py-3 text-right text-text-primary tabular-nums font-medium">
                      {formatCurrency(Number(acct.current_balance), acct.currency_code ?? org?.base_currency_code)}
                    </td>
                    <td className="px-4 py-3">
                      {acct.is_active
                        ? <StatusBadge status="ACTIVE" />
                        : <StatusBadge status="VOIDED" />}
                    </td>
                    <td className="px-4 py-3">
                      {!acct.is_default && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setDefault(acct.id); }}
                          title="Set as default"
                          className="p-1 rounded-lg text-text-muted hover:text-warning-500 transition-colors"
                        >
                          <Star className="w-4 h-4" />
                        </button>
                      )}
                      {acct.is_default && <Star className="w-4 h-4 text-warning-500 fill-warning-500" />}
                    </td>
                  </tr>
                  {expandedId === acct.id && (
                    <tr key={`${acct.id}-txns`}>
                      <td colSpan={7} className="bg-bg-muted/30 px-4 py-3">
                        <TransactionTable
                          bankAccountId={acct.id}
                          txns={txns[acct.id]}
                          loading={txnsLoading === acct.id}
                          currencyCode={acct.currency_code ?? org?.base_currency_code}
                        />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add Bank Account Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Add Bank Account">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Account name *</label>
              <input className={`${inputCls} mt-1.5`} placeholder="e.g. HBL Current Account"
                value={form.account_name}
                onChange={(e) => setForm({ ...form, account_name: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Bank name *</label>
              <input className={`${inputCls} mt-1.5`} placeholder="e.g. Habib Bank Limited"
                value={form.bank_name}
                onChange={(e) => setForm({ ...form, bank_name: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Account number (masked)</label>
              <input className={`${inputCls} mt-1.5`} placeholder="****1234"
                value={form.account_number_masked}
                onChange={(e) => setForm({ ...form, account_number_masked: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">IBAN</label>
              <input className={`${inputCls} mt-1.5`} placeholder="PK00XXXX0000000000"
                value={form.iban}
                onChange={(e) => setForm({ ...form, iban: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">Branch code</label>
              <input className={`${inputCls} mt-1.5`}
                value={form.branch_code}
                onChange={(e) => setForm({ ...form, branch_code: e.target.value })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Currency</label>
              <input className={`${inputCls} mt-1.5`}
                value={form.currency_code}
                onChange={(e) => setForm({ ...form, currency_code: e.target.value })} />
            </div>
          </div>
          <p className="text-[11px] text-text-muted">
            A linked GL account will be created automatically by the backend.
          </p>
          {formError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{formError}</p>}
          <div className="flex justify-end gap-2">
            <button onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving}
              className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {saving ? "Adding…" : "Add Account"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

/* ---- Inline transaction sub-table ---- */

function TransactionTable({
  txns, loading, currencyCode,
}: {
  bankAccountId: string;
  txns?: BankTransaction[];
  loading: boolean;
  currencyCode?: string;
}) {
  if (loading) return <p className="text-xs text-text-muted py-2">Loading transactions…</p>;
  if (!txns || txns.length === 0) return <p className="text-xs text-text-muted py-2">No transactions yet.</p>;
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-wide text-text-muted">
          <th className="py-1.5 pr-3 font-medium">Date</th>
          <th className="py-1.5 pr-3 font-medium">Direction</th>
          <th className="py-1.5 pr-3 font-medium">Description</th>
          <th className="py-1.5 pr-3 font-medium">Counterparty</th>
          <th className="py-1.5 pr-3 font-medium text-right">Amount</th>
          <th className="py-1.5 font-medium">Status</th>
        </tr>
      </thead>
      <tbody>
        {txns.map((t) => (
          <tr key={t.id} className="border-t border-border-subtle/40">
            <td className="py-1.5 pr-3 tabular-nums text-text-secondary">{t.transaction_date}</td>
            <td className="py-1.5 pr-3">
              <span className={t.direction === "INFLOW" ? "text-success-600" : "text-error-600"}>
                {t.direction === "INFLOW" ? "↗ In" : "↘ Out"}
              </span>
            </td>
            <td className="py-1.5 pr-3 text-text-primary max-w-[200px] truncate">
              {t.description ?? "-"}
              {t.is_transfer && <span className="ml-1 text-ai-600 text-[10px]">(Transfer)</span>}
            </td>
            <td className="py-1.5 pr-3 text-text-secondary">{t.counterparty ?? "-"}</td>
            <td className="py-1.5 pr-3 text-right tabular-nums font-medium text-text-primary">
              {formatCurrency(Number(t.amount), currencyCode)}
            </td>
            <td className="py-1.5"><StatusBadge status={t.status} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
