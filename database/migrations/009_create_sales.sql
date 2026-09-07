-- Migration: create_sales

create table quotations (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  quotation_number text not null,
  revision        smallint not null default 1,
  customer_id     uuid not null references customers(id),
  project_id      uuid references projects(id),
  status          quotation_status not null default 'DRAFT',
  quotation_date  date not null default current_date,
  valid_until     date,
  currency_code   char(3) references currencies(code),
  subtotal        numeric(18,2) not null default 0,
  discount_total  numeric(18,2) not null default 0,
  tax_total       numeric(18,2) not null default 0,
  total           numeric(18,2) not null default 0,
  notes           text,
  terms           text,
  sent_at         timestamptz,
  accepted_at     timestamptz,
  created_by      uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, quotation_number, revision)
);

create table quotation_items (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  quotation_id    uuid not null references quotations(id) on delete cascade,
  line_number     smallint not null default 1,
  description     text not null,
  product_id      uuid references products(id),
  service_id      uuid references services(id),
  project_id      uuid references projects(id),
  quantity        numeric(18,4) not null default 1 check (quantity > 0),
  unit_price      numeric(18,2) not null default 0 check (unit_price >= 0),
  discount_amount numeric(18,2) not null default 0 check (discount_amount >= 0),
  tax_rate_id     uuid references tax_rates(id),
  tax_amount      numeric(18,2) not null default 0,
  line_total      numeric(18,2) not null default 0,
  notes           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table invoices (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  invoice_number      text not null,
  customer_id         uuid not null references customers(id),
  project_id          uuid references projects(id),
  quotation_id        uuid references quotations(id),
  status              invoice_status not null default 'DRAFT',
  invoice_date        date not null default current_date,
  due_date            date,
  payment_terms_days  smallint not null default 30,
  currency_code       char(3) references currencies(code),
  subtotal            numeric(18,2) not null default 0,
  discount_total      numeric(18,2) not null default 0,
  tax_total           numeric(18,2) not null default 0,
  total               numeric(18,2) not null default 0,
  amount_paid         numeric(18,2) not null default 0 check (amount_paid >= 0),
  notes               text,
  terms               text,
  journal_entry_id    uuid references journal_entries(id),
  sent_at             timestamptz,
  paid_at             timestamptz,
  voided_at           timestamptz,
  created_by          uuid references auth.users(id),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, invoice_number),
  check (amount_paid <= total)
);

create table invoice_items (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  invoice_id      uuid not null references invoices(id) on delete cascade,
  line_number     smallint not null default 1,
  description     text not null,
  product_id      uuid references products(id),
  service_id      uuid references services(id),
  project_id      uuid references projects(id),
  quantity        numeric(18,4) not null default 1 check (quantity > 0),
  unit_price      numeric(18,2) not null default 0 check (unit_price >= 0),
  discount_amount numeric(18,2) not null default 0 check (discount_amount >= 0),
  tax_rate_id     uuid references tax_rates(id),
  tax_amount      numeric(18,2) not null default 0,
  line_total      numeric(18,2) not null default 0,
  revenue_account_id uuid references accounts(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table credit_notes (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references organizations(id) on delete cascade,
  credit_note_number  text not null,
  customer_id         uuid not null references customers(id),
  invoice_id          uuid references invoices(id),
  status              invoice_status not null default 'DRAFT',
  credit_note_date    date not null default current_date,
  currency_code       char(3) references currencies(code),
  subtotal            numeric(18,2) not null default 0,
  discount_total      numeric(18,2) not null default 0,
  tax_total           numeric(18,2) not null default 0,
  total               numeric(18,2) not null default 0,
  reason              text,
  journal_entry_id    uuid references journal_entries(id),
  created_by          uuid references auth.users(id),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, credit_note_number)
);

create table credit_note_items (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  credit_note_id  uuid not null references credit_notes(id) on delete cascade,
  line_number     smallint not null default 1,
  description     text not null,
  invoice_item_id uuid references invoice_items(id),
  product_id      uuid references products(id),
  service_id      uuid references services(id),
  quantity        numeric(18,4) not null default 1 check (quantity > 0),
  unit_price      numeric(18,2) not null default 0 check (unit_price >= 0),
  discount_amount numeric(18,2) not null default 0 check (discount_amount >= 0),
  tax_rate_id     uuid references tax_rates(id),
  tax_amount      numeric(18,2) not null default 0,
  line_total      numeric(18,2) not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Auto numbering for sales documents
create or replace function public.trg_document_number_assign()
returns trigger language plpgsql as $$
declare
  v_prefix text;
  v_doc_type text := tg_argv[0];
  v_prefix_col text := tg_argv[1];
  v_number_col text := tg_argv[2];
begin
  if to_jsonb(new) ->> v_number_col is null or to_jsonb(new) ->> v_number_col = '' then
    execute format('select coalesce(s.%I, %L) from public.organization_settings s where s.organization_id = $1', v_prefix_col, tg_argv[3])
      into v_prefix using new.organization_id;
    execute format('new.%I := public.next_document_number($1, $2, $3)', v_number_col)
      using new.organization_id, v_doc_type, coalesce(v_prefix, tg_argv[3]);
  end if;
  return new;
end;
$$;

create trigger trg_quotations_number before insert on quotations
  for each row execute function public.trg_document_number_assign('QUOTATION','quotation_prefix','quotation_number','QT');
create trigger trg_invoices_number before insert on invoices
  for each row execute function public.trg_document_number_assign('INVOICE','invoice_prefix','invoice_number','INV');
create trigger trg_credit_notes_number before insert on credit_notes
  for each row execute function public.trg_document_number_assign('CREDIT_NOTE','credit_note_prefix','credit_note_number','CN');
