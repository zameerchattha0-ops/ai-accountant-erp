-- Migration: create_ai_control_plane_schema
-- AI Control Plane: static agent metadata, tools, context, workflows.
-- Separate from existing runtime AI tables (public.ai_requests, etc.).

create schema if not exists ai;

-- ---- Enumerations ----
create type ai.agent_status_code       as enum ('ACTIVE','INACTIVE','ARCHIVED','PLANNED');
create type ai.module_type_code        as enum ('ORCHESTRATOR','PLANNER','CONTEXT_MANAGER','TOOL_ROUTER','VALIDATOR','ACCOUNTING_ENGINE','REPORTING','RESPONSE_FORMATTER');
create type ai.tool_type_code          as enum ('QUERY','MUTATION','REPORT','SYSTEM');
create type ai.risk_level_code         as enum ('LOW','MEDIUM','HIGH','CRITICAL');
create type ai.step_type_code          as enum ('REASON','RETRIEVE','VALIDATE','CONFIRM','EXECUTE','VERIFY','RESPOND');
create type ai.session_status_code     as enum ('PENDING','PLANNING','WAITING_FOR_USER','EXECUTING','COMPLETED','FAILED','CANCELLED');
create type ai.sensitivity_code        as enum ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED');
create type ai.source_type_code        as enum ('TABLE','VIEW','FUNCTION','SERVICE');
create type ai.failure_behavior_code   as enum ('ABORT','SKIP','CONTINUE','RETRY');
create type ai.verification_code       as enum ('VERIFIED','UNVERIFIED','FAILED');

-- ================================================================
-- ai.agents – register AI Agents available within the ERP
-- ================================================================
create table ai.agents (
  id                            uuid primary key default gen_random_uuid(),
  organization_id               uuid references public.organizations(id) on delete set null,
  name                          text not null,
  slug                          text not null,
  description                   text,
  purpose                       text,
  role                          text,
  status                        ai.agent_status_code not null default 'ACTIVE',
  current_version               text,
  current_instruction_version   text,
  default_model_configuration_id uuid,
  is_system_agent               boolean not null default false,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now(),
  unique (slug, organization_id)
);

-- ================================================================
-- ai.agent_versions – version the Agent implementation/configuration
-- ================================================================
create table ai.agent_versions (
  id            uuid primary key default gen_random_uuid(),
  agent_id      uuid not null references ai.agents(id) on delete cascade,
  version       text not null,
  description   text,
  configuration jsonb not null default '{}',
  status        ai.agent_status_code not null default 'ACTIVE',
  released_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (agent_id, version)
);

-- ================================================================
-- ai.agent_modules – individual logical components of the Agent
-- ================================================================
create table ai.agent_modules (
  id                uuid primary key default gen_random_uuid(),
  agent_id          uuid not null references ai.agents(id) on delete cascade,
  module_name       text not null,
  module_type       ai.module_type_code not null,
  description       text,
  purpose           text,
  responsibilities  jsonb not null default '[]',
  input_schema      jsonb not null default '{}',
  output_schema     jsonb not null default '{}',
  execution_order   smallint,
  status            ai.agent_status_code not null default 'ACTIVE',
  version           text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (agent_id, module_name)
);

-- ================================================================
-- ai.instruction_versions – track ERP_AGENT_CONSTITUTION.md versions
-- ================================================================
create table ai.instruction_versions (
  id                uuid primary key default gen_random_uuid(),
  agent_id          uuid not null references ai.agents(id) on delete cascade,
  version           text not null,
  name              text not null,
  description       text,
  content_hash      text,
  source_reference  text,
  status            ai.agent_status_code not null default 'ACTIVE',
  created_at        timestamptz not null default now(),
  activated_at      timestamptz,
  retired_at        timestamptz,
  unique (agent_id, version)
);

-- ================================================================
-- ai.model_configurations – Gemini model configuration (NO secrets)
-- ================================================================
create table ai.model_configurations (
  id            uuid primary key default gen_random_uuid(),
  provider      text not null,
  model_name    text not null,
  model_version text,
  configuration jsonb not null default '{}',
  status        ai.agent_status_code not null default 'ACTIVE',
  is_default    boolean not null default false,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (provider, model_name, model_version)
);

