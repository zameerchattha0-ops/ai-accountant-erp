# AI Accountant — Full-Product UX + Performance + Data-Fetching Audit

> Scope: entire application (Next.js 15 frontend, FastAPI backend, Supabase Postgres).
> Method: static repository audit with file:line evidence, before any code change.
> Priority: **P0** = correctness / massive data transfer / blocking · **P1** = major
> friction / slow pages / bad dropdowns / refetch problems · **P2** = visual and
> interaction polish · **P3** = decorative refinements.

## 0. Baselines (measured before any change)

| Suite | Result |
|---|---|
| Frontend `vitest run` | **103 tests pass** (4 files, 10.6 s) |
| Backend `pytest -q` | **857 tests pass** (13.1 s) |
| `tsc --noEmit` | clean (empty output) |
| Realtime subscriptions | **none exist** (`postgres_changes`/`channel` → 0 hits in `src`) |
| Request cancellation | **none exist** (`AbortController`/`abortSignal` → 0 hits in `src`) |

## A. UX problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| A1 | Native `<select>` pickers render the **entire** customer/supplier table as options — page-length dropdowns, no search | `sales/invoices/page.tsx:337-344`, `sales/quotations/page.tsx:345`, `receipts/page.tsx:273`, `payments/page.tsx:278`, `purchases/bills/page.tsx:318` | **P1** |
| A2 | TopBar **Search and Bell buttons do nothing** (no onClick); the Bell shows a red dot implying notifications that do not exist | `components/layout/TopBar.tsx:82-88` | **P1** |
| A3 | `Modal` has no Escape-to-close, no focus trap/restore, no `role="dialog"`/`aria-modal` — every modal inherits this | `components/shared/Modal.tsx` | **P1** |
| A4 | List search inputs rely on `placeholder` as the only accessible name | all list pages | **P2** |
| A5 | Most list search filters the fetched array — feels instant today, but must keep that feel (debounce + keep previous rows) when moved server-side | all list pages | P1 |
| A6 | Two competing `EmptyState` components with different APIs | `States.tsx:23` vs `EmptyState.tsx` | **P2** |
| A7 | Sidebar collapsed state / open groups not persisted across reloads | `Sidebar.tsx:100-102` | **P3** |
| A8 | Errors show raw database messages instead of "what happened / what to do" copy | every list `ErrorState message={error}` | **P2** |
| A9 | No global command interface (Ctrl/Cmd+K); navigation is mouse-first | repo-wide | **P2** |
| A10 | Cash Flow has no period control while P&L silently scopes to the reporting year — inconsistent report semantics | `reports/cash-flow/page.tsx` | **P2** |

## B. Performance problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| B1 | **Unbounded full-table fetches** (`select("*")`, no limit) on every core list — multi-MB payloads at 10k–100k rows, and past the PostgREST response cap rows silently vanish | customers:47, suppliers:47, employees:115, invoices:73, quotations:74, credit-notes:80, bills:75, returns:80, payments:64, receipts:64, chart-of-accounts:54, banking:53+69, aging:42 | **P0** |
| B2 | General Ledger loads **every** `v_general_ledger` row for the range then filters in JS — biggest table in the product (target 500k lines) | `general-ledger/page.tsx:35-47` | **P0** |
| B3 | Cash Flow takes `.limit(500)` then **computes category totals + net over those 500 rows** — silently wrong statement totals past 500 cash lines | `reports/cash-flow/page.tsx:33,41-49` | **P0** (correctness) |
| B4 | Dashboard sums ALL open receivables/payables rows client-side for two KPI numbers | `(dashboard)/page.tsx:130-131,146-156` | **P1** |
| B5 | Perpetual full-viewport `blur(84px)/blur(90px)` animated blobs + backdrop-blur chrome — continuous GPU cost while scrolling | `globals.css:470,646`, `TopBar.tsx:63` | **P2** |
| B6 | Payments/Receipts KPI tiles reduce **all** rows client-side — O(n) aggregation that forbids paginating the list without lying | `payments/page.tsx:99-104,209` | **P1** |
| B7 | `aiGetSessions` default `limit=1000` rows per feed load | `lib/api/client.ts:90-101` | **P2** |
| B8 | Catalogue polls on interval + window focus on top of search reloads — acceptable (server-backed, silent) but keep bounded | `catalogue/page.tsx:125-133` | P3 (OK) |


