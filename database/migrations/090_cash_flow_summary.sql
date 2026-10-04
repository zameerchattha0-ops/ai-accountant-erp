-- Migration: 090_cash_flow_summary
-- Exact category totals for the Cash Flow statement.
--
-- Why (UX audit B3, P0): the statement page summed whatever rows it had
-- fetched — it capped the fetch at 500 rows, so once an organisation posted
-- more than 500 cash movements the OPERATING/INVESTING/FINANCING totals and
-- the net figure were silently WRONG. Totals now come from one grouped SQL
-- pass over v_cash_flow for the selected period, regardless of row volume;
-- the page falls back to summing its loaded rows only when this function has
-- not been applied yet, and hides the tiles entirely if that fallback cannot
-- be trusted (truncated load) rather than showing a partial number.
--
-- Apply with:  python scripts/apply_migrations.py 090_cash_flow_summary.sql
--
-- Hardened like migration 071's report RPCs: SECURITY DEFINER +
-- assert_org_report_access (ACTIVE membership, 42501 otherwise).

create or replace function public.get_cash_flow_summary(
  target_org uuid,
  p_from date default null,
  p_to date default null
)
returns table(
  category text,
  total    numeric
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
    v.cash_flow_category,
    coalesce(sum(v.net_amount), 0)::numeric
  from public.v_cash_flow v
  where v.organization_id = target_org
    and (p_from is null or v.transaction_date >= p_from)
    and (p_to is null or v.transaction_date <= p_to)
  group by v.cash_flow_category;
end;
$function$;

comment on function public.get_cash_flow_summary(uuid, date, date) is
  'Org- and period-scoped cash-flow totals per category (OPERATING/INVESTING/FINANCING). NULL dates mean unbounded.';
