-- Migration: create_purchases_expenses

create table purchase_bills (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null references organizations(id) on delete cascade,
  bill_number           text not null,
  supplier_id           uuid references suppliers(id),  -- NULL for cash purchases
  status                bill_status not null default 'DRAFT',
  bill_date             date not null default current_date,
  due_date              date,
  payment_terms_days    smallint not null default 30,
  supplier_invoice_ref  text,
  currency_code         char(3) references currencies(code),
  subtotal              numeric(18,2) not null default 0,
  discount_total        numeric(18,2) not null default 0,
  tax_total             numeric(18,2) not null default 0,
  total                 numeric(18,2) not null default 0,
  amount_paid           numeric(18,2) not null default 0 check (amount_paid >= 0),
  notes                 text,
  journal_entry_id      uuid references journal_entries(id),
  paid_at               timestamptz,
  voided_at             timestamptz,
  created_by            uuid references auth.users(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (organization_id, bill_number),
  check (amount_paid <= total)
);

create table purchase_bill_items (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  bill_id         uuid not null references purchase_bills(id) on delete cascade,
  line_number     smallint not null default 1,
  description     text not null,
  product_id      uuid references products(id),
  expense_account_id uuid references accounts(id),
  project_id      uuid references projects(id),
  fixed_asset_id  uuid,
  quantity        numeric(18,4) not null default 1 check (quantity > 0),
  unit_price      numeric(18,2) not null default 0 check (unit_price >= 0),
  discount_amount numeric(18,2) not null default 0 check (discount_amount >= 0),
  tax_rate_id     uuid references tax_rates(id),
  tax_amount      numeric(18,2) not null default 0,
  line_total      numeric(18,2) not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table purchase_returns (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  return_number   text not null,
  bill_id         uuid references purchase_bills(id),
  supplier_id     uuid references suppliers(id),
  status          bill_status not null default 'DRAFT',
  return_date     date not null default current_date,
  currency_code   char(3) references currencies(code),
  subtotal        numeric(18,2) not null default 0,
  tax_total       numeric(18,2) not null default 0,
  total           numeric(18,2) not null default 0,
  reason          text,
  journal_entry_id uuid references journal_entries(id),
  created_by      uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, return_number)
);

create table purchase_return_items (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  return_id      uuid not null references purchase_returns(id) on delete cascade,
  line_number     smallint not null default 1,
  description     text not null,
  bill_item_id    uuid references purchase_bill_items(id),
  product_id      uuid references products(id),
  quantity        numeric(18,4) not null default 1 check (quantity > 0),
  unit_price      numeric(18,2) not null default 0 check (unit_price >= 0),
  tax_amount      numeric(18,2) not null default 0,
  line_total      numeric(18,2) not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table expense_categories (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null references organizations(id) on delete cascade,
  name                  text not null,
  description           text,
  default_account_id    uuid references accounts(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (organization_id, name)
);

create table expenses (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  expense_number  text not null,
  expense_date    date not null default current_date,
  payee_name      text,
  supplier_id     uuid references suppliers(id),
  category_id     uuid references expense_categories(id),
  description     text,
  currency_code   char(3) references currencies(code),
  subtotal        numeric(18,2) not null default 0,
  tax_total       numeric(18,2) not null default 0,
  total           numeric(18,2) not null default 0,
  payment_mode    payment_method_code,
  status          expense_status not null default 'DRAFT',
  journal_entry_id uuid references journal_entries(id),
  created_by      uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, expense_number)
);

create table expense_items (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  expense_id      uuid not null references expenses(id) on delete cascade,
  line_number     smallint not null default 1,
  description     text not null,
  expense_account_id uuid references accounts(id),
  project_id      uuid references projects(id),
  quantity        numeric(18,4) not null default 1 check (quantity > 0),
  unit_price      numeric(18,2) not null default 0 check (unit_price >= 0),
  tax_rate_id     uuid references tax_rates(id),
  tax_amount      numeric(18,2) not null default 0,
  line_total      numeric(18,2) not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create trigger trg_purchase_bills_number before insert on purchase_bills
  for each row execute function public.trg_document_number_assign('PURCHASE_BILL','bill_prefix','bill_number','BILL');
create trigger trg_purchase_returns_number before insert on purchase_returns
  for each row execute function public.trg_document_number_assign('PURCHASE_RETURN','return_prefix','return_number','RET');
create trigger trg_expenses_number before insert on expenses
  for each row execute function public.trg_document_number_assign('EXPENSE','expense_prefix','expense_number','EXP');
