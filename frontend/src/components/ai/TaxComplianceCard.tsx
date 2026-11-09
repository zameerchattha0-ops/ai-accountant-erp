"use client";

import { ShieldCheck, AlertTriangle, FileText, CheckCircle2, Building2, Landmark, Percent } from "lucide-react";
import { formatCurrency } from "@/lib/utils/currency";

export interface TaxBreakdownData {
  authority?: string;
  supply_nature?: "GOODS" | "SERVICE" | string;
  sales_tax_rate?: number;
  sales_tax_amount?: number;
  further_tax_rate?: number;
  further_tax_amount?: number;
  total_tax_amount?: number;
  input_tax_eligible?: boolean;
  input_tax_asset_amount?: number;
  expense_or_cost_amount?: number;
  wht_rate_percent?: number;
  wht_amount?: number;
  whst_amount?: number;
  sales_tax_withholding_percentage?: number;
  net_payable?: number;
  net_cash_payment_to_vendor?: number;
  gross_total?: number;
  gross_invoice_total?: number;
  rule_code?: string;
  advisory?: string;
  payment_method?: string;
  amount?: number;
  subtotal?: number;
  s73_warning?: string;
  is_cash?: boolean;
}

interface Props {
  data?: TaxBreakdownData | Record<string, unknown>;
  summary?: string;
  currency?: string;
  onViewCertificate?: () => void;
}

