-- Migration: create_ai_execution_reporting

create table ai_requests (
  id                   uuid primary key default gen_random_uuid(),
  organization_id      uuid not null references organizations(id) on delete cascade,
  user_id              uuid not null,
  request_text         text not null,
  intent               text,
  model                text,
  model_version        text,
  agent_version        text,
  constitution_version text,
  status               ai_request_status not null default 'RECEIVED',
  error_message        text,
  started_at           timestamptz not null default now(),
  completed_at         timestamptz,
  created_at           timestamptz not null default now()
);

create table ai_execution_plans (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  ai_request_id   uuid not null references ai_requests(id) on delete cascade,
  summary         text,
  plan            jsonb not null default '[]',
  status          ai_request_status not null default 'PLANNING',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table ai_tool_calls (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  ai_request_id   uuid not null references ai_requests(id) on delete cascade,
  plan_id         uuid references ai_execution_plans(id) on delete set null,
  tool_name       text not null,
  tool_args       jsonb not null default '{}',
  result          jsonb,
  status          text not null default 'PENDING'
                  check (status in ('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED')),
  error_message   text,
  started_at      timestamptz,
  completed_at    timestamptz,
  created_at      timestamptz not null default now()
);

create table ai_execution_actions (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  ai_request_id   uuid not null references ai_requests(id) on delete cascade,
  tool_call_id    uuid references ai_tool_calls(id) on delete set null,
  action_type     text not null,
  entity_type     text,
  entity_id       uuid,
  entity_code     text,
  payload         jsonb not null default '{}',
  is_high_impact  boolean not null default false,
  status          text not null default 'PENDING'
                  check (status in ('PENDING','AWAITING_CONFIRMATION','CONFIRMED','DECLINED','EXECUTED','FAILED','ROLLED_BACK')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table ai_confirmations (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  action_id       uuid not null references ai_execution_actions(id) on delete cascade,
  requested_at    timestamptz not null default now(),
  confirmed_at    timestamptz,
  confirmed_by    uuid,
  method          text,
  is_confirmed    boolean not null default false,
  decline_reason  text,
  created_at      timestamptz not null default now()
);

create table ai_execution_results (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  ai_request_id   uuid not null references ai_requests(id) on delete cascade,
  summary         text,
  result          jsonb not null default '{}',
  status          ai_request_status not null default 'EXECUTING',
  created_at      timestamptz not null default now()
);

create table report_requests (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id         uuid not null,
  report_type     text not null check (report_type in (
                    'CUSTOMER_LEDGER','SUPPLIER_LEDGER','GENERAL_LEDGER','TRIAL_BALANCE',
                    'PROFIT_LOSS','BALANCE_SHEET','CASH_FLOW','CUSTOMER_AGING','SUPPLIER_AGING',
                    'PROJECT_PROFITABILITY','ACCOUNT_LEDGER','CUSTOM')),
  parameters      jsonb not null default '{}',
  output_format   text not null default 'JSON' check (output_format in ('JSON','PDF','XLSX','CSV')),
  status          report_status not null default 'PENDING',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table generated_reports (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  request_id      uuid not null references report_requests(id) on delete cascade,
  report_type     text not null,
  parameters      jsonb not null default '{}',
  data            jsonb,
  storage_path    text,
  generated_by    uuid,
  generated_at    timestamptz not null default now()
);
