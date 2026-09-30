"use client";

import { useCallback, useEffect, useState } from "react";
import { Banknote, Plus, Search, Trash2 } from "lucide-react";
import {
  disposeFixedAsset,
  listFixedAssets,
  recordAssetDepreciation,
  registerFixedAsset,
  type FixedAssetRegister,
} from "@/lib/api/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { FixedAsset } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

const PAYMENT_METHODS = ["CASH", "BANK_TRANSFER", "CHEQUE", "CARD", "CREDIT"];
const DEPRECIATION_METHODS = [
  { value: "STRAIGHT_LINE", label: "Straight line" },
  { value: "REDUCING_BALANCE", label: "Reducing balance" },
];
const STATUS_FILTERS = [
  "ALL", "ACTIVE", "FULLY_DEPRECIATED", "DISPOSED", "SOLD", "WRITTEN_OFF",
];
/** A disposed or written-off asset can be neither depreciated nor disposed again. */
const OPEN_STATUSES = new Set(["ACTIVE", "FULLY_DEPRECIATED"]);

const today = () => new Date().toISOString().slice(0, 10);

/** The API carries the refusal text in ``detail`` — surface it verbatim. */
function messageOf(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* plain-text error — already readable */
  }
  return raw;
}

interface RegisterForm {
  name: string;
  purchase_cost: string;
  purchase_date: string;
  payment_method: string;
  supplier_name: string;
  useful_life_years: string;
  depreciation_method: string;
  salvage_value: string;
  description: string;
}

const EMPTY_REGISTER: RegisterForm = {
  name: "",
  purchase_cost: "",
  purchase_date: today(),
  payment_method: "CASH",
  supplier_name: "",
  useful_life_years: "",
  depreciation_method: "STRAIGHT_LINE",
  salvage_value: "",
  description: "",
};

