# AI-Native Accounting & Financial ERP — Complete Codebase Integration Audit

**Version:** 1.0 · **Date:** 2026-08-29 · **Mode:** Deep audit + integration verification (no code/DB modified)
**Scope:** Python/FastAPI backend · Next.js frontend · Live Supabase database (via MCP) · AI Control Plane · ERP_AGENT_CONSTITUTION.md v1.2.0

---

## PART 1 — Executive Summary

**Primary objective answer: NO.** The system cannot currently receive a natural-language request from an authenticated user, execute a correct accounting treatment, persist it safely, and return a verified result. The runtime chain is broken at its first database write.

**The one-sentence verdict:** The database layer is excellent and hardened, the code layers are individually well-written, but the *integration between them was never exercised end-to-end* — every write to the AI Control Plane uses column names that do not exist in the live schema, so `/api/ai/execute` fails on every request against the real Supabase.

**Six system-blocking issues (all CRITICAL):**

| # | Issue | Effect |
|---|-------|--------|
| C1 | `database.py` writes to `ai.*` execution tables with non-existent columns (`user_message`, `session_id`, `tool_name`, `tool_input`, `required_fields`, `action_description`, `result_data`, …) | First insert in every request throws → every execute call returns `FAILED: "An unexpected error occurred"` |
| C2 | Session status enum mismatch: Python writes 13-phase values into `session_status_code` (7 values); the 13 values belong in `current_phase` (`execution_phase_code`) | Even with C1 fixed, status updates fail |
| C3 | Confirmation occurs AFTER tool execution, and approval re-runs `execute()` from scratch | High-risk mutations execute without consent; approval duplicates invoices/journals |
| C4 | The deterministic accounting engine's 7 transaction builders are never called by any runtime path; invoices/bills/payments/expenses are created WITHOUT journal entries; the only journal path is Gemini composing debit/credit lines itself | Violates Constitution §3 ("AI must never compute debit/credit"); financial statements omit posted documents; wrong books |
| C5 | `get_gemini_tool_definitions()` exposes only `organization_id` as a parameter for all 36 tools; the 98 seeded `ai.tool_parameters` rows are never read | Gemini does not know tool signatures → malformed tool calls → runtime failures |
| C6 | No transaction atomicity anywhere (invoice → items → journal are separate writes; even `prepare_journal` is 2 inserts) | Violates Constitution §10; partial states possible |

**Also critical from a security standpoint:** the `X-User-Id`/`X-Organization-Id` header fallback is enabled in **all** environments with no `is_production` gate, and it never verifies that the header org matches the user's membership → any caller can act on any organization.

**What genuinely works:** 39/39 offline unit tests pass; JWT bearer path is correctly wired frontend→backend; the Gemini API key is properly stored in Vault behind a service-role-only function; the database has RLS on all 76 public + 20 ai tables, balancing/period/immutability triggers, 14 reporting views, and a complete, consistent tool/permission/workflow metadata set; repositories are almost uniformly organization-scoped.

**Production readiness:** Local development: **PARTIAL** (server runs, health endpoint works, unit tests pass). Internal testing / hackathon demo: **NOT READY** (no request can complete). Beta/production: **NOT READY**.

---

## PART 2 — Complete Repository Inventory

**Backend `Ai Accountant/ERP/app/` (31 Python files, ~5,100 lines):**

| Path | Lines | Purpose | Integration status |
|------|-------|---------|-------------------|
| `main.py` | 243 | FastAPI app, 6 endpoints, CORS, lifespan | IMPLEMENTED; CORS via deprecated `on_event`; reads OK, execute path blocked by C1 |
| `config.py` | 86 | pydantic-settings; Constitution path | IMPLEMENTED, correct |
| `database.py` | 369 | Service-role client, CRUD helpers, control-plane writers | **BROKEN** — control-plane column mismatches (C1/C2); `_table()` ai-schema routing correct |
| `auth.py` | 205 | JWT decode + membership/role resolution | PARTIAL — header fallback is an org-spoofing hole (C7) |
| `agent.py` | 337 | 10-phase orchestrator, state machine | PARTIAL — phases reordered vs Constitution (confirm after execute), re-execution duplication (C3) |
| `planner.py` | 273 | Regex intent/entity/amount extraction | IMPLEMENTED but keyword-only; ~26 intents |
| `context_manager.py` | 185 | Minimal context assembly | PARTIAL — only 8 intents have `ai.context_rules`; report prefetch only for trial balance |
| `gemini_client.py` | 270 | Gemini wrapper, system instructions, tool loop | PARTIAL — Constitution truncated to 8,000 chars; tool loop exits after first response (no result feedback) (C8) |
| `tool_router.py` | 142 | Registry → permission → validator → handler | PARTIAL — permission/validation integration good; tool declarations parameterless (C5) |
| `validator.py` | 210 | Structural + metadata-driven rules | PARTIAL — 2 of 10 DB rules dead (slug mismatch); BALANCED/PERIOD_OPEN rules never fire for `post_journal` (entry_id-only args) |
| `accounting_engine.py` | 356 | 7 deterministic transaction builders + verify | **DISCONNECTED** — only `verify_journal` is ever imported (C4) |
| `permissions.py` | 201 | Capability maps, role hierarchy | IMPLEMENTED; process-lifetime cache; OWNER/ADMIN bypass |
| `models/schemas.py` | 341 | Pydantic v2 models + 9 enums | IMPLEMENTED; `ExecutionStatus` conflates session status with phase (C2) |
| `tools/__init__.py` | 332 | 36 tool handlers | IMPLEMENTED; `record_expense_payment` mis-wired to `record_supplier_payment` |
| repositories (16 files) | ~1,700 | Supabase data access | IMPLEMENTED; org-scoped except `get_journal_lines`; validate/post/reverse use RPC without org args (service-role → RLS bypass) |
| services (13 files) | ~1,000 | Business orchestration | PARTIAL — document services never call the accounting engine; no atomicity |
| tests (4 files) | ~477 | 39 unit tests | PASSING (offline only) |

