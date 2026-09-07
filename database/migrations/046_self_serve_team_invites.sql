-- =====================================================================
-- 046 — SELF-SERVE TEAM INVITES (no backend admin API required)
-- =====================================================================
-- Flow: org OWNER/ADMIN records an invite (email + role) from Settings.
-- When that email SIGNS UP, a trigger on auth.users automatically creates
-- the organization_members row (ACTIVE) with the invited role.  Users who
-- ALREADY exist can accept via the accept_my_team_invite() RPC, called
-- once by the frontend.  No invitation email is sent by the system — the
-- owner shares the app URL; the allowlist does the rest.
-- =====================================================================

create table public.team_invites (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  email           text not null check (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  role_code       text not null references public.organization_roles(code) on delete restrict,
  invited_by      uuid references auth.users(id) on delete set null,
  status          text not null default 'PENDING'
                    check (status in ('PENDING','ACCEPTED','REVOKED')),
  created_at      timestamptz not null default now(),
  accepted_at     timestamptz,
  unique (organization_id, email)
);

alter table public.team_invites enable row level security;

create policy team_invites_read on public.team_invites
  for select to authenticated
  using (has_org_role(organization_id, 5::smallint));

create policy team_invites_manage on public.team_invites
  for all to authenticated
  using (has_org_role(organization_id, 2::smallint))
  with check (has_org_role(organization_id, 2::smallint));

-- Auto-join on SIGNUP: a new auth user whose email matches a PENDING
-- invite becomes an ACTIVE member of the inviting organisation.
create or replace function public.link_pending_team_invite()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  invite record;
begin
  if new.email is null then
    return new;
  end if;
  select * into invite
  from public.team_invites
  where lower(email) = lower(new.email)
    and status = 'PENDING'
  order by created_at desc
  limit 1;
  if invite is null then
    return new;
  end if;
  insert into public.organization_members
    (organization_id, user_id, role_id, status, invited_by, joined_at)
  select invite.organization_id, new.id, r.id, 'ACTIVE', invite.invited_by, now()
  from public.organization_roles r
  where r.code = invite.role_code;
  update public.team_invites
  set status = 'ACCEPTED', accepted_at = now()
  where id = invite.id;
  return new;
end;
$$;

-- NOTE: verified there was NO pre-existing trigger on auth.users.
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.link_pending_team_invite();

-- Accept flow for ALREADY-REGISTERED users: joins the caller to any org
-- that has a PENDING invite for their (authenticated) email address.
create or replace function public.accept_my_team_invite()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  invite record;
  caller_email text;
  joined integer := 0;
begin
  if auth.uid() is null then
    return 0;
  end if;
  select email into caller_email from auth.users where id = auth.uid();
  if caller_email is null then
    return 0;
  end if;
  for invite in
    select * from public.team_invites
    where lower(email) = lower(caller_email)
      and status = 'PENDING'
    order by created_at desc
  loop
    -- Skip if the caller is somehow already a member of that org.
    if not exists (
      select 1 from public.organization_members
      where organization_id = invite.organization_id
        and user_id = auth.uid()
    ) then
      insert into public.organization_members
        (organization_id, user_id, role_id, status, invited_by, joined_at)
      select invite.organization_id, auth.uid(), r.id, 'ACTIVE',
             invite.invited_by, now()
      from public.organization_roles r
      where r.code = invite.role_code;
      joined := joined + 1;
    end if;
    update public.team_invites
    set status = 'ACCEPTED', accepted_at = now()
    where id = invite.id;
  end loop;
  return joined;
end;
$$;

grant execute on function public.accept_my_team_invite() to authenticated;

-- Member roster with emails (clients cannot read auth.users directly).
create or replace function public.list_team_members(target_org uuid)
returns table (
  user_id uuid,
  email text,
  full_name text,
  role_code text,
  role_name text,
  status text,
  joined_at timestamptz
)
language sql
security definer
set search_path = public
stable
as $$
  select m.user_id,
         u.email,
         coalesce(u.raw_user_meta_data->>'full_name', u.email),
         r.code,
         r.name,
         m.status::text,
         m.joined_at
  from public.organization_members m
  join public.organization_roles r on r.id = m.role_id
  join auth.users u on u.id = m.user_id
  where m.organization_id = target_org
    and has_org_role(target_org, 5::smallint)
  order by r.rank, m.created_at;
$$;

grant execute on function public.list_team_members(uuid) to authenticated;
