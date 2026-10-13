-- =====================================================================
-- Migration 095: loan scheduled-events engine + restructure/write-off flows
-- =====================================================================
-- PART A — loan_payment_events: the DURABLE "pending proposed journal"
--   the scheduled sweep creates when an installment becomes due.  A due
--   date does NOT mean cash was paid, so the sweep NEVER posts: it records
--   a PENDING event carrying the exact segregated split; settlement happens
--   only when the owner confirms (record_loan_repayment marks it COMPLETED).
-- PART B — principal_paid / interest_paid per installment: a PARTIAL
--   payment's cash split must persist, so outstanding principal (and a
--   later write-off) are computed from REAL numbers, never approximated.
-- PART C — loan_restructurings: every term change is audited (old terms,
--   new terms, outstanding at the time, reason).
-- =====================================================================

alter table public.loan_installments
  add column if not exists principal_paid numeric(18,2) not null default 0,
  add column if not exists interest_paid  numeric(18,2) not null default 0;

create table if not exists public.loan_payment_events (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  loan_id         uuid not null references public.loans(id) on delete cascade,
  installment_id  uuid not null references public.loan_installments(id) on delete cascade,
  event_type      text not null default 'INSTALLMENT_DUE',
  status          text not null default 'PENDING'
                    check (status in ('PENDING','COMPLETED','DISMISSED')),
  -- The proposed segregated journal, as recorded by the sweep.
  proposed        jsonb not null,
  created_at      timestamptz not null default now(),
  resolved_at     timestamptz
);

-- One PENDING event per installment ever (idempotent sweep: re-running
-- never duplicates; after settlement the row stays as history).
create unique index if not exists uq_loan_events_installment
  on public.loan_payment_events (installment_id);
create index if not exists idx_loan_events_org_status
  on public.loan_payment_events (organization_id, status);

create table if not exists public.loan_restructurings (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  loan_id         uuid not null references public.loans(id) on delete cascade,
  changed_at      timestamptz not null default now(),
  outstanding_principal numeric(18,2) not null,
  old_terms       jsonb not null,
  new_terms       jsonb not null,
  reason          text,
  actor_note      text
);

alter table public.loan_payment_events enable row level security;
alter table public.loan_restructurings enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public'
                 and tablename='loan_payment_events' and policyname='loan_payment_events_org_access') then
    create policy loan_payment_events_org_access on loan_payment_events for all to authenticated
      using (public.is_org_member(organization_id))
      with check (public.is_org_member(organization_id));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public'
                 and tablename='loan_restructurings' and policyname='loan_restructurings_org_access') then
    create policy loan_restructurings_org_access on loan_restructurings for all to authenticated
      using (public.is_org_member(organization_id))
      with check (public.is_org_member(organization_id));
  end if;
end $$;

-- v_loans gains REAL outstanding (cash-aware via principal_paid).  The new
-- column ORDER changes a position name, which CREATE OR REPLACE refuses —
-- DROP + CREATE (same precedent as 091's get_income_statement recreate).
drop view if exists public.v_loans;
create view public.v_loans with (security_invoker = true) as
select
  l.*,
  coalesce(s.scheduled, 0)                         as scheduled_count,
  coalesce(s.paid_count, 0)                        as paid_count,
  coalesce(s.total_interest, 0)                    as total_interest,
  coalesce(s.principal_paid, 0)                    as principal_paid,
  greatest(l.principal - coalesce(s.principal_paid, 0), 0) as outstanding_principal,
  coalesce(cur.current_portion, 0)                 as current_portion,
  greatest(
    greatest(l.principal - coalesce(s.principal_paid, 0), 0)
      - coalesce(cur.current_portion, 0), 0)       as noncurrent_portion,
  nxt.next_due_date,
  coalesce(ov.overdue_count, 0)                    as overdue_count
from public.loans l
left join (
  select loan_id,
         count(*)                                                    as scheduled,
         count(*) filter (where status = 'PAID')                     as paid_count,
         sum(interest_component)                                     as total_interest,
         sum(principal_paid)                                         as principal_paid
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

grant select on public.loan_payment_events to authenticated, service_role;
grant select on public.loan_restructurings to authenticated, service_role;
