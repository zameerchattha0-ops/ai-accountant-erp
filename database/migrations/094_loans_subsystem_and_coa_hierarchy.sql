-- =====================================================================
-- Migration 094: LOANS & FINANCING subsystem + COA hierarchy correction
-- =====================================================================
-- PART A — loans / loan_installments.  The LOAN SCHEDULE is the source of
--   truth: principal outstanding, current/non-current portions, interest
--   accrued/paid and next due date are DERIVED from these tables (never
--   from manually maintained accounts).  Every accounting event a loan
--   generates carries its unique descriptive narration (e.g.
--   'Loan - HBL - Vehicle Financing - 2026').
-- PART B — COA hierarchy correction (below the tables): seeds the missing
--   category headings and re-parents OBVIOUS top-level accounts.
-- =====================================================================

-- ---------------------------------------------------------------------
-- A1. loans — one row per borrowing OR lending, a controlled accounting object
-- ---------------------------------------------------------------------
create table if not exists public.loans (
  id                 uuid primary key default gen_random_uuid(),
  organization_id    uuid not null references organizations(id) on delete cascade,
  direction          text not null check (direction in ('BORROWED','GIVEN')),
  -- Unique descriptive identity, attached to EVERY journal this loan makes.
  narration          text not null,
  counterparty       text not null,          -- lender (BORROWED) / borrower (GIVEN)
  purpose            text,
  principal          numeric(18,2) not null check (principal > 0),
  currency_code      char(3) not null default 'PKR',
  loan_date          date not null default current_date,
  interest_rate      numeric(9,5) not null default 0,   -- annual %
  interest_method    text not null default 'REDUCING'
                       check (interest_method in ('REDUCING','FLAT')),
  tenure_months      int not null check (tenure_months > 0),
  frequency          text not null default 'MONTHLY'
                       check (frequency in ('MONTHLY','QUARTERLY','SEMI_ANNUAL','ANNUALLY','CUSTOM')),
  custom_interval_months int check (custom_interval_months is null or custom_interval_months > 0),
  first_payment_date date not null,
  maturity_date      date,
  grace_months       int not null default 0 check (grace_months >= 0),
  balloon_amount     numeric(18,2) not null default 0 check (balloon_amount >= 0),
  fees_charges       numeric(18,2) not null default 0,
  -- GL wiring (resolved/created by the service at loan creation)
  cash_account_id    uuid not null references accounts(id),
  loan_account_id    uuid not null references accounts(id),      -- payable / receivable
  interest_account_id uuid references accounts(id),             -- expense / income
  party_id           uuid,                                       -- supplier/customer link when present
  status             text not null default 'ACTIVE'
                       check (status in ('ACTIVE','COMPLETED','DEFAULTED','WRITTEN_OFF')),
  initial_entry_id   uuid references journal_entries(id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create unique index if not exists uq_loans_org_narration
  on public.loans (organization_id, narration);
create index if not exists idx_loans_org_status
  on public.loans (organization_id, status);

-- ---------------------------------------------------------------------
-- A2. loan_installments — the amortization schedule (source of truth)
-- ---------------------------------------------------------------------
create table if not exists public.loan_installments (
  id                 uuid primary key default gen_random_uuid(),
  organization_id    uuid not null references organizations(id) on delete cascade,
  loan_id            uuid not null references public.loans(id) on delete cascade,
  installment_no     int not null check (installment_no > 0),
  due_date           date not null,
  opening_principal  numeric(18,2) not null,
  principal_component numeric(18,2) not null,
  interest_component numeric(18,2) not null,
  total_due          numeric(18,2) not null,
  closing_principal  numeric(18,2) not null check (closing_principal >= 0),
  status             text not null default 'SCHEDULED'
                       check (status in ('SCHEDULED','DUE','PAID','PARTIAL','OVERDUE','WAIVED')),
  paid_date          date,
  paid_amount        numeric(18,2) not null default 0,
  journal_entry_id   uuid references journal_entries(id),
  created_at         timestamptz not null default now(),
  unique (loan_id, installment_no)
);

create index if not exists idx_loan_installments_due
  on public.loan_installments (organization_id, due_date, status);

-- RLS — same org-membership policy family as every tenant table (019/091).
alter table public.loans enable row level security;
alter table public.loan_installments enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public'
                 and tablename='loans' and policyname='loans_org_access') then
    create policy loans_org_access on loans for all to authenticated
      using (public.is_org_member(organization_id))
      with check (public.is_org_member(organization_id));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public'
                 and tablename='loan_installments' and policyname='loan_installments_org_access') then
    create policy loan_installments_org_access on loan_installments for all to authenticated
      using (public.is_org_member(organization_id))
      with check (public.is_org_member(organization_id));
  end if;
