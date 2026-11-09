"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Download,
  FileSpreadsheet,
  ShieldCheck,
  AlertTriangle,
  Building2,
  Calendar,
  Layers,
  CheckCircle2,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import PageHeader from "@/components/shared/PageHeader";
import TaxProfileBadge from "@/components/shared/TaxProfileBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";

type Tab = "annexure-c" | "annexure-a" | "provincial";

interface CustomerRelation {
  id: string;
  name: string;
  customer_code: string | null;
  tax_number: string | null;
  strn: string | null;
  sales_tax_status: string | null;
}

interface SupplierRelation {
  id: string;
  name: string;
  supplier_code: string | null;
  tax_number: string | null;
  strn: string | null;
  sales_tax_status: string | null;
}

interface SalesInvoiceRow {
  id: string;
  invoice_number: string;
  invoice_date: string;
  subtotal: number;
  tax_total: number;
  total: number;
  status: string;
  customer?: CustomerRelation | null;
}

interface PurchaseBillRow {
  id: string;
  bill_number: string;
  bill_date: string;
  supplier_invoice_ref: string | null;
  subtotal: number;
  tax_total: number;
  total: number;
  status: string;
  supplier?: SupplierRelation | null;
}

const inputCls =
  "px-3 py-1.5 rounded-xl bg-bg-surface border border-border-default text-xs text-text-primary focus:outline-none focus:ring-2 focus:ring-ai-100 transition-colors";

function getMonthDateRange(year: number, month: number) {
  const start = new Date(Date.UTC(year, month, 1));
  const end = new Date(Date.UTC(year, month + 1, 0));
  return {
    startStr: start.toISOString().slice(0, 10),
    endStr: end.toISOString().slice(0, 10),
  };
}

