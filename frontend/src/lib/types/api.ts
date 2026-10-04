import type { ExecutionStatus, RiskLevel } from "./enums";

/* ---- Requests ---- */

export interface AttachmentRef {
  file_name: string;
  file_url?: string;
  mime_type?: string;
  file_size?: number;
  /** Base64-encoded file content - inline upload for vision extraction. */
  data_base64?: string;
}

/** Client-side upload limits (mirrors backend document_extractor). */
export const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
export const ALLOWED_UPLOAD_MIMES = new Set([
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/webp",
]);

export interface UserRequest {
  message: string;
  conversation_id?: string;
  session_id?: string;
  attachments?: AttachmentRef[];
}

export interface ClarificationAnswer {
  session_id: string;
  answer: string;
}

export interface ConfirmationDecision {
  session_id: string;
  approved: boolean;
  notes?: string;
}

/* ---- Organization onboarding (AI-assisted first-time setup) ---- */

export interface OnboardingBusinessType {
  value: string;
  template_code: string;
  template_name: string | null;
  base_account_count: number | null;
  optional_group_count: number | null;
}

export interface OnboardingCurrency {
  code: string;
  name: string;
  symbol: string | null;
  decimal_places: number | null;
}

export interface OnboardingAccount {
  code: string;
  name: string;
  account_type: string;
  category?: string | null;
  parent_code?: string | null;
  description?: string | null;
}

export interface OnboardingBundle {
  code: string;
  label: string;
  description?: string | null;
  /** Pre-recommended by the product for the chosen business type. */
  recommended?: boolean;
  /** Pre-ticked in the review step (recommended, or proposed by the AI). */
  selected?: boolean;
  reason?: string | null;
  account_count?: number | null;
  accounts?: OnboardingAccount[];
}

export interface OnboardingQuestion {
  id: string;
  field: string;
  question: string;
  why?: string | null;
  options?: { value: string; label: string }[];
  /** "assistant" | "backend_requirement" */
  source?: string;
}

export interface OnboardingSchema {
  available: boolean;
  required_fields: string[];
  defaults: Record<string, string | null>;
  fiscal_year_end_month: { min: number; max: number };
  business_types: OnboardingBusinessType[];
  currencies: OnboardingCurrency[];
  account_bundles: { code: string; label: string; description?: string | null }[];
  bundles_by_business_type: Record<string, { code: string; recommended: boolean }[]>;
  validation_rules: string[];
  countries: { code: string; timezone: string; currency: string }[];
  business_type?: string | null;
  catalog?: {
    business_type: string;
    template: { code: string; name: string; description?: string | null };
    base_accounts: OnboardingAccount[];
    optional_groups: OnboardingBundle[];
  };
}

export interface OnboardingAnalysis {
  status: "ok" | "needs_information" | "unavailable";
  used_ai: boolean;
  reason?: string | null;
  summary: string;
  /** Only real backend field names ever appear here. */
  fields: Record<string, string | number | null>;
  /** How each value was obtained (inferred / backend_default / ...). */
  field_sources: Record<string, string>;
  field_notes: Record<string, string>;
  /** Fields the assistant did NOT populate — shown as "not stated". */
  unresolved: string[];
  questions: OnboardingQuestion[];
  account_groups: OnboardingBundle[];
  rejected: { field: string; reason: string }[];
  analysis: Record<string, unknown>;
}

export interface OnboardingAnswer {
  field: string;
  answer: string;
}

/* ---- Responses ---- */

export interface AgentResponse {
  status: ExecutionStatus;
  execution_id?: string;
  action?: string;
  summary?: string;
  affected_entities?: AffectedEntity[];
  accounting_impact?: AccountingEntry[];
  verification_status?: string;
  requires_user_input: boolean;
  question?: string;
  required_information?: string[];
  /** Quick-answer buttons (e.g. suggested accounts + "Create new account"). */
  options?: string[];
  /**
   * structured per-question tap-to-answer options
   * (data-driven chips).  Each inner list is aligned with the
   * corresponding numbered sub-question of the questionnaire.
   */
  question_options?: QuestionOption[][];
  confirmation_required: boolean;
  risk_level?: RiskLevel;
  data?: Record<string, unknown>;
}

/** Mirrors app/models/schemas.py QuestionOption — label shown, value sent. */
export interface QuestionOption {
  value: string;
  label: string;
}

/**
 * Canonical affected-entity contract (mirrors app/models/schemas.py
 * AffectedEntity / app/entity_contract.py). The backend guarantees that
 * `type` is always a non-empty string; the UI remains defensive anyway.
 */
export interface AffectedEntity {
  type: string;
  action?: string;
  name?: string;
  id?: string;
  number?: string;
  total?: number;
}

export interface AccountingEntry {
  account: string;
  debit?: number;
  credit?: number;
  description?: string;
}

/* ---- Sessions ---- */

/**
 * Real agent-reasoning progress (mirrors app/main.py GET /api/ai/progress).
 * Only backend-recorded state - never model chain-of-thought.
 */
