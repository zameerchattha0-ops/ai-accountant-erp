import type { PrintDoc, PrintDocItem } from "./types";
import { ACCENTS, fmtDate } from "./types";

/* ---- Builders: module records → normalized PrintDoc ---------------
   Each builder maps a module's DB record + line items + party into the
   premium template's shape, keeping column naming module-accurate
   ("Valid until" on quotations, "Reason" on credit/debit notes, …). */

const fmtNum = (n: number | null | undefined) =>
  Number(n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const partyName = (p: unknown): string => {
  if (!p) return "-";
  const row = Array.isArray(p) ? p[0] : p;
  return (row as { name?: string } | null)?.name ?? "-";
};

interface CommonMeta {
  orgName: string;
  orgTaxNumber?: string | null;
  partyLabel: string;
  party: unknown;
  partyEmail?: string | null;
  partyTaxNumber?: string | null;
}

const metaDoc = (m: CommonMeta): Pick<PrintDoc, "orgName" | "orgTaxNumber" | "partyLabel" | "partyName" | "partyEmail" | "partyTaxNumber"> => ({
  orgName: m.orgName,
  orgTaxNumber: m.orgTaxNumber,
  partyLabel: m.partyLabel,
  partyName: partyName(m.party),
  partyEmail: m.partyEmail ?? null,
  partyTaxNumber: m.partyTaxNumber ?? null,
});

/* Quotation → premium printable quotation */
export function buildQuotationDoc(q: Record<string, unknown>, items: Record<string, unknown>[], m: CommonMeta): PrintDoc {
  const accent = ACCENTS.quotation;
  const lines: PrintDocItem[] = items.map((it) => ({
    description: String(it.description ?? "-"),
    quantity: Number(it.quantity ?? 0),
    unitPrice: Number(it.unit_price ?? 0),
    discount: Number(it.discount_amount ?? 0),
    tax: Number(it.tax_amount ?? 0),
    lineTotal: Number(it.line_total ?? 0),
  }));
  return {
    title: "Quotation",
    docNumber: `${String(q.quotation_number ?? "-")}${Number(q.revision ?? 1) > 1 ? ` rev ${Number(q.revision)}` : ""}`,
    status: String(q.status ?? "DRAFT"),
    accent: accent.gradient,
    accentSolid: accent.solid,
    ...metaDoc(m),
    metaRows: [
      { label: "Quotation date", value: fmtDate((q.quotation_date as string) ?? null) },
      { label: "Valid until", value: fmtDate((q.valid_until as string) ?? null) },
      { label: "Total", value: fmtNum(Number(q.total ?? 0)) },
    ],
    items: lines,
    totals: {
      subtotal: Number(q.subtotal ?? 0),
      discount: Number(q.discount_total ?? 0),
      tax: Number(q.tax_total ?? 0),
      total: Number(q.total ?? 0),
    },
    notes: (q.notes as string) ?? null,
    terms: (q.terms as string) ?? null,
  };
}

/* Credit note → premium printable credit note */
export function buildCreditNoteDoc(cn: Record<string, unknown>, items: Record<string, unknown>[], m: CommonMeta): PrintDoc {
  const accent = ACCENTS.creditNote;
  const lines: PrintDocItem[] = items.map((it) => ({
    description: String(it.description ?? "-"),
    quantity: Number(it.quantity ?? 0),
    unitPrice: Number(it.unit_price ?? 0),
    discount: Number(it.discount_amount ?? 0),
    tax: Number(it.tax_amount ?? 0),
    lineTotal: Number(it.line_total ?? 0),
  }));
  return {
    title: "Credit Note",
    docNumber: String(cn.credit_note_number ?? "-"),
    status: String(cn.status ?? "DRAFT"),
    accent: accent.gradient,
    accentSolid: accent.solid,
    ...metaDoc({ ...m, partyLabel: "Credited to" }),
    metaRows: [
      { label: "Credit note date", value: fmtDate((cn.credit_note_date as string) ?? null) },
      { label: "Reason", value: String(cn.reason ?? "-") },
      { label: "Total credited", value: fmtNum(Number(cn.total ?? 0)) },
    ],
    items: lines,
    itemsTitle: "Credited items",
    totals: {
      subtotal: Number(cn.subtotal ?? 0),
      discount: Number(cn.discount_total ?? 0),
      tax: Number(cn.tax_total ?? 0),
      total: Number(cn.total ?? 0),
      paidTone: "credit",
    },
    notes: (cn.reason as string) ?? null,
    notesTitle: "Reason",
  };
}

/* Purchase return → premium printable DEBIT NOTE */
export function buildDebitNoteDoc(r: Record<string, unknown>, items: Record<string, unknown>[], m: CommonMeta): PrintDoc {
  const accent = ACCENTS.debitNote;
  const lines: PrintDocItem[] = items.map((it) => ({
    description: String(it.description ?? "-"),
    quantity: Number(it.quantity ?? 0),
    unitPrice: Number(it.unit_price ?? 0),
    tax: Number(it.tax_amount ?? 0),
    lineTotal: Number(it.line_total ?? 0),
  }));
  return {
    title: "Debit Note",
    docNumber: String(r.return_number ?? "-"),
    status: String(r.status ?? "DRAFT"),
    accent: accent.gradient,
    accentSolid: accent.solid,
    ...metaDoc({ ...m, partyLabel: "Debited to (supplier)" }),
    metaRows: [
      { label: "Return date", value: fmtDate((r.return_date as string) ?? null) },
      { label: "Reason", value: String(r.reason ?? "-") },
      { label: "Total debited", value: fmtNum(Number(r.total ?? 0)) },
    ],
    items: lines,
    itemsTitle: "Returned items",
    totals: {
      subtotal: Number(r.subtotal ?? 0),
      tax: Number(r.tax_total ?? 0),
      total: Number(r.total ?? 0),
      paidTone: "credit",
    },
    notes: (r.reason as string) ?? null,
    notesTitle: "Reason",
  };
}

/* Purchase bill → premium printable vendor bill */
export function buildBillDoc(b: Record<string, unknown>, items: Record<string, unknown>[], m: CommonMeta): PrintDoc {
  const accent = ACCENTS.bill;
  const lines: PrintDocItem[] = items.map((it) => ({
    description: String(it.description ?? "-"),
    quantity: Number(it.quantity ?? 0),
    unitPrice: Number(it.unit_price ?? 0),
    discount: Number(it.discount_amount ?? 0),
    tax: Number(it.tax_amount ?? 0),
    lineTotal: Number(it.line_total ?? 0),
  }));
  const paid = Number(b.amount_paid ?? 0);
  return {
    title: "Purchase Bill",
    docNumber: String(b.bill_number ?? "-"),
    status: String(b.status ?? "DRAFT"),
    accent: accent.gradient,
    accentSolid: accent.solid,
    ...metaDoc({ ...m, partyLabel: "Supplier" }),
    metaRows: [
      { label: "Bill date", value: fmtDate((b.bill_date as string) ?? null) },
      { label: "Due date", value: fmtDate((b.due_date as string) ?? null) },
      { label: "Amount due", value: fmtNum(Math.max(0, Number(b.total ?? 0) - paid)) },
    ],
    items: lines,
    itemsTitle: "Purchased items",
    totals: {
      subtotal: Number(b.subtotal ?? 0),
      discount: Number(b.discount_total ?? 0),
      tax: Number(b.tax_total ?? 0),
      total: Number(b.total ?? 0),
      paid,
      balance: Math.max(0, Number(b.total ?? 0) - paid),
      paidTone: "debit",
    },
    notes: (b.notes as string) ?? null,
  };
}