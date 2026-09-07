-- Migration: create_projects_products_services

create table projects (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  project_code        text not null,
  name                text not null,
  description         text,
  customer_id         uuid references customers(id),
  status              project_status not null default 'PLANNING',
  billing_type        billing_type_code,
  start_date          date,
  end_date            date,
  budget              numeric(18,2) check (budget is null or budget >= 0),
  currency_code       char(3) references currencies(code),
  revenue_account_id  uuid references accounts(id),
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, project_code),
  check (end_date is null or start_date is null or end_date >= start_date)
);

create table project_members (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references organizations(id) on delete cascade,
  project_id        uuid not null references projects(id) on delete cascade,
  user_id           uuid not null references auth.users(id) on delete cascade,
  role_in_project   text,
  allocated_hours   numeric(18,2) check (allocated_hours is null or allocated_hours >= 0),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (project_id, user_id)
);

create table project_milestones (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  project_id      uuid not null references projects(id) on delete cascade,
  name            text not null,
  description     text,
  due_date        date,
  completed_at    timestamptz,
  amount          numeric(18,2) check (amount is null or amount >= 0),
  status          text not null default 'PENDING',
  sort_order      smallint not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table project_settings (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  project_id      uuid not null unique references projects(id) on delete cascade,
  settings        jsonb not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table product_categories (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name            text not null,
  parent_id       uuid references product_categories(id) on delete set null,
  description     text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, name)
);

create table products (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  product_code        text not null,
  name                text not null,
  description         text,
  category_id         uuid references product_categories(id) on delete set null,
  unit                text default 'PCS',
  is_stock_tracked    boolean not null default false,
  unit_price          numeric(18,2) not null default 0 check (unit_price >= 0),
  cost_price          numeric(18,2) check (cost_price is null or cost_price >= 0),
  revenue_account_id  uuid references accounts(id),
  tax_rate_id         uuid references tax_rates(id),
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, product_code)
);

create table service_categories (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name            text not null,
  parent_id       uuid references service_categories(id) on delete set null,
  description     text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, name)
);

create table services (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  service_code        text not null,
  name                text not null,
  description         text,
  category_id         uuid references service_categories(id) on delete set null,
  billing_unit        service_unit_code not null default 'HOUR',
  standard_rate       numeric(18,2) not null default 0 check (standard_rate >= 0),
  cost_rate           numeric(18,2) check (cost_rate is null or cost_rate >= 0),
  revenue_account_id  uuid references accounts(id),
  tax_rate_id         uuid references tax_rates(id),
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, service_code)
);