**Frontend `frontend/src/` (19 TS/TSX files):** login/signup/verify-email, dashboard shell, AICommandBox + clarification/confirmation/action-card components, API client, Supabase browser/server clients, middleware cookie guard. Types cover the full response contract. **Attachments are local blob URLs only; never uploaded.** Sidebar routes are placeholders.

**Database (live via MCP):** 35 migrations applied; 76 public tables (all RLS); 20 `ai.*` tables (all RLS); 14 views; 19 functions incl. `validate_journal_entry`, `post_journal_entry`, `reverse_journal_entry`, `get_period_for_date`, `next_document_number`, `get_gemini_api_key`; extensions `pgcrypto`, `uuid-ossp`, `pg_trgm`, `supabase_vault`. All business tables currently hold **0 rows** (reference data only: currencies=11, tax_categories=3, roles=5, account template=148 items).

**Local migration drift:** 29 local files vs 35 applied migrations. Remote-only (unmirrored locally): `update_constitution_v120`, `add_planned_to_ai_status`, `seed_ai_control_plane_metadata`, `add_control_plane_governance_tables`, `seed_control_plane_governance_data`, `026_add_implemented_enum_value`, `027_update_tool_status_implemented`, `028_seed_tool_parameters_batch1/2/3`.

**Classification summary:** IMPLEMENTED-but-unintegrated is the dominant failure mode. Dead code: `accounting_engine` builders (7 fns), `gemini_client.generate_text`, `planner` mappings for `record_purchase`/`record_sale` (fallback intents). Duplicated logic: confirmation policy (planner hardcodes vs `ai.tools.requires_confirmation` + `ai.workflows.requires_confirmation`, both ignored).

---

## PART 3 — File-by-File Review (critical files)

**main.py** — Endpoints match frontend client exactly (`/api/ai/execute|clarify|confirm`, `/api/ai/sessions[/{id}]`, `/api/health`). `UserRequest.message` is the only field consumed; `conversation_id`, `session_id`, `attachments` are accepted and **silently ignored**. `get_session` detail query filters child tables by `session_id` — column does not exist (`execution_session_id`) → 500 on session detail.

**auth.py** — `_decode_jwt`: HS256, `verify_aud: False`, expired tokens rejected; second attempt identical to the first (dead code path). `jwt_secret` defaults to `"change-me"` when env is unset → any token signed with the literal default verifies. `_resolve_membership` picks the *first* membership (multi-org users get arbitrary org). Header fallback: takes `X-User-Id` **and** `X-Organization-Id` at face value; membership lookup only feeds the role — it never checks the header org belongs to the user → **full cross-tenant impersonation without any token**. No `is_production` gate.

**config.py** — Clean. `.env` present with all 17 variables set (names verified, values not inspected beyond presence). Gemini key correctly excluded (Vault).

**database.py** — `_table()` ai-schema routing works. Column mismatches against live schema: `ai_execution_sessions.user_message` (actual `user_request`), `constitution_version` (actual `instruction_version_id`), `model_configuration` (actual `model_configuration_id`); `ai_execution_steps.session_id/step_data` (actual `execution_session_id`, `input_summary`/`output_summary`); `ai_tool_calls.session_id/step_id/tool_name/tool_input/tool_output` (actual `execution_session_id`/`execution_step_id`/`tool_id`/`input_payload`/`output_payload`); `ai_clarifications.required_fields` (actual `required_information`); `ai_confirmations.action_description/confirmation_data` (actual `description`; no data column — `action_type`, `user_confirmed` exist); `ai_execution_results.result_data` (actual `result_payload`). Additionally `ai.tool_calls.tool_id` is a **FK to ai.tools** — Python has only the slug.

**agent.py** — Phase order: RECEIVED → INTERPRETING → PLANNING → (clarify?) → CONTEXT → GEMINI → **EXECUTE TOOLS** → VALIDATE → **CONFIRM** → VERIFY → COMPLETED. Constitution §9 requires VALIDATE → PREVIEW → ASK → EXECUTE. So mutations run *before* consent. `resume_with_confirmation(approved=True)` calls `execute()` again with the original message → a second invoice/bill/journal is created (first one already committed). `resume_with_clarification` similarly re-runs from scratch: new session row, prior session orphaned in AWAITING_CLARIFICATION forever. Verification (Phase 8) only fires when a tool result contains `data["entry"]["id"]` — only `prepare_journal` returns that shape, so document-creating tools are never verified. `agent_id` hardcoded (matches live row `4c706ac0…`, `erp-accounting-agent`, ACTIVE). `MAX_TOOL_ITERATIONS = 10` defined, never used.

