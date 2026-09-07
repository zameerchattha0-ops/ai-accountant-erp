import type { InvoiceTemplateProps } from "./types";
import { fmtDate } from "./types";

/**
 * MINIMAL - stripped-back, monochrome, print-friendly. Maximum ink economy:
 * no fills, hairline rules, tight spacing.
 */
export default function InvoiceTemplateMinimal({
  invoice, items, customer, org, formatAmount,
}: InvoiceTemplateProps) {
  return (
    <div className="bg-white text-slate-700 print:shadow-none print:rounded-none">
      <div className="px-8 py-10">
        {/* Top line */}
        <div className="flex justify-between items-baseline">
          <p className="font-medium tracking-tight">{org?.name ?? "Your Company"}</p>
          <p className="text-sm tracking-widest uppercase text-slate-400">Invoice</p>
        </div>
        <p className="text-xs text-slate-400 mt-0.5">
          {invoice.invoice_number} · {fmtDate(invoice.invoice_date)}
          {invoice.due_date ? ` · due ${fmtDate(invoice.due_date)}` : ""}
        </p>

        <div className="mt-8 flex justify-between text-sm">
          <div>
            <p className="text-xs text-slate-400">From</p>
            <p>{org?.legal_name ?? org?.name ?? "Your Company"}</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-slate-400">To</p>
            <p>{customer?.name ?? "-"}</p>
            {customer?.email && <p className="text-xs text-slate-400">{customer.email}</p>}
          </div>
        </div>

        {/* Items - hairline table */}
        <table className="w-full mt-10 text-sm">
          <thead>
            <tr className="text-xs text-slate-400 border-b border-slate-200">
              <th className="py-2 text-left font-normal">Description</th>
              <th className="py-2 text-right font-normal">Qty</th>
              <th className="py-2 text-right font-normal">Price</th>
              <th className="py-2 text-right font-normal">Amount</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} className="border-b border-slate-100">
                <td className="py-2">{it.description}</td>
                <td className="py-2 text-right tabular-nums text-slate-500">{it.quantity}</td>
                <td className="py-2 text-right tabular-nums text-slate-500">{formatAmount(it.unit_price)}</td>
                <td className="py-2 text-right tabular-nums">{formatAmount(it.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Totals - right column only */}
        <div className="mt-6 flex justify-end">
          <div className="w-56 text-sm">
            <div className="flex justify-between py-1 text-slate-500">
              <span>Subtotal</span><span className="tabular-nums">{formatAmount(invoice.subtotal)}</span>
            </div>
            {invoice.tax_total > 0 && (
              <div className="flex justify-between py-1 text-slate-500">
                <span>Tax</span><span className="tabular-nums">{formatAmount(invoice.tax_total)}</span>
              </div>
            )}
            <div className="flex justify-between py-1.5 border-t border-slate-800 mt-1 font-medium">
              <span>Total</span><span className="tabular-nums">{formatAmount(invoice.total)}</span>
            </div>
            {invoice.amount_paid > 0 && (
              <div className="flex justify-between py-1.5 text-slate-500">
                <span>Balance due</span>
                <span className="tabular-nums">{formatAmount(invoice.total - invoice.amount_paid)}</span>
              </div>
            )}
          </div>
        </div>

        {invoice.notes && <p className="mt-10 text-xs text-slate-400">{invoice.notes}</p>}

        <p className="mt-12 text-[10px] text-slate-300 tracking-wide">
          {invoice.currency_code} · {invoice.status}
        </p>
      </div>
    </div>
  );
}
