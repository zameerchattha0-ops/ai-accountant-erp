import { Sparkles } from "lucide-react";
import type { InvoiceTemplateProps } from "./types";
import { fmtDate } from "./types";

/**
 * MODERN - gradient accent header, soft card layout, ai-native branding.
 */
export default function InvoiceTemplateModern({
  invoice, items, customer, org, formatAmount,
}: InvoiceTemplateProps) {
  return (
    <div className="bg-white text-slate-800 rounded-2xl overflow-hidden shadow-sm print:shadow-none print:rounded-none border border-border-subtle">
      {/* Header band */}
      <div className="bg-gradient-to-r from-violet-600 to-indigo-600 px-8 py-7 text-white print:bg-violet-600">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/15 flex items-center justify-center">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <p className="font-semibold text-lg leading-tight">{org?.legal_name ?? org?.name ?? "Your Company"}</p>
              {org?.tax_number && <p className="text-xs text-white/70">NTN {org.tax_number}</p>}
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase tracking-widest text-white/70">Invoice</p>
            <p className="font-semibold text-lg tabular-nums">{invoice.invoice_number}</p>
            <p className="text-xs text-white/70 mt-1 capitalize">{invoice.status.toLowerCase()}</p>
          </div>
        </div>
      </div>

      {/* Meta */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 px-8 py-6 border-b border-slate-100">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">Billed to</p>
          <p className="font-medium text-sm">{customer?.name ?? "-"}</p>
          {customer?.email && <p className="text-xs text-slate-500">{customer.email}</p>}
          {customer?.tax_number && <p className="text-xs text-slate-500">NTN {customer.tax_number}</p>}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">Invoice date</p>
          <p className="text-sm font-medium">{fmtDate(invoice.invoice_date)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">Due date</p>
          <p className="text-sm font-medium">{fmtDate(invoice.due_date)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">Amount due</p>
          <p className="text-sm font-semibold text-violet-700 tabular-nums">
            {formatAmount(invoice.total - invoice.amount_paid)}
          </p>
        </div>
      </div>

      {/* Items */}
      <div className="px-8 py-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-widest text-slate-400 border-b border-slate-200">
              <th className="py-2 font-medium">Description</th>
              <th className="py-2 font-medium text-right">Qty</th>
              <th className="py-2 font-medium text-right">Unit price</th>
              <th className="py-2 font-medium text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} className="border-b border-slate-50">
                <td className="py-2.5 pr-4">{it.description}</td>
                <td className="py-2.5 text-right tabular-nums">{it.quantity}</td>
                <td className="py-2.5 text-right tabular-nums text-slate-500">{formatAmount(it.unit_price)}</td>
                <td className="py-2.5 text-right tabular-nums font-medium">{formatAmount(it.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Totals */}
        <div className="mt-5 flex justify-end">
          <div className="w-60 space-y-1.5 text-sm">
            <div className="flex justify-between text-slate-500">
              <span>Subtotal</span>
              <span className="tabular-nums">{formatAmount(invoice.subtotal)}</span>
            </div>
            {invoice.discount_total > 0 && (
              <div className="flex justify-between text-slate-500">
                <span>Discount</span>
                <span className="tabular-nums">- {formatAmount(invoice.discount_total)}</span>
              </div>
            )}
            {invoice.tax_total > 0 && (
              <div className="flex justify-between text-slate-500">
                <span>Tax</span>
                <span className="tabular-nums">{formatAmount(invoice.tax_total)}</span>
              </div>
            )}
            <div className="pt-2 border-t border-slate-200 flex justify-between">
              <span className="font-semibold">Total</span>
              <span className="font-semibold tabular-nums">{formatAmount(invoice.total)}</span>
            </div>
            {invoice.amount_paid > 0 && (
              <>
                <div className="flex justify-between text-slate-500">
                  <span>Paid</span>
                  <span className="tabular-nums">- {formatAmount(invoice.amount_paid)}</span>
                </div>
                <div className="flex justify-between text-violet-700 font-semibold">
                  <span>Balance due</span>
                  <span className="tabular-nums">{formatAmount(invoice.total - invoice.amount_paid)}</span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {invoice.notes && (
        <div className="px-8 pb-6">
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">Notes</p>
          <p className="text-xs text-slate-500">{invoice.notes}</p>
        </div>
      )}

      <div className="bg-slate-50 px-8 py-4 text-[11px] text-slate-400 text-center print:bg-white">
        {org?.legal_name ?? org?.name ?? "Your Company"} · Generated by AI Accountant
      </div>
    </div>
  );
}