**planner.py** — Ordered regex intents (good specificity ordering). Requires supplier name for *both* cash and credit purchase intents — contradicts §18 (cash purchase does not require a supplier). No cash-vs-credit question when unstated (§20 violated: "record_purchase"/"record_sale" fallback intents execute without asking payment method). Amount regex supports Rs/PKR/₨ only. Entity regexes capitalize-anchored; "Dell" in scenario 1 is captured as supplier_name by the `from|supplier` pattern only if preceded by "from" — scenario 1 has no "from", so no supplier captured (good), but intent = `record_purchase` with no clarification and no confirmation.

**context_manager.py** — Org + FY + period always fetched. Entity fetching gated on `ai.context_rules` slugs: **only 8 intents have rules** (`create_invoice`, `customer_balance`, `generate_financial_statements`, `generate_trial_balance`, `project_profitability`, `record_credit_purchase`, `record_payment`, `supplier_balance`). For the other ~18 intents (credit sale, cash sale/purchase, expense, receipt, quotation, credit note, purchase return, ledgers, P&L, balance sheet, cash flow, GL), Gemini receives only org name + period + hint-based entity searches. `_fetch_reports` returns data only for trial balance; balance sheet / income statement slugs return `[]`.

**gemini_client.py** — System instruction = 7 static rules + first **8,000 characters** of the 40k-char Constitution (~20%). No permissions, no current date, no financial year, no user role in the prompt (period is in user content; date is not — "Trial Balance for August" cannot be resolved to a period). `generate_with_tools`: sends one message; loop `break`s immediately after collecting the first response's tool calls — tool results are never sent back to Gemini; no multi-step reasoning possible; `iteration_count` is always 1. `history=[]` each call → no conversation memory. All tool parameters serialized as STRING schema. If Gemini echoes `organization_id` in args, `handler(organization_id, **arguments)` raises TypeError (duplicate kwarg) → generic failure.

**tool_router.py** — Registry lookup → permission check (good) → validator for mutations (good) → handler. `get_gemini_tool_definitions()` returns one property (`organization_id`) for every tool — ignores `ai.tool_parameters` entirely (C5). No per-parameter type/required validation against DB metadata.

**validator.py** — Structural amount/date checks + DB rules by `applies_to`. Dead rules found: `record_customer_payment` (tool is `record_customer_receipt`), `record_expense` (tool is `create_expense`). `BALANCED` and `PERIOD_OPEN` for `post_journal` read `total_debit/total_credit/transaction_date` from tool args — `post_journal` only receives `entry_id` → rules never evaluate. `_check_period_open` swallows all exceptions → returns None (pass-through; DB trigger is the real guard).

**accounting_engine.py** — Correct double-entry builders (debit/credit placement verified for all 7 transaction types; receivable/payable lines carry customer/supplier dims; project dim on purchase/revenue lines). **Zero callers** in runtime code (only `verify_journal` imported by agent.py). `verify_journal` re-sums lines and checks balance — sound.

**permissions.py** — `ai.permissions` (7 capabilities) → tool-capability map; role permission strings → capabilities; `_ALWAYS_ALLOWED` = 11 read tools. OWNER/ADMIN and `ai:full` bypass. Cache is process-lifetime (no TTL; `invalidate_cache` never called).

**models/schemas.py** — Complete and internally consistent. `ExecutionStatus` (13 values) mirrors `execution_phase_code` exactly but is written to `session_status_code` (7 values) — the conflation is the C2 root cause.

**tools/__init__.py** — 36 handlers registered; read-only flags consistent with `ai.tools.read_only` for all 36 (verified against live DB). `record_expense_payment` delegates to `payment_service.record_supplier_payment` while its DB metadata advertises `expense_id`/`bill_id` params → guaranteed failure (`supplier_id` missing). `_classify_expense` is a pure keyword heuristic (no DB).

---

## PART 4 — Critical Line-Level Findings

| File | Function | Lines | Severity | Problem |
|------|----------|-------|----------|---------|
| database.py | `create_execution_session` | 237–258 | CRITICAL | Inserts `user_message`, `constitution_version`, `model_configuration` — none exist |
| database.py | `create_execution_step` | 268–284 | CRITICAL | `session_id`, `step_data` ≠ `execution_session_id`, `input_summary`/`output_summary` |
| database.py | `create_tool_call` | 287–307 | CRITICAL | `session_id`/`step_id`/`tool_name`/`tool_input`/`tool_output` ≠ actual columns; `tool_id` is an FK |
| database.py | `create_clarification` | 310–328 | CRITICAL | `session_id`, `required_fields` ≠ `execution_session_id`, `required_information` |
| database.py | `create_confirmation` | 331–351 | CRITICAL | `session_id`, `action_description`, `confirmation_data` ≠ `execution_session_id`, `description`, — |
| database.py | `create_execution_result` | 354–368 | CRITICAL | `session_id`, `result_data` ≠ `execution_session_id`, `result_payload` |
| agent.py | `execute` | 134–188 | CRITICAL | Tools executed (L137–154) before confirmation gate (L174–188); approval re-executes everything |
| agent.py | `resume_with_confirmation` | 314–319 | CRITICAL | Re-invokes `execute()` → duplicate documents |
| auth.py | `authenticate_header` | 179–199 | CRITICAL | Header org never validated against membership; enabled in all envs |
| tool_router.py | `get_gemini_tool_definitions` | 118–141 | CRITICAL | Only `organization_id` exposed as parameter for all 36 tools |
| gemini_client.py | `generate_with_tools` | 119–147 | HIGH | Loop breaks after first response; tool results never fed back |
| gemini_client.py | `_build_system_instructions` | 209 | MEDIUM | Constitution truncated to 8,000 chars |
| tools/__init__.py | `_record_expense_payment` | 261–263 | HIGH | Wrong service (needs `supplier_id`; metadata promises `expense_id`/`bill_id`) |
| planner.py | `plan` | 123–128 | MEDIUM | Supplier required for cash purchases; cash/credit never asked when unstated |
| validator.py | `_load_rules` | 125–132 | MEDIUM | Slug mismatches → 2 dead rules |
| journal_repository.py | `get_journal_lines` | 97–104 | MEDIUM | No organization_id filter |
| main.py | `get_session` | 200–219 | HIGH | Child queries filter on non-existent `session_id` column |
| agent.py | `execute` (Phase 8) | 193–201 | HIGH | Verification only for results shaped like `prepare_journal` output |

