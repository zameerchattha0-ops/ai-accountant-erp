# Transaction Recording Constitution — Architecture Gap Report

**Status:** DRAFT FOR REVIEW — no code changed. Implementation is STOPPED until
this report is reviewed (Constitution §25).

**Inspected commit:** `192b658` (main == origin/main == production).
**Method:** live read of services, engine, repositories, tools, migrations
(71 SQL files, 001–080), frontend pages, archive test pins, and repowiki
cross-claims — every claim below carries a `file:line` or is marked *verify*.

---

## 1. Current invoice accounting flow

**AI path (fully journaled, party-correct):**
`create_invoice` tool → `invoice_service.create_invoice` (`invoice_service.py:24-143`,
parity law: item validation, totals recomputed from lines) → `post_invoice_atomic`
RPC with `p_journal: None` (`:127`; the RPC only writes a journal when
`p_journal` is non-null — `076_atomic_invoice_posting.sql:112`) → **the tool
handler then calls `auto_journal(document_type="invoice")`** (`tools/__init__.py:394`)
→ `engine.record_credit_sale` (`accounting_engine.py:122-166`): Dr `receivable_account_id`
(the customer's **dedicated child ledger**, resolved `auto_journal` → `:560-563`)
+ `customer_id` on both lines, Cr revenue. Quotation conversion journals too
(`quotation_service.py:182`).

**UI path (NOT journaled):** `sales/invoices/page.tsx:189` inserts `invoices` +
`invoice_items` **directly via supabase** — zero calls to any journal-creation
function exist anywhere in `frontend/src` (grep: `auto_journal|post_journal|…` → no hits).
The invoice exists; the GL never sees it.

## 2. Current purchase accounting flow

**AI path:** `create_purchase_bill` tool → purchase service → atomic RPC
(migration 077) → tool handler `auto_journal("purchase_bill")`
(`tools/__init__.py:475`) → `engine.record_credit_purchase`
(`accounting_engine.py:39-80`): Dr expense/asset, Cr **supplier's dedicated
payable child account** (`:603-605`), `supplier_id` on both lines.
**UI path:** `purchases/bills/page.tsx:168` inserts directly — **no journal** (same as §1).

## 3. Current customer-party relationship

`customers` (`006_create_customers_suppliers.sql:3-23`): **no `balance` column**
(§19 satisfied by schema). `receivable_account_id` FK → per-party child GL
(`1100-0001 ABC …`) created and linked at customer creation
(`customer_service.py:59-78`) with explicit backfill
(`party_ledger_service.py` — control-account ladder, exact-name reuse, read-only
resolution; archived pin `test_party_ledger_accounts.py`). Journal lines carry
`customer_id`; invoices carry `customer_id`. Evidence layer exposes the party +
open items (`books_evidence.py:360,704`, `v_open_receivables`).

## 4. Current supplier-party relationship

Symmetric: `suppliers.payable_account_id` (`006:68`), engine lines carry
`supplier_id`, `_resolve_supplier_payable` (`payment_service.py:247-268`; row →
PAYABLE-category fallback → raises if none), nature-aware payment debit side
(§6). Archived pins assert `credit_purchase payable_account_id == party account`.

## 5. Current receivable/payable implementation

Dual-layer: **document state** (`invoices.amount_paid/status` via
`_update_invoice_paid`, `payment_service.py:271-288`; bills `:291-308`) +
**GL state** (party child accounts under 1100/2010) + **allocations**
(`receipt_allocations` / `payment_allocations`, `013:26-65`) + **reporting**
`v_customer_ledger` / `v_supplier_ledger` (journal-derived, window running
balance), `v_open_receivables`, aging views. The two layers agree **only on
the AI path** (see §11-V1).

## 6. Current payment/receipt behavior

`payment_service.record_customer_receipt` (`:315-423`): money side follows the
channel (`_resolve_settlement_gl` — cash never crossed with bank); **credit side
follows `transaction_nature`** (`_resolve_receipt_credit_account`): settlement →
party receivable, **advance → customer-advances liability, loan → loan account,
fallback warns and the warning is disclosed** (`:408-410`). Atomic
`create_receipt_atomic` (078) + validate + post. Supplier payments mirror it
(advance → supplier-advances **asset**). Nature routing exists on the
deterministic fast path (`agent.py:312-407`: ALLOCATION / ADVANCE /
LOAN_OR_SETTLEMENT) and the archived `test_settlement_ledger.py` pins all four
branchings; the model path depends on the tool contract emitting
`transaction_nature` (**verify** at implementation time).

## 7. Current settlement/allocation model

Schema supports **many rows per receipt/payment** (013:57-65). Every code path
creates **exactly one row with `amount_allocated = full receipt amount`**:
service (`payment_service.py:412-420`) and UI (`receipts/page.tsx:153`,
`payments/page.tsx:156`). **No over-allocation guard**
(`_update_invoice_paid` adds unconditionally; `new_paid` may exceed `total`).
**No invoice↔customer linkage check** at allocation (observed at `:412-420` —
*verify exhaustively during implementation*). Overpayment/remainder → advance
split does not exist.

## 8. Current ledger implementation

Backend complete: `v_customer_ledger` / `v_supplier_ledger` (running balance),
repositories `get_customer_ledger` (`customer_repository.py:107-122`) /
`get_supplier_ledger` (`supplier_repository.py:105`), AI tools
`get_customer_ledger` / `get_supplier_ledger`, report intents
`generate_customer_ledger` / `generate_supplier_ledger` (planner report
vocabulary + `ai.agent_capabilities` seed), evidence kind `ledgers`.
**Frontend: nothing.** `customers/page.tsx` and `suppliers/page.tsx` contain
**zero** matches for `balance`, `ledger`, `export`, `download` (the only
"export" hit is the TS `export default` keyword) — no balance column, no
View-Ledger action, no export action on either page.

## 9. Current journal implementation

`journal_entries` + `journal_lines` with customer/supplier/project/tax
dimensions; balance enforced (engine invariant + DB constraints/triggers);
open-period enforcement; posted-entry immutability + reversal; deterministic
numbering; `prepare_journal → validate_journal → post_journal` pipeline
(`accounting_service`); atomic doc+journal RPCs (076/077/078); idempotency
(075); `verify_journal` (`accounting_engine.py:376-396`) feeding Phase 7/8
verification.

## 10. What already satisfies the Constitution

- **§1/§6 party-centric + symmetric:** dedicated per-party child GL accounts,
  `customer_id`/`supplier_id` on journal lines and engine builders, backfill.
- **§2 (AI path):** party ledger IS journal-derived — GL ↔ subledger reconcile.
- **§8:** `record_cash_sale` = Dr Cash/Bank, Cr Revenue — no phantom receivable.
- **§9/§13:** nature-aware receipts/payments (settlement/advance/loan with
  disclosed fallbacks) + fast-path nature routing; the receipt ladder asks the
  economic-nature question before allocation (`test_receipt_ladder`).
- **§10/§17:** evidence-first — `v_open_receivables`, party gates, search-before-
  ask, M0 canaries; **§18:** `AccountingReasoningContext` provenance incl. the
  FIX-4a honest-PREFERENCE label.
- **§19:** no manual balance state anywhere in schema.
- **§20:** double-entry validation, atomic posting, idempotency keys, RLS
  tenant isolation, Phase 7/8 verification.
- **§21:** generic primitives only — no `security_deposit()`-style templates;
  engine builders + journal + settlement allocations compose all 12 M0 canaries.
- **§16/§22:** skeptical ladders + evidence layer can answer the three questions
  for the AI path.

## 11. What violates it

- **V1 (critical) — UI write paths bypass the accounting engine.** Invoices,
  bills, receipts, and allocations are inserted **directly** from the browser;
  `frontend/src` contains **no journal-creation call anywhere**. The receipts
  page even states *"The journal entry … will be created by the AI agent"*
  (`receipts/page.tsx:346`) — an unenforced convention; the AI agent creates
  its own receipts and does not journalize UI rows. Result: documents +
  `amount_paid` move while the GL and `v_customer_ledger` do not →
  §2 reconciliation, §19, §20 violated on every UI-originated transaction.
- **V2 — allocation integrity:** no over-allocation guard, no receipt-customer ↔
  invoice linkage check, full amount forced onto a single invoice (§11/§12).
- **V3 — multi-invoice settlement impossible** in code despite schema support (§12).
- **V4 — no party balance / ledger / export UI** (§3/§4/§5).
- **V5 — confirmation preview is free-text**, not generated from the proposed
  plan (no Dr/Cr table, no party-effect, no balance delta) (§23).
- **V6 — nature wiring on the model path** must be confirmed against the live
  tool contract (§9) (*verify*).

## 12. What can be reused (do not rebuild)

Party-ledger service + child accounts; engine `record_*` builders; atomic RPCs
076–078; `receipt/payment_allocations` schema (already multi-row);
`v_customer_ledger`/`v_supplier_ledger` + repositories + AI ledger tools;
nature-aware `_resolve_receipt_credit_account` / `_resolve_payment_debit_account`;
reporting pipeline (`generated_reports`, XLSX/PDF/CSV/JSON formats);
evidence kinds + party gates + materialization aliases; confirmation +
verification + audit machinery; the full archive test pins
(`test_party_ledger_accounts`, `test_settlement_ledger`,
`test_cross_module_lifecycles`, `test_receipt_ladder`).

## 13. What must evolve

1. UI write paths → service/RPC-backed endpoints (or DB-level enforcement).
2. Allocation engine: outstanding-balance guard, party-linkage check, multi-row
   allocation, remainder semantics (overpay → advance or ask).
3. Tool contracts: allocation list + `transaction_nature` on settlement tools.
4. Customers/Suppliers pages: balance column, View Ledger, Export — all from the
   same authoritative view query (§5).
5. Confirmation preview composed from the proposed plan (aligns prior M3).

## 14. What genuinely does not exist yet

Multi-invoice allocation code path · allocation validators · party-ledger/export
UI · engine-authored confirmation preview (§23) · DB-level journal enforcement
for direct table writes · settlement-remainder → advance auto-split ·
invoice↔customer validation at allocation time.

---

## Smallest migration sequence (proposal — not started)

| # | Change | Constitution refs | Risk | Proof |
|---|---|---|---|---|
| **C1** | **Close the engine bypass**: route UI invoice/bill/receipt writes through existing service/RPC endpoints (or enforce at DB level), so *every* document gets its journal atomically | §1 §2 §19 §20 | medium (UI flows) | `test_cross_module_lifecycles`, live A/B: UI receipt ⇒ visible in `v_customer_ledger` + GL |
| **C2** | **Allocation correctness**: fail-closed over-allocation guard, receipt-customer ↔ invoice match, multi-row allocation, remainder → existing nature ladder (advance vs settlement) | §11 §12 §13 | low-medium | new unit tests + `test_settlement_ledger` extensions |
| **C3** | **Nature wiring verification + contract**: confirm/force `transaction_nature` through the model-path tool contract; audit fallback warnings reach the confirmation | §9 §16 | low | contract test + receipt-ladder E2E |
| **C4** | **Customers/Suppliers page**: receivable/payable balance, View Ledger, Export — single authoritative query behind UI and export | §3 §4 §5 | low | UI parity test: exported rows == view rows == AI `get_customer_ledger` |
| **C5** | **Engine-authored confirmation preview** (Dr/Cr + party effect + balance delta from the proposed plan; aligns migration-report M3) | §7 §17 §23 | low | snapshot tests against engine-built plans |

Sequenced by integrity-first: **C1 → C2 → C3 → (C4 ∥ C5)**. Each lands as its
own local-only commit with the full regression gates
(`app/tests` + archive net + `_validate_fix` + `_validate_alias` +
`_measure_prompt`) before the next begins.

---

**STOP — awaiting review before any implementation.**

