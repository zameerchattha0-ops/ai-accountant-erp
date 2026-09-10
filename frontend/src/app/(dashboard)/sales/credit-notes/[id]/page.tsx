"use client";

import { useCallback } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/lib/hooks/useOrg";
import { createClient } from "@/lib/supabase/client";
import DocShell from "@/components/print/DocShell";
import { buildCreditNoteDoc } from "@/components/print/build";
import type { PrintDoc } from "@/components/print/types";

/**
 * Premium printable CREDIT NOTE.
 * Route: /sales/credit-notes/[id] — rose letterhead, "Credited to" party,
 * reason-forward layout for refunds/discounts/corrections.
 */
export default function CreditNotePrintPage() {
  const params = useParams<{ id: string }>();
  const { org } = useOrg();

  const load = useCallback(
    async (supabase: ReturnType<typeof createClient>): Promise<PrintDoc | null> => {
      const { data: cn, error } = await supabase
        .from("credit_notes")
        .select("*, customer:customers(name, email, tax_number)")
        .eq("id", params.id)
        .single();
      if (error || !cn) return null;
      const { data: items } = await supabase
        .from("credit_note_items")
        .select("*")
        .eq("credit_note_id", params.id)
        .order("line_number");
      return buildCreditNoteDoc(cn, items ?? [], {
        orgName: org?.legal_name ?? org?.name ?? "Your Company",
        orgTaxNumber: org?.tax_number ?? null,
        partyLabel: "Credited to",
        party: cn.customer,
      });
    },
    [params.id, org],
  );

  return (
    <DocShell
      backHref="/sales/credit-notes"
      backLabel="Back to credit notes"
      load={load}
    />
  );
}