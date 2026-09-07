-- =====================================================================
-- Migration 039 (part 1): backfill_account_categories
-- =====================================================================
-- Root cause: create_organization() and the test-org seed inserted
-- accounts WITHOUT account_category_id.  v_cash_flow joins
-- account_categories on BANK/CASH, so cash-flow reporting was
-- structurally empty for every seeded organisation.

-- 1. Bank-linked GL accounts are BANK (never CASH)
update public.accounts a
set account_category_id = (select c.id from public.account_categories c
                           where c.code = 'BANK')
where a.account_category_id is null
  and a.id in (select gl_account_id from public.bank_accounts
               where gl_account_id is not null);

-- 2. Deterministic type/name mapping for the remainder
update public.accounts a
set account_category_id = c.id
from public.account_types t
join public.account_categories c on c.account_type_id = t.id
where a.account_category_id is null
  and t.code = a.account_type
  and c.code = case a.account_type::text
      when 'ASSET' then case
          when a.name ilike '%accumulated%' then 'ACCUM_DEPRECIATION'
          when a.name ilike '%cash%' then 'CASH'
          when a.name ilike '%bank%' then 'BANK'
          when a.name ilike '%receivable%' then 'RECEIVABLE'
          when a.name ilike '%inventory%' or a.name ilike '%stock%' then 'INVENTORY'
          when a.name ilike '%prepaid%' or a.name ilike '%advance%' then 'PREPAID'
          when a.code like '15%' or a.name ilike '%equipment%'
               or a.name ilike '%furniture%' or a.name ilike '%vehicle%'
               or a.name ilike '%building%' then 'FIXED_ASSET'
          else 'OTHER_ASSET' end
      when 'LIABILITY' then case
          when a.name ilike '%payable%' and a.name ilike '%tax%' then 'TAX_PAYABLE'
          when a.name ilike '%payable%' then 'PAYABLE'
          when a.name ilike '%credit card%' then 'CREDIT_CARD'
          when a.name ilike '%loan%' then 'LOAN'
          when a.name ilike '%unearned%' or a.name ilike '%deferred%' then 'UNEARNED_REVENUE'
          when a.name ilike '%accrued%' then 'ACCRUED'
          else 'OTHER_LIABILITY' end
      when 'EQUITY' then case
          when a.name ilike '%retained%' then 'RETAINED_EARNINGS'
          when a.name ilike '%drawing%' then 'DRAWINGS'
          else 'OWNER_CAPITAL' end
      when 'REVENUE' then case
          when a.name ilike '%other income%' then 'OTHER_INCOME'
          else 'OPERATING_REVENUE' end
      when 'EXPENSE' then case
          when a.name ilike '%depreciation%' then 'DEPRECIATION_EXPENSE'
          when a.name ilike '%salary%' or a.name ilike '%wage%'
               or a.name ilike '%payroll%' then 'PAYROLL'
          when a.name ilike '%tax%' then 'TAX_EXPENSE'
          else 'OPERATING_EXPENSE' end
  end;
