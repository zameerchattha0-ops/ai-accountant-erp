"use client";

import { useCallback } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/lib/hooks/useOrg";
import { createClient } from "@/lib/supabase/client";
import DocShell from "@/components/print/DocShell";
import { buildBillDoc } from "@/components/print/build";
import type { PrintDoc } from "@/components/print/types";

/**
 * Premium printable PURCHASE BILL.
 * Route: /purchases/bills/[id] — sky letterhead, supplier party block,
 * paid/balance totals for vendor-bill print/PDF output.
 */
export default function PurchaseBillPrintPage() {
  const params = useParams<{ id: string }>();
  const { org } = useOrg();

  const load = useCallback(
    async (supabase: ReturnType<typeof createClient>): Promise<PrintDoc | null> => {
      const { data: b, error } = await supabase
        .from("purchase_bills")
        .select("*, supplier:suppliers(name, email, tax_number)")
        .eq("id", params.id)
        .single();
      if (error || !b) return null;
      const { data: items } = await supabase
        .from("purchase_bill_items")
        .select("*")
        .eq("bill_id", params.id)
        .order("line_number");
      return buildBillDoc(b, items ?? [], {
        orgName: org?.legal_name ?? org?.name ?? "Your Company",
        orgTaxNumber: org?.tax_number ?? null,
        partyLabel: "Supplier",
        party: b.supplier,
      });
    },
    [params.id, org],
  );

  return (
    <DocShell
      backHref="/purchases/bills"
      backLabel="Back to bills"
      load={load}
    />
  );
}