---

## PART 5 — Dependency Graph (verified from imports)

```
main.py ─→ auth.py ─→ database.py ─→ Supabase (service role)
   │            └──── config.py
   ├→ agent.py ─→ planner.py ─→ models/schemas.py
   │      ├→ context_manager.py ─→ repositories (customer/supplier/account/org/project/report)
   │      ├→ gemini_client.py ─→ database.py (Vault key) ─→ tool_router.get_gemini_tool_definitions
   │      ├→ tool_router.py ─→ permissions.py ─→ database.py (ai.permissions)
   │      │        ├→ validator.py ─→ repositories + database.py (ai.validation_rules)
   │      │        └→ tools/__init__.py ─→ services (13) ─→ repositories (16) ─→ database.py
   │      └→ accounting_engine.verify_journal ─→ accounting_service ─→ journal_repository
   └→ database.py (sessions list/detail)
```
No circular imports (verified). Layering is clean. The architectural flaw is not the graph but **missing edges**: `services → accounting_engine` (nothing wires document creation to journal creation), `gemini_client → ai.tool_parameters` (metadata unread), `agent → ai.workflows` (workflow engine never executed).

---

## PART 6 — Database Schema Audit

- 76 public tables, RLS enabled on all. `document_sequences` RLS-with-no-policy is **by design** (service-role only; table comment says so).
- Integrity triggers verified present: `trg_journal_lines_totals` (balance), `trg_journal_entries_status` (state machine + posted immutability), `trg_journal_lines_guard`, `trg_journal_entries_number`, `trg_document_number_assign`, `trg_party_code_assign`; functions `validate/post/reverse_journal_entry`, `get_period_for_date`, `close/reopen_accounting_period`.
- 14 reporting views incl. `v_trial_balance`, `v_general_ledger`, `v_customer_ledger`, `v_supplier_ledger`, `v_project_profitability` (security_invoker per design).
- `ai` schema enums: `session_status_code` {PENDING, PLANNING, WAITING_FOR_USER, EXECUTING, COMPLETED, FAILED, CANCELLED} vs `execution_phase_code` {RECEIVED…REJECTED, 13 values}. `step_type_code` {REASON, RETRIEVE, VALIDATE, CONFIRM, EXECUTE, VERIFY, RESPOND} vs Python's free-text step types ("PLANNING", "CONTEXT_LOADING"…) — mismatch.
- Security advisor: only intentional residuals (deny-all sequence table; helper EXECUTE grants) plus one genuine WARN: `public.rls_auto_enable()` SECURITY DEFINER executable by `anon` — should be revoked/moved.

---

## PART 7 — Code ↔ Database Consistency

**Consistent:** tool slugs/flags (36/36), capability permission lists, organization-scoped repo queries vs table columns, journal entry columns vs `create_journal_entry` insert, `v_*` view names vs report_repository, agent UUID, `get_period_for_date` RPC signature, Vault helper.

**Inconsistent:** all 6 control-plane write helpers (Part 4); session status semantics; `ai.tool_calls.tool_id` FK vs slug-based logging; `ai.execution_steps.step_type` enum vs free-text; migration file drift (35 applied vs 29 local); `record_expense_payment` params vs handler; validation-rule `applies_to` slugs (2 dead).

---

## PART 8 — AI Control Plane ↔ Code Consistency

| Table | Rows | Used by code? | Verdict |
|-------|------|---------------|---------|
| ai.agents / agent_versions | 1/1 | agent_id hardcoded only | PARTIALLY USED |
| ai.agent_modules | 8 | never read | IGNORED |
| ai.instruction_versions | 3 | never read (Constitution read from disk instead) | DUPLICATED IN CODE |
| ai.model_configurations | 1 | never read (config.py env instead) | IGNORED |
| ai.tools | 36 | registry mirrors slugs/flags manually | DUPLICATED (kept in sync by tests) |
| ai.tool_parameters | 98 | **never read** | IGNORED — root cause of C5 |
| ai.context_sources | 21 | never read directly | IGNORED |
| ai.context_rules | 8 | read (get_context_sources_for_intent) | PARTIALLY USED (8 of ~26 intents) |
| ai.workflows / workflow_steps | 13 / 92 (all PLANNED) | **never executed** | UNIMPLEMENTED at runtime |
| ai.execution_sessions / steps / tool_calls / clarifications / confirmations / execution_results | 0 rows | writes attempted, all fail on schema | BROKEN |
| ai.permissions | 7 | read + cached | USED |
| ai.validation_rules | 10 | read; 2 dead by slug, 2 inert by shape | PARTIALLY USED |
| ai.audit_events | 0 | never written | UNIMPLEMENTED |

