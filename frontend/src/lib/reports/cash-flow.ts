/**
 * Cash Flow statement data layer.
 *
 * The old page issued ONE query with `.limit(500)` and summed whatever came
 * back — silently wrong category totals and net cash flow for any
 * organisation with more than 500 cash movements (audit B3, P0). This module
 * fixes that with three guarantees:
 *
 * 1. Totals come from `get_cash_flow_summary` (migration 090) — one grouped
 *    SQL pass over any volume. Until that migration is applied, totals fall
 *    back to summing the loaded rows, but ONLY while the load is complete.
 * 2. The movement list is fetched in bounded 1000-row chunks (PostgREST caps
 *    a single response) up to MAX_ROWS — no silent 500-row cut.
 * 3. Hitting MAX_ROWS sets `truncated`; the page must say so and must refuse
 *    to display fallback totals it cannot trust.
 */

import type { SupabaseClient } from "@supabase/supabase-js";

export const CHUNK_SIZE = 1000;
/** Safety ceiling for the statement list (20 chunked requests at most). */
export const MAX_ROWS = 20_000;

export type CashCategory = "OPERATING" | "INVESTING" | "FINANCING";

export interface CategoryTotals {
  OPERATING: number;
  INVESTING: number;
  FINANCING: number;
}

/** One row of v_cash_flow as the statement renders it. */
export interface CashFlowRow {
  organization_id: string;
  transaction_date: string;
  journal_entry_id: string;
  journal_number: string;
  source_type: string | null;
  cash_flow_category: CashCategory;
  cash_account_id: string;
  cash_account_code: string;
  cash_account_name: string;
  contra_account_id: string;
  contra_account_code: string;
  contra_account_name: string;
  net_amount: number | string;
  entry_description: string | null;
}

const COLUMNS =
  "organization_id, transaction_date, journal_entry_id, journal_number, source_type, cash_flow_category, cash_account_id, cash_account_code, cash_account_name, contra_account_id, contra_account_code, contra_account_name, net_amount, entry_description";

export const EMPTY_TOTALS: CategoryTotals = {
  OPERATING: 0,
  INVESTING: 0,
  FINANCING: 0,
};

/** Pure reduction used as the pre-migration fallback (unit-tested). */
export function computeCategoryTotals(
  rows: { cash_flow_category: string; net_amount: number | string }[]
): CategoryTotals {
  const totals: CategoryTotals = { ...EMPTY_TOTALS };
  for (const r of rows) {
    const key = r.cash_flow_category;
    if (key === "OPERATING" || key === "INVESTING" || key === "FINANCING") {
      totals[key] += Number(r.net_amount) || 0;
    }
  }
  return totals;
}

export function netOf(totals: CategoryTotals): number {
  return totals.OPERATING + totals.INVESTING + totals.FINANCING;
}

/**
 * Fetch the statement movements for an optional period, in stable date order,
 * chunked so a PostgREST row cap can never silently truncate the result —
 * `truncated: true` is reported instead.
 */
export async function fetchCashFlowRows(
  supabase: SupabaseClient,
  organizationId: string,
  opts: { from?: string | null; to?: string | null; signal?: AbortSignal } = {}
): Promise<{ rows: CashFlowRow[]; truncated: boolean }> {
  const rows: CashFlowRow[] = [];
  let offset = 0;

  for (;;) {
    const want = Math.min(CHUNK_SIZE, MAX_ROWS - offset);
    let query = supabase
      .from("v_cash_flow")
      .select(COLUMNS)
      .eq("organization_id", organizationId)
      // Deterministic order so chunk boundaries are reproducible.
      .order("transaction_date", { ascending: false })
      .order("journal_number", { ascending: false })
      .order("cash_account_id", { ascending: true })
      .order("contra_account_id", { ascending: true })
      .range(offset, offset + want - 1);
    if (opts.from) query = query.gte("transaction_date", opts.from);
    if (opts.to) query = query.lte("transaction_date", opts.to);
    if (opts.signal) query = query.abortSignal(opts.signal);

    const { data, error } = await query;
    if (error) throw error;
    const page = (data ?? []) as unknown as CashFlowRow[];
    rows.push(...page);
    if (page.length < want) return { rows, truncated: false };
    offset += page.length;
    if (offset >= MAX_ROWS) return { rows, truncated: true };
  }
}

/**
 * Exact category totals for the period — one SQL aggregate via migration 090.
 * Returns null when the function is not available (migration not applied);
 * callers then fall back to `computeCategoryTotals(loadedRows)` only when the
 * load was complete.
 */
export async function loadCashFlowSummary(
  supabase: SupabaseClient,
  organizationId: string,
  opts: { from?: string | null; to?: string | null; signal?: AbortSignal } = {}
): Promise<CategoryTotals | null> {
  let rpc = supabase.rpc("get_cash_flow_summary", {
    target_org: organizationId,
    p_from: opts.from ?? null,
    p_to: opts.to ?? null,
  });
  if (opts.signal) rpc = rpc.abortSignal(opts.signal);
  const { data, error } = await rpc;
  if (error || !Array.isArray(data)) return null;

  const totals: CategoryTotals = { ...EMPTY_TOTALS };
  for (const row of data as { category: string; total: number | string }[]) {
    if (
      row.category === "OPERATING" ||
      row.category === "INVESTING" ||
      row.category === "FINANCING"
    ) {
      totals[row.category] = Number(row.total) || 0;
    }
  }
  return totals;
}
