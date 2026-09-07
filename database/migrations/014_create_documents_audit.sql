-- Migration: create_documents_audit

create table tax_transactions (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  tax_rate_id     uuid not null references tax_rates(id),
  direction       tax_direction_code not null,
  transaction_date date not null default current_date,
  source_type     text not null check (source_type in ('INVOICE','CREDIT_NOTE','PURCHASE_BILL','PURCHASE_RETURN','EXPENSE','MANUAL')),
  source_id       uuid,
  base_amount     numeric(18,2) not null default 0,
  tax_amount      numeric(18,2) not null default 0,
  journal_entry_id uuid references journal_entries(id),
  created_at      timestamptz not null default now()
);

create table documents (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  doc_type        text not null check (doc_type in ('RECEIPT','INVOICE','PURCHASE_BILL','CONTRACT','BANK_STATEMENT','SCREENSHOT','PDF','OTHER')),
  title           text not null,
  file_name       text not null,
  mime_type       text,
  size_bytes      bigint check (size_bytes is null or size_bytes >= 0),
  storage_bucket  text not null default 'erp-documents',
  storage_path    text not null,
  content_hash    text,
  uploaded_by     uuid references auth.users(id),
  archived_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table document_links (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  document_id     uuid not null references documents(id) on delete cascade,
  entity_type     text not null check (entity_type in ('CUSTOMER','SUPPLIER','INVOICE','CREDIT_NOTE','PURCHASE_BILL','PURCHASE_RETURN','EXPENSE','PAYMENT','RECEIPT','PROJECT','FIXED_ASSET','JOURNAL_ENTRY','ORGANIZATION')),
  entity_id       uuid not null,
  created_at      timestamptz not null default now(),
  unique (document_id, entity_type, entity_id)
);

create table audit_logs (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id         uuid references auth.users(id),
  actor_type      actor_type_code not null default 'USER',
  action          audit_action_code not null,
  entity_type     text not null,
  entity_id       uuid,
  entity_code     text,
  old_values      jsonb,
  new_values      jsonb,
  description     text,
  ai_request_id   uuid,
  created_at      timestamptz not null default now()
);

create index idx_audit_logs_entity on audit_logs (organization_id, entity_type, entity_id);
create index idx_audit_logs_created on audit_logs (organization_id, created_at desc);
