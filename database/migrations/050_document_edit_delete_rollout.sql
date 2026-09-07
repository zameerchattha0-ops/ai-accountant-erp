-- ============================================================
-- 050: EDIT/DELETE ROLLOUT TO DOCUMENT MODULES (journal pattern)
-- ============================================================
-- Work Stream F: applies the verified journal-entry permission model
-- (migration 048) to Quotations, Purchase Bills, Invoices, Expenses,
-- Payments and Receipts.
--
-- Permission model (mirrors journal_entries):
--   * SELECT / INSERT / UPDATE: any active organization member.
--   * DELETE: OWNER/ADMIN ONLY  (has_org_role(organization_id, 2)).
--     The previous <table>_org_access ALL policy allowed ANY member to
--     delete - it is replaced by four per-command policies.
--
-- Status-guard triggers (BEFORE UPDATE OR DELETE, all callers incl. AI):
--   * Quotations        - edit/delete DRAFT only; CONVERTED is locked.
--   * Purchase bills    - edit/delete DRAFT only; PAID/POSTED documents
--                         go through the purchase-return path.
--   * Invoices          - edit/delete DRAFT only; ISSUED/PAID documents
--                         are corrected by credit note.
--   * Expenses          - edit while unpaid; PAID expenses are reversed,
--                         never edited or deleted.
--   * Payments/Receipts - edit only while unallocated and not terminal;
--                         deletion requires zero allocations.
--
-- Linked journals: a document with a LINKED JOURNAL is NEVER deleted
-- (explicit refusal - the safer default, chosen deliberately). The
-- document's own correction path (reversal / credit note / return)
-- applies instead.
-- ============================================================

-- ---------------------------------------------------------------------------
-- Shared lifecycle guard (fires for every caller: UI, service, AI).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.guard_document_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v_label         text;
  v_source_type   text;
  v_terminal      text[];
  v_allocations   integer := 0;
  v_journals      integer := 0;
  v_material_edit boolean;
  v_delete_ok     boolean;
