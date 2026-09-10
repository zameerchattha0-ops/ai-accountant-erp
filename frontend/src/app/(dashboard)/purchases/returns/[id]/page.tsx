"use client";

import { useCallback } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/lib/hooks/useOrg";
import { createClient } from "@/lib/supabase/client";
import DocShell from "@/components/print/DocShell";
import { buildDebitNoteDoc } from "@/components/print/build";
import type { PrintDoc } from "@/components/print/types";

/**
 * Premium printable DEBIT NOTE (purchase return).
 * Route: /purchases/returns/[id] — amber letterhead, "Debited to
 * (supplier)" party, reason-forward layout for goods returned.
 */
export default function DebitNotePrintPage() {
  const params = useParams<{ id: string }>();
  const { org } = useOrg();

  const load = useCallback(
    async (supabase: ReturnType<typeof createClient>): Promise<PrintDoc | null> => {
      const { data: r, error } = await supabase
        .from("purchase_returns")
        .select("*, supplier:suppliers(name, email, tax_number)")
        .eq("id", params.id)
        .single();
      if (error || !r) return null;
      const { data: items } = await supabase
        .from("purchase_return_items")
        .select("*")
        .eq("return_id", params.id)
        .order("line_number");
      return buildDebitNoteDoc(r, items ?? [], {
        orgName: org?.legal_name ?? org?.name ?? "Your Company",
        orgTaxNumber: org?.tax_number ?? null,
        partyLabel: "Debited to (supplier)",
        party: r.supplier,
      });
    },
    [params.id, org],
  );

  return (
    <DocShell
      backHref="/purchases/returns"
      backLabel="Back to purchase returns"
      load={load}
    />
  );
}