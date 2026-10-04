/**
 * Pure list-engine logic — server-side search / pagination helpers shared by
 * every list page and the party combobox.
 *
 * Convention (see lib/projects/logic.ts, lib/ai-activity/logic.ts): this file
 * contains NO React and NO supabase imports so the behaviour that decides what
 * the database is asked for is unit-testable on its own.
 */

/** Rows per initial viewport — 25 keeps a page inside one screen of rows. */
export const DEFAULT_PAGE_SIZE = 25;

/** Debounce before a keystroke becomes a database query (§8: ~150–300 ms). */
export const SEARCH_DEBOUNCE_MS = 250;

/**
 * Make a user's search string safe for PostgREST `or()` + ILIKE.
 *
 * - strips `(`, `)`, `,`, `'` — the characters that would break or() filter
 *   grammar or act as quoting (same trade-off the journal page documents);
 * - escapes ILIKE wildcards `\ % _` so a literal "50%" matches "50%",
 *   never "anything";
 * - collapses whitespace and trims.
 */
export function sanitizeSearch(raw: string): string {
  return raw
    .replace(/[()',]/g, " ")
    .replace(/([\\%_])/g, "\\$1")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Build the `or(...)` expression that matches *q* against any of *columns*
 * (case-insensitive substring). Returns "" when the search is empty after
 * sanitising so callers can skip the filter entirely.
 *
 * Columns are code-provided constants; *q* is always sanitised here, never
 * interpolated raw.
 */
export function ilikeAny(columns: string[], q: string): string {
  const s = sanitizeSearch(q);
  if (!s) return "";
  return columns.map((c) => `${c}.ilike.%${s}%`).join(",");
}

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidUuid(value: string): boolean {
  return UUID_RE.test(value);
}

/**
 * The `or(...)` expression for a DOCUMENT list: root columns (numbers,
 * references) OR membership in a bounded set of party ids that matched the
 * search on the parties table.
 *
 * PostgREST cannot OR a root column with an embedded column in one filter, so
 * pages resolve party matches first (bounded, indexed) and pass the ids here.
 * Non-uuid ids are dropped — ids are never trusted as raw filter syntax.
 */
export function documentOrFilter(
  columns: string[],
  partyIdColumn: string,
  q: string,
  partyIds: string[]
): string {
  const parts: string[] = [];
  const base = ilikeAny(columns, q);
  if (base) parts.push(base);
  const ids = partyIds.filter((id) => typeof id === "string" && isValidUuid(id));
  if (ids.length > 0) parts.push(`${partyIdColumn}.in.(${ids.join(",")})`);
  return parts.join(",");
}

export interface PageRange {
  /** Total rows matching the current filters. */
  total: number;
  /** 1-based first row on the page (0 when there are no rows). */
  from: number;
  /** 1-based last row on the page (0 when there are no rows). */
  to: number;
  totalPages: number;
  hasPrev: boolean;
  hasNext: boolean;
}

/** Window + navigation math for a paged list. Never throws on empty lists. */
export function pageRange(page: number, pageSize: number, total: number): PageRange {
  const size = Math.max(1, Math.floor(pageSize));
  const count = Math.max(0, Math.floor(total));
  const totalPages = Math.max(1, Math.ceil(count / size));
  const current = Math.min(Math.max(0, Math.floor(page)), totalPages - 1);
  return {
    total: count,
    from: count === 0 ? 0 : current * size + 1,
    to: Math.min(count, current * size + size),
    totalPages,
    hasPrev: current > 0,
    hasNext: current < totalPages - 1,
  };
}

/** "1–25 of 342" — the range label under a paged table. */
export function rangeLabel(range: PageRange): string {
  if (range.to === 0) return "0 of 0";
  return `${range.from.toLocaleString()}–${range.to.toLocaleString()} of ${range.total.toLocaleString()}`;
}

/**
 * True when *err* is a request the client itself cancelled (AbortController).
 * Aborts are control flow, never user-facing errors.
 */
export function isAbortError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as { name?: unknown; code?: unknown };
  if (e.name === "AbortError") return true;
  // DOMException.ABORT_ERR is code 20; some wrappers pass it through.
  if (e.code === "ABORT_ERR" || e.code === 20) return true;
  return false;
}

/**
 * Monotonic request sequence — a response is applied ONLY when its sequence
 * is still the newest one issued. Pair with AbortController so an obsolete
 * search can never overwrite a newer one (§19).
 */
export function createSequencer() {
  let current = 0;
  return {
    next(): number {
      current += 1;
      return current;
    },
    isCurrent(seq: number): boolean {
      return seq === current;
    },
    current(): number {
      return current;
    },
  };
}

/**
 * Session-scoped "recent picks" ring — lets a combobox offer the parties the
 * user actually chose lately instead of an arbitrary slice of the table (§21).
 */
export function createRecentList(capacity = 5) {
  const size = Math.max(1, capacity);
  let ids: string[] = [];
  return {
    push(id: string): void {
      if (!id) return;
      ids = [id, ...ids.filter((x) => x !== id)].slice(0, size);
    },
    list(): string[] {
      return [...ids];
    },
    remove(id: string): void {
      ids = ids.filter((x) => x !== id);
    },
    clear(): void {
      ids = [];
    },
  };
}
