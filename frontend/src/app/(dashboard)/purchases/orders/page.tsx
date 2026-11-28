"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Plus,
  Search,
  Truck,
  FileText,
  CheckCircle2,
  AlertCircle,
  X,
  ArrowRight,
  GitBranch,
  ExternalLink,
} from "lucide-react";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import PartyCombobox from "@/components/shared/PartyCombobox";
import { EmptyState, TableSkeleton } from "@/components/shared/States";
import {
  purchaseOrderList,
  purchaseOrderCreate,
  purchaseOrderGet,
  purchaseOrderStatusUpdate,
  catalogueList,
  type PurchaseOrder,
  type PurchaseOrderChainNode,
  type PurchaseOrderItem,
  type CatalogueItem,
} from "@/lib/api/client";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface LineDraft {
  product_id: string;
  description: string;
  quantity: string;
  unit_price: string;
  tax_amount: string;
}

const STAGE_TABS: { key: string; label: string }[] = [
  { key: "ALL", label: "All Stages" },
  { key: "RFQ", label: "RFQ" },
  { key: "ORDERED", label: "Ordered (PO)" },
  { key: "RECEIVED", label: "Received (GRN)" },
  { key: "BILLED", label: "Billed" },
  { key: "CANCELLED", label: "Cancelled" },
];

const STAGE_LABELS: Record<string, string> = {
  RFQ: "RFQ",
  ORDERED: "PO",
  RECEIVED: "GRN",
  BILLED: "Bill",
};

const today = () => new Date().toISOString().slice(0, 10);

