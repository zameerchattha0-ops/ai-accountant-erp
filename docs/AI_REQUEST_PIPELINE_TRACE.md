# AI REQUEST PIPELINE — EXACT EXECUTION TRACE & REASONING AUDIT

**Audit mode:** read-only inspection of CURRENT code (`Ai Accountant/ERP/`) + live Supabase `gghkbpdaqogncbrwzmpp` (14 real execution sessions examined). No code or DB modified.
**Companion doc:** `ERP_SYSTEM_ARCHITECTURE_AND_REASONING.md` (system-level blueprint). This file is the *request-level* execution trace.

---

## PART 1 — STAGE-BY-STAGE PIPELINE (WHAT ACTUALLY HAPPENS)

### STAGE 0 — User Message → Frontend
- **File:** `frontend/src/components/ai/AICommandBox.tsx` (`handleSend`, line 41)
- **What happens:** message + optional attachments collected; calls `aiExecute({message, attachments?})`.
- **File:** `frontend/src/lib/api/client.ts` (`fetchApi`, line 11; `aiExecute`, line 42)
- **Data passed:** `POST {NEXT_PUBLIC_API_URL|http://localhost:8000}/api/ai/execute`, body `{"message": "..."}`, header `Authorization: Bearer <supabase-jwt>` (JWT from `supabase.auth.getSession()`).

### STAGE 1 — Backend auth
- **File:** `app/main.py` (`ai_execute` route → `get_current_user` → `authenticate_header`)
- **File:** `app/auth.py` (`authenticate_header`, line 257; `authenticate`, ~line 208; `_decode_jwt`, line 83)
- **Mechanics:** Bearer JWT → inspect `alg` header → ES256/RS256 verified against Supabase JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, cached 300 s) OR HS256 legacy secret (`config.jwt_secret`). Extract `sub` → `user_id` → `_resolve_membership(user_id)` queries `organization_members` (status ACTIVE) → `organization_id` + `role_id` → `organization_roles` row → `role_code` + `permissions` (JSON array).
- **Data passed onward:** `AuthContext(user_id, organization_id, role_code, role_permissions)`.

