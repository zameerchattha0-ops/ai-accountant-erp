import type {
  ClarificationRecord,
  ConfirmationRecord,
  SessionResult,
  SessionStep,
  SessionSummary,
  ToolCallRecord,
} from "@/lib/types/api";

/**
 * Pure decision helpers for the AI Activity page.
 *
 * Everything the feed DERIVES (filtering, the headline, durations, read/write
 * tool classification and the honesty of the result section) lives here as
 * plain functions so a test can pin the behaviour without mounting React.
 *
 * Nothing here invents data: a session row carries no title, summary or model
 * name, so every fallback below is an explicit "we don't have this" rather than
 * a fabricated value.
 */

/** The API carries the refusal text in ``detail`` — surface it verbatim. */
export { apiErrorMessage as messageOf } from "@/lib/api/errors";

/** ``ai.session_status_code`` (migration 026) — the filter and the counts. */
export const SESSION_STATUSES = [
  "PENDING",
  "PLANNING",
  "WAITING_FOR_USER",
  "EXECUTING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;

/** The status filter's options, ALL first — same shape as the other registers. */
export const STATUS_FILTERS: readonly string[] = ["ALL", ...SESSION_STATUSES];

/**
 * Statuses that are still moving.  ``WAITING_FOR_USER`` counts as active: the
 * run is genuinely parked on a human answer, and calling it finished would tell
 * the user their request is done when nothing will proceed without them.
 */
const ACTIVE_STATUSES = new Set([
  "PENDING",
  "PLANNING",
  "WAITING_FOR_USER",
  "EXECUTING",
]);

export function isActiveSession(status: string): boolean {
  return ACTIVE_STATUSES.has(String(status ?? "").toUpperCase());
}

/** "AWAITING_CLARIFICATION" → "awaiting clarification"; "" → "". */
export function humanise(code: string): string {
  return (code ?? "").replace(/_/g, " ").toLowerCase();
}

/**
 * What a session card must say.  `ai.execution_sessions` has NO title, summary
 * or action column — `user_request` (the sentence the user typed) is the only
 * human-meaningful text — so a blank one is reported as "Untitled request"
 * rather than rendered as an empty, unidentifiable card.
 */
export function sessionHeadline(session: SessionSummary): string {
  const raw = String(session.user_request ?? "").trim();
  return raw || "Untitled request";
}

/** Seconds the run took — null while running, or when a timestamp is missing. */
export function sessionDurationSeconds(
  session: SessionSummary
): number | null {
  const start = session.started_at || session.created_at;
  const end = session.completed_at;
  if (!start || !end) return null;
  const from = Date.parse(start);
  const to = Date.parse(end);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return null;
  return Math.round((to - from) / 1000);
}

/** "4s" / "2m 05s" / "1h 03m" — "—" when the run has no completed span. */
export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** "10 Oct 2026, 14:32" — "—" for a missing/unparseable stamp. */
export function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  const stamp = Date.parse(iso);
  if (!Number.isFinite(stamp)) return "—";
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(stamp));
}

/** The fields the search/status filter reads — a structural subset of a row. */
export interface ActivitySearchRow {
  user_request?: string | null;
  status: string;
}

/**
 * Search (what the user typed) + status filter over the loaded feed.
 * Mirrors the backend's own narrowing so the page and the API agree on what a
 * search means.  Generic so it stays decoupled from ``SessionSummary``.
 */
export function filterSessions<T extends ActivitySearchRow>(
  items: T[],
  search: string,
  status: string
): T[] {
  const q = search.trim().toLowerCase();
  return items.filter((row) => {
    if (status !== "ALL" && String(row.status ?? "").toUpperCase() !== status) {
      return false;
    }
    if (!q) return true;
    return String(row.user_request ?? "").toLowerCase().includes(q);
  });
}

/**
 * The rows the feed should show.
 *
 * Normally the loaded feed IS the whole feed, so filtering it in the browser is
 * instant AND complete — the best UX.  Only when the feed is TRUNCATED is the
 * browser's copy incomplete (and so cannot answer the query); then the server's
 * debounced matches win, falling back to the loaded page while they are in
 * flight (never a blank list).
 */
export function visibleSessions<T extends ActivitySearchRow>(
  rows: T[],
  search: string,
  status: string,
  serverMatches: T[] | null,
  truncated: boolean
): T[] {
  if (truncated) return serverMatches ?? rows;
  return filterSessions(rows, search, status);
}

/** Short, readable id fragment for a tool whose catalog row is missing. */
function shortId(value?: string | null): string {
  const raw = String(value ?? "");
  return raw.length > 8 ? raw.slice(0, 8) : raw;
}

/**
 * The name to show for a tool call.  `read_only` is false when the tool WROTE
 * to the user's books — the single most important distinction on this page —
 * but a missing catalog row must never be rendered as if it were read-only, so
 * an unknown call is labelled as an unknown tool.
 */
export function toolLabel(call: ToolCallRecord): string {
  const named = String(call.tool_name ?? "").trim();
  if (named) return named;
  const id = shortId(call.tool_id);
  return id ? `Tool ${id}` : "Unknown tool";
}

/** True only when we KNOW the call wrote. `null` (unresolved) is not a write. */
export function isWriteTool(call: ToolCallRecord): boolean {
  return call.tool_read_only === false;
}

export interface TrailCounts {
  steps: number;
  toolCalls: number;
  clarifications: number;
  confirmations: number;
  /** Tool calls that wrote to the books. */
  writes: number;
  /** Tool calls we KNOW only read. */
  reads: number;
  /** Tool calls whose catalog row could not be resolved. */
  unknown: number;
}

/** Headline counts for one run's trail (drives the chips and empty states). */
export function trailCounts(input: {
  steps?: SessionStep[] | null;
  tool_calls?: ToolCallRecord[] | null;
  clarifications?: ClarificationRecord[] | null;
  confirmations?: ConfirmationRecord[] | null;
}): TrailCounts {
  const toolCalls = input.tool_calls ?? [];
  return {
    steps: (input.steps ?? []).length,
    toolCalls: toolCalls.length,
    clarifications: (input.clarifications ?? []).length,
    confirmations: (input.confirmations ?? []).length,
    writes: toolCalls.filter(isWriteTool).length,
    reads: toolCalls.filter((call) => call.tool_read_only === true).length,
    unknown: toolCalls.filter((call) => call.tool_read_only == null).length,
  };
}

/**
 * What the result section can honestly claim — three states, because "we have
 * no result" means three very different things:
 *
 * * ``"recorded"`` — a result row exists (what changed / was it verified).
 * * ``"pending"``  — the run has not finished, so no result is expected yet.
 * * ``"missing"``  — the run is TERMINAL but no result row was written. That is
 *   a real gap the user should see, never a silent blank or an invented outcome.
 */
export type ResultState = "recorded" | "pending" | "missing";

export function resultState(
  session: SessionSummary,
  results: SessionResult | null | undefined
): ResultState {
  if (results) return "recorded";
  return isActiveSession(String(session.status ?? "")) ? "pending" : "missing";
}

