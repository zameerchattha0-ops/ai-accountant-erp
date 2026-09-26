"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Printer, Check } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import { cn } from "@/lib/utils/cn";
import StatusBadge from "@/components/shared/StatusBadge";
import { ErrorState, TableSkeleton } from "@/components/shared/States";
import NoteTemplate, {
  type NoteVariant,
} from "@/components/notes/NoteTemplates";
import type { Supplier } from "@/lib/types/entities";

const TEMPLATES: { id: NoteVariant; label: string }[] = [
  { id: "modern", label: "Modern" },
  { id: "professional", label: "Professional" },
  { id: "minimal", label: "Minimal" },
];

interface DebitNoteDoc {
  id: string;
  return_number: string;
  return_date: string;
  status: string;
  reason: string | null;
  subtotal: number;
  tax_total: number;
  total: number;
  currency_code: string | null;
  journal_entry_id: string | null;
  supplier_id: string | null;
  bill_id: string | null;
}

interface NoteItemRow {
  id: string;
  description: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

interface PageData {
  note: DebitNoteDoc;
  items: NoteItemRow[];
  supplier: Supplier | null;
  reference: string | null;
}

export default function DebitNoteDetailPage() {
  const params = useParams<{ id: string }>();
  const { org } = useOrg();
  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [template, setTemplate] = useState<NoteVariant>("modern");
  const [updating, setUpdating] = useState(false);

  const load = useCallback(async () => {
    const supabase = createClient();
    const { data: note, error: noteError } = await supabase
      .from("purchase_returns")
      .select("*")
      .eq("id", params.id)
      .single();
    if (noteError || !note) {
      setError(noteError?.message ?? "Debit note not found");
      return;
    }
    const { data: items } = await supabase
      .from("purchase_return_items")
      .select("*")
      .eq("return_id", params.id)
      .order("line_number");
    const { data: suppliers } = note.supplier_id
      ? await supabase
          .from("suppliers")
          .select("*")
          .eq("id", note.supplier_id)
          .limit(1)
      : { data: [] };
    let reference: string | null = null;
    if (note.bill_id) {
      const { data: bill } = await supabase
        .from("purchase_bills")
        .select("bill_number")
        .eq("id", note.bill_id)
        .limit(1);
      reference = bill?.[0]?.bill_number ?? null;
    }
    setData({
      note: note as DebitNoteDoc,
      items: (items ?? []) as NoteItemRow[],
      supplier: (suppliers?.[0] as Supplier) ?? null,
      reference,
    });
  }, [params.id]);

  useEffect(() => { load(); }, [load]);

  // Default template from org settings (same preference as invoices).
  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase
      .from("organization_settings")
      .select("settings")
      .eq("organization_id", org.organization_id)
      .limit(1)
      .then(({ data }) => {
        const preferred = (data?.[0]?.settings as Record<string, unknown> | null)
          ?.invoice_template;
        if (preferred && TEMPLATES.some((t) => t.id === preferred)) {
          setTemplate(preferred as NoteVariant);
        }
      });
  }, [org]);

  const updateStatus = async (status: "OPEN" | "VOIDED") => {
    if (!data) return;
    setUpdating(true);
    const supabase = createClient();
    const { error: updError } = await supabase
      .from("purchase_returns")
      .update({ status })
      .eq("id", data.note.id);
    setUpdating(false);
    if (updError) setError(updError.message);
    else await load();
  };

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) {
    return (
      <div className="max-w-6xl mx-auto space-y-4">
        <TableSkeleton rows={8} cols={4} />
      </div>
    );
  }

  const { note, items, supplier, reference } = data;
  const formatAmount = (n: number) =>
    formatCurrency(n, note.currency_code ?? org?.base_currency_code);

  return (
    <div className="max-w-4xl mx-auto space-y-5 print:space-y-0">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 print:hidden">
        <Link
          href="/purchases/returns"
          className="text-sm text-ai-600 hover:text-ai-700 flex items-center gap-1.5"
        >
          <ArrowLeft className="w-4 h-4" /> Back to debit notes
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center rounded-xl bg-bg-surface border border-border-subtle p-0.5">
            {TEMPLATES.map((t) => (
              <button
                key={t.id}
                onClick={() => setTemplate(t.id)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                  template === t.id
                    ? "bg-ai-500 text-white"
                    : "text-text-secondary hover:text-text-primary"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-bg-surface border border-border-subtle text-sm font-medium text-text-secondary hover:text-text-primary hover:border-ai-200 transition-colors"
          >
            <Printer className="w-4 h-4" /> Print / PDF
          </button>
          {note.status === "DRAFT" && (
            <>
              <button
                onClick={() => updateStatus("OPEN")}
                disabled={updating}
                className="flex items-center gap-1.5 px-3.5 py-2 btn-3d btn-shine rounded-xl bg-success-600 hover:bg-success-700 text-white text-sm font-medium disabled:opacity-50 transition-colors"
              >
                <Check className="w-4 h-4" /> Open
              </button>
              <button
                onClick={() => updateStatus("VOIDED")}
                disabled={updating}
                className="px-3.5 py-2 rounded-xl bg-bg-surface border border-error-200 text-sm font-medium text-error-600 hover:bg-error-50 disabled:opacity-50 transition-colors"
              >
                Void
              </button>
            </>
          )}
          {note.status === "OPEN" && (
            <button
              onClick={() => updateStatus("VOIDED")}
              disabled={updating}
              className="px-3.5 py-2 rounded-xl bg-bg-surface border border-error-200 text-sm font-medium text-error-600 hover:bg-error-50 disabled:opacity-50 transition-colors"
            >
              Void
            </button>
          )}
        </div>
      </div>

      {/* Status strip */}
      <div className="flex items-center gap-2 print:hidden">
        <StatusBadge status={note.status} />
        <span className="text-xs text-text-muted">
          {note.status === "DRAFT"
            ? "Draft — open to finalize. The reversal journal posts through the AI agent for double-entry integrity."
            : `Journal entry: ${note.journal_entry_id ? "linked" : "not yet posted"}`}
        </span>
      </div>

      {/* Template render */}
      <NoteTemplate
        kind="debit"
        variant={template}
        note={{
          number: note.return_number,
          date: note.return_date,
          status: note.status,
          reason: note.reason,
          subtotal: Number(note.subtotal),
          discount_total: 0,
          tax_total: Number(note.tax_total),
          total: Number(note.total),
          reference,
        }}
        items={items}
        party={supplier}
        org={org ?? null}
        formatAmount={formatAmount}
      />
    </div>
  );
}
