"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Plus,
  Search,
  Pencil,
  Trash2,
  Power,
  RefreshCw,
  Package,
  Wrench,
  History,
  ArrowUpDown,
  ArrowDownRight,
  ArrowUpRight,
  AlertTriangle,
} from "lucide-react";
import PageHeader from "@/components/shared/PageHeader";
import Modal from "@/components/shared/Modal";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import { apiErrorMessage } from "@/lib/api/errors";
import {
  catalogueCreate,
  catalogueDelete,
  catalogueList,
  catalogueSetActive,
  catalogueUpdate,
  catalogueProductMovements,
  catalogueAllMovements,
  type CatalogueItem,
  type CatalogueKind,
  type StockMovement,
} from "@/lib/api/client";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

/** The service_unit_code enum (authoritative DB enum). */
const BILLING_UNITS = ["HOUR", "DAY", "MONTH", "FIXED", "ITEM"] as const;

const PRODUCT_STOCK_FILTERS = [
  { id: "ALL", label: "All Items" },
  { id: "TRACKED", label: "Stock Tracked" },
  { id: "IN_STOCK", label: "In Stock" },
  { id: "OUT_OF_STOCK", label: "Out of Stock" },
  { id: "ACTIVE", label: "Active" },
  { id: "INACTIVE", label: "Inactive" },
] as const;

const SERVICE_STATUS_FILTERS = [
  { id: "ALL", label: "All" },
  { id: "ACTIVE", label: "Active" },
  { id: "INACTIVE", label: "Inactive" },
] as const;

const MOVEMENT_DIRECTION_FILTERS = [
  { id: "ALL", label: "All Movements" },
  { id: "RECEIPT", label: "Inward Receipts (+)" },
  { id: "ISSUE", label: "Outward Issues (-)" },
] as const;

/** Refresh cadence: 20s is enough without hammering the API. */
const REFRESH_MS = 20_000;

interface ItemForm {
  name: string;
  description: string;
  // product
  unit: string;
  is_stock_tracked: boolean;
  opening_stock: string;
  unit_price: string;
  cost_price: string;
  // service
  billing_unit: string;
  standard_rate: string;
  cost_rate: string;
}

const EMPTY_FORM: ItemForm = {
  name: "",
  description: "",
  unit: "",
  is_stock_tracked: false,
  opening_stock: "",
  unit_price: "",
  cost_price: "",
  billing_unit: "HOUR",
  standard_rate: "",
  cost_rate: "",
};

function codeOf(item: CatalogueItem): string {
  return item.product_code || item.service_code || "—";
}

function statusOf(item: CatalogueItem): string {
  return item.is_active ? "ACTIVE" : "INACTIVE";
}

