import type { Project } from "@/lib/types/entities";

/**
 * Pure decision helpers for the Projects page.
 *
 * Everything the page DERIVES (filtering, validation, the create/edit payload
 * and the preflight explanation of a would-be 409) lives here as plain
 * functions so a test can pin the behaviour without mounting React.
 *
 * The validation below is a MIRROR of ``app/services/project_service.py``
 * (``_clean_common``): the page shows the refusal BEFORE the round trip — but
 * the server never trusts this mirror, because the AI agent posts through the
 * very same service functions.
 */

/** The API carries the refusal text in ``detail`` — surface it verbatim. */
export { apiErrorMessage as messageOf } from "@/lib/api/errors";

/** The ``project_status`` enum (migration 001). */
export const PROJECT_STATUSES = [
  "PLANNING",
  "ACTIVE",
  "ON_HOLD",
  "COMPLETED",
  "CANCELLED",
] as const;

/** The ``billing_type_code`` enum; "" in the form means "not stated". */
export const BILLING_TYPES = [
  "FIXED_PRICE",
  "TIME_AND_MATERIALS",
  "RETAINER",
] as const;

/** The status filter's options, ALL first — mirrors the Fixed Assets page. */
export const STATUS_FILTERS: readonly string[] = ["ALL", ...PROJECT_STATUSES];

/** "ON_HOLD" → "on hold"; "" → "". */
export function humanise(code: string): string {
  return (code ?? "").replace(/_/g, " ").toLowerCase();
}

export interface ProjectFormValues {
  name: string;
  /** "" = no customer linked. */
  customer_id: string;
  status: string;
  /** "" = no billing type stated. */
  billing_type: string;
  start_date: string;
  end_date: string;
  budget: string;
  description: string;
}

export const EMPTY_PROJECT_FORM: ProjectFormValues = {
  name: "",
  customer_id: "",
  status: "PLANNING",
  billing_type: "",
  start_date: "",
  end_date: "",
  budget: "",
  description: "",
};

/** Load a register row into the edit form (dates trimmed to YYYY-MM-DD). */
export function projectFormFrom(project: Project): ProjectFormValues {
  return {
    name: project.name ?? "",
    customer_id: project.customer_id ?? "",
    status: project.status ?? "PLANNING",
    billing_type: project.billing_type ?? "",
    start_date: (project.start_date ?? "").slice(0, 10),
    end_date: (project.end_date ?? "").slice(0, 10),
    budget: project.budget != null ? String(project.budget) : "",
    description: project.description ?? "",
  };
}

/** The fields the filter/search reads — a structural subset of a register row. */
export interface ProjectSearchRow {
  name: string;
  project_code?: string | null;
  customer_name?: string | null;
  status: string;
}

/**
 * Search (name / code / customer) + status filter over the register rows.
 * Mirrors the backend's own narrowing so the page and the API agree on what a
 * search means.  Generic so it stays decoupled from ``ProjectRow`` (client.ts).
 */
export function filterProjects<T extends ProjectSearchRow>(
  items: T[],
  search: string,
  status: string
): T[] {
  const q = search.trim().toLowerCase();
  return items.filter((row) => {
    if (status !== "ALL" && row.status !== status) return false;
    if (!q) return true;
    return (
      row.name.toLowerCase().includes(q) ||
      (row.project_code ?? "").toLowerCase().includes(q) ||
      (row.customer_name ?? "").toLowerCase().includes(q)
    );
  });
}

/**
 * The rows the register table should show.
 *
 * Normally the loaded register IS the whole register, so filtering it in the
 * browser is instant AND complete — the best UX.  Only when the register is
 * TRUNCATED is the browser's copy incomplete (and so cannot answer the query);
 * then the server's debounced matches win, falling back to the loaded page
 * while they are in flight (never a blank list).
 */
export function visibleProjects<T extends ProjectSearchRow>(
  rows: T[],
  search: string,
  status: string,
  serverMatches: T[] | null,
  truncated: boolean
): T[] {
  if (truncated) return serverMatches ?? rows;
  return filterProjects(rows, search, status);
}

/**
 * Client-side mirror of the service's hard refusals — the first problem, or
 * null when the submission is acceptable.  Every returned sentence is the one
 * the server would have produced, so a user never learns a rule from a 409.
 */
export function projectFormBlocker(form: ProjectFormValues): string | null {
  if (form.name.trim().length < 2) {
    return "A project name is required (at least 2 characters).";
  }

  if (form.budget.trim()) {
    const budget = Number(form.budget);
    if (!Number.isFinite(budget)) {
      return "Project budget must be a number.";
    }
    if (budget < 0) {
      return "Project budget cannot be negative.";
    }
  }

  const dates: [string, string][] = [
    ["start", form.start_date],
    ["end", form.end_date],
  ];
  for (const [label, value] of dates) {
    if (value && !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      return `The ${label} date must be formatted YYYY-MM-DD.`;
    }
  }
  if (form.start_date && form.end_date && form.end_date < form.start_date) {
    return "The end date cannot be before the start date.";
  }

  if (
    form.status &&
    !(PROJECT_STATUSES as readonly string[]).includes(form.status)
  ) {
    return (
      `Unknown project status '${form.status}'. Use one of: ` +
      `${humanise(PROJECT_STATUSES.join(", "))}.`
    );
  }
  if (
    form.billing_type &&
    !(BILLING_TYPES as readonly string[]).includes(form.billing_type)
  ) {
    return (
      `Unknown billing type '${form.billing_type}'. Use one of: ` +
      `${humanise(BILLING_TYPES.join(", "))}.`
    );
  }
  return null;
}

/** The POST/PATCH body: trimmed strings, blanks as null, budget as a number. */
export interface ProjectPayloadValues {
  name: string;
  description: string | null;
  customer_id: string | null;
  status: string;
  billing_type: string | null;
  start_date: string | null;
  end_date: string | null;
  budget: number | null;
}

export function projectPayload(form: ProjectFormValues): ProjectPayloadValues {
  const budget = form.budget.trim();
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    customer_id: form.customer_id || null,
    status: form.status,
    billing_type: form.billing_type || null,
    start_date: form.start_date || null,
    end_date: form.end_date || null,
    // A blank budget means "no budget", never 0 (the service makes the same
    // distinction) — otherwise an unstated budget would silently read as zero.
    budget: budget === "" ? null : Number(budget),
  };
}

/**
 * True once the project has at least one posted journal line behind it.  Lets
 * the table distinguish "no postings yet" (—) from a genuine posted zero.
 */
export function hasPostings(row: { revenue: number; costs: number }): boolean {
  return row.revenue !== 0 || row.costs !== 0;
}

/**
 * How a P&L figure should read.  Three states, because "we could not load it"
 * must never look like "it earned nothing":
 *
 * * ``"unknown"`` — the profitability lookup failed (degraded register).
 * * ``"none"``    — no posted journal lines yet.
 * * ``"posted"``  — real numbers from posted lines.
 */
export type PnlState = "unknown" | "none" | "posted";

export function pnlState(
  row: { revenue: number; costs: number },
  profitabilityKnown: boolean
): PnlState {
  if (!profitabilityKnown) return "unknown";
  return hasPostings(row) ? "posted" : "none";
}

/** "40.0%" — or "—" when the view carried no margin (no revenue to divide by). */
export function formatMargin(percent: number | null | undefined): string {
  if (percent == null || !Number.isFinite(Number(percent))) return "—";
  return `${Number(percent).toFixed(1)}%`;
}

