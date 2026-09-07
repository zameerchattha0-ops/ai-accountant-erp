-- ============================================================
-- 051: FIX reverse_journal_entry PERMISSIONS FOR THE JOURNAL PAGE
-- ============================================================
-- Live defect (Owner, Journal page): clicking "Reverse" on a POSTED
-- entry failed with
--   "permission denied for function reverse_journal_entry" (403).
--
-- Root cause: the security-hardening migrations (023/037/045) revoked
-- EXECUTE from authenticated, and the function is SECURITY INVOKER while
-- calling next_document_number (invoker-only, document_sequences is
-- service-role-only by design). No caller path from the UI could work.
--
-- Fix (mirrors the create_next_financial_year pattern):
--   * The function becomes SECURITY DEFINER (search_path already
--     pinned) so the document-numbering sequence and settings read work.
--   * An INTERNAL guard now authorises the caller: only an active
--     Owner/Admin (has_org_role(org, 2)) of the entry's organisation may
--     reverse - matching the DELETE policy and the Journal page gate.
--     auth.uid() is unaffected by DEFINER, so the 049 audit trigger still
--     records the real actor.
--   * EXECUTE granted to authenticated.
-- ============================================================

CREATE OR REPLACE FUNCTION public.reverse_journal_entry(p_entry_id uuid, p_reversal_date date DEFAULT NULL::date, p_reason text DEFAULT NULL::text, p_reversed_by uuid DEFAULT NULL::uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
declare
  v_entry journal_entries%rowtype;
  v_reversal_id uuid;
  v_prefix text;
begin
  select * into v_entry from public.journal_entries where id = p_entry_id;
  if not found then
    raise exception 'Journal entry % not found', p_entry_id;
  end if;

  -- Authorisation: reversal is the correction path for POSTED financial
  -- documents - restricted to Owner/Admin, matching the DELETE policy.
  if not public.has_org_role(v_entry.organization_id, 2::smallint) then
    raise exception 'Only the Owner or an Administrator can reverse journal entries';
  end if;

  if v_entry.status <> 'POSTED' then
    raise exception 'Only POSTED entries can be reversed, entry is %', v_entry.status;
  end if;
  if v_entry.reversal_of_entry_id is not null then
    raise exception 'Reversal entries cannot themselves be reversed';
  end if;

  select coalesce(s.journal_prefix, 'JE') into v_prefix
  from public.organization_settings s where s.organization_id = v_entry.organization_id;

  insert into public.journal_entries (
    organization_id, journal_number, transaction_date, accounting_period_id,
    description, reference, status, source_type, source_id, currency_code,
    total_debit, total_credit, reversal_of_entry_id, created_by
  ) values (
    v_entry.organization_id,
    public.next_document_number(v_entry.organization_id, 'JOURNAL', coalesce(v_prefix, 'JE')),
    coalesce(p_reversal_date, current_date),
    null,
    coalesce('Reversal of ' || v_entry.journal_number || case when p_reason is not null then ': ' || p_reason else '' end, 'Reversal'),
    v_entry.journal_number,
    'DRAFT', 'REVERSAL', v_entry.id, v_entry.currency_code,
    v_entry.total_credit, v_entry.total_debit,
    v_entry.id, p_reversed_by
  ) returning id into v_reversal_id;

  insert into public.journal_lines (
    organization_id, entry_id, line_number, account_id, description,
    debit, credit, customer_id, supplier_id, project_id, tax_rate_id
  )
  select
    l.organization_id, v_reversal_id, l.line_number, l.account_id,
    coalesce('Reversal: ' || l.description, 'Reversal'),
    l.credit, l.debit,
    l.customer_id, l.supplier_id, l.project_id, l.tax_rate_id
  from public.journal_lines l
  where l.entry_id = v_entry.id;

  update public.journal_entries
  set status = 'POSTED', posted_by = p_reversed_by
  where id = v_reversal_id;

  update public.journal_entries
  set status = 'REVERSED', reversed_by_entry_id = v_reversal_id, updated_at = now()
  where id = v_entry.id;

  return v_reversal_id;
end;
$function$;

GRANT EXECUTE ON FUNCTION public.reverse_journal_entry(uuid, date, text, uuid) TO authenticated;