export default function TaxAnnexuresPage() {
  const { org } = useOrg();
  const [tab, setTab] = useState<Tab>("annexure-c");

  const today = useMemo(() => new Date(), []);
  const [selectedYear, setSelectedYear] = useState<number>(today.getFullYear());
  const [selectedMonth, setSelectedMonth] = useState<number>(today.getMonth());

  const [salesRows, setSalesRows] = useState<SalesInvoiceRow[] | null>(null);
  const [purchaseRows, setPurchaseRows] = useState<PurchaseBillRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { startStr, endStr } = useMemo(
    () => getMonthDateRange(selectedYear, selectedMonth),
    [selectedYear, selectedMonth]
  );

  const monthLabel = useMemo(() => {
    return new Date(Date.UTC(selectedYear, selectedMonth, 1)).toLocaleString("default", {
      month: "long",
      year: "numeric",
    });
  }, [selectedYear, selectedMonth]);

  const loadData = useCallback(async () => {
    if (!org) return;
    setLoading(true);
    setError(null);
    try {
      const supabase = createClient();

      // 1. Fetch Sales Invoices for Annexure-C
      const { data: sData, error: sErr } = await supabase
        .from("invoices")
        .select(
          `id, invoice_number, invoice_date, subtotal, tax_total, total, status,
           customer:customers(id, name, customer_code, tax_number, strn, sales_tax_status)`
        )
        .eq("organization_id", org.organization_id)
        .gte("invoice_date", startStr)
        .lte("invoice_date", endStr)
        .not("status", "in", '("VOIDED","DRAFT")')
        .order("invoice_date", { ascending: true });

      if (sErr) throw sErr;
      setSalesRows((sData as unknown as SalesInvoiceRow[]) ?? []);

      // 2. Fetch Purchase Bills for Annexure-A
      const { data: pData, error: pErr } = await supabase
        .from("purchase_bills")
        .select(
          `id, bill_number, bill_date, supplier_invoice_ref, subtotal, tax_total, total, status,
           supplier:suppliers(id, name, supplier_code, tax_number, strn, sales_tax_status)`
        )
        .eq("organization_id", org.organization_id)
        .gte("bill_date", startStr)
        .lte("bill_date", endStr)
        .not("status", "in", '("VOIDED","DRAFT")')
        .order("bill_date", { ascending: true });

      if (pErr) throw pErr;
      setPurchaseRows((pData as unknown as PurchaseBillRow[]) ?? []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load tax data");
    } finally {
      setLoading(false);
    }
  }, [org, startStr, endStr]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Annexure-C calculations
  const annexureCSummary = useMemo(() => {
    let totalSales = 0;
    let standardGst = 0;
    let furtherTax = 0;
    let grandTax = 0;

    (salesRows ?? []).forEach((row) => {
      const sub = Number(row.subtotal || 0);
      const tax = Number(row.tax_total || 0);
      totalSales += sub;

      const cStatus = (row.customer?.sales_tax_status || "UNREGISTERED").toUpperCase();
      const isActive = cStatus.includes("ACTIVE") || cStatus.includes("ATL");

      if (isActive) {
        standardGst += tax;
      } else {
        // Section 3(1A) 4% Further Tax split estimation
        const fTaxEst = Math.round(sub * 0.04 * 100) / 100;
        furtherTax += fTaxEst;
        standardGst += Math.max(0, tax - fTaxEst);
      }
      grandTax += tax;
    });

    return { totalSales, standardGst, furtherTax, grandTax };
  }, [salesRows]);

  // Annexure-A calculations
  const annexureASummary = useMemo(() => {
    let totalPurchases = 0;
    let totalInputTaxBilled = 0;
    let claimableInputTax = 0;
    let blockedInputTax = 0;

    (purchaseRows ?? []).forEach((row) => {
      const sub = Number(row.subtotal || 0);
      const tax = Number(row.tax_total || 0);
      totalPurchases += sub;
      totalInputTaxBilled += tax;

      const sStatus = (row.supplier?.sales_tax_status || "UNREGISTERED").toUpperCase();
      const isActive = sStatus.includes("ACTIVE") || sStatus.includes("ATL");

      if (isActive) {
        claimableInputTax += tax;
      } else {
        blockedInputTax += tax;
      }
    });

    return { totalPurchases, totalInputTaxBilled, claimableInputTax, blockedInputTax };
  }, [purchaseRows]);

  // CSV Exporter for Annexure-C (FBR Iris format)
  const exportAnnexureCCsv = () => {
    if (!salesRows || salesRows.length === 0) return;
    const headers = [
      "Buyer NTN",
      "Buyer STRN",
      "Buyer Name",
      "Document Type",
      "Document Number",
      "Document Date",
      "Sales Type",
      "Rate %",
      "Value of Sales",
      "Sales Tax",
      "Further Tax",
      "Total Sales Tax",
    ];

    const lines = salesRows.map((r) => {
      const ntn = r.customer?.tax_number || "";
      const strn = r.customer?.strn || "";
      const name = (r.customer?.name || "Customer").replace(/"/g, '""');
      const docType = "Tax Invoice";
      const docNum = r.invoice_number;
      const docDate = r.invoice_date;
      const salesType = "Domestic Standard Rate Supply";
      const rate = 18;
      const sub = Number(r.subtotal || 0);
      const tax = Number(r.tax_total || 0);

      const cStatus = (r.customer?.sales_tax_status || "UNREGISTERED").toUpperCase();
      const isActive = cStatus.includes("ACTIVE") || cStatus.includes("ATL");
      const fTax = isActive ? 0 : Math.round(sub * 0.04 * 100) / 100;
      const sTax = Math.max(0, tax - fTax);

      return [
        `"${ntn}"`,
        `"${strn}"`,
        `"${name}"`,
        `"${docType}"`,
        `"${docNum}"`,
        `"${docDate}"`,
        `"${salesType}"`,
        rate,
        sub.toFixed(2),
        sTax.toFixed(2),
        fTax.toFixed(2),
        tax.toFixed(2),
      ].join(",");
    });

    const csvContent = [headers.join(","), ...lines].join("\r\n");
    downloadBlob(csvContent, `FBR_Iris_Annexure_C_${startStr}_to_${endStr}.csv`, "text/csv;charset=utf-8;");
  };

  // CSV Exporter for Annexure-A (FBR Iris format)
  const exportAnnexureACsv = () => {
    if (!purchaseRows || purchaseRows.length === 0) return;
    const headers = [
      "Supplier NTN",
      "Supplier STRN",
      "Supplier Name",
      "Document Type",
      "Document Number",
      "Document Date",
      "Purchase Type",
      "Rate %",
      "Value of Purchases",
      "Sales Tax Billed",
      "Input Tax Claimable (A/C 1060)",
      "Ineligible / Capitalized (P-03/P-05)",
      "FBR Rule Code",
    ];

    const lines = purchaseRows.map((r) => {
      const ntn = r.supplier?.tax_number || "";
      const strn = r.supplier?.strn || "";
      const name = (r.supplier?.name || "Supplier").replace(/"/g, '""');
      const docType = "Purchase Invoice";
      const docNum = r.bill_number;
      const docDate = r.bill_date;
      const pType = "Standard Rate Domestic Purchase";
      const rate = 18;
      const sub = Number(r.subtotal || 0);
      const tax = Number(r.tax_total || 0);

      const sStatus = (r.supplier?.sales_tax_status || "UNREGISTERED").toUpperCase();
      const isActive = sStatus.includes("ACTIVE") || sStatus.includes("ATL");
      const claimable = isActive ? tax : 0;
      const ineligible = isActive ? 0 : tax;
      const rule = isActive ? "P-01 (Active Supplier)" : "P-03 / P-05 (Unregistered / Blocked Input)";

      return [
        `"${ntn}"`,
        `"${strn}"`,
        `"${name}"`,
        `"${docType}"`,
        `"${docNum}"`,
        `"${docDate}"`,
        `"${pType}"`,
        rate,
        sub.toFixed(2),
        tax.toFixed(2),
        claimable.toFixed(2),
        ineligible.toFixed(2),
        `"${rule}"`,
      ].join(",");
    });

    const csvContent = [headers.join(","), ...lines].join("\r\n");
    downloadBlob(csvContent, `FBR_Iris_Annexure_A_${startStr}_to_${endStr}.csv`, "text/csv;charset=utf-8;");
  };

  function downloadBlob(content: string, filename: string, mime: string) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  const currency = org?.base_currency_code || "PKR";

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <PageHeader
        title="FBR Tax Annexures & E-Filing"
        subtitle={`Sales Tax Act 1990 & Provincial Returns for ${org?.name ?? "your company"}`}
        logoUrl={org?.logo_url}
        actions={
          <div className="flex items-center gap-2">
            {tab === "annexure-c" && (
              <button
                onClick={exportAnnexureCCsv}
                disabled={!salesRows || salesRows.length === 0}
                className="flex items-center gap-1.5 px-3.5 py-1.5 btn-3d rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-xs font-medium disabled:opacity-40 transition-colors shadow-2xs"
              >
                <Download className="w-3.5 h-3.5" />
                Export Annexure-C (CSV)
              </button>
            )}
            {tab === "annexure-a" && (
              <button
                onClick={exportAnnexureACsv}
                disabled={!purchaseRows || purchaseRows.length === 0}
                className="flex items-center gap-1.5 px-3.5 py-1.5 btn-3d rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-xs font-medium disabled:opacity-40 transition-colors shadow-2xs"
              >
                <Download className="w-3.5 h-3.5" />
                Export Annexure-A (CSV)
              </button>
            )}
          </div>
        }
      />

      {/* Period Filter & Navigation Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl bg-bg-surface border border-border-subtle">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-ai-50 text-ai-600">
            <Calendar className="w-4 h-4" />
          </div>
          <div>
            <span className="text-xs font-semibold text-text-primary">Tax Period: {monthLabel}</span>
            <p className="text-[11px] text-text-muted">
              {startStr} through {endStr}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <select
            className={inputCls}
            value={selectedMonth}
            onChange={(e) => setSelectedMonth(Number(e.target.value))}
          >
            {[
              "January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December",
            ].map((m, idx) => (
              <option key={m} value={idx}>{m}</option>
            ))}
          </select>

          <select
            className={inputCls}
            value={selectedYear}
            onChange={(e) => setSelectedYear(Number(e.target.value))}
          >
            {[2024, 2025, 2026, 2027].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Tab Switcher */}
      <div className="flex gap-2 border-b border-border-subtle pb-2">
        <button
          onClick={() => setTab("annexure-c")}
          className={cn(
            "flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all",
            tab === "annexure-c"
              ? "bg-ai-500 text-white shadow-2xs"
              : "text-text-secondary hover:text-text-primary hover:bg-bg-muted"
          )}
        >
          <FileSpreadsheet className="w-4 h-4" />
          Annexure-C (Domestic Sales)
          {salesRows && (
            <span className={cn(
              "px-1.5 py-0.5 rounded-full text-[10px]",
              tab === "annexure-c" ? "bg-white/20 text-white" : "bg-bg-muted text-text-secondary"
            )}>
              {salesRows.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setTab("annexure-a")}
          className={cn(
            "flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all",
            tab === "annexure-a"
              ? "bg-ai-500 text-white shadow-2xs"
              : "text-text-secondary hover:text-text-primary hover:bg-bg-muted"
          )}
        >
          <Building2 className="w-4 h-4" />
          Annexure-A (Domestic Purchases)
          {purchaseRows && (
            <span className={cn(
              "px-1.5 py-0.5 rounded-full text-[10px]",
              tab === "annexure-a" ? "bg-white/20 text-white" : "bg-bg-muted text-text-secondary"
            )}>
              {purchaseRows.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setTab("provincial")}
          className={cn(
            "flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all",
            tab === "provincial"
              ? "bg-ai-500 text-white shadow-2xs"
              : "text-text-secondary hover:text-text-primary hover:bg-bg-muted"
          )}
        >
          <Layers className="w-4 h-4" />
          Provincial Services (PRA / SRB / KPRA)
        </button>
      </div>

      {/* TAB CONTENT: ANNEXURE-C */}
      {tab === "annexure-c" && (
        <div className="space-y-4">
          {/* Statutory Metric Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Value of Supplies</span>
              <p className="text-xl font-bold text-text-primary tabular-nums mt-1">
                {formatCurrency(annexureCSummary.totalSales, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">Gross sales before taxes</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Standard GST (18%)</span>
              <p className="text-xl font-bold text-emerald-600 tabular-nums mt-1">
                {formatCurrency(annexureCSummary.standardGst, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">Output tax on registered & active</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Further Tax (4%)</span>
              <p className="text-xl font-bold text-amber-600 tabular-nums mt-1">
                {formatCurrency(annexureCSummary.furtherTax, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">Section 3(1A) unregistered levy</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Total Output Tax</span>
              <p className="text-xl font-bold text-ai-600 tabular-nums mt-1">
                {formatCurrency(annexureCSummary.grandTax, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">Payable to FBR Treasury</span>
            </div>
          </div>

          {/* Table */}
          {loading ? (
            <TableSkeleton cols={7} />
          ) : error ? (
            <ErrorState message={error} onRetry={loadData} />
          ) : (salesRows ?? []).length === 0 ? (
            <EmptyState
              title="No Sales Invoices for this period"
              hint="Approved sales invoices within this month will automatically appear here formatted for FBR Iris Annexure-C."
            />
          ) : (
            <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left uppercase tracking-wide text-[10px] text-text-muted border-b border-border-subtle bg-bg-muted/30">
                    <th className="px-4 py-3 font-semibold">Invoice No</th>
                    <th className="px-4 py-3 font-semibold">Date</th>
                    <th className="px-4 py-3 font-semibold">Customer / Buyer</th>
                    <th className="px-4 py-3 font-semibold">Tax Profile</th>
                    <th className="px-4 py-3 font-semibold text-right">Value of Sales</th>
                    <th className="px-4 py-3 font-semibold text-right">Standard GST (18%)</th>
                    <th className="px-4 py-3 font-semibold text-right">Further Tax (4%)</th>
                    <th className="px-4 py-3 font-semibold text-right">Total Invoice</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle/50">
                  {salesRows!.map((row) => {
                    const sub = Number(row.subtotal || 0);
                    const tax = Number(row.tax_total || 0);
                    const cStatus = (row.customer?.sales_tax_status || "UNREGISTERED").toUpperCase();
                    const isActive = cStatus.includes("ACTIVE") || cStatus.includes("ATL");
                    const fTax = isActive ? 0 : Math.round(sub * 0.04 * 100) / 100;
                    const sTax = Math.max(0, tax - fTax);

                    return (
                      <tr key={row.id} className="hover:bg-bg-muted/40 transition-colors">
                        <td className="px-4 py-3 font-mono font-medium text-text-primary">{row.invoice_number}</td>
                        <td className="px-4 py-3 text-text-secondary tabular-nums">{row.invoice_date}</td>
                        <td className="px-4 py-3 text-text-primary">
                          <div className="font-medium">{row.customer?.name ?? "Walk-in"}</div>
                          <div className="text-[10px] text-text-muted font-mono">
                            {row.customer?.strn ? `STRN: ${row.customer.strn}` : row.customer?.tax_number ? `NTN: ${row.customer.tax_number}` : "No NTN/STRN"}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <TaxProfileBadge
                            status={row.customer?.sales_tax_status}
                            strn={row.customer?.strn}
                            taxNumber={row.customer?.tax_number}
                          />
                        </td>
                        <td className="px-4 py-3 text-right text-text-primary font-mono tabular-nums">
                          {formatCurrency(sub, currency)}
                        </td>
                        <td className="px-4 py-3 text-right text-emerald-600 font-mono tabular-nums">
                          {formatCurrency(sTax, currency)}
                        </td>
                        <td className="px-4 py-3 text-right text-amber-600 font-mono tabular-nums">
                          {fTax > 0 ? formatCurrency(fTax, currency) : "—"}
                        </td>
                        <td className="px-4 py-3 text-right font-medium text-text-primary font-mono tabular-nums">
                          {formatCurrency(Number(row.total || 0), currency)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: ANNEXURE-A */}
      {tab === "annexure-a" && (
        <div className="space-y-4">
          {/* Statutory Metric Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Value of Purchases</span>
              <p className="text-xl font-bold text-text-primary tabular-nums mt-1">
                {formatCurrency(annexureASummary.totalPurchases, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">Total purchase bill subtotals</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Input Tax Billed</span>
              <p className="text-xl font-bold text-text-secondary tabular-nums mt-1">
                {formatCurrency(annexureASummary.totalInputTaxBilled, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">Gross GST on supplier invoices</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Claimable Input (A/C 1060)</span>
              <p className="text-xl font-bold text-emerald-600 tabular-nums mt-1">
                {formatCurrency(annexureASummary.claimableInputTax, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">P-01 Active ATL vendors (Asset)</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">Blocked / Capitalized</span>
              <p className="text-xl font-bold text-amber-600 tabular-nums mt-1">
                {formatCurrency(annexureASummary.blockedInputTax, currency)}
              </p>
              <span className="text-[10px] text-text-secondary">P-03/P-05 Unregistered (Ineligible)</span>
            </div>
          </div>

          {/* Table */}
          {loading ? (
            <TableSkeleton cols={7} />
          ) : error ? (
            <ErrorState message={error} onRetry={loadData} />
          ) : (purchaseRows ?? []).length === 0 ? (
            <EmptyState
              title="No Purchase Bills for this period"
              hint="Recorded purchase bills within this month will appear here with Section 73 & ATL input tax eligibility analysis."
            />
          ) : (
            <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left uppercase tracking-wide text-[10px] text-text-muted border-b border-border-subtle bg-bg-muted/30">
                    <th className="px-4 py-3 font-semibold">Bill No / Ref</th>
                    <th className="px-4 py-3 font-semibold">Date</th>
                    <th className="px-4 py-3 font-semibold">Supplier</th>
                    <th className="px-4 py-3 font-semibold">Tax Profile</th>
                    <th className="px-4 py-3 font-semibold text-right">Value of Purchases</th>
                    <th className="px-4 py-3 font-semibold text-right">GST Billed</th>
                    <th className="px-4 py-3 font-semibold text-right">Claimable Input</th>
                    <th className="px-4 py-3 font-semibold">FBR Rule</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle/50">
                  {purchaseRows!.map((row) => {
                    const sub = Number(row.subtotal || 0);
                    const tax = Number(row.tax_total || 0);
                    const sStatus = (row.supplier?.sales_tax_status || "UNREGISTERED").toUpperCase();
                    const isActive = sStatus.includes("ACTIVE") || sStatus.includes("ATL");
                    const claimable = isActive ? tax : 0;

                    return (
                      <tr key={row.id} className="hover:bg-bg-muted/40 transition-colors">
                        <td className="px-4 py-3 font-mono font-medium text-text-primary">
                          <div>{row.bill_number}</div>
                          {row.supplier_invoice_ref && (
                            <div className="text-[10px] text-text-muted">Ref: {row.supplier_invoice_ref}</div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-text-secondary tabular-nums">{row.bill_date}</td>
                        <td className="px-4 py-3 text-text-primary">
                          <div className="font-medium">{row.supplier?.name ?? "Vendor"}</div>
                          <div className="text-[10px] text-text-muted font-mono">
                            {row.supplier?.strn ? `STRN: ${row.supplier.strn}` : row.supplier?.tax_number ? `NTN: ${row.supplier.tax_number}` : "No NTN/STRN"}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <TaxProfileBadge
                            status={row.supplier?.sales_tax_status}
                            strn={row.supplier?.strn}
                            taxNumber={row.supplier?.tax_number}
                          />
                        </td>
                        <td className="px-4 py-3 text-right text-text-primary font-mono tabular-nums">
                          {formatCurrency(sub, currency)}
                        </td>
                        <td className="px-4 py-3 text-right text-text-secondary font-mono tabular-nums">
                          {formatCurrency(tax, currency)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono tabular-nums">
                          {claimable > 0 ? (
                            <span className="font-semibold text-emerald-600">
                              {formatCurrency(claimable, currency)}
                            </span>
                          ) : (
                            <span className="text-text-muted">Rs. 0 (Cost)</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {isActive ? (
                            <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium">
                              <CheckCircle2 className="w-3.5 h-3.5" /> P-01 Eligible
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[11px] text-amber-600 font-medium">
                              <AlertTriangle className="w-3.5 h-3.5" /> P-03 Unregistered
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: PROVINCIAL SERVICES */}
      {tab === "provincial" && (
        <div className="space-y-4">
          <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle flex items-start gap-3">
            <div className="p-2 rounded-xl bg-purple-50 text-purple-600 shrink-0">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <h4 className="text-xs font-semibold text-text-primary">Provincial Services Tax Framework</h4>
              <p className="text-xs text-text-secondary leading-relaxed">
                Services are governed strictly by Provincial Revenue Authorities (Punjab: PRA @ 16%, Sindh: SRB @ 15%,
                Khyber Pakhtunkhwa: KPRA @ 15%, Balochistan: BRA @ 15%, Islamabad Capital: ICT @ 15%).
                By statutory rule, Section 3(1A) 4% Further Tax is <strong>strictly 0%</strong> on services.
                Withholding Sales Tax (Wh-ST) rules apply at 100% deduction for unregistered/inactive service providers
                and 20% for active corporate service providers.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">PRA (Punjab @ 16%)</span>
              <p className="text-lg font-bold text-text-primary mt-1">Punjab Sales Tax on Services</p>
              <span className="text-[10px] text-text-secondary">Wh-ST: 100% unregistered / 20% active corp</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">SRB (Sindh @ 15%)</span>
              <p className="text-lg font-bold text-text-primary mt-1">Sindh Sales Tax on Services</p>
              <span className="text-[10px] text-text-secondary">Wh-ST: 100% unregistered / 20% active corp</span>
            </div>
            <div className="p-4 rounded-2xl bg-bg-surface border border-border-subtle">
              <span className="text-[11px] uppercase tracking-wide text-text-muted font-medium">KPRA / BRA / ICT (15%)</span>
              <p className="text-lg font-bold text-text-primary mt-1">Regional Service Tax Authorities</p>
              <span className="text-[10px] text-text-secondary">IT Services: 2-3% concessionary regime</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

