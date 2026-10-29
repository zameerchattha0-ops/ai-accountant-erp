"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Search, Truck, FileText, CheckCircle2, AlertCircle, X } from "lucide-react";
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
  purchaseOrderStatusUpdate,
  catalogueList,
  type PurchaseOrder,
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

const today = () => new Date().toISOString().slice(0, 10);

export default function PurchaseOrdersPage() {
  const { org } = useOrg();
  const [orders, setOrders] = useState<PurchaseOrder[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [rowBusy, setRowBusy] = useState<string | null>(null);

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

  // Detailed View Modal
  const [viewingOrder, setViewingOrder] = useState<PurchaseOrder | null>(null);

  const loadData = useCallback(async () => {
    if (!org) return;
    setLoading(true);
    setError(null);
    try {
      const res = await purchaseOrderList(statusFilter, search);
      setOrders(res.orders || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load purchase orders.";
      setError(msg);
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, [org, statusFilter, search]);

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

  const filteredOrders = useMemo(() => {
    if (!orders) return [];
    if (!search.trim()) return orders;
    const q = search.toLowerCase();
    return orders.filter(
      (o) =>
        o.po_number.toLowerCase().includes(q) ||
        (o.supplier_name && o.supplier_name.toLowerCase().includes(q))
    );
  }, [orders, search]);

  // Metric Aggregations
  const metrics = useMemo(() => {
    if (!orders) return { total: 0, rfq: 0, ordered: 0, received: 0, value: 0 };
    return {
      total: orders.length,
      rfq: orders.filter((o) => o.status === "RFQ").length,
      ordered: orders.filter((o) => o.status === "ORDERED").length,
      received: orders.filter((o) => o.status === "RECEIVED").length,
      value: orders.reduce((sum, o) => sum + (o.total || 0), 0),
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
      // Reset form
      setSupplierId("");
      setOrderStatus("RFQ");
      setLines([{ product_id: "", description: "", quantity: "1", unit_price: "", tax_amount: "0" }]);
      setNotes("");
      loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create order.";
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleStatusTransition = async (order: PurchaseOrder, nextStatus: string) => {
    setRowBusy(order.id);
    try {
      await purchaseOrderStatusUpdate(order.id, nextStatus, true, nextStatus === "BILLED");
      loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Status transition failed";
      alert(msg);
    } finally {
      setRowBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Purchase Orders & RFQs"
        subtitle="Dedicated procurement pipeline: RFQ / Quotation → Confirmed PO → Goods Received Note (GRN) → Purchase Bill."
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
        <div className="p-3.5 rounded-xl bg-danger-50 border border-danger-200 text-xs text-danger-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Metrics Banner */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="bg-bg-surface border border-border-default rounded-2xl p-4">
          <p className="text-xs text-text-muted">Total Orders / RFQs</p>
          <p className="text-2xl font-bold text-text-primary mt-1">{metrics.total}</p>
        </div>
        <div className="bg-bg-surface border border-blue-200/50 bg-blue-50/20 rounded-2xl p-4">
          <p className="text-xs text-blue-700 font-medium">Requisitions / RFQs</p>
          <p className="text-2xl font-bold text-blue-800 mt-1">{metrics.rfq}</p>
        </div>
        <div className="bg-bg-surface border border-purple-200/50 bg-purple-50/20 rounded-2xl p-4">
          <p className="text-xs text-purple-700 font-medium">Inbound In-Flight (PO)</p>
          <p className="text-2xl font-bold text-purple-800 mt-1">{metrics.ordered}</p>
        </div>
        <div className="bg-bg-surface border border-emerald-200/50 bg-emerald-50/20 rounded-2xl p-4">
          <p className="text-xs text-emerald-700 font-medium">Received (GRN)</p>
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
          {["ALL", "RFQ", "ORDERED", "RECEIVED", "BILLED", "CANCELLED"].map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                statusFilter === st
                  ? "bg-ai-500 text-white"
                  : "text-text-muted hover:text-text-primary hover:bg-bg-muted"
              }`}
            >
              {st === "ALL" ? "All Orders" : st}
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search PO # or supplier..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-bg-surface border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100"
          />
        </div>
      </div>

      {/* Orders Table */}
      <div className="bg-bg-surface border border-border-default rounded-2xl overflow-hidden shadow-sm">
        {loading ? (
          <TableSkeleton rows={5} cols={6} />
        ) : filteredOrders.length === 0 ? (
          <EmptyState
            title="No purchase orders found"
            hint="Create your first RFQ or Purchase Order to begin tracking inbound inventory."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-border-subtle bg-bg-muted/50 text-xs font-medium text-text-muted uppercase tracking-wider">
                  <th className="px-5 py-3.5">Order / RFQ #</th>
                  <th className="px-5 py-3.5">Supplier</th>
                  <th className="px-5 py-3.5">Order Date</th>
                  <th className="px-5 py-3.5">Expected Delivery</th>
                  <th className="px-5 py-3.5">Status</th>
                  <th className="px-5 py-3.5 text-right">Total</th>
                  <th className="px-5 py-3.5 text-center">Lifecycle Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {filteredOrders.map((order) => (
                  <tr key={order.id} className="hover:bg-bg-muted/30 transition-colors">
                    <td className="px-5 py-3.5 font-medium text-text-primary">
                      <button
                        onClick={() => setViewingOrder(order)}
                        className="text-ai-600 hover:underline font-mono text-xs"
                      >
                        {order.po_number}
                      </button>
                    </td>
                    <td className="px-5 py-3.5 text-text-primary">
                      {order.supplier_name || "—"}
                    </td>
                    <td className="px-5 py-3.5 text-text-secondary text-xs">{order.order_date}</td>
                    <td className="px-5 py-3.5 text-text-secondary text-xs">
                      {order.expected_delivery_date || "—"}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={order.status} />
                    </td>
                    <td className="px-5 py-3.5 text-right font-medium text-text-primary tabular-nums">
                      {formatCurrency(order.total)}
                    </td>
                    <td className="px-5 py-3.5 text-center">
                      <div className="inline-flex items-center gap-1.5">
                        {order.status === "RFQ" && (
                          <button
                            disabled={rowBusy === order.id}
                            onClick={() => handleStatusTransition(order, "ORDERED")}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 text-xs font-medium transition-colors"
                            title="Vendor accepts quotation -> Issue Purchase Order (In Transit)"
                          >
                            <Truck className="w-3 h-3" /> Issue PO
                          </button>
                        )}
                        {order.status === "ORDERED" && (
                          <button
                            disabled={rowBusy === order.id}
                            onClick={() => handleStatusTransition(order, "RECEIVED")}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 hover:bg-emerald-100 text-xs font-medium transition-colors"
                            title="Goods arrived -> Record Goods Received Note (GRN) to Warehouse Stock"
                          >
                            <CheckCircle2 className="w-3 h-3" /> Receive (GRN)
                          </button>
                        )}
                        {order.status === "RECEIVED" && (
                          <button
                            disabled={rowBusy === order.id}
                            onClick={() => handleStatusTransition(order, "BILLED")}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
                            title="Convert received goods to Purchase Bill"
                          >
                            <FileText className="w-3 h-3" /> Convert to Bill
                          </button>
                        )}
                        {order.status !== "CANCELLED" && order.status !== "BILLED" && (
                          <button
                            disabled={rowBusy === order.id}
                            onClick={() => handleStatusTransition(order, "CANCELLED")}
                            className="p-1 rounded-lg text-text-muted hover:text-error-600 hover:bg-error-50 text-xs transition-colors"
                            title="Cancel order"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
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
              <label className="block text-xs font-medium text-text-secondary mb-1">
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
              <label className="block text-xs font-medium text-text-secondary mb-1">Order Date</label>
              <input
                type="date"
                value={orderDate}
                onChange={(e) => setOrderDate(e.target.value)}
                className={inputCls}
                required
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1">Expected Delivery</label>
              <input
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
                        type="text"
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
                      <label className="text-[10px] text-text-muted">Qty</label>
                      <input
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
                      <label className="text-[10px] text-text-muted">Unit Price</label>
                      <input
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
                      <label className="text-[10px] text-text-muted">Tax</label>
                      <input
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
            <label className="block text-xs font-medium text-text-secondary mb-1">Notes / Terms</label>
            <textarea
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

      {/* Order Details View Modal */}
      {viewingOrder && (
        <Modal
          open={!!viewingOrder}
          onClose={() => setViewingOrder(null)}
          title={`Order ${viewingOrder.po_number}`}
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

            <div>
              <p className="text-xs font-medium text-text-muted uppercase mb-2">Order Summary</p>
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

            <div className="flex justify-end pt-2">
              <button
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
