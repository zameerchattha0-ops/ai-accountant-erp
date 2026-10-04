/**
 * Payments / Receipts KPI totals — ONE indexed SQL pass via migration 089,
 * with a correct-but-heavier fallback for the window before that migration
 * is applied.
 *
 * Why this exists (UX audit B6/D4): the tiles used to reduce EVERY row that
 * the list page had fetched, which both shipped the whole table to the
 * browser and made paginating the list impossible without lying about the
 * money. Totals now come from `get_payment_summary` / `get_receipt_summary`
 * (single aggregate) — or, pre-migration, from a BOUNDED chunked scan over
 * narrow columns (status, amount[, is_transfer]) that pages 1000 rows at a
 * time instead of one giant payload.
 *
 * If even the scan hits its safety cap, `degraded` is true and callers must
 * show "—" rather than a partial number (same contract as the projects
 * register's `degraded` flag).
 */

import type { SupabaseClient } from "@supabase/supabase-js";

export interface PartyTotals {
  /** Completed money in (receipts) / out (payments, excluding transfers). */
  paid: number;
  /** Money still pending. */
  pending: number;
  /** Row count for the "Total" tile. */
  count: number;
  /** "rpc" = aggregate SQL; "scan" = chunked fallback (pre-migration). */
  source: "rpc" | "scan";
  /** True when the fallback hit SCAN_MAX_ROWS — tiles must show "—". */
  degraded: boolean;
}

export const SCAN_PAGE_SIZE = 1000;
/** Safety valve for the pre-migration scan (~100k rows ≈ 100 chunked calls). */
export const SCAN_MAX_ROWS = 100_000;

/** Pure reduction over narrow payment rows (fallback path + unit tests). */
export function summarizeRows(
  rows: { status: string; amount: number | string; is_transfer?: boolean | null }[],
  opts: { countTransfersInPaid?: boolean } = {}
): { paid: number; pending: number; count: number } {
  let paid = 0;
  let pending = 0;
  for (const r of rows) {
    const amount = Number(r.amount) || 0;
    if (r.status === "COMPLETED" && (opts.countTransfersInPaid || !r.is_transfer)) {
      paid += amount;
    } else if (r.status === "PENDING") {
      pending += amount;
    }
  }
  return { paid, pending, count: rows.length };
}

type Kind = "payment" | "receipt";

interface SummaryRow {
  total_paid?: number | string;
  total_received?: number | string;
  total_pending?: number | string;
  total?: number | string;
}

async function chunkedScan(
  supabase: SupabaseClient,
  orgId: string,
  kind: Kind,
  signal?: AbortSignal
): Promise<PartyTotals> {
  const table = kind === "payment" ? "payments" : "receipts";
  const narrow =
    kind === "payment" ? "status, amount, is_transfer" : "status, amount";
  let offset = 0;
  const rows: { status: string; amount: number; is_transfer?: boolean | null }[] = [];
  let truncated = false;

  for (;;) {
    const want = Math.min(SCAN_PAGE_SIZE, SCAN_MAX_ROWS - offset);
    let query = supabase
      .from(table)
      .select(narrow)
      .eq("organization_id", orgId)
      .order("id", { ascending: true })
      .range(offset, offset + want - 1);
    if (signal) query = query.abortSignal(signal);
    const { data, error } = await query;
    if (error) throw error;
    const page = (data ?? []) as unknown as {
      status: string;
      amount: number;
      is_transfer?: boolean | null;
    }[];
    rows.push(...page);
    if (page.length < want) break;
    offset += page.length;
    if (offset >= SCAN_MAX_ROWS) {
      truncated = true;
      break;
    }
  }

  const sums = summarizeRows(rows, {
    countTransfersInPaid: kind === "receipt",
  });
  return {
    paid: sums.paid,
    pending: sums.pending,
    count: rows.length,
    source: "scan",
    degraded: truncated,
  };
}

/**
 * KPI totals for a payment/receipt list. Throws only on real failures —
 * callers treat an abort as "do not render" (isAbortError).
 */
export async function loadPartyTotals(
  supabase: SupabaseClient,
  orgId: string,
  kind: Kind,
  signal?: AbortSignal
): Promise<PartyTotals> {
  const fn = kind === "payment" ? "get_payment_summary" : "get_receipt_summary";
  let rpc = supabase.rpc(fn, { target_org: orgId });
  if (signal) rpc = rpc.abortSignal(signal);
  const { data, error } = await rpc;

  if (!error && Array.isArray(data) && data.length > 0) {
    const row = (data[0] as SummaryRow) ?? {};
    const paid =
      kind === "payment"
        ? Number(row.total_paid ?? 0)
        : Number(row.total_received ?? 0);
    return {
      paid,
      pending: Number(row.total_pending ?? 0),
      count: Number(row.total ?? 0),
      source: "rpc",
      degraded: false,
    };
  }

  // Migration 089 not applied yet (function missing) → bounded fallback.
  // Any OTHER rpc failure still falls through to the scan: correct values
  // matter more than a fast failure here.
  return chunkedScan(supabase, orgId, kind, signal);
}
