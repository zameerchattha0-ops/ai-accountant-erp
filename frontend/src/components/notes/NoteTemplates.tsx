import { Sparkles } from "lucide-react";
import { fmtDate } from "@/components/invoices/types";

/**
 * Branded document templates for CREDIT NOTES (customer returns) and
 * DEBIT NOTES (purchase returns) — the same three brand styles as the
 * invoice templates (Modern / Professional / Minimal) so every document
 * family shares one look.  Reason-forward: the reason why the note exists
 * sits directly under the letterhead.
 */

export type NoteVariant = "modern" | "professional" | "minimal";

export interface NoteItem {
  id: string;
  description: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

export interface NoteParty {
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  tax_number?: string | null;
}

export interface NoteDoc {
  number: string;
  date: string;
  status: string;
  reason?: string | null;
  subtotal: number;
  discount_total?: number | null;
  tax_total: number;
  total: number;
  /** The invoice/bill this note is issued against (ids resolved by the page). */
  reference?: string | null;
}

export interface NoteTemplateProps {
  kind: "credit" | "debit";
  variant: NoteVariant;
  note: NoteDoc;
  items: NoteItem[];
  party: NoteParty | null;
  org: {
    name?: string | null;
    legal_name?: string | null;
    tax_number?: string | null;
  } | null;
  formatAmount: (n: number) => string;
}

/**
 * The three template bodies render the same note; only the dispatcher
 * selects a variant — so they omit it (the dispatcher strips it from
 * `rest` before spreading).
 */
type NoteBodyProps = Omit<NoteTemplateProps, "variant">;

export const noteLabels = (kind: "credit" | "debit") =>
  kind === "credit"
    ? {
        title: "Credit Note",
        partyLabel: "Credited to",
        refLabel: "Against invoice",
        foot: "Thank you — your balance has been adjusted.",
      }
    : {
        title: "Debit Note",
        partyLabel: "Debited to (supplier)",
        refLabel: "Against bill",
        foot: "Goods returned — payable adjusted.",
      };

/* --------------------------------------------------------------------------
 * MODERN — gradient accent header, soft card layout (mirrors
 * InvoiceTemplateModern; rose for credit notes, amber for debit notes).
 * ------------------------------------------------------------------------ */
function Modern({ kind, note, items, party, org, formatAmount }: NoteBodyProps) {
  const L = noteLabels(kind);
  const band =
    kind === "credit"
      ? "from-rose-600 to-orange-600 print:bg-rose-600"
      : "from-amber-600 to-orange-700 print:bg-amber-600";
  return (
    <div className="bg-white text-slate-800 rounded-2xl overflow-hidden shadow-sm print:shadow-none print:rounded-none border border-border-subtle">
      <div className={`bg-gradient-to-r ${band} px-8 py-7 text-white`}>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/15 flex items-center justify-center">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <p className="font-semibold text-lg leading-tight">
                {org?.legal_name ?? org?.name ?? "Your Company"}
              </p>
              {org?.tax_number && (
                <p className="text-xs text-white/70">NTN {org.tax_number}</p>
              )}
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase tracking-widest text-white/70">
              {L.title}
            </p>
            <p className="font-semibold text-lg tabular-nums">{note.number}</p>
            <p className="text-xs text-white/70 mt-1 capitalize">
              {note.status.toLowerCase()}
            </p>
          </div>
        </div>
      </div>

      {note.reason && (
        <div className="bg-rose-50 border-b border-rose-100 px-8 py-4">
          <p className="text-[10px] uppercase tracking-widest text-rose-400 mb-1">
            Reason
          </p>
          <p className="text-sm text-rose-900">{note.reason}</p>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 px-8 py-6 border-b border-slate-100">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
            {L.partyLabel}
          </p>
          <p className="font-medium text-sm">{party?.name ?? "-"}</p>
          {party?.email && <p className="text-xs text-slate-500">{party.email}</p>}
          {party?.tax_number && (
            <p className="text-xs text-slate-500">NTN {party.tax_number}</p>
          )}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
            Note date
          </p>
          <p className="text-sm font-medium">{fmtDate(note.date)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
            {L.refLabel}
          </p>
          <p className="text-sm font-medium">{note.reference ?? "-"}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
            Adjusted amount
          </p>
          <p className="text-sm font-semibold text-rose-700 tabular-nums">
            {formatAmount(note.total)}
          </p>
        </div>
      </div>

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
                <td className="py-2.5 text-right tabular-nums text-slate-500">
                  {formatAmount(it.unit_price)}
                </td>
                <td className="py-2.5 text-right tabular-nums font-medium">
                  {formatAmount(it.line_total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="mt-5 flex justify-end">
          <div className="w-60 space-y-1.5 text-sm">
            <div className="flex justify-between text-slate-500">
              <span>Subtotal</span>
              <span className="tabular-nums">{formatAmount(note.subtotal)}</span>
            </div>
            {!!note.discount_total && note.discount_total > 0 && (
              <div className="flex justify-between text-slate-500">
                <span>Discount</span>
                <span className="tabular-nums">
                  - {formatAmount(note.discount_total)}
                </span>
              </div>
            )}
            {note.tax_total > 0 && (
              <div className="flex justify-between text-slate-500">
                <span>Tax</span>
                <span className="tabular-nums">{formatAmount(note.tax_total)}</span>
              </div>
            )}
            <div className="pt-2 border-t border-slate-200 flex justify-between">
              <span className="font-semibold">Adjusted total</span>
              <span className="font-semibold tabular-nums">
                {formatAmount(note.total)}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-slate-50 px-8 py-4 text-[11px] text-slate-400 text-center print:bg-white">
        {org?.legal_name ?? org?.name ?? "Your Company"} · {L.foot}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * PROFESSIONAL — traditional enterprise letterhead: serif accents, ruled
 * borders, formal block layout (mirrors InvoiceTemplateProfessional).
 * ------------------------------------------------------------------------ */
function Professional({
  kind, note, items, party, org, formatAmount,
}: NoteBodyProps) {
  const L = noteLabels(kind);
  return (
    <div className="bg-white text-slate-800 border border-slate-300 print:border-0 print:shadow-none rounded-none shadow-sm">
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
            <p className="font-serif text-xl font-semibold uppercase tracking-[0.2em]">
              {L.title}
            </p>
            <p className="text-sm tabular-nums mt-0.5">{note.number}</p>
          </div>
        </div>
      </div>

      {note.reason && (
        <div className="px-10 py-4 border-b border-slate-200 bg-slate-50">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">
            Reason
          </p>
          <p className="text-sm text-slate-700">{note.reason}</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-8 px-10 py-7 border-b border-slate-200">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
            From
          </p>
          <p className="text-sm font-medium">
            {org?.legal_name ?? org?.name ?? "Your Company"}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
            {L.partyLabel}
          </p>
          <p className="text-sm font-medium">{party?.name ?? "-"}</p>
          {party?.email && <p className="text-xs text-slate-500">{party.email}</p>}
          {party?.phone && <p className="text-xs text-slate-500">{party.phone}</p>}
          {party?.tax_number && (
            <p className="text-xs text-slate-500">NTN {party.tax_number}</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-4 divide-x divide-slate-200 border-b border-slate-200 text-center">
        {[
          ["Note date", fmtDate(note.date)],
          [L.refLabel, note.reference ?? "-"],
          ["Status", note.status],
          ["Adjusted", formatAmount(note.total)],
        ].map(([label, value]) => (
          <div key={label} className="py-3">
            <p className="text-[10px] uppercase tracking-widest text-slate-400">{label}</p>
            <p className="text-sm font-medium mt-0.5 tabular-nums">{value}</p>
          </div>
        ))}
      </div>

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
                <td className="px-3 py-2.5 border border-slate-200 text-slate-400 tabular-nums">
                  {i + 1}
                </td>
                <td className="px-3 py-2.5 border border-slate-200">{it.description}</td>
                <td className="px-3 py-2.5 border border-slate-200 text-right tabular-nums">
                  {it.quantity}
                </td>
                <td className="px-3 py-2.5 border border-slate-200 text-right tabular-nums">
                  {formatAmount(it.unit_price)}
                </td>
                <td className="px-3 py-2.5 border border-slate-200 text-right tabular-nums font-medium">
                  {formatAmount(it.line_total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="mt-6 flex justify-end">
          <table className="text-sm w-72">
            <tbody>
              <tr>
                <td className="py-1 text-slate-500">Subtotal</td>
                <td className="py-1 text-right tabular-nums">{formatAmount(note.subtotal)}</td>
              </tr>
              {!!note.discount_total && note.discount_total > 0 && (
                <tr>
                  <td className="py-1 text-slate-500">Discount</td>
                  <td className="py-1 text-right tabular-nums">
                    - {formatAmount(note.discount_total)}
                  </td>
                </tr>
              )}
              {note.tax_total > 0 && (
                <tr>
                  <td className="py-1 text-slate-500">Tax</td>
                  <td className="py-1 text-right tabular-nums">{formatAmount(note.tax_total)}</td>
                </tr>
              )}
              <tr className="border-t-2 border-slate-800">
                <td className="py-2 font-semibold">Adjusted total</td>
                <td className="py-2 text-right font-semibold tabular-nums">
                  {formatAmount(note.total)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="border-t border-slate-200 px-10 py-4 flex justify-between items-center">
        <p className="text-[11px] text-slate-400">Status: {note.status}</p>
        <p className="font-serif text-xs text-slate-500 italic">{L.foot}</p>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * MINIMAL — stripped typography, thin rules, maximum whitespace (mirrors
 * InvoiceTemplateMinimal).
 * ------------------------------------------------------------------------ */
function Minimal({ kind, note, items, party, org, formatAmount }: NoteBodyProps) {
  const L = noteLabels(kind);
  return (
    <div className="bg-white text-slate-900 border border-slate-200 rounded-lg print:border-0 shadow-none">
      <div className="px-10 pt-9 pb-5 flex justify-between items-start">
        <div>
          <p className="text-base font-semibold tracking-tight">
            {org?.legal_name ?? org?.name ?? "Your Company"}
          </p>
          {org?.tax_number && (
            <p className="text-[11px] text-slate-400 mt-0.5">NTN {org.tax_number}</p>
          )}
        </div>
        <div className="text-right">
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-slate-500">
            {L.title}
          </p>
          <p className="text-sm tabular-nums mt-0.5">{note.number}</p>
        </div>
      </div>

      <div className="mx-10 border-t border-slate-200" />

      {note.reason && (
        <div className="px-10 py-4">
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
            Reason
          </p>
          <p className="text-sm text-slate-600">{note.reason}</p>
        </div>
      )}

      <div className="px-10 py-5 flex flex-wrap gap-x-12 gap-y-3 text-sm">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-0.5">
            {L.partyLabel}
          </p>
          <p className="font-medium">{party?.name ?? "-"}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-0.5">
            Note date
          </p>
          <p className="font-medium tabular-nums">{fmtDate(note.date)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-0.5">
            {L.refLabel}
          </p>
          <p className="font-medium">{note.reference ?? "-"}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-0.5">
            Adjusted amount
          </p>
          <p className="font-medium tabular-nums">{formatAmount(note.total)}</p>
        </div>
      </div>

      <div className="px-10 pb-8">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-y border-slate-200 text-left text-[10px] uppercase tracking-widest text-slate-400">
              <th className="py-2 font-medium">Description</th>
              <th className="py-2 font-medium text-right">Qty</th>
              <th className="py-2 font-medium text-right">Unit price</th>
              <th className="py-2 font-medium text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} className="border-b border-slate-100">
                <td className="py-2.5 pr-4">{it.description}</td>
                <td className="py-2.5 text-right tabular-nums">{it.quantity}</td>
                <td className="py-2.5 text-right tabular-nums text-slate-500">
                  {formatAmount(it.unit_price)}
                </td>
                <td className="py-2.5 text-right tabular-nums">{formatAmount(it.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="mt-5 ml-auto w-60 text-sm space-y-1">
          <div className="flex justify-between text-slate-500">
            <span>Subtotal</span>
            <span className="tabular-nums">{formatAmount(note.subtotal)}</span>
          </div>
          {!!note.discount_total && note.discount_total > 0 && (
            <div className="flex justify-between text-slate-500">
              <span>Discount</span>
              <span className="tabular-nums">- {formatAmount(note.discount_total)}</span>
            </div>
          )}
          {note.tax_total > 0 && (
            <div className="flex justify-between text-slate-500">
              <span>Tax</span>
              <span className="tabular-nums">{formatAmount(note.tax_total)}</span>
            </div>
          )}
          <div className="flex justify-between border-t border-slate-300 pt-1.5 font-medium">
            <span>Adjusted total</span>
            <span className="tabular-nums">{formatAmount(note.total)}</span>
          </div>
        </div>
      </div>

      <div className="px-10 pb-5 text-[11px] text-slate-400 flex justify-between">
        <span>{note.status}</span>
        <span>{L.foot}</span>
      </div>
    </div>
  );
}

/** Branded credit/debit note document — pick the invoice house style. */
export default function NoteTemplate({ variant, ...rest }: NoteTemplateProps) {
  if (variant === "professional") return <Professional {...rest} />;
  if (variant === "minimal") return <Minimal {...rest} />;
  return <Modern {...rest} />;
}