end $$;


-- ---------------------------------------------------------------------
-- A3. v_loan_installment_schedule — schedule + derived status at read time
--   overdue: due_date < CURRENT_DATE and not paid/waived
-- ---------------------------------------------------------------------
create or replace view public.v_loan_installment_schedule
with (security_invoker = true) as
select
  i.organization_id,
  i.loan_id,
  l.narration,
  l.direction,
  l.counterparty,
  i.installment_no,
  i.due_date,
  i.opening_principal,
  i.principal_component,
  i.interest_component,
  i.total_due,
  i.closing_principal,
  case
    when i.status in ('PAID','WAIVED') then i.status
    when i.due_date < current_date then 'OVERDUE'
    when i.due_date <= current_date + interval '30 days' then 'DUE'
    else i.status
  end as live_status,
  i.paid_date,
  i.paid_amount,
  i.journal_entry_id
from public.loan_installments i
join public.loans l on l.id = i.loan_id;

-- ---------------------------------------------------------------------
-- A4. v_loans — one row per loan with schedule-derived position
--   current_portion  = unpaid principal due within the next 12 months
--   noncurrent_portion = remaining unpaid principal beyond 12 months
--   (computed from the SCHEDULE — never manually maintained)
-- ---------------------------------------------------------------------
create or replace view public.v_loans
with (security_invoker = true) as
select
  l.*,
  coalesce(s.scheduled, 0)                         as scheduled_count,
  coalesce(s.paid_count, 0)                        as paid_count,
  coalesce(s.total_interest, 0)                    as total_interest,
  coalesce(s.paid_principal, 0)                    as principal_paid,
  coalesce(cur.current_portion, 0)                 as current_portion,
  greatest(
    coalesce(s.unpaid_principal, l.principal)
      - coalesce(cur.current_portion, 0), 0)       as noncurrent_portion,
  nxt.next_due_date,
  coalesce(ov.overdue_count, 0)                    as overdue_count
from public.loans l
left join (
  select loan_id,
         count(*)                                                    as scheduled,
         count(*) filter (where status = 'PAID')                     as paid_count,
         sum(interest_component)                                     as total_interest,
         sum(principal_component) filter (where status = 'PAID')      as paid_principal,
         sum(principal_component) filter (where status <> 'PAID'
                                            and status <> 'WAIVED')    as unpaid_principal
  from public.loan_installments group by loan_id
) s on s.loan_id = l.id
left join (
  select loan_id, sum(principal_component) as current_portion
  from public.loan_installments
  where status <> 'PAID' and status <> 'WAIVED'
    and due_date between current_date and current_date + interval '12 months'
  group by loan_id
) cur on cur.loan_id = l.id
left join (
  select loan_id, min(due_date) as next_due_date
  from public.loan_installments
  where status <> 'PAID' and status <> 'WAIVED'
  group by loan_id
) nxt on nxt.loan_id = l.id
left join (
  select loan_id, count(*) as overdue_count
  from public.loan_installments
  where due_date < current_date and status <> 'PAID' and status <> 'WAIVED'
  group by loan_id
) ov on ov.loan_id = l.id;

grant select on public.v_loan_installment_schedule to authenticated, service_role;
grant select on public.v_loans to authenticated, service_role;


-- =====================================================================
-- PART B — COA hierarchy correction
--   B1 seeds missing category headings (idempotent, per org, collision-safe
--   code probing).  B2 re-parents ONLY exact-name, TOP-LEVEL, same-type
--   matches — a custom-named account is never touched.
-- =====================================================================
do $$
declare
  org record;
  h  record;
  heading_id uuid;
  code_candidate text;
