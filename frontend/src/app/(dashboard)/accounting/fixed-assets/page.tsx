"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Banknote, FolderCog, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { createClient } from "@/lib/supabase/client";
import {
  createFixedAssetCategory,
  disposeFixedAsset,
  listFixedAssetCategories,
  listFixedAssets,
  recordAssetDepreciation,
  registerFixedAsset,
  updateFixedAssetCategory,
  type FixedAssetRegister,
} from "@/lib/api/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import {
  accountOptions,
  applyCategoryDefaults,
  automaticAssetAccountLabel,
  assetAccountBlocker,
  depreciationBlocker,
  filterAssets,
  messageOf,
  registerBlocker,
  setupNotices,
  unknownSupplierNotice,
} from "@/lib/fixed-assets/logic";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Account, AssetCategory, FixedAsset } from "@/lib/types/entities";

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
  /** "" = let the backend resolve deterministically (never an error). */
  category_id: string;
  asset_account_id: string;
  depreciation_expense_account_id: string;
  accumulated_depreciation_account_id: string;
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
  category_id: "",
  asset_account_id: "",
  depreciation_expense_account_id: "",
  accumulated_depreciation_account_id: "",
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
    depreciation_expense_account_id: "",
    accumulated_depreciation_account_id: "",
  });
  const [disposeTarget, setDisposeTarget] = useState<FixedAsset | null>(null);
  const [disposeForm, setDisposeForm] = useState({
    transaction_date: today(),
    disposal_type: "DISPOSAL",
    disposal_amount: "",
  });

  // Configuration the FORMS need: chart of accounts (GL pickers + preflight),
  // suppliers (exact-name refusals), and the asset categories themselves.
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [suppliers, setSuppliers] = useState<{ name: string }[]>([]);
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [categoriesOpen, setCategoriesOpen] = useState(false);
  const [catSaving, setCatSaving] = useState(false);
  /** Non-null = the form is editing that category instead of adding one. */
  const [catEditingId, setCatEditingId] = useState<string | null>(null);
  const [catError, setCatError] = useState<string | null>(null);
  const [catForm, setCatForm] = useState({
    name: "",
    description: "",
    default_useful_life_years: "",
    default_depreciation_method: "STRAIGHT_LINE",
    default_asset_account_id: "",
    default_depreciation_expense_account_id: "",
    default_accumulated_depreciation_account_id: "",
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

  /** Chart of accounts, suppliers and categories — everything the forms ask. */
  const loadConfig = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const [accts, sups] = await Promise.all([
      supabase
        .from("accounts")
        .select("*")
        .eq("organization_id", org.organization_id)
        .order("code"),
      supabase
        .from("suppliers")
        .select("name")
        .eq("organization_id", org.organization_id)
        .order("name"),
    ]);
    if (!accts.error) setAccounts(accts.data ?? []);
    if (!sups.error) setSuppliers(sups.data ?? []);
    try {
      setCategories((await listFixedAssetCategories()).items);
    } catch {
      /* the category list is configuration, not data — the register still works */
    }
  }, [org]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const assetAccountOptions = useMemo(
    () => accountOptions(accounts, "ASSET"),
    [accounts]
  );
  const expenseAccountOptions = useMemo(
    () => accountOptions(accounts, "EXPENSE"),
    [accounts]
  );
  /** What a register/depreciation submission would hit — shown BEFORE the 409. */
  const configNotices = useMemo(() => setupNotices(accounts), [accounts]);
  const supplierNotice = useMemo(
    () => unknownSupplierNotice(form.supplier_name, suppliers),
    [form.supplier_name, suppliers]
  );
  /**
   * Everything the register form warns about BEFORE the 409: the supplier
   * name, the chart gaps, and — when the chart has accounts but none the
   * backend could choose — the asset account the user must pick.
   */
  const registerNotices = useMemo(() => {
    const notices = [...configNotices];
    if (supplierNotice) notices.unshift(supplierNotice);
    if (accounts.length > 0) {
      const accountNotice = assetAccountBlocker(
        accounts,
        form.asset_account_id
      );
      if (accountNotice) notices.push(accountNotice);
    }
    return notices;
  }, [accounts, configNotices, supplierNotice, form.asset_account_id]);

  /**
   * Would this depreciation charge be refused? The original blocker decides
   * whether to show the pickers; the live one (including what the user has
   * just picked) is the message — it clears once the accounts are chosen.
   */
  const depNeedsAccounts = depTarget
    ? depreciationBlocker(depTarget, accounts) !== null
    : false;
  const depBlocker =
    depTarget && depNeedsAccounts
      ? depreciationBlocker(
          {
            ...depTarget,
            gl_depreciation_expense_account_id:
              depForm.depreciation_expense_account_id ||
              depTarget.gl_depreciation_expense_account_id,
            gl_accumulated_depreciation_account_id:
              depForm.accumulated_depreciation_account_id ||
              depTarget.gl_accumulated_depreciation_account_id,
          },
          accounts
        )
      : null;

  const rows = useMemo(() => register?.items ?? [], [register]);
  const filtered = useMemo(
    () => filterAssets(rows, search, status),
    [rows, search, status]
  );
  const counts = register?.counts ?? {};
  const summary = register?.summary ?? {
    purchase_cost: 0,
    accumulated_depreciation: 0,
    book_value: 0,
  };

  const handleRegister = async () => {
    const blocker = registerBlocker(form, accounts, form.asset_account_id);
    if (blocker) {
      setFormError(blocker);
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await registerFixedAsset({
        name: form.name.trim(),
        purchase_cost: Number(form.purchase_cost),
        purchase_date: form.purchase_date || undefined,
        payment_method: form.payment_method,
        supplier_name: form.supplier_name.trim() || null,
        asset_account_id: form.asset_account_id || null,
        useful_life_years: form.useful_life_years
          ? Number(form.useful_life_years)
          : null,
        depreciation_method: form.depreciation_method,
        salvage_value: form.salvage_value ? Number(form.salvage_value) : 0,
        description: form.description.trim() || null,
        category_id: form.category_id || null,
        depreciation_expense_account_id:
          form.depreciation_expense_account_id || null,
        accumulated_depreciation_account_id:
          form.accumulated_depreciation_account_id || null,
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

  /** A category supplies the policy (life + method) — the register never does. */
  const handleCategoryChange = (categoryId: string) => {
    const category = categories.find((c) => c.id === categoryId) ?? null;
    setForm((prev) => ({
      ...applyCategoryDefaults(prev, category, {
        life: "useful_life_years",
        method: "depreciation_method",
      }),
      category_id: categoryId,
      asset_account_id:
        category?.default_asset_account_id ?? prev.asset_account_id,
      depreciation_expense_account_id:
        category?.default_depreciation_expense_account_id ??
        prev.depreciation_expense_account_id,
      accumulated_depreciation_account_id:
        category?.default_accumulated_depreciation_account_id ??
        prev.accumulated_depreciation_account_id,
    }));
  };

  const handleSaveCategory = async () => {
    if (catForm.name.trim().length < 2) {
      setCatError("A category name is required.");
      return;
    }
    setCatSaving(true);
    setCatError(null);
    const payload = {
      name: catForm.name.trim(),
      description: catForm.description.trim() || null,
      default_useful_life_years: catForm.default_useful_life_years
        ? Number(catForm.default_useful_life_years)
        : null,
      default_depreciation_method: catForm.default_depreciation_method,
      default_asset_account_id: catForm.default_asset_account_id || null,
      default_depreciation_expense_account_id:
        catForm.default_depreciation_expense_account_id || null,
      default_accumulated_depreciation_account_id:
        catForm.default_accumulated_depreciation_account_id || null,
    };
    try {
      if (catEditingId) {
        await updateFixedAssetCategory(catEditingId, payload);
      } else {
        await createFixedAssetCategory(payload);
      }
      setCategories((await listFixedAssetCategories()).items);
      setCatEditingId(null);
      setCatForm({ ...catForm, name: "", description: "" });
    } catch (e) {
      setCatError(messageOf(e));
    } finally {
      setCatSaving(false);
    }
  };

  /** Load a category into the form for editing (same fields, PATCH on save). */
  const editCategory = (category: AssetCategory) => {
    setCatError(null);
    setCatEditingId(category.id);
    setCatForm({
      name: category.name,
      description: category.description ?? "",
      default_useful_life_years:
        category.default_useful_life_years != null
          ? String(category.default_useful_life_years)
          : "",
      default_depreciation_method: category.default_depreciation_method,
      default_asset_account_id: category.default_asset_account_id ?? "",
      default_depreciation_expense_account_id:
        category.default_depreciation_expense_account_id ?? "",
      default_accumulated_depreciation_account_id:
        category.default_accumulated_depreciation_account_id ?? "",
    });
  };

  const cancelCategoryEdit = () => {
    setCatEditingId(null);
    setCatError(null);
    setCatForm({
      ...catForm,
      name: "",
      description: "",
    });
  };

  const openDepreciate = (asset: FixedAsset) => {
    setFormError(null);
    setDepForm({
      transaction_date: today(),
      depreciation_amount: "",
      depreciation_expense_account_id:
        asset.gl_depreciation_expense_account_id ?? "",
      accumulated_depreciation_account_id:
        asset.gl_accumulated_depreciation_account_id ?? "",
    });
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
        depreciation_expense_account_id:
          depForm.depreciation_expense_account_id || null,
        accumulated_depreciation_account_id:
          depForm.accumulated_depreciation_account_id || null,
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
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setCatError(null);
                setCatEditingId(null);
                setCategoriesOpen(true);
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border-default bg-bg-surface px-3.5 py-2 text-sm font-medium text-text-secondary hover:bg-bg-muted transition-colors"
            >
              <FolderCog className="w-4 h-4" />
              Categories
            </button>
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
          </div>
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
          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-text-secondary">
                Category
              </label>
              <button
                onClick={() => {
                  setCatError(null);
                  setCatEditingId(null);
                  setCategoriesOpen(true);
                }}
                className="inline-flex items-center gap-1 text-xs font-medium text-ai-600 hover:text-ai-500"
              >
                <FolderCog className="w-3.5 h-3.5" />
                Manage categories
              </button>
            </div>
            <select
              className={`${inputCls} mt-1.5`}
              value={form.category_id}
              onChange={(e) => handleCategoryChange(e.target.value)}
            >
              <option value="">No category — set the policy by hand</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                  {category.default_useful_life_years
                    ? ` — ${category.default_useful_life_years} yrs`
                    : ""}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-text-muted">
              The category supplies the useful life, method and GL accounts —
              the register never invents them.
            </p>
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
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Asset account
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.asset_account_id}
                onChange={(e) =>
                  setForm({ ...form, asset_account_id: e.target.value })
                }
              >
                <option value="">{automaticAssetAccountLabel(accounts)}</option>
                {assetAccountOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Depreciation expense
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.depreciation_expense_account_id}
                onChange={(e) =>
                  setForm({
                    ...form,
                    depreciation_expense_account_id: e.target.value,
                  })
                }
              >
                <option value="">Automatic</option>
                {expenseAccountOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Accumulated depreciation
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.accumulated_depreciation_account_id}
                onChange={(e) =>
                  setForm({
                    ...form,
                    accumulated_depreciation_account_id: e.target.value,
                  })
                }
              >
                <option value="">Automatic</option>
                {assetAccountOptions
                  .filter((option) =>
                    option.label
                      .toLowerCase()
                      .includes("accumulated depreciation")
                  )
                  .map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
              </select>
            </div>
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
          {registerNotices.map((notice) => (
            <p
              key={notice}
              className="rounded-xl border border-warning-500 bg-warning-50 px-3 py-2 text-xs text-warning-600"
            >
              {notice}
            </p>
          ))}
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
          {depNeedsAccounts && (
            <div className="space-y-3 rounded-xl border border-warning-500 bg-warning-50 p-3">
              {depBlocker && (
                <p className="text-xs text-warning-600">{depBlocker}</p>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-medium text-text-secondary">
                    Depreciation expense
                  </label>
                  <select
                    className={`${inputCls} mt-1.5`}
                    value={depForm.depreciation_expense_account_id}
                    onChange={(e) =>
                      setDepForm({
                        ...depForm,
                        depreciation_expense_account_id: e.target.value,
                      })
                    }
                  >
                    <option value="">Automatic</option>
                    {expenseAccountOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-text-secondary">
                    Accumulated depreciation
                  </label>
                  <select
                    className={`${inputCls} mt-1.5`}
                    value={depForm.accumulated_depreciation_account_id}
                    onChange={(e) =>
                      setDepForm({
                        ...depForm,
                        accumulated_depreciation_account_id: e.target.value,
                      })
                    }
                  >
                    <option value="">Automatic</option>
                    {assetAccountOptions
                      .filter((option) =>
                        option.label
                          .toLowerCase()
                          .includes("accumulated depreciation")
                      )
                      .map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                  </select>
                </div>
              </div>
            </div>
          )}
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

      <Modal
        open={categoriesOpen}
        onClose={() => setCategoriesOpen(false)}
        title="Asset categories"
      >
        <div className="space-y-4">
          <p className="text-xs text-text-secondary">
            A category is configuration only: the default useful life, method
            and GL accounts that prefill the register form. Nothing is posted
            until an asset is registered against it.
          </p>

          {categories.length === 0 ? (
            <p className="rounded-xl border border-border-subtle bg-bg-muted px-3 py-2 text-xs text-text-muted">
              No categories yet — create the first one below (e.g. Vehicles,
              5 years, straight line).
            </p>
          ) : (
            <ul className="divide-y divide-border-subtle rounded-xl border border-border-subtle">
              {categories.map((category) => (
                <li key={category.id} className="px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium text-text-primary">
                      {category.name}
                    </p>
                    <div className="flex items-center gap-3">
                      <p className="text-xs text-text-muted">
                        {category.default_useful_life_years
                          ? `${category.default_useful_life_years} yrs · `
                          : ""}
                        {category.default_depreciation_method.replace(/_/g, " ")}
                      </p>
                      <button
                        onClick={() => editCategory(category)}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-lg border border-border-default px-2 py-1 text-[11px] font-medium text-text-secondary transition-colors hover:bg-bg-muted",
                          catEditingId === category.id &&
                            "border-ai-300 bg-ai-50 text-ai-700"
                        )}
                      >
                        <Pencil className="w-3 h-3" />
                        {catEditingId === category.id ? "Editing" : "Edit"}
                      </button>
                    </div>
                  </div>
                  {category.description && (
                    <p className="mt-0.5 text-xs text-text-muted">
                      {category.description}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}

          {catEditingId && (
            <p className="rounded-xl border border-ai-200 bg-ai-50 px-3 py-2 text-xs text-ai-700">
              Editing “{catForm.name || "this category"}” — Save changes updates
              its defaults. The register form uses the updated policy from the
              next asset on.
            </p>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Name *
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                value={catForm.name}
                onChange={(e) => setCatForm({ ...catForm, name: e.target.value })}
                placeholder="e.g. Vehicles"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Default useful life (years)
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                inputMode="numeric"
                value={catForm.default_useful_life_years}
                onChange={(e) =>
                  setCatForm({
                    ...catForm,
                    default_useful_life_years: e.target.value,
                  })
                }
                placeholder="e.g. 5"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Default method
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={catForm.default_depreciation_method}
                onChange={(e) =>
                  setCatForm({
                    ...catForm,
                    default_depreciation_method: e.target.value,
                  })
                }
              >
                {DEPRECIATION_METHODS.map((method) => (
                  <option key={method.value} value={method.value}>
                    {method.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Asset account
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={catForm.default_asset_account_id}
                onChange={(e) =>
                  setCatForm({
                    ...catForm,
                    default_asset_account_id: e.target.value,
                  })
                }
              >
                <option value="">None</option>
                {assetAccountOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Depreciation expense
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={catForm.default_depreciation_expense_account_id}
                onChange={(e) =>
                  setCatForm({
                    ...catForm,
                    default_depreciation_expense_account_id: e.target.value,
                  })
                }
              >
                <option value="">None</option>
                {expenseAccountOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Accumulated depreciation
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={catForm.default_accumulated_depreciation_account_id}
                onChange={(e) =>
                  setCatForm({
                    ...catForm,
                    default_accumulated_depreciation_account_id: e.target.value,
                  })
                }
              >
                <option value="">None</option>
                {assetAccountOptions
                  .filter((option) =>
                    option.label
                      .toLowerCase()
                      .includes("accumulated depreciation")
                  )
                  .map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
              </select>
            </div>
          </div>
          {catError && <p className="text-xs text-error-600">{catError}</p>}
          <div className="flex justify-end gap-2 pt-1">
            {catEditingId && (
              <button
                onClick={cancelCategoryEdit}
                className="rounded-xl border border-border-default px-3.5 py-2 text-sm font-medium text-text-secondary hover:bg-bg-muted transition-colors"
              >
                Cancel edit
              </button>
            )}
            <button
              onClick={() => setCategoriesOpen(false)}
              className="rounded-xl border border-border-default px-3.5 py-2 text-sm font-medium text-text-secondary hover:bg-bg-muted transition-colors"
            >
              Close
            </button>
            <button
              onClick={handleSaveCategory}
              disabled={catSaving}
              className="rounded-xl bg-gradient-to-b from-ai-500 to-ai-600 px-3.5 py-2 text-sm font-semibold text-white hover:from-ai-400 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {catSaving
                ? "Saving..."
                : catEditingId
                  ? "Save changes"
                  : "Add category"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

