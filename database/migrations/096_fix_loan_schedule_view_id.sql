-- =====================================================================
-- Migration 096: v_loan_installment_schedule must expose the installment id
-- =====================================================================
-- FINDING (live lifecycle E2E, 2026-10-14): the sweep keys installments by
-- ``row["id"]``, but the 094 view selected every column EXCEPT ``i.id`` —
-- KeyError on the first live run.  Recreated (DROP+CREATE: 091/095
-- precedent) with the id FIRST so consumers can tie events/payments back
-- to the exact row.
-- =====================================================================
drop view if exists public.v_loan_installment_schedule;

create view public.v_loan_installment_schedule
with (security_invoker = true) as
select
  i.id,
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
  i.status,
  i.paid_date,
  i.paid_amount,
  i.principal_paid,
  i.interest_paid,
  i.journal_entry_id
from public.loan_installments i
join public.loans l on l.id = i.loan_id;

grant select on public.v_loan_installment_schedule to authenticated, service_role;
