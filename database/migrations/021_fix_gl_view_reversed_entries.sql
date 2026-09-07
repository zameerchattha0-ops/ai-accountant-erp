-- Migration: fix_gl_view_reversed_entries
-- The General Ledger originally exposed only POSTED entries. A reversed original
-- entry must remain visible (accounting history is never deleted), so REVERSED
-- entries are now included and the entry status is surfaced as a column.
-- DRAFT/VALIDATED/VOIDED entries remain excluded (not part of the books).

create or replace view v_general_ledger
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
  e.source_id,
  e.status        as entry_status
from journal_entries e
join journal_lines l on l.entry_id = e.id
join accounts a      on a.id = l.account_id
left join customers c on c.id = l.customer_id
left join suppliers s on s.id = l.supplier_id
left join projects p  on p.id = l.project_id
where e.status in ('POSTED','REVERSED');
