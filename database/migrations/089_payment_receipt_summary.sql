-- Migration: 089_payment_receipt_summary
-- Aggregate KPIs for the Payments / Receipts pages.
--
-- Why (UX audit B6/D4): the "Total paid / Pending / Total" tiles used to sum
-- EVERY payment row inside the browser, which (a) shipped the whole table to
-- the client and (b) made it impossible to paginate those lists honestly —
-- any page-based UI would have shown page-scoped money totals. One indexed
-- SQL pass replaces both problems.
--
-- Apply with:  python scripts/apply_migrations.py 089_payment_receipt_summary.sql
-- Until it runs, the frontend falls back to a bounded chunked scan (correct
-- values, heavier transport) — the pages work either way.
--
-- Hardened like migration 071's report RPCs: SECURITY DEFINER +
-- assert_org_report_access (ACTIVE membership, 42501 otherwise).

create or replace function public.get_payment_summary(target_org uuid)
returns table(
  total_paid    numeric,
  total_pending numeric,
  total         bigint
)
language plpgsql
stable
security definer
set search_path = public
as $function$
begin
  perform public.assert_org_report_access(target_org);

  return query
  select
    coalesce(sum(case when p.status = 'COMPLETED' and p.is_transfer = false
                      then p.amount end), 0)::numeric,
    coalesce(sum(case when p.status = 'PENDING'
                      then p.amount end), 0)::numeric,
    count(*)::bigint
  from public.payments p
  where p.organization_id = target_org;
end;
$function$;

create or replace function public.get_receipt_summary(target_org uuid)
returns table(
  total_received numeric,
  total_pending  numeric,
  total          bigint
)
language plpgsql
stable
security definer
set search_path = public
as $function$
begin
  perform public.assert_org_report_access(target_org);

  return query
  select
    coalesce(sum(case when r.status = 'COMPLETED' then r.amount end), 0)::numeric,
    coalesce(sum(case when r.status = 'PENDING' then r.amount end), 0)::numeric,
    count(*)::bigint
  from public.receipts r
  where r.organization_id = target_org;
end;
$function$;

comment on function public.get_payment_summary(uuid) is
  'Org-scoped KPI totals for payments: completed (excl. transfers), pending, count.';
comment on function public.get_receipt_summary(uuid) is
  'Org-scoped KPI totals for receipts: completed, pending, count.';