export default function PurchaseOrdersPage() {
  const { org } = useOrg();
  const [orders, setOrders] = useState<PurchaseOrder[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [transitionBanner, setTransitionBanner] = useState<{
    message: string;
    targetTab?: string;
    targetDoc?: string;
  } | null>(null);

  // New PO Modal
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [supplierId, setSupplierId] = useState("");
  const [orderStatus, setOrderStatus] = useState<"RFQ" | "ORDERED">("RFQ");
  const [orderDate, setOrderDate] = useState(today());
  const [expectedDate, setExpectedDate] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([
    { product_id: "", description: "", quantity: "1", unit_price: "", tax_amount: "0" },
  ]);

  // Product Catalog for quick selection
  const [products, setProducts] = useState<CatalogueItem[]>([]);

  // Detailed View Modal (enriched with line items + full stage lineage)
  const [viewingOrder, setViewingOrder] = useState<PurchaseOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Support deep links like /purchases/orders?tab=RECEIVED&doc=GRN-000001
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab");
    const doc = params.get("doc");
    if (tab && STAGE_TABS.some((t) => t.key === tab.toUpperCase())) {
      setStatusFilter(tab.toUpperCase());
    }
    if (doc) {
      setSearch(doc);
    }
  }, []);

  const loadData = useCallback(async () => {
    if (!org) return;
    setLoading(true);
    setError(null);
    try {
      const res = await purchaseOrderList("ALL", "");
      setOrders(res.orders || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load purchase orders.";
      setError(msg);
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, [org]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Load products for dropdown
  useEffect(() => {
    if (!org) return;
    catalogueList("products")
      .then((res) => setProducts(res.items || []))
      .catch(() => setProducts([]));
  }, [org]);

  const openDocumentModal = useCallback(async (order: PurchaseOrder) => {
    setViewingOrder(order);
    setDetailLoading(true);
    try {
      const res = await purchaseOrderGet(order.id);
      if (res?.order) {
        setViewingOrder(res.order);
      }
    } catch {
      // Keep summary data if detail lookup fails in offline/partial state
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const jumpToStageDoc = useCallback(
    async (stage: string, docNumber: string, docId?: string) => {
      if (STAGE_TABS.some((t) => t.key === stage.toUpperCase())) {
        setStatusFilter(stage.toUpperCase());
      }
      setSearch(docNumber);
      const match = (orders || []).find(
        (o) => (docId && o.id === docId) || o.po_number === docNumber
      );
      if (match) {
        await openDocumentModal(match);
      }
    },
    [orders, openDocumentModal]
  );

  const filteredOrders = useMemo(() => {
    if (!orders) return [];
    const byTab =
      statusFilter === "ALL"
        ? orders
        : orders.filter((o) => String(o.status || "").toUpperCase() === statusFilter);
    if (!search.trim()) return byTab;
    const q = search.trim().toLowerCase();
    return byTab.filter((o) => {
      const chainText = (o.chain || []).map((c) => c.doc_number).join(" ").toLowerCase();
      return (
        o.po_number.toLowerCase().includes(q) ||
        Boolean(o.supplier_name && o.supplier_name.toLowerCase().includes(q)) ||
        Boolean(o.promoted_to_po_number && o.promoted_to_po_number.toLowerCase().includes(q)) ||
        Boolean(o.promoted_to_bill_number && o.promoted_to_bill_number.toLowerCase().includes(q)) ||
        Boolean(o.source_rfq_number && o.source_rfq_number.toLowerCase().includes(q)) ||
        Boolean(o.source_po_number && o.source_po_number.toLowerCase().includes(q)) ||
        Boolean(o.source_grn_number && o.source_grn_number.toLowerCase().includes(q)) ||
        chainText.includes(q)
      );
    });
  }, [orders, statusFilter, search]);

  // Org-wide pipeline KPIs across open stage heads (promoted ancestors stay visible in tabs without 2x/3x counting)
  const metrics = useMemo(() => {
    if (!orders) return { total: 0, rfq: 0, ordered: 0, received: 0, billed: 0, value: 0 };
    return {
      total: orders.length,
      rfq: orders.filter((o) => o.status === "RFQ" && !o.is_promoted).length,
      ordered: orders.filter((o) => o.status === "ORDERED" && !o.is_promoted).length,
      received: orders.filter((o) => o.status === "RECEIVED" && !o.is_promoted).length,
      billed: orders.filter((o) => o.status === "BILLED").length,
      value: orders
        .filter((o) => !o.is_promoted && o.status !== "CANCELLED")
        .reduce((sum, o) => sum + (o.total || 0), 0),
    };
  }, [orders]);

  const handleAddLine = () => {
    setLines([...lines, { product_id: "", description: "", quantity: "1", unit_price: "", tax_amount: "0" }]);
  };

  const handleRemoveLine = (idx: number) => {
    if (lines.length <= 1) return;
    setLines(lines.filter((_, i) => i !== idx));
  };

  const handleProductSelect = (idx: number, pid: string) => {
    const prod = products.find((p) => p.id === pid);
    const updated = [...lines];
    updated[idx].product_id = pid;
    if (prod) {
      if (!updated[idx].description) updated[idx].description = prod.name;
      if (!updated[idx].unit_price && prod.cost_price != null) {
        updated[idx].unit_price = String(prod.cost_price);
      }
    }
    setLines(updated);
  };

  const formSubtotal = useMemo(() => {
    return lines.reduce((sum, l) => {
      const q = parseFloat(l.quantity) || 0;
      const p = parseFloat(l.unit_price) || 0;
      return sum + q * p;
    }, 0);
  }, [lines]);

  const formTax = useMemo(() => {
    return lines.reduce((sum, l) => sum + (parseFloat(l.tax_amount) || 0), 0);
  }, [lines]);

  const formTotal = formSubtotal + formTax;

  const handleCreateOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!lines.length || !lines[0].description) {
      setFormError("At least one line item with a description is required.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const itemsPayload: PurchaseOrderItem[] = lines.map((l) => ({
        product_id: l.product_id || null,
        description: l.description,
        quantity: parseFloat(l.quantity) || 1,
        unit_price: parseFloat(l.unit_price) || 0,
        tax_amount: parseFloat(l.tax_amount) || 0,
        line_total: (parseFloat(l.quantity) || 1) * (parseFloat(l.unit_price) || 0) + (parseFloat(l.tax_amount) || 0),
      }));

      await purchaseOrderCreate({
        supplier_id: supplierId || null,
        status: orderStatus,
        order_date: orderDate,
        expected_delivery_date: expectedDate || null,
        notes: notes || null,
        items: itemsPayload,
      });

      setModalOpen(false);
      setSupplierId("");
      setOrderStatus("RFQ");
      setLines([{ product_id: "", description: "", quantity: "1", unit_price: "", tax_amount: "0" }]);
      setNotes("");
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create order.";
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleStatusTransition = async (order: PurchaseOrder, nextStatus: string) => {
    setRowBusy(order.id);
    setError(null);
    try {
      const res = await purchaseOrderStatusUpdate(order.id, nextStatus, true, nextStatus === "BILLED");
      const promoted = res?.order as (PurchaseOrder & { created_bill?: { bill_number?: string } }) | undefined;
      if (nextStatus === "ORDERED" && promoted?.po_number) {
        setTransitionBanner({
          message: `Preserved ${order.po_number} in RFQ and issued Purchase Order ${promoted.po_number}.`,
          targetTab: "ORDERED",
          targetDoc: promoted.po_number,
        });
      } else if (nextStatus === "RECEIVED" && promoted?.po_number) {
        setTransitionBanner({
          message: `Preserved ${order.po_number} in Ordered and recorded Goods Receipt Note ${promoted.po_number}.`,
          targetTab: "RECEIVED",
          targetDoc: promoted.po_number,
        });
      } else if (nextStatus === "BILLED") {
        const billNum = promoted?.created_bill?.bill_number || promoted?.po_number;
        setTransitionBanner({
          message: `Preserved ${order.po_number} in Received (GRN) and generated Purchase Bill ${billNum || ""}.`,
          targetTab: "BILLED",
          targetDoc: billNum,
        });
      }
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Status transition failed";
      setError(msg);
    } finally {
      setRowBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Purchase Orders & RFQs"
        subtitle="Linked stage pipeline: RFQ (RFQ-#) → Confirmed PO (PO-#) → Goods Receipt Note (GRN-#) → Purchase Bill (PUR-#) with full backward provenance."
        actions={
          <button
            onClick={() => setModalOpen(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-ai-500 text-white font-medium text-sm hover:bg-ai-600 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" /> New Order / RFQ
          </button>
        }
      />

      {error && (
        <div className="p-3.5 rounded-xl bg-error-50 border border-error-200 text-xs text-error-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {transitionBanner && (
        <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <GitBranch className="w-4 h-4 shrink-0 text-emerald-600" />
            <span>{transitionBanner.message}</span>
          </div>
          <div className="flex items-center gap-2">
            {transitionBanner.targetTab && (
              <button
                type="button"
                onClick={() => {
                  setStatusFilter(transitionBanner.targetTab!);
                  setSearch("");
                }}
                className="px-2.5 py-1 rounded-lg bg-emerald-600 text-white font-medium hover:bg-emerald-700 transition-colors"
              >
                Open {STAGE_TABS.find((t) => t.key === transitionBanner.targetTab)?.label || transitionBanner.targetTab}
              </button>
            )}
            <button
              type="button"
              onClick={() => setTransitionBanner(null)}
              className="p-1 rounded-lg hover:bg-emerald-100 text-emerald-700"
              aria-label="Dismiss promotion notice"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Metrics Banner */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="bg-bg-surface border border-border-default rounded-2xl p-4">
          <p className="text-xs text-text-muted">Stage Documents</p>
          <p className="text-2xl font-bold text-text-primary mt-1">{metrics.total}</p>
        </div>
        <div className="bg-bg-surface border border-blue-200/50 bg-blue-50/20 rounded-2xl p-4">
          <p className="text-xs text-blue-700 font-medium">Open RFQs</p>
          <p className="text-2xl font-bold text-blue-800 mt-1">{metrics.rfq}</p>
        </div>
        <div className="bg-bg-surface border border-purple-200/50 bg-purple-50/20 rounded-2xl p-4">
          <p className="text-xs text-purple-700 font-medium">Inbound In-Flight (PO)</p>
          <p className="text-2xl font-bold text-purple-800 mt-1">{metrics.ordered}</p>
        </div>
        <div className="bg-bg-surface border border-emerald-200/50 bg-emerald-50/20 rounded-2xl p-4">
          <p className="text-xs text-emerald-700 font-medium">Pending Billing (GRN)</p>
          <p className="text-2xl font-bold text-emerald-800 mt-1">{metrics.received}</p>
        </div>
        <div className="bg-bg-surface border border-border-default rounded-2xl p-4">
          <p className="text-xs text-text-muted">Pipeline Valuation</p>
          <p className="text-2xl font-bold text-text-primary mt-1">{formatCurrency(metrics.value)}</p>
        </div>
      </div>

      {/* Controls & Filter Tabs */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="flex items-center gap-1.5 bg-bg-surface p-1 rounded-xl border border-border-default overflow-x-auto w-full sm:w-auto">
          {STAGE_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setStatusFilter(tab.key)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                statusFilter === tab.key
                  ? "bg-ai-500 text-white"
                  : "text-text-muted hover:text-text-primary hover:bg-bg-muted"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-2.5" />
          <input
            id="po-search"
            name="po-search"
            type="text"
            aria-label="Search purchase orders"
            placeholder="Search RFQ #, PO #, GRN #, Bill # or supplier..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-7 py-1.5 rounded-xl bg-bg-surface border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-2.5 top-2 text-text-muted hover:text-text-primary"
              aria-label="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Orders Table */}
      <div className="bg-bg-surface border border-border-default rounded-2xl overflow-hidden shadow-sm">
        {loading ? (
          <TableSkeleton rows={5} cols={7} />
        ) : filteredOrders.length === 0 ? (
          <EmptyState
            title="No procurement documents found"
            hint="Create an RFQ or Purchase Order, or switch stages above."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-border-subtle bg-bg-muted/50 text-xs font-medium text-text-muted uppercase tracking-wider">
                  <th className="px-5 py-3.5">Document #</th>
                  <th className="px-5 py-3.5">Supplier</th>
                  <th className="px-5 py-3.5">Date</th>
                  <th className="px-5 py-3.5">Stage &amp; Traceability</th>
                  <th className="px-5 py-3.5 text-right">Total</th>
                  <th className="px-5 py-3.5 text-center">Lifecycle Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {filteredOrders.map((order) => {
                  const upstreamNodes: PurchaseOrderChainNode[] = (order.chain || []).filter(
                    (c) =>
                      !c.is_current &&
                      ((order.status === "ORDERED" && c.stage === "RFQ") ||
                        (order.status === "RECEIVED" && (c.stage === "ORDERED" || c.stage === "RFQ")) ||
                        (order.status === "BILLED" && c.stage !== "BILLED"))
                  );
                  return (
                    <tr key={order.id} className="hover:bg-bg-muted/30 transition-colors">
                      <td className="px-5 py-3.5 font-medium text-text-primary">
                        <button
                          type="button"
                          onClick={() => openDocumentModal(order)}
                          className="text-ai-600 hover:underline font-mono text-xs font-semibold"
                        >
                          {order.po_number}
                        </button>
                        {order.record_type === "BILL" && order.bill_status && (
                          <div className="text-[10.5px] text-text-muted mt-0.5">
                            Bill status: {order.bill_status}
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-text-primary">
                        {order.supplier_name || "—"}
                      </td>
                      <td className="px-5 py-3.5 text-text-secondary text-xs tabular-nums">
                        <div>{order.order_date}</div>
                        {order.expected_delivery_date && (
                          <div className="text-[10.5px] text-text-muted">
                            ETA {order.expected_delivery_date}
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <StatusBadge status={order.status} />
                          {order.promoted_to_po_number && (
                            <button
                              type="button"
                              onClick={() =>
                                jumpToStageDoc(
                                  order.promoted_to_status || (order.status === "RFQ" ? "ORDERED" : "RECEIVED"),
                                  order.promoted_to_po_number!,
                                  order.promoted_to_order_id || undefined
                                )
                              }
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-mono font-medium bg-ai-50 text-ai-700 border border-ai-200 hover:bg-ai-100 transition-colors"
                              title={`Promoted to ${order.promoted_to_po_number}`}
                            >
                              <ArrowRight className="w-2.5 h-2.5" />
                              {order.promoted_to_po_number}
                            </button>
                          )}
                          {order.promoted_to_bill_number && (
                            <Link
                              href={`/purchases/bills?search=${encodeURIComponent(order.promoted_to_bill_number)}`}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-mono font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors"
                              title={`Billed as ${order.promoted_to_bill_number}`}
                            >
                              <ArrowRight className="w-2.5 h-2.5" />
                              {order.promoted_to_bill_number}
                            </Link>
                          )}
                        </div>
                        {upstreamNodes.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1 mt-1 text-[10.5px] text-text-muted">
                            <span>Origin:</span>
                            {[...upstreamNodes].reverse().map((node, idx) => (
                              <span key={node.id} className="inline-flex items-center gap-1">
                                {idx > 0 && <span>←</span>}
                                <button
                                  type="button"
                                  onClick={() => jumpToStageDoc(node.stage, node.doc_number, node.id)}
                                  className="font-mono text-ai-600 hover:underline"
                                  title={`Open originating ${STAGE_LABELS[node.stage] || node.stage} ${node.doc_number}`}
                                >
                                  {node.doc_number}
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-right font-medium text-text-primary tabular-nums">
                        {formatCurrency(order.total)}
                      </td>
                      <td className="px-5 py-3.5 text-center">
                        <div className="inline-flex items-center gap-1.5">
                          {order.status === "RFQ" && !order.is_promoted && (
                            <button
                              disabled={rowBusy === order.id}
                              onClick={() => handleStatusTransition(order, "ORDERED")}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 text-xs font-medium transition-colors"
                              title="Preserve RFQ and issue Purchase Order (PO-#)"
                            >
                              <Truck className="w-3 h-3" /> Issue PO
                            </button>
                          )}
                          {order.status === "ORDERED" && !order.is_promoted && (
                            <button
                              disabled={rowBusy === order.id}
                              onClick={() => handleStatusTransition(order, "RECEIVED")}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 hover:bg-emerald-100 text-xs font-medium transition-colors"
                              title="Preserve PO and issue Goods Received Note (GRN-#)"
                            >
                              <CheckCircle2 className="w-3 h-3" /> Receive (GRN)
                            </button>
                          )}
                          {order.status === "RECEIVED" && !order.is_promoted && (
                            <button
                              disabled={rowBusy === order.id}
                              onClick={() => handleStatusTransition(order, "BILLED")}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
                              title="Preserve GRN and convert to Purchase Bill (PUR-#)"
                            >
                              <FileText className="w-3 h-3" /> Convert to Bill
                            </button>
                          )}
                          {order.is_promoted && order.promoted_to_bill_number && (
                            <Link
                              href={`/purchases/bills?search=${encodeURIComponent(order.promoted_to_bill_number)}`}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-bg-muted text-text-secondary hover:text-ai-600 text-xs font-medium transition-colors"
                            >
                              <ExternalLink className="w-3 h-3" /> Open Bill
                            </Link>
                          )}
                          {order.is_promoted && order.promoted_to_po_number && (
                            <button
                              type="button"
                              onClick={() =>
                                jumpToStageDoc(
                                  order.promoted_to_status || (order.status === "RFQ" ? "ORDERED" : "RECEIVED"),
                                  order.promoted_to_po_number!,
                                  order.promoted_to_order_id || undefined
                                )
                              }
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-bg-muted text-text-secondary hover:text-ai-600 text-xs font-medium transition-colors"
                            >
                              <ArrowRight className="w-3 h-3" /> View {order.promoted_to_po_number}
                            </button>
                          )}
                          {order.record_type === "BILL" && (
                            <Link
                              href={`/purchases/bills/${order.id}`}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
                            >
                              <ExternalLink className="w-3 h-3" /> View Bill
                            </Link>
                          )}
                          {!order.is_promoted &&
                            order.status !== "CANCELLED" &&
                            order.status !== "BILLED" && (
                              <button
                                disabled={rowBusy === order.id}
                                onClick={() => handleStatusTransition(order, "CANCELLED")}
                                className="p-1 rounded-lg text-text-muted hover:text-error-600 hover:bg-error-50 text-xs transition-colors"
                                title="Cancel stage document"
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Order Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="Create Purchase Order / RFQ"
      >
        <form onSubmit={handleCreateOrder} className="space-y-4">
          {formError && (
            <div className="p-3 rounded-xl bg-error-50 border border-error-200 text-xs text-error-700 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" /> {formError}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1">
                Initial Type / Status
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setOrderStatus("RFQ")}
                  className={`flex-1 py-1.5 px-3 rounded-xl text-xs font-medium border ${
                    orderStatus === "RFQ"
                      ? "bg-blue-50 border-blue-300 text-blue-700"
                      : "bg-bg-primary border-border-default text-text-secondary"
                  }`}
                >
                  RFQ / Quotation
                </button>
                <button
                  type="button"
                  onClick={() => setOrderStatus("ORDERED")}
                  className={`flex-1 py-1.5 px-3 rounded-xl text-xs font-medium border ${
                    orderStatus === "ORDERED"
                      ? "bg-purple-50 border-purple-300 text-purple-700"
                      : "bg-bg-primary border-border-default text-text-secondary"
                  }`}
                >
                  Purchase Order (PO)
                </button>
              </div>
            </div>

            <div>
              <label htmlFor="po-supplier" className="block text-xs font-medium text-text-secondary mb-1">
                Supplier
              </label>
              <PartyCombobox
                kind="supplier"
                organizationId={org?.organization_id ?? ""}
                baseCurrency={org?.base_currency_code}
                value={supplierId}
                onChange={(id) => setSupplierId(id)}
                inputId="po-supplier"
                label="Supplier"
                placeholder="Select supplier..."
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="po-order-date" className="block text-xs font-medium text-text-secondary mb-1">Order Date</label>
              <input
                id="po-order-date"
                name="order_date"
                type="date"
                value={orderDate}
                onChange={(e) => setOrderDate(e.target.value)}
                className={inputCls}
                required
              />
            </div>
            <div>
              <label htmlFor="po-expected-date" className="block text-xs font-medium text-text-secondary mb-1">Expected Delivery</label>
              <input
                id="po-expected-date"
                name="expected_delivery_date"
                type="date"
                value={expectedDate}
                onChange={(e) => setExpectedDate(e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          {/* Line Items */}
          <div className="space-y-2 pt-2 border-t border-border-subtle">
            <div className="flex justify-between items-center">
              <span className="text-xs font-medium text-text-secondary uppercase tracking-wider">
                Line Items
              </span>
              <button
                type="button"
                onClick={handleAddLine}
                className="text-xs text-ai-600 font-medium hover:underline inline-flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" /> Add Line
              </button>
            </div>

            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              {lines.map((line, idx) => (
                <div key={idx} className="p-3 bg-bg-muted/40 rounded-xl space-y-2 border border-border-subtle">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div>
                      <select
                        id={`po-line-product-${idx}`}
                        name={`po-line-product-${idx}`}
                        aria-label={`Line ${idx + 1} product`}
                        value={line.product_id}
                        onChange={(e) => handleProductSelect(idx, e.target.value)}
                        className={inputCls}
                      >
                        <option value="">-- Custom / Catalog Item --</option>
                        {products.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.product_code} — {p.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <input
                        id={`po-line-desc-${idx}`}
                        name={`po-line-desc-${idx}`}
                        type="text"
                        aria-label={`Line ${idx + 1} description`}
                        placeholder="Description"
                        value={line.description}
                        onChange={(e) => {
                          const updated = [...lines];
                          updated[idx].description = e.target.value;
                          setLines(updated);
                        }}
                        className={inputCls}
                        required
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 items-center">
                    <div>
                      <label htmlFor={`po-line-qty-${idx}`} className="text-[10px] text-text-muted">Qty</label>
                      <input
                        id={`po-line-qty-${idx}`}
                        name={`po-line-qty-${idx}`}
                        type="number"
                        step="0.01"
                        min="0.01"
                        placeholder="Qty"
                        value={line.quantity}
                        onChange={(e) => {
                          const updated = [...lines];
                          updated[idx].quantity = e.target.value;
                          setLines(updated);
                        }}
                        className={inputCls}
                        required
                      />
                    </div>
                    <div>
                      <label htmlFor={`po-line-price-${idx}`} className="text-[10px] text-text-muted">Unit Price</label>
                      <input
                        id={`po-line-price-${idx}`}
                        name={`po-line-price-${idx}`}
                        type="number"
                        step="0.01"
                        min="0"
                        placeholder="Price"
                        value={line.unit_price}
                        onChange={(e) => {
                          const updated = [...lines];
                          updated[idx].unit_price = e.target.value;
                          setLines(updated);
                        }}
                        className={inputCls}
                        required
                      />
                    </div>
                    <div>
                      <label htmlFor={`po-line-tax-${idx}`} className="text-[10px] text-text-muted">Tax</label>
                      <input
                        id={`po-line-tax-${idx}`}
                        name={`po-line-tax-${idx}`}
                        type="number"
                        step="0.01"
                        placeholder="Tax"
                        value={line.tax_amount}
                        onChange={(e) => {
                          const updated = [...lines];
                          updated[idx].tax_amount = e.target.value;
                          setLines(updated);
                        }}
                        className={inputCls}
                      />
                    </div>
                    <div className="flex items-center justify-between pt-3">
                      <span className="text-xs font-semibold tabular-nums text-text-primary">
                        {formatCurrency(
                          (parseFloat(line.quantity) || 0) * (parseFloat(line.unit_price) || 0) +
                            (parseFloat(line.tax_amount) || 0)
                        )}
                      </span>
                      {lines.length > 1 && (
                        <button
                          type="button"
                          onClick={() => handleRemoveLine(idx)}
                          className="text-text-muted hover:text-error-600 p-1"
                          aria-label={`Remove line ${idx + 1}`}
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Total display */}
            <div className="flex justify-between items-center py-2 px-3 bg-bg-muted rounded-xl">
              <span className="text-xs font-medium text-text-muted">Estimated Total</span>
              <span className="text-sm font-bold text-text-primary tabular-nums">
                {formatCurrency(formTotal)}
              </span>
            </div>
          </div>

          <div>
            <label htmlFor="po-notes" className="block text-xs font-medium text-text-secondary mb-1">Notes / Terms</label>
            <textarea
              id="po-notes"
              name="notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Payment terms, delivery instructions..."
              className={inputCls}
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl text-xs font-medium text-text-secondary hover:bg-bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 rounded-xl bg-ai-500 text-white text-xs font-medium hover:bg-ai-600 transition-colors shadow-sm disabled:opacity-50"
            >
              {saving ? "Creating..." : orderStatus === "RFQ" ? "Create RFQ" : "Issue Purchase Order"}
            </button>
          </div>
        </form>
      </Modal>

      {/* Order / Stage Document Details & Lineage Modal */}
      {viewingOrder && (
        <Modal
          open={!!viewingOrder}
          onClose={() => setViewingOrder(null)}
          title={`${STAGE_LABELS[viewingOrder.status] || "Document"} ${viewingOrder.po_number}`}
          wide
        >
          <div className="space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-border-subtle">
              <div>
                <p className="text-xs text-text-muted">Supplier</p>
                <p className="text-sm font-medium text-text-primary">{viewingOrder.supplier_name || "—"}</p>
              </div>
              <div className="text-right">
                <StatusBadge status={viewingOrder.status} />
                <p className="text-xs text-text-muted mt-1">{viewingOrder.order_date}</p>
              </div>
            </div>

            {/* Interactive 4-Stage Procurement Chain */}
            {viewingOrder.chain && viewingOrder.chain.length > 0 && (
              <div className="rounded-xl border border-border-subtle bg-bg-muted/30 p-3">
                <p className="text-[11px] font-medium text-text-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <GitBranch className="w-3.5 h-3.5 text-ai-600" />
                  Document Traceability Chain
                </p>
                <div className="flex flex-wrap items-center gap-1.5">
                  {viewingOrder.chain.map((node, idx) => (
                    <div key={node.id} className="inline-flex items-center gap-1.5">
                      {idx > 0 && <ArrowRight className="w-3.5 h-3.5 text-text-muted" />}
                      {node.record_type === "BILL" ? (
                        <Link
                          href={`/purchases/bills/${node.id}`}
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-medium transition-colors ${
                            node.is_current
                              ? "bg-emerald-50 border-emerald-300 text-emerald-800"
                              : "bg-bg-surface border-border-default text-ai-600 hover:border-ai-300"
                          }`}
                        >
                          <span className="text-[10px] uppercase text-text-muted">Bill</span>
                          <span className="font-mono">{node.doc_number}</span>
                          <ExternalLink className="w-3 h-3" />
                        </Link>
                      ) : (
                        <button
                          type="button"
                          onClick={() => jumpToStageDoc(node.stage, node.doc_number, node.id)}
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-medium transition-colors ${
                            node.is_current
                              ? "bg-ai-50 border-ai-300 text-ai-800"
                              : "bg-bg-surface border-border-default text-text-primary hover:border-ai-300"
                          }`}
                        >
                          <span className="text-[10px] uppercase text-text-muted">
                            {STAGE_LABELS[node.stage] || node.stage}
                          </span>
                          <span className="font-mono">{node.doc_number}</span>
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Line Items Table */}
            <div>
              <p className="text-xs font-medium text-text-muted uppercase mb-2">Line Items</p>
              {detailLoading && !(viewingOrder.items && viewingOrder.items.length) ? (
                <p className="text-xs text-text-muted py-2">Loading line items...</p>
              ) : viewingOrder.items && viewingOrder.items.length > 0 ? (
                <div className="border border-border-subtle rounded-xl overflow-hidden">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-bg-muted/50 text-text-muted">
                      <tr>
                        <th className="px-3 py-2 font-medium">Description</th>
                        <th className="px-3 py-2 text-right font-medium">Qty</th>
                        <th className="px-3 py-2 text-right font-medium">Unit Price</th>
                        <th className="px-3 py-2 text-right font-medium">Tax</th>
                        <th className="px-3 py-2 text-right font-medium">Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                      {viewingOrder.items.map((it, idx) => (
                        <tr key={it.id || idx}>
                          <td className="px-3 py-2 text-text-primary">{it.description}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
                            {it.quantity}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
                            {formatCurrency(it.unit_price)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
                            {formatCurrency(it.tax_amount || 0)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums font-medium text-text-primary">
                            {formatCurrency(it.line_total ?? it.quantity * it.unit_price)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-text-muted">No line items recorded.</p>
              )}
            </div>

            <div>
              <p className="text-xs font-medium text-text-muted uppercase mb-2">Summary</p>
              <div className="bg-bg-muted/50 rounded-xl p-3 space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-text-muted">Subtotal</span>
                  <span className="font-medium tabular-nums">{formatCurrency(viewingOrder.subtotal)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-text-muted">Tax</span>
                  <span className="font-medium tabular-nums">{formatCurrency(viewingOrder.tax_total)}</span>
                </div>
                <div className="flex justify-between text-sm font-bold border-t border-border-subtle pt-2">
                  <span>Total</span>
                  <span className="tabular-nums">{formatCurrency(viewingOrder.total)}</span>
                </div>
              </div>
            </div>

            {viewingOrder.notes && (
              <div>
                <p className="text-xs text-text-muted">Notes</p>
                <p className="text-xs text-text-secondary bg-bg-muted p-2 rounded-lg mt-1">{viewingOrder.notes}</p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              {viewingOrder.record_type === "BILL" && (
                <Link
                  href={`/purchases/bills/${viewingOrder.id}`}
                  className="px-4 py-1.5 rounded-xl bg-ai-500 text-white text-xs font-medium hover:bg-ai-600 inline-flex items-center gap-1"
                >
                  <ExternalLink className="w-3.5 h-3.5" /> Print / Open Purchase Bill
                </Link>
              )}
              <button
                type="button"
                onClick={() => setViewingOrder(null)}
                className="px-4 py-1.5 rounded-xl bg-bg-muted text-xs font-medium text-text-secondary hover:text-text-primary"
              >
                Close
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