export default function TaxComplianceCard({
  data,
  summary,
  currency = "PKR",
  onViewCertificate,
}: Props) {
  if (!data && !summary) return null;

  const d = (data || {}) as TaxBreakdownData;

  // Extract or infer values
  const authority = String(d.authority || "FBR").toUpperCase();
  const nature = String(d.supply_nature || (summary && /service/i.test(summary) ? "SERVICE" : "GOODS")).toUpperCase();
  const rate = Number(d.sales_tax_rate ?? (summary && /(\d+(?:\.\d+)?)\s*%\s*(?:gst|pra|srb|service)/i.exec(summary)?.[1]) ?? 18);
  const taxAmount = Number(d.sales_tax_amount ?? d.total_tax_amount ?? 0);
  const furtherTaxAmount = Number(d.further_tax_amount ?? 0);
  const inputEligible = d.input_tax_eligible !== false;
  const inputAssetAmount = Number(d.input_tax_asset_amount ?? (inputEligible ? taxAmount : 0));
  const whtRate = Number(d.wht_rate_percent ?? 0);
  const whtAmount = Number(d.wht_amount ?? 0);
  const whstAmount = Number(d.whst_amount ?? 0);
  const totalAmount = Number(d.gross_total ?? d.gross_invoice_total ?? d.amount ?? 0);

  // Section 73 Cash Limitation Check
  const paymentMethod = String(d.payment_method || (summary && /cash/i.test(summary) ? "CASH" : "BANK")).toUpperCase();
  const isCash = paymentMethod === "CASH" || Boolean(d.is_cash);
  const isS73Violation = isCash && totalAmount > 50000;

  const isProvincial = ["PRA", "SRB", "KPRA", "BRA", "ICT"].includes(authority) || nature === "SERVICE";

  return (
    <div className="rounded-2xl border border-ai-200/80 bg-gradient-to-b from-ai-50/50 to-bg-surface overflow-hidden shadow-sm">
      {/* Header bar */}
      <div className="px-4 py-3 bg-ai-50/80 border-b border-ai-200/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-ai-500 text-white flex items-center justify-center font-bold text-xs shadow-xs">
            CA
          </div>
          <div>
            <h4 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
              Chartered Tax & Compliance Audit
            </h4>
            <p className="text-[10px] text-text-muted">
              {authority} {isProvincial ? "Provincial Services Regime" : "Federal Goods Regime (STA 1990)"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-white/80 text-ai-700 border-ai-200 shadow-2xs">
            {nature === "SERVICE" ? "SERVICE" : "GOODS"} · {rate}% {authority}
          </span>
          {isProvincial ? (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200">
              0% Further Tax (Services)
            </span>
          ) : furtherTaxAmount > 0 ? (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border bg-amber-50 text-amber-700 border-amber-200">
              +4% Further Tax (S.3(1A))
            </span>
          ) : null}
        </div>
      </div>

      <div className="p-4 space-y-3.5">
        {/* Section 73 Cash Limitation Banner */}
        {isS73Violation ? (
          <div className="flex items-start gap-2.5 p-3 rounded-xl bg-amber-50/90 border border-amber-200/80 text-amber-900 text-xs">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-amber-950">
                ⚠️ Section 73 Compliance Warning: Cash Payment Exceeds Rs. 50,000
              </p>
              <p className="text-[11px] text-amber-800 mt-0.5 leading-relaxed">
                Under Section 73 of the Income Tax Ordinance 2001 and Sales Tax Act 1990, business payments over Rs. 50,000 in cash violate the statutory banking channel. Input tax recovery is forfeited and the expense may be disallowed in tax assessment. Switch to a crossed cheque or bank transfer.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-50/60 border border-emerald-200/60 text-emerald-800 text-[11px]">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
            <span>
              {isCash
                ? "Section 73 Compliant: Cash amount is within the statutory Rs. 50,000 threshold."
                : "Section 73 Compliant: Routed through verifiable banking channel."}
            </span>
          </div>
        )}

        {/* 4-Column Statutory Metric Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
          <div className="p-2.5 rounded-xl border border-border-subtle bg-bg-surface">
            <p className="text-[10px] uppercase tracking-wide text-text-muted font-medium flex items-center gap-1">
              <Building2 className="w-3 h-3 text-ai-500" /> Applicable Tax
            </p>
            <p className="font-semibold text-text-primary tabular-nums mt-1">
              {rate}% ({formatCurrency(taxAmount, currency)})
            </p>
            <p className="text-[10px] text-text-secondary mt-0.5">
              {isProvincial ? `${authority} Services Tariff` : "FBR Standard GST"}
            </p>
          </div>

          <div className="p-2.5 rounded-xl border border-border-subtle bg-bg-surface">
            <p className="text-[10px] uppercase tracking-wide text-text-muted font-medium flex items-center gap-1">
              <ShieldCheck className="w-3 h-3 text-emerald-600" /> Input Tax Asset
            </p>
            <p className="font-semibold tabular-nums mt-1 text-emerald-700">
              {inputEligible ? formatCurrency(inputAssetAmount, currency) : "Rs. 0.00"}
            </p>
            <p className="text-[10px] text-text-secondary mt-0.5">
              {inputEligible ? "Asset (Account 1060)" : "Capitalized to Cost"}
            </p>
          </div>

          <div className="p-2.5 rounded-xl border border-border-subtle bg-bg-surface">
            <p className="text-[10px] uppercase tracking-wide text-text-muted font-medium flex items-center gap-1">
              <Percent className="w-3 h-3 text-purple-600" /> Income Tax WHT
            </p>
            <p className="font-semibold tabular-nums mt-1 text-purple-700">
              {whtRate > 0 ? `${whtRate}% (${formatCurrency(whtAmount, currency)})` : "0% (Exempt / None)"}
            </p>
            <p className="text-[10px] text-text-secondary mt-0.5">
              u/s 153 ITO 2001
            </p>
          </div>

          <div className="p-2.5 rounded-xl border border-border-subtle bg-bg-surface">
            <p className="text-[10px] uppercase tracking-wide text-text-muted font-medium flex items-center gap-1">
              <Landmark className="w-3 h-3 text-blue-600" /> Sales Tax Wh-ST
            </p>
            <p className="font-semibold tabular-nums mt-1 text-blue-700">
              {whstAmount > 0 ? formatCurrency(whstAmount, currency) : "Rs. 0.00"}
            </p>
            <p className="text-[10px] text-text-secondary mt-0.5">
              {authority} Wh-Rules
            </p>
          </div>
        </div>

        {/* Advisory / Commentary */}
        {d.advisory && (
          <div className="px-3.5 py-2.5 rounded-xl bg-bg-surface border border-border-subtle/80 text-xs text-text-secondary leading-relaxed">
            <span className="font-medium text-text-primary">CA Finding: </span>
            {d.advisory}
          </div>
        )}

        {/* Certificate Button if WHT exists */}
        {(whtAmount > 0 || whstAmount > 0 || onViewCertificate) && (
          <div className="flex items-center justify-between pt-1">
            <div className="text-[11px] text-text-muted">
              Withholding deductions require official CPR / Form 165 documentation.
            </div>
            {onViewCertificate && (
              <button
                type="button"
                onClick={onViewCertificate}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-ai-50 hover:bg-ai-100 text-ai-700 text-xs font-medium border border-ai-200 transition-colors cursor-pointer"
              >
                <FileText className="w-3.5 h-3.5" /> View WHT Certificate
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

