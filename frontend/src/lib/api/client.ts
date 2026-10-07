import type { AgentResponse, UserRequest, ClarificationAnswer, ConfirmationDecision, ActivityFeed, SessionBundle, AgentProgress, OnboardingSchema, OnboardingAnalysis, OnboardingAnswer } from "@/lib/types/api";
import type { AssetCategory, FixedAsset, Project } from "@/lib/types/entities";

// Same-origin by default: on Vercel the FastAPI backend is served under
// /api/* of the same domain (see vercel.json "services"). For local dev set
// NEXT_PUBLIC_API_URL=http://localhost:8000 in frontend/.env.local.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Get JWT from Supabase session (stored in cookie)
  const { createClient } = await import("@/lib/supabase/client");
  const supabase = createClient();

  async function doFetch<T>(): Promise<T> {
    const { data: { session } } = await supabase.auth.getSession();
    const token = session?.access_token;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string> || {}),
    };

    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (!res.ok) {
      const body = await res.text();
      throw new ApiError(res.status, body || res.statusText);
    }

    return res.json();
  }

  try {
    return await doFetch<T>();
  } catch (err) {
    // A 401 from the API almost always means the browser held a stale
    // access token (e.g. signed by a rotated JWT signing key). supabase-js
    // does NOT proactively refresh a still-unexpired token, so force one
    // refresh and retry exactly once. Security is unchanged: the retry still
    // carries a freshly issued Supabase session token.
    const is401 = err instanceof ApiError && err.status === 401;
    if (!is401) throw err;
    const { data } = await supabase.auth.refreshSession();
    if (!data.session) throw err;
    return doFetch<T>();
  }
}

/* ---- AI Endpoints ---- */

export async function aiExecute(request: UserRequest): Promise<AgentResponse> {
  return fetchApi<AgentResponse>("/api/ai/execute", {
    method: "POST",
    body: JSON.stringify(request),
  });
}
export async function aiClarify(answer: ClarificationAnswer): Promise<AgentResponse> {
  return fetchApi<AgentResponse>("/api/ai/clarify", {
    method: "POST",
    body: JSON.stringify(answer),
  });
}

export async function aiConfirm(decision: ConfirmationDecision): Promise<AgentResponse> {
  return fetchApi<AgentResponse>("/api/ai/confirm", {
    method: "POST",
    body: JSON.stringify(decision),
  });
}

/**
 * This user's AI-activity feed.
 *
 * `counts` and `total` always cover the WHOLE loaded feed; `query` and `status`
 * narrow `items` only — so a filter can never make the counts beside it lie.
 *
 * The default page is BOUNDED (production request 2026-10-08 "remove extra
 * load"): real feeds sit far below it, so the common load is one small
 * response — and beyond it the API's honest `truncated` flag already switches
 * the page to server-side search, so nothing is lost by not asking for 1000.
 */
export async function aiGetSessions(
  limit = 300,
  query = "",
  status = "ALL"
): Promise<ActivityFeed> {
  const params = new URLSearchParams({
    limit: String(limit),
    query,
    status,
  });
  return fetchApi<ActivityFeed>(`/api/ai/sessions?${params.toString()}`);
}

/**
 * Polls the REAL, user-safe reasoning progress for an in-flight execution.
 * The conversation_id is the client-generated request id passed to aiExecute.
 */
export async function aiProgress(conversationId: string): Promise<AgentProgress> {
  return fetchApi(
    `/api/ai/progress?conversation_id=${encodeURIComponent(conversationId)}`
  );
}

export async function aiGetSession(sessionId: string): Promise<SessionBundle> {
  return fetchApi<SessionBundle>(`/api/ai/sessions/${sessionId}`);
}

/**
 * resume-by-conversation. Returns the latest NON-TERMINAL
 * execution session (status PENDING / PLANNING / EXECUTING) for this
 * user+org so a browser refresh mid-run can reattach the progress view.
 */
