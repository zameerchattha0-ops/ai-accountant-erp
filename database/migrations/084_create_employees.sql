-- ============================================================================
-- 084 â€” Employees module (replaces the empty Expense Entries module)
-- ============================================================================
-- Quick-entry philosophy: ONLY three fields are mandatory
--   full_name, date_of_joining, basic_salary
-- Everything else is optional detail.  Allowances are a CHILD table â€” the
-- user describes them in natural language, the LLM structures them, and
-- Python validates + executes (set_employee_allowances).
-- employee_code is auto-assigned by the SHARED party-code trigger (EMP-â€¦).
-- ============================================================================

-- ---- org-level prefix (the shared trigger reads it by column name) --------
alter table organization_settings
  add column if not exists employee_prefix text not null default 'EMP';

-- ---- extend the shared party-code trigger with employee_code ---------------
create or replace function public.trg_party_code_assign()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $function$
declare
  v_prefix text;
  v_next text;
  v_doc_type text := tg_argv[0];
  v_prefix_col text := tg_argv[1];
  v_code_col text := tg_argv[2];
  v_default text := tg_argv[3];
begin
  if to_jsonb(new) ->> v_code_col is null or to_jsonb(new) ->> v_code_col = '' then
    execute format('select coalesce(s.%I, %L) from public.organization_settings s where s.organization_id = $1', v_prefix_col, v_default)
      into v_prefix using new.organization_id;
    v_next := public.next_document_number(new.organization_id, v_doc_type, coalesce(v_prefix, v_default));
    case v_code_col
      when 'customer_code' then new.customer_code := v_next;
      when 'supplier_code' then new.supplier_code := v_next;
      when 'employee_code' then new.employee_code := v_next;
      else raise exception 'trg_party_code_assign: unsupported code column %', v_code_col;
    end case;
  end if;
  return new;
end;
$function$;

-- ---- employees --------------------------------------------------------------
create table employees (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null references organizations(id) on delete cascade,
  employee_code         text not null,
  full_name             text not null,
  date_of_joining       date not null,
  basic_salary          numeric(18,2) not null check (basic_salary > 0),
  status                text not null default 'ACTIVE'
                        check (status in ('ACTIVE','PROBATION','ON_LEAVE','RESIGNED','TERMINATED')),
  -- ---- optional detail (fill now or later) ----
  designation           text,
  department            text,
  employment_type       text,          -- FULL_TIME | PART_TIME | CONTRACT | INTERN
  cnic                  text,
  date_of_birth         date,
  gender                text,
  phone                 text,
  email                 text,
  address               text,
  bank_name             text,
  bank_account_number   text,
  tax_number            text,
  pay_day               smallint check (pay_day between 1 and 31),
  probation_end_date    date,
  resignation_date      date,
  notes                 text,
  is_active             boolean not null default true,
  archived_at           timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (organization_id, employee_code)
);

create trigger trg_employees_code_assign
  before insert on employees
  for each row execute function
  public.trg_party_code_assign('EMPLOYEE','employee_prefix','employee_code','EMP');

create trigger trg_employees_updated_at
  before update on employees
  for each row execute function public.set_updated_at();

-- ---- employee_allowances --------------------------------------------------
-- component_kind lets raises / deductions / bonuses reuse this table later
-- without a schema change.  raw_text keeps the user's own sentence (audit);
-- source marks whether the LLM structured it (AI) or a form did (MANUAL).
create table employee_allowances (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references organizations(id) on delete cascade,
  employee_id       uuid not null references employees(id) on delete cascade,
  component_kind    text not null default 'ALLOWANCE'
                    check (component_kind in ('ALLOWANCE','DEDUCTION','BONUS')),
  allowance_type    text,          -- HOUSE_RENT | TRANSPORT | FUEL | MEDICAL | OTHER (free text allowed)
  description       text not null, -- "House rent"
  amount            numeric(18,2) not null check (amount >= 0),
  frequency         text not null default 'MONTHLY'
                    check (frequency in ('MONTHLY','ONE_TIME','ANNUAL')),
  effective_from    date not null default current_date,
  effective_to      date,
  source            text not null default 'MANUAL' check (source in ('MANUAL','AI')),
  raw_text          text,          -- the user's natural-language sentence
  ai_execution_id   uuid,          -- links the row to the agent run that wrote it
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create trigger trg_employee_allowances_updated_at
  before update on employee_allowances
  for each row execute function public.set_updated_at();

-- ---- indexes ----------------------------------------------------------------
create index idx_employees_org_status on employees (organization_id, status);
create index idx_employees_org_name on employees (organization_id, full_name);
create index idx_employee_allowances_employee
  on employee_allowances (employee_id, effective_from);

-- ---- RLS: same org-scoped pattern as migration 019 --------------------------
do $$
declare
  t text;
begin
  foreach t in array array['employees','employee_allowances']
  loop
    execute format(
      'create policy %I on %I for all to authenticated
         using (public.is_org_member(organization_id))
         with check (public.is_org_member(organization_id))',
      t || '_org_access', t
    );
  end loop;
end $$;