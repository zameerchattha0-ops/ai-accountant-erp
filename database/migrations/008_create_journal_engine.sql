-- Migration: create_journal_engine
-- Sequences, entries, lines, integrity enforcement

-- ---- Safe concurrent document numbering (never MAX(id)+1) ----
create table document_sequences (
  organization_id uuid not null references organizations(id) on delete cascade,
  doc_type        text not null,
  prefix          text not null default '',
  next_value      bigint not null default 1,
  primary key (organization_id, doc_type)
);

create or replace function public.next_document_number(
  p_org uuid,
  p_doc_type text,
  p_prefix text default null
)
returns text
language plpgsql
as $$
declare
  v_next bigint;
  v_prefix text;
begin
  select coalesce(s.prefix, '') into v_prefix
  from public.document_sequences s
  where s.organization_id = p_org and s.doc_type = p_doc_type;

  if p_prefix is not null then
    v_prefix := p_prefix;
  end if;

  insert into public.document_sequences (organization_id, doc_type, prefix, next_value)
  values (p_org, p_doc_type, v_prefix, 2)
  on conflict (organization_id, doc_type)
  do update set next_value = public.document_sequences.next_value + 1
  returning next_value - 1 into v_next;

  return coalesce(v_prefix, '') || '-' || lpad(v_next::text, 6, '0');
end;
$$;

-- ---- Journal entries ----
create table journal_entries (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null references organizations(id) on delete cascade,
  journal_number        text not null,
  transaction_date      date not null,
  accounting_period_id  uuid references accounting_periods(id),
  description           text,
  reference             text,
  status                journal_status not null default 'DRAFT',
  source_type           text,
  source_id             uuid,
  currency_code         char(3) references currencies(code),
  total_debit           numeric(18,2) not null default 0,
  total_credit          numeric(18,2) not null default 0,
  posted_at             timestamptz,
  posted_by             uuid references auth.users(id),
  reversal_of_entry_id  uuid references journal_entries(id),
  reversed_by_entry_id  uuid references journal_entries(id),
  created_by            uuid references auth.users(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (organization_id, journal_number)
);

create table journal_lines (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  entry_id        uuid not null references journal_entries(id) on delete cascade,
  line_number     smallint not null default 1,
  account_id      uuid not null references accounts(id),
  description     text,
  debit           numeric(18,2) not null default 0,
  credit          numeric(18,2) not null default 0,
  customer_id     uuid references customers(id),
  supplier_id     uuid references suppliers(id),
  project_id      uuid references projects(id),
  tax_rate_id     uuid references tax_rates(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check (debit >= 0 and credit >= 0),
  check (not (debit > 0 and credit > 0)),
  check (debit + credit > 0)
);

create index idx_journal_lines_entry on journal_lines (entry_id);

-- ---- Guard: posted/reversed/voided entries are immutable ----
create or replace function public.trg_journal_lines_guard()
returns trigger language plpgsql as $$
declare
  v_entry_id uuid;
  v_status journal_status;
begin
  v_entry_id := coalesce(new.entry_id, old.entry_id);
  select status into v_status from public.journal_entries where id = v_entry_id;
  if v_status in ('POSTED','REVERSED','VOIDED') then
    raise exception 'Journal lines of entry % are in status % and cannot be modified. Use a reversal instead.', v_entry_id, v_status;
  end if;
  return coalesce(new, old);
end;
$$;

create trigger trg_journal_lines_guard
  before insert or update or delete on journal_lines
  for each row execute function public.trg_journal_lines_guard();

-- ---- Recompute entry totals whenever lines change ----
create or replace function public.trg_journal_lines_totals()
returns trigger language plpgsql as $$
declare
  v_entry_id uuid;
begin
  v_entry_id := coalesce(new.entry_id, old.entry_id);
  update public.journal_entries e
  set total_debit = (select coalesce(sum(l.debit),0) from public.journal_lines l where l.entry_id = v_entry_id),
      total_credit = (select coalesce(sum(l.credit),0) from public.journal_lines l where l.entry_id = v_entry_id),
      updated_at = now()
  where e.id = v_entry_id;
  return null;
end;
$$;

create trigger trg_journal_lines_totals
  after insert or update or delete on journal_lines
  for each row execute function public.trg_journal_lines_totals();

-- ---- Posting rules: balanced entry, open period, posted-entry immutability ----
create or replace function public.get_period_for_date(
  p_org uuid,
  p_date date
)
returns uuid
language sql stable
as $$
  select p.id
  from public.accounting_periods p
  where p.organization_id = p_org
    and p_date between p.start_date and p.end_date
  limit 1;
$$;

create or replace function public.trg_journal_entries_status()
returns trigger language plpgsql as $$
declare
  v_status period_status;
begin
  -- Posted entries: only allow transition to REVERSED/VOIDED; core fields frozen
  if old.status = 'POSTED' and new.status = old.status then
    if new.transaction_date is distinct from old.transaction_date
       or new.organization_id is distinct from old.organization_id
       or new.journal_number is distinct from old.journal_number then
      raise exception 'Posted journal entry % cannot be edited. Use a reversal.', old.journal_number;
    end if;
  end if;

  if old.status in ('REVERSED','VOIDED') then
    raise exception 'Journal entry % is % and cannot be modified.', old.journal_number, old.status;
  end if;

  -- VALIDATED -> require balance
  if new.status = 'VALIDATED' and old.status = 'DRAFT' then
    if new.total_debit is null or new.total_debit <= 0 or new.total_debit <> new.total_credit then
      raise exception 'Journal entry % is not balanced: total debit % <> total credit %',
        new.journal_number, coalesce(new.total_debit,0), coalesce(new.total_credit,0);
    end if;
  end if;

  -- POSTING: enforce balance + open accounting period
  if new.status = 'POSTED' and old.status in ('DRAFT','VALIDATED') then
    if new.total_debit is null or new.total_debit <= 0 or new.total_debit <> new.total_credit then
      raise exception 'Cannot post unbalanced journal entry %: total debit % <> total credit %',
        new.journal_number, coalesce(new.total_debit,0), coalesce(new.total_credit,0);
    end if;

    if new.accounting_period_id is null then
      new.accounting_period_id := public.get_period_for_date(new.organization_id, new.transaction_date);
    end if;

    if new.accounting_period_id is null then
      raise exception 'No accounting period exists for transaction date % in this organization', new.transaction_date;
    end if;

    select p.status into v_status
    from public.accounting_periods p
    where p.id = new.accounting_period_id and p.organization_id = new.organization_id;

    if v_status is null then
      raise exception 'Invalid accounting period for journal entry %', new.journal_number;
    end if;
    if v_status <> 'OPEN' then
      raise exception 'Accounting period is % - posting is not allowed', v_status;
    end if;

    new.posted_at := now();
  end if;

  return new;
end;
$$;

create trigger trg_journal_entries_status
  before update of status, transaction_date, organization_id, journal_number, accounting_period_id
  on journal_entries
  for each row execute function public.trg_journal_entries_status();

-- ---- Auto-assign journal number on insert ----
create or replace function public.trg_journal_entries_number()
returns trigger language plpgsql as $$
declare
  v_prefix text;
begin
  if new.journal_number is null or new.journal_number = '' then
    select coalesce(s.journal_prefix, 'JE') into v_prefix
    from public.organization_settings s
    where s.organization_id = new.organization_id;
    new.journal_number := public.next_document_number(new.organization_id, 'JOURNAL', coalesce(v_prefix, 'JE'));
  end if;
  return new;
end;
$$;

create trigger trg_journal_entries_number
  before insert on journal_entries
  for each row execute function public.trg_journal_entries_number();
