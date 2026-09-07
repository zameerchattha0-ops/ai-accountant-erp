-- Migration: create_banking

create table bank_accounts (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  account_name        text not null,
  bank_name           text not null,
  account_number_masked text,
  iban                text,
  branch_code         text,
  currency_code       char(3) references currencies(code),
  gl_account_id       uuid not null references accounts(id),
  current_balance     numeric(18,2) not null default 0,
  last_reconciled_at  timestamptz,
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, account_name)
);

create table cash_accounts (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name            text not null,
  gl_account_id   uuid not null references accounts(id),
  currency_code   char(3) references currencies(code),
  current_balance numeric(18,2) not null default 0,
  custodian       text,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, name)
);

create table bank_transactions (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  bank_account_id     uuid not null references bank_accounts(id) on delete cascade,
  transaction_date    date not null,
  value_date          date,
  direction           payment_direction not null,
  amount              numeric(18,2) not null check (amount > 0),
  description         text,
  reference           text,
  counterparty        text,
  status              bank_txn_status not null default 'UNRECONCILED',
  journal_entry_id    uuid references journal_entries(id),
  reconciliation_id   uuid,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table bank_statement_imports (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references organizations(id) on delete cascade,
  bank_account_id   uuid not null references bank_accounts(id) on delete cascade,
  file_name         text not null,
  import_date       timestamptz not null default now(),
  statement_start   date,
  statement_end     date,
  total_lines       smallint not null default 0,
  imported_lines    smallint not null default 0,
  status            text not null default 'COMPLETED',
  imported_by        uuid references auth.users(id),
  created_at        timestamptz not null default now()
);

create table bank_statement_lines (
  id                      uuid primary key default gen_random_uuid(),
  organization_id         uuid not null references organizations(id) on delete cascade,
  import_id               uuid not null references bank_statement_imports(id) on delete cascade,
  line_number             smallint not null,
  transaction_date        date not null,
  description             text,
  reference               text,
  direction               payment_direction not null,
  amount                  numeric(18,2) not null check (amount > 0),
  balance_after           numeric(18,2),
  matched_transaction_id  uuid references bank_transactions(id) on delete set null,
  is_matched              boolean not null default false,
  created_at              timestamptz not null default now()
);

create table bank_reconciliations (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  bank_account_id     uuid not null references bank_accounts(id) on delete cascade,
  reconciliation_date date not null,
  statement_balance   numeric(18,2) not null default 0,
  system_balance      numeric(18,2) not null default 0,
  difference          numeric(18,2) generated always as (statement_balance - system_balance) stored,
  status              reconciliation_status not null default 'IN_PROGRESS',
  journal_entry_id    uuid references journal_entries(id),
  completed_at        timestamptz,
  completed_by        uuid references auth.users(id),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

alter table bank_transactions
  add constraint bank_transactions_reconciliation_fkey
  foreign key (reconciliation_id) references bank_reconciliations(id) on delete set null;

create table bank_reconciliation_items (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  reconciliation_id   uuid not null references bank_reconciliations(id) on delete cascade,
  bank_transaction_id uuid references bank_transactions(id) on delete cascade,
  statement_line_id   uuid references bank_statement_lines(id) on delete cascade,
  is_cleared          boolean not null default false,
  created_at          timestamptz not null default now()
);
