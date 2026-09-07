-- =====================================================================
-- 053 - ORG PREFERENCES (Work Stream F: clarification memory + defaults)
-- =====================================================================
-- The agent learns durable per-organization defaults from clarification
-- answers (payment mode, tax category, nature decision for a recurring
-- item) and reuses them as authoritative defaults on later runs.
-- Mirror of the document_sequences security pattern (045): RLS enabled,
-- service-role-only writes, no client policies by design - the agent's
-- trusted service layer is the ONLY writer; clients never need access.
-- =====================================================================

create table if not exists ai.org_preferences (
  id             uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  key            text not null,
  value          text not null,
  source         text not null default 'learned',  -- 'learned' | 'user_set'
  confidence     numeric not null default 0.8,
  updated_at     timestamptz not null default now(),
  unique (organization_id, key)
);

create index if not exists idx_org_preferences_org
  on ai.org_preferences (organization_id);

alter table ai.org_preferences enable row level security;

drop policy if exists org_preferences_service_role on ai.org_preferences;
create policy org_preferences_service_role
  on ai.org_preferences
  for all
  to service_role
  using (true)
  with check (true);

revoke all on ai.org_preferences from anon;
revoke all on ai.org_preferences from authenticated;
