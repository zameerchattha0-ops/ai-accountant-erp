import type { InvoiceTemplateProps } from "./types";
import { fmtDate } from "./types";

/**
 * PROFESSIONAL - traditional enterprise letterhead: serif accents, ruled
 * borders, formal block layout. Suited to corporate clients and print.
 */
export default function InvoiceTemplateProfessional({
  invoice, items, customer, org, formatAmount,
}: InvoiceTemplateProps) {
  return (
    <div className="bg-white text-slate-800 border border-slate-300 print:border-0 print:shadow-none rounded-none shadow-sm">
      {/* Letterhead */}
      <div className="border-b-2 border-slate-800 px-10 pt-10 pb-6">
        <div className="flex justify-between items-end">
          <div>
            <p className="font-serif text-2xl font-bold tracking-tight">
              {org?.legal_name ?? org?.name ?? "Your Company"}
            </p>
            {org?.tax_number && (
              <p className="text-xs text-slate-500 mt-1">Business NTN: {org.tax_number}</p>
            )}
          </div>
          <div className="text-right">
            <p className="font-serif text-xl font-semibold uppercase tracking-[0.2em]">Invoice</p>
            <p className="text-sm tabular-nums mt-0.5">{invoice.invoice_number}</p>
          </div>
        </div>
      </div>

      {/* Parties */}
      <div className="grid grid-cols-2 gap-8 px-10 py-7 border-b border-slate-200">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">From</p>
          <p className="text-sm font-medium">{org?.legal_name ?? org?.name ?? "Your Company"}</p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">Bill to</p>
          <p className="text-sm font-medium">{customer?.name ?? "-"}</p>
          {customer?.email && <p className="text-xs text-slate-500">{customer.email}</p>}
          {customer?.phone && <p className="text-xs text-slate-500">{customer.phone}</p>}
          {customer?.tax_number && <p className="text-xs text-slate-500">NTN {customer.tax_number}</p>}
        </div>
      </div>

      {/* Meta strip */}
      <div className="grid grid-cols-4 divide-x divide-slate-200 border-b border-slate-200 text-center">
        {[
          ["Invoice date", fmtDate(invoice.invoice_date)],
          ["Due date", fmtDate(invoice.due_date)],
          ["Terms", invoice.payment_terms_days != null ? `${invoice.payment_terms_days} days` : "-"],
          ["Currency", invoice.currency_code],
        ].map(([label, value]) => (
          <div key={label} className="py-3">
            <p className="text-[10px] uppercase tracking-widest text-slate-400">{label}</p>
            <p className="text-sm font-medium mt-0.5">{value}</p>
          </div>
        ))}
      </div>

      {/* Items */}
      <div className="px-10 py-7">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-100 text-left text-[11px] uppercase tracking-wide text-slate-600">
              <th className="px-3 py-2.5 font-semibold border border-slate-200">#</th>
              <th className="px-3 py-2.5 font-semibold border border-slate-200">Description</th>
              <th className="px-3 py-2.5 font-semibold border border-slate-200 text-right">Qty</th>
              <th className="px-3 py-2.5 font-semibold border border-slate-200 text-right">Unit price</th>
              <th className="px-3 py-2.5 font-semibold border border-slate-200 text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={it.id}>
                <td className="px-3 py-2.5 border border-slate-200 text-slate-400 tabular-nums">{i + 1}</td>
                <td className="px-3 py-2.5 border border-slate-200">{it.description}</td>
                <td className="px-3 py-2.5 border border-slate-200 text-right tabular-nums">{it.quantity}</td>
                <td className="px-3 py-2.5 border border-slate-200 text-right tabular-nums">{formatAmount(it.unit_price)}</td>
                <td className="px-3 py-2.5 border border-slate-200 text-right tabular-nums font-medium">{formatAmount(it.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Totals */}
        <div className="mt-6 flex justify-end">
          <table className="text-sm w-72">
            <tbody>
              <tr>
                <td className="py-1 text-slate-500">Subtotal</td>
                <td className="py-1 text-right tabular-nums">{formatAmount(invoice.subtotal)}</td>
              </tr>
              {invoice.discount_total > 0 && (
                <tr>
                  <td className="py-1 text-slate-500">Discount</td>
                  <td className="py-1 text-right tabular-nums">- {formatAmount(invoice.discount_total)}</td>
                </tr>
              )}
              {invoice.tax_total > 0 && (
                <tr>
                  <td className="py-1 text-slate-500">Tax</td>
                  <td className="py-1 text-right tabular-nums">{formatAmount(invoice.tax_total)}</td>
                </tr>
              )}
              <tr className="border-t-2 border-slate-800">
                <td className="py-2 font-semibold">Total due</td>
                <td className="py-2 text-right font-semibold tabular-nums">{formatAmount(invoice.total)}</td>
              </tr>
              {invoice.amount_paid > 0 && (
                <tr>
                  <td className="py-1 text-slate-500">Paid</td>
                  <td className="py-1 text-right tabular-nums">- {formatAmount(invoice.amount_paid)}</td>
                </tr>
              )}
              {invoice.amount_paid > 0 && (
                <tr className="border-t border-slate-300">
                  <td className="py-2 font-semibold">Balance</td>
                  <td className="py-2 text-right font-semibold tabular-nums">
                    {formatAmount(invoice.total - invoice.amount_paid)}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {invoice.notes && (
        <div className="px-10 pb-6">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Notes</p>
          <p className="text-xs text-slate-600">{invoice.notes}</p>
        </div>
      )}
      {invoice.terms && (
        <div className="px-10 pb-6">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Terms</p>
          <p className="text-xs text-slate-600">{invoice.terms}</p>
        </div>
      )}

      <div className="border-t border-slate-200 px-10 py-4 flex justify-between items-center">
        <p className="text-[11px] text-slate-400">Status: {invoice.status}</p>
        <p className="font-serif text-xs text-slate-500 italic">Thank you for your business</p>
      </div>
    </div>
  );
}