BEGIN
  -- A "material edit" is any change other than the status machine itself
  -- and the updated_at touch. Status transitions stay workflow-driven.
  v_material_edit :=
    to_jsonb(OLD) - ARRAY['status','updated_at'] IS DISTINCT FROM
    to_jsonb(NEW) - ARRAY['status','updated_at'];

  CASE TG_TABLE_NAME
    WHEN 'quotations' THEN
      v_label := 'Quotation'; v_source_type := 'quotation';
      v_terminal := ARRAY['CONVERTED'::quotation_status]::text[];
      v_delete_ok := (OLD.status = 'DRAFT');
    WHEN 'purchase_bills' THEN
      v_label := 'Purchase bill'; v_source_type := 'purchase_bill';
      v_terminal := ARRAY['VOIDED'::bill_status]::text[];
      v_delete_ok := (OLD.status = 'DRAFT');
    WHEN 'invoices' THEN
      v_label := 'Invoice'; v_source_type := 'invoice';
      v_terminal := ARRAY['CREDITED'::invoice_status,'VOIDED'::invoice_status]::text[];
      v_delete_ok := (OLD.status = 'DRAFT');
    WHEN 'expenses' THEN
      v_label := 'Expense'; v_source_type := 'expense';
      v_terminal := ARRAY['CANCELLED'::expense_status]::text[];
      v_delete_ok := (OLD.status <> 'PAID');
    WHEN 'payments' THEN
      v_label := 'Payment'; v_source_type := 'payment';
      v_terminal := ARRAY['CANCELLED'::payment_status,'REVERSED'::payment_status]::text[];
      v_delete_ok := TRUE;  -- deletability governed by allocations/journal below
    WHEN 'receipts' THEN
      v_label := 'Receipt'; v_source_type := 'receipt';
      v_terminal := ARRAY['CANCELLED'::payment_status,'REVERSED'::payment_status]::text[];
      v_delete_ok := TRUE;
    ELSE
      RAISE EXCEPTION 'guard_document_lifecycle: unhandled table %', TG_TABLE_NAME;
  END CASE;

  -- ---------------- DELETE -------------------------------------------------
  IF TG_OP = 'DELETE' THEN
    -- Linked-journal refusal (guaranteed coverage, chosen safe default).
    SELECT count(*) INTO v_journals
    FROM public.journal_entries je
    WHERE je.source_type = v_source_type AND je.source_id = OLD.id;
    IF v_journals > 0 THEN
      RAISE EXCEPTION
        '% cannot be deleted because a linked journal entry exists - use the document''s own correction path (reversal / credit note / purchase return) instead.',
        v_label;
    END IF;

    -- Payments/Receipts: allocations must be removed first (explicit message).
    IF TG_TABLE_NAME = 'payments' THEN
      SELECT count(*) INTO v_allocations
      FROM public.payment_allocations a WHERE a.payment_id = OLD.id;
    ELSIF TG_TABLE_NAME = 'receipts' THEN
      SELECT count(*) INTO v_allocations
      FROM public.receipt_allocations a WHERE a.receipt_id = OLD.id;
    END IF;
    IF v_allocations > 0 THEN
      RAISE EXCEPTION
        '% cannot be deleted while allocations exist (% found) - remove the allocations first.',
        v_label, v_allocations;
    END IF;

    IF NOT v_delete_ok THEN
      RAISE EXCEPTION
        'Only DRAFT %ss can be deleted (current status: %). Use the native correction path for confirmed documents.',
        v_label, OLD.status;
    END IF;
    RETURN OLD;
  END IF;

  -- ---------------- UPDATE -------------------------------------------------
  -- Terminal states are locked completely (no edits, no status transitions).
  IF OLD.status::text = ANY(v_terminal) THEN
    RAISE EXCEPTION
      '% is % and is locked - it cannot be modified.',
      v_label, OLD.status;
  END IF;

  -- Payments/Receipts: material edits require zero allocations.
  IF TG_TABLE_NAME = 'payments' THEN
    SELECT count(*) INTO v_allocations
    FROM public.payment_allocations a WHERE a.payment_id = OLD.id;
  ELSIF TG_TABLE_NAME = 'receipts' THEN
    SELECT count(*) INTO v_allocations
    FROM public.receipt_allocations a WHERE a.receipt_id = OLD.id;
  END IF;
  IF v_allocations > 0 AND v_material_edit THEN
    RAISE EXCEPTION
      '% has allocations and cannot be edited - remove the allocations first.',
      v_label;
  END IF;

  -- Expenses: PAID is corrected by reversal, never by edit.
  IF TG_TABLE_NAME = 'expenses' AND OLD.status = 'PAID' AND v_material_edit THEN
    RAISE EXCEPTION
      'Paid expense cannot be edited - record a reversal instead.';
  END IF;

  -- Quotations/bills/invoices: material fields freeze once confirmed.
  IF TG_TABLE_NAME IN ('quotations','purchase_bills','invoices')
     AND OLD.status <> 'DRAFT' AND v_material_edit THEN
    RAISE EXCEPTION
      '% in status % cannot be edited - only DRAFT documents are editable; use the native correction path (reversal / credit note / purchase return).',
      v_label, OLD.status;
  END IF;

  RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- Attach the guard to every module table.
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_quotations_lifecycle_guard ON public.quotations;
CREATE TRIGGER trg_quotations_lifecycle_guard
BEFORE UPDATE OR DELETE ON public.quotations
FOR EACH ROW EXECUTE FUNCTION public.guard_document_lifecycle();

DROP TRIGGER IF EXISTS trg_purchase_bills_lifecycle_guard ON public.purchase_bills;
CREATE TRIGGER trg_purchase_bills_lifecycle_guard
BEFORE UPDATE OR DELETE ON public.purchase_bills
FOR EACH ROW EXECUTE FUNCTION public.guard_document_lifecycle();

DROP TRIGGER IF EXISTS trg_invoices_lifecycle_guard ON public.invoices;
CREATE TRIGGER trg_invoices_lifecycle_guard
BEFORE UPDATE OR DELETE ON public.invoices
FOR EACH ROW EXECUTE FUNCTION public.guard_document_lifecycle();

DROP TRIGGER IF EXISTS trg_expenses_lifecycle_guard ON public.expenses;
CREATE TRIGGER trg_expenses_lifecycle_guard
BEFORE UPDATE OR DELETE ON public.expenses
FOR EACH ROW EXECUTE FUNCTION public.guard_document_lifecycle();

DROP TRIGGER IF EXISTS trg_payments_lifecycle_guard ON public.payments;
CREATE TRIGGER trg_payments_lifecycle_guard
BEFORE UPDATE OR DELETE ON public.payments
FOR EACH ROW EXECUTE FUNCTION public.guard_document_lifecycle();