-- Add deferred FK from agents now that model_configurations exists
alter table ai.agents
  add constraint fk_agents_model_config
  foreign key (default_model_configuration_id)
  references ai.model_configurations(id) on delete set null;

-- ================================================================
-- ai.tools – controlled capabilities available to the Agent
-- ================================================================
create table ai.tools (
  id                            uuid primary key default gen_random_uuid(),
  name                          text not null,
  slug                          text not null unique,
  description                   text,
  purpose                       text,
  module_id                     uuid references ai.agent_modules(id) on delete set null,
  tool_type                     ai.tool_type_code not null default 'QUERY',
  read_only                     boolean not null default true,
  requires_confirmation         boolean not null default false,
  requires_validation           boolean not null default false,
  requires_accounting_engine    boolean not null default false,
  organization_scoped           boolean not null default true,
  risk_level                    ai.risk_level_code not null default 'LOW',
  status                        ai.agent_status_code not null default 'ACTIVE',
  version                       text,
  implementation_reference      text,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now()
);

-- ================================================================
-- ai.tool_parameters – input/output contracts for tools
-- ================================================================
create table ai.tool_parameters (
  id                uuid primary key default gen_random_uuid(),
  tool_id           uuid not null references ai.tools(id) on delete cascade,
  parameter_name    text not null,
  description       text,
  data_type         text not null,
  required          boolean not null default false,
  default_value     text,
  validation_rules  jsonb not null default '{}',
  position          smallint,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (tool_id, parameter_name)
);

