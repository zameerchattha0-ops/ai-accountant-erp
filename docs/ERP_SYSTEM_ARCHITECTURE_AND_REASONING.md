# ERP SYSTEM ARCHITECTURE AND REASONING — CONTINUITY BLUEPRINT

**Project:** AI Accountant — AI-Native Accounting & Financial ERP ("Ai Accountant", developed by Zameer Haider)
**Document version:** 1.0 · **Date of audit:** 2026-08-30 · **Mode:** Read-only audit + documentation (no code/DB modified)
**Audited sources:** Local codebase (`Ai Accountant/ERP/`), SQL migrations (`database/migrations/`), live Supabase project `gghkbpdaqogncbrwzmpp` (via Supabase MCP), `ERP_AGENT_CONSTITUTION.md` v1.2.0, `CODEBASE_INTEGRATION_AUDIT.md` v1.0, `IMPLEMENTATION_CHECKLIST.md` (Session 2), `FRONTEND_MASTER_BUILD_PROMPT.md`.

---

## ⚠️ HOW A FRESH AGENT MUST USE THIS DOCUMENT

1. **This is a continuity blueprint, not a redesign proposal.** Extend the existing system along its existing grain; never reset, replace, simplify, or "modernise" established architecture.
2. Status labels used throughout:
   - **[IMPLEMENTED]** — verified in code and/or live DB.
   - **[PARTIAL]** — exists but has known gaps (listed).
   - **[MISSING]** — designed/intended but not built.
   - **[BROKEN]** — exists but does not work (evidence given).
   - **[INTENDED]** — future requirement recorded by the owner; do not build without instruction.
3. **Do not invent architecture that is not documented here or present in code.** New work must be justified against the Constitution (`ERP_AGENT_CONSTITUTION.md` — immutable governance) and recorded in a new session checklist.
4. Governance hierarchy (from the Constitution):
   ```
   ERP_AGENT_CONSTITUTION.md (git, immutable governance)
        ↓ governs
   AI Control Plane (Supabase ai.* schema, runtime configuration)
        ↓ read by
   Agent Runtime (Python: agent.py, planner.py, …)
        ↓ drives
   Gemini (reasoning ONLY — never computes accounting) + Backend services
        ↓ deterministic
   Accounting Engine → ERP tables (authoritative financial truth)
   ```
5. **Nothing is ever sent to Gemini that it must compute financially.** Gemini interprets language and selects tools. The Accounting Engine computes debit/credit. ERP tables are truth; if `ai.tool_calls` and `journal_entries` disagree, ERP tables win (Constitution §16).

---

## 1. PROJECT PURPOSE AND BUSINESS MODEL

**[IMPLEMENTED]**

- **Product:** multi-tenant, AI-first accounting ERP. Current owner profile: "Zameer Labs PVT Ltd" (Pakistani software house, base currency PKR). A seeded test org "Test Traders (Pvt) Ltd" exists alongside it.
- **Core UX philosophy:** the user does NOT fill accounting forms — they *tell the AI what happened* ("I bought a laptop from ABC Computers for Rs.150,000 on credit") and the Agent interprets, clarifies, plans, validates, posts, and reports back. Module screens (Sales, Purchases, Banking, Reports…) exist for browsing/verification; the AI chat box on the Dashboard is the primary transaction entry point.
- **Deployment model (current):** local full-stack dev setup:
  - Backend: Python FastAPI + uvicorn at `http://localhost:8000` (`Ai Accountant/ERP/app/`).
  - Frontend: Next.js 15 (App Router) + React 19 + Tailwind v4 at `http://localhost:3000` (`Ai Accountant/ERP/frontend/`).
  - Database: hosted Supabase project `gghkbpdaqogncbrwzmpp` (Postgres + Auth + Vault). **No Supabase Edge Functions are deployed (count = 0)** — all backend logic lives in the Python service.
  - AI: Google Gemini `gemini-2.5-flash` via `google-genai` SDK; API key stored in **Supabase Vault**, retrieved at runtime through `public.get_gemini_api_key()` (SECURITY DEFINER, service-role only). Key never appears in `.env` or code. **[IMPLEMENTED]**
- **Launcher:** `Runapp.bat` kills stale ports 8000/3000, validates the venv/.env/deps, starts uvicorn (8000) with a health-wait loop, npm-installs + starts Next.js (3000), opens the browser; step logging to `runapp_log.txt`. **[IMPLEMENTED]**

---

## 2. AI-NATIVE ERP PHILOSOPHY

**[IMPLEMENTED — the governing doctrine, from Constitution v1.2.0 (ACTIVE in ai.instruction_versions)]**

1. **10-phase reasoning protocol:** Understand → Determine Requirements → Acquire Context → Re-evaluate → Plan → Validate → Confirm → Execute → Verify → Respond.
2. **13-state execution state machine** (`ai.execution_phase_code`): RECEIVED, INTERPRETING, PLANNING, CONTEXT_LOADING, AWAITING_CLARIFICATION, VALIDATING, AWAITING_CONFIRMATION, EXECUTING, VERIFYING, COMPLETED, FAILED, CANCELLED, REJECTED — written to `ai.execution_sessions.current_phase`. A parallel 7-value lifecycle (`ai.session_status_code`: PENDING, PLANNING, WAITING_FOR_USER, EXECUTING, COMPLETED, FAILED, CANCELLED) is written to `status`. Mapping lives in `agent._PHASE_STATUS_MAP`. **[IMPLEMENTED]**
3. **Deterministic accounting:** `accounting_engine.py` is the ONLY component that constructs journal lines. Gemini never computes debit/credit. Invariant: TOTAL DEBIT == TOTAL CREDIT.
4. **No assumptions:** missing *material* information triggers exactly ONE clarification question per turn (dynamic, not a fixed script); answered questions are never re-asked (history merge); after `MAX_CLARIFICATION_ROUNDS = 3` (agent.py) the request goes to Gemini with what is known rather than looping.
5. **Relevant-data retrieval:** the entire database is NEVER sent to Gemini. `context_manager.build_context()` resolves `ai.context_rules` (intent → required sources) and fetches only relevant, hint-filtered rows.
6. **Human consent for high-impact actions:** `requires_confirmation` is stored per tool in `ai.tools`; the Agent raises `AWAITING_CONFIRMATION` and *stops before any mutation* (fixed from the original post-execution confirmation bug — see §14).
7. **Full traceability:** every request writes session → steps → tool_calls → clarifications → confirmations → execution_result → audit_events (Constitution §15). Control Plane is metadata; ERP tables are financial truth (§16).
8. **Layered defence:** Gemini proposal → Control-Plane permission check → parameter/structural validation (`validator.py` + `ai.validation_rules`) → DB triggers/constraints as last line.

### 2.1 ERP_AGENT_CONSTITUTION.md and how it is used

- `ERP_AGENT_CONSTITUTION.md` (v1.2.0, 833 lines, in the ERP root next to `app/`) is the **immutable governance document**. It is version-controlled in Git; the DB only tracks metadata in `ai.instruction_versions` (version number, hash, source path, activation).
- **Runtime use:** `gemini_client` loads the FULL file from disk (`config.CONSTITUTION_PATH`) as the Gemini system instructions on every call; `agent.execute()` records `instruction_version_id` on every session so each operation is traceable to the governing version.
- Its sections define: the Control Plane schema (§2), deterministic accounting (§3), intent resolution and clarification rules, context rules, tool contracts and the tool-call protocol, permissions and capability boundaries, validation rules, the confirmation lifecycle, atomicity (§10), the execution state machine, API payload contract, secrets handling (§14 — Vault only), execution traceability (§15), financial truth boundary (§16), and versioning (§17).
- A code change that contradicts the Constitution requires a governance amendment: update the Constitution, bump its version, add a new ACTIVE `ai.instruction_versions` row, retire the old one.

---

## 3. COMPLETE SYSTEM ARCHITECTURE (AS BUILT)

**[IMPLEMENTED]**