export default function FixedAssetsPage() {
  const { org, loading: orgLoading } = useOrg();
  const [register, setRegister] = useState<FixedAssetRegister | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("ALL");

  const [registerOpen, setRegisterOpen] = useState(false);
  const [form, setForm] = useState<RegisterForm>(EMPTY_REGISTER);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [depTarget, setDepTarget] = useState<FixedAsset | null>(null);
  const [depForm, setDepForm] = useState({
    transaction_date: today(),
    depreciation_amount: "",
  });
  const [disposeTarget, setDisposeTarget] = useState<FixedAsset | null>(null);
  const [disposeForm, setDisposeForm] = useState({
    transaction_date: today(),
    disposal_type: "DISPOSAL",
    disposal_amount: "",
  });

  const currency = org?.base_currency_code;
  const money = useCallback(
    (value: number | null | undefined) =>
      formatCurrency(Number(value ?? 0), currency),
    [currency]
  );

  const load = useCallback(async () => {
    if (!org) return;
    try {
      setError(null);
      setRegister(await listFixedAssets());
    } catch (e) {
      setError(messageOf(e));
    }
  }, [org]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = register?.items ?? [];
  const filtered = rows.filter(
    (row) =>
      (status === "ALL" || row.status === status) &&
      (!search ||
        row.name.toLowerCase().includes(search.toLowerCase()) ||
        (row.asset_code ?? "").toLowerCase().includes(search.toLowerCase()))
  );
  const counts = register?.counts ?? {};
  const summary = register?.summary ?? {
    purchase_cost: 0,
    accumulated_depreciation: 0,
    book_value: 0,
  };

  const handleRegister = async () => {
    const cost = Number(form.purchase_cost);
    if (form.name.trim().length < 2 || !Number.isFinite(cost) || cost <= 0) {
      setFormError("An asset name and a positive purchase cost are required.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await registerFixedAsset({
        name: form.name.trim(),
        purchase_cost: cost,
        purchase_date: form.purchase_date || undefined,
        payment_method: form.payment_method,
        supplier_name: form.supplier_name.trim() || null,
        useful_life_years: form.useful_life_years
          ? Number(form.useful_life_years)
          : null,
        depreciation_method: form.depreciation_method,
        salvage_value: form.salvage_value ? Number(form.salvage_value) : 0,
        description: form.description.trim() || null,
      });
      setRegisterOpen(false);
      setForm(EMPTY_REGISTER);
      await load();
    } catch (e) {
      setFormError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const openDepreciate = (asset: FixedAsset) => {
    setFormError(null);
    setDepForm({ transaction_date: today(), depreciation_amount: "" });
    setDepTarget(asset);
  };

  const handleDepreciate = async () => {
    if (!depTarget) return;
    setSaving(true);
    setFormError(null);
    try {
      await recordAssetDepreciation(depTarget.id, {
        transaction_date: depForm.transaction_date || undefined,
        depreciation_amount: depForm.depreciation_amount
          ? Number(depForm.depreciation_amount)
          : null,
      });
      setDepTarget(null);
      await load();
    } catch (e) {
      setFormError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const openDispose = (asset: FixedAsset) => {
    setFormError(null);
    setDisposeForm({
      transaction_date: today(),
      disposal_type: "DISPOSAL",
      disposal_amount: "",
    });
    setDisposeTarget(asset);
  };

  const handleDispose = async () => {
    if (!disposeTarget) return;
    setSaving(true);
    setFormError(null);
    try {
      await disposeFixedAsset(disposeTarget.id, {
        transaction_date: disposeForm.transaction_date || undefined,
        disposal_type: disposeForm.disposal_type,
        disposal_amount: disposeForm.disposal_amount
          ? Number(disposeForm.disposal_amount)
          : 0,
      });
      setDisposeTarget(null);
      await load();
    } catch (e) {
      setFormError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Fixed Assets"
        subtitle="The asset register: register an acquisition, charge depreciation, or dispose — each action posts its own journal."
        actions={
          <button
            onClick={() => {
              setForm(EMPTY_REGISTER);
              setFormError(null);
              setRegisterOpen(true);
            }}
            className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-b from-ai-500 to-ai-600 px-3.5 py-2 text-sm font-semibold text-white hover:from-ai-400 transition"
          >
            <Plus className="w-4 h-4" />
            Register asset
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Total cost", value: money(summary.purchase_cost) },
          {
            label: "Accumulated depreciation",
            value: money(summary.accumulated_depreciation),
          },
          { label: "Book value", value: money(summary.book_value) },
          { label: "Active assets", value: String(counts.ACTIVE ?? 0) },
        ].map((card) => (
          <div
            key={card.label}
            className="bg-bg-surface rounded-2xl border border-border-subtle p-4"
          >
            <p className="text-[11px] uppercase tracking-wide text-text-muted">
              {card.label}
            </p>
            <p className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {card.value}
            </p>
          </div>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by asset name or code..."
            className={`${inputCls} pl-9`}
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={`${inputCls} sm:w-60`}
        >
          {STATUS_FILTERS.map((option) => (
            <option key={option} value={option}>
              {option === "ALL"
                ? `All assets (${counts.ALL ?? rows.length})`
                : `${option.replace(/_/g, " ")} (${counts[option] ?? 0})`}
            </option>
          ))}
        </select>
      </div>

      {orgLoading || (!register && !error) ? (
        <TableSkeleton cols={7} />
      ) : error ? (
        <ErrorState message={error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={
            rows.length ? "No assets match this filter" : "No fixed assets yet"
          }
          hint={
            rows.length
              ? undefined
              : "Register an acquisition here, or tell the AI agent: \"I purchased a car for 4,000,000 on cash\"."
          }
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Code</th>
                <th className="px-4 py-3 font-medium">Asset</th>
                <th className="px-4 py-3 font-medium">Purchased</th>
                <th className="px-4 py-3 font-medium text-right">Cost</th>
                <th className="px-4 py-3 font-medium text-right">Life</th>
                <th className="px-4 py-3 font-medium">Method</th>
                <th className="px-4 py-3 font-medium text-right">Accum. dep.</th>
                <th className="px-4 py-3 font-medium text-right">Book value</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((asset) => {
                const open = OPEN_STATUSES.has(asset.status);
                return (
                  <tr
                    key={asset.id}
                    className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors"
                  >
                    <td className="px-4 py-3 text-text-secondary tabular-nums">
                      {asset.asset_code ?? "-"}
                    </td>
                    <td className="px-4 py-3 font-medium text-text-primary">
                      {asset.name}
                      {asset.description ? (
                        <span className="block text-xs font-normal text-text-muted">
                          {asset.description}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums">
                      {asset.purchase_date ?? "-"}
                    </td>
                    <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                      {money(asset.purchase_cost)}
                    </td>
                    <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                      {asset.useful_life_years ?? "-"}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {(asset.depreciation_method || "")
                        .replace(/_/g, " ")
                        .toLowerCase() || "-"}
                    </td>
                    <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                      {money(asset.accumulated_depreciation)}
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-text-primary tabular-nums">
                      {money(asset.book_value)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={asset.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => openDepreciate(asset)}
                          disabled={!open}
                          title={
                            open
                              ? "Charge one depreciation entry"
                              : "A disposed asset can no longer be depreciated"
                          }
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary hover:border-ai-300 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <Banknote className="w-3.5 h-3.5" />
                          Depreciate
                        </button>
                        <button
                          onClick={() => openDispose(asset)}
                          disabled={!open}
                          title={
                            open
                              ? "Dispose, sell or write off this asset"
                              : "This asset is already disposed of"
                          }
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-error-600 hover:border-error-300 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          Dispose
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
        title="Register asset"
      >
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium text-text-secondary">Name *</label>
            <input
              className={`${inputCls} mt-1.5`}
              value={form.name}
              autoFocus
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Delivery Van"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Purchase cost *
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                inputMode="decimal"
                value={form.purchase_cost}
                onChange={(e) => setForm({ ...form, purchase_cost: e.target.value })}
                placeholder="4000000"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Purchase date
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                type="date"
                value={form.purchase_date}
                onChange={(e) =>
                  setForm({ ...form, purchase_date: e.target.value })
                }
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Payment method
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.payment_method}
                onChange={(e) =>
                  setForm({ ...form, payment_method: e.target.value })
                }
              >
                {PAYMENT_METHODS.map((method) => (
                  <option key={method} value={method}>
                    {method.replace(/_/g, " ").toLowerCase()}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Supplier{form.payment_method === "CREDIT" ? " *" : ""}
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                value={form.supplier_name}
                onChange={(e) =>
                  setForm({ ...form, supplier_name: e.target.value })
                }
                placeholder={
                  form.payment_method === "CREDIT"
                    ? "Required for a credit purchase"
                    : "Optional"
                }
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Useful life (years)
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                inputMode="numeric"
                value={form.useful_life_years}
                onChange={(e) =>
                  setForm({ ...form, useful_life_years: e.target.value })
                }
                placeholder="e.g. 5 — blank = no schedule yet"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Depreciation method
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.depreciation_method}
                onChange={(e) =>
                  setForm({ ...form, depreciation_method: e.target.value })
                }
              >
                {DEPRECIATION_METHODS.map((method) => (
                  <option key={method.value} value={method.value}>
                    {method.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">
              Salvage value
            </label>
            <input
              className={`${inputCls} mt-1.5`}
              inputMode="decimal"
              value={form.salvage_value}
              onChange={(e) =>
                setForm({ ...form, salvage_value: e.target.value })
              }
              placeholder="0 — depreciation never goes below this"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">
              Description
            </label>
            <textarea
              className={`${inputCls} mt-1.5`}
              rows={2}
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              placeholder="e.g. Toyota Hilux — registration LEB-1234"
            />
          </div>
          {formError && <p className="text-xs text-error-600">{formError}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={() => setRegisterOpen(false)}
              className="rounded-xl border border-border-default px-3.5 py-2 text-sm font-medium text-text-secondary hover:bg-bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleRegister}
              disabled={saving}
              className="rounded-xl bg-gradient-to-b from-ai-500 to-ai-600 px-3.5 py-2 text-sm font-semibold text-white hover:from-ai-400 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? "Registering..." : "Register asset"}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={depTarget !== null}
        onClose={() => setDepTarget(null)}
        title={`Charge depreciation${depTarget ? ` — ${depTarget.name}` : ""}`}
      >
        <div className="space-y-4">
          {depTarget && (
            <p className="text-xs text-text-secondary">
              Cost {money(depTarget.purchase_cost)} · Salvage{" "}
              {money(depTarget.salvage_value)} · Book value{" "}
              {money(depTarget.book_value)}
              {depTarget.useful_life_years
                ? ` · Life ${depTarget.useful_life_years} yrs`
                : " · no useful life configured"}
            </p>
          )}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Date
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                type="date"
                value={depForm.transaction_date}
                onChange={(e) =>
                  setDepForm({ ...depForm, transaction_date: e.target.value })
                }
              />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Amount (optional)
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                inputMode="decimal"
                value={depForm.depreciation_amount}
                onChange={(e) =>
                  setDepForm({
                    ...depForm,
                    depreciation_amount: e.target.value,
                  })
                }
                placeholder="Blank = the asset's own policy"
              />
            </div>
          </div>
          <p className="text-[11px] text-text-muted">
            Leaving the amount blank posts one month of straight-line
            depreciation — (cost − salvage) ÷ useful life ÷ 12. The charge never
            takes the book value below the salvage value.
          </p>
          {formError && <p className="text-xs text-error-600">{formError}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={() => setDepTarget(null)}
              className="rounded-xl border border-border-default px-3.5 py-2 text-sm font-medium text-text-secondary hover:bg-bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDepreciate}
              disabled={saving}
              className="rounded-xl bg-gradient-to-b from-ai-500 to-ai-600 px-3.5 py-2 text-sm font-semibold text-white hover:from-ai-400 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? "Posting..." : "Post depreciation"}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={disposeTarget !== null}
        onClose={() => setDisposeTarget(null)}
        title={`Dispose${disposeTarget ? ` — ${disposeTarget.name}` : ""}`}
      >
        <div className="space-y-4">
          {disposeTarget && (
            <p className="text-xs text-text-secondary">
              Cost {money(disposeTarget.purchase_cost)} · Accumulated
              depreciation {money(disposeTarget.accumulated_depreciation)} ·
              Carrying amount {money(disposeTarget.book_value)}
            </p>
          )}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Type
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={disposeForm.disposal_type}
                onChange={(e) =>
                  setDisposeForm({
                    ...disposeForm,
                    disposal_type: e.target.value,
                    disposal_amount:
                      e.target.value === "WRITE_OFF"
                        ? ""
                        : disposeForm.disposal_amount,
                  })
                }
              >
                <option value="DISPOSAL">Disposal</option>
                <option value="SALE">Sale</option>
                <option value="WRITE_OFF">Write-off</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Date
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                type="date"
                value={disposeForm.transaction_date}
                onChange={(e) =>
                  setDisposeForm({
                    ...disposeForm,
                    transaction_date: e.target.value,
                  })
                }
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">
              Proceeds
            </label>
            <input
              className={`${inputCls} mt-1.5`}
              inputMode="decimal"
              value={disposeForm.disposal_amount}
              disabled={disposeForm.disposal_type === "WRITE_OFF"}
              onChange={(e) =>
                setDisposeForm({
                  ...disposeForm,
                  disposal_amount: e.target.value,
                })
              }
              placeholder={
                disposeForm.disposal_type === "WRITE_OFF"
                  ? "A write-off has no proceeds"
                  : "0 — nothing received"
              }
            />
          </div>
          {formError && <p className="text-xs text-error-600">{formError}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={() => setDisposeTarget(null)}
              className="rounded-xl border border-border-default px-3.5 py-2 text-sm font-medium text-text-secondary hover:bg-bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDispose}
              disabled={saving}
              className="rounded-xl bg-gradient-to-b from-error-500 to-error-600 px-3.5 py-2 text-sm font-semibold text-white transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? "Posting..." : "Post disposal"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
