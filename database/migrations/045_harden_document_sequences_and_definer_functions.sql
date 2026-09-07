-- =====================================================================
-- 045 — SECURITY HARDENING (advisor remediation, evidence-based)
-- =====================================================================
-- Finding 1 (lint 0008, INFO): public.document_sequences has RLS enabled
--   but no policies.
-- Evidence: the ONLY writers are the trg_document_number_assign trigger
--   (SECURITY DEFINER, owned by postgres — verified via pg_proc) and the
--   service role.  Clients never need direct access.
-- Fix: explicit service_role policy (clears the lint) + revoke ALL client
--   privileges (defense in depth).  The definer trigger is unaffected.
-- =====================================================================

drop policy if exists document_sequences_service_role on public.document_sequences;
create policy document_sequences_service_role
  on public.document_sequences
  for all
  to service_role
  using (true)
  with check (true);

revoke all on public.document_sequences from anon;
revoke all on public.document_sequences from authenticated;

-- =====================================================================
-- Finding 2 (lint 0029, WARN): SECURITY DEFINER functions executable by
--   signed-in users.
-- Analysis per function (do NOT blanket-revoke):
-- * create_organization  — KEEP for authenticated AND anon: it is the
--   signup/onboarding entry point (an unauthenticated new user must be
--   able to provision their organization).  Intentional definer.
-- * has_org_role / is_org_member — these are called INSIDE RLS policies;
--   authenticated MUST keep EXECUTE or every org query breaks.  anon has
--   no legitimate use (RLS already denies anonymous business access), so
--   anon EXECUTE is revoked.
-- =====================================================================

revoke execute on function public.has_org_role(uuid, smallint) from anon;
revoke execute on function public.is_org_member(uuid) from anon;
