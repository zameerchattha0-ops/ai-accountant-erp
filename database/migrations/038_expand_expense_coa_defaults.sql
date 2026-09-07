-- =====================================================================
-- Migration 038: expand_expense_coa_defaults
-- Expense COA correction + safe deterministic default.
-- =====================================================================
-- Root cause fixed: the manually-created account code '5-1010' sorts
-- before the 6xxx series under the repository's `code.asc` ordering, so
-- EVERY "first EXPENSE account" default (classifier fallback, engine
-- _resolve_default_account) resolved to Utilities Expense, and no
-- account name matched the classifier's consumable term "supplies".

-- 1. Recode the anomalous 5-1010 into the standard 6xxx series.
--    Journal lines reference accounts by id — history is unaffected.
update public.accounts a
set code = '6140', updated_at = now()
where a.code = '5-1010'
  and not exists (
    select 1 from public.accounts b
    where b.organization_id = a.organization_id and b.code = '6140'
  );

-- 2. 'Office Expenses' → 'Office Supplies': the deterministic classifier
--    searches consumables by "supplies"/"consumable" name terms.
--    Applied to live accounts AND template reference data (future orgs).
update public.accounts
set name = 'Office Supplies', updated_at = now()
where account_type = 'EXPENSE' and name = 'Office Expenses';

update public.account_template_items
set name = 'Office Supplies'
where account_type = 'EXPENSE' and name = 'Office Expenses';

-- 3. Safe last-resort default: the first-by-code EXPENSE account becomes
--    a genuinely generic account instead of Salaries (6010) after the
--    recode in step 1.
insert into public.accounts
  (organization_id, code, name, account_type, normal_balance,
   is_system, is_active, description)
select o.id, '6000', 'General Operating Expense', 'EXPENSE', 'DEBIT',
       true, true, 'Default operating expense account for unmapped purchases'
from public.organizations o
where not exists (
  select 1 from public.accounts a
  where a.organization_id = o.id and a.code = '6000'
);

-- 4b. The inserted 6000 item must also carry the operating-expense
--     category (reporting views join on account_categories).
update public.account_template_items ti
set account_category_id = (select c.id from public.account_categories c
                           join public.account_types t
                             on t.id = c.account_type_id
                           where c.code = 'OPERATING_EXPENSE')
where ti.code = '6000' and ti.account_category_id is null;

-- 4. Same safe default for every future organisation template.
insert into public.account_template_items
  (template_id, code, name, account_type, sort_order)
select t.id, '6000', 'General Operating Expense', 'EXPENSE', 0
from public.account_templates t
where not exists (
  select 1 from public.account_template_items ti
  where ti.template_id = t.id and ti.code = '6000'
);