---

## PART 9 — Constitution ↔ Code Consistency

| Constitution rule | Implementation reality | Verdict |
|---|---|---|
| §3 AI must never compute debits/credits (engine does it) | Engine builders uncalled; Gemini must compose `lines[]` for `prepare_journal` | **VIOLATED** |
| §5 10-phase protocol; ask only for material missing info | Phases present but confirm-after-execute; cash/credit not asked | **VIOLATED** (ordering, §20) |
| §6 minimal payload; never full DB | Context manager is genuinely minimal (sometimes too minimal) | PASSED |
| §8 validation rules metadata-driven | Read but 4 of 10 inert; DB triggers are the real gate | PARTIAL |
| §9 confirmation lifecycle PLAN→VALIDATE→PREVIEW→ASK→EXECUTE | EXECUTE→…→ASK; approve = re-execute (duplicates) | **VIOLATED** |
| §10 atomicity; "invoice created, journal failed = never" | No transaction anywhere; journals not even part of document flows | **VIOLATED** |
| §11 13-state machine recorded in ai.execution_sessions | Phase enum matches `current_phase`; code writes it to `status` | BROKEN (C2) |
| §13 RLS tenant isolation | Service-role client bypasses RLS; isolation is Python-side org filters (sound but single-layer) | PARTIAL |
| §14 secrets in Vault only | Correct: Vault + service-role-only helper | PASSED |
| §15 full traceability (sessions/steps/tool_calls/results/audit_events) | Intended writes all fail; audit_events never written | BROKEN |
| §16 ERP tables are financial truth | Views/triggers enforce this | PASSED |
| §17 versioning recorded per execution | `constitution_version` column doesn't exist; version stored nowhere at runtime | BROKEN |

---

## PART 10 — Gemini Runtime Context Audit

What Gemini actually receives: 7 static rules + Constitution[:8000] as system instruction; user content = org name/currency, current period name/dates, up to 5 customer/supplier names, up to 10 account code+names (when rules allow), then the user message. **Not included:** current date, financial year, user role/permissions, tool parameter schemas, conversation history, prior tool results, attachment data, project/bank-account context (fetchers exist but gated to slugs never active for most intents). Size: compact (good). Security: no secrets, no SQL, no cross-org data (context built server-side from org-scoped repos).

---

## PART 11 — User Request Lifecycle (as-implemented trace)

1. Frontend `aiExecute` → POST `/api/ai/execute` with Bearer JWT + `{message, attachments?}`.
2. `authenticate_header` → JWT path: decode → `sub` → membership (first ACTIVE) → role. *(Header path: org spoofable.)*
3. `agent.execute` → `create_execution_session` → **FAILS** (C1) → exception → `AgentResponse(FAILED, "An unexpected error occurred")`.
4. *(If C1 were fixed:)* planner → optional clarification → context → Gemini (one shot) → tool calls executed sequentially with permission+validation → validation of results → confirmation (post-hoc) → verify (journals only) → result row (fails, C1) → response.
5. Clarify/confirm resume by re-running `execute()` with the original message stitched to the answer — new session, duplicate side effects on approval.

---

## PART 12–14 — Agent Reasoning / Planner / Context Manager Audits

**Agent:** single-pass orchestration; no re-evaluation phase (Phase 4 of protocol = Gemini single call); no iterative investigate→plan loop; state machine writes all fail (C1/C2). **Planner:** deterministic regex; correctly ordered; fails contextual duties: payment-method disambiguation (§20), Dell-as-brand investigation (§17 — passes by luck of regex, not by design), date absence (defaults silently to today in services — silent date behavior). **Context manager:** architecture correct (rules→sources→repos); coverage gap 8/26 intents; accounts only via `chart_of_accounts` slug; reports prefetch incomplete (trial balance only).

---

## PART 15–19 — Tool Architecture / Validator / Accounting Engine / Services / Repositories

**Tools:** 36 registered, flags match DB, handlers wrap services. Defects: parameterless declarations (C5), `organization_id` collision risk, `record_expense_payment` mis-wiring, KeyError on missing required kwargs (e.g., `kw["customer_id"]`) surfaced as generic errors.

**Validator:** runs for mutations only when auth present (always true via API) — good placement; effective checks: entity existence (customer/supplier/account), amount non-negative, ISO dates, PERIOD_OPEN via RPC. Inert: BALANCED, PERIOD_OPEN(post_journal), 2 slug-dead rules. DB triggers remain the true last line — confirmed present.

**Accounting engine:** logic correct (Part 3), **disconnected** (C4). `verify_journal` works.

**Services:** org-scoped; verify counterparties; create single rows; **no journals, no allocations, no engine calls** — `link_journal_to_*` repo helpers exist but are never called by services. `classify_expense` heuristic-only.

**Repositories:** uniformly org-scoped except `get_journal_lines`; RPC transitions rely on DB functions (good) but invoked via service role (org safety = inside function, unverified here); insert shapes match live columns for public tables (invoices/bills/payments/receipts/expenses verified against schema listing).

---

## PART 20–21 — Authentication & Multi-Tenancy Audit

JWT path: solid (HS256, expiry checked, membership-resolved org — org never taken from client). Weaknesses: audience not verified; default-secret fallback; first-membership ambiguity; header fallback org spoof (C7). Multi-tenancy: every repository call passes `organization_id` (single defense layer; service role bypasses RLS by design). No query path was found where Gemini can steer cross-org reads (context and tools all org-bound server-side). `search_ilike` always org-filtered. **One latent hole:** `get_journal_lines(entry_id)` un-scoped; reachable only with an entry id already verified org-owned — defense-in-depth fix recommended.

