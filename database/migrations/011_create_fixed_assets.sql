-- Migration: create_fixed_assets
-- (also adds missing return_prefix to organization_settings)

alter table organization_settings
  add column if not exists return_prefix text not null default 'RET';

create table asset_categories (
  id                          uuid primary key default gen_random_uuid(),
  organization_id             uuid not null references organizations(id) on delete cascade,
  name                        text not null,
  description                 text,
  default_useful_life_years   smallint check (default_useful_life_years is null or default_useful_life_years > 0),
  default_depreciation_method  depreciation_method default 'STRAIGHT_LINE',
  default_asset_account_id          uuid references accounts(id),
  default_depreciation_expense_account_id uuid references accounts(id),
  default_accumulated_depreciation_account_id uuid references accounts(id),
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  unique (organization_id, name)
);

create table fixed_assets (
  id                              uuid primary key default gen_random_uuid(),
  organization_id                 uuid not null references organizations(id) on delete cascade,
  asset_code                      text not null,
  name                            text not null,
  description                     text,
  category_id                     uuid references asset_categories(id),
  supplier_id                     uuid references suppliers(id),
  purchase_date                   date not null default current_date,
  purchase_cost                   numeric(18,2) not null check (purchase_cost >= 0),
  salvage_value                   numeric(18,2) not null default 0 check (salvage_value >= 0),
  useful_life_years               smallint check (useful_life_years is null or useful_life_years > 0),
  depreciation_method             depreciation_method not null default 'STRAIGHT_LINE',
  depreciation_rate_percent       numeric(7,4) check (depreciation_rate_percent is null or depreciation_rate_percent >= 0),
  accumulated_depreciation         numeric(18,2) not null default 0 check (accumulated_depreciation >= 0),
  book_value                      numeric(18,2) generated always as (purchase_cost - accumulated_depreciation) stored,
  status                          asset_status not null default 'ACTIVE',
  gl_asset_account_id             uuid references accounts(id),
  gl_depreciation_expense_account_id uuid references accounts(id),
  gl_accumulated_depreciation_account_id uuid references accounts(id),
  purchase_bill_id                uuid references purchase_bills(id),
  purchase_journal_entry_id       uuid references journal_entries(id),
  disposal_date                   date,
  disposal_amount                 numeric(18,2) check (disposal_amount is null or disposal_amount >= 0),
  disposal_journal_entry_id       uuid references journal_entries(id),
  created_by                      uuid references auth.users(id),
  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now(),
  unique (organization_id, asset_code),
  check (salvage_value <= purchase_cost)
);

-- Backfill FK for purchase_bill_items.fixed_asset_id (defined as plain uuid earlier)
do $$
begin
  if exists (
    select 1 from information_schema.table_constraints
    where constraint_name = 'purchase_bill_items_fixed_asset_id_fkey'
  ) then
    alter table purchase_bill_items drop constraint purchase_bill_items_fixed_asset_id_fkey;
  end if;
end $$;

alter table purchase_bill_items
  add constraint purchase_bill_items_fixed_asset_id_fkey
  foreign key (fixed_asset_id) references fixed_assets(id) on delete set null;

create table asset_depreciation_schedules (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null references organizations(id) on delete cascade,
  asset_id              uuid not null references fixed_assets(id) on delete cascade,
  accounting_period_id  uuid references accounting_periods(id),
  depreciation_date     date not null,
  opening_book_value    numeric(18,2) not null default 0,
  depreciation_amount   numeric(18,2) not null default 0 check (depreciation_amount >= 0),
  closing_book_value    numeric(18,2) not null default 0,
  is_posted            boolean not null default false,
  journal_entry_id     uuid references journal_entries(id),
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (asset_id, depreciation_date)
);

create table asset_transactions (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references organizations(id) on delete cascade,
  asset_id          uuid not null references fixed_assets(id) on delete cascade,
  transaction_type  text not null check (transaction_type in ('PURCHASE','DEPRECIATION','REVALUATION','DISPOSAL','WRITE_OFF')),
  transaction_date  date not null default current_date,
  amount            numeric(18,2) not null default 0,
  journal_entry_id  uuid references journal_entries(id),
  details           jsonb not null default '{}',
  created_at        timestamptz not null default now()
);

create trigger trg_fixed_assets_number before insert on fixed_assets
  for each row execute function public.trg_document_number_assign('FIXED_ASSET','asset_prefix','asset_code','AST');