## C. Data-fetching problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| C1 | **Fetch-everything → filter-in-browser** is the dominant list pattern (~20 pages). Server-side search/pagination exists on only ONE list page (journal) plus REST-backed pages (projects, catalogue, ai-activity, fixed-assets) | journal:87-109 (good) vs all others | **P0** |
| C2 | Server-side debounced search exists only in journal/projects/ai-activity/catalogue; moved pages must preserve instant-feel: debounce ~250-300 ms + keep previous rows visible while refetching | journal:111-116 | P1 |
| C3 | No request cancellation anywhere → out-of-order responses can overwrite newer results; overlapping `load()` races possible on repeated `erp:data-changed` | 0 `AbortController` hits | **P1** |
| C4 | Document lists search party **name** client-side via embedded row; server-side replacement needs a two-step bounded party lookup (PostgREST `or` cannot span root + embedded columns) | invoices:131-140 | P1 (design constraint) |
| C5 | Form option lists fetched fully on every form mount: customers/suppliers unbounded (P1), bank accounts / supplier's open bills bounded (OK) | invoices:82-92, payments:73-97 | **P1** |
| C6 | Good patterns to preserve: `useOrg` session cache + in-flight dedupe (`useOrg.ts:29-71`), 401 refresh-retry (`client.ts:46-59`), catalogue silent background refresh, `erp:data-changed` targeted refresh (dashboard:176-180) | — | keep |

## D. Database / query problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| D1 | Org-scoped btree + trigram (`gin_trgm_ops`) indexes exist for customer/supplier/product/account **names** — good foundation for server search | `018:13-37` | pass |
| D2 | **No search indexes on document numbers** (`invoice_number`, `quotation_number`, `bill_number`, `payment_number`, `receipt_number`) — `ilike '%q%'` degrades to org-partition seq scans as documents grow (unique constraints only serve prefix lookups) | `018:50-101`, `009:74` | **P2** |
| D3 | `employees` table (migration 084) has no search indexes — 018 predates it | `084` | **P2** |
| D4 | No aggregate RPC for KPI sums (payments/receipts) or cash-flow totals — frontend currently cheats by loading rows | `017`, `034:42` | **P1** (migrations 089/090) |
| D5 | RLS org scoping (`.eq("organization_id", …)`) consistently applied — server-side pagination keeps this intact | all pages | pass |

## E. Real-time problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| E1 | **No Supabase realtime subscriptions exist** — no duplicates, no leaks, no event storms. Refresh model = remount-on-navigate + `erp:data-changed` custom event (dashboard, settings) + catalogue focus/interval refresh | 0 `channel` hits | pass |
| E2 | Recommendation: **do not add** Supabase realtime for lists (§38). Navigation-remount is correct at this data size; targeted cache invalidation only becomes necessary if a client query cache is ever introduced | — | note |
| E3 | AI progress polling bounded (1.5 s, deadline, cancelled on unmount); agent reattach backs off 4 s → 10 s | `AIProgress.tsx:9,168-199`, `agentRunStore.ts:160-261` | pass |

## F. Component inconsistencies

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| F1 | `EmptyState` ×2 (A6) | States.tsx / EmptyState.tsx | P2 |
| F2 | `inputCls` string duplicated per page (~15 copies) instead of one shared field component | every page header | **P2** |
| F3 | Shared primitives that work and form the base of the system: `PageHeader`, `StatusBadge`, `StatusMenu` (Escape + outside click + aria), `TableSkeleton`, `AccountCombobox` (full ARIA pattern), `DraftDeleteButton` | `components/shared/*` | keep |
| F4 | `AccountCombobox` receives the FULL accounts array and filters client-side — same unbounded-list problem one level down (party sub-ledgers grow per customer) | `AccountCombobox.tsx:165-187,287` | **P1** (deferred, designed) |
| F5 | Primary/secondary button styles consistent (`btn-3d btn-shine` vs bordered surface) — unify later, not blocking | repo-wide | P3 |

