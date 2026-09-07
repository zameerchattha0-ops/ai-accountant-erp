-- Migration: create_reporting_views
-- All views use security_invoker = true so RLS applies through them.

-- General Ledger: posted journal lines enriched with account/party/project names
create view v_general_ledger
with (security_invoker = true) as
select
  e.organization_id,
  e.id            as journal_entry_id,
  e.journal_number,
  l.id            as journal_line_id,
  e.transaction_date,
  e.posted_at,
  l.line_number,
  a.id            as account_id,
  a.code          as account_code,
  a.name          as account_name,
  a.account_type,
  l.description   as line_description,
  e.description   as entry_description,
  l.debit,
  l.credit,
  l.customer_id,
  c.name          as customer_name,
  l.supplier_id,
  s.name          as supplier_name,
  l.project_id,
  p.name          as project_name,
  e.source_type,
  e.source_id
from journal_entries e
join journal_lines l on l.entry_id = e.id
join accounts a      on a.id = l.account_id
left join customers c on c.id = l.customer_id
left join suppliers s on s.id = l.supplier_id
left join projects p  on p.id = l.project_id
where e.status = 'POSTED';

-- Customer ledger with running balance (debit - credit)
create view v_customer_ledger
with (security_invoker = true) as
select
  gl.*,
  sum(gl.debit - gl.credit) over (
    partition by gl.organization_id, gl.customer_id
    order by gl.transaction_date, gl.journal_number, gl.journal_line_id
    rows between unbounded preceding and current row
  ) as running_balance
from v_general_ledger gl
where gl.customer_id is not null;

-- Supplier ledger with running balance (credit - debit)
create view v_supplier_ledger
with (security_invoker = true) as
select
  gl.*,
  sum(gl.credit - gl.debit) over (
    partition by gl.organization_id, gl.supplier_id
    order by gl.transaction_date, gl.journal_number, gl.journal_line_id
    rows between unbounded preceding and current row
  ) as running_balance
from v_general_ledger gl
where gl.supplier_id is not null;

-- Trial balance per account
create view v_trial_balance
with (security_invoker = true) as
select
  a.organization_id,
  a.id            as account_id,
  a.code          as account_code,
  a.name          as account_name,
  a.account_type,
  a.normal_balance,
  coalesce(sum(gl.debit), 0)  as total_debit,
  coalesce(sum(gl.credit), 0) as total_credit,
  coalesce(sum(gl.debit), 0) - coalesce(sum(gl.credit), 0) as balance
from accounts a
join v_general_ledger gl on gl.account_id = a.id
group by a.organization_id, a.id, a.code, a.name, a.account_type, a.normal_balance;

-- Per-account summary respecting normal balance
create view v_account_summary
with (security_invoker = true) as
select
  a.organization_id,
  a.id            as account_id,
  a.code          as account_code,
  a.name          as account_name,
  a.account_type,
  a.normal_balance,
  coalesce(sum(gl.debit), 0)  as total_debit,
  coalesce(sum(gl.credit), 0) as total_credit,
  case a.normal_balance
    when 'DEBIT'  then coalesce(sum(gl.debit), 0) - coalesce(sum(gl.credit), 0)
    when 'CREDIT' then coalesce(sum(gl.credit), 0) - coalesce(sum(gl.debit), 0)
  end as balance
from accounts a
left join v_general_ledger gl on gl.account_id = a.id
group by a.organization_id, a.id, a.code, a.name, a.account_type, a.normal_balance;

-- Open receivables (unpaid invoices) with days outstanding
create view v_open_receivables
with (security_invoker = true) as
select
  i.organization_id,
  i.id             as invoice_id,
  i.invoice_number,
  i.customer_id,
  c.name           as customer_name,
  i.invoice_date,
  i.due_date,
  i.total,
  i.amount_paid,
  i.total - i.amount_paid as outstanding,
  case when i.due_date is null then 0
       else greatest(current_date - i.due_date, 0) end as days_outstanding
from invoices i
join customers c on c.id = i.customer_id
where i.status in ('ISSUED','PARTIALLY_PAID','OVERDUE')
  and (i.total - i.amount_paid) > 0;

-- Open payables (unpaid bills) with days outstanding
create view v_open_payables
with (security_invoker = true) as
select
  b.organization_id,
  b.id           as bill_id,
  b.bill_number,
  b.supplier_id,
  s.name         as supplier_name,
  b.bill_date,
  b.due_date,
  b.total,
  b.amount_paid,
  b.total - b.amount_paid as outstanding,
  case when b.due_date is null then 0
       else greatest(current_date - b.due_date, 0) end as days_outstanding
from purchase_bills b
join suppliers s on s.id = b.supplier_id
where b.status in ('OPEN','PARTIALLY_PAID','OVERDUE')
  and (b.total - b.amount_paid) > 0;

