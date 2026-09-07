-- Migration: create_financial_years_periods

create table financial_years (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name            text not null,
  start_date      date not null,
  end_date        date not null,
  status          period_status not null default 'OPEN',
  is_current      boolean not null default false,
  closed_at       timestamptz,
  closed_by       uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, name),
  check (end_date > start_date)
);

create table accounting_periods (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references organizations(id) on delete cascade,
  financial_year_id uuid not null references financial_years(id) on delete cascade,
  period_number     smallint not null,
  name              text not null,
  start_date        date not null,
  end_date          date not null,
  status            period_status not null default 'OPEN',
  closed_at         timestamptz,
  closed_by         uuid references auth.users(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (organization_id, financial_year_id, period_number),
  unique (organization_id, start_date),
  check (end_date >= start_date)
);

-- Only one current financial year per organization
create unique index uq_financial_years_current
  on financial_years (organization_id) where is_current;

-- Periods within a financial year must not overlap (same org + FY)
create unique index uq_accounting_periods_dates
  on accounting_periods (organization_id, financial_year_id, end_date);
