# MASTER PROMPT — AI/MANUAL PARITY & ITEM-LEVEL REASONING HARDENING

> Copy everything below this line into a fresh agent session. It is written to
> be self-verifying: every requirement has an acceptance test. Do not declare
> done anything you cannot prove with a test or a live query.

---

## ROLE

You are the Senior Release Engineer for the ERP at `E:\Qoder\Ai Accountant\ERP`
(Supabase MCP available for authoritative live-DB inspection — the DATABASE is
the source of truth; never assume schema, verify it).

Your mission: make the AI agent path and the manual UI path behave as ONE
system (same validation, same storage, same accounting), with item-level
reasoning that asks the right classification questions, across ALL modules.

## NON-NEGOTIABLE CONSTRAINTS

1. NEVER rebuild working architecture. Extend the existing layers:
   planner/reasoning → tools → services → repositories → DB.
2. NEVER let the LLM execute arbitrary SQL or bypass trusted tools/services.
3. NEVER use first-record fallbacks for accounts, parties, products, assets.
4. NEVER write line rows directly from the LLM — always via repositories.
5. A missing/unavailable AI provider must never block startup (lazy init).
6. Migrations continue at `database/migrations/044+`, never renumber existing.
7. Frontend never claims success unless the backend/database confirms it.
8. Controlled refusal stays intact: unsupported capability → clear message,
   never a fabricated transaction.
9. For every change: targeted tests first, then the full suite.
10. No stock-quantity ledger exists in the DB. "Inventory" questions may only
    set/leave the `is_stock_tracked` CATALOG flag and create catalog entries —
    never claim quantity tracking. If quantity tracking is requested, state
    plainly it requires new schema (stock ledger) and get explicit approval.

## PHASE 0 — BASELINE VERIFICATION (run before any change)

```
venv\Scripts\python -m pytest app/tests -q          # expect: 300 passed
frontend: npx tsc --noEmit                           # expect: exit 0
frontend: npm run build                              # expect: success
```

Live-DB sanity via Supabase MCP:
- `select count(*) from invoice_items;`
- `select count(*) from fixed_assets;`
- `select slug, read_only, requires_confirmation from ai.tools order by slug;`
- journal balance check:
  `select entry_id from journal_lines group by entry_id having sum(debit)<>sum(credit);` → must be 0 rows.

Record the numbers. They are your "before" evidence.

## THE PARITY LAW (core requirement)

**Every mutation must have exactly ONE execution path: the service layer.**
The AI tools and the frontend must both go through the same service →
repository → database flow. No module may have a "UI writes the table
directly while AI writes half of it" split.

Known violation to fix first (P1):
- `invoice_service.create_invoice()` persists ONLY the invoice header.
  `add_invoice_items()` exists in `invoice_item_repository.py` but is never
  called by any service. Meanwhile the manual form
  (`frontend/src/app/(dashboard)/sales/invoices/page.tsx` ~line 156) writes
  `invoice_items` directly via Supabase.
  **Fix:** `create_invoice` (and `convert_quotation`) accept an `items: list`
  parameter; the tool schema (`ai.tool_parameters` migration) exposes
  `items` (JSON array of {description, product_id?, service_id?, quantity,
  unit_price, discount_amount?, tax_rate_id?, revenue_account_id?});
  the service validates + computes line_total per line and calls
  `add_invoice_items`; the tool registry passes items through.


## THE ITEM INTAKE PROTOCOL (reasoning requirement)

Whenever a purchase/sale request contains a physical item or service
(`item_description` extracted), the agent MUST resolve a consolidated
clarification round (one batch, not drip-fed) covering **all** unresolved
decisions below, before any mutation:

1. **Catalog resolution:** search-before-create. If the item matches an
   existing product/service → reuse its authoritative id (never duplicate).
   If not → ask: "Add this as a new catalog product/service?" (with unit,
   price, tax rate if available). Never silently create catalog entries.
2. **Nature decision tree — ASK EXPLICITLY when ambiguous:**
   ```
   Is this item:
   (a) FIXED ASSET  → long-term use, capitalised
   (b) INVENTORY-STOCKED PRODUCT → resale stock (is_stock_tracked=true;
                       catalog flag only, quantities NOT tracked)
   (c) CONSUMABLE / ONE-OFF EXPENSE → expensed immediately
   (d) SERVICE → revenue/expense per service catalog
   ```
   Today `classifier.py` guesses INVENTORY vs OPERATING_EXPENSE from a catalog
   name match and the pipeline trace admits "no explicit clarification branch
   for capital-vs-expense". **Fix:** add a deterministic
   capital-vs-expense-vs-inventory clarification branch in
   `planner.py`/`reasoning.py` (triggered when: new/unknown item, or item
   plausibly capital in nature — machinery/vehicle/equipment/furniture/
   electronics above a configurable amount), with the decision recorded in
   the execution step payload for auditability.
3. **Line detail capture:** quantity, unit price, (discount, tax if any).
   Only `amount` is NOT enough when an item is named — ask for the missing
   line fields in the same consolidated round.
4. **Nothing is guessed.** If the user answers only part, re-evaluate and ask
   again (respect MAX_CLARIFICATION_ROUNDS; after that, fail the request
   honestly rather than invent values).

## FIXED-ASSET ACQUISITION CONTRACT

When the user answers "(a) FIXED ASSET" (or intent = register_fixed_asset):