export interface AgentProgress {
  found: boolean;
  current_phase?: string;
  status?: string;
  steps: ProgressStep[];
  tools: ProgressTool[];
}

export interface ProgressStep {
  step_type: string;
  phase?: string;
  status?: string;
  created_at?: string;
  summary?: Record<string, unknown>;
}

export interface ProgressTool {
  tool: string;
  status?: string;
}

/**
 * One row of `ai.execution_sessions` (migrations 026 + 028).
 *
 * The ONLY human-meaningful headline a session carries is `user_request` — the
 * sentence the user actually typed.  (An earlier draft of these types guessed
 * at `action` / `summary` columns that do not exist, which would have rendered
 * as blank cards; it was corrected against the schema here.)
 */
export interface SessionSummary {
  id: string;
  organization_id?: string;
  user_id?: string;
  conversation_id?: string | null;
  user_request: string;
  status: ExecutionStatus | string;
  /** `ai.execution_phase_code` — where the run got to (m028). */
  current_phase?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  /** When a WAITING_FOR_USER run counts as abandoned (m074). */
  expires_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

/**
 * GET /api/ai/sessions — same register contract as Projects / Fixed Assets:
 * `counts` and `total` describe the WHOLE feed, never the current filter.
 */
export interface ActivityFeed {
  items: SessionSummary[];
  counts: Record<string, number>;
  total: number;
  /** True when the feed filled the read page (its copy is incomplete). */
  truncated: boolean;
  status: string;
}

/** `ai.execution_steps` — ordered stages of one run. */
export interface SessionStep {
  step_order: number;
  step_type: string;
  description?: string | null;
  status: string;
  input_summary?: string | null;
  output_summary?: string | null;
  error_details?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at?: string;
}

/**
 * `ai.tool_calls`, with `tool_name` / `tool_read_only` / `tool_risk_level`
 * resolved from `ai.tools` by the backend — the row itself carries only a
 * `tool_id` UUID, and `read_only: false` is how the page tells a READ of the
 * user's books from a WRITE to them.
 */
export interface ToolCallRecord {
  call_order: number;
  tool_id: string;
  tool_name: string | null;
  tool_read_only: boolean | null;
  tool_risk_level: string | null;
  status: string;
  input_payload?: Record<string, unknown>;
  output_payload?: Record<string, unknown>;
  error_details?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

/** `ai.clarifications` — what the agent asked the user, and what they replied. */
export interface ClarificationRecord {
  question: string;
  reason?: string | null;
  user_response?: string | null;
  status: string;
  asked_at?: string | null;
  answered_at?: string | null;
}

/** `ai.confirmations` — a high-impact action the user approved or declined. */
export interface ConfirmationRecord {
  action_type: string;
  description?: string | null;
  risk_level: string;
  confirmation_required: boolean;
  user_confirmed: boolean | null;
  confirmed_at?: string | null;
}

/** `ai.execution_results` — what changed, and whether it was VERIFIED. */
export interface SessionResult {
  status: string;
  summary?: string | null;
  action_type?: string | null;
  affected_entities?: unknown[];
  result_payload?: Record<string, unknown>;
  verification_status?: string;
  completed_at?: string | null;
}

/** GET /api/ai/sessions/{id} — the full trail for one run. */
export interface SessionBundle {
  session: SessionSummary;
  steps: SessionStep[];
  tool_calls: ToolCallRecord[];
  clarifications: ClarificationRecord[];
  confirmations: ConfirmationRecord[];
  results: SessionResult | null;
}

/* ---- Organization ---- */

export interface Organization {
  id: string;
  name: string;
  slug: string;
  legal_name?: string;
  business_type: string;
  tax_number?: string;
  registration_number?: string;
  base_currency_code: string;
  country_code?: string;
  timezone: string;
  fiscal_year_end_month: number;
  is_active: boolean;
}

export interface OrganizationMember {
  id: string;
  organization_id: string;
  user_id: string;
  role_id: string;
  status: "INVITED" | "ACTIVE";
  joined_at?: string;
  role?: {
    code: string;
    name: string;
    permissions: string[];
  };
}

export interface OrganizationSettings {
  id: string;
  organization_id: string;
  invoice_prefix: string;
  quotation_prefix: string;
  bill_prefix: string;
  credit_note_prefix: string;
  journal_prefix: string;
  payment_prefix: string;
  receipt_prefix: string;
  customer_prefix: string;
  supplier_prefix: string;
  project_prefix: string;
  expense_prefix: string;
  asset_prefix: string;
  default_payment_terms_days: number;
  settings: Record<string, unknown>;
}

/* ---- Create Organization Request ---- */

export interface CreateOrganizationRequest {
  name: string;
  business_type: string;
  base_currency_code: string;
  country_code: string;
  timezone: string;
  fiscal_year_end_month: number;
  legal_name?: string;
  tax_number?: string;
  registration_number?: string;
}
