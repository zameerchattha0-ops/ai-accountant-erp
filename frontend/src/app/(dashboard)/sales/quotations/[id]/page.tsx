"use client";

import { useCallback } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/lib/hooks/useOrg";
import { createClient } from "@/lib/supabase/client";
import DocShell from "@/components/print/DocShell";
import { buildQuotationDoc } from "@/components/print/build";
import type { PrintDoc } from "@/components/print/types";

/**
 * Premium printable QUOTATION.
 * Route: /sales/quotations/[id] — letterhead-quality output for print/PDF.
 */
export default function QuotationPrintPage() {
  const params = useParams<{ id: string }>();
  const { org } = useOrg();

  const load = useCallback(
    async (supabase: ReturnType<typeof createClient>): Promise<PrintDoc | null> => {
      const { data: q, error } = await supabase
        .from("quotations")
        .select("*, customer:customers(name, email, tax_number)")
        .eq("id", params.id)
        .single();
      if (error || !q) return null;
      const { data: items } = await supabase
        .from("quotation_items")
        .select("*")
        .eq("quotation_id", params.id)
        .order("line_number");
      return buildQuotationDoc(q, items ?? [], {
        orgName: org?.legal_name ?? org?.name ?? "Your Company",
        orgTaxNumber: org?.tax_number ?? null,
        partyLabel: "Prepared for",
        party: q.customer,
      });
    },
    [params.id, org],
  );

  return (
    <DocShell
      backHref="/sales/quotations"
      backLabel="Back to quotations"
      load={load}
    />
  );
}