```
Browser (localhost:3000)
  Next.js 15 App Router, React 19, Tailwind 4
  ├── Auth: supabase-js (@supabase/ssr) — login / signup / verify-email
  ├── Org context: useOrg() hook → organization_members ⋈ organizations + roles
  ├── AI Chat: AICommandBox (dashboard) → POST {API_BASE}/api/ai/execute
  │      · sends Supabase JWT as "Authorization: Bearer <token>"
  │      · renders clarification / confirmation / result cards
  │      (AIProgress, AIClarification, AIConfirmation, AIActionCard)
  └── Module pages (Sales, Purchases, Customers, Suppliers, Projects, Expenses,
         Payments, Receipts, Banking, Accounting, Reports, AI Activity, Settings)
         — direct Supabase reads via anon key + RLS; mutations mostly AI-first
                    │ HTTPS + Bearer JWT (CORS: localhost:3000)
                    ▼
FastAPI backend (localhost:8000) — "ERP AI Agent" v1.0.0
  main.py routes:
     GET  /api/health
     POST /api/ai/execute   → agent.execute()
     POST /api/ai/clarify   → agent.resume_with_clarification()
     POST /api/ai/confirm   → agent.resume_with_confirmation()
     GET  /api/ai/sessions[/{id}]
  Auth: auth.py — JWT ES256/RS256 via Supabase JWKS; HS256 legacy fallback;
        org ALWAYS resolved from organization_members (never from client)
                    │ service-role key (server only)
                    ▼
Agent orchestration (app/agent.py)
  planner → context_manager → [clarify?] → gemini_client (planning call)
        → confirmation gate (ai.confirmations) → gemini_client (executor call)
        → tool_router → validator → services → accounting_engine
        → verify_journal → execution_result → response
                    ▼
Supabase (project gghkbpdaqogncbrwzmpp)
  ├── public.* — 76 ERP tables (financial truth), 14 reporting views, RPCs, triggers
  ├── ai.*     — 20 Control Plane tables (governance metadata)
  ├── auth.users, vault (Gemini key), storage
  └── RLS on ALL public + ai tables (anon/authenticated; backend uses
        service_role which bypasses RLS by design)
```

### 3.1 Backend component inventory (app/, ~5,100 lines)

| File | Lines | Role |
|---|---|---|
| `main.py` | 206 | FastAPI app, routes, CORS, lifespan (pre-warms Gemini client) |
| `agent.py` | 408 | Orchestrator: request lifecycle, phase/status tracking, clarify/confirm resume |
| `planner.py` | 531 | Regex intent classification, entity extraction, clarification decisions, tools/context/outcome maps |
| `context_manager.py` | 182 | Minimal relevant-context builder (intent-driven, hint-filtered) |
| `gemini_client.py` | 333 | Gemini wrapper: Constitution system prompt, tool defs from `ai.tool_parameters`, tool loop, retries |
| `tool_router.py` | 167 | Registry → permission → validator → handler; builds Gemini tool definitions |
| `validator.py` | 175 | Structural checks + DB `ai.validation_rules` + entity existence + period-open check |
| `accounting_engine.py` | 470 | Deterministic journal builders (credit/cash purchase, credit/cash sale, expense, receipt, payment, transfer), `auto_journal()` dispatcher, `verify_journal()` |
| `auth.py` | 256 | JWT ES256/RS256 (JWKS) + HS256 legacy; AuthContext (user_id, organization_id, role_code, role_permissions) |
| `permissions.py` | 165 | `ai.permissions` capability mapping, role→capability resolution, allow/deny sets |
| `database.py` | 520 | Service client wrapper; ai_* prefix → ai schema routing; control-plane writers (sessions, steps, clarifications, confirmations, results); Vault key fetch |
| `config.py` | 67 | pydantic-settings; Constitution path; model config (no secrets) |
| `models/schemas.py` | 270 | Pydantic: AgentContext, AgentResponse, ExecutionPlan, ToolCall/ToolResult, ExecutionStatus, ValidationResult |
| `tools/__init__.py` | 333 | Registry of 36 tool slugs → handlers → services; several handlers call `auto_journal` |
| `repositories/*` | 17 files | Org-scoped CRUD (accounts, banks, credit notes, customers, expenses, invoice items, invoices, journals, organizations, payments, projects, purchases, purchase returns, quotations, reports, suppliers) |
| `services/*` | 13 files | Business logic (accounting, bank, credit note, customer, expense, invoice, payment, project, purchase return, purchase, quotation, reporting, supplier) |
| `tests/*` | 5 files | Offline unit tests (planner, permissions, tools, control-plane writers) — 39/39 pass **[IMPLEMENTED]** |

### 3.2 End-to-end request flow (canonical)

```
USER REQUEST (natural language, AICommandBox)
→ POST /api/ai/execute (Bearer JWT) → auth → AuthContext
→ agent.execute(): session row in ai.execution_sessions (phase RECEIVED)
→ INTERPRETING: planner.plan() → intent + entities + missing-info check
→ (missing material info?) → AWAITING_CLARIFICATION: clarification row written;
   user answers via /api/ai/clarify → resume_with_clarification() → history
   reloaded from ai.clarifications → execute() re-run with merged answers
→ CONTEXT_LOADING: context_manager.build_context(intent, hints, history)
→ PLANNING: Gemini planning call (tools described but NO executor callable)
→ (ai.tools.requires_confirmation?) → confirmation row + AWAITING_CONFIRMATION;
   user decides via /api/ai/confirm → resume_with_confirmation() → if approved,
   re-run execute() and proceed to the executor call
→ EXECUTING: Gemini executor call (tool loop ≤ MAX_TOOL_ITERATIONS = 10)
→ tool_router.route_tool_call(): registry → authorize_tool() → validate_operation()
   → handler → service → repository → Supabase write
→ document services call accounting_engine.auto_journal() (invoice/purchase_bill/
   expense) or engine.record_* (receipts/payments/transfer) → journal entry + lines
→ VERIFYING: accounting_engine.verify_journal() (balance re-read from DB)
→ ai.execution_results row (verification_status) → COMPLETED
→ USER-FACING RESULT: AgentResponse (summary, accounting_impact, risk_level, data)
```

### 3.3 Component detail (agent.py, planner.py, context_manager.py, gemini_client.py)

**agent.py — Orchestrator [IMPLEMENTED]**
- Owns the lifecycle; constants: `MAX_TOOL_ITERATIONS = 10`, `MAX_CLARIFICATION_ROUNDS = 3`.
- `_PHASE_STATUS_MAP` maps each 13-phase to (session_status, completed) — this is the C2 fix from the audit (phases go to `current_phase`, statuses to `status`).
- Two-call Gemini design (C3 fix): planning call passes NO executor callable (Gemini can propose tools but nothing runs); the confirmation gate sits between planning and the executor call; `resume_with_confirmation(approved=True)` re-runs `execute()` which proceeds to the executor call.
- Clarification resume (`resume_with_clarification`) writes the answer via `resolve_clarification`, reloads the COMPLETE Q&A history (`get_clarification_history`) and re-enters `execute()` with `clarification_history` — so answered values are merged into extraction and never re-asked. `seed_clarification_history` copies prior Q&A into a new session row so history survives the session-per-round design.
- Every phase transition and every step is logged to the Control Plane; step logging failures are non-fatal (warning).

**planner.py — Planner [IMPLEMENTED, regex-based]**
- NOT an LLM. Ordered regex `_INTENT_PATTERNS` classify intent: reports first (`generate_trial_balance`, `generate_balance_sheet`, `generate_profit_loss`, `generate_cash_flow`, `generate_general_ledger`, `customer_balance`, `supplier_balance`, `project_profitability`, ledgers), then new document types (`create_quotation`, `create_credit_note`, `create_purchase_return`, `record_expense_payment`), then mutations (`create_invoice`, `record_credit_sale`, `record_cash_sale`, `record_credit_purchase`, `record_cash_purchase`, `record_expense`, `record_receipt`, `record_payment`, `record_bank_transfer`, …) plus master-data intents (`create_customer`, `create_supplier`, `create_bank_account`, `list_bank_accounts`, …).
- Entity extraction handles amount format variants ("Rs.150,000", "150000", "1.5 lakh"), dates ("today", "yesterday", ISO), payment method hints (cash/bank/transfer/cheque), counterparty names ("from X", "to X", "for X").
- Clarification philosophy (in-code, mirrors Constitution): extract FIRST, reuse answered values, at most ONE question per turn chosen dynamically, trust the LLM when inconclusive (pass hints to Gemini instead of blocking). Cash-vs-credit questions and "no supplier required for cash purchase" rules live here (per audit remediation phase 6; planner still has legacy fallbacks mapped to clarify-first).
- Emits `ExecutionPlan` with: intent, entities, tools (via `_tools_for_intent`), context sources (via `_context_for_intent`), expected outcome (via `_outcome`).
- The Planner never executes DB mutations.