DROP TRIGGER IF EXISTS trg_receipts_lifecycle_guard ON public.receipts;
CREATE TRIGGER trg_receipts_lifecycle_guard
BEFORE UPDATE OR DELETE ON public.receipts
FOR EACH ROW EXECUTE FUNCTION public.guard_document_lifecycle();

-- ---------------------------------------------------------------------------
-- RLS: replace the blanket ALL policy with the journal-entry pattern.
-- (Per-command policies; delete restricted to OWNER/ADMIN, rank <= 2.)
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS quotations_org_access ON public.quotations;
CREATE POLICY quotations_select ON public.quotations
  FOR SELECT TO authenticated USING (is_org_member(organization_id));
CREATE POLICY quotations_insert ON public.quotations
  FOR INSERT TO authenticated WITH CHECK (is_org_member(organization_id));
CREATE POLICY quotations_update ON public.quotations
  FOR UPDATE TO authenticated
  USING (is_org_member(organization_id))
  WITH CHECK (is_org_member(organization_id));
CREATE POLICY quotations_delete ON public.quotations
  FOR DELETE TO authenticated USING (has_org_role(organization_id, 2::smallint));

DROP POLICY IF EXISTS purchase_bills_org_access ON public.purchase_bills;
CREATE POLICY purchase_bills_select ON public.purchase_bills
  FOR SELECT TO authenticated USING (is_org_member(organization_id));
CREATE POLICY purchase_bills_insert ON public.purchase_bills
  FOR INSERT TO authenticated WITH CHECK (is_org_member(organization_id));
CREATE POLICY purchase_bills_update ON public.purchase_bills
  FOR UPDATE TO authenticated
  USING (is_org_member(organization_id))
  WITH CHECK (is_org_member(organization_id));
CREATE POLICY purchase_bills_delete ON public.purchase_bills
  FOR DELETE TO authenticated USING (has_org_role(organization_id, 2::smallint));

DROP POLICY IF EXISTS invoices_org_access ON public.invoices;
CREATE POLICY invoices_select ON public.invoices
  FOR SELECT TO authenticated USING (is_org_member(organization_id));
CREATE POLICY invoices_insert ON public.invoices
  FOR INSERT TO authenticated WITH CHECK (is_org_member(organization_id));
CREATE POLICY invoices_update ON public.invoices
  FOR UPDATE TO authenticated
  USING (is_org_member(organization_id))
  WITH CHECK (is_org_member(organization_id));
CREATE POLICY invoices_delete ON public.invoices
  FOR DELETE TO authenticated USING (has_org_role(organization_id, 2::smallint));

DROP POLICY IF EXISTS expenses_org_access ON public.expenses;
CREATE POLICY expenses_select ON public.expenses
  FOR SELECT TO authenticated USING (is_org_member(organization_id));
CREATE POLICY expenses_insert ON public.expenses
  FOR INSERT TO authenticated WITH CHECK (is_org_member(organization_id));
CREATE POLICY expenses_update ON public.expenses
  FOR UPDATE TO authenticated
  USING (is_org_member(organization_id))
  WITH CHECK (is_org_member(organization_id));
CREATE POLICY expenses_delete ON public.expenses
  FOR DELETE TO authenticated USING (has_org_role(organization_id, 2::smallint));

DROP POLICY IF EXISTS payments_org_access ON public.payments;
CREATE POLICY payments_select ON public.payments
  FOR SELECT TO authenticated USING (is_org_member(organization_id));
CREATE POLICY payments_insert ON public.payments
  FOR INSERT TO authenticated WITH CHECK (is_org_member(organization_id));
CREATE POLICY payments_update ON public.payments
  FOR UPDATE TO authenticated
  USING (is_org_member(organization_id))
  WITH CHECK (is_org_member(organization_id));
CREATE POLICY payments_delete ON public.payments
  FOR DELETE TO authenticated USING (has_org_role(organization_id, 2::smallint));

DROP POLICY IF EXISTS receipts_org_access ON public.receipts;
CREATE POLICY receipts_select ON public.receipts
  FOR SELECT TO authenticated USING (is_org_member(organization_id));
CREATE POLICY receipts_insert ON public.receipts
  FOR INSERT TO authenticated WITH CHECK (is_org_member(organization_id));
CREATE POLICY receipts_update ON public.receipts
  FOR UPDATE TO authenticated
  USING (is_org_member(organization_id))
  WITH CHECK (is_org_member(organization_id));
CREATE POLICY receipts_delete ON public.receipts
  FOR DELETE TO authenticated USING (has_org_role(organization_id, 2::smallint));
