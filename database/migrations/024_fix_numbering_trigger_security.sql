-- Migration: fix_numbering_trigger_security
-- Trigger functions that call the service-role-only next_document_number() must be
-- SECURITY DEFINER, otherwise authenticated frontend users cannot insert rows into
-- numbered tables (customers, suppliers, invoices, bills, payments, ...).
-- Trigger functions are exempt from EXECUTE checks when fired, so EXECUTE is
-- revoked from everyone to make them RPC-inaccessible while triggers keep working.

alter function public.trg_document_number_assign()  security definer;
alter function public.trg_party_code_assign()       security definer;
alter function public.trg_journal_entries_number()  security definer;

revoke execute on function public.trg_document_number_assign()  from public, anon, authenticated;
revoke execute on function public.trg_party_code_assign()       from public, anon, authenticated;
revoke execute on function public.trg_journal_entries_number()  from public, anon, authenticated;