**context_manager.py — Context Manager [IMPLEMENTED]**
- `build_context()` fetches: organization row, current financial year, open accounting period; then, ONLY for sources listed in `ai.context_rules[intent].required_sources` (or hinted by entities): customers (hint-name search, limit 5), suppliers (same), accounts (chart, limit 50, type-filtered), projects, bank accounts (payment/receipt/transfer/expense-payment intents), open documents (ISSUED/PARTIALLY_PAID invoices; OPEN/PARTIALLY_PAID bills — for allocation context), and pre-fetched report summaries (trial_balance, cash_flow).
- Everything is packed into `AgentContext` including `extracted_entities` (authoritative — Gemini must reuse, never re-ask) and `clarification_history` (Q&A pairs — never re-ask).
- **[PARTIAL]** `_fetch_reports` pre-fetches only trial_balance and cash_flow; balance_sheet/income_statement are fetched by the reporting tools at execution time instead.

**gemini_client.py — Gemini Client [IMPLEMENTED]**
- Singleton; initialised once at startup (lifespan) and lazily.
- API key from Vault via `database.get_gemini_api_key()` (fails fast if absent).
- Loads the FULL Constitution markdown from `ERP_AGENT_CONSTITUTION.md` (path in config) as system instructions. **[PARTIAL]** the full document is large; per the audit this stays under model limits today but is a known pressure point (remediation suggested a distilled rule set).
- `generate_with_tools(user_message, context, max_tool_iterations, executor=None)`: builds user content (org context, FY/period, relevant names, extracted entities, clarification history, user request), fetches typed tool definitions from `ai.tool_parameters` (via tool_router), maps JSON-Schema types → Gemini Type enum properly, and loops: on `function_call` → run via executor → feed `function_response` back — until text-only response or iteration cap. With `executor=None` (planning call) tool calls are returned unexecuted.
- Retries: tenacity, 3 attempts, exponential backoff (2–10s).

### 3.4 tool_router, validator, permissions, auth, database (detail)

**tool_router.py — Tool Router [IMPLEMENTED]**
- Execution safety chain: (1) registry lookup — unknown tools rejected; (2) `authorize_tool()` permission check via `ai.permissions` (skipped only when auth is None); (3) for mutations, `validate_operation()` — failures return a ToolResult error, never an exception to Gemini; (4) handler execution with org injected server-side; ValueError → error result, unexpected Exception → generic "unexpected error" (internal details logged, not leaked).
- `get_gemini_tool_definitions()` (C5 fix): loads all IMPLEMENTED tools + their `ai.tool_parameters` rows in bulk, builds typed JSON-Schema (string/integer/number/boolean/array/object), skips `organization_id` (auto-injected server-side, never exposed to Gemini), sorts parameters by position.

**validator.py — Validator [IMPLEMENTED]**
- Always-on structural checks: positive amounts (amount/total/subtotal/unit_price), ISO-valid dates.
- Loads ACTIVE `ai.validation_rules` matching the tool slug (`applies_to`) ordered by priority; supported rule types: `ENTITY_EXISTS` (customer/supplier), `AMOUNT_POSITIVE`, `BALANCED` (|debit−credit| ≤ 0.01), `PERIOD_OPEN`.
- Direct entity existence checks for customer_id / supplier_id / account_id.
- Period check via RPC `get_period_for_date(p_org, p_date)` → status must be OPEN; None (unknown) defers to DB triggers.
- **[PARTIAL]** Known mismatches from the audit not fully re-verified: some seeded rule slugs may not match tool slugs (e.g. `record_customer_payment` vs tool `record_customer_receipt`), and BALANCED/PERIOD_OPEN for `post_journal` evaluate tool ARGS rather than re-reading the entry from DB — the DB trigger still enforces both, so integrity is not at risk, but the pre-flight rule is weaker than intended.

**permissions.py — Permission-Based Tool Routing [IMPLEMENTED]**
- Role hierarchy (organization_roles, rank 1–5): OWNER > ADMIN > ACCOUNTANT > MANAGER > VIEWER.
- `ai.permissions` rows define capabilities (sales, purchases, expenses, payments, reporting, master_data, journal_management) each with `allowed_tools` / `denied_tools` JSON arrays (7 capability rows, 45 allowed-tool references total).
- Role permission strings ("accounting:full", "sales:manage", "reports:read", "ai:full", "org:manage") map to capabilities via `_role_capability_map`.
- `_ALWAYS_ALLOWED` read-only tools (search/get/ledger/classify) bypass capability checks for any authenticated user. OWNER/ADMIN or `ai:full` → everything. Tools not covered by any capability are DENIED by default.
- Process-level cache of permission rows (`invalidate_cache()` exists; **[PARTIAL]** no TTL — audit flagged stale cache risk).

