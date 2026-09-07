-- Migration: create_business_functions
-- Party code assignment, period close/reopen, journal lifecycle, updated_at triggers

-- Assign CUST-/SUP- codes from organization_settings prefixes
create or replace function trg_party_code_assign()
returns trigger language plpgsql as $$
declare
  v_prefix text;
  v_doc_type text := tg_argv[0];
  v_prefix_col text := tg_argv[1];
  v_code_col text := tg_argv[2];
  v_default text := tg_argv[3];
begin
  if to_jsonb(new) ->> v_code_col is null or to_jsonb(new) ->> v_code_col = '' then
    execute format('select coalesce(s.%I, %L) from public.organization_settings s where s.organization_id = $1', v_prefix_col, v_default)
      into v_prefix using new.organization_id;
    execute format('new.%I := public.next_document_number($1, $2, $3)', v_code_col)
      using new.organization_id, v_doc_type, coalesce(v_prefix, v_default);
  end if;
  return new;
end;
$$;

create trigger trg_customers_code before insert on customers
  for each row execute function trg_party_code_assign('CUSTOMER','customer_prefix','customer_code','CUST');

create trigger trg_suppliers_code before insert on suppliers
  for each row execute function trg_party_code_assign('SUPPLIER','supplier_prefix','supplier_code','SUP');

-- Close an accounting period (LOCKED is permanent); auto-close FY when no OPEN periods remain
create or replace function close_accounting_period(p_period_id uuid)
returns void language plpgsql as $$
declare
  v_period accounting_periods%rowtype;
  v_open_count int;
begin
  select * into v_period from public.accounting_periods where id = p_period_id;
  if not found then
    raise exception 'Accounting period % not found', p_period_id;
  end if;
  if v_period.status = 'CLOSED' then
    raise exception 'Accounting period % is already closed', v_period.name;
  end if;
  if v_period.status = 'LOCKED' then
    raise exception 'Accounting period % is locked and cannot be modified', v_period.name;
  end if;

  update public.accounting_periods
  set status = 'CLOSED', closed_at = now(), updated_at = now()
  where id = p_period_id;

  select count(*) into v_open_count
  from public.accounting_periods p
  where p.financial_year_id = v_period.financial_year_id and p.status = 'OPEN';

  if v_open_count = 0 then
    update public.financial_years
    set status = 'CLOSED', closed_at = now(), updated_at = now()
    where id = v_period.financial_year_id and status = 'OPEN';
  end if;
end;
$$;

-- Reopen a CLOSED period (LOCKED can never be reopened)
create or replace function reopen_accounting_period(p_period_id uuid, p_reopened_by uuid default null)
returns void language plpgsql as $$
declare
  v_period accounting_periods%rowtype;
begin
  select * into v_period from public.accounting_periods where id = p_period_id;
  if not found then
    raise exception 'Accounting period % not found', p_period_id;
  end if;
  if v_period.status = 'LOCKED' then
    raise exception 'Accounting period % is LOCKED and cannot be reopened', v_period.name;
  end if;
  if v_period.status = 'OPEN' then
    raise exception 'Accounting period % is already open', v_period.name;
  end if;

  update public.accounting_periods
  set status = 'OPEN', closed_at = null, updated_at = now()
  where id = p_period_id;

  update public.financial_years
  set status = 'OPEN', closed_at = null, updated_at = now()
  where id = v_period.financial_year_id;
end;
$$;

-- Validate a DRAFT entry (must be balanced)
create or replace function validate_journal_entry(p_entry_id uuid)
returns boolean language plpgsql as $$
declare
  v_entry journal_entries%rowtype;
begin
  select * into v_entry from public.journal_entries where id = p_entry_id;
  if not found then
    raise exception 'Journal entry % not found', p_entry_id;
  end if;
  if v_entry.status <> 'DRAFT' then
    raise exception 'Only DRAFT entries can be validated, entry is %', v_entry.status;
  end if;
  if v_entry.total_debit is null or v_entry.total_debit <= 0 or v_entry.total_debit <> v_entry.total_credit then
    raise exception 'Journal entry % is not balanced: debit % vs credit %',
      v_entry.journal_number, coalesce(v_entry.total_debit,0), coalesce(v_entry.total_credit,0);
  end if;
  update public.journal_entries set status = 'VALIDATED', updated_at = now() where id = p_entry_id;
  return true;
end;
$$;

-- Post a DRAFT/VALIDATED entry (triggers enforce balance + open period)
create or replace function post_journal_entry(p_entry_id uuid, p_posted_by uuid default null)
returns boolean language plpgsql as $$
declare
  v_entry journal_entries%rowtype;
begin
  select * into v_entry from public.journal_entries where id = p_entry_id;
  if not found then
    raise exception 'Journal entry % not found', p_entry_id;
  end if;
  if v_entry.status not in ('DRAFT','VALIDATED') then
    raise exception 'Journal entry % cannot be posted from status %', v_entry.journal_number, v_entry.status;
  end if;
  update public.journal_entries
  set status = 'POSTED', posted_by = p_posted_by, updated_at = now()
  where id = p_entry_id;
  return true;
end;
$$;

-- Reverse a POSTED entry: creates mirrored entry (debit<->credit swapped), posts it,
-- marks the original REVERSED. Returns the reversal entry id.
create or replace function reverse_journal_entry(
  p_entry_id uuid,
  p_reversal_date date default null,
  p_reason text default null,
  p_reversed_by uuid default null
)
returns uuid language plpgsql as $$
declare
  v_entry journal_entries%rowtype;
  v_reversal_id uuid;
  v_prefix text;
begin
  select * into v_entry from public.journal_entries where id = p_entry_id;
  if not found then
    raise exception 'Journal entry % not found', p_entry_id;
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
$$;

-- Maintain updated_at on every table that has the column
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare
  r record;
begin
  for r in
    select c.relname as table_name
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    join information_schema.columns col
      on col.table_schema = n.nspname and col.table_name = c.relname and col.column_name = 'updated_at'
    where n.nspname = 'public'
      and c.relkind = 'r'
      and not exists (
        select 1 from pg_trigger t
        join pg_proc p on p.oid = t.tgfoid
        where t.tgrelid = c.oid and not t.tgisinternal and p.proname = 'set_updated_at'
      )
  loop
    execute format(
      'create trigger trg_%s_set_updated_at before update on %I for each row execute function public.set_updated_at()',
      r.table_name, r.table_name
    );
  end loop;
end $$;