-- ================================================================
-- ai.context_sources – where the Agent can retrieve information
-- ================================================================
create table ai.context_sources (
  id                  uuid primary key default gen_random_uuid(),
  name                text not null,
  slug                text not null unique,
  source_type         ai.source_type_code not null default 'TABLE',
  description         text,
  schema_name         text,
  table_name          text,
  view_name           text,
  function_name       text,
  tool_name           text,
  sensitivity         ai.sensitivity_code not null default 'INTERNAL',
  organization_scoped boolean not null default true,
  allowed_operations  jsonb not null default '["read"]',
  status              ai.agent_status_code not null default 'ACTIVE',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- ================================================================
-- ai.context_rules – relevant sources for particular intents
-- ================================================================
create table ai.context_rules (
  id                uuid primary key default gen_random_uuid(),
  agent_id          uuid not null references ai.agents(id) on delete cascade,
  name              text not null,
  intent            text not null,
  description       text,
  priority          smallint not null default 0,
  conditions        jsonb not null default '{}',
  required_sources  jsonb not null default '[]',
  optional_sources  jsonb not null default '[]',
  excluded_sources  jsonb not null default '[]',
  status            ai.agent_status_code not null default 'ACTIVE',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (agent_id, intent)
);

-- ================================================================
-- ai.workflows – high-level ERP workflows available to the Agent
-- ================================================================
create table ai.workflows (
  id                    uuid primary key default gen_random_uuid(),
  agent_id              uuid not null references ai.agents(id) on delete cascade,
  name                  text not null,
  slug                  text not null,
  description           text,
  intent                text,
  risk_level            ai.risk_level_code not null default 'LOW',
  requires_confirmation boolean not null default false,
  status                ai.agent_status_code not null default 'ACTIVE',
  version               text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (agent_id, slug)
);

-- ================================================================
-- ai.workflow_steps – logical execution sequence within workflows
-- ================================================================
create table ai.workflow_steps (
  id                uuid primary key default gen_random_uuid(),
  workflow_id       uuid not null references ai.workflows(id) on delete cascade,
  step_order        smallint not null,
  name              text not null,
  description       text,
  step_type         ai.step_type_code not null default 'REASON',
  module_id         uuid references ai.agent_modules(id) on delete set null,
  tool_id           uuid references ai.tools(id) on delete set null,
  required          boolean not null default true,
  conditions        jsonb not null default '{}',
  failure_behavior  ai.failure_behavior_code not null default 'ABORT',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (workflow_id, step_order),
  check (step_order > 0)
);

-- ================================================================
-- ai.execution_sessions – one AI request/execution lifecycle
-- ================================================================
create table ai.execution_sessions (
  id                      uuid primary key default gen_random_uuid(),
  organization_id         uuid not null references public.organizations(id) on delete cascade,
  user_id                 uuid not null,
  agent_id                uuid not null references ai.agents(id),
  agent_version_id        uuid references ai.agent_versions(id),
  instruction_version_id  uuid references ai.instruction_versions(id),
  model_configuration_id  uuid references ai.model_configurations(id),
  conversation_id         uuid,
  user_request            text not null,
  status                  ai.session_status_code not null default 'PENDING',
  started_at              timestamptz not null default now(),
  completed_at            timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- ================================================================
-- ai.execution_steps – Agent execution stages
-- ================================================================
create table ai.execution_steps (
  id                  uuid primary key default gen_random_uuid(),
  execution_session_id uuid not null references ai.execution_sessions(id) on delete cascade,
  step_order          smallint not null,
  module_id           uuid references ai.agent_modules(id) on delete set null,
  step_type           ai.step_type_code not null default 'REASON',
  description         text,
  status              ai.session_status_code not null default 'PENDING',
  input_summary       text,
  output_summary      text,
  started_at          timestamptz,
  completed_at        timestamptz,
  error_details       text,
  created_at          timestamptz not null default now()
);

-- ================================================================
-- ai.tool_calls – controlled ERP tool invocations during execution
-- ================================================================
create table ai.tool_calls (
  id                  uuid primary key default gen_random_uuid(),
  execution_session_id uuid not null references ai.execution_sessions(id) on delete cascade,
  execution_step_id   uuid references ai.execution_steps(id) on delete set null,
  tool_id             uuid not null references ai.tools(id),
  call_order          smallint not null,
  input_payload       jsonb not null default '{}',
  output_payload      jsonb not null default '{}',
  status              ai.session_status_code not null default 'PENDING',
  started_at          timestamptz,
  completed_at        timestamptz,
  error_details       text,
  created_at          timestamptz not null default now()
);

-- ================================================================
-- ai.clarifications – questions from Agent when info is missing/ambiguous
-- ================================================================
create table ai.clarifications (
  id                  uuid primary key default gen_random_uuid(),
  execution_session_id uuid not null references ai.execution_sessions(id) on delete cascade,
  question            text not null,
  reason              text,
  required_information jsonb not null default '[]',
  options             jsonb not null default '[]',
  user_response       text,
  status              ai.session_status_code not null default 'WAITING_FOR_USER',
  asked_at            timestamptz not null default now(),
  answered_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- ================================================================
-- ai.confirmations – explicit user confirmation for high-impact actions
-- ================================================================
create table ai.confirmations (
  id                  uuid primary key default gen_random_uuid(),
  execution_session_id uuid not null references ai.execution_sessions(id) on delete cascade,
  action_type         text not null,
  description         text,
  risk_level          ai.risk_level_code not null default 'MEDIUM',
  confirmation_required boolean not null default true,
  user_confirmed      boolean,
  confirmed_at        timestamptz,
  user_id             uuid,
  created_at          timestamptz not null default now()
);

-- ================================================================
-- ai.execution_results – final verified result of an AI execution
-- ================================================================
create table ai.execution_results (
  id                  uuid primary key default gen_random_uuid(),
  execution_session_id uuid not null unique references ai.execution_sessions(id) on delete cascade,
  status              ai.session_status_code not null default 'COMPLETED',
  summary             text,
  action_type         text,
  affected_entities   jsonb not null default '[]',
  result_payload      jsonb not null default '{}',
  verification_status ai.verification_code not null default 'UNVERIFIED',
  completed_at        timestamptz,
  created_at          timestamptz not null default now()
);

-- ================================================================
-- Indexes (non-FK, non-unique)
-- ================================================================
create index idx_ai_agents_org_status        on ai.agents (organization_id, status) where organization_id is not null;
create index idx_ai_agents_system            on ai.agents (is_system_agent) where is_system_agent = true;
create index idx_ai_tools_module             on ai.tools (module_id) where module_id is not null;
create index idx_ai_tools_type               on ai.tools (tool_type);
create index idx_ai_tools_risk               on ai.tools (risk_level);
create index idx_ai_context_rules_intent     on ai.context_rules (intent);
create index idx_ai_execution_sessions_org   on ai.execution_sessions (organization_id, created_at desc);
create index idx_ai_execution_sessions_agent on ai.execution_sessions (agent_id);
create index idx_ai_execution_sessions_conv  on ai.execution_sessions (conversation_id);
create index idx_ai_execution_steps_session  on ai.execution_steps (execution_session_id, step_order);
create index idx_ai_tool_calls_session       on ai.tool_calls (execution_session_id);
create index idx_ai_tool_calls_tool          on ai.tool_calls (tool_id);
create index idx_ai_clarifications_session   on ai.clarifications (execution_session_id);
create index idx_ai_confirmations_session    on ai.confirmations (execution_session_id);
create index idx_ai_execution_results_session on ai.execution_results (execution_session_id);

-- ================================================================
-- Row Level Security
-- ================================================================

-- Enable RLS on every ai schema table
alter table ai.agents                enable row level security;
alter table ai.agent_versions        enable row level security;
alter table ai.agent_modules         enable row level security;
alter table ai.instruction_versions  enable row level security;
alter table ai.model_configurations  enable row level security;
alter table ai.tools                 enable row level security;
alter table ai.tool_parameters       enable row level security;
alter table ai.context_sources       enable row level security;
alter table ai.context_rules         enable row level security;
alter table ai.workflows             enable row level security;
alter table ai.workflow_steps        enable row level security;
alter table ai.execution_sessions    enable row level security;
alter table ai.execution_steps       enable row level security;
alter table ai.tool_calls            enable row level security;
alter table ai.clarifications        enable row level security;
alter table ai.confirmations         enable row level security;
alter table ai.execution_results     enable row level security;

-- System metadata: readable by all authenticated users
do $$
declare t text;
begin
  foreach t in array array[
    'agents','agent_versions','agent_modules','instruction_versions',
    'model_configurations','tools','tool_parameters','context_sources',
    'context_rules','workflows','workflow_steps'
  ] loop
    execute format(
      'create policy ai_%s_read on ai.%I for select to authenticated using (true)',
      t, t
    );
  end loop;
end $$;

-- Organization-scoped execution data: org members only
-- execution_sessions has organization_id directly
create policy ai_execution_sessions_org on ai.execution_sessions for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

-- Tables without organization_id: check via parent execution_sessions
do $$
declare t text;
begin
  foreach t in array array[
    'execution_steps','tool_calls','clarifications','confirmations','execution_results'
  ] loop
    execute format(
      'create policy ai_%s_org on ai.%I for all to authenticated
         using (exists (
           select 1 from ai.execution_sessions s
           where s.id = %I.execution_session_id
             and public.is_org_member(s.organization_id)
         ))
         with check (exists (
           select 1 from ai.execution_sessions s
           where s.id = %I.execution_session_id
             and public.is_org_member(s.organization_id)
         ))',
      t, t, t, t
    );
  end loop;
end $$;

-- ================================================================
-- updated_at triggers (ai schema tables only)
-- ================================================================
do $$
declare
  r record;
begin
  for r in
    select c.relname as table_name
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    join information_schema.columns col
      on col.table_schema = n.nspname and col.table_name = c.relname and col.column_name = 'updated_at'
    where n.nspname = 'ai'
      and c.relkind = 'r'
  loop
    execute format(
      'create trigger trg_ai_%s_updated_at before update on ai.%I for each row execute function public.set_updated_at()',
      r.table_name, r.table_name
    );
  end loop;
end $$;
