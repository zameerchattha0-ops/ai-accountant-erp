-- Migration: create_payments_receipts

create table payments (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  payment_number  text not null,
  payment_date    date not null default current_date,
  direction       payment_direction not null default 'OUTFLOW',
  payment_method  payment_method_code not null default 'BANK_TRANSFER',
  bank_account_id uuid references bank_accounts(id),
  cash_account_id uuid references cash_accounts(id),
  supplier_id     uuid references suppliers(id),
  expense_id     uuid references expenses(id),
  amount          numeric(18,2) not null check (amount > 0),
  currency_code   char(3) references currencies(code),
  reference       text,
  notes           text,
  status          payment_status not null default 'COMPLETED',
  journal_entry_id uuid references journal_entries(id),
  created_by      uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, payment_number)
);

create table payment_allocations (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  payment_id      uuid not null references payments(id) on delete cascade,
  bill_id         uuid references purchase_bills(id),
  expense_id      uuid references expenses(id),
  amount_allocated numeric(18,2) not null check (amount_allocated > 0),
  created_at      timestamptz not null default now()
);

create table receipts (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  receipt_number  text not null,
  receipt_date    date not null default current_date,
  payment_method  payment_method_code not null default 'BANK_TRANSFER',
  bank_account_id uuid references bank_accounts(id),
  cash_account_id uuid references cash_accounts(id),
  customer_id     uuid references customers(id),
  amount          numeric(18,2) not null check (amount > 0),
  currency_code   char(3) references currencies(code),
  reference       text,
  notes           text,
  status          payment_status not null default 'COMPLETED',
  journal_entry_id uuid references journal_entries(id),
  created_by      uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, receipt_number)
);

create table receipt_allocations (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  receipt_id      uuid not null references receipts(id) on delete cascade,
  invoice_id      uuid references invoices(id),
  credit_note_id  uuid references credit_notes(id),
  amount_allocated numeric(18,2) not null check (amount_allocated > 0),
  created_at      timestamptz not null default now()
);

create trigger trg_payments_number before insert on payments
  for each row execute function public.trg_document_number_assign('PAYMENT','payment_prefix','payment_number','PAY');
create trigger trg_receipts_number before insert on receipts
  for each row execute function public.trg_document_number_assign('RECEIPT','receipt_prefix','receipt_number','RCP');
