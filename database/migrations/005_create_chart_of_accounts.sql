-- Migration: create_chart_of_accounts
-- Chart of accounts, account types/categories, business templates

create table account_types (
  id            uuid primary key default gen_random_uuid(),
  code          account_type_code not null unique,
  name          text not null,
  normal_balance normal_balance_code not null,
  sort_order    smallint not null default 0,
  description   text
);

create table account_categories (
  id              uuid primary key default gen_random_uuid(),
  account_type_id uuid not null references account_types(id),
  code            text not null,
  name            text not null,
  description     text,
  unique (account_type_id, code),
  unique (code)
);

create table chart_of_accounts (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name            text not null default 'Standard',
  is_default      boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, name)
);

create table accounts (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null references organizations(id) on delete cascade,
  chart_of_accounts_id  uuid references chart_of_accounts(id) on delete set null,
  code                  text not null,
  name                  text not null,
  account_type          account_type_code not null,
  account_category_id   uuid references account_categories(id),
  parent_account_id     uuid references accounts(id) on delete set null,
  normal_balance        normal_balance_code not null,
  is_system             boolean not null default false,
  is_control_account    boolean not null default false,
  is_active             boolean not null default true,
  description           text,
  archived_at           timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (organization_id, code),
  check (
    (account_type in ('ASSET','EXPENSE') and normal_balance = 'DEBIT')
    or (account_type in ('LIABILITY','EQUITY','REVENUE') and normal_balance = 'CREDIT')
  )
);

-- Business-aware account templates (global reference data)
create table account_templates (
  id            uuid primary key default gen_random_uuid(),
  code          text not null unique,
  name          text not null,
  business_type business_type_code not null,
  description   text,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now()
);

create table account_template_items (
  id                    uuid primary key default gen_random_uuid(),
  template_id           uuid not null references account_templates(id) on delete cascade,
  code                  text not null,
  name                  text not null,
  account_type          account_type_code not null,
  account_category_id   uuid references account_categories(id),
  suggested_parent_code text,
  sort_order            smallint not null default 0,
  unique (template_id, code)
);

create table business_account_recommendations (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  onboarding_id   uuid references organization_onboarding(id) on delete set null,
  template_id     uuid references account_templates(id),
  account_name    text not null,
  account_type    account_type_code not null,
  rationale       text,
  is_accepted     boolean,
  created_at      timestamptz not null default now()
);

-- ---- Prevent circular account hierarchy ----
create or replace function public.prevent_account_cycle()
returns trigger language plpgsql as $$
declare
  v_parent uuid;
  v_depth int := 0;
begin
  if new.parent_account_id is null then
    return new;
  end if;
  if new.parent_account_id = new.id then
    raise exception 'Account % cannot be its own parent', new.code;
  end if;
  if new.parent_account_id is distinct from old.parent_account_id or old.id is null then
    v_parent := new.parent_account_id;
    while v_parent is not null and v_depth < 100 loop
      if v_parent = new.id then
        raise exception 'Circular account hierarchy detected for account %', new.code;
      end if;
      select a.parent_account_id into v_parent
      from public.accounts a where a.id = v_parent;
      v_depth := v_depth + 1;
    end loop;
    if v_depth >= 100 then
      raise exception 'Account hierarchy too deep or circular for account %', new.code;
    end if;
  end if;
  return new;
end;
$$;

create trigger trg_accounts_prevent_cycle
  before insert or update of parent_account_id on accounts
  for each row execute function public.prevent_account_cycle();
