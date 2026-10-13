-- =====================================================================
-- Migration 091: perpetual inventory stock ledger + hierarchy P&L RPC
-- =====================================================================
-- PART A — inventory_movements
--   The database has NO stock ledger (documented in
--   app/repositories/product_repository.py).  Perpetual inventory needs one:
--   purchases add QUANTITY (RECEIPT), sales subtract it (ISSUE) and the
--   engine recognises Cost of Sales from the SAME movement data.
--
--   DESIGN (deliberately simple, auditable):
--   * every movement stores its OWN unit_cost.  A RECEIPT carries the
--     purchase unit cost; an ISSUE carries the weighted-average cost the
--     accounting engine computed at posting time, so the journal and the
--     stock ledger can never disagree about the cost of that issue.
--   * v_product_stock derives quantity/value at READ time — no cached
--     aggregate can drift after a correction/reversal.
--
-- PART B — get_income_statement RPC gains parent columns so the P&L page
--   can build the multi-step statement (Revenue → Cost of Sales → Gross
--   Profit → Operating Expenses → Operating Profit → Other Income →
--   Finance Costs → Tax Expense → Net Profit) from the ACCOUNT HIERARCHY
--   instead of hard-coded account names.  The function's return type
--   changes, so it must be DROPped and recreated (Postgres refuses an
--   in-place return-type change).
-- =====================================================================

-- ---------------------------------------------------------------------
-- A1. inventory_movements
-- ---------------------------------------------------------------------
create table if not exists public.inventory_movements (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  product_id      uuid not null references products(id) on delete cascade,
  direction       text not null check (direction in ('RECEIPT','ISSUE')),
  quantity        numeric(18,4) not null check (quantity > 0),
  unit_cost       numeric(18,4) not null check (unit_cost >= 0),
  value           numeric(18,2) not null generated always as (round(quantity * unit_cost, 2)) stored,
  source_type     text,          -- purchase_bill / invoice / cash_sale / manual
  source_id       uuid,          -- journal or document id
  movement_date   date not null default current_date,
  description     text,
  created_at      timestamptz not null default now()
);

create index if not exists idx_inventory_movements_org_product
  on public.inventory_movements (organization_id, product_id);

create index if not exists idx_inventory_movements_source
  on public.inventory_movements (organization_id, source_type, source_id);

-- RLS: same org-membership policy as every tenant table (migration 019).
-- enable_rls is idempotent; the policy is created only when absent so a
-- re-run of this file cannot fail on a duplicate policy name.
alter table public.inventory_movements enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename  = 'inventory_movements'
      and policyname = 'inventory_movements_org_access'
  ) then
    create policy inventory_movements_org_access on inventory_movements
      for all to authenticated
      using (public.is_org_member(organization_id))
      with check (public.is_org_member(organization_id));
  end if;
end $$;

-- ---------------------------------------------------------------------
-- A2. v_product_stock — derived quantity / value / weighted-average cost
-- ---------------------------------------------------------------------
create or replace view public.v_product_stock
with (security_invoker = true) as
select
  p.organization_id,
  p.id as product_id,
  p.product_code,
  p.name,
  coalesce(sum(case when m.direction = 'RECEIPT' then m.quantity else -m.quantity end), 0)
    as quantity_on_hand,
  coalesce(sum(case when m.direction = 'RECEIPT' then m.value else -m.value end), 0)
    as total_value,
  case
    when coalesce(sum(case when m.direction = 'RECEIPT' then m.quantity else -m.quantity end), 0) > 0
    then round(
      coalesce(sum(case when m.direction = 'RECEIPT' then m.value else -m.value end), 0)
      / sum(case when m.direction = 'RECEIPT' then m.quantity else -m.quantity end), 4)
    else 0
  end as average_cost
from public.products p
left join public.inventory_movements m
  on m.product_id = p.id and m.organization_id = p.organization_id
group by p.organization_id, p.id, p.product_code, p.name;

grant select on public.v_product_stock to authenticated, service_role;
revoke all on public.v_product_stock from anon;

-- ---------------------------------------------------------------------
-- B. get_income_statement — recreate WITH hierarchy columns
--     (original: migration 047; additive columns only, same first five
--      names/types/order so existing consumers keep working)
-- ---------------------------------------------------------------------
drop function if exists public.get_income_statement(uuid);

create function public.get_income_statement(target_org uuid)
returns table (
  organization_id uuid,
  account_type text,
  account_code text,
  account_name text,
  net_amount numeric,
  account_id uuid,
  parent_account_code text,
  parent_account_name text,
  is_group boolean
)
language sql
security definer
set search_path = public
stable
as $$
  select a.organization_id,
         a.account_type::text,
         a.code,
         a.name,
         coalesce(sum(gl.debit - gl.credit), 0) as net_amount,
         a.id as account_id,
         pa.code as parent_account_code,
         pa.name as parent_account_name,
         exists (
           select 1 from public.accounts c
           where c.parent_account_id = a.id and c.is_active
         ) as is_group
  from public.accounts a
  join public.journal_lines gl on gl.account_id = a.id
  join public.journal_entries e on e.id = gl.entry_id
  left join public.accounts pa on pa.id = a.parent_account_id
  left join public.financial_years fy
    on fy.organization_id = a.organization_id and fy.is_current
  where a.organization_id = target_org
    and a.account_type in ('REVENUE', 'EXPENSE')
    and a.is_active
    and e.status in ('POSTED', 'REVERSED')
    and (fy.id is null
         or e.transaction_date between fy.start_date and fy.end_date)
  group by a.organization_id, a.account_type, a.code, a.name,
           a.id, pa.code, pa.name
$$;

grant execute on function public.get_income_statement(uuid) to authenticated;

