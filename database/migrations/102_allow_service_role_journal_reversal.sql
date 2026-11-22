-- ============================================================
-- 102: ALLOW SERVICE ROLE JOURNAL REVERSAL (AI ASSISTANT / TOOL ROUTER)
-- ============================================================
-- AI Agent tool router calls reverse_journal_entry using the service role.
-- auth.uid() is NULL when called via backend service role client.
-- In migration 051, has_org_role was evaluated even when auth.uid() was NULL,
-- blocking programmatic reversals by authorized admin/owner users through the AI.
--
-- Fix:
--   * If auth.uid() is present (client JWT / browser), enforce has_org_role(org, 2).
--   * If auth.uid() is NULL, service_role/backend caller is already authorized
--     at the API boundary (tool_router checks role and capabilities).
--   * Grant EXECUTE to authenticated and service_role.
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

  -- Authorisation: reversal is restricted to Owner/Admin when called by an end user JWT.
  -- Service-role / backend callers (auth.uid() is NULL) are authorized by the AI tool router.
  if auth.uid() is not null and not public.has_org_role(v_entry.organization_id, 2::smallint) then
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
    v_entry.id, coalesce(p_reversed_by, auth.uid())
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
  set status = 'POSTED', posted_by = coalesce(p_reversed_by, auth.uid())
  where id = v_reversal_id;

  update public.journal_entries
  set status = 'REVERSED', reversed_by_entry_id = v_reversal_id, updated_at = now()
  where id = v_entry.id;

  return v_reversal_id;
end;
$function$;

GRANT EXECUTE ON FUNCTION public.reverse_journal_entry(uuid, date, text, uuid) TO authenticated, service_role;