---

## PART 22–26 — Accounting Integrity / Clarification / Confirmation / Execution / Verification

**Integrity:** DB layer enforces balance, open periods, immutability (verified triggers + in-DB tests per prior sessions). Python layer undermines it: documents without journals (receivables/payables never hit the GL), Gemini-authored lines, no atomicity. **Clarification:** loop works at the API level but loses session identity (new session per resume; old session stuck; `ai.clarifications.user_response` never written back). **Confirmation:** see C3 — post-hoc + duplication; `user_confirmed`/`confirmed_at` never recorded. **Execution audit:** all writes fail (C1); `step_type_code` enum mismatch. **Verification:** only journals verified; documents/payments/receivable balances never re-read; `verification_code` enum {VERIFIED, UNVERIFIED, FAILED} compatible.

---

## PART 27–29 — Reporting / Invoice / Attachment Audits

**Reporting:** views exist and are org-scoped; `get_trial_balance` ignores date/period params (no "Trial Balance for August" filtering); GL date filtering documented as not implemented; report data flows view→repo→service→tool→Gemini (values never invented — good). **Invoice:** multi-line invoice architecture exists in DB (`invoices` + `invoice_items`, `invoice_item_repository` present) but `create_invoice` service handles **header only**; no tax computation; no journal; frontend has no invoice page. **Attachments:** frontend collects files into `AttachmentRef` with `blob:` URLs; backend `UserRequest.attachments` accepted and ignored end-to-end; no storage bucket, no extraction. Scenario 10 impossible.

---

## PART 30–33 — Error-Path / Security / Performance / Dead Code

**Error paths:** agent catches everything → FAILED response (correct shape); tool router isolates handler exceptions; DB triggers abort bad postings. Partial-state risks: invoice-without-journal (systemic), entry-then-lines two-step, no compensating actions. **Security:** Vault key (good); no SQL injection surface (PostgREST parameterized; no raw SQL from user input); prompt-injection surface limited (tools deny-listed, permissions enforced server-side); logging includes message content (PII consideration); CORS configurable; secrets set in `.env` (not committed per `.gitignore`); C7 remains the top auth hole. **Performance:** context fetch is lean; permission cache good; N+1s: `get_tools_for_capability` loops per slug (unused path), clarifications add 2 queries; no unbounded reads (all limit-capped). **Dead/duplicated:** Part 2 inventory; `generate_text`; engine builders; `_INTENT_PATTERNS` fallbacks; duplicated confirmation policy sources.

---

## PART 34 — Integration Matrix

| Component | Exists | Correct | Integrated | Tested | Secure | Prod-ready |
|---|---|---|---|---|---|---|
| Frontend | ✅ | ✅ | ⚠️ (attachments, org ctx) | ❌ | ✅ | ❌ |
| FastAPI | ✅ | ✅ | ✅ | partial | ⚠️ | ❌ |
| Authentication | ✅ | ⚠️ | ✅ | ❌ | ❌ (C7) | ❌ |
| Agent | ✅ | ⚠️ | ❌ (C1/C3) | ❌ | – | ❌ |
| Planner | ✅ | ⚠️ | ✅ | ✅ (39 UT) | – | ⚠️ |
| Context Manager | ✅ | ⚠️ | partial | ❌ | ✅ | ⚠️ |
| Gemini Client | ✅ | ⚠️ | ❌ (C5/C8) | ❌ | ✅ | ❌ |
| Tool Router | ✅ | ⚠️ | ❌ (C5) | partial | ✅ | ❌ |
| Tools (36) | ✅ | ⚠️ | partial | registry only | ✅ | ❌ |
| Validator | ✅ | ⚠️ | partial | ❌ | ✅ | ⚠️ |
| Accounting Engine | ✅ | ✅ | ❌ (C4) | ❌ | – | ❌ |
| Services | ✅ | ⚠️ | partial | ❌ | ✅ | ❌ |
| Repositories | ✅ | ✅ | ✅ | ❌ | ⚠️ | ⚠️ |
| Supabase DB | ✅ | ✅ | ✅ (schema side) | in-DB tests | ✅ | ✅ |
| AI Control Plane (runtime) | ✅ schema | ✅ metadata | ❌ (C1/C2) | ❌ | ✅ | ❌ |
| Reporting | ✅ | ⚠️ (no dates) | ✅ | ❌ | ✅ | ⚠️ |
| Invoice system | partial | ❌ | ❌ | ❌ | – | ❌ |
| Attachments | ❌ | – | ❌ | ❌ | – | ❌ |
| Conversation | partial | ⚠️ | ❌ | ❌ | – | ❌ |
| Audit trail | ✅ schema | – | ❌ (C1) | ❌ | – | ❌ |

---

## PART 35 — End-to-End Scenario Traces (required 10)

All 10 scenarios share Step-1 failure: `create_execution_session` throws → **FAILED**. Traces below assume C1/C2 fixed, and expose the next failure per scenario:

