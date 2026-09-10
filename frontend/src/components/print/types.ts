import type { ReactNode } from "react";

/* ---- Normalized printable document -------------------------------
   One shape feeds the premium DocTemplate for every module:
   quotations, invoices, credit notes, debit notes (purchase returns),
   purchase bills — sales and purchases alike. */
export interface PrintDocTotals {
  subtotal?: number;
  discount?: number;
  tax?: number;
  total: number;
  paid?: number;
  balance?: number;
  paidLabel?: string;
  balanceLabel?: string;
  paidTone?: "credit" | "debit";
}

export interface PrintDocItem {
  description: string;
  quantity: number;
  unitPrice: number;
  discount?: number;
  tax?: number;
  lineTotal: number;
}

export interface PrintDoc {
  /* Letterhead band */
  title: string;             // e.g. "Quotation", "Credit Note", "Debit Note"
  docNumber: string;         // e.g. "QT-000042 rev 2"
  status: string;            // e.g. "DRAFT", "POSTED"
  accent: string;            // tailwind gradient classes, e.g. "from-violet-600 to-indigo-600"
  accentSolid: string;       // print-safe solid, e.g. "print:bg-violet-600"

  orgName: string;
  orgTaxNumber?: string | null;

  /* Meta grid */
  partyLabel: string;        // "Billed to" / "Returned to" / "Credited to"
  partyName: string;
  partyEmail?: string | null;
  partyTaxNumber?: string | null;
  metaRows: { label: string; value: string }[];

  /* Body */
  items: PrintDocItem[];
  itemsTitle?: string;       // defaults to "Items"
  quantityTitle?: string;    // defaults to "Qty"
  unitTitle?: string;        // defaults to "Unit price"

  totals: PrintDocTotals;

  notes?: string | null;
  notesTitle?: string;
  terms?: string | null;
  termsTitle?: string;
  footer?: ReactNode;
}

export const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "-";

/* Premium accents per module — same family, distinct hue per document
   type so a stack of printed pages reads module-identifiable. */
export const ACCENTS = {
  quotation: { gradient: "from-teal-600 to-emerald-600", solid: "print:bg-teal-600" },
  invoice: { gradient: "from-violet-600 to-indigo-600", solid: "print:bg-violet-600" },
  creditNote: { gradient: "from-rose-600 to-pink-600", solid: "print:bg-rose-600" },
  debitNote: { gradient: "from-amber-600 to-orange-600", solid: "print:bg-amber-600" },
  bill: { gradient: "from-sky-600 to-cyan-600", solid: "print:bg-sky-600" },
} as const;