export interface ActiveSessionInfo {
  found: boolean;
  session: {
    session_id: string;
    conversation_id: string | null;
    status: string;
    current_phase: string | null;
    created_at: string | null;
    /** Last control-plane write (backend ages stranded runs out on this). */
    updated_at?: string | null;
    age_seconds?: number | null;
  } | null;
}

export async function latestActiveSession(): Promise<ActiveSessionInfo> {
  return fetchApi("/api/ai/sessions/latest-active");
}

/**
 * Cancel the user's in-flight run (production request 2026-10-08: "where is
 * the button to cancel the ongoing request?").
 *
 * The control plane marks the session CANCELLED — the executor refuses
 * further mutations, the terminal guard stops the status being rewritten,
 * reattach stops, and the AI-Activity feed never shows it.  `cancelled:
 * false` means the run had already FINISHED while the click was in flight:
 * its real outcome stands (a finished run is history, never rewritten).
 */
export interface CancelRunResult {
  cancelled: boolean;
  status: string;
  /** The cancelled session — null when the run was still a QUEUED job. */
  session_id: string | null;
  /** Set when cancel landed BEFORE a worker claimed the run (L2). */
  job_id?: string | null;
}

export async function aiCancelRun(payload: {
  conversation_id?: string;
  session_id?: string;
}): Promise<CancelRunResult> {
  return fetchApi<CancelRunResult>("/api/ai/sessions/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/* ---- Catalogue (products & services) -------------------------------------
 *
 * The page goes through the API rather than querying Supabase directly (the
 * customers page does that) for three reasons spelled out in app/main.py:
 * the item CODE is generated server-side by an RPC, the delete rule needs a
 * cross-table usage check, and validation must live in one place so the page
 * and the agent can never disagree.  Both kinds share the same four calls.
 */
export type CatalogueKind = "products" | "services";

export interface CatalogueItem {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  /** Products: "PRD-0001". Services: "SRV-0001". */
  product_code?: string;
  service_code?: string;
  /** Products */
  unit?: string | null;
  is_stock_tracked?: boolean;
  unit_price?: number | null;
  cost_price?: number | null;
  /** Services */
  billing_unit?: string;
  standard_rate?: number | null;
  cost_rate?: number | null;
  revenue_account_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CatalogueCounts {
  total: number;
  active: number;
  inactive: number;
}

export interface CatalogueList {
  items: CatalogueItem[];
  counts: CatalogueCounts;
  status: string;
}

export interface CatalogueMutation {
  item: CatalogueItem;
  reused?: boolean;
}

export async function catalogueList(
  kind: CatalogueKind,
  params: { query?: string; status?: string } = {}
): Promise<CatalogueList> {
  const search = new URLSearchParams();
  if (params.query) search.set("query", params.query);
  if (params.status) search.set("status", params.status);
  const qs = search.toString();
  return fetchApi<CatalogueList>(`/api/catalogue/${kind}${qs ? `?${qs}` : ""}`);
}

export async function catalogueCreate(
  kind: CatalogueKind,
  payload: Record<string, unknown>
): Promise<CatalogueMutation> {
  return fetchApi<CatalogueMutation>(`/api/catalogue/${kind}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function catalogueUpdate(
  kind: CatalogueKind,
  id: string,
  payload: Record<string, unknown>
): Promise<CatalogueMutation> {
  return fetchApi<CatalogueMutation>(`/api/catalogue/${kind}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** Soft delete / reactivate — history keeps resolving the item. */
export async function catalogueSetActive(
  kind: CatalogueKind,
  id: string,
  active: boolean
): Promise<CatalogueMutation> {
  return fetchApi<CatalogueMutation>(`/api/catalogue/${kind}/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ active }),
  });
}

/** Hard delete — the API refuses (409) while any document references the item. */
export async function catalogueDelete(
  kind: CatalogueKind,
  id: string
): Promise<{ deleted: boolean }> {
  return fetchApi<{ deleted: boolean }>(`/api/catalogue/${kind}/${id}`, {
    method: "DELETE",
  });
}

/* ---- background runs ---- */

export interface EnqueueJobResult {
  queued: boolean;
  job_id: string;
  conversation_id: string | null;
}

export async function aiEnqueueJob(request: UserRequest): Promise<EnqueueJobResult> {
  return fetchApi("/api/ai/jobs", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export interface AiJobStatus {
  job_id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  conversation_id: string | null;
  result: AgentResponse | null;
  error: string | null;
  created_at: string;
}

export async function aiGetJob(jobId: string): Promise<AiJobStatus> {
  return fetchApi(`/api/ai/jobs/${jobId}`);
}

/** True when *err* is an ApiError carrying HTTP *status* (e.g. 404 from
 *  an older backend without the jobs endpoint). */
export function isApiErrorWithStatus(err: unknown, status: number): boolean {
  return (
    err instanceof Error &&
    typeof (err as unknown as { status?: unknown }).status === "number" &&
    (err as unknown as { status: number }).status === status
  );
}

export interface BackgroundJobHandlers {
  enqueue: () => Promise<EnqueueJobResult>;
  getJob: (jobId: string) => Promise<AiJobStatus>;
  onResult: (res: AgentResponse) => void;
  onError: (message: string) => void;
  onStalled: (jobId: string) => void;
  /** The job reached CANCELLED (cancel-before-claim, or another surface
   *  cancelled it). Without this the poll loop would spin for ever —
   *  CANCELLED matches none of the other terminal branches. */
  onCancelled?: () => void;
  /** Poll cadence and stall window (injectable for tests). */
  pollIntervalMs?: number;
  stallAfterMs?: number;
  sleep?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * enqueue an AI run and poll it to a terminal state.
 * SUCCEEDED renders the result card, FAILED surfaces the error, and a
 * QUEUED job no worker claims within the stall window triggers the
 * one-click "run in foreground instead" offer. The jobs endpoint is
 * consulted via the injected handlers so older backends can 404.
 */
export async function runBackgroundJob(
  h: BackgroundJobHandlers
): Promise<void> {
  const wait = h.sleep ?? defaultSleep;
  const interval = h.pollIntervalMs ?? 2_000;
  const stallAfter = h.stallAfterMs ?? 90_000;
  const job = await h.enqueue();
  const startedAt = Date.now();
  for (;;) {
    await wait(interval);
    const status = await h.getJob(job.job_id);
    if (status.status === "SUCCEEDED" && status.result) {
      h.onResult(status.result);
      return;
    }
    if (status.status === "FAILED") {
      h.onError(status.error || "The background run failed.");
      return;
    }
    if (status.status === "CANCELLED") {
      // Terminal: the run was cancelled (this tab's Cancel, or another
      // surface).  Stop polling — never spin on a state we handle here.
      h.onCancelled?.();
      return;
    }
    if (status.status === "QUEUED" && Date.now() - startedAt > stallAfter) {
      h.onStalled(job.job_id);
      return;
    }
  }
}

/* ---- SSE streaming execution ---- */

export interface StreamEvents {
  onStep?: (step: {
    step_type: string;
    phase?: string | null;
    status?: string | null;
    created_at?: string | null;
    execution_id?: string | null;
  }) => void;
}

/* P2-⑪: serverless cold start happens BEFORE the server's started_at —
 * the browser is the only place TTFB can see it. Fire-and-forget report;
 * observability only, never blocks or fails the request. */
async function reportClientTtfb(args: {
  executionId: string;
  ttfbMs: number;
  transport: string;
  token?: string;
}): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/ai/client-timing`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(args.token ? { Authorization: `Bearer ${args.token}` } : {}),
      },
      body: JSON.stringify({
        execution_id: args.executionId,
        ttfb_ms: Math.max(0, Math.round(args.ttfbMs)),
        transport: args.transport,
      }),
    });
  } catch {
    /* observability only */
  }
}

/**
 * Runs the agent over the SSE endpoint. Resolves with the FINAL
 * AgentResponse once verification completed; every recorded reasoning
 * step is delivered to onStep as it lands. Falls back to the plain
 * POST endpoint when the stream cannot even be opened (older backend).
 */
export async function aiExecuteStream(
  request: UserRequest,
  events?: StreamEvents
): Promise<AgentResponse> {
  const { createClient } = await import("@/lib/supabase/client");
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const startedAt = performance.now();

  const res = await fetch(`${API_BASE}/api/ai/execute-stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(request),
  });

  if (!res.ok || !res.body) {
    // Older backend without the SSE route - fall back to the plain call.
    const fallback = await aiExecute(request);
    // Guard: AgentResponse.execution_id is optional (string | undefined);
    // only report TTFB when the id actually came back.
    if (fallback.execution_id) {
      void reportClientTtfb({
        executionId: fallback.execution_id,
        ttfbMs: performance.now() - startedAt,
        transport: "inline",
        token,
      });
    }
    return fallback;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // Wrapped in an object so TypeScript's closure analysis cannot narrow
  // `final` to `null` (it is assigned inside handleEvent).
  const state = {
    final: null as AgentResponse | null,
    firstByteAt: null as number | null,
    ttfbReported: false,
  };

  const maybeReportTtfb = (executionId?: string | null) => {
    if (state.ttfbReported || state.firstByteAt === null || !executionId) return;
    state.ttfbReported = true;
    void reportClientTtfb({
      executionId,
      ttfbMs: state.firstByteAt - startedAt,
      transport: "sse",
      token,
    });
  };

  const handleEvent = (raw: string) => {
    const lines = raw.split("\n");
    let event = "message";
    let data = "";
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return;
    if (event === "step") {
      try {
        const parsed = JSON.parse(data);
        events?.onStep?.(parsed);
        // P2-⑪: the FIRST-BYTE instant is frozen above; report TTFB once a
        // DB-backed step event carries the execution_id (the instant-ack
        // RECEIVED event predates session creation).
        maybeReportTtfb(parsed?.execution_id);
      } catch {
        /* malformed step - ignore */
      }
    } else if (event === "final") {
      try {
        state.final = JSON.parse(data) as AgentResponse;
        maybeReportTtfb(state.final?.execution_id);
      } catch {
        /* malformed final - handled by null check below */
      }
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (state.firstByteAt === null) state.firstByteAt = performance.now();
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    // SSE messages are separated by a blank line.
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      handleEvent(raw);
    }
  }

  if (!state.final) {
    // Stream ended without a final event - falling back to a sync call is
    // unsafe (the run already happened), so surface an honest error.
    throw new Error("The AI stream ended without a result. Try again.");
  }
  return state.final;
}

/* ---- Organization onboarding (AI-assisted first-time setup) ---- */

/**
 * Real backend-compatible onboarding choices: business types with the chart
 * each one produces, supported currencies, required fields and the optional
 * account bundles. Read from the backend contract, never hard-coded, so the
 * UI cannot offer a choice the backend rejects.
 */
export async function onboardingSchema(businessType?: string): Promise<OnboardingSchema> {
  const query = businessType ? `?business_type=${encodeURIComponent(businessType)}` : "";
  return fetchApi<OnboardingSchema>(`/api/onboarding/schema${query}`);
}

/**
 * Ask the assistant to turn a plain-language business description into an
 * onboarding PROPOSAL. Nothing is created: the result is reviewed (and
 * edited) by the user before the organization is created.
 */
export async function aiAnalyzeOrganization(payload: {
  description: string;
  business_type?: string | null;
  answers?: OnboardingAnswer[];
  history?: { role: "user" | "assistant"; content: string }[];
}): Promise<OnboardingAnalysis> {
  return fetchApi<OnboardingAnalysis>("/api/onboarding/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/* ---- Fixed Assets (the asset register) ---- */

export interface FixedAssetSummary {
  purchase_cost: number;
  accumulated_depreciation: number;
  book_value: number;
}

export interface FixedAssetRegister {
  items: FixedAsset[];
  /** Counts per asset_status, plus "ALL" — computed over the whole register. */
  counts: Record<string, number>;
  summary: FixedAssetSummary;
  status: string;
}

/**
 * The register. Counts and the summary always cover EVERY asset; `query` and
 * `status` narrow the returned rows only.
 */
export async function listFixedAssets(
  query = "",
  status = "ALL"
): Promise<FixedAssetRegister> {
  const params = new URLSearchParams({ query, status });
  return fetchApi<FixedAssetRegister>(`/api/fixed-assets?${params.toString()}`);
}

export interface RegisterFixedAssetPayload {
  name: string;
  purchase_cost: number;
  purchase_date?: string;
  payment_method?: string;
  /**
   * Explicit settlement ledger (the cash/bank picker). When omitted the
   * backend follows `payment_method`: CASH credits cash-on-hand, every other
   * treatment credits the configured bank account.
   */
  payment_account_id?: string | null;
  supplier_name?: string | null;
  /** Explicit ASSET account pick (the form's picker); omitted = name match. */
  asset_account_id?: string | null;
  useful_life_years?: number | null;
  depreciation_method?: string;
  salvage_value?: number;
  description?: string | null;
  /** Category whose defaults (life / method / GL accounts) the form carried. */
  category_id?: string | null;
  /**
   * The form's GL picks. Sent when chosen; the backend still resolves them
   * deterministically when omitted, so a blank field is never an error.
   */
  depreciation_expense_account_id?: string | null;
  accumulated_depreciation_account_id?: string | null;
}

/**
 * Register (capitalise) an asset. The backend creates the record AND posts
 * the acquisition journal — the browser never writes a journal itself.
 */
export async function registerFixedAsset(
  payload: RegisterFixedAssetPayload
): Promise<{ item: FixedAsset }> {
  return fetchApi<{ item: FixedAsset }>("/api/fixed-assets", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Post one depreciation charge (blank amount = the period's own pro-rata). */
export async function recordAssetDepreciation(
  assetId: string,
  payload: {
    depreciation_amount?: number | null;
    transaction_date?: string;
    /** Explicit GL picks (used when the asset row carries none). */
    depreciation_expense_account_id?: string | null;
    accumulated_depreciation_account_id?: string | null;
  }
): Promise<{
  item: FixedAsset & {
    /**
     * The period the charge covered: acquisition (or the last charge) → the
     * charge date, computed by the backend.
     */
    depreciation_period?: {
      from: string;
      to: string;
      days: number;
      basis: string;
    };
    /**
     * The journal IS posted and the book value IS updated; this is set only
     * when a sub-ledger row (schedule / audit trail) could not be written.
     */
    bookkeeping_warning?: string | null;
    /**
     * The asset's accumulated depreciation exceeds the total in its
     * depreciation trail (a charge posted without a schedule row) — this
     * charge's period may overlap that earlier one.
     */
    trail_warning?: string | null;
  };
}> {
  return fetchApi<{ item: FixedAsset }>(
    `/api/fixed-assets/${assetId}/depreciation`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

/** Dispose of / sell / write off an asset (posts the disposal journal). */
export async function disposeFixedAsset(
  assetId: string,
  payload: {
    disposal_amount?: number;
    disposal_type?: string;
    transaction_date?: string;
  }
): Promise<{ item: FixedAsset }> {
  return fetchApi<{ item: FixedAsset }>(`/api/fixed-assets/${assetId}/dispose`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/* ---- Asset categories (configuration: default life / method / GL accounts) ---- */

export interface AssetCategoryPayload {
  name: string;
  description?: string | null;
  default_useful_life_years?: number | null;
  default_depreciation_method?: string;
  default_asset_account_id?: string | null;
  default_depreciation_expense_account_id?: string | null;
  default_accumulated_depreciation_account_id?: string | null;
}

/** The categories the register form prefills from. */
export async function listFixedAssetCategories(): Promise<{
  items: AssetCategory[];
}> {
  return fetchApi<{ items: AssetCategory[] }>("/api/fixed-assets/categories");
}

/** Create a category (409 when the name is taken or the policy is invalid). */
export async function createFixedAssetCategory(
  payload: AssetCategoryPayload
): Promise<{ item: AssetCategory }> {
  return fetchApi<{ item: AssetCategory }>("/api/fixed-assets/categories", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Edit a category's defaults. */
export async function updateFixedAssetCategory(
  categoryId: string,
  payload: Partial<AssetCategoryPayload>
): Promise<{ item: AssetCategory }> {
  return fetchApi<{ item: AssetCategory }>(
    `/api/fixed-assets/categories/${categoryId}`,
    { method: "PATCH", body: JSON.stringify(payload) }
  );
}

/* ---- Projects ---- */

/** A customer as the project form's picker needs it (id + display name). */
export interface ProjectCustomer {
  id: string;
  name: string;
}

/** Register-wide totals for the page's KPI tiles (never the current filter). */
export interface ProjectSummary {
  budget: number;
  revenue: number;
  costs: number;
  gross_profit: number;
}

/**
 * A register row: the project plus its ``v_project_profitability`` columns.
 * A project with no posted journal lines reads 0 (the view LEFT JOINs), never
 * a hole, and ``margin_percent`` is null when there is no revenue to divide by.
 */
export interface ProjectRow extends Project {
  /** The linked customer's name, or null (none linked / lookup unavailable). */
  customer_name: string | null;
  revenue: number;
  costs: number;
  gross_profit: number;
  margin_percent: number | null;
}

export interface ProjectRegister {
  items: ProjectRow[];
  /** Counts per project_status, plus "ALL" — computed over the whole register. */
  counts: Record<string, number>;
  summary: ProjectSummary;
  customers: ProjectCustomer[];
  /** The register size the counts/summary describe (== items.length normally). */
  total: number;
  /**
   * True when the read page filled: ``items`` (and the counts/summary) describe
   * only the rows read, so the page must SAY SO rather than imply completeness.
   */
  truncated: boolean;
  /**
   * Lookups that failed, e.g. ``["profitability"]`` / ``["customers"]``. The
   * related figures are UNKNOWN — the page shows "—", never a bare 0.
   */
  degraded: string[];
  status: string;
}

/**
 * The register. Counts, the summary and the customer list always cover EVERY
 * project; `query` and `status` narrow the returned rows only.
 */
export async function listProjects(
  query = "",
  status = "ALL"
): Promise<ProjectRegister> {
  const params = new URLSearchParams({ query, status });
  return fetchApi<ProjectRegister>(`/api/projects?${params.toString()}`);
}

export interface ProjectPayload {
  name: string;
  description?: string | null;
  customer_id?: string | null;
  status?: string;
  billing_type?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  budget?: number | null;
  /** Only honoured on create; the org's base currency is sent by the page. */
  currency_code?: string;
}

/** Create a project — the server derives ``project_code`` when none is sent. */
export async function createProject(
  payload: ProjectPayload
): Promise<{ item: Project }> {
  return fetchApi<{ item: Project }>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** ``project_code`` is an identifier other documents cite — never editable. */
export type ProjectUpdate = Omit<ProjectPayload, "currency_code">;

/** Edit a project (only editable fields; the id comes from the path). */
export async function updateProject(
  projectId: string,
  payload: ProjectUpdate
): Promise<{ item: Project }> {
  return fetchApi<{ item: Project }>(`/api/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/* ---- Health ---- */

export async function healthCheck(): Promise<{ status: string; version: string }> {
  return fetchApi("/api/health");
}
