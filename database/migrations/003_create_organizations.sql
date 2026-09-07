-- Migration: create_organizations
-- Multi-tenancy core - organizations, roles, members, settings, onboarding

create table organizations (
  id                  uuid primary key default gen_random_uuid(),
  name                text not null,
  slug                text not null unique,
  legal_name          text,
  business_type       business_type_code not null default 'OTHER',
  tax_number          text,
  registration_number text,
  base_currency_code  char(3) not null default 'PKR' references currencies(code),
  country_code        char(2),
  timezone            text not null default 'Asia/Karachi',
  fiscal_year_end_month smallint not null default 6 check (fiscal_year_end_month between 1 and 12),
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table organization_roles (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique,
  name        text not null,
  description text,
  rank        smallint not null,  -- lower rank = higher privileges
  permissions jsonb not null default '[]'
);

create table organization_members (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id         uuid not null references auth.users(id) on delete cascade,
  role_id         uuid not null references organization_roles(id),
  status          member_status not null default 'INVITED',
  invited_by      uuid references auth.users(id),
  joined_at       timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, user_id)
);

create table organization_settings (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null unique references organizations(id) on delete cascade,
  invoice_prefix      text not null default 'INV',
  quotation_prefix    text not null default 'QT',
  bill_prefix         text not null default 'BILL',
  credit_note_prefix  text not null default 'CN',
  journal_prefix      text not null default 'JE',
  payment_prefix      text not null default 'PAY',
  receipt_prefix      text not null default 'RCP',
  customer_prefix     text not null default 'CUST',
  supplier_prefix     text not null default 'SUP',
  project_prefix      text not null default 'PROJ',
  expense_prefix      text not null default 'EXP',
  asset_prefix        text not null default 'AST',
  default_payment_terms_days smallint not null default 30,
  settings            jsonb not null default '{}',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table organization_onboarding (
  id                              uuid primary key default gen_random_uuid(),
  organization_id                 uuid not null unique references organizations(id) on delete cascade,
  business_type                   business_type_code not null default 'OTHER',
  core_services                   jsonb not null default '[]',
  industry_details                text,
  responses                       jsonb not null default '{}',
  recommended_accounts_generated  boolean not null default false,
  onboarding_completed_at         timestamptz,
  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now()
);

-- ---- RLS membership helper (security definer to avoid recursion) ----
create or replace function public.is_org_member(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_members m
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'ACTIVE'
  );
$$;

create or replace function public.has_org_role(target_org uuid, min_rank smallint)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_members m
    join public.organization_roles r on r.id = m.role_id
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'ACTIVE'
      and r.rank <= min_rank
  );
$$;