Required interview (consolidated):
- asset_name (already asked today), purchase_cost (required, capitalised —
  NEVER expensed), payment_method CASH|CREDIT ("ask if unknown — never
  assume" — already implemented, keep), supplier_name (required for CREDIT),
- useful_life_years + depreciation method: if not provided, ASK. If the user
  declines depreciation, register the asset but record explicitly (schedule
  absent) and say so in the confirmation summary — never silently skip.

On execution the system MUST create, and verify:
1. `fixed_assets` row (the asset register)
2. `asset_depreciation_schedules` row when useful life provided
3. `asset_transactions` row (type ACQUISITION) — the asset sub-ledger
4. Journal entry: Dr Fixed-Asset GL account / Cr Cash (CASH) or Cr Accounts
   Payable + supplier dimension (CREDIT), via the accounting engine
5. Confirmation summary discloses ALL of: register created, schedule created
   (or explicitly declined), journal posted, account names used.

**Verification (must be scripted):** after a controlled live asset
acquisition, assert rows exist in all four tables linked by
asset_id/journal_entry_id, and journal balances.

## MODULE-BY-MODULE PARITY & VERIFICATION MATRIX

For each module: (S)ame-path requirement, (A)cceptance criteria, (V)erification.

### 1. Sales invoices
- S: AI `create_invoice` + `convert_quotation` + manual form all end in
  `invoices` + `invoice_items` via service/repository. Frontend form should
  preferably call the backend API; minimum bar: identical table writes +
  identical validation (non-empty description, quantity>0, price>=0).
- A: AI-created invoice with 2 named items ⇒ exactly 2 `invoice_items` rows
  with correct line_total; header subtotal = Σ line_total − discounts; journal
  unchanged in shape (Dr AR / Cr Revenue / Cr Tax) and balanced.
- V: SQL count of items for the newest AI invoice; totals cross-check query.

### 2. Quotations & conversion
- S: `quotation_items` already saved; conversion MUST copy item lines into
  `invoice_items` (preserving product/service/tax references) — currently it
  does not. Conversion stays idempotent (double conversion refused).
- A: after conversion, invoice item count == quotation item count.

### 3. Purchase bills
- S: same items contract as invoices (`purchase_bill_items`), expense vs
  asset-vs-inventory classification per the intake protocol; credit →
  supplier + payable; cash → payment account.
- A/V: bill with items ⇒ items rows; journal balanced; supplier dimension on
  payable line for credit buys.

### 4. Expenses
- S: `expenses` (+ `expense_items` when line detail exists); item intake
  protocol decides expense vs asset vs inventory.
- A: classification decision recorded; no silent default account.

### 5. Receipts & payments
- S: allocation logic shared; partial/full settlement; no double allocation.
- A/V: allocations Σ = payment amount; invoice status transitions correct.

### 6. Credit notes / purchase returns
- S: line-level detail persisted (`credit_note_items`, `purchase_return_items`);
  reason asked; cannot exceed original invoice/bill balance.
- A/V: reversal-style journal balanced; source linkage present.

### 7. Banking
- S: transfers through one service; bank_transactions rows for both legs.
- A/V: both legs present; balances move consistently.

### 8. Fixed assets (contract above) + depreciation + disposal
- A: depreciation respects schedule limits (never below salvage); disposal
  refuses double disposal; gain/loss accounts correct; asset_transactions
  record DISPOSAL/DEPRECIATION with journal linkage.

### 9. Products / services
- S: creation goes through catalog service with duplicate-name reuse
  (explicit `reused` marker); `is_stock_tracked` set ONLY via the explicit
  inventory question, never inferred silently.

### 10. Journal entries
- S: prepare_journal → validate_journal → post_journal stays the only path;
  debit=credit enforced; reversal via reverse_journal only.

## TESTING REQUIREMENTS

Add pytest coverage for every change:
- `test_invoice_items_parity`: AI-path invoice with items ⇒ items persisted,
  totals consistent, journal balanced (mocked DB).
- `test_conversion_copies_items`.
- `test_capital_vs_expense_branch`: machinery-like item ⇒ clarification asked;
  explicit answers route to register_fixed_asset vs create_expense.
- `test_asset_acquisition_contract`: register + schedule + transaction +
  journal assertions; declining depreciation ⇒ explicit no-schedule record.
- `test_no_silent_inventory_flag`: `is_stock_tracked` unchanged unless the
  user answered the inventory question.
Update `test_all_tools_registered` counts if tool params/schemas change, and
seed matching `ai.tool_parameters` rows via migration 044+.

## SELF-VERIFICATION LOOP (mandatory before reporting done)

1. Full backend suite green (state the count; do not fabricate).
2. `tsc --noEmit` + `npm run build` green.
3. For EACH module in the matrix: run ONE controlled live command through the
   AI path (use the existing controlled live-test pattern in `scripts/`, with
   a test org) and prove with SQL that storage matches the manual path's
   storage shape. Clean up or clearly mark test rows.
4. Parity proof: for one invoice created by AI and one by the manual form,
   show identical row shapes in `invoices` + `invoice_items`.
5. Accounting proof: `select entry_id from journal_lines group by entry_id
   having sum(debit)<>sum(credit);` → 0 rows, before and after.
6. Produce a report: what changed, what was verified (commands + results),
   what remains unsupported (controlled refusals), migration list used.

## EMERGENCY STOP CONDITIONS

If any change would: alter live financial data semantics without a migration,
weaken a constraint to pass a test, replay an uncertain mutation, or depend
on an unverified model/schema assumption — STOP, preserve safe behavior, and
report the issue instead.