## G. Accessibility problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| G1 | Modal: no Escape, no focus trap/restore, no dialog semantics (A3) | `Modal.tsx` | **P1** |
| G2 | Search inputs without accessible names (placeholder only) | list pages | **P2** |
| G3 | Table `<th>` without `scope="col"` | all tables | **P3** |
| G4 | `AccountCombobox` implements WAI-ARIA correctly — it is the reference for the new party combobox | `AccountCombobox.tsx` | pass |
| G5 | `prefers-reduced-motion` pauses aura drift; print rules hide chrome | `globals.css:578` | pass |

## H. Mobile / responsive

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| H1 | Mobile sidebar drawer works; tables rely on `overflow-x-auto` (acceptable for accounting grids; column sets to revisit) | `Sidebar.tsx` | **P2** |
| H2 | Modals `max-h-[90vh]` internal scroll — OK; new combobox must stay anchored + internally scrollable on touch | `Modal.tsx:22` | P1 (constraint) |
| H3 | Dashboard KPI grid collapses at `sm:` — OK | `(dashboard)/page.tsx` | pass |

## I. Visual design problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| I1 | Heavy perpetual blur effects (B5) conflict with the "calm, performant" direction | `globals.css:470,646` | **P2** |
| I2 | Every table wrapped in `rounded-2xl border` cards nested in page cards — box-heavy fragmentation (§26) | all pages | **P3** |
| I3 | Radius system mixes `rounded-xl` inputs / `rounded-2xl` cards / `rounded-full` badges — arbitrary in places | repo-wide | **P3** |

## J. Architectural problems

| ID | Finding | Evidence | Pri |
|---|---|---|---|
| J1 | Two data-access styles coexist: browser→PostgREST (older pages) vs FastAPI REST (newer). Decision: **keep both** (§46) — standardize *behaviour* (server search, pagination, counts, degraded flags) instead of rewriting | — | decision |
| J2 | No client query-cache layer; `useOrg` proves the session-cache pattern. Lists don't need a cache once server pagination + keep-previous-rows exists; don't add a caching library now (§38) | — | decision |
| J3 | Virtualization: **not adopted**. Chosen strategy = server pagination (25 rows/page) + bounded combobox results (≤20). Rendering ~25 rows makes a virtualization dependency pure overhead (§10, §38). Revisit only for a genuinely unbounded single-view list | — | decision |
| J4 | Payments/Receipts KPIs must move to SQL (RPC) so their lists can paginate without lying (B6/D4) | migrations 089/090 | **P1** |

---

## Priority order (implementation)

1. **P0** — kill unbounded list fetches (server search + pagination on 10+ pages); fix silent cash-flow truncation.
2. **P1** — searchable party combobox (constrained viewport); request cancellation/stale-guard; GL pagination; payments/receipts summary RPC; Modal a11y; TopBar dead controls.
3. **P2** — search-index migration, error copy, aria labels, blur cost, unification plan.
4. **P3** — visual polish pass (radius/border/typography) — deliberately deferred (churn vs value).


## Implementation record

### Wave 1 — shared infrastructure (P1)