1. **"I bought a Dell laptop for Rs.150,000."** → intent `record_purchase` (no cash/credit match) → no clarification, no confirmation → tools per planner: search_supplier(“Dell”?)—entity regex captures nothing → Gemini one-shot must decide; with C4, no journal is created unless Gemini hand-composes `prepare_journal` lines (Constitution violation). **Fails §17/§18/§20 intent.**
2. **"…from ABC Computers for Rs.150,000 on credit."** → `record_credit_purchase`; clarification only if amount/supplier missing (both present) → confirmation REQUIRED but only after execution: `create_supplier`?/`create_purchase_bill` + (never) journal run first → duplicate on approval. **C3.**
3. **"Sold services to XYZ for Rs.200,000 and received payment."** → regex falls to `record_sale` (no cash-sale match) → no confirmation → receipt + sale semantics conflated; customer auto-creation possible via Gemini tool choice; no journal (C4).
4. **"…on credit."** → `record_credit_sale` → confirmation post-execution (C3); invoice without journal (C4).
5. **"Create an invoice for ABC Technologies for Rs.500,000."** → `create_invoice`; customer name captured; context: customer_master+COA (rule exists!) → best-case path; still: header-only invoice, no items, no journal, no tax.
6. **"Show me ABC Technologies' ledger."** → `customer_balance` (rule exists) → `get_customer_ledger` via `v_customer_ledger` → would work post-C1; ledger empty because journals were never created by any flow.
7. **"How much do we owe ABC Computers?"** → `supplier_balance` rule exists → supplier ledger + bills + payments → works post-C1 (data permitting).
8. **"Trial Balance for August."** → `generate_trial_balance` → `get_trial_balance` takes **no date params** → whole-history TB returned; August not honored; current date unknown to Gemini.
9. **"Record Rs.50,000 internet expense."** → `record_expense` → `create_expense` row only; no journal; classify_expense heuristic ("internet"→Utilities?); no payment-method question.
10. **"Upload this receipt and record the expense."** → attachments ignored end-to-end → impossible.

**Database effects per scenario (as-implemented):** scenario 2/4/5 would insert `purchase_bills`/`invoices` rows (org-scoped, numbered by trigger) and `ai_*` nothing (C1); journal_entries/journal_lines **not touched**; ledgers/TB/BS unaffected → statements diverge from documents.

---

## PART 36–39 — Issue Register (summary counts)

- **CRITICAL (7):** C1 control-plane schema mismatch; C2 status/phase enum conflation; C3 confirmation-after-execution + duplicate re-execution; C4 accounting engine disconnected / Gemini-authored journals; C5 tool parameters never exposed to Gemini; C6 no atomicity; C7 header-auth org spoofing (all envs).
- **HIGH (9):** H1 Gemini single-shot loop (no tool-result feedback, no history); H2 empty live DB + no onboarding path (auth 403 for every real user); H3 attachments ignored; H4 clarification/confirmation resume creates new sessions (orphaned state, context loss); H5 session detail endpoint 500s (`session_id` filter); H6 `record_expense_payment` mis-wired; H7 dead/inert validation rules (slug + shape); H8 context rules cover 8/26 intents; H9 document flows create no journals (receivable/payable never in GL — accounting corollary of C4).
- **MEDIUM (10):** JWT `verify_aud` off + default-secret fallback; first-membership org ambiguity; permissions cache no TTL; Constitution truncated; planner cash/credit & supplier-for-cash issues; `get_journal_lines` unscoped; report date filtering absent; `step_type_code` mismatch; migration drift 35 vs 29; `rls_auto_enable` anon-executable WARN.
- **LOW/INFO (8):** dead code items; `generate_text`; docstring inaccuracies (trigram claim); `MAX_TOOL_ITERATIONS` unused; `on_event` deprecation; PII in logs; frontend placeholder routes; duplicated confirmation-policy sources.

---

## PART 40 — Recommended Fix Order → see REMEDIATION PLAN (next section)

---

## PART 41 — Production Readiness Assessment

| Tier | Rating | Rationale |
|---|---|---|
| Local development | **PARTIAL** | Server boots, health OK, 39/39 unit tests, DB reachable; no request completes |
| Internal testing | **NOT READY** | C1/C2 block every execute; no seeded org/accounts/periods |
| Hackathon demo | **NOT READY** | Same blockers; would require hotfixes + data seeding |
| Beta users | **NOT READY** | C3/C4/C6/C7 create financial & security risk |
| Production | **NOT READY** | All of the above |

---

## PART 42 — Final Architecture (target-state, post-remediation)

```
Frontend (JWT + org context + real attachment upload)
→ FastAPI (JWT-only auth, org from membership)
→ agent.execute (plan → validate → PREVIEW → CONFIRM → execute → verify → respond)
→ context_manager (rules for ALL intents, from ai.context_rules)
→ Gemini (full Constitution, tool schemas from ai.tool_parameters, iterative loop with tool results)
→ tool_router (permissions + parameter validation from ai.tool_parameters)
→ services (atomic: document + items + journal via accounting_engine + allocations)
→ repositories (org-scoped; DB transactions via RPC)
→ Supabase (RLS + triggers + views = financial truth)
→ ai.* execution audit (correct columns/enums) → structured AgentResponse → frontend
```

---

# REMEDIATION PLAN (Phase-gated; no changes made during audit)

**PHASE 1 — SECURITY (C7, JWT hardening)**
1. `auth.py: authenticate_header` — delete header fallback or gate behind `settings.is_production is False` AND validate `x_organization_id ∈ user memberships`. Test: spoof attempt → 401/403.
2. `config.py` — fail fast when `jwt_secret == "change-me"` in production; enable `verify_aud` with audience "authenticated".
3. DB: `REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, authenticated;`