-- Customer aging buckets: current / 1-30 / 31-60 / 61-90 / 90+
create view v_customer_aging
with (security_invoker = true) as
select
  organization_id,
  customer_id,
  customer_name,
  sum(outstanding) as total_outstanding,
  sum(case when days_outstanding <= 0 then outstanding else 0 end) as bucket_current,
  sum(case when days_outstanding between 1 and 30 then outstanding else 0 end) as bucket_1_30,
  sum(case when days_outstanding between 31 and 60 then outstanding else 0 end) as bucket_31_60,
  sum(case when days_outstanding between 61 and 90 then outstanding else 0 end) as bucket_61_90,
  sum(case when days_outstanding > 90 then outstanding else 0 end) as bucket_90_plus
from v_open_receivables
group by organization_id, customer_id, customer_name;

-- Supplier aging buckets
create view v_supplier_aging
with (security_invoker = true) as
select
  organization_id,
  supplier_id,
  supplier_name,
  sum(outstanding) as total_outstanding,
  sum(case when days_outstanding <= 0 then outstanding else 0 end) as bucket_current,
  sum(case when days_outstanding between 1 and 30 then outstanding else 0 end) as bucket_1_30,
  sum(case when days_outstanding between 31 and 60 then outstanding else 0 end) as bucket_31_60,
  sum(case when days_outstanding between 61 and 90 then outstanding else 0 end) as bucket_61_90,
  sum(case when days_outstanding > 90 then outstanding else 0 end) as bucket_90_plus
from v_open_payables
group by organization_id, supplier_id, supplier_name;

-- Project profitability: revenue, costs, gross profit, margin %
create view v_project_profitability
with (security_invoker = true) as
select
  p.organization_id,
  p.id           as project_id,
  p.project_code,
  p.name         as project_name,
  p.status,
  p.budget,
  coalesce(sum(case when gl.account_type = 'REVENUE' then gl.debit - gl.credit end), 0) as project_revenue,
  coalesce(sum(case when gl.account_type = 'EXPENSE' then gl.debit - gl.credit end), 0) as project_costs,
  coalesce(sum(case when gl.account_type = 'REVENUE' then gl.debit - gl.credit end), 0)
    - coalesce(sum(case when gl.account_type = 'EXPENSE' then gl.debit - gl.credit end), 0) as gross_profit,
  case
    when coalesce(sum(case when gl.account_type = 'REVENUE' then gl.debit - gl.credit end), 0) = 0 then null
    else round(
      (coalesce(sum(case when gl.account_type = 'REVENUE' then gl.debit - gl.credit end), 0)
       - coalesce(sum(case when gl.account_type = 'EXPENSE' then gl.debit - gl.credit end), 0))
      / sum(case when gl.account_type = 'REVENUE' then gl.debit - gl.credit end) * 100, 2)
  end as margin_percent
from projects p
left join v_general_ledger gl on gl.project_id = p.id
group by p.organization_id, p.id, p.project_code, p.name, p.status, p.budget;

-- Recent journal entries feed
create view v_recent_transactions
with (security_invoker = true) as
select
  organization_id,
  id              as journal_entry_id,
  journal_number,
  transaction_date,
  description,
  status,
  source_type,
  total_debit,
  created_at
from journal_entries e
order by created_at desc;

-- Income statement (revenue & expense accounts)
create view v_income_statement
with (security_invoker = true) as
select
  a.organization_id,
  a.account_type,
  a.code          as account_code,
  a.name          as account_name,
  coalesce(sum(gl.debit - gl.credit), 0) as net_amount
from accounts a
left join v_general_ledger gl on gl.account_id = a.id
where a.account_type in ('REVENUE','EXPENSE')
  and a.is_active = true
group by a.organization_id, a.account_type, a.code, a.name;

-- Balance sheet (asset, liability & equity accounts)
create view v_balance_sheet
with (security_invoker = true) as
select
  a.organization_id,
  a.account_type,
  a.code          as account_code,
  a.name          as account_name,
  coalesce(sum(gl.debit - gl.credit), 0) as net_amount
from accounts a
left join v_general_ledger gl on gl.account_id = a.id
where a.account_type in ('ASSET','LIABILITY','EQUITY')
  and a.is_active = true
group by a.organization_id, a.account_type, a.code, a.name;

-- Balance sheet summary with derived retained earnings
create view v_balance_sheet_summary
with (security_invoker = true) as
select
  organization_id,
  sum(case when account_type = 'ASSET' then net_amount else 0 end)    as total_assets,
  sum(case when account_type = 'LIABILITY' then net_amount else 0 end) as total_liabilities,
  sum(case when account_type = 'EQUITY' then net_amount else 0 end)   as total_equity,
  coalesce((select sum(is2.net_amount) from v_income_statement is2
            where is2.organization_id = bs.organization_id and is2.account_type = 'EXPENSE'), 0)
  - coalesce((select sum(is2.net_amount) from v_income_statement is2
              where is2.organization_id = bs.organization_id and is2.account_type = 'REVENUE'), 0)
    as retained_earnings
from v_balance_sheet bs
group by organization_id;
