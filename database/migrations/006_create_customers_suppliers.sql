-- Migration: create_customers_suppliers

create table customers (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null references organizations(id) on delete cascade,
  customer_code         text not null,
  name                  text not null,
  legal_name            text,
  tax_number            text,
  email                 text,
  phone                 text,
  website               text,
  credit_limit          numeric(18,2) not null default 0 check (credit_limit >= 0),
  payment_terms_days    smallint not null default 30 check (payment_terms_days >= 0),
  currency_code         char(3) references currencies(code),
  receivable_account_id uuid references accounts(id),
  is_active             boolean not null default true,
  archived_at           timestamptz,
  notes                 text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (organization_id, customer_code)
);

create table customer_contacts (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  customer_id     uuid not null references customers(id) on delete cascade,
  contact_type    contact_type_code not null default 'PRIMARY',
  name            text not null,
  designation     text,
  email           text,
  phone           text,
  is_primary      boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table customer_addresses (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  customer_id     uuid not null references customers(id) on delete cascade,
  address_type    address_type_code not null default 'BILLING',
  line1           text not null,
  line2           text,
  city            text,
  state           text,
  postal_code     text,
  country_code    char(2),
  is_default      boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table suppliers (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  supplier_code       text not null,
  name                text not null,
  legal_name          text,
  tax_number          text,
  email               text,
  phone               text,
  website             text,
  credit_limit        numeric(18,2) not null default 0 check (credit_limit >= 0),
  payment_terms_days  smallint not null default 30 check (payment_terms_days >= 0),
  currency_code       char(3) references currencies(code),
  payable_account_id  uuid references accounts(id),
  is_active           boolean not null default true,
  archived_at         timestamptz,
  notes               text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, supplier_code)
);

create table supplier_contacts (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  supplier_id     uuid not null references suppliers(id) on delete cascade,
  contact_type    contact_type_code not null default 'PRIMARY',
  name            text not null,
  designation     text,
  email           text,
  phone           text,
  is_primary      boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table supplier_addresses (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  supplier_id     uuid not null references suppliers(id) on delete cascade,
  address_type    address_type_code not null default 'BILLING',
  line1           text not null,
  line2           text,
  city            text,
  state           text,
  postal_code     text,
  country_code    char(2),
  is_default      boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- One default contact/address per customer/supplier per type
create unique index uq_customer_contacts_primary
  on customer_contacts (customer_id) where is_primary;
create unique index uq_customer_addresses_default
  on customer_addresses (customer_id, address_type) where is_default;
create unique index uq_supplier_contacts_primary
  on supplier_contacts (supplier_id) where is_primary;
create unique index uq_supplier_addresses_default
  on supplier_addresses (supplier_id, address_type) where is_default;
