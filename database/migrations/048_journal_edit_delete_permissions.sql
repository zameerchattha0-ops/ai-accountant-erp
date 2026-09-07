-- =====================================================================
-- 048 — JOURNAL EDIT/DELETE PERMISSIONS (parity with product rules)
-- =====================================================================
-- * EDIT: any ACTIVE organization member may edit (already allowed by the
--   old ALL policy — preserved via explicit select/insert/update).
-- * DELETE: OWNER/ADMIN only — the blanket ALL policy allowed ANY member
--   to delete journal entries, which is too permissive for books.
-- * SAFETY: only DRAFT entries may be deleted.  POSTED/REVERSED entries
--   are immutable by accounting law — the correction path is REVERSAL
--   (reverse_journal_entry), never deletion.
-- * journal_lines keeps member-wide access: editing an entry replaces its
--   lines (delete+insert) — that is an EDIT, not a transaction delete.
-- =====================================================================

drop policy if exists journal_entries_org_access on public.journal_entries;

create policy journal_entries_select on public.journal_entries
  for select to authenticated
  using (is_org_member(organization_id));

create policy journal_entries_insert on public.journal_entries
  for insert to authenticated
  with check (is_org_member(organization_id));

create policy journal_entries_update on public.journal_entries
  for update to authenticated
  using (is_org_member(organization_id))
  with check (is_org_member(organization_id));

create policy journal_entries_delete on public.journal_entries
  for delete to authenticated
  using (has_org_role(organization_id, 2::smallint));

-- Guard: only DRAFT entries may ever be deleted.
create or replace function public.guard_journal_entry_delete()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if old.status <> 'DRAFT' then
    raise exception 'Only DRAFT journal entries can be deleted. This entry is % — reverse it instead.', old.status;
  end if;
  return old;
end;
$$;

drop trigger if exists trg_journal_entries_guard_delete on public.journal_entries;
create trigger trg_journal_entries_guard_delete
  before delete on public.journal_entries
  for each row execute function public.guard_journal_entry_delete();