export default function CataloguePage() {
  const { org } = useOrg();
  const [view, setView] = useState<"products" | "services" | "movements">("products");
  const kind: CatalogueKind = view === "services" ? "services" : "products";
  const noun = kind === "products" ? "Product" : "Service";

  const [items, setItems] = useState<CatalogueItem[] | null>(null);
  const [counts, setCounts] = useState({ total: 0, active: 0, inactive: 0 });
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [movementFilter, setMovementFilter] = useState<string>("ALL");
  const [loading, setLoading] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);

  // Global Movements Ledger state
  const [allMovements, setAllMovements] = useState<StockMovement[] | null>(null);
  const [loadingMovements, setLoadingMovements] = useState(false);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<CatalogueItem | null>(null);
  const [form, setForm] = useState<ItemForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Single-product movement drawer/modal
  const [movementItem, setMovementItem] = useState<CatalogueItem | null>(null);
  const [itemMovements, setItemMovements] = useState<StockMovement[] | null>(null);
  const [loadingItemMovements, setLoadingItemMovements] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState<CatalogueItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  // Fetch individual item movement history
  useEffect(() => {
    if (!movementItem) {
      setItemMovements(null);
      return;
    }
    setLoadingItemMovements(true);
    catalogueProductMovements(movementItem.id)
      .then((data) => setItemMovements(data))
      .catch(() => setItemMovements([]))
      .finally(() => setLoadingItemMovements(false));
  }, [movementItem]);

  // Inventory KPI aggregations across products
  const totalValuation = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => sum + (it.valuation || 0), 0);
  }, [kind, items]);

  const totalStockUnits = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => sum + (it.quantity_on_hand || 0), 0);
  }, [kind, items]);

  const totalReceived = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => sum + (it.purchased_quantity || 0), 0);
  }, [kind, items]);

  const totalIssued = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => sum + (it.sold_quantity || 0), 0);
  }, [kind, items]);

  const outOfStockCount = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.filter(
      (it) => it.is_stock_tracked && (it.quantity_on_hand ?? 0) <= 0
    ).length;
  }, [kind, items]);

  const totalInbound = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => sum + (Number(it.qty_inbound_transit) || 0), 0);
  }, [kind, items]);

  const totalReserved = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => sum + (Number(it.qty_reserved) || 0), 0);
  }, [kind, items]);

  const totalCustomerPremises = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => sum + (Number(it.qty_customer_premises) || 0), 0);
  }, [kind, items]);

  const totalAvailable = useMemo(() => {
    if (!items || kind !== "products") return 0;
    return items.reduce((sum, it) => {
      const avail = it.qty_available != null ? Number(it.qty_available) : Math.max(0, (it.quantity_on_hand || 0) - (Number(it.qty_reserved) || 0));
      return sum + avail;
    }, 0);
  }, [kind, items]);

  const searchRef = useRef(search);
  useEffect(() => {
    searchRef.current = search;
  }, [search]);

  const loadMovementsData = useCallback(async () => {
    if (!org) return;
    setLoadingMovements(true);
    try {
      const data = await catalogueAllMovements(300);
      setAllMovements(data);
    } catch {
      setAllMovements([]);
    } finally {
      setLoadingMovements(false);
    }
  }, [org]);

  const load = useCallback(
    async (opts: { silent?: boolean } = {}) => {
      if (!org) return;
      if (!opts.silent) setLoading(true);
      try {
        const backendStatus =
          statusFilter === "ACTIVE" || statusFilter === "INACTIVE"
            ? statusFilter
            : "ALL";
        const data = await catalogueList(kind, {
          query: searchRef.current.trim(),
          status: backendStatus,
        });
        setItems(data.items ?? []);
        setCounts(data.counts ?? { total: 0, active: 0, inactive: 0 });
        setLastSync(new Date());
        setError(null);
      } catch (err) {
        setError(apiErrorMessage(err));
      } finally {
        if (!opts.silent) setLoading(false);
      }
    },
    [org, kind, statusFilter]
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      load();
      if (view === "movements") {
        loadMovementsData();
      }
    }, search ? 250 : 0);
    return () => clearTimeout(timer);
  }, [load, loadMovementsData, search, view]);

  useEffect(() => {
    if (view === "movements" && !allMovements) {
      loadMovementsData();
    }
  }, [view, allMovements, loadMovementsData]);

  useEffect(() => {
    const timer = setInterval(() => {
      load({ silent: true });
      if (view === "movements") {
        loadMovementsData();
      }
    }, REFRESH_MS);
    const onFocus = () => {
      load({ silent: true });
      if (view === "movements") {
        loadMovementsData();
      }
    };
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [load, loadMovementsData, view]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (item: CatalogueItem) => {
    setEditing(item);
    setForm({
      name: item.name,
      description: item.description || "",
      unit: item.unit || "",
      is_stock_tracked: item.is_stock_tracked || false,
      opening_stock:
        item.opening_quantity !== null && item.opening_quantity !== undefined
          ? String(item.opening_quantity)
          : "",
      unit_price:
        item.unit_price !== null && item.unit_price !== undefined
          ? String(item.unit_price)
          : "",
      cost_price:
        item.cost_price !== null && item.cost_price !== undefined
          ? String(item.cost_price)
          : "",
      billing_unit: item.billing_unit || "HOUR",
      standard_rate:
        item.standard_rate !== null && item.standard_rate !== undefined
          ? String(item.standard_rate)
          : "",
      cost_rate:
        item.cost_rate !== null && item.cost_rate !== undefined
          ? String(item.cost_rate)
          : "",
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) {
      setFormError(`${noun} name is required.`);
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        description: form.description.trim() || null,
      };

      if (kind === "products") {
        payload.unit = form.unit.trim() || null;
        payload.is_stock_tracked = form.is_stock_tracked;
        payload.opening_quantity =
          form.opening_stock.trim() === "" ? null : Number(form.opening_stock);
        payload.unit_price =
          form.unit_price.trim() === "" ? null : Number(form.unit_price);
        payload.cost_price =
          form.cost_price.trim() === "" ? null : Number(form.cost_price);
      } else {
        payload.billing_unit = form.billing_unit;
        payload.standard_rate =
          form.standard_rate.trim() === "" ? null : Number(form.standard_rate);
        payload.cost_rate =
          form.cost_rate.trim() === "" ? null : Number(form.cost_rate);
      }

      if (editing) {
        await catalogueUpdate(kind, editing.id, payload);
      } else {
        await catalogueCreate(kind, payload);
      }
      setModalOpen(false);
      await load();
      if (view === "movements") {
        await loadMovementsData();
      }
    } catch (err) {
      setFormError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (item: CatalogueItem) => {
    setRowBusy(item.id);
    try {
      await catalogueSetActive(kind, item.id, !item.is_active);
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setRowBusy(null);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setRowBusy(confirmDelete.id);
    setDeleteError(null);
    try {
      await catalogueDelete(kind, confirmDelete.id);
      setConfirmDelete(null);
      await load();
      if (view === "movements") {
        await loadMovementsData();
      }
    } catch (err) {
      setDeleteError(apiErrorMessage(err));
    } finally {
      setRowBusy(null);
    }
  };

  // Client-side filtering including stock conditions
  const filtered = useMemo(() => {
    let rows = items ?? [];
    if (kind === "products") {
      if (statusFilter === "TRACKED") {
        rows = rows.filter((r) => r.is_stock_tracked);
      } else if (statusFilter === "IN_STOCK") {
        rows = rows.filter(
          (r) => r.is_stock_tracked && (r.quantity_on_hand ?? 0) > 0
        );
      } else if (statusFilter === "OUT_OF_STOCK") {
        rows = rows.filter(
          (r) => r.is_stock_tracked && (r.quantity_on_hand ?? 0) <= 0
        );
      } else if (statusFilter === "ACTIVE") {
        rows = rows.filter((r) => r.is_active);
      } else if (statusFilter === "INACTIVE") {
        rows = rows.filter((r) => !r.is_active);
      }
    } else {
      if (statusFilter === "ACTIVE") {
        rows = rows.filter((r) => r.is_active);
      } else if (statusFilter === "INACTIVE") {
        rows = rows.filter((r) => !r.is_active);
      }
    }

    const term = search.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter(
      (row) =>
        row.name.toLowerCase().includes(term) ||
        codeOf(row).toLowerCase().includes(term)
    );
  }, [items, search, kind, statusFilter]);

  // Client-side filtering for global movements
  const filteredMovements = useMemo(() => {
    let rows = allMovements ?? [];
    if (movementFilter !== "ALL") {
      rows = rows.filter((m) => m.direction === movementFilter);
    }
    const term = search.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter(
      (m) =>
        (m.product_name && m.product_name.toLowerCase().includes(term)) ||
        (m.sku && m.sku.toLowerCase().includes(term)) ||
        (m.description && m.description.toLowerCase().includes(term)) ||
        (m.source_type && m.source_type.toLowerCase().includes(term))
    );
  }, [allMovements, movementFilter, search]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Products & Services Catalogue"
        subtitle="Manage inventory products, billable services, perpetual stock levels, and historical movement ledger with live valuation tracking."
        actions={
          <>
            <button
              onClick={() => {
                load();
                if (view === "movements") loadMovementsData();
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border-default bg-bg-surface px-3 py-2 text-xs font-medium text-text-secondary hover:text-text-primary hover:border-ai-300 transition-colors"
              title="Refresh now"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
            {view !== "movements" && (
              <button
                onClick={openCreate}
                className="inline-flex items-center gap-1.5 rounded-xl bg-ai-500 hover:bg-ai-600 px-4 py-2 text-sm font-medium text-white btn-3d btn-shine transition-colors"
              >
                <Plus className="w-4 h-4" />
                Add {noun}
              </button>
            )}
          </>
        }
      />

      {/* ---- Navigation Tabs ---- */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => {
            setView("products");
            setStatusFilter("ALL");
          }}
          className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition-colors ${
            view === "products"
              ? "bg-ai-500 text-white shadow-sm"
              : "bg-bg-surface border border-border-default text-text-secondary hover:text-text-primary"
          }`}
        >
          <Package className="w-4 h-4" />
          Products & Stock
        </button>

        <button
          onClick={() => {
            setView("services");
            setStatusFilter("ALL");
          }}
          className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition-colors ${
            view === "services"
              ? "bg-ai-500 text-white shadow-sm"
              : "bg-bg-surface border border-border-default text-text-secondary hover:text-text-primary"
          }`}
        >
          <Wrench className="w-4 h-4" />
          Services
        </button>

        <button
          onClick={() => {
            setView("movements");
            loadMovementsData();
          }}
          className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition-colors ${
            view === "movements"
              ? "bg-ai-500 text-white shadow-sm"
              : "bg-bg-surface border border-border-default text-text-secondary hover:text-text-primary"
          }`}
        >
          <ArrowUpDown className="w-4 h-4" />
          Stock Movements Ledger
        </button>

        <span className="ml-auto inline-flex items-center gap-1.5 text-[11px] text-text-muted">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              error ? "bg-error-500" : "bg-success-500"
            }`}
          />
          {error
            ? "not syncing"
            : lastSync
            ? `live · updated ${lastSync.toLocaleTimeString()}`
            : "connecting…"}
        </span>
      </div>

      {/* ---- Multi-State Stock Pipeline KPI Strip ---- */}
      {view !== "services" ? (
        <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-6">
          <div className="bg-bg-surface rounded-2xl border border-border-subtle px-3.5 py-3">
            <p className="text-[10px] uppercase tracking-wide text-text-muted font-medium">
              Total Valuation
            </p>
            <p className="text-base font-bold text-text-primary mt-0.5">
              {formatCurrency(totalValuation, org?.base_currency_code)}
            </p>
          </div>

          <div className="bg-bg-surface rounded-2xl border border-border-subtle px-3.5 py-3">
            <p className="text-[10px] uppercase tracking-wide text-text-muted font-medium" title="Physical stock inside warehouse">
              Warehouse On-Hand (Q_on_hand)
            </p>
            <p className="text-base font-bold text-text-primary mt-0.5">
              {totalStockUnits.toLocaleString()}
            </p>
          </div>

          <div className="bg-bg-surface rounded-2xl border border-purple-200/50 bg-purple-50/20 px-3.5 py-3">
            <p className="text-[10px] uppercase tracking-wide text-purple-700 font-medium" title="Purchased goods on confirmed PO in transit">
              Inbound In-Flight (Q_inbound)
            </p>
            <p className="text-base font-bold text-purple-800 mt-0.5">
              +{totalInbound.toLocaleString()}
            </p>
          </div>

          <div className="bg-bg-surface rounded-2xl border border-amber-200/50 bg-amber-50/20 px-3.5 py-3">
            <p className="text-[10px] uppercase tracking-wide text-amber-700 font-medium" title="Allocated to accepted sales orders">
              Reserved (Q_reserved)
            </p>
            <p className="text-base font-bold text-amber-800 mt-0.5">
              -{totalReserved.toLocaleString()}
            </p>
          </div>

          <div className="bg-bg-surface rounded-2xl border border-sky-200/50 bg-sky-50/20 px-3.5 py-3">
            <p className="text-[10px] uppercase tracking-wide text-sky-700 font-medium" title="Consignment / in-flight on customer premises">
              Customer Site (Q_premises)
            </p>
            <p className="text-base font-bold text-sky-800 mt-0.5">
              {totalCustomerPremises.toLocaleString()}
            </p>
          </div>

          <div className="bg-bg-surface rounded-2xl border border-emerald-200/50 bg-emerald-50/20 px-3.5 py-3">
            <p className="text-[10px] uppercase tracking-wide text-emerald-700 font-medium" title="Usable stock: On-Hand - Reserved">
              Available to Promise
            </p>
            <p className="text-base font-bold text-emerald-800 mt-0.5">
              {totalAvailable.toLocaleString()}
            </p>
          </div>
        </div>
      ) : (
        <div className="grid gap-3 grid-cols-3">
          <div className="bg-bg-surface rounded-2xl border border-border-subtle px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-text-muted">
              Total Services
            </p>
            <p className="text-lg font-semibold text-text-primary">
              {counts.total}
            </p>
          </div>
          <div className="bg-bg-surface rounded-2xl border border-border-subtle px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-text-muted">
              Active
            </p>
            <p className="text-lg font-semibold text-success-600">
              {counts.active}
            </p>
          </div>
          <div className="bg-bg-surface rounded-2xl border border-border-subtle px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-text-muted">
              Inactive
            </p>
            <p className="text-lg font-semibold text-text-muted">
              {counts.inactive}
            </p>
          </div>
        </div>
      )}

      {/* ---- Toolbar (Search & Filter Pills) ---- */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            className={`${inputCls} pl-9`}
            placeholder={
              view === "movements"
                ? "Search movements by product name, SKU, or reference..."
                : `Search ${kind} by name or code…`
            }
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap gap-1.5">
          {view === "products" &&
            PRODUCT_STOCK_FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setStatusFilter(f.id)}
                className={`rounded-xl px-3 py-2 text-xs font-medium transition-colors ${
                  statusFilter === f.id
                    ? "bg-brand-navy text-white shadow-sm"
                    : "bg-bg-surface border border-border-default text-text-secondary hover:text-text-primary"
                }`}
              >
                {f.label}
              </button>
            ))}

          {view === "services" &&
            SERVICE_STATUS_FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setStatusFilter(f.id)}
                className={`rounded-xl px-3 py-2 text-xs font-medium transition-colors ${
                  statusFilter === f.id
                    ? "bg-brand-navy text-white shadow-sm"
                    : "bg-bg-surface border border-border-default text-text-secondary hover:text-text-primary"
                }`}
              >
                {f.label}
              </button>
            ))}

          {view === "movements" &&
            MOVEMENT_DIRECTION_FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setMovementFilter(f.id)}
                className={`rounded-xl px-3 py-2 text-xs font-medium transition-colors ${
                  movementFilter === f.id
                    ? "bg-brand-navy text-white shadow-sm"
                    : "bg-bg-surface border border-border-default text-text-secondary hover:text-text-primary"
                }`}
              >
                {f.label}
              </button>
            ))}
        </div>
      </div>

      {/* ---- View Content: Products/Services Table vs Movements Ledger ---- */}
      {view !== "movements" ? (
        <>
          {error && <ErrorState message={error} />}

          {!error && loading && !items && <TableSkeleton rows={6} cols={5} />}

          {!error && items && filtered.length === 0 && (
            <EmptyState
              title={search ? `No ${kind} match “${search}”` : `No ${kind} yet`}
              hint={
                search
                  ? "Try a different search query or reset your stock filter."
                  : `Add your first ${noun} — the AI agent then uses it on invoices and bills instead of inventing a line item.`
              }
            />
          )}

          {!error && items && filtered.length > 0 && (
            <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                      <th className="px-4 py-3 font-medium">Code</th>
                      <th className="px-4 py-3 font-medium">Name</th>
                      <th className="px-4 py-3 font-medium" title={kind === "products" ? "Moving average cost for stock-tracked products, or base unit price" : undefined}>
                        {kind === "products" ? "Unit price (Avg Cost)" : "Standard rate"}
                      </th>
                      <th className="px-4 py-3 font-medium">
                        {kind === "products" ? "Unit" : "Billed per"}
                      </th>
                      {kind === "products" && (
                        <>
                          <th className="px-3 py-3 font-medium text-right" title="Opening balance">
                            Opening
                          </th>
                          <th className="px-3 py-3 font-medium text-right" title="Purchases during period">
                            Inward (+)
                          </th>
                          <th className="px-3 py-3 font-medium text-right" title="Sales during period">
                            Outward (-)
                          </th>
                          <th className="px-3 py-3 font-medium text-right" title="Closing stock position at t₀">
                            Closing (t₀)
                          </th>
                          <th className="px-3 py-3 font-medium text-right" title="Closing valuation">
                            Valuation
                          </th>
                        </>
                      )}
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((item) => (
                      <tr
                        key={item.id}
                        className="border-b border-border-subtle last:border-0 hover:bg-bg-muted/40 transition-colors"
                      >
                        <td className="px-4 py-3 font-mono text-xs text-text-secondary">
                          {codeOf(item)}
                        </td>
                        <td className="px-4 py-3">
                          <p className="font-medium text-text-primary">{item.name}</p>
                          {item.description && (
                            <p className="text-xs text-text-muted line-clamp-1">
                              {item.description}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3 text-text-primary">
                          <div>
                            <span className="font-medium">
                              {formatCurrency(
                                Number(
                                  kind === "products"
                                    ? (item.is_stock_tracked && item.average_cost != null && item.average_cost > 0
                                        ? item.average_cost
                                        : item.unit_price ?? 0)
                                    : item.standard_rate ?? 0
                                ),
                                org?.base_currency_code
                              )}
                            </span>
                            {kind === "products" && item.is_stock_tracked && (
                              <span className="block text-[10px] text-text-muted font-normal">
                                {item.average_cost != null && item.average_cost > 0 ? "Avg cost" : "Unit price"}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-text-secondary">
                          {kind === "products"
                            ? item.unit || "—"
                            : item.billing_unit || "—"}
                        </td>
                        {kind === "products" && (
                          <>
                            <td className="px-3 py-3 text-right text-xs tabular-nums text-text-secondary">
                              {item.is_stock_tracked ? (item.opening_quantity ?? 0) : "—"}
                            </td>
                            <td className="px-3 py-3 text-right text-xs tabular-nums text-success-600 font-medium">
                              {item.is_stock_tracked ? `+${item.purchased_quantity ?? 0}` : "—"}
                            </td>
                            <td className="px-3 py-3 text-right text-xs tabular-nums text-error-600 font-medium">
                              {item.is_stock_tracked ? `-${item.sold_quantity ?? 0}` : "—"}
                            </td>
                            <td className="px-3 py-3 text-right">
                              {item.is_stock_tracked ? (
                                <span
                                  className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums ${
                                    (item.quantity_on_hand ?? 0) > 0
                                      ? "bg-success-100 text-success-800"
                                      : "bg-error-100 text-error-800"
                                  }`}
                                  title="Closing units on hand at t₀ = Opening + Inward - Outward"
                                >
                                  {item.quantity_on_hand ?? 0}
                                </span>
                              ) : (
                                <span className="text-text-muted" title="Not stock-tracked">—</span>
                              )}
                            </td>
                            <td className="px-3 py-3 text-right text-xs tabular-nums font-medium text-text-primary">
                              {item.is_stock_tracked
                                ? formatCurrency(Number(item.valuation ?? 0), org?.base_currency_code)
                                : "—"}
                            </td>
                          </>
                        )}
                        <td className="px-4 py-3">
                          <StatusBadge status={statusOf(item)} />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1.5">
                            {kind === "products" && item.is_stock_tracked && (
                              <button
                                onClick={() => setMovementItem(item)}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-ai-600 hover:border-ai-300 transition-colors"
                                title="Stock Movement Ledger (Tracing)"
                              >
                                <History className="w-3.5 h-3.5" />
                                Tracing
                              </button>
                            )}
                            <button
                              onClick={() => openEdit(item)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary hover:border-ai-300 transition-colors"
                            >
                              <Pencil className="w-3.5 h-3.5" />
                              Edit
                            </button>
                            <button
                              onClick={() => handleToggleActive(item)}
                              disabled={rowBusy === item.id}
                              title={
                                item.is_active
                                  ? "Deactivate — keeps history, hides it from pickers"
                                  : "Reactivate"
                              }
                              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary hover:border-warning-300 transition-colors disabled:opacity-40"
                            >
                              <Power className="w-3.5 h-3.5" />
                              {item.is_active ? "Deactivate" : "Activate"}
                            </button>
                            <button
                              onClick={() => {
                                setConfirmDelete(item);
                                setDeleteError(null);
                              }}
                              title="Delete — only possible while no document uses it"
                              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs font-medium text-error-600 hover:border-error-300 transition-colors"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : (
        /* ---- Global Stock Movements Ledger Table ---- */
        <div className="space-y-3">
          {loadingMovements && !allMovements && <TableSkeleton rows={8} cols={7} />}

          {!loadingMovements && filteredMovements.length === 0 && (
            <EmptyState
              title={
                search
                  ? `No movements match “${search}”`
                  : "No stock movements recorded yet"
              }
              hint={
                search
                  ? "Try searching by another product name, SKU, or clear your direction filter."
                  : "Stock movements automatically register whenever purchase bills, invoices, or manual inventory adjustments are recorded."
              }
            />
          )}

          {filteredMovements.length > 0 && (
            <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                      <th className="px-4 py-3 font-medium">Date & Time</th>
                      <th className="px-4 py-3 font-medium">Product / Item</th>
                      <th className="px-4 py-3 font-medium">Direction</th>
                      <th className="px-4 py-3 font-medium text-right">Quantity</th>
                      <th className="px-4 py-3 font-medium text-right">Unit Cost</th>
                      <th className="px-4 py-3 font-medium text-right">Movement Valuation</th>
                      <th className="px-4 py-3 font-medium">Reference / Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredMovements.map((m) => {
                      const isReceipt = m.direction === "RECEIPT";
                      const dateStr = m.movement_date || m.created_at;
                      const formattedDate = dateStr
                        ? new Date(dateStr).toLocaleString("en-GB", {
                            dateStyle: "medium",
                            timeStyle: "short",
                          })
                        : "—";

                      return (
                        <tr
                          key={m.id}
                          className="border-b border-border-subtle last:border-0 hover:bg-bg-muted/40 transition-colors"
                        >
                          <td className="px-4 py-3 font-mono text-xs text-text-secondary whitespace-nowrap">
                            {formattedDate}
                          </td>
                          <td className="px-4 py-3">
                            <p className="font-medium text-text-primary">
                              {m.product_name || "—"}
                            </p>
                            {m.sku && (
                              <p className="font-mono text-[11px] text-text-muted">
                                SKU: {m.sku}
                              </p>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            {isReceipt ? (
                              <span className="inline-flex items-center gap-1 rounded-md bg-success-50 px-2 py-0.5 text-xs font-semibold text-success-700 border border-success-200">
                                <ArrowDownRight className="w-3.5 h-3.5 text-success-600" />
                                INWARD (+)
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700 border border-amber-200">
                                <ArrowUpRight className="w-3.5 h-3.5 text-amber-600" />
                                OUTWARD (-)
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs font-semibold tabular-nums whitespace-nowrap">
                            <span className={isReceipt ? "text-success-600" : "text-amber-600"}>
                              {isReceipt ? `+${m.quantity}` : `-${m.quantity}`} {m.unit || ""}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-xs tabular-nums text-text-secondary whitespace-nowrap">
                            {formatCurrency(m.unit_cost, org?.base_currency_code)}
                          </td>
                          <td className="px-4 py-3 text-right text-xs tabular-nums font-semibold text-text-primary whitespace-nowrap">
                            {formatCurrency(
                              m.valuation ?? (m.quantity * m.unit_cost),
                              org?.base_currency_code
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs text-text-secondary max-w-xs">
                            <p className="font-medium text-text-primary truncate">
                              {m.source_type || "DIRECT"}
                            </p>
                            {m.description && (
                              <p className="text-[11px] text-text-muted truncate">
                                {m.description}
                              </p>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ---- Create / Edit Modal ---- */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? `Edit ${noun}` : `Add New ${noun}`}
      >
        <form onSubmit={handleSave} className="space-y-4">
          {formError && <ErrorState message={formError} />}

          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              Name <span className="text-error-500">*</span>
            </label>
            <input
              className={inputCls}
              placeholder={
                kind === "products" ? "e.g. Ergonomic Office Chair" : "e.g. Audit Consulting"
              }
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              Description (optional)
            </label>
            <textarea
              className={`${inputCls} min-h-[70px] resize-y`}
              placeholder="Internal notes or customer-facing description..."
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>

          {kind === "products" ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-text-secondary mb-1">
                    Selling / Unit Price
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className={inputCls}
                    placeholder="0.00"
                    value={form.unit_price}
                    onChange={(e) =>
                      setForm({ ...form, unit_price: e.target.value })
                    }
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-secondary mb-1">
                    Cost Price
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className={inputCls}
                    placeholder="0.00"
                    value={form.cost_price}
                    onChange={(e) =>
                      setForm({ ...form, cost_price: e.target.value })
                    }
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-text-secondary mb-1">
                    Unit of Measure
                  </label>
                  <input
                    className={inputCls}
                    placeholder="e.g. pcs, kg, box"
                    value={form.unit}
                    onChange={(e) => setForm({ ...form, unit: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-secondary mb-1">
                    Opening Stock (Units)
                  </label>
                  <input
                    type="number"
                    step="1"
                    min="0"
                    disabled={!!editing}
                    className={`${inputCls} disabled:opacity-50`}
                    placeholder="0"
                    value={form.opening_stock}
                    onChange={(e) =>
                      setForm({ ...form, opening_stock: e.target.value })
                    }
                  />
                </div>
              </div>

              <label className="flex items-center gap-2 cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={form.is_stock_tracked}
                  onChange={(e) =>
                    setForm({ ...form, is_stock_tracked: e.target.checked })
                  }
                  className="rounded border-border-default text-ai-500 focus:ring-ai-100 w-4 h-4"
                />
                <span className="text-xs font-medium text-text-primary">
                  Track perpetual stock levels & valuation for this product
                </span>
              </label>
            </>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Billing Unit
                </label>
                <select
                  className={inputCls}
                  value={form.billing_unit}
                  onChange={(e) =>
                    setForm({ ...form, billing_unit: e.target.value })
                  }
                >
                  {BILLING_UNITS.map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Standard Rate
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className={inputCls}
                  placeholder="0.00"
                  value={form.standard_rate}
                  onChange={(e) =>
                    setForm({ ...form, standard_rate: e.target.value })
                  }
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Cost Rate
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className={inputCls}
                  placeholder="0.00"
                  value={form.cost_rate}
                  onChange={(e) =>
                    setForm({ ...form, cost_rate: e.target.value })
                  }
                />
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2 border-t border-border-subtle">
            <button
              type="button"
              onClick={() => setModalOpen(false)}
              className="rounded-xl border border-border-default bg-bg-surface px-4 py-2 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-ai-500 hover:bg-ai-600 px-4 py-2 text-xs font-medium text-white transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : editing ? "Save Changes" : `Create ${noun}`}
            </button>
          </div>
        </form>
      </Modal>

      {/* ---- Individual Product Tracing Modal ---- */}
      <Modal
        open={!!movementItem}
        onClose={() => setMovementItem(null)}
        title={`Stock Tracing: ${movementItem?.name || ""}`}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-2 bg-bg-muted/40 rounded-xl p-3 text-xs">
            <div>
              <p className="text-text-muted">Units On Hand</p>
              <p className="font-semibold text-text-primary">
                {movementItem?.quantity_on_hand ?? 0} {movementItem?.unit || ""}
              </p>
            </div>
            <div>
              <p className="text-text-muted">Moving Avg Cost</p>
              <p className="font-semibold text-text-primary">
                {formatCurrency(movementItem?.average_cost ?? movementItem?.cost_price ?? 0, org?.base_currency_code)}
              </p>
            </div>
            <div>
              <p className="text-text-muted">Total Valuation</p>
              <p className="font-semibold text-text-primary">
                {formatCurrency(movementItem?.valuation ?? 0, org?.base_currency_code)}
              </p>
            </div>
          </div>

          {loadingItemMovements && <TableSkeleton rows={4} cols={4} />}

          {!loadingItemMovements && itemMovements && itemMovements.length === 0 && (
            <p className="text-center text-xs text-text-muted py-6">
              No stock movements recorded for this item yet.
            </p>
          )}

          {!loadingItemMovements && itemMovements && itemMovements.length > 0 && (
            <div className="max-h-80 overflow-y-auto rounded-xl border border-border-subtle">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-subtle bg-bg-muted/30 text-left text-[10px] uppercase tracking-wide text-text-muted">
                    <th className="px-3 py-2">Date</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2 text-right">Qty</th>
                    <th className="px-3 py-2 text-right">Cost</th>
                    <th className="px-3 py-2">Reference</th>
                  </tr>
                </thead>
                <tbody>
                  {itemMovements.map((m) => (
                    <tr
                      key={m.id}
                      className="border-b border-border-subtle last:border-0"
                    >
                      <td className="px-3 py-2 font-mono text-[11px] text-text-secondary">
                        {m.movement_date || m.created_at
                          ? new Date(m.movement_date || m.created_at).toLocaleDateString()
                          : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`font-semibold ${
                            m.direction === "RECEIPT"
                              ? "text-success-600"
                              : "text-amber-600"
                          }`}
                        >
                          {m.direction === "RECEIPT" ? "Inward (+)" : "Outward (-)"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums font-medium">
                        {m.direction === "RECEIPT" ? `+${m.quantity}` : `-${m.quantity}`}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
                        {formatCurrency(m.unit_cost, org?.base_currency_code)}
                      </td>
                      <td className="px-3 py-2 text-text-muted truncate max-w-[140px]">
                        {m.source_type || m.description || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex justify-end pt-2">
            <button
              onClick={() => setMovementItem(null)}
              className="rounded-xl border border-border-default bg-bg-surface px-4 py-2 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </Modal>

      {/* ---- Delete Confirmation Modal ---- */}
      <Modal
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        title={`Delete ${noun}?`}
      >
        <div className="space-y-4">
          <p className="text-sm text-text-secondary">
            Are you sure you want to delete{" "}
            <span className="font-semibold text-text-primary">
              {confirmDelete?.name}
            </span>
            ? If any transaction or invoice references this {noun.toLowerCase()},
            the system will refuse deletion to safeguard accounting integrity.
          </p>

          {deleteError && <ErrorState message={deleteError} />}

          <div className="flex justify-end gap-2 pt-2 border-t border-border-subtle">
            <button
              onClick={() => setConfirmDelete(null)}
              className="rounded-xl border border-border-default bg-bg-surface px-4 py-2 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={!!rowBusy}
              className="rounded-xl bg-error-600 hover:bg-error-700 px-4 py-2 text-xs font-medium text-white transition-colors disabled:opacity-50"
            >
              {rowBusy ? "Deleting..." : "Delete Permanently"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
