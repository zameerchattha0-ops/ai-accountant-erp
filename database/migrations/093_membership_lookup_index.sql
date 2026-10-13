-- =====================================================================
-- Migration 093: membership lookup index (high-CPU forensics 2026-10-13)
-- =====================================================================
-- FINDING: pg_stat_user_tables showed organization_members with 220,564
-- SEQ SCANS (the hottest table in the project) while every membership
-- resolution in app/auth.py filters exactly:
--     WHERE user_id = X AND status = 'ACTIVE'
-- The existing indexes are (id) PK and (organization_id, user_id) —
-- neither leads with user_id, so every authenticated request
-- seq-scans the table.  Tiny today (18 rows), but it is the single
-- most-executed query pattern in the app and the index makes it O(log n).
-- =====================================================================

create index if not exists idx_organization_members_user_status
  on public.organization_members (user_id, status);

comment on index public.idx_organization_members_user_status is
  'Hot path: auth._resolve_membership filters user_id + ACTIVE status; '
  'was 220k seq scans before this index (high-CPU forensics 2026-10-13).';
