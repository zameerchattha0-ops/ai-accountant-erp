-- ============================================================
-- 049: AUDIT TRAIL FOR JOURNAL EDIT / DELETE / REVERSE
-- ============================================================
-- Work Stream E: the audit_logs table now receives a row for EVERY
-- journal-entry edit (before/after summary), DRAFT delete, and POSTED
-- reversal - for ALL paths (UI, service, AI) because it is enforced by
-- a DATABASE TRIGGER, not by application code.
--
-- Notes:
-- * audit_action_code gains a 'DELETE' value (additive, safe). The value
--   is only USED at trigger-fire time (later transactions), so adding it
--   inside this migration transaction is valid.
-- * The trigger function is SECURITY DEFINER (search_path pinned) so the
--   audit row lands regardless of the caller's RLS privileges. audit_logs
--   does not use FORCE ROW LEVEL SECURITY, so the table-owner insert is
--   permitted.
-- * POSTED documents remain immutable: in-place edits of posted entries
--   are already blocked by trg_journal_entries_status; the correction
--   path is REVERSAL, which this trigger records as action 'REVERSE'.
-- * auth.uid() is NULL for service-role writes (backend/AI); those rows
--   are recorded with actor_type SYSTEM. Human (authenticated) edits are
--   recorded with actor_type USER and their user_id.
-- ============================================================

ALTER TYPE public.audit_action_code ADD VALUE IF NOT EXISTS 'DELETE';

CREATE OR REPLACE FUNCTION public.audit_journal_entry_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_user  uuid := auth.uid();
  v_actor actor_type_code;
BEGIN
  v_actor := CASE
    WHEN v_user IS NULL THEN 'SYSTEM'::actor_type_code
    ELSE 'USER'::actor_type_code
  END;

  -- ---------------- DELETE (DRAFT-only; guard trigger enforces) ----------
  IF TG_OP = 'DELETE' THEN
    INSERT INTO public.audit_logs (
      organization_id, user_id, actor_type, action, entity_type,
      entity_id, entity_code, old_values, description
    )
    VALUES (
      OLD.organization_id, v_user, v_actor, 'DELETE', 'journal_entry',
      OLD.id, OLD.journal_number,
      jsonb_build_object(
        'status',           OLD.status,
        'transaction_date', OLD.transaction_date,
        'total_debit',      OLD.total_debit,
        'total_credit',     OLD.total_credit,
        'description',      OLD.description
      ),
      'Journal entry deleted (DRAFT-only - enforced by guard trigger).'
    );
    RETURN OLD;
  END IF;

  -- ---------------- REVERSE (posted correction path) ---------------------
  IF NEW.status = 'REVERSED'
     AND (OLD.status IS DISTINCT FROM NEW.status
          OR OLD.reversed_by_entry_id IS DISTINCT FROM NEW.reversed_by_entry_id) THEN
    INSERT INTO public.audit_logs (
      organization_id, user_id, actor_type, action, entity_type,
      entity_id, entity_code, old_values, new_values, description
    )
    VALUES (
      NEW.organization_id, v_user, v_actor, 'REVERSE', 'journal_entry',
      NEW.id, NEW.journal_number,
      jsonb_build_object('status', OLD.status),
      jsonb_build_object(
        'status',               NEW.status,
        'reversed_by_entry_id', NEW.reversed_by_entry_id
      ),
      'Posted journal entry reversed (immutable document; correction by reversal).'
    );
    RETURN NEW;
  END IF;

  -- ---------------- EDIT (material field change) --------------------------
  -- Only a material edit is audited: description / reference /
  -- transaction_date. Status transitions (DRAFT -> POSTED etc.) and the
  -- updated_at touch are NOT edits and would only add noise.
  IF (OLD.description      IS DISTINCT FROM NEW.description)
  OR (OLD.reference        IS DISTINCT FROM NEW.reference)
  OR (OLD.transaction_date IS DISTINCT FROM NEW.transaction_date) THEN
    INSERT INTO public.audit_logs (
      organization_id, user_id, actor_type, action, entity_type,
      entity_id, entity_code, old_values, new_values, description
    )
    VALUES (
      NEW.organization_id, v_user, v_actor, 'UPDATE', 'journal_entry',
      NEW.id, NEW.journal_number,
      jsonb_build_object(
        'description',      OLD.description,
        'reference',        OLD.reference,
        'transaction_date', OLD.transaction_date
      ),
      jsonb_build_object(
        'description',      NEW.description,
        'reference',        NEW.reference,
        'transaction_date', NEW.transaction_date
      ),
      'Journal entry edited (before/after summary captured).'
    );
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_journal_entries_audit ON public.journal_entries;

CREATE TRIGGER trg_journal_entries_audit
AFTER UPDATE OR DELETE ON public.journal_entries
FOR EACH ROW
EXECUTE FUNCTION public.audit_journal_entry_change();
