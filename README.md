# AI-Native ERP with AI Accountant Agent

An AI-native ERP for small businesses: a full double-entry accounting core
(sales, purchases, expenses, banking, fixed assets, financial statements)
driven by a natural-language AI agent that reasons about business events,
resolves dependencies, asks consolidated clarifying questions, requires
explicit confirmation for sensitive mutations, and independently verifies
every execution against the database.

## Architecture

```
Next.js 15 frontend (port 3000)
        │  Bearer JWT (Supabase session)
        ▼
FastAPI backend (port 8000)  —  app/main.py
        │
        ├── Agent pipeline (app/agent.py, planner.py, reasoning.py)
        │     intent → economic-event classification → 360° impact analysis
        │     → targeted context → dependency resolution → consolidated
        │     clarification → confirmation gate → trusted tools → validation
        │     → accounting engine → independent verification
        │
        ├── AI Orchestrator (app/ai_orchestrator.py)
        │     Qwen (Alibaba Model Studio, primary, capability-aware chain)
        │     → Gemini (fallback, key from Supabase Vault)
        │     provider fallback ONLY for provider-level failures; never
        │     replays a request after any tool has executed
        │
        ├── Tool Router (app/tool_router.py) — registry, permissions,
        │     validation, duplicate protection; no arbitrary SQL from the LLM
        │
        └── Supabase PostgreSQL (service_role, RLS enforced for clients)
              public.* business schema + ai.* agent control plane
```

## Stack

- **Backend:** Python 3.12, FastAPI, pydantic-settings, supabase-py, structlog
- **Frontend:** Next.js 15 (App Router), TypeScript, Tailwind CSS 4, Supabase SSR
- **Database:** Supabase-hosted PostgreSQL (RLS on all tables)
- **AI:** Alibaba Cloud Model Studio / Qwen (primary), Google Gemini (fallback)

## Capabilities

- Customers, suppliers, products, services, projects
- Quotations (with conversion to invoices), sales invoices, credit notes
- Purchase bills, purchase returns, expenses
- Receipts and payments with full/partial allocation and settlement
- Banking: accounts, transfers, transactions
- Fixed assets: registration, depreciation schedules, disposal
- Double-entry journal engine with source-tied entries, reversals
- Trial balance, general ledger, profit & loss, balance sheet, cash flow,
  aging, project profitability reports
- AI agent: reasoning/planning, clarification and confirmation workflows,
  document/vision extraction feeding normal ERP reasoning
- Organization onboarding, roles/permissions, audit logging

## Getting started

### Prerequisites

- Python 3.12+
- Node.js 20+
- A Supabase project (database URL + keys)
- Alibaba Model Studio API key (Qwen) — optional for UI-only use; the app
  starts and serves the dashboard even without any AI provider configured
  (provider initialisation is lazy and never blocks startup)

### Setup

1. **Database:** apply the SQL migrations in `database/migrations/` in
   filename order (`001…043`) to a fresh Supabase project.
2. **Backend config:** copy `.env.example` to `.env` and fill in your values.
   Never commit `.env`. The Gemini key lives in Supabase Vault and is read
   via the `get_gemini_api_key()` RPC (service_role only).
3. **Python deps:**
   ```bat
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```
4. **Frontend deps:**
   ```bat
   cd frontend
   npm install
   ```

### Run

One click (starts backend + frontend, waits for health, opens the browser):

```bat
Runapp.bat
```

Or manually:

```bat
venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```

- App: http://localhost:3000
- API: http://localhost:8000 (docs at `/docs`, health at `/api/health`)

### Tests

```bat
venv\Scripts\python -m pytest app/tests -q
cd frontend && npx tsc --noEmit
```

The offline backend suite (300 tests) uses a mocked Supabase client and
requires no network or credentials.

## Environment variables

See `.env.example` for the full annotated list. Key variables:

| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | Database access (service role: backend only, never the browser) |
| `QWEN_API_KEY`, `QWEN_BASE_URL`, `QWEN_MODEL_CHAIN`, `QWEN_VISION_MODEL_CHAIN`, `QWEN_BANNED_MODELS` | Primary AI provider and capability-aware chains |
| `GEMINI_MODEL` | Fallback provider model (key stays in Supabase Vault) |
| `AI_PRIMARY_PROVIDER`, `AI_FALLBACK_PROVIDER` | Provider routing |
| `APP_HOST`, `APP_PORT`, `APP_ENV`, `CORS_ORIGINS` | Server configuration |

Frontend (`.env.local`): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
`NEXT_PUBLIC_API_URL` — browser-safe values only.

## Security notes

- All secrets are environment/Vault based; no credentials are hardcoded.
  `.gitignore` protects `.env`, `.env.*`, logs, caches and build output.
- RLS is enabled on every table; clients only ever use the anon key.
- The LLM can only invoke the registered, permission-checked ERP tools;
  it never executes arbitrary SQL or code.
- Financial mutations pass a validator + accounting engine and an
  independent database verification step before success is reported.

## Known limitations

The following are not implemented and are refused cleanly rather than
simulated: multi-warehouse stock ledger / inventory movements, payroll and
employee management, cost centers / departments / locations, and complete
tax-to-GL mapping for all jurisdictions.

## License / status

Project built for the national AI hackathon demo. Not production-hardened
for multi-tenant public deployment.
