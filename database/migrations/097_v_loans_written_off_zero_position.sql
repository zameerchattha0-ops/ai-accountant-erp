-- =====================================================================
-- Migration 097: v_loans presents a WRITTEN_OFF loan at zero position
-- =====================================================================
-- FINDING (live lifecycle E2E, 2026-10-14): after write_off_loan the GL
-- balance is extinguished by the forgiveness/impairment journal, but
-- v_loans.outstanding_principal still showed principal - principal_paid
-- (cash-based) — a written-off loan must present as fully settled.
-- The view now derives: WRITTEN_OFF => outstanding/current/non-current = 0.
-- =====================================================================
drop view if exists public.v_loans;

create view public.v_loans with (security_invoker = true) as
select
  l.*,
  coalesce(s.scheduled, 0)                         as scheduled_count,
  coalesce(s.paid_count, 0)                        as paid_count,
  coalesce(s.total_interest, 0)                    as total_interest,
  coalesce(s.principal_paid, 0)                    as principal_paid,
  case when l.status = 'WRITTEN_OFF' then 0
       else greatest(l.principal - coalesce(s.principal_paid, 0), 0)
  end                                              as outstanding_principal,
  case when l.status = 'WRITTEN_OFF' then 0
       else coalesce(cur.current_portion, 0)
  end                                              as current_portion,
  case when l.status = 'WRITTEN_OFF' then 0
       else greatest(
              greatest(l.principal - coalesce(s.principal_paid, 0), 0)
                - coalesce(cur.current_portion, 0), 0)
  end                                              as noncurrent_portion,
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

grant select on public.v_loans to authenticated, service_role;
