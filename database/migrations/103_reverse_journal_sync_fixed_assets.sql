-- ============================================================================
-- 103: SYNCHRONIZE FIXED ASSETS ON JOURNAL ENTRY REVERSAL
-- ============================================================================
-- When a posted purchase/compound journal entry is reversed via
-- public.reverse_journal_entry, any linked ACTIVE fixed asset with zero
-- posted depreciation is automatically retired (WRITTEN_OFF) alongside an
-- audit row in public.asset_transactions so the Fixed Asset Register never
-- remains orphaned after voucher reversal.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.reverse_journal_entry(
  p_entry_id uuid,
  p_reversal_date date DEFAULT NULL::date,
  p_reason text DEFAULT NULL::text,
  p_reversed_by uuid DEFAULT NULL::uuid
)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
declare
  v_entry journal_entries%rowtype;
  v_reversal_id uuid;
  v_prefix text;
  v_rev_date date := coalesce(p_reversal_date, current_date);
  v_asset record;
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
    v_rev_date,
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

  -- Coordinate un-depreciated fixed assets registered from this journal
  for v_asset in
    select id, organization_id, purchase_cost, coalesce(description, name) as base_desc
    from public.fixed_assets
    where purchase_journal_entry_id = v_entry.id
      and status = 'ACTIVE'
      and coalesce(accumulated_depreciation, 0) = 0
  loop
    update public.fixed_assets
    set status = 'WRITTEN_OFF',
        disposal_date = v_rev_date,
        disposal_amount = 0,
        disposal_journal_entry_id = v_reversal_id,
        description = trim(both from coalesce(v_asset.base_desc, '') || ' [Purchase Journal Reversed]'),
        updated_at = now()
    where id = v_asset.id;

    insert into public.asset_transactions (
      organization_id, asset_id, transaction_type, transaction_date,
      amount, journal_entry_id, details
    ) values (
      v_asset.organization_id, v_asset.id, 'WRITE_OFF', v_rev_date,
      coalesce(v_asset.purchase_cost, 0), v_reversal_id,
      jsonb_build_object(
        'source', 'journal_reversal',
        'reversed_journal_entry_id', v_entry.id,
        'reason', coalesce(p_reason, 'Reversal')
      )
    );
  end loop;

  return v_reversal_id;
end;
$function$;

GRANT EXECUTE ON FUNCTION public.reverse_journal_entry(uuid, date, text, uuid) TO authenticated, service_role;