| File | Purpose |
|---|---|
| `frontend/src/lib/lists/logic.ts` | Pure list logic: `sanitizeSearch` (strips `()',` + escapes ILIKE `%_\`), `ilikeAny`, `documentOrFilter` (uuid-validated party-id membership), `pageRange`/`rangeLabel`, `isAbortError`, `createSequencer`, `createRecentList` |
| `frontend/src/lib/lists/logic.test.ts` | 23 unit tests over query-building + paging math |
| `frontend/src/lib/hooks/useServerList.ts` | The list engine: debounced search (250 ms) → page 0, one in-flight load with **AbortController + monotonic sequence** (stale responses dropped), **keep-previous-rows** while refetching (no skeleton flash), exact `count`, page clamping when rows vanish, `refresh()` for mutations |
| `frontend/src/components/shared/Pagination.tsx` | "1–25 of 342 · Page 1 of 14 · Prev/Next", keyboard/aria, dimmed while refreshing |
| `frontend/src/components/shared/PartyCombobox.tsx` | Server-searched customer/supplier combobox: bounded 20-row default ("Recently added" + session "Recent"), 200 ms debounced `name/code/email/phone` search with cancellation, **max-h-64 internally-scrolling viewport anchored to the input**, ↑↓/Enter/Esc keyboard model, WAI-ARIA combobox roles, "+ Create new …" footer → inline create → auto-select (§22), selected label resolves for archived parties |
| `frontend/src/components/shared/Modal.tsx` | a11y (G1): `role="dialog"` + `aria-modal` + `aria-labelledby`, Escape-to-close, focus moves in and returns to the trigger, Tab/Shift+Tab focus trap |

### Wave 2 — master data (P0 fetch-all eliminated)

`customers`, `suppliers`, `employees` pages: `select("*")` + browser `.filter()` →
`useServerList` with **server-side search** (name · code · email · phone · tax for
parties; name · code · department · designation · email for employees), `range(0..24)`
window, `count: exact`, `Pagination`, stable `created_at desc, id` ordering,
select-lists trimmed to rendered columns, `aria-label` on search inputs, table dim
(opacity) while refetching instead of skeleton swaps.

### Wave 3 — sales documents (P0 + P1)

`invoices`, `quotations`, `credit-notes`: status filter + search moved into the
database; party-name search resolved through a **bounded second query**
(customer ids ≤ 200, then `or(invoice_number.ilike…, customer_id.in(…))`) because
PostgREST cannot OR a root column with an embedded one (audit C4). Customer
`<select>` + separate "new customer" input replaced by `PartyCombobox`
(inline create inside the dropdown — one fewer field beside it). Row-action errors
moved to a dedicated `actionError` merged into the same `ErrorState` with a Retry
that clears + reloads.

### Wave 4 — purchases & money (P0 + P1 + migrations)

`bills`, `purchase-returns`: same server-side pattern as Wave 3 with supplier
two-step search; supplier pickers → `PartyCombobox` (bills keeps its bounded
per-supplier open-bill selector).

`payments`, `receipts`: server-side list **plus** the KPI fix (audit B6): the
"Total Paid / Pending / Total" tiles no longer reduce fetched rows — they call
**`get_payment_summary` / `get_receipt_summary`** (migration 089, one indexed SQL
aggregate) and, until that migration runs, fall back to a bounded chunked scan over
narrow columns (`status, amount[, is_transfer]`, 1 000-row pages, 100 k-row cap) —
values stay correct either way, and a capped scan shows **"—"** rather than a
partial number.

- `database/migrations/089_payment_receipt_summary.sql` (**apply manually**)
- `frontend/src/lib/payments/summary.ts` + `summary.test.ts` (6 tests)

### Wave 5 — General Ledger + Cash Flow (P0)

- `general-ledger`: unbounded `select("*")` over `v_general_ledger` → server-side
  account/date/search filters + 25-row pages. Footer is now explicitly
  **"Page totals — 25 of 34 219 lines"** with the Pagination row carrying the
  filtered total (honest, never claiming rows the browser never received).
- `cash-flow` (audit B3 — the silent 500-row cap produced WRONG statement totals):
  movements now fetch in bounded 1 000-row chunks up to 20 000 rows with abort, and
  a cap is reported via a `truncated` banner, never silently; category totals come
  from **`get_cash_flow_summary`** (migration 090, exact SQL aggregate for the
  period) → fallback: sum of a *complete* load → otherwise **"—"**; new editable
  From/To period inputs default to the **current reporting year** (consistent with
  P&L scoping), with an "All time" reset.
- `database/migrations/090_cash_flow_summary.sql` (**apply manually**)
- `frontend/src/lib/reports/cash-flow.ts` + `cash-flow.test.ts` (5 tests)

### Wave 6 — P2 interaction fixes

- **TopBar dead controls (A2)**: the non-functional Search button now opens a real
  palette; the fake notification Bell was removed outright (no notification system
  exists — a permanent red dot is a lie).
- **`CommandMenu`**: Ctrl/Cmd+K page palette (↑↓/Enter/Esc, ARIA combobox/listbox),
  routes flattened from the *exported* Sidebar `navItems` — one source of truth.
  Mounted in the dashboard shell; dispatched from the TopBar button.


### Before → after (query-shape evidence)

| Page | Before | After |
|---|---|---|
| customers/suppliers/employees | `select("*")` · **no limit** · browser `.filter()` | 11–13 named columns · `range` 25 · `count=exact` · `ilike` OR across 5 fields · abortable |
| invoices/quotations/credit-notes/bills/returns | `select("*, embed")` · no limit · status+search in JS | 10–12 columns + embed · `range` 25 · status `.eq` · two-step party search ≤200 ids |
| payments/receipts | `select("*, 2 embeds")` · no limit · KPI `reduce` over ALL rows | 13 columns · `range` 25 · KPI via SQL aggregate (RPC) / bounded scan |
| general ledger | `select("*")` on **every line in range** · JS filter | `range` 25 · server `or()` on 5 fields · server account/date filters |
| cash flow | **`.limit(500)` + totals summed from the 500** | chunked ≤20 000 + SQL-exact totals + truncation banner + period inputs |
| list search inputs | placeholder-only accessible name | `aria-label` added (G2) |

### Deliberate non-changes (§38, §46)

- **No virtualization dependency**: server pagination (25 rows) + bounded combobox
  results (≤20) make DOM size irrelevant (audit J3).
- **No Supabase realtime**: no subscriptions exist; navigation-remount +
  `erp:data-changed` is correct at this data size (audit E1/E2).
- **No data-access rewrite**: browser→PostgREST (older pages) and FastAPI REST
  (newer pages) both remain; only *behaviour* was standardised (audit J1).
- **Chart of Accounts / AccountCombobox server-search** (F4): designed but deferred
  — the grouped tree cannot paginate honestly without a search-first redesign;
  flagged as the next P1.
- **Dashboard open-receivables/payables sums** (B4): deferred to the same
  aggregate-RPC treatment as migration 089 (P2 follow-up).
- Accounting logic, permissions, RLS, AI pipeline: **untouched** (§42, §46).

### Verification (after)

- Frontend `vitest run`: **137 tests pass** (103 baseline + 34 new).
- `tsc --noEmit`: clean.
- Backend `pytest -q`: 857 pass (backend code untouched).
- `eslint`: 0 errors (only pre-existing warnings remain).
- `next build`: **✓ compiled successfully**, type-check + lint phases passed, all
  routes generated (fixed one missing `"use client"` directive on `CommandMenu`
  that only the build phase can catch).

### Migrations — APPLIED and verified (2026-10-04)

`089_payment_receipt_summary.sql` and `090_cash_flow_summary.sql` were applied to
the live Supabase project through the Management API:

```
python scripts/apply_migrations.py 089_payment_receipt_summary.sql 090_cash_flow_summary.sql
→ OK 089_payment_receipt_summary.sql · OK 090_cash_flow_summary.sql
```

End-to-end verification (PostgREST RPC calls, exactly how the app invokes them):

| RPC | Result |
|---|---|
| `get_payment_summary` | **HTTP 200** — `[{"total_paid":0,"total_pending":0,"total":0}]` |
| `get_receipt_summary` | **HTTP 200** — `[{"total_received":0,"total_pending":0,"total":0}]` |
| `get_cash_flow_summary` | **HTTP 200** — `[]` (no movements for the probe org — correct) |

Payments/receipts KPIs and cash-flow category totals now run on the **SQL-exact
path**; the bounded-scan and complete-load fallbacks remain only as safety nets.

Operational note: the previous `SUPABASE_ACCESS_TOKEN` in
`E:\Qoder\.secrets\tokens.env` was expired (Management API returned HTTP 401);
it was refreshed from the new token the owner generated in
Supabase → Account Settings → Access Tokens.

