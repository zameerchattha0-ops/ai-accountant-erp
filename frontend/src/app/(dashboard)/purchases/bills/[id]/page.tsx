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

      const refIds = [b.source_grn_id, b.source_po_id, b.source_rfq_id].filter(
        (x): x is string => Boolean(x)
      );
      const refMap = new Map<string, string>();
      if (refIds.length > 0 && org) {
        const { data: poRefs } = await supabase
          .from("purchase_orders")
          .select("id, po_number")
          .eq("organization_id", org.organization_id)
          .in("id", refIds);
        for (const r of (poRefs ?? []) as { id: string; po_number: string }[]) {
          refMap.set(r.id, r.po_number);
        }
      }
      const enrichedBill = {
        ...b,
        source_grn_number: b.source_grn_id ? refMap.get(b.source_grn_id) ?? null : null,
        source_po_number: b.source_po_id ? refMap.get(b.source_po_id) ?? null : null,
        source_rfq_number: b.source_rfq_id ? refMap.get(b.source_rfq_id) ?? null : null,
      };
      return buildBillDoc(enrichedBill, items ?? [], {
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