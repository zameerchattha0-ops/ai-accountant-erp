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
import InvoiceTemplateModern from "@/components/invoices/InvoiceTemplateModern";
import InvoiceTemplateProfessional from "@/components/invoices/InvoiceTemplateProfessional";
import InvoiceTemplateMinimal from "@/components/invoices/InvoiceTemplateMinimal";
import type { Customer, Invoice, InvoiceItem, InvoiceTemplateId } from "@/lib/types/entities";

const TEMPLATES: { id: InvoiceTemplateId; label: string }[] = [
  { id: "modern", label: "Modern" },
  { id: "professional", label: "Professional" },
  { id: "minimal", label: "Minimal" },
];

interface PageData {
  invoice: Invoice;
  items: InvoiceItem[];
  customer: Customer | null;
}

export default function InvoiceDetailPage() {
  const params = useParams<{ id: string }>();
  const { org } = useOrg();
  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [template, setTemplate] = useState<InvoiceTemplateId>("modern");
  const [updating, setUpdating] = useState(false);

  const load = useCallback(async () => {
    const supabase = createClient();
    const { data: invoice, error: invError } = await supabase
      .from("invoices")
      .select("*")
      .eq("id", params.id)
      .single();
    if (invError || !invoice) {
      setError(invError?.message ?? "Invoice not found");
      return;
    }
    const { data: items } = await supabase
      .from("invoice_items")
      .select("*")
      .eq("invoice_id", params.id)
      .order("line_number");
    const { data: customers } = await supabase
      .from("customers")
      .select("*")
      .eq("id", invoice.customer_id)
      .limit(1);
    setData({ invoice, items: items ?? [], customer: customers?.[0] ?? null });
  }, [params.id]);

  useEffect(() => { load(); }, [load]);

  // Default template from org settings (per-view override below)
  useEffect(() => {
    if (!org) return;
    const supabase = createClient();
    supabase
      .from("organization_settings")
      .select("settings")
      .eq("organization_id", org.organization_id)
      .limit(1)
      .then(({ data }) => {
        const preferred = (data?.[0]?.settings as Record<string, unknown> | null)?.invoice_template;
        if (preferred && TEMPLATES.some((t) => t.id === preferred)) {
          setTemplate(preferred as InvoiceTemplateId);
        }
      });
  }, [org]);

  const updateStatus = async (status: "ISSUED" | "VOIDED") => {
    if (!data) return;
    setUpdating(true);
    const supabase = createClient();
    const patch: Partial<Invoice> =
      status === "ISSUED"
        ? { status, sent_at: new Date().toISOString() }
        : { status, voided_at: new Date().toISOString() };
    const { error: updError } = await supabase
      .from("invoices")
      .update(patch)
      .eq("id", data.invoice.id);
    setUpdating(false);
    if (updError) setError(updError.message);
    else load();
  };

  if (error) {
    return (
      <div className="max-w-6xl mx-auto space-y-4">
        <Link href="/sales/invoices" className="text-sm text-ai-600 hover:text-ai-700 flex items-center gap-1.5">
          <ArrowLeft className="w-4 h-4" /> Back to invoices
        </Link>
        <ErrorState message={error} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-6xl mx-auto space-y-4">
        <TableSkeleton rows={8} cols={4} />
      </div>
    );
  }

  const { invoice, items, customer } = data;
  const formatAmount = (n: number) => formatCurrency(n, invoice.currency_code);

  const templateProps = {
    invoice,
    items,
    customer,
    org: org ?? null,
    formatAmount,
  };

  return (
    <div className="max-w-4xl mx-auto space-y-5 print:space-y-0">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 print:hidden">
        <Link href="/sales/invoices" className="text-sm text-ai-600 hover:text-ai-700 flex items-center gap-1.5">
          <ArrowLeft className="w-4 h-4" /> Back to invoices
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          {/* Template switcher */}
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
          {invoice.status === "DRAFT" && (
            <>
              <button
                onClick={() => updateStatus("ISSUED")}
                disabled={updating}
                className="flex items-center gap-1.5 px-3.5 py-2 btn-3d btn-shine rounded-xl bg-success-600 hover:bg-success-700 text-white text-sm font-medium disabled:opacity-50 transition-colors"
              >
                <Check className="w-4 h-4" /> Issue
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
        </div>
      </div>

      {/* Status strip */}
      <div className="flex items-center gap-2 print:hidden">
        <StatusBadge status={invoice.status} />
        <span className="text-xs text-text-muted">
          {invoice.status === "DRAFT"
            ? "Draft - issue to finalize. Journal posting runs through the AI agent for double-entry integrity."
            : `Journal entry: ${invoice.journal_entry_id ? "linked" : "not yet posted"}`}
        </span>
      </div>

      {/* Template render */}
      {template === "modern" && <InvoiceTemplateModern {...templateProps} />}
      {template === "professional" && <InvoiceTemplateProfessional {...templateProps} />}
      {template === "minimal" && <InvoiceTemplateMinimal {...templateProps} />}
    </div>
  );
}
