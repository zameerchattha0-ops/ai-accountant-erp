-- Migration: revoke_public_execute_rls_helpers
-- Least-privilege EXECUTE grants on helper functions.

-- ---- RLS helper functions: authenticated may execute (needed inside policies) ----
revoke execute on function public.is_org_member(uuid)          from public;
revoke execute on function public.has_org_role(uuid, smallint) from public;
grant  execute on function public.is_org_member(uuid)          to authenticated;
grant  execute on function public.has_org_role(uuid, smallint) to authenticated;

-- ---- Sensitive business functions: service role only ----
-- Numbering, period close/reopen and journal lifecycle must only run from the
-- trusted backend; anon/authenticated clients must never call them directly.
revoke execute on function public.next_document_number(uuid, text, text)  from public, anon, authenticated;
revoke execute on function public.close_accounting_period(uuid)           from public, anon, authenticated;
revoke execute on function public.reopen_accounting_period(uuid, uuid)    from public, anon, authenticated;
revoke execute on function public.validate_journal_entry(uuid)            from public, anon, authenticated;
revoke execute on function public.post_journal_entry(uuid, uuid)          from public, anon, authenticated;
revoke execute on function public.reverse_journal_entry(uuid, date, text, uuid) from public, anon, authenticated;
