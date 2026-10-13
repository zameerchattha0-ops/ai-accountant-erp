-- =====================================================================
-- Migration 092: restore report access guard lost by 091's recreate
-- =====================================================================
-- FINDING (CRITICAL control regression, discovered 2026-10-13 while
-- verifying migration 091 objects on live project gghkbpdaqogncbrwzmpp):
--
--   071 hardened get_trial_balance / get_income_statement with
--   assert_org_report_access + explicit revokes from PUBLIC and anon.
--   091 DROPPED and recreated get_income_statement as LANGUAGE sql
--   SECURITY DEFINER.  A recreated function inherits Postgres's DEFAULT
--   ACL — EXECUTE granted to PUBLIC — and 091's file only GRANTs to
--   authenticated; it never re-revokes.  Live check confirmed:
--     has_function_privilege('anon', 'get_income_statement(uuid)', 'EXECUTE')
--     => true    (while get_trial_balance correctly stays false)
--   Any anonymous caller could read ANY organization's P&L by passing an
--   arbitrary target_org.  The 071 membership guard was also absent from
--   the 091 body.
--
-- FIX: recreate with the SAME nine-column return type (contract kept:
-- 071's first five names/types/order + 091's four hierarchy columns),
-- restore the assert_org_report_access guard, and re-apply 071's
-- revoke/grant set.  LANGUAGE plpgsql is required for the leading
-- perform guard.
-- =====================================================================

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
language plpgsql
stable
security definer
set search_path = public
as $function$
begin
  perform public.assert_org_report_access(target_org);

  return query
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
           a.id, pa.code, pa.name;
end;
$function$;

-- 071's grant set, re-applied (the PUBLIC default must die again).
revoke all on function public.get_income_statement(uuid) from public;
revoke all on function public.get_income_statement(uuid) from anon;
grant execute on function public.get_income_statement(uuid) to authenticated;
grant execute on function public.get_income_statement(uuid) to service_role;

comment on function public.get_income_statement(uuid) is
  'Hierarchical P&L (091 columns) with 071 access guard restored (092): '
  'SECURITY DEFINER + assert_org_report_access; EXECUTE revoked from PUBLIC/anon.';
