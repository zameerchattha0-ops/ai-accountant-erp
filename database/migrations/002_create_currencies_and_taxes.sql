-- Migration: create_currencies_and_taxes
-- Global reference data - currencies, exchange rates, taxes

create table currencies (
  code            char(3) primary key,
  name            text not null,
  symbol          text,
  decimal_places  smallint not null default 2 check (decimal_places between 0 and 6),
  is_active       boolean not null default true
);

create table exchange_rates (
  id              uuid primary key default gen_random_uuid(),
  base_currency   char(3) not null references currencies(code),
  quote_currency  char(3) not null references currencies(code),
  rate            numeric(18,8) not null check (rate > 0),
  effective_date  date not null,
  source          text,
  created_at      timestamptz not null default now(),
  unique (base_currency, quote_currency, effective_date),
  check (base_currency <> quote_currency)
);

create table tax_categories (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique,
  name        text not null,
  description text
);

create table taxes (
  id              uuid primary key default gen_random_uuid(),
  tax_category_id uuid not null references tax_categories(id),
  name            text not null,
  description     text,
  is_active       boolean not null default true
);

create table tax_rates (
  id              uuid primary key default gen_random_uuid(),
  tax_id          uuid not null references taxes(id),
  name            text not null,
  rate_percent    numeric(7,4) not null check (rate_percent >= 0),
  effective_from  date not null,
  effective_to    date,
  is_default      boolean not null default false,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  check (effective_to is null or effective_to >= effective_from)
);
