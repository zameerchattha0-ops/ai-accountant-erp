import type { PrintDoc } from "./types";

/**
 * DocTemplate — PREMIUM printable document format.
 * One letterhead-quality template for every module (quotation, credit
 * note, debit note, bill…). A4-optimized: `@media print` (globals.css)
 * strips the app chrome, keeps colors via print-color-adjust, and the
 * status stamp / totals block survive every browser's print pipeline.
 *
 * Design language: deep gradient letterhead band, tabular numerals,
 * hairline rules, generous whitespace — "premium class" print output.
 */
export default function DocTemplate({
  doc,
  variant = "modern",
}: {
  doc: PrintDoc;
  variant?: "modern" | "professional" | "minimal";
}) {
  const num = (n: number) =>
    n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const isDraft = doc.status?.toLowerCase() === "draft";
  const isNegative = doc.totals.paidTone === "credit";

  if (variant === "professional") {
    return (
      <div className="bg-white text-slate-800 border-2 border-slate-800 print:border-0 print:shadow-none rounded-none shadow-sm">
        {/* Letterhead */}
        <div className="border-b-2 border-slate-800 px-10 pt-10 pb-6">
          <div className="flex justify-between items-end">
            <div>
              <p className="font-serif text-2xl font-bold tracking-tight">{doc.orgName}</p>
              {doc.orgTaxNumber && <p className="text-xs text-slate-500 mt-1">NTN: {doc.orgTaxNumber}</p>}
            </div>
            <div className="text-right">
              <p className="font-serif text-xl font-semibold uppercase tracking-[0.2em]">{doc.title}</p>
              <p className="text-sm tabular-nums font-mono mt-0.5">{doc.docNumber}</p>
              {!isDraft && (
                <span className="inline-block mt-2 px-3 py-0.5 border border-slate-800 text-[10px] font-bold uppercase tracking-widest">
                  {doc.status}
                </span>
              )}
            </div>
          </div>
        </div>
        {/* Meta grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 px-10 py-6 border-b border-slate-200">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">{doc.partyLabel}</p>
            <p className="font-medium text-sm">{doc.partyName || "-"}</p>
            {doc.partyEmail && <p className="text-xs text-slate-500 break-words">{doc.partyEmail}</p>}
            {doc.partyTaxNumber && <p className="text-xs text-slate-500">NTN {doc.partyTaxNumber}</p>}
          </div>
          {doc.metaRows.map((m) => (
            <div key={m.label}>
              <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">{m.label}</p>
              <p className="text-sm font-medium tabular-nums">{m.value}</p>
            </div>
          ))}
        </div>
        {/* Items */}
        <div className="px-10 py-6">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-widest text-slate-500 border-b-2 border-slate-800">
                <th className="py-2.5 font-semibold">{doc.itemsTitle ?? "Items"}</th>
                <th className="py-2.5 font-semibold text-right">{doc.quantityTitle ?? "Qty"}</th>
                <th className="py-2.5 font-semibold text-right">{doc.unitTitle ?? "Unit price"}</th>
                <th className="py-2.5 font-semibold text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {doc.items.length === 0 ? (
                <tr><td colSpan={4} className="py-4 text-center text-xs text-slate-400">No line items</td></tr>
              ) : (
                doc.items.map((it, i) => (
                  <tr key={i} className="border-b border-slate-200">
                    <td className="py-2.5 pr-4">
                      {it.description}
                      {it.discount != null && it.discount > 0 && <span className="block text-[11px] text-slate-400">Discount - {num(it.discount)}</span>}
                      {it.tax != null && it.tax > 0 && <span className="block text-[11px] text-slate-400">Tax + {num(it.tax)}</span>}
                    </td>
                    <td className="py-2.5 text-right tabular-nums">{it.quantity}</td>
                    <td className="py-2.5 text-right tabular-nums text-slate-600">{num(it.unitPrice)}</td>
                    <td className="py-2.5 text-right tabular-nums font-medium">{num(it.lineTotal)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <div className="mt-6 flex justify-end">
            <div className="w-64 space-y-1.5 text-sm">
              {doc.totals.subtotal != null && <div className="flex justify-between text-slate-600"><span>Subtotal</span><span className="tabular-nums">{num(doc.totals.subtotal)}</span></div>}
              {doc.totals.tax != null && doc.totals.tax > 0 && <div className="flex justify-between text-slate-600"><span>Tax</span><span className="tabular-nums">{num(doc.totals.tax)}</span></div>}
              <div className="pt-2 border-t-2 border-slate-800 flex justify-between font-bold"><span>Total</span><span className="tabular-nums">{num(doc.totals.total)}</span></div>
              {doc.totals.paid != null && doc.totals.paid > 0 && (
                <>
                  <div className="flex justify-between text-slate-600"><span>{doc.totals.paidLabel ?? "Paid"}</span><span className="tabular-nums">- {num(doc.totals.paid)}</span></div>
                  {doc.totals.balance != null && <div className="flex justify-between font-bold text-slate-900"><span>Balance due</span><span className="tabular-nums">{num(doc.totals.balance)}</span></div>}
                </>
              )}
            </div>
          </div>
        </div>
        {(doc.notes || doc.terms) && (
          <div className="px-10 pb-6 grid sm:grid-cols-2 gap-6 border-t border-slate-200 pt-4">
            {doc.notes && <div><p className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Notes</p><p className="text-xs text-slate-600">{doc.notes}</p></div>}
            {doc.terms && <div><p className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Terms</p><p className="text-xs text-slate-600">{doc.terms}</p></div>}
          </div>
        )}
        <div className="bg-slate-100 px-10 py-3 text-[11px] text-slate-500 text-center border-t border-slate-300">
          {doc.orgName} · {doc.title} {doc.docNumber}
        </div>
      </div>
    );
  }

  if (variant === "minimal") {
    return (
      <div className="bg-white text-slate-900 rounded-none shadow-none print:shadow-none p-10 font-sans border border-slate-100">
        <div className="flex justify-between items-start pb-8 border-b border-slate-100">
          <div>
            <h1 className="text-xl font-light tracking-tight">{doc.orgName}</h1>
            {doc.orgTaxNumber && <p className="text-xs text-slate-400 mt-0.5">NTN {doc.orgTaxNumber}</p>}
          </div>
          <div className="text-right">
            <span className="text-xs font-mono uppercase text-slate-400">{doc.title}</span>
            <p className="text-base font-mono tabular-nums">{doc.docNumber}</p>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 py-6 border-b border-slate-100 text-xs">
          <div><p className="text-slate-400 mb-0.5">{doc.partyLabel}</p><p className="font-medium">{doc.partyName || "-"}</p></div>
          {doc.metaRows.map((m) => (
            <div key={m.label}><p className="text-slate-400 mb-0.5">{m.label}</p><p className="font-medium tabular-nums">{m.value}</p></div>
          ))}
        </div>
        <div className="py-6">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-400 border-b border-slate-100">
                <th className="py-2 font-normal">{doc.itemsTitle ?? "Items"}</th>
                <th className="py-2 font-normal text-right">{doc.quantityTitle ?? "Qty"}</th>
                <th className="py-2 font-normal text-right">{doc.unitTitle ?? "Unit price"}</th>
                <th className="py-2 font-normal text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {doc.items.map((it, i) => (
                <tr key={i} className="border-b border-slate-50">
                  <td className="py-2 pr-4">{it.description}</td>
                  <td className="py-2 text-right tabular-nums">{it.quantity}</td>
                  <td className="py-2 text-right tabular-nums text-slate-500">{num(it.unitPrice)}</td>
                  <td className="py-2 text-right tabular-nums">{num(it.lineTotal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 flex justify-end">
            <div className="w-56 space-y-1 text-xs">
              <div className="flex justify-between py-1 border-t border-slate-900 font-semibold"><span>Total</span><span className="tabular-nums">{num(doc.totals.total)}</span></div>
              {doc.totals.paid != null && doc.totals.paid > 0 && (
                <>
                  <div className="flex justify-between text-slate-500"><span>Paid</span><span className="tabular-nums">- {num(doc.totals.paid)}</span></div>
                  {doc.totals.balance != null && <div className="flex justify-between font-semibold"><span>Balance</span><span className="tabular-nums">{num(doc.totals.balance)}</span></div>}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white text-slate-800 rounded-2xl overflow-hidden shadow-sm print:shadow-none print:rounded-none border border-border-subtle">
      {/* ===== Letterhead band ===== */}
      <div className={`bg-gradient-to-r ${doc.accent} ${doc.accentSolid} px-8 py-7 text-white relative`}>
        <div className="flex items-start justify-between">
          <div>
            <p className="font-semibold text-xl leading-tight">{doc.orgName}</p>
            {doc.orgTaxNumber && <p className="text-xs text-white/70 mt-0.5">NTN {doc.orgTaxNumber}</p>}
          </div>
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-[0.3em] text-white/70">{doc.title}</p>
            <p className="font-semibold text-lg tabular-nums mt-1">{doc.docNumber}</p>
            {!isDraft && (
              <span className="inline-block mt-2 px-3 py-0.5 rounded-full border border-white/50 text-[10px] font-bold uppercase tracking-widest">
                {doc.status}
              </span>
            )}
          </div>
        </div>
        <div className="mt-6 h-px bg-white/30" />
      </div>

      {/* ===== Meta grid ===== */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 px-8 py-6 border-b border-slate-100">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">{doc.partyLabel}</p>
          <p className="font-medium text-sm">{doc.partyName || "-"}</p>
          {doc.partyEmail && <p className="text-xs text-slate-500 break-words">{doc.partyEmail}</p>}
          {doc.partyTaxNumber && <p className="text-xs text-slate-500">NTN {doc.partyTaxNumber}</p>}
        </div>
        {doc.metaRows.map((m) => (
          <div key={m.label}>
            <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">{m.label}</p>
            <p className="text-sm font-medium tabular-nums">{m.value}</p>
          </div>
        ))}
      </div>

      {/* ===== Items ===== */}
      <div className="px-8 py-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-widest text-slate-400 border-b border-slate-200">
              <th className="py-2 font-medium">{doc.itemsTitle ?? "Items"}</th>
              <th className="py-2 font-medium text-right">{doc.quantityTitle ?? "Qty"}</th>
              <th className="py-2 font-medium text-right">{doc.unitTitle ?? "Unit price"}</th>
              <th className="py-2 font-medium text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {doc.items.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-4 text-center text-xs text-slate-400">No line items</td>
              </tr>
            ) : (
              doc.items.map((it, i) => (
                <tr key={i} className="border-b border-slate-50">
                  <td className="py-2.5 pr-4">
                    {it.description}
                    {it.discount != null && it.discount > 0 && (
                      <span className="block text-[11px] text-slate-400">Discount - {num(it.discount)}</span>
                    )}
                    {it.tax != null && it.tax > 0 && (
                      <span className="block text-[11px] text-slate-400">Tax + {num(it.tax)}</span>
                    )}
                  </td>
                  <td className="py-2.5 text-right tabular-nums">{it.quantity}</td>
                  <td className="py-2.5 text-right tabular-nums text-slate-500">{num(it.unitPrice)}</td>
                  <td className="py-2.5 text-right tabular-nums font-medium">{num(it.lineTotal)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* ===== Totals ===== */}
        <div className="mt-5 flex justify-end">
          <div className="w-64 space-y-1.5 text-sm">
            {doc.totals.subtotal != null && (
              <div className="flex justify-between text-slate-500">
                <span>Subtotal</span>
                <span className="tabular-nums">{num(doc.totals.subtotal)}</span>
              </div>
            )}
            {doc.totals.discount != null && doc.totals.discount > 0 && (
              <div className="flex justify-between text-slate-500">
                <span>Discount</span>
                <span className="tabular-nums">- {num(doc.totals.discount)}</span>
              </div>
            )}
            {doc.totals.tax != null && doc.totals.tax > 0 && (
              <div className="flex justify-between text-slate-500">
                <span>Tax</span>
                <span className="tabular-nums">{num(doc.totals.tax)}</span>
              </div>
            )}
            <div className="pt-2 border-t border-slate-200 flex justify-between">
              <span className="font-semibold">Total</span>
              <span className="font-semibold tabular-nums">{num(doc.totals.total)}</span>
            </div>
            {doc.totals.paid != null && doc.totals.paid > 0 && (
              <>
                <div className="flex justify-between text-slate-500">
                  <span>{doc.totals.paidLabel ?? (isNegative ? "Credited" : "Paid")}</span>
                  <span className="tabular-nums">- {num(doc.totals.paid)}</span>
                </div>
                {doc.totals.balance != null && (
                  <div className={`flex justify-between font-semibold ${isNegative ? "text-rose-700" : "text-slate-800"}`}>
                    <span>{doc.totals.balanceLabel ?? (isNegative ? "Balance credited" : "Balance due")}</span>
                    <span className="tabular-nums">{num(doc.totals.balance)}</span>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* ===== Notes / Terms ===== */}
      {(doc.notes || doc.terms) && (
        <div className="px-8 pb-6 grid sm:grid-cols-2 gap-6">
          {doc.notes && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">{doc.notesTitle ?? "Notes"}</p>
              <p className="text-xs text-slate-500 whitespace-pre-line">{doc.notes}</p>
            </div>
          )}
          {doc.terms && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">{doc.termsTitle ?? "Terms"}</p>
              <p className="text-xs text-slate-500 whitespace-pre-line">{doc.terms}</p>
            </div>
          )}
        </div>
      )}

      {/* ===== Footer ===== */}
      <div className="bg-slate-50 px-8 py-4 text-[11px] text-slate-400 text-center print:bg-white border-t border-slate-100">
        {doc.footer ?? (
          <>
            {doc.orgName} · {doc.title} {doc.docNumber} · Generated by AI Accountant
          </>
        )}
      </div>
    </div>
  );
}