begin
  for org in select id from public.organizations loop
    for h in
      select * from (values
        ('Current Assets','ASSET','DEBIT',null,'1900'),
        ('Non-Current Assets','ASSET','DEBIT',null,'1910'),
        ('Property, Plant & Equipment','ASSET','DEBIT','Non-Current Assets','1920'),
        ('Loans Receivable','ASSET','DEBIT','Non-Current Assets','1350'),
        ('Current Liabilities','LIABILITY','CREDIT',null,'2900'),
        ('Non-Current Liabilities','LIABILITY','CREDIT',null,'2910'),
        ('Current Portion of Long-Term Loan','LIABILITY','CREDIT','Current Liabilities','2140'),
        ('Long-Term Loans','LIABILITY','CREDIT','Non-Current Liabilities','2300'),
        ('Interest Income','REVENUE','CREDIT','Other Income','4910')
      ) as t(name, atype, nb, parent_name, code_base)
    loop
      if not exists (
        select 1 from public.accounts a
         where a.organization_id = org.id
           and lower(a.name) = lower(h.name)
           and a.account_type::text = h.atype
      ) then
        heading_id := null;
        if h.parent_name is not null then
          select a.id into heading_id from public.accounts a
           where a.organization_id = org.id
             and lower(a.name) = lower(h.parent_name)
             and a.account_type::text = h.atype
           limit 1;
        end if;
        code_candidate := h.code_base;
        while exists (select 1 from public.accounts a
                       where a.organization_id = org.id and a.code = code_candidate) loop
          code_candidate := (code_candidate::int + 1)::text;
        end loop;
        insert into public.accounts
          (organization_id, code, name, account_type, normal_balance,
           parent_account_id, is_control_account, is_active, is_system, description)
        values
          (org.id, code_candidate, h.name, h.atype::account_type_code,
           h.nb::normal_balance_code, heading_id,
           false, true, false, 'Seeded category heading (migration 094)');
      end if;
    end loop;
  end loop;
end $$;


-- B2. Re-parent obvious top-level accounts (exact name, top-level only,
--     same type as the heading, never the heading itself).
do $$
declare
  org record;
  m   record;
  heading_id uuid;
  moved int;
begin
  for org in select id from public.organizations loop
    for m in
      select * from (values
        ('Cash','Current Assets','ASSET'),
        ('Cash Account','Current Assets','ASSET'),
        ('Petty Cash','Current Assets','ASSET'),
        ('Bank','Current Assets','ASSET'),
        ('Banks','Current Assets','ASSET'),
        ('Bank Account','Current Assets','ASSET'),
        ('Accounts Receivable','Current Assets','ASSET'),
        ('Inventory','Current Assets','ASSET'),
        ('Stock In Hand','Current Assets','ASSET'),
        ('Prepaid Expenses','Current Assets','ASSET'),
        ('Accounts Payable','Current Liabilities','LIABILITY'),
        ('Accrued Expenses','Current Liabilities','LIABILITY'),
        ('Accrued Liabilities','Current Liabilities','LIABILITY'),
        ('Short-Term Borrowings','Current Liabilities','LIABILITY'),
        ('Salaries Payable','Current Liabilities','LIABILITY'),
        ('Land','Property, Plant & Equipment','ASSET'),
        ('Building','Property, Plant & Equipment','ASSET'),
        ('Buildings','Property, Plant & Equipment','ASSET'),
        ('Plant & Machinery','Property, Plant & Equipment','ASSET'),
        ('Machinery','Property, Plant & Equipment','ASSET'),
        ('Vehicles','Property, Plant & Equipment','ASSET'),
        ('Office Equipment','Property, Plant & Equipment','ASSET'),
        ('Furniture & Fixtures','Property, Plant & Equipment','ASSET'),
        ('Computer Equipment','Property, Plant & Equipment','ASSET'),
        ('Equipment','Property, Plant & Equipment','ASSET'),
        ('Leasehold Improvements','Property, Plant & Equipment','ASSET')
      ) as t(acct_name, heading_name, atype)
    loop
      select a.id into heading_id from public.accounts a
       where a.organization_id = org.id
         and lower(a.name) = lower(m.heading_name)
         and a.account_type::text = m.atype
       limit 1;
      if heading_id is null then
        continue;  -- heading absent (sparse chart) -> leave the chart alone
      end if;
      update public.accounts a
         set parent_account_id = heading_id
       where a.organization_id = org.id
         and lower(a.name) = lower(m.acct_name)
         and a.account_type::text = m.atype
         and a.parent_account_id is null      -- top-level only
         and a.id <> heading_id
         and a.is_active;
      get diagnostics moved = row_count;
      if moved > 0 then
        raise notice 'coa-094: moved % under % (org %)',
          m.acct_name, m.heading_name, org.id;
      end if;
    end loop;
  end loop;
end $$;

