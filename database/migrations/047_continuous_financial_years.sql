-- =====================================================================
-- 047 — CONTINUOUS FINANCIAL YEARS + REPORTING-YEAR SCOPED REPORTS
-- =====================================================================
-- * create_next_financial_year(org): owner/admin clicks "Add next year"
--   in Settings — creates the FOLLOWING year (start = prev end + 1 day)
--   with 12 monthly OPEN periods, continuously, forever.  If "today"
--   falls inside the new year it becomes the reporting year automatically
--   (recording continues seamlessly; posting needs an OPEN period).
-- * set_reporting_year(org, year): switches which year reports cover.
-- * get_income_statement / get_trial_balance: SAME row shapes as the
--   existing views but filtered to the org's REPORTING year
--   (financial_years.is_current).  Falls back to all-time when the org
--   has no reporting year.  Balance-sheet stays cumulative (correct).
-- =====================================================================

create or replace function public.create_next_financial_year(target_org uuid)
returns public.financial_years
language plpgsql
security definer
set search_path = public
as $$
declare
  latest public.financial_years;
  next_start date;
  next_end date;
  fy_name text;
  new_year public.financial_years;
  m int;
  p_start date;
  p_end date;
begin
  if not has_org_role(target_org, 2::smallint) then
    raise exception 'Only the Owner or an Administrator can create financial years';
  end if;

  select * into latest
  from public.financial_years
  where organization_id = target_org
  order by end_date desc
  limit 1;

  if latest.id is null then
    raise exception 'No financial year exists yet — create the first one during onboarding.';
  end if;

  next_start := latest.end_date + 1;
  next_end := (next_start + interval '1 year' - interval '1 day')::date;

  if exists (
    select 1 from public.financial_years
    where organization_id = target_org and start_date = next_start
  ) then
    raise exception 'The next financial year (% → %) already exists.', next_start, next_end;
  end if;

  if date_part('year', next_start) = date_part('year', next_end) then
    fy_name := 'FY ' || date_part('year', next_start)::text;
  else
    fy_name := 'FY ' || date_part('year', next_start)::text || '-'
             || lpad((date_part('year', next_end) % 100)::text, 2, '0');
  end if;

  -- If TODAY falls inside the new year, it becomes the reporting year
  -- automatically (so recording continues without a manual switch).
  insert into public.financial_years
    (organization_id, name, start_date, end_date, status, is_current)
  values
    (target_org, fy_name, next_start, next_end, 'OPEN',
     date_trunc('day', now())::date between next_start and next_end)
  returning * into new_year;

  if new_year.is_current then
    update public.financial_years
    set is_current = false
    where organization_id = target_org and id <> new_year.id;
  end if;

  -- 12 monthly periods, OPEN, so posting works immediately.
  for m in 1..12 loop
    p_start := (next_start + ((m - 1) || ' month')::interval)::date;
    p_end := (next_start + (m || ' month')::interval - interval '1 day')::date;
    if p_end > next_end then p_end := next_end; end if;
    if p_start > next_end then p_start := next_end; end if;
    insert into public.accounting_periods
      (organization_id, financial_year_id, period_number, name,
       start_date, end_date, status)
    values
      (target_org, new_year.id, m,
       to_char(p_start, 'Mon') || ' ' || to_char(p_start, 'YYYY'),
       p_start, p_end, 'OPEN')
    on conflict do nothing;
  end loop;

  return new_year;
end;
$$;

create or replace function public.set_reporting_year(target_org uuid, year_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not has_org_role(target_org, 2::smallint) then
    raise exception 'Only the Owner or an Administrator can change the reporting year';
  end if;
  if not exists (
    select 1 from public.financial_years
    where organization_id = target_org and id = year_id
  ) then
    raise exception 'Financial year does not belong to this organization';
  end if;
  update public.financial_years set is_current = false
  where organization_id = target_org;
  update public.financial_years set is_current = true where id = year_id;
end;
$$;

-- Year-scoped income statement (same shape as v_income_statement).
create or replace function public.get_income_statement(target_org uuid)
returns table (
  organization_id uuid,
  account_type text,
  account_code text,
  account_name text,
  net_amount numeric
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
         coalesce(sum(gl.debit - gl.credit), 0) as net_amount
  from public.accounts a
  join public.journal_lines gl on gl.account_id = a.id
  join public.journal_entries e on e.id = gl.entry_id
  left join public.financial_years fy
    on fy.organization_id = a.organization_id and fy.is_current
  where a.organization_id = target_org
    and a.account_type in ('REVENUE', 'EXPENSE')
    and a.is_active
    and e.status in ('POSTED', 'REVERSED')
    and (fy.id is null
         or e.transaction_date between fy.start_date and fy.end_date)
  group by a.organization_id, a.account_type, a.code, a.name
$$;

-- Year-scoped trial balance (same shape as v_trial_balance).
create or replace function public.get_trial_balance(target_org uuid)
returns table (
  account_id uuid,
  account_code text,
  account_name text,
  account_type text,
  normal_balance text,
  total_debit numeric,
  total_credit numeric,
  balance numeric
)
language sql
security definer
set search_path = public
stable
as $$
  select a.id,
         a.code,
         a.name,
         a.account_type::text,
         a.normal_balance::text,
         coalesce(sum(gl.debit), 0) as total_debit,
         coalesce(sum(gl.credit), 0) as total_credit,
         (coalesce(sum(gl.debit), 0) - coalesce(sum(gl.credit), 0)) as balance
  from public.accounts a
  join public.journal_lines gl on gl.account_id = a.id
  join public.journal_entries e on e.id = gl.entry_id
  left join public.financial_years fy
    on fy.organization_id = a.organization_id and fy.is_current
  where a.organization_id = target_org
    and e.status in ('POSTED', 'REVERSED')
    and (fy.id is null
         or e.transaction_date between fy.start_date and fy.end_date)
  group by a.id, a.code, a.name, a.account_type, a.normal_balance
$$;

grant execute on function public.create_next_financial_year(uuid) to authenticated;
grant execute on function public.set_reporting_year(uuid, uuid) to authenticated;
grant execute on function public.get_income_statement(uuid) to authenticated;
grant execute on function public.get_trial_balance(uuid) to authenticated;
