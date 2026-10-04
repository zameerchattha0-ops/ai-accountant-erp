"use client";

/**
 * useServerList — the shared data engine behind every paginated list page.
 *
 * Guarantees (in priority order):
 * 1. NEVER ships the whole table: callers provide a `fetchPage` that queries
 *    one window (`.range`) with search/status applied by the database.
 * 2. Instant feel: the previous rows stay on screen while a new page/search
 *    loads (stale-while-revalidate) — no skeleton flash after first paint.
 * 3. Correctness under rapid input: every load gets an AbortSignal + a
 *    monotonic sequence; obsolete responses are dropped, not rendered (§19).
 * 4. Debounced search that resets to page 0, and filter changes that do the
 *    same — the user never lands on an empty page 7 of 3.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEFAULT_PAGE_SIZE,
  SEARCH_DEBOUNCE_MS,
  createSequencer,
  isAbortError,
} from "@/lib/lists/logic";

export interface ListPageResult<T> {
  rows: T[];
  /** Total matching rows (count: "exact"), or null when unavailable. */
  count: number | null;
}

export interface FetchPageArgs {
  page: number;
  pageSize: number;
  /** Debounced + sanitised by the caller's query builder. */
  search: string;
  signal: AbortSignal;
}

export type FetchPage<T> = (args: FetchPageArgs) => Promise<ListPageResult<T>>;

export interface UseServerListOptions<T> {
  /**
   * Loads ONE page. Identity may change every render (pages close over local
   * state) — the hook keeps it in a ref and never re-runs the load because of
   * it.
   */
  fetchPage: FetchPage<T>;
  /** Extra filter values (e.g. status). A change resets to page 0. */
  filters?: unknown[];
  pageSize?: number;
  debounceMs?: number;
  /** Hold the query (e.g. org not loaded yet). */
  enabled?: boolean;
}

export interface UseServerListResult<T> {
  /** null until the FIRST page arrives — matches the pages' skeleton logic. */
  rows: T[] | null;
  count: number;
  error: string | null;
  /** A load is in flight (subtle opacity, never a blank swap). */
  refreshing: boolean;
  search: string;
  setSearch: (value: string) => void;
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  /** Re-run the current query (after create/update/delete). */
  refresh: () => void;
}

export function useServerList<T>({
  fetchPage,
  filters,
  pageSize = DEFAULT_PAGE_SIZE,
  debounceMs = SEARCH_DEBOUNCE_MS,
  enabled = true,
}: UseServerListOptions<T>): UseServerListResult<T> {
  const [rows, setRows] = useState<T[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(0);
  const [refreshTick, setRefreshTick] = useState(0);

  // Latest fetchPage without making it a load dependency (it is an inline
  // closure in most pages and would otherwise re-fire the effect per render).
  const fetchRef = useRef(fetchPage);
  useEffect(() => {
    fetchRef.current = fetchPage;
  });

  // Monotonic load sequence — a response only lands if it is still the newest.
  const seqRef = useRef(createSequencer());

  // Debounce: keystrokes become ONE query, always from page 0.
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch((prev) => {
        if (prev === search) return prev;
        setPage(0);
        return search;
      });
    }, debounceMs);
    return () => clearTimeout(t);
  }, [search, debounceMs]);

  const filterKey = JSON.stringify(filters ?? []);

  useEffect(() => {
    if (!enabled) return;
    setPage((p) => (p === 0 ? p : 0));
  }, [filterKey, enabled]);

  // The load itself: one in flight at a time, abort + sequence on change.
  useEffect(() => {
    if (!enabled) return;
    const seq = seqRef.current.next();
    const controller = new AbortController();
    let alive = true;
    setRefreshing(true);

    fetchRef
      .current({ page, pageSize, search: debouncedSearch, signal: controller.signal })
      .then((res) => {
        if (!alive || !seqRef.current.isCurrent(seq)) return;
        // Deleted last row of a page / filter shrank: step back instead of
        // stranding the user on an empty page.
        if (page > 0 && res.rows.length === 0 && (res.count ?? 0) > 0) {
          setPage((p) => Math.max(0, Math.min(p, page - 1)));
          return;
        }
        setRows(res.rows);
        setCount(res.count ?? res.rows.length);
        setError(null);
      })
      .catch((err) => {
        if (!alive || !seqRef.current.isCurrent(seq)) return;
        if (isAbortError(err)) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (alive && seqRef.current.isCurrent(seq)) setRefreshing(false);
      });

    return () => {
      alive = false;
      controller.abort();
    };
  }, [enabled, page, debouncedSearch, refreshTick, pageSize, filterKey]);

  const refresh = useCallback(() => setRefreshTick((t) => t + 1), []);

  return {
    rows,
    count,
    error,
    refreshing,
    search,
    setSearch,
    page,
    setPage,
    pageSize,
    refresh,
  };
}