**PHASE 2 — CONTROL-PLANE WRITE FIX (C1, C2)**
4. `database.py` — rewrite all six writers to actual columns: `user_request`, `instruction_version_id` (FK to ai.instruction_versions), `model_configuration_id` (FK), `execution_session_id`, `input_payload`/`output_payload`, `required_information`, `description`, `result_payload`; resolve `tool_id` FK from slug; write phases to `current_phase`, statuses to `session_status_code` {PENDING→PLANNING→WAITING_FOR_USER→EXECUTING→COMPLETED/FAILED/CANCELLED}; steps use `step_type_code` {REASON,RETRIEVE,VALIDATE,CONFIRM,EXECUTE,VERIFY,RESPOND}.
5. `models/schemas.py` — split `SessionStatus` (7) from `ExecutionPhase` (13).
6. `main.py get_session` — fix child-table filters to `execution_session_id`.
7. Integration test: full execute against staging DB asserts session/steps/tool_calls rows.

**PHASE 3 — CONFIRMATION LIFECYCLE (C3)**
8. `agent.py` — reorder: plan → validate (pre-flight via validator + engine preview) → create confirmation with preview payload (action, entities, journal preview from accounting_engine) → STOP. On approval: resume the SAME session (status EXECUTING) and execute tools once. On rejection: REJECTED, nothing executed. Never re-run `execute()`.
9. `ai.confirmations` — write `user_confirmed`, `confirmed_at`, `user_id` on decision.

**PHASE 4 — ACCOUNTING INTEGRITY (C4, C6, H9)**
10. Wire services to the engine: `invoice_service.create_invoice` → resolve AR/Revenue accounts → `accounting_engine.record_credit_sale`; same for purchase (`record_credit_purchase`/`record_cash_purchase`), expense (`record_expense`), receipts/payments (`record_customer_receipt`/`record_supplier_payment` + payment rows + allocations).
11. Atomicity: implement a single PostgREST RPC (e.g., `public.execute_accounting_transaction(jsonb)`) wrapping document + items + journal + tax + audit in one DB transaction; services call it. Fallback: accept two-step but never expose un-journaled documents (compensating delete).
12. Add invoice items + tax handling to `create_invoice` (use `invoice_item_repository`).
13. Tests: for each of the 10 scenarios assert DB effects (tables read/inserted, journal lines, balance).

**PHASE 5 — GEMINI INTEGRATION (C5, H1)**
14. `tool_router.get_gemini_tool_definitions` — load `ai.tool_parameters` (join ai.tools, status IMPLEMENTED), emit typed properties (string/number/boolean/array/uuid→string), required list; drop the `organization_id` property (inject server-side; strip it from args before handler call).
15. `gemini_client.generate_with_tools` — implement the real loop: send tool results back as function_response parts until no function_call or `max_tool_iterations`; keep last N turns as history; include current date, FY, role, and allowed-tool list in system/user context; raise Constitution budget (or send distilled rule set) — keep under model limits.
16. Fix `_record_expense_payment` → dedicated implementation (load expense/bill → pay + settle).

**PHASE 6 — PLANNER & CONTEXT (H8, §17–§21)**
17. `planner.py` — ask cash-vs-credit when unstated for purchases/sales; do not require supplier for cash purchase; add payment-method and date-materiality questions; map `record_purchase/record_sale` fallbacks to explicit clarify-first.
18. Seed `ai.context_rules` for all remaining intents (18) or default rule (org+FY+period+ hinted entities); extend `_fetch_reports` for balance_sheet/income_statement; pass current date + FY to Gemini.

**PHASE 7 — VALIDATOR & RULES (H7)**
19. Fix `applies_to` slugs in `ai.validation_rules` (record_customer_payment→record_customer_receipt; record_expense→create_expense); re-shape BALANCED/PERIOD_OPEN for post_journal to re-read the entry from DB rather than tool args; parameter validation against `ai.tool_parameters` in tool_router.

**PHASE 8 — API & FRONTEND (H3, H4, H5)**
20. Attachments: Supabase Storage bucket + signed URL upload + backend extraction (Gemini vision) or explicitly reject with clear error until built.
21. Conversation: honor `conversation_id` (persist, feed history), keep clarify/confirm on the same session (fix H4), sessions endpoint already aligned post-Phase-2.
22. Frontend: pass conversation_id; add org context display; remove placeholder dashboard data or label as demo.

**PHASE 9 — DATA PROVISIONING (H2)**
23. Onboarding path: create organization + membership + FY + periods + chart of accounts from `account_templates` (148 items ready) — backend endpoint or SQL runbook; seed one demo org for testing.

**PHASE 10 — HARDENING & SYNC**
24. Mirror the 10 remote-only migrations into `database/migrations/`; add migration-sync check to CI.
25. `get_journal_lines` org filter; permissions cache TTL; deprecate `on_event`; scrub message content from logs (hash/truncate); dead-code removal (`generate_text`, unused planner fallbacks after Phase 6).

**Suggested execution order:** Phase 2 → 1 → 3 → 5 → 4 → 6 → 7 → 9 → 8 → 10 (unblock requests first, then close security, then consent, then Gemini, then accounting, then data, then API/frontend, then hygiene). Each phase ends with: re-read files, dependency check, live-DB compatibility check, pytest + new integration tests, and re-run of affected scenarios from Part 35.

**Approval requested before any implementation.**
