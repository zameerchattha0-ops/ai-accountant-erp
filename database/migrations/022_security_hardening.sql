-- Migration: security_hardening
-- Remediation of Supabase Security Advisor findings:
--   1. Pin search_path on SECURITY DEFINER / plpgsql functions (search_path hijacking).
--   2. Relocate pg_trgm to the extensions schema (keeps public clean, Supabase convention).
--   3. (Privilege revokes continue in migration 023.)

-- ---- 1. Pin search_path on all functions ----
alter function public.is_org_member(uuid)                        set search_path = public, extensions;
alter function public.has_org_role(uuid, smallint)               set search_path = public, extensions;
alter function public.get_period_for_date(uuid, date)            set search_path = public, extensions;
alter function public.next_document_number(uuid, text, text)     set search_path = public, extensions;
alter function public.trg_document_number_assign()               set search_path = public, extensions;
alter function public.trg_party_code_assign()                    set search_path = public, extensions;
alter function public.trg_journal_entries_number()               set search_path = public, extensions;
alter function public.trg_journal_entries_status()               set search_path = public, extensions;
alter function public.trg_journal_lines_guard()                  set search_path = public, extensions;
alter function public.trg_journal_lines_totals()                 set search_path = public, extensions;
alter function public.prevent_account_cycle()                    set search_path = public, extensions;
alter function public.set_updated_at()                           set search_path = public, extensions;
alter function public.close_accounting_period(uuid)              set search_path = public, extensions;
alter function public.reopen_accounting_period(uuid, uuid)       set search_path = public, extensions;
alter function public.validate_journal_entry(uuid)               set search_path = public, extensions;
alter function public.post_journal_entry(uuid, uuid)             set search_path = public, extensions;
alter function public.reverse_journal_entry(uuid, date, text, uuid) set search_path = public, extensions;

-- ---- 2. Move pg_trgm into the extensions schema ----
-- Existing GIN indexes follow the opclass automatically.
alter extension pg_trgm set schema extensions;
