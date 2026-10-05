# AI-Native ERP with AI Accountant Agent

An AI-native ERP built for small businesses: a complete double-entry accounting system — sales, purchases, expenses, banking, fixed assets, and financial reporting — driven by a natural-language AI agent that interprets business events, applies accounting logic, and verifies every change.

## Overview

Manage customers, suppliers, products and services, quotations and invoices, purchase bills and credit notes, receipts and payments, banking, fixed assets, and financial statements — all through natural language or the intuitive web interface. The AI Accountant agent handles everything from intent understanding to journal entry creation, asks clarifying questions when information is missing, and requires explicit confirmation before sensitive changes.

## Architecture

```
Next.js 15 frontend (port 3000)
        │  Bearer JWT (Supabase session)
        ▼
FastAPI backend (port 8000)
        │
        ├── AI agent pipeline — intent classification → economic-event analysis →
        │     dependency resolution → clarification → confirmation → trusted tools
        │     → double-entry journal construction → database verification
        ├── Model orchestration — configurable AI providers with automatic fallback
        ├── Tool router — permission-checked, registered ERP operations only
        │     (the agent cannot run arbitrary SQL or code)
        └── Supabase PostgreSQL (Row Level Security enabled)
```

## Features

- **Party ledger management** — customers and suppliers with dedicated receivable/payable
  sub-ledgers segregated from control accounts
- **Sales cycle** — quotations that convert to invoices, sales invoices, and credit notes
  (branded, source-linked reversal entries)
- **Purchases & expenses** — purchase bills, debit notes / purchase returns, and expense tracking
- **Payments** — receipts and payments with full or partial allocation and settlement
- **Banking** — bank accounts, transfers, and transaction management
- **Fixed assets** — asset registration, depreciation schedules, and disposal
- **Reports** — trial balance, general ledger, profit & loss, balance sheet, cash flow,
  accounts receivable/payable aging, and project profitability
- **Product & service catalogue** — live search, filters, and inline create/edit/deactivate
- **AI Accountant agent** — natural-language transaction entry, document/vision extraction,
  and clarification and confirmation workflows

## Stack

- **Backend:** Python 3.12, FastAPI, pydantic-settings, supabase-py, structlog
- **Frontend:** Next.js 15 (App Router), TypeScript, Tailwind CSS 4, Supabase SSR
- **Database:** Supabase-hosted PostgreSQL (Row Level Security on all tables)
- **AI:** Configurable provider gateway with primary/secondary/fallback routing

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment (see .env.example)
cp .env.example .env

# Start the application
./Runapp.bat
```

- Frontend: http://localhost:3000
- API: http://localhost:8000 (docs at `/docs`, health at `/api/health`)

```bash
curl http://localhost:8000/api/health
```

## Environment variables

See `.env.example` for the full annotated list. Key variables:

| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | Database access (the service-role key is backend-only) |
| AI provider keys (`TH_API_KEY`, `QWEN_API_KEY`, `GEMINI_MODEL`) | Primary and secondary AI provider configuration |
| `AI_PRIMARY_PROVIDER`, `AI_FALLBACK_PROVIDER` | Model provider routing |
| `APP_HOST`, `APP_PORT`, `APP_ENV`, `CORS_ORIGINS` | Server configuration |

Frontend (`.env.local`): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
`NEXT_PUBLIC_API_URL` — browser-safe values only.

## Deployment

The repository ships a `vercel.json` that deploys both the Next.js app (`frontend/`) and the
FastAPI backend (`app.main:app`) as one project. Pushing to `main` deploys production; every
other branch creates a preview deployment.

| Check | Details |
|---|---|
| Production URL | https://ai-accountant-erp.vercel.app |
| Backend health | `GET /api/health` → `{"status":"ok",...}` |
| API docs | `/docs` (OpenAPI) |

Configure the environment variables from `.env.example` in the Vercel project before the
first deploy; keep provider keys and the service-role key as project secrets.

## Project structure

```
app/                 FastAPI application
  main.py            HTTP surface (auth, catalogue, AI, reports, …)
  agent.py           agent pipeline entry point
  accounting_reasoning.py, semantic_layer.py, planner.py
  tool_router.py, tools/      registered, permission-checked ERP tools
  accounting_engine.py        deterministic double-entry journal construction
  services/, repositories/    business logic and data access
  prompts.py, config.py       model instructions and settings
database/migrations/         SQL schema, applied in filename order
frontend/            Next.js 15 App Router UI
docs/                design references and governance
scripts/             background worker and operator utilities
```

## Security

- All secrets come from environment variables or managed vaults; nothing is hardcoded.
- `.gitignore` protects local secrets, logs, caches, and build output.
- Row Level Security is enforced on every table; client applications use the read-only anon key.
- The agent can only call registered, permission-checked ERP tools — no arbitrary SQL or code.
- Every financial change is validated through the accounting engine and independently verified
  against the database before it is reported as complete.
- Record resolution is read-only and scoped per tenant; identifiers are matched from existing
  data rather than invented.

## License

Proprietary — all rights reserved.