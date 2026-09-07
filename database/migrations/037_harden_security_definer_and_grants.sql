-- =====================================================================
-- Migration 037: harden_security_definer_and_grants
-- Security advisor remediation, non-destructive.
-- =====================================================================

-- 1. v_cash_flow must not bypass RLS (was SECURITY DEFINER).
alter view public.v_cash_flow set (security_invoker = true);

-- 2. rls_auto_enable() is a DDL maintenance helper — admin/service-role only.
revoke execute on function public.rls_auto_enable() from anon, authenticated, public;

-- 3. Trigger function: never callable via RPC; pin a schema-qualified
--    search_path so the definer context cannot be hijacked.
revoke execute on function public.trg_bank_accounts_single_default()
  from anon, authenticated, public;
alter function public.trg_bank_accounts_single_default()
  set search_path = public;

-- 4. create_organization: never executable by unauthenticated (anon)
--    callers or by PUBLIC (default EXECUTE grant). Authenticated access
--    is retained for the onboarding flow.
do $$
declare r record;
begin
  for r in
    select p.oid::regprocedure as sig
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'create_organization'
  loop
    execute format('revoke execute on function %s from public', r.sig);
    execute format('revoke execute on function %s from anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end $$;

-- NOTE (accepted, documented): public.is_org_member(uuid) keeps
-- authenticated EXECUTE — it is referenced by RLS policies and runs as
-- the querying role, so revoking it would break row-level security.