### STAGE 2 — Session creation (Control Plane write #1)
- **File:** `app/agent.py` `execute()` (line 82) → `app/database.py` `create_execution_session()` / `_get_control_plane_ids()` (line 197)
- **Tables:** reads `ai.agents` (status ACTIVE), `ai.instruction_versions` (version = agent.current_instruction_version = "1.2.0"); **INSERT** `ai.execution_sessions` `{user_request, agent_id, instruction_version_id, model_configuration_id, conversation_id?, status: PENDING, current_phase: RECEIVED}`.
- **Step log:** `create_execution_step(step_type="REASON", input_summary={"message": …})` → `ai.execution_steps`. *(Verified live: every session's step 1 = REASON/"RECEIVED".)*
- `_CONTROL_PLANE_IDS` cached per process.

### STAGE 3 — Planner (deterministic, no LLM)
- **File:** `app/planner.py` `plan(user_message, clarification_history)` (line 189)
- **Exact sequence:**
  1. `_identify_intent(msg_lower)` — ordered regex `_INTENT_PATTERNS` (line 42; reports first, then documents, then mutations).
  2. `_extract_payment_method` (line 176): CREDIT (`on credit|khata|udhaar`), CASH, BANK_TRANSFER, CHEQUE, CARD → `_refine_intent()` upgrades generic `record_purchase`→`record_credit_purchase`/`record_cash_purchase` (same for sales). No keyword → stays generic `record_purchase`/`record_sale`.
  3. `_extract_entities` (supplier via `from <name>`, customer via `to <name>`), `_extract_amount` (`Rs. 20,000` / `20000 rs` / `for 20,000`), `_extract_date` ("today"/"yesterday"/ISO/month names), `_extract_item` (`_ITEM_PATTERNS`, line 156 → e.g. "hp laptop").
  4. **Clarification-history merge** (line 222): `_merge_clarification_answers(entities, history)` — every prior Q&A answer parsed and folded into entities ("20,000" → 20000.0). *(Proven live: session `974b475f…` step 2 shows `{"supplier_name": "abc comupters", "amount": 20000.0}` merged.)*
  5. Requirements flags (line 226): `requires_validation` (false for report intents), `requires_accounting = intent in _TRANSACTION_INTENTS`, `requires_confirmation` (line 234: credit purchase/sale, create_invoice, record_receipt, record_payment, credit note, purchase return, expense payment, bank transfer, bank account — **generic `record_purchase`/`record_sale` are NOT in this set**).
  6. `_required_fields(intent)` (`_TRANSACTION_INTENTS` map, ~line 330): `record_credit_purchase` → `[amount, supplier_name]`; `record_cash_purchase` → `[]` (**supplier NOT required — the one-off-cash rule**); `record_credit_sale` → `[amount, customer_name]`; `record_cash_sale` → `[amount]`.
  7. Missing-field check (dynamic): missing ⇒ at most ONE question from `_FIELD_QUESTION` (amount → "What is the transaction amount?"). After `MAX_CLARIFICATION_ROUNDS = 3` the plan is passed to Gemini with hints instead.
- **Data passed onward:** `ExecutionPlan{intent, extracted_entities, tools[], context_sources[], outcome, requires_*}`.
- **Step log:** step 2 = REASON/"PLANNING" with `{intent, extracted_entities}`. *(Verified live.)*

### STAGE 4 — Clarification gate (if triggered)
- **File:** `app/agent.py` (`execute()` after planning; `resume_with_clarification`, line 399)
- **Tables:** **INSERT** `ai.clarifications {execution_session_id, question, required_information[], options[], status: WAITING_FOR_USER}`; session → `current_phase: AWAITING_CLARIFICATION`, `status: WAITING_FOR_USER`.
- **Return:** `{status: "AWAITING_CLARIFICATION", execution_id, question}` → frontend `AIClarification.tsx` → user answers → `aiClarify({session_id, answer})` → `POST /api/ai/clarify` → `resume_with_clarification()`:
  - `resolve_clarification()` → row `status: COMPLETED, user_response, answered_at`.
  - `get_clarification_history(session_id)` reloads the COMPLETE Q&A list from `ai.clarifications`.
  - **Re-enters `execute(user_message=ORIGINAL request, clarification_history=history)`** — the answer is never treated as an isolated new request. *(Proven live: resumed sessions re-run from RECEIVED with the original message and merged entities.)*
  - `seed_clarification_history` copies prior Q&A into the new session row so history survives the session-per-round design.

### STAGE 5 — Context retrieval (database FIRST)
- **File:** `app/context_manager.py` `build_context(organization_id, user_id, intent, entity_hints, clarification_history)` (line 32)
- **Reads, in order:**
  1. `organizations` row (`organization_repository.get_organization`).
  2. `financial_years` (is_current=true) + `accounting_periods` (status OPEN) — `get_current_financial_year`, `get_open_accounting_period`.
  3. `ai.context_rules` → `get_context_sources_for_intent(intent)` → `required_sources[]`.
  4. Hint-gated fetches (only what the intent needs): customers (ilike search, limit 5), suppliers (limit 5), `accounts` (limit 50), `projects` (limit 5), `bank_accounts` (payment intents), open invoices (ISSUED/PARTIALLY_PAID) / open bills (OPEN/PARTIALLY_PAID) for allocation context, `v_trial_balance`/`v_cash_flow` for report intents.
- **⚠️ THIS STAGE IS WHERE THE LIVE PIPELINE CURRENTLY CRASHES — see PART 3.**
- **Data passed onward:** `AgentContext{organization, financial_year, accounting_period, relevant_customers/suppliers/accounts/projects/bank_accounts/documents/reports, extracted_entities, clarification_history}`.

### STAGE 6 — Reasoning (Gemini planning call)
- **File:** `app/agent.py` — planning call with `executor=None`; **File:** `app/gemini_client.py` `generate_with_tools(..., executor=None)` (line 74)
- Nothing executes here: tool calls Gemini proposes are returned unexecuted. The Agent inspects the proposal + plan.

### STAGE 7 — Confirmation gate
- **File:** `app/agent.py` (between planning and executor call) → `app/database.py` `create_confirmation()` (line 532)
- **Table:** **INSERT** `ai.confirmations {execution_session_id, action_type, description, risk_level, confirmation_required: true}`; session → AWAITING_CONFIRMATION / WAITING_FOR_USER. User decides via `POST /api/ai/confirm` → `resume_with_confirmation()` (line 399): `resolve_confirmation()` records `user_confirmed / confirmed_at / user_id`; reject → REJECTED terminal; approve → re-enter `execute()` which proceeds to the executor call. **No mutation happens before this gate for `requires_confirmation` tools.**

### STAGE 8 — Tool selection & execution (Gemini executor call)
- **File:** `app/gemini_client.py` `generate_with_tools(..., executor=…)`; manual loop (lines 129–209), `automatic_function_calling: maximum_iterations=0`, `MAX_TOOL_ITERATIONS = 10`. Each `function_call` → executor → `function_response` sent back (`chat.send_message`, line 203) until a text-only response or the cap.
- **File:** `app/tool_router.py` `route_tool_call()` (line 30): registry check (`app/tools/__init__.py`) → `permissions.authorize_tool()` (`ai.permissions` × role capabilities) → mutation? `validator.validate_operation()` → handler `(organization_id, **args)`.
- **Tables per call:** **INSERT** `ai.tool_calls {execution_session_id, tool_id (via `_resolve_tool_id` cache), input_payload, output_payload}`.
- *(Live status: `ai.tool_calls` = 0 rows — see PART 3 for why.)*

### STAGE 9 — Validator (pre-mutation)
- **File:** `app/validator.py` `validate_operation()` (line 31)
- Checks: positive amounts; ISO dates; ACTIVE `ai.validation_rules` by `applies_to` (ENTITY_EXISTS / AMOUNT_POSITIVE / BALANCED / PERIOD_OPEN); direct customer/supplier/account existence; `get_period_for_date(p_org, p_date)` RPC → period must be OPEN.

### STAGE 10 — Accounting Engine + Supabase mutation
- **Files:** `app/accounting_engine.py` (builders + `auto_journal` dispatcher, ~line 430), `app/services/accounting_service.py` (`prepare_journal`, line 24), `app/repositories/journal_repository.py`.
- **Example — credit purchase of HP laptop, 20,000:**
  1. `create_supplier` if needed (`supplier_service.create` — duplicate-safe, name-only minimum) → `public.suppliers` (party code via `trg_party_code_assign`).
  2. `create_purchase_bill` → `public.purchase_bills` (+ `purchase_bill_items`), doc number via `next_document_number` trigger (`document_sequences`).
  3. `auto_journal("purchase_bill", doc)` → `_resolve_default_account` → `record_credit_purchase(supplier_id, asset_account_id=6150-class, payable_account_id=2010, amount=20000, …)`.
  4. `prepare_journal` validates (≥2 lines, |Dr−Cr| ≤ 0.01, > 0) → **INSERT** `journal_entries` (DRAFT, source_type='purchase_bill', source_id) + **INSERT** `journal_lines` (Dr Expense 20,000 supplier-dimensioned; Cr 2010 Accounts Payable 20,000 supplier-dimensioned).
  5. Receipt/payment services additionally `validate_journal` → `post_journal` (DRAFT→VALIDATED→POSTED via RPC + `trg_journal_entries_status`).
- **Pre-existing records required (verified live):** org → `financial_years` (is_current) → 12 `accounting_periods` (OPEN) → per-org `accounts` COA (22 accounts seeded by the `create_organization` SECURITY DEFINER RPC — 44 rows live across 2 orgs). A freshly onboarded org is never empty.

### STAGE 11 — Verification
- **File:** `app/accounting_engine.py` `verify_journal(entry_id)` — re-reads `journal_lines` from DB, asserts balanced. **INSERT** `ai.execution_results {execution_session_id, status, summary, action_type, affected_entities[], result_payload, verification_status, completed_at}`; session → VERIFYING → COMPLETED; `ai.audit_events` for governance events.

### STAGE 12 — Final AI response
- **File:** `app/agent.py` (PHASE 6) → `AgentResponse{status, summary, execution_id, question?, risk_level?, accounting_impact?, data}` (`app/models/schemas.py`) → `AIActionCard.tsx`. The DB — not Gemini's claim — is what was verified and reported.

---

## PART 2 — EXACTLY WHAT GEMINI RECEIVES (EVERY CALL)

### 2.1 Generation config (both planning and executor calls)
- **File:** `app/gemini_client.py` lines 100–118
- `model = settings.gemini_model` (default **gemini-2.5-flash**; also stored in `ai.model_configurations`), `temperature=0.1`, `max_output_tokens=8192`, `top_p=0.95`, `top_k=40`, `tools=<function declarations>`, `automatic_function_calling={maximum_iterations: 0}` (loop is managed by our code), `system_instruction=<see 2.2>`.

### 2.2 System instructions (`_build_system_instructions`, lines 253–289) — IDENTICAL on every call
1. Hard-coded identity + CORE RULES (verbatim in code):
   - "You are an AI accounting assistant for a small-business ERP system…"
   - Rule 1: NEVER compute debit/credit arithmetic — the accounting engine handles that.
   - Rule 2: NEVER invent financial figures — always use data from tools.
   - Rule 3: NEVER make assumptions about uncertain information — ask the user.
   - **Rule 4: Do NOT automatically create suppliers or customers just because a name appears.**
   - Rule 5: Search before creating persistent entities.
   - Rule 6: Ask only when material information is missing; do not ask unnecessary questions.
   - Rule 7: Explain what you did in concise, factual terms.
2. INFORMATION REUSE RULES (STRICT) 8–12: EXTRACTED ENTITIES are authoritative ground truth (never re-ask them); CLARIFICATION HISTORY answers are final (never re-ask); analyse the COMPLETE request TOGETHER before deciding anything is missing; ask at most ONE question and only when material info is absent from ALL sources; when sufficient information exists, proceed directly with tool calls.
3. **GOVERNANCE DOCUMENT (ERP_AGENT_CONSTITUTION): `self._constitution[:8000]`** — the first 8,000 characters of `ERP_AGENT_CONSTITUTION.md` loaded from disk (`config.CONSTITUTION_PATH`), truncated for token budget. The remainder of the 833-line document is NOT sent.

### 2.3 User content (`_build_user_content`, lines 291–336) — rebuilt per request
```
Organisation: <name> (currency: PKR)
Current period: <period name> (<start> to <end>)
Relevant customers: <up to 5 names>
Relevant suppliers: <up to 5 names>
Relevant accounts: <up to 10 "code name">
[if extracted_entities] EXTRACTED ENTITIES (authoritative — use directly, never re-ask):
  - amount: 20000.0
  - supplier_name: abc computers
  - item_description: hp laptop
  - payment_method: …
[if history] CLARIFICATION HISTORY (already answered — never re-ask):
  - Q: What is the transaction amount? -> A: 20,000
User request: <original message>
```
- Note: the user content carries the ORIGINAL user request (not the answer) + merged entities + history — this is how "20,000" is re-attached to the full transaction.

### 2.4 Tool definitions (both calls)
- **File:** `app/tool_router.py` `get_gemini_tool_definitions()` (line 119)
- All 36 IMPLEMENTED tools as Gemini `FunctionDeclaration`s with typed JSON-Schema parameters (string/integer/number/boolean/array/object) sourced from `ai.tool_parameters` (98 rows, sorted by position, `required` flags honoured). `organization_id` is stripped — injected server-side. Descriptions come from the in-code registry.

### 2.5 Difference between the two Gemini calls
- **Planning call:** `executor=None` → any `function_call` Gemini emits is returned to `agent.py` and NOT executed. Gemini sees everything in 2.1–2.4 but cannot touch the DB.
- **Executor call (after confirmation):** `executor=<wrapper around route_tool_call>` → same prompt content, but tool calls run through Stage 8's security chain and results are fed back as `function_response {result: <ToolResult payload>}` parts.

## PART 3 — CRITICAL REASONING ISSUE: LIVE INVESTIGATION RESULT

Scenario tested against CURRENT code AND live data: *"I purchased the HP laptop from ABC Computers." → "What is the price?" → "20,000."*

### 3.1 What works (verified)

1. **Clarification triggers correctly.** "I Purchase a hp Laptop from abc computers" (no amount) → intent `record_purchase`, missing `amount` → question "What is the transaction amount?" written to `ai.clarifications`, session AWAITING_CLARIFICATION. *(Live sessions `73976a76…`, `4a1a6c05…`.)*
2. **The answer is re-attached to the COMPLETE transaction, not treated as a new request.** `resume_with_clarification` re-runs `execute()` with the ORIGINAL user request + full Q&A history; `_merge_clarification_answers` folds "20,000" → `amount: 20000.0` while preserving `supplier_name` and `item_description`. **Hard evidence from `ai.execution_steps`** (session `974b475f…`, step 2): `{"intent": "record_purchase", "extracted_entities": {"supplier_name": "abc comupters", "amount": 20000.0}}`.
3. **The planner reasons about the whole transaction** (answers to your questions 1–12 below map to real code, see §4).

### 3.2 The actual defect — every resumed session FAILS [BROKEN]

**Live evidence (14 sessions, all examined):** every round-1 session = AWAITING_CLARIFICATION (correct); **every resumed session = FAILED** (e.g. `974b475f…`, `ac7d141c…`, `2f1a0699…`, `c2201ff3…`). `ai.execution_results.summary` for every failure:

```
Error: {'message': '"failed to parse order (start_date.asc.asc)" (line 1, column 16)',
        'code': 'PGRST100', 'hint': None, …}
```

**Root cause — one bug in `app/database.py` `fetch_many()` (lines 114–115):**

```python
if order:
    q = q.order(order)          # ← BUG
```

Callers pass PostgREST-style strings like `order="start_date.asc"`, but supabase-py's `.order(column)` expects a bare COLUMN NAME and appends the direction itself. The passed `"start_date.asc"` becomes the query param `order=start_date.asc.asc` → PostgREST rejects it (PGRST100).

**Failure chain for your exact scenario:**
```
Round 2 execute() → clarification gate PASSES (amount merged)
→ PHASE CONTEXT_LOADING → context_manager.build_context()
→ organization_repository.get_open_accounting_period()
→ get_accounting_periods() → fetch_many("accounting_periods", order="start_date.asc")
→ PostgREST PGRST100 → exception → agent.execute() catch → session FAILED
```
Round 1 never reaches `build_context()` (clarification returns first), which is why round 1 works and round 2 always dies at the same place. `ai.tool_calls` = 0 rows because NO session has ever survived context loading to reach Gemini's executor.

**Other call sites with the same latent bug** (all currently unreachable or unexercised for the same reason): `organization_repository.get_financial_years("start_date.desc")`, `get_bank_accounts("bank_name.asc")`, `database.resolve_confirmation("created_at.asc")`, `database.create_execution_session`-adjacent ordered reads, `validator._load_rules("priority.desc")`, `payment_repository`/`journal_repository` ordered reads. Fix once in `fetch_many` and all are repaired.

**Exact fix (3 lines in `app/database.py`, `fetch_many`):**

```python
if order:
    col, _, direction = order.partition(".")
    q = q.order(col, desc=(direction == "desc"))
```

**This audit did NOT apply the fix** (documentation-only mandate). Until applied, no AI request that passes the clarification gate — or requires confirmation — can ever complete. This also explains the earlier dashboard experience where answering "20,000." produced a failure.

### 3.3 Secondary observations from live data

- Sessions `4c096ae2…`/`e8f967ea…` (message already contained "for 20000 rs") still asked for the amount — those runs (2026-08-30 06:28) predate the current amount-pattern handling; the current `_extract_amount` matches "20000 rs". No repro today.
- One round-1 clarification stored `required_information: ["What is the transaction amount?"]` (question text instead of "amount") in older rows — cosmetic legacy, current rows use `["amount"]`.
- `conversation_id` is NULL on all sessions: multi-round history works via `seed_clarification_history`, but conversation threading is not yet populated (known PARTIAL).

## PART 4 — THE 14 REASONING QUESTIONS vs ACTUAL IMPLEMENTATION

| # | Question | Where it is actually answered (file → mechanism) | Status |
|---|---|---|---|
| 1 | What exactly was purchased? | `planner._extract_item` (`_ITEM_PATTERNS`) → `item_description: "hp laptop"`; passed to Gemini as authoritative entity | ✅ |
| 2 | HP = brand, ABC Computers = supplier? | Planner extracts supplier only from `from <name>`; "hp laptop" captured as item. Gemini system Rule 4 forbids creating parties from product nouns | ✅ |
| 3 | Does ABC Computers exist? | Context Stage 5 pre-loads matching suppliers; Gemini must `search_supplier` (Rule 5 "search before create"); `supplier_service.create()` re-checks duplicates and returns the existing row if found | ✅ |
| 4 | Cash or credit? | `planner._extract_payment_method` + `_refine_intent`; absent keyword → generic intent; if material, Gemini may clarify (Rule 3). **Note:** generic `record_purchase` skips required-field enforcement for supplier — see caveat below | ⚠️ |
| 5 | Asset vs expense vs inventory account? | `accounting_engine.auto_journal` → `_resolve_default_account(EXPENSE)` default; Gemini may propose `account_id`/`account_code` which the engine resolves via `accounting_service.resolve_account`. No inventory valuation logic exists (products table not wired into journals) | ⚠️ (defaults; no capital-vs-expense clarification branch) |
| 6 | Which cash/bank account? | `payment_service._resolve_bank_gl_account` (bank_account_id → its GL link); cash fallback `cash_account_id`; multiple banks → context supplies them and Gemini/validator picks; not auto-guessed | ✅ |
| 7 | Transaction date? | `planner._extract_date` ("today" default) → `transaction_date` entity | ✅ |
| 8 | Financial period? | DB-first: `get_period_for_date(p_org, p_date)` RPC checked by `validator._check_period_open` AND enforced by DB trigger; context supplies current period to Gemini | ✅ |
| 9 | Which ledger/account must be used? | Engine resolves from seeded COA (1010 Bank, 1020 Cash, 1100 AR, 2010 AP, 4xxx revenue, 6xxx expense) — never Gemini arithmetic | ✅ |
| 10 | Flow into Chart of Accounts? | `journal_lines.account_id` FK → `accounts` hierarchy; balances aggregate into `v_account_summary`/`v_trial_balance` | ✅ |
| 11 | Required journal entry? | `record_credit_purchase`: Dr Expense/Asset 20,000 / Cr 2010 AP 20,000 — constructed ONLY by `accounting_engine`, balanced by construction | ✅ |
| 12 | Supplier ledger impact? | `journal_lines.supplier_id` dimension → `v_supplier_ledger` / `v_open_payables`; receipts/payments update party documents | ✅ (once pipeline unblocked) |
| 13 | Trial Balance / Statements impact? | Views `v_trial_balance`, `v_income_statement`, `v_balance_sheet`, `v_cash_flow` aggregate POSTED entries; `verify_journal` + auto-post keeps them current | ✅ |
| 14 | What must exist BEFORE posting? | DB-first inspection: org → FY → OPEN periods → COA (all seeded by `create_organization` RPC — verified live: 44 accounts, 24 periods); party existence via context + validator ENTITY_EXISTS; account existence via validator | ✅ |

**Caveats (⚠️ rows):**
- **Cash-or-credit ambiguity:** with no payment keyword the intent stays `record_purchase` whose `_required_fields` is `[]`, so the deterministic planner does not itself force the cash-vs-credit question — the decision is deferred to Gemini (system Rules 3/11 + Constitution). Works via the LLM in practice, but is not guaranteed at the planner layer. Hardening option (not applied): treat missing `payment_method` on purchase/sale intents as a material gap.
- **Asset-vs-expense:** `auto_journal` defaults to the EXPENSE default account; routing hardware to 1500 Computer Equipment depends on Gemini passing an account hint — there is no explicit clarification branch for capital-vs-expense.

## PART 5 — NEW SUPPLIER / CUSTOMER LOGIC vs THE REQUESTED RULES

| Requested rule | Actual implementation | Verdict |
|---|---|---|
| Don't fail when DB is empty | COA/FY/periods seeded at org creation; parties creatable at runtime (`create_supplier`/`create_customer` tools, master_data capability) | ✅ |
| Create MINIMUM record (name only), invent nothing | `supplier_service.create(name, …)` — all other fields optional; no address/phone/tax invented. Note: service defaults `payment_terms_days=30`, `currency_code=PKR` (silent defaults, not invented user data) | ✅ (with note) |
| Don't auto-create merely because a name appears | Gemini system Rule 4 + Rule 5; planner requires `supplier_name` ONLY for credit intents | ✅ |
| One-off cash purchase → no supplier tracking | `_required_fields("record_cash_purchase") = []`; engine `record_cash_purchase` takes no supplier | ✅ |
| Credit purchase → supplier required | `record_credit_purchase` requires `supplier_name`; validator ENTITY_EXISTS; engine dimensions payable lines with supplier_id | ✅ |
| Cash sale → no customer required | `record_cash_sale` → `[amount]` only | ✅ |
| Credit sale → customer required | `record_credit_sale` → `[amount, customer_name]` | ✅ |
| Enrichable later | All contact/tax fields nullable and editable | ✅ |
| Duplicate protection | `supplier_service.create` / `customer_service.create` search first, return existing row on exact name match | ✅ |

**Verdict:** the reasoning design already matches your rules — visible in system prompts, planner requirements, and engine builders. The system is prevented from demonstrating it end-to-end by the single `fetch_many` bug in PART 3.2.

## PART 6 — RECOMMENDED NEXT STEP (NOT applied — approval required)

1. Patch `app/database.py` `fetch_many` lines 114–115 (exact 3-line fix in PART 3.2).
2. Restart backend; send "I purchased the HP laptop from ABC Computers." → answer "20,000."
3. Expect: AWAITING_CLARIFICATION → merged plan → (confirmation if credit) → tool calls recorded in `ai.tool_calls` → supplier + bill + balanced journal in `public.*` → `verification_status=VERIFIED` → session COMPLETED.
4. Re-run `pytest app/tests/ -v` (must stay 39/39) and `python scripts/smoke_test.py`.

*End of trace. Generated from current code and live DB evidence; no modifications made.*





