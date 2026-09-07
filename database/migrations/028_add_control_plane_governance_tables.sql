-- Migration: add_control_plane_governance_tables
-- Adds 3 missing Control Plane tables: permissions, validation_rules, audit_events
-- Plus an execution_phase enum for fine-grained session phase tracking.

-- ================================================================
-- Execution phase enum (fine-grained state within a session)
-- ================================================================
create type ai.execution_phase_code as enum (
  'RECEIVED',
  'INTERPRETING',
  'PLANNING',
  'CONTEXT_LOADING',
  'AWAITING_CLARIFICATION',
  'VALIDATING',
  'AWAITING_CONFIRMATION',
  'EXECUTING',
  'VERIFYING',
  'COMPLETED',
  'FAILED',
  'CANCELLED',
  'REJECTED'
);

-- ================================================================
-- ai.permissions – agent capability boundaries
-- ================================================================
create table ai.permissions (
  id                uuid primary key default gen_random_uuid(),
  agent_id          uuid not null references ai.agents(id) on delete cascade,
  capability        text not null,
  description       text,
  allowed_workflows jsonb not null default '[]',
  allowed_tools     jsonb not null default '[]',
  denied_tools      jsonb not null default '[]',
  conditions        jsonb not null default '{}',
  status            ai.agent_status_code not null default 'ACTIVE',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (agent_id, capability)
);

-- ================================================================
-- ai.validation_rules – business validation constraints
-- ================================================================
create table ai.validation_rules (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  slug          text not null unique,
  rule_type     text not null check (rule_type in (
                  'ENTITY_EXISTS','PERIOD_OPEN','BALANCED',
                  'NOT_DUPLICATE','CREDIT_LIMIT','TAX_VALID',
                  'AMOUNT_POSITIVE','CUSTOM'
                )),
  description   text,
  applies_to    text,  -- workflow slug or tool slug
  condition     jsonb not null default '{}',
  error_message text,
  priority      smallint not null default 0,
  status        ai.agent_status_code not null default 'ACTIVE',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ================================================================
-- ai.audit_events – agent-level governance audit trail
-- ================================================================
create table ai.audit_events (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid references public.organizations(id) on delete set null,
  execution_session_id uuid references ai.execution_sessions(id) on delete set null,
  actor_type          public.actor_type_code not null default 'AI',
  event_type          text not null,
  event_category      text,
  description         text,
  affected_entity_type text,
  affected_entity_id  uuid,
  details             jsonb not null default '{}',
  ip_address          inet,
  created_at          timestamptz not null default now()
);

-- ================================================================
-- Add execution_phase to execution_sessions
-- ================================================================
alter table ai.execution_sessions
  add column current_phase ai.execution_phase_code not null default 'RECEIVED';

-- ================================================================
-- Indexes
-- ================================================================
create index idx_ai_permissions_agent       on ai.permissions (agent_id);
create index idx_ai_validation_rules_type   on ai.validation_rules (rule_type);
create index idx_ai_validation_rules_applies on ai.validation_rules (applies_to);
create index idx_ai_audit_events_org        on ai.audit_events (organization_id, created_at desc);
create index idx_ai_audit_events_session    on ai.audit_events (execution_session_id);
create index idx_ai_audit_events_type       on ai.audit_events (event_type);
create index idx_ai_execution_sessions_phase on ai.execution_sessions (current_phase);

-- ================================================================
-- RLS
-- ================================================================
alter table ai.permissions      enable row level security;
alter table ai.validation_rules enable row level security;
alter table ai.audit_events     enable row level security;

-- permissions and validation_rules: system metadata, globally readable
create policy ai_permissions_read on ai.permissions
  for select to authenticated using (true);

create policy ai_validation_rules_read on ai.validation_rules
  for select to authenticated using (true);

-- audit_events: org-scoped (via execution_session or direct organization_id)
create policy ai_audit_events_org on ai.audit_events
  for all to authenticated
  using (
    organization_id is null
    or public.is_org_member(organization_id)
  )
  with check (
    organization_id is null
    or public.is_org_member(organization_id)
  );

-- ================================================================
-- updated_at triggers
-- ================================================================
do $$
declare r record;
begin
  for r in
    select c.relname as table_name
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'ai'
      and c.relkind = 'r'
      and c.relname in ('permissions','validation_rules')
      and exists (
        select 1 from information_schema.columns col
        where col.table_schema = 'ai' and col.table_name = c.relname and col.column_name = 'updated_at'
      )
      and not exists (
        select 1 from pg_trigger t join pg_proc p on p.oid = t.tgfoid
        where t.tgrelid = c.oid and not t.tgisinternal and p.proname = 'set_updated_at'
      )
  loop
    execute format(
      'create trigger trg_ai_%s_updated_at before update on ai.%I for each row execute function public.set_updated_at()',
      r.table_name, r.table_name
    );
  end loop;
end $$;