**auth.py — JWT Authentication [IMPLEMENTED]**
- Accepts ES256/RS256 (verify via Supabase JWKS endpoint `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, cached PyJWKClient, 300s lifespan) and HS256 (legacy shared secret from `.env` JWT_SECRET) — chosen by token `alg` header.
- `authenticate()`: Bearer token → sub → user_id → `_resolve_membership(user_id)` (organization_members, ACTIVE) → organization_id → role via role_id (organization_roles: code + permissions array).
- `authenticate_header()` dependency: JWT first; legacy `X-User-Id` header fallback for development — **and even in fallback mode, organization_id is derived from actual membership, never from `X-Organization-Id`** (fixes the audit's org-spoofing issue). **[PARTIAL]** the header fallback itself is still enabled in all environments (audit recommended an is_production gate).

**database.py — Supabase Layer [IMPLEMENTED]**
- Single service-role client (bypasses RLS — by design, server-side only).
- `_table()`: names prefixed `ai_` route to the `ai` schema (e.g. `ai_execution_sessions` → `ai.execution_sessions`).
- Generic helpers: fetch_one/fetch_many/insert_one/update_one (+ select with org filters), `call_rpc`.
- Control-plane writers with CORRECT live columns (C1 fix): `create_execution_session` (user_request, agent_id, instruction_version_id, model_configuration_id, conversation_id…), `set_session_phase` (current_phase + status + completed flags), `create_execution_step` (step_type ∈ step_type_code), `create_clarification`/`resolve_clarification`/`get_clarification_history`/`seed_clarification_history`, `create_confirmation`/`resolve_confirmation`, `create_execution_result` (result_payload, verification_status…), `log_tool_call`.
- `get_gemini_api_key()`: RPC `get_gemini_api_key` (SECURITY DEFINER, service_role only) reading the key from Vault.
- **[PARTIAL]** `get_journal_lines` lacks an organization filter (audit item; repo-level, low risk because entry lookup is org-scoped).

### 3.5 Accounting Engine and tool registry (detail)

**accounting_engine.py — Deterministic Accounting Engine [IMPLEMENTED]**
- High-level builders (each produces balanced 2+ line journals via `accounting_service.prepare_journal`):
  - `record_credit_purchase`: Dr Asset/Expense (supplier-dimensioned), Cr Accounts Payable (supplier-dimensioned). source_type `purchase_bill`.
  - `record_cash_purchase`: Dr Asset/Expense, Cr Cash/Bank. source_type `purchase`.
  - `record_credit_sale`: Dr Accounts Receivable (customer-dimensioned), Cr Revenue.
  - `record_cash_sale`: Dr Cash/Bank, Cr Revenue.
  - `record_expense`: Dr Expense, Cr Cash/Bank payment account (optionally supplier-dimensioned).
  - `record_customer_receipt`: Dr Bank GL, Cr Receivable. `record_supplier_payment`: Dr Payable, Cr Bank GL.
  - `record_bank_transfer`: Dr destination bank GL, Cr source bank GL.
- `auto_journal(document_type, document, …)` — dispatcher (post-audit addition = the C4 fix): for `invoice`, `purchase_bill`, `expense` it resolves default accounts by type (`_resolve_default_account` with fallbacks ASSET→CURRENT_ASSET, LIABILITY→CURRENT_LIABILITY, REVENUE→INCOME) and calls the matching builder with the document id as `source_id`. On failure returns `{"journal_warning": …}` — **the document is NOT rolled back** (deliberate, documented in-code; see atomicity gap §14).
- `verify_journal(entry_id)`: re-reads lines from DB, asserts balanced; called by the agent in VERIFYING.
- `accounting_service.prepare_journal` validates: ≥2 lines, |Σdebit − Σcredit| ≤ 0.01, amounts > 0; creates the entry (DRAFT) then lines. Lifecycle DRAFT → VALIDATED → POSTED (→ REVERSED) enforced by DB triggers + RPCs `validate_journal_entry`, `post_journal_entry`, `reverse_journal_entry`.
- payment_service auto-VALIDATES and auto-POSTS receipt/payment journals immediately (ledgers + cash-flow stay current), then links the journal to the receipt/payment row. **[IMPLEMENTED]**
- **[PARTIAL]** quotation / credit note / purchase return / fixed assets / bank charges have NO auto-journal builders yet (documents post without journals; audit Phase-4 items remain).

**tools/__init__.py — Tool Registry [IMPLEMENTED — 36 slugs, 0 PLANNED]**
- Registry maps every `ai.tools` slug → handler + read_only + description:
  - Customers: search_customer, get_customer, create_customer, get_customer_ledger
  - Suppliers: search_supplier, get_supplier, create_supplier, get_supplier_ledger
  - Accounts: search_account, get_chart_of_accounts, create_account
  - Sales: create_invoice, get_invoice, create_quotation, create_credit_note
  - Purchases: create_purchase_bill, get_purchase_bill, create_purchase_return
  - Expenses: create_expense, classify_expense, record_expense_payment
  - Payments: record_customer_receipt, record_supplier_payment
  - Banking: list_bank_accounts, create_bank_account, record_bank_transfer
  - Journal: prepare_journal, validate_journal, post_journal, reverse_journal
  - Reporting: get_general_ledger, get_trial_balance, get_profit_loss, get_balance_sheet, get_cash_flow, generate_report
  - Projects: create_project, get_project, get_project_profitability
- Mutation handlers for invoice / purchase_bill / expense call `auto_journal()` after document creation; receipt/payment/transfer handlers call `payment_service` which calls the engine directly.
- **[PARTIAL]** `record_expense_payment` has a dedicated handler; whether it fully settles the target bill was an open audit remediation item (Phase 5 #16) — verify at implementation time.

## 4. AI CONTROL PLANE (Supabase `ai` schema — 20 tables)

**[IMPLEMENTED — all RLS-enabled; metadata tables globally readable by authenticated; execution tables org-scoped via execution_session_id]**

| Table | Rows (audit) | Purpose |
|---|---|---|
| agents | 1 | `erp-accounting-agent` v1.0.0, ACTIVE |
| agent_versions | 1 | Release versioning |
| agent_modules | 8 | ORCHESTRATOR → PLANNER → CONTEXT_MANAGER → TOOL_ROUTER → VALIDATOR → ACCOUNTING_ENGINE → REPORTING → RESPONSE_FORMATTER (execution_order 1–8) |
| instruction_versions | 3 | Constitution tracking: v1.0.0 + v1.1.0 ARCHIVED, **v1.2.0 ACTIVE**; source_reference `Ai Accountant/ERP/ERP_AGENT_CONSTITUTION.md`; content_hash currently NULL **[PARTIAL]** |
| model_configurations | 1 | Google gemini 2.5-flash, temp 0.1, top_p 0.95, top_k 40, max_output_tokens 8192, is_default |
| permissions | 7 | Capability → allowed/denied tools (see §3.4) |
| tools | 36 | All IMPLEMENTED; tool_type QUERY/MUTATION/REPORT/SYSTEM; risk_level LOW/MEDIUM/HIGH; flags requires_confirmation / requires_validation / requires_accounting_engine per tool |
| tool_parameters | 98 | Typed input contracts per tool (required, position, description) — consumed by tool_router |
| context_sources | 21 | Approved data sources (sensitivity, access rules) |
| context_rules | 8 | intent → required_sources (create_invoice, customer_balance, generate_financial_statements, generate_trial_balance, project_profitability, record_credit_purchase, record_payment, supplier_balance) — **[PARTIAL]** 8 of ~26 intents covered; context_manager has an in-code fallback map for the rest |
| validation_rules | 10 | ENTITY_EXISTS / AMOUNT_POSITIVE / PERIOD_OPEN / BALANCED per applies_to (create_invoice ×3, create_purchase_bill ×2, post_journal ×2, record_customer_payment, record_expense, …) |
| workflows | 13 | create_invoice, record_cash/credit_sale, record_cash/credit_purchase, record_customer_payment, record_supplier_payment, record_expense, generate_trial_balance, generate_financial_statements, ledgers, project profitability |
| workflow_steps | 92 | Ordered execution sequence per workflow |
| execution_sessions | live | One row per AI request (user_request, agent_id, instruction_version_id, model_configuration_id, conversation_id, current_phase, status) |
| execution_steps | live | REASON/RETRIEVE/VALIDATE/CONFIRM/EXECUTE/VERIFY/RESPOND stages |
| tool_calls | live | Controlled tool invocations (input/output payloads) |
| clarifications | live | Agent questions + user answers (WAITING_FOR_USER → COMPLETED) |
| confirmations | live | High-impact approvals (risk_level, user_confirmed, confirmed_at) |
| execution_results | live | Final verified results (result_payload, verification_status) |
| audit_events | live | Governance audit trail |

**How it is used:** the Agent READS runtime configuration from these tables (tools, parameters, permissions, context rules, validation rules, confirmation policy) and WRITES the execution trail into session/step/call/clarification/confirmation/result/audit tables. It must NOT hard-code values the Control Plane provides.

**Confirmation policy as seeded (from ai.tools):** `post_journal` and `reverse_journal` are HIGH risk (confirmation + validation + engine); `record_customer_receipt`, `record_supplier_payment`, `create_credit_note`, `create_purchase_return`, most document mutations are MEDIUM with `requires_confirmation=true`; `create_customer`/`create_supplier` and journal PREPARE/VALIDATE have confirmation=false; all QUERY/REPORT tools are LOW, no confirmation. **[IMPLEMENTED — the agent honours requires_confirmation]**

## 5. DATABASE ARCHITECTURE (public schema — 76 tables, all RLS-enabled)

**[IMPLEMENTED — 40 migrations applied to the live project; 34 SQL files mirrored in `database/migrations/` (drift noted in §15)]**

Migration order (each builds on the last): `001` extensions/enums/helpers · `002` currencies & taxes · `003` organizations (+members, roles, settings, onboarding) · `004` financial years & accounting periods · `005` chart of accounts (+types, categories, templates with 148 template items) · `006` customers & suppliers (+contacts, addresses) · `007` projects, products, services · `008` journal engine · `009` sales (quotations, invoices+items, credit notes) · `010` purchases & expenses · `011` fixed assets · `012` banking · `013` payments & receipts (+allocations, tax_transactions) · `014` documents & audit · `015` AI execution & reporting · `016` business functions · `017` reporting views · `018` indexes · `019` RLS policies · `020` reference seed · `021` GL view reversal fix · `022–023` security hardening / revoke public execute · `024` numbering trigger security fix · `025` Gemini key Vault helper · `026–029` AI Control Plane schema + governance seed + Constitution v1.2.0 · `030` implemented enum + expose ai schema + seed test org · `031–032` create/fix `create_organization` RPC · `033` org logo · `034` banking/payments/receipts enhancements (multiple bank accounts, single-default trigger).

### 5.1 Domain groups and key relationships

- **Tenancy:** `organizations` (1) → `organization_members` (user_id → auth.users; role_id → organization_roles OWNER/ADMIN/ACCOUNTANT/MANAGER/VIEWER, each with a permissions JSON array) → every business table carries `organization_id` FK. `organization_settings`, `organization_onboarding`, `logo_url`. **Every repository query is org-scoped.** [IMPLEMENTED]
- **Fiscal calendar:** `financial_years` → `accounting_periods` (24 rows: 12 months × 2 orgs; OPEN/CLOSED/LOCKED). RPCs `get_period_for_date`, `close_accounting_period`, `reopen_accounting_period`. Posting refuses closed/locked periods (trigger).
- **Accounting core:** `account_types` (5, with normal_balance) → `account_categories` (26) → `accounts` (per-org COA; 44 rows = 2 orgs × 22) → `journal_entries` (entry_no by trigger, transaction_date, source_type/source_id, currency, totals) → `journal_lines` (account_id, debit, credit, customer/supplier/project dimensions). Guards: `trg_journal_lines_guard`, `trg_journal_lines_totals`, `trg_journal_entries_status`, `prevent_account_cycle`. `account_templates` (7) + `account_template_items` (148) ready for onboarding COA generation. `business_account_recommendations` empty **[MISSING — recommendation engine not built]**.
- **Sales:** `quotations`(+items; DRAFT→SENT→ACCEPTED→REJECTED→EXPIRED→CONVERTED) → `invoices`(+items; DRAFT→ISSUED→PARTIALLY_PAID→PAID / VOID; amount_paid; due_date) → `credit_notes`(+items). Customer FK; project FK on invoices. Numbering via `next_document_number(p_org, p_doc_type, p_prefix)` + SECURITY DEFINER trigger `trg_document_number_assign` over `document_sequences` (concurrent-safe counters; **RLS on document_sequences intentionally has NO policy** — service role only).
- **Purchases:** `purchase_bills`(+items; OPEN→PARTIALLY_PAID→PAID) → `purchase_returns`(+items). Supplier FK. `expenses`(+items, expense_categories) with payment account + supplier FK.
- **Banking:** `bank_accounts` (multiple per org, GL link, is_default single-default trigger) + `cash_accounts` → `bank_transactions`, `bank_statement_imports`/`bank_statement_lines` (**[MISSING]** no import flow), `bank_reconciliations`/`bank_reconciliation_items` (**[MISSING]** no reconciliation flow).
- **Payments:** `payments` (OUTFLOW; payment_direction INFLOW/OUTFLOW) + `payment_allocations` (→ purchase_bills); `receipts` + `receipt_allocations` (→ invoices). Methods: CASH, BANK_TRANSFER, CHEQUE, CARD, ONLINE, OTHER. `tax_transactions` per document.
- **Assets:** `asset_categories`, `fixed_assets`, `asset_depreciation_schedules`, `asset_transactions` — schema complete **[MISSING]** no UI/tooling/depreciation posting.
- **Documents & audit:** `documents`, `document_links`, `audit_logs` (actor_type USER/AI/SYSTEM) — **[PARTIAL]** DB-trigger audit where defined; Python-side writing not comprehensive.
- **Reporting requests:** `report_requests` (report_type enum incl. ledgers, TRIAL_BALANCE, PROFIT_LOSS, BALANCE_SHEET, CASH_FLOW, agings, PROJECT_PROFITABILITY, ACCOUNT_LEDGER, CUSTOM; output JSON/PDF/XLSX/CSV; PENDING/RUNNING/COMPLETED/FAILED) → `generated_reports` (data JSONB, storage_path). **[PARTIAL]** `generate_report` tool exists; async pipeline + PDF/XLSX **[MISSING]**.

### 5.2 Reporting views (14) — read-only truth projections

`v_general_ledger` (handles reversals — migration 021), `v_trial_balance`, `v_income_statement`, `v_balance_sheet` + `v_balance_sheet_summary`, `v_cash_flow`, `v_customer_ledger`, `v_supplier_ledger`, `v_customer_aging`, `v_supplier_aging`, `v_open_receivables`, `v_open_payables`, `v_account_summary`, `v_project_profitability`, `v_recent_transactions`. Repositories read these views; tools surface them; the frontend Reports pages read the same views via Supabase + RLS.

### 5.3 Seeded reference data [IMPLEMENTED]

- Currencies: AED, AUD, CAD, CNY, EUR, GBP, INR, JPY, PKR, SAR, USD. `exchange_rates` empty **[MISSING]** multi-currency handling (PKR assumed everywhere).
- Taxes (Pakistan-specific): Sales Tax (GST) 0% / 5% / **17% default**; WHT on Imports 6%; WHT on Services 8%; Income Tax Corporate 29%.
- Roles: OWNER(1), ADMIN(2), ACCOUNTANT(3), MANAGER(4), VIEWER(5) with permissions JSON arrays.
- COA per org (22 accounts): 1010 Bank, 1020 Cash, 1100 Accounts Receivable, 1300 Prepaid Expenses, 1500 Computer Equipment, 1510 Accum. Depreciation, 2010 Accounts Payable, 2110 Sales Tax Payable, 2130 Accrued Salaries, 3010 Owner Capital, 3200 Retained Earnings, 4010/4020/4030/4050 revenue accounts (naming varies slightly per org — template-driven, intended), 4900 Other Income, 6010 Salaries, 6020 Freelancers, 6100/6130 Office Expenses, 6100 Cloud Infrastructure, 6110 Software Subscriptions, 6120 Internet, 6150 Hardware Purchases, 6200 Depreciation Expense, 6300 Bank Charges.
- Orgs: `Test Traders (Pvt) Ltd` (test seed, fixed UUIDs, OWNER user `00000000-0000-4000-8000-000000000001`, org `00000000-0000-4000-8000-000000000010`) and `Zameer Labs PVT Ltd` (SOFTWARE_HOUSE, PKR — the owner's real org created via signup → onboarding → `create_organization` RPC).

---

## 6. BUSINESS LOGIC AND REASONING RULES (domain by domain)

### 6.1 Customers / Suppliers — one-off vs recurring counterparty logic [IMPLEMENTED — core rule of the system]

- The Agent must NOT invent master data. "I bought a Dell laptop for Rs.150,000" → "Dell" is a PRODUCT description, not a supplier; the Agent must NOT auto-create a supplier named Dell. A cash purchase needs NO supplier at all.
- "I bought a laptop from ABC Computers for Rs.150,000 on credit" → "ABC Computers" IS a recurring counterparty (credit requires a payable ledger) → search suppliers first; if genuinely absent, ask/confirm creation ("ABC Computers is not in your suppliers. Create it?") or create with confirmation per tool policy (`create_supplier` confirmation=false but the planner routes it explicitly).
- Symmetric rule for customers on credit sales. Party codes are auto-assigned by trigger (`trg_party_code_assign`).
- These exact cases are in `IMPLEMENTATION_CHECKLIST.md` §"Deep Reasoning + Integration Tests" and partially in `tests/test_planner.py` (offline assertions).

### 6.2 Cash vs credit logic [IMPLEMENTED]

- Credit purchase → document `purchase_bills` + journal Dr Expense/Asset, Cr Accounts Payable (supplier-dimensioned). Supplier REQUIRED.
- Cash purchase → journal Dr Expense/Asset, Cr Cash/Bank. NO supplier, NO bill row required.
- Credit sale → `invoices` + Dr Receivable, Cr Revenue (customer-dimensioned). Cash sale → Dr Cash/Bank, Cr Revenue.
- If the wording does not state cash or credit, the planner/Gemini must ASK (material missing info) — never assume.
- Payment method matters for receipts/payments: bank vs cash changes the GL credit/debit side (`_resolve_bank_gl_account`, cash_account fallback).

### 6.3 Invoices / Quotations / Credit notes [IMPLEMENTED documents; PARTIAL accounting]

- `create_invoice` (tool): invoice + items (multi-line supported via invoice_item_repository) + `auto_journal` (Dr Receivable, Cr Revenue). Tax fields exist (tax_transactions, Sales Tax Payable 2110) but **tax computation is not wired into auto_journal yet** **[PARTIAL]**.
- Quotations: full CRUD + status lifecycle, NO journal (correct — non-accounting document until converted; conversion quotation→invoice **[MISSING]**).
- Credit notes: CRUD + reason required; reduces receivable conceptually but **no auto-journal builder yet** **[PARTIAL]**.
- Invoice numbering per org per type via document_sequences; templates exist in the frontend (Minimal/Modern/Professional print templates).

### 6.4 Payments / Receipts / Banking [IMPLEMENTED]

- `record_customer_receipt`: receipt row → auto-journal Dr Bank GL / Cr Receivable → validate + POST → link journal → optional allocation against invoice → update invoice amount_paid/status (PAID / PARTIALLY_PAID).
- `record_supplier_payment`: symmetric (Dr Payable / Cr Bank GL; allocation against purchase_bills).
- `record_bank_transfer`: two bank accounts (source resolved by name/id, destination likewise), Dr destination GL, Cr source GL.
- `create_bank_account`: bank row + linked GL account creation (chart of accounts 1010 Bank parent); only one default account per org (DB trigger).
- `record_expense_payment`: pays an expense/bill (see §3.5 partial note).
- Statement import + reconciliation tables exist; flows **[MISSING]**.

### 6.5 Journals / Ledgers / Trial Balance / Financial Statements [IMPLEMENTED]

- Only path to GL: journal_entries/journal_lines via the engine (or the explicit prepare→validate→post tool chain, which Gemini may use for non-standard entries; posting requires confirmation, HIGH risk).
- All statements are views over posted entries; reversal support (reverse_journal, HIGH risk, confirmation; v_general_ledger excludes/marks reversed entries — migration 021).
- Trial balance re-reads account balances; P&L, balance sheet (with summary), cash flow (payment_direction/method-driven) all available to the AI and the Reports UI.

## 7. AI CLARIFICATION, CONTEXT RETENTION AND NO-ASSUMPTION RULES

**[IMPLEMENTED]**

- **Clarification lifecycle:** missing material info → `ai.clarifications` row (question, required_information[], options[], status WAITING_FOR_USER) + session → AWAITING_CLARIFICATION / WAITING_FOR_USER → frontend `AIClarification` card → user answer via `/api/ai/clarify` → `resolve_clarification` (status COMPLETED, answered_at) → full Q&A history reloaded → `execute()` re-run with history merged. One question per turn; max 3 rounds then delegate to Gemini with hints. `scripts/smoke_test.py` proves this exact chain against the live DB ("I bought a laptop from ABC Computers on credit." — deliberately amount-less → expects AWAITING_CLARIFICATION and verifies session/step/clarification rows).
- **Context retention:** `seed_clarification_history` copies answered Q&A into each new session row (session-per-round design) so `get_clarification_history` stays complete. `conversation_id` column exists on sessions; **[PARTIAL]** multi-turn conversation threading beyond clarification rounds (feeding prior session results into new requests) is not implemented — audit Phase-8 #21.
- **No-assumption rules (must be preserved):**
  1. Never assume cash vs credit — ask.
  2. Never invent suppliers/customers from product-like nouns; credit requires a real counterparty.
  3. Never assume an amount — ask (smoke test relies on this).
  4. Never assume a bank/cash account when multiple exist and method unstated — ask or default per org settings.
  5. Never compute debit/credit — propose intent; the engine posts.
  6. Never re-ask answered questions (history is authoritative).
  7. Never send the whole DB — context_rules decide sources.
- **Relevant-data retrieval:** enforced in `context_manager` (hint-filtered, source-gated, limits 5–50) — never table dumps.

## 8. VALIDATION, TOOL EXECUTION AND ACCOUNTING INTEGRITY

**[IMPLEMENTED with noted partials]**

- Layer 1 Control-Plane permissions (role → capability → tool).
- Layer 2 `ai.validation_rules` + structural validation (amounts, dates, entity existence, period open).
- Layer 3 Confirmation gate BEFORE any mutation for `requires_confirmation` tools; user decision recorded; rejection → REJECTED terminal state; approval re-enters execute() (planner/Gemini will produce the same plan; tool args were already validated).
- Layer 4 Engine balance invariant + DB triggers (journal line guards, totals, status lifecycle, period lock).
- Layer 5 `verify_journal()` re-read post-write; `ai.execution_results.verification_status` = VERIFIED/UNVERIFIED/FAILED.
- **Atomicity gap [BROKEN-by-design → INTENDED fix]:** no single DB transaction spans document + items + journal (Constitution §10 mandates atomicity; audit remediation proposes a `public.execute_accounting_transaction(jsonb)` RPC). Currently: document insert → journal insert → validate → post, as separate writes; `journal_warning` path leaves un-journaled documents visible. This is the top known integrity debt.

---

## 9. AUTHENTICATION, AUTHORIZATION, RLS, MULTI-TENANCY

**[IMPLEMENTED]**

- **Supabase Auth:** email/password with email verification (frontend login/signup/verify-email). Session JWT sent by the frontend to FastAPI. Two users exist (owner's gmail account + seeded test OWNER).
- **Backend JWT:** ES256/RS256 via JWKS + HS256 legacy fallback; org resolved from membership; role + permissions resolved from organization_roles.
- **Authorization:** tool-level via ai.permissions + role capability map (VIEWER effectively read-only; OWNER/ADMIN full). Org-level: org ALWAYS from membership.
- **RLS:** enabled on ALL 76 public + 20 ai tables. Policies: org-scoped `*_org_access` ALL policies using `is_org_member(target_org)` / `has_org_role(target_org, min_rank)` SECURITY DEFINER helpers (public execute revoked — migration 023); global-read SELECT policies for shared metadata (currencies, exchange_rates, ai metadata); `document_sequences` deliberately has NO policy (service-role only). Advisors run after DDL (security advisor was used during hardening migrations).
- **Service role:** backend only, in `.env` (never shipped to browser); frontend uses anon key + RLS for direct reads.

## 10. ERROR HANDLING

**[IMPLEMENTED]**

- Gemini calls: tenacity retries (3×, exponential); failures raise → agent catches → session FAILED with user-safe summary.
- Tool execution: ValueError → explicit message; unexpected → generic message + logged detail (no internal leak).
- Control-plane write failures are non-fatal where possible (step logging) but session creation failures fail the request.
- Journal failures inside document services: document kept + `journal_warning` returned (transparency over silent loss) — paired with the atomicity gap above.
- Frontend: network errors surfaced with actionable text ("The AI service is offline. Start the backend server (port 8000)…").

## 11. REPORTING / EXPORT ARCHITECTURE

**[PARTIAL]**

- Read path (IMPLEMENTED): 14 SQL views → report_repository / reporting tools → AI answers + Reports UI pages (aging, balance-sheet, cash-flow, profit-loss, project-profitability) reading the same views directly via Supabase RLS.
- Report request pipeline (PARTIAL): `report_requests`/`generated_reports` tables + `generate_report` tool exist; the asynchronous PENDING→RUNNING→COMPLETED worker, PDF/XLSX/CSV rendering, and Storage `storage_path` delivery are **[MISSING]**.

## 12. UI / UX PRINCIPLES AND MODULE STRUCTURE

**[IMPLEMENTED unless noted]**

- Design language: teal/indigo "Ai Accountant" brand; Dashboard greets the org by name; KPI cards (Revenue, Expenses, Net Profit, Receivables, Payables, Cash & Bank); quick actions (New Invoice, New Quotation, Add Customer, Record Purchase, Trial Balance); Recent Transactions + Outstanding panels (fed by v_recent_transactions / agings).
- **AI-first interaction:** `AICommandBox` on the Dashboard is the primary entry ("Tell me what happened…"); renders AIProgress (phase feedback), AIClarification (question + answer), AIConfirmation (summary, risk level, accounting impact, approve/reject), AIActionCard (structured result).
- Sidebar modules: Dashboard, Sales (Invoices, Quotations, Credit Notes), Purchases (Bills, Returns), Customers, Suppliers, Projects, Expenses, Payments, Receipts, Banking, Accounting (Chart of Accounts, General Ledger, Journal, Trial Balance), Reports (P&L, Balance Sheet, Cash Flow, Aging, Project Profitability), AI Activity, Settings.
- Placeholder pages (render `ComingSoon`): AI Activity, Expenses, Purchases→Returns, Sales→Credit Notes, Projects (9-line pages) **[MISSING — intended]**. Full pages exist for: Dashboard (264), Invoices (349) + invoice [id] (0 lines — empty stub **[BROKEN stub]**), Quotations (392), Bills (358), Customers/Suppliers (195 each), Payments (340), Receipts (335), Banking (398), COA (262), General Ledger (157), Journal (427), Trial Balance (118), Reports pages, Settings (629), Onboarding (477), Welcome (428).
- Auth flow pages: login (99), signup (142), verify-email (28); `middleware.ts` guards routes; `(auth)` and `(dashboard)` route groups; onboarding + welcome flows create the organization (via `create_organization` RPC) with logo upload (033).
- Shared components: Modal, PageHeader, StatusBadge, States (empty/error), ComingSoon; invoice print templates (Minimal/Modern/Professional); `lib/types` mirror DB entities/enums/api contracts (434 + 113 + 146 lines).
- Org context: `useOrg()` resolves ACTIVE membership + role; TopBar shows org name + Administrator role; Settings page (629 lines) manages org profile/logo etc.

## 13. CURRENT DEPENDENCIES AND INTEGRATIONS

- **Backend (requirements.txt):** fastapi, uvicorn[standard], python-multipart, supabase, google-genai, pydantic(+settings), python-jose, passlib, PyJWT (ES256/JWKS + HS256), httpx, tenacity, structlog, pytest(+asyncio, cov). Python ≥3.11; venv at `ERP/venv`.
- **Frontend (package.json):** next 15, react 19, @supabase/supabase-js + @supabase/ssr, lucide-react, @phosphor-icons/react, clsx, tailwind-merge, tailwindcss 4, eslint, typescript 5.
- **External:** Supabase (Postgres, Auth incl. JWKS, Vault, Storage bucket for org logos/reports), Google Gemini (2.5-flash).
- **Integrations NOT present:** no Edge Functions, no webhooks, no email/SMS sending (verification is via Supabase Auth default), no bank feeds, no FBR tax filing.

## 14. IMPLEMENTATION STATUS MASTER TABLE

### Audit remediation ledger (C1–C6 from CODEBASE_INTEGRATION_AUDIT.md v1.0 → current state)

| Finding (original) | Current status |
|---|---|
| C1 Control-plane writes used non-existent columns | **FIXED** — database.py writers match live schema (proven by smoke_test.py DB assertions) |
| C2 13-phase values written to 7-value session_status_code | **FIXED** — `_PHASE_STATUS_MAP` splits current_phase vs status |
| C3 Confirmation AFTER tool execution; approval re-ran everything | **FIXED** — two-call Gemini design; confirmation gate before the executor call |
| C4 Engine builders never called; documents posted without journals | **FIXED** (core docs) — auto_journal dispatcher wired into invoice/purchase_bill/expense tools; receipt/payment/transfer use engine directly. **Residual:** quotation/credit note/purchase return journals still missing |
| C5 Tool definitions exposed only organization_id; tool_parameters unread | **FIXED** — get_gemini_tool_definitions() builds typed contracts from ai.tool_parameters |
| C6 No transaction atomicity | **NOT FIXED** — top integrity debt (single-transaction RPC is the intended remedy) |
| Header org spoofing (X-Organization-Id trusted) | **FIXED** — org always resolved from membership; residual: header fallback lacks is_production gate |

### Working end-to-end today [IMPLEMENTED]

- Auth (frontend ↔ Supabase ↔ backend JWT), org resolution, role resolution.
- Full agent chain: execute → clarify (multi-round with retention) → confirm → Gemini tool loop → permission check → validation → tool → service → engine → verify → result, with complete Control-Plane traceability (proven by `scripts/smoke_test.py` for the clarification path).
- 36 tools registered in DB + code; typed Gemini tool contracts from ai.tool_parameters; confirmation-before-mutation; journal auto-posting for invoices, purchase bills, expenses, receipts, supplier payments, bank transfers, bank account creation; reversal.
- All reports via views (AI + UI); trial balance, P&L, balance sheet, cash flow, ledgers, agings, project profitability.
- Onboarding: signup → org creation RPC (org + membership + FY + 12 periods + COA) → dashboard.
- Offline test suite 39/39; control-plane writes verified against live DB.

### Partially implemented [PARTIAL]

- Atomicity: no single-transaction document+items+journal RPC (Constitution §10 target).
- Tax computation not wired into auto_journal (tax tables/views exist).
- Quotation→invoice conversion; credit note / purchase return / quotation journals; fixed-asset depreciation posting; bank charges.
- ai.context_rules covers 8 of ~26 intents (code fallback map covers the rest).
- Validator rule-slug mismatches possible (record_customer_payment vs record_customer_receipt; record_expense vs create_expense); BALANCED/PERIOD_OPEN for post_journal read args not DB.
- record_expense_payment bill-settlement completeness; permissions cache TTL; get_journal_lines org filter; `instruction_versions.content_hash` NULL; conversation threading beyond clarifications; header-auth fallback lacks is_production gate.

### Missing [MISSING] (schema ready where noted)

- Attachments/receipt processing (Gemini vision + Storage) — UI upload exists, backend does not.
- Bank statement import + reconciliation flows; fixed assets UI/tooling; expenses/credit-notes/returns/projects/AI-activity pages (ComingSoon placeholders); report export PDF/XLSX/CSV pipeline; multi-currency (exchange_rates); business account recommendations; rate limiting; production logging config; PDF invoice sending; quotation PDF email.

### Broken [BROKEN]

- `frontend/src/app/(dashboard)/sales/invoices/[id]/page.tsx` is a 0-line empty stub (route exists, renders nothing).
- Migration drift: live DB has 40 migrations; local `database/migrations/` has 34 files with different numbering for the control-plane batch (026–034 locally vs 026–040 live, incl. split 028 batches). Mirror before the next DB change.

### Known bugs / technical debt (from the audit, post-fix residuals)

1. Atomicity gap (above) — highest priority debt.
2. Constitution sent in full to Gemini each call (token pressure).
3. Planner legacy fallbacks (record_purchase/record_sale generic intents) still present alongside explicit clarify-first mapping.
4. `documents`/`document_links` and Python-side `audit_events` writing under-used.
5. Frontend dashboard shows zeros gracefully but no "demo data" labels; invoice [id] stub; no pagination on some list pages.
6. `generate_text` and other dead code flagged for removal after planner consolidation.

### Intended / future [INTENDED — owner roadmap; do not start without instruction]

- `public.execute_accounting_transaction(jsonb)` atomic RPC; attachment intelligence (OCR/receipt extraction); bank feeds; full reconciliation; FBR/GST reporting; team invitations UI; AI Activity feed page; recurring invoices; multi-org switching UI (schema supports multi-membership).

## 15. VERIFICATION OF THIS DOCUMENT vs CODEBASE & LIVE SCHEMA (audit findings)

Verified directly during this audit (evidence-based):

- ✅ All 13 Python core modules, tools registry (36 slugs), services and repositories exist and match the descriptions above; control-plane writers use live column names (cross-checked against `information_schema` and `scripts/smoke_test.py` assertions).
- ✅ Live DB: 76 public tables + 20 ai tables, all RLS-enabled; 14 views; 21 public functions incl. SECURITY DEFINER `create_organization` (2 overloads), `get_gemini_api_key`, `is_org_member`, `has_org_role`, `next_document_number`, journal RPCs, period RPCs; triggers as listed.
- ✅ Control Plane seeds: 36 tools IMPLEMENTED, 98 tool_parameters, 7 permissions capabilities, 8 context_rules, 10 validation_rules, 13 workflows, 92 workflow_steps, Constitution v1.2.0 ACTIVE.
- ✅ Seeded data: 2 orgs, 44 accounts, 148 template items, 6 tax rates, 11 currencies, 5 roles.
- ⚠️ Discrepancy 1 — migration drift (34 local files vs 40 applied; numbering differs in the 026–034 range). Mirror before next DDL.
- ⚠️ Discrepancy 2 — `accounts` has TWO 4010-named rows per org pair with differing names (Software Development vs Services Revenue) — template variants per org, NOT a bug; do not "fix" by merging.
- ⚠️ Discrepancy 3 — `IMPLEMENTATION_CHECKLIST.md` claims all remaining work items "NEXT" but the audit remediation phases 4–10 are only partially done (see §14 partials). The checklist predates the auto_journal wiring.
- ⚠️ Discrepancy 4 — empty stub `sales/invoices/[id]/page.tsx` (0 bytes of code) despite sidebar linking to invoice detail.
- ⚠️ Discrepancy 5 — `ai.instruction_versions.content_hash` is NULL for all versions though the Constitution says SHA-256 hashes are stored.

## 16. CANONICAL WORKFLOW TRACES (real examples from this ERP)

Each trace uses the fixed pipeline of §3.2; only the domain specifics differ.

**A. One-off CASH purchase (no supplier exists or needed)**
USER: "I bought a Dell laptop for Rs.150,000 cash today."
→ INTERPRETATION: intent `record_cash_purchase` (bought+cash); entities: amount 150000, item "Dell laptop", date today; method CASH.
→ NO-ASSUMPTION CHECK: cash stated → no supplier required (Dell is a product noun — NEVER create supplier "Dell").
→ CONTEXT: chart_of_accounts + accounting_periods (per context rules).
→ PLAN → CONFIRM (purchase mutations require confirmation per ai.tools).
→ TOOL: `create_expense`/`record_cash_purchase` path → expense/document row (category Hardware Purchases 6150 or Computer Equipment 1500 if asset — ask if ambiguous).
→ ACCOUNTING ENGINE: `record_cash_purchase` → Dr 6150 Hardware Purchases (or 1500), Cr 1020 Cash — balanced by construction.
→ VERIFY → result summarising Dr/Cr.

**B. CREDIT purchase with supplier creation**
USER: "I bought a laptop from ABC Computers for Rs.150,000 on credit." (amount-less variant = smoke test)
→ amount missing → AWAITING_CLARIFICATION "What was the amount?" → answer merged → proceed.
→ supplier "ABC Computers" not found → clarify/confirm creation → `create_supplier` (party code auto-trigger).
→ `create_purchase_bill` + `auto_journal(purchase_bill)` → Dr Expense/Asset, Cr 2010 Accounts Payable (supplier-dimensioned) → bill OPEN.
→ Later "pay ABC Computers 150,000 from Meezan" → `record_supplier_payment`: payment row + Dr 2010 / Cr Bank GL + allocation → bill PAID.

**C. CASH sale**
USER: "Sold a website maintenance package for Rs.80,000 cash."
→ `record_cash_sale` → Dr 1020 Cash, Cr 4030 Maintenance Revenue. No customer row required unless stated.

**D. CREDIT sale to existing customer + receipt later**
USER: "Invoice ABC Traders Rs.500,000 for software development, due in 30 days."
→ `create_invoice` (+items) → Dr 1100 Receivable / Cr 4010 Revenue → ISSUED.
→ "ABC Traders paid 200,000 into Meezan" → `record_customer_receipt` + allocation → invoice PARTIALLY_PAID; aging reflects balance.

**E. Multiple bank accounts**
USER: "Transfer 100,000 from Meezan to JazzCash."
→ if account names ambiguous among bank_accounts → clarify which; else `record_bank_transfer` → Dr JazzCash GL / Cr Meezan GL. Single-default trigger keeps one is_default account.

**F. Expense with payment**
USER: "Record Rs.25,000 office rent paid by bank transfer."
→ `create_expense` → Dr 6130 Office Expenses / Cr Bank GL (+ supplier optional).

**G. Reporting (read-only, no confirmation)**
USER: "Show me this month's profit…"
→ intent `generate_profit_loss` → context income_statement → tool `get_profit_loss` → view `v_income_statement` → natural-language answer; NO journal, NO confirmation.

**H. High-impact manual journal**
USER: "Post a journal: Dr Owner Capital 100,000, Cr Cash 100,000."
→ tools `prepare_journal` → `validate_journal` → `post_journal` (HIGH risk → AWAITING_CONFIRMATION before posting; DB BALANCED + PERIOD_OPEN enforced again at trigger level).

## 17. WHAT MUST NOT BE CHANGED WITHOUT EXPLICIT JUSTIFICATION

1. **The four-layer separation:** Constitution (git) / Control Plane (ai.*) / Runtime (Python) / Financial Truth (public.*). Never move governance into code or truth into the Control Plane.
2. **Gemini never computes debit/credit** — all journal construction stays in `accounting_engine.py`.
3. **Confirmation BEFORE execution** for `requires_confirmation` tools (do not revert to post-execution approval).
4. **Clarification merge semantics:** answered questions never re-asked; one question per turn; 3-round ceiling.
5. **Org-scoping everywhere:** org always derived from membership; every repository query filtered by organization_id; RLS on all tables; `document_sequences` service-role only.
6. **Planner is deterministic regex** — do not replace with LLM calls without recording a Constitution amendment.
7. **Document numbering via `next_document_number` + triggers** (concurrent-safe); no client-side numbering.
8. **Journal lifecycle DRAFT→VALIDATED→POSTED→REVERSED** with DB triggers; never write POSTED directly.
9. **The 13-phase / 7-status state machine** and `_PHASE_STATUS_MAP`.
10. **Tool registry ↔ ai.tools 1:1 slug mapping**; new tools must be seeded in ai.tools + ai.tool_parameters + ai.permissions FIRST, then registered in code.
11. **Two-org seed data and party-code triggers**; COA code ranges (1xxx assets, 2xxx liabilities, 3xxx equity, 4xxx revenue, 6xxx expenses).
12. **Vault-stored Gemini key** — never move to .env.

## 18. ENVIRONMENT & RUN REFERENCE

- `.env` (backend): SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, JWT_SECRET (legacy HS256), GEMINI_MODEL etc. (key itself in Vault). `.env.local` (frontend): NEXT_PUBLIC_SUPABASE_URL/ANON_KEY, NEXT_PUBLIC_API_URL.
- Run: `Runapp.bat` (or manually: uvicorn `app.main:app --port 8000 --reload` from `ERP/`; `npm run dev/build/start` in `ERP/frontend/`).
- Tests: `pytest app/tests/ -v` (offline, mocked Supabase). Live smoke: `python scripts/smoke_test.py` (in-process ASGI, uses seeded test org and JWT_SECRET HS256 token; asserts AWAITING_CLARIFICATION + control-plane rows).
- API docs: `http://localhost:8000/docs`.
- Seeded test identities: user `00000000-0000-4000-8000-000000000001` (OWNER), org `00000000-0000-4000-8000-000000000010` (Test Traders (Pvt) Ltd).

---

## APPENDIX A — SOURCE-OF-TRUTH DOCUMENT MAP

| Document | Role |
|---|---|
| `ERP_AGENT_CONSTITUTION.md` v1.2.0 | Immutable governance (reasoning protocol, tool contracts, confirmation lifecycle, atomicity mandate, state machine) — loaded as Gemini system prompt |
| `CODEBASE_INTEGRATION_AUDIT.md` v1.0 | Historical deep audit: 6 critical findings (C1–C6) + 10-phase remediation plan — phases 1–3 & most of 5 applied; track remaining via §14 here |
| `IMPLEMENTATION_CHECKLIST.md` | Session-2 log: JWT auth, permissions, 4 tools, multi-line invoices, legacy ai_* table cleanup, test infra |
| `FRONTEND_MASTER_BUILD_PROMPT.md` | Frontend design system + module specs used to build the Next.js UI |
| `ERP_SYSTEM_ARCHITECTURE_AND_REASONING.md` | THIS FILE — the continuity blueprint that supersedes scattered knowledge |

*End of blueprint. Generated by a read-only audit agent; no code or database objects were modified during its preparation.*














