-- 099 — ALLOW PAYMENT SETTLEMENT UPDATES ON CONFIRMED INVOICES AND PURCHASE BILLS
-- ============================================================
-- INCIDENT: Recording customer receipt against invoice INV-000006 and
-- supplier payment against bill PUR-000005 failed with error P0001:
--   "Invoice in status ISSUED cannot be edited - only DRAFT documents are editable"
--   "Purchase bill in status OPEN cannot be edited - only DRAFT documents are editable"
--
-- ROOT CAUSE: guard_document_lifecycle() defines v_material_edit by stripping
-- only ARRAY['status', 'updated_at']. When payment service increments
-- amount_paid (and sets paid_at / status to PAID / PARTIALLY_PAID), Postgres
-- treats the change to amount_paid as a "material edit" on a non-DRAFT document
-- and raises exception P0001.
--
-- FIX: Exclude payment settlement fields (amount_paid, paid_at, sent_at)
-- from v_material_edit for invoices and purchase_bills. Changes to document
-- totals, lines, parties, and dates on non-DRAFT documents remain strictly blocked.
-- ============================================================

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
  -- A "material edit" is any change other than the status machine itself,
  -- updated_at, and payment settlement fields (amount_paid, paid_at, sent_at).
  -- Payment settlements on confirmed/issued documents update amount_paid and status
  -- and must never be blocked as material document edits.
  IF TG_TABLE_NAME = 'invoices' THEN
    v_material_edit :=
      to_jsonb(OLD) - ARRAY['status','updated_at','amount_paid','paid_at','sent_at'] IS DISTINCT FROM
      to_jsonb(NEW) - ARRAY['status','updated_at','amount_paid','paid_at','sent_at'];
  ELSIF TG_TABLE_NAME = 'purchase_bills' THEN
    v_material_edit :=
      to_jsonb(OLD) - ARRAY['status','updated_at','amount_paid','paid_at'] IS DISTINCT FROM
      to_jsonb(NEW) - ARRAY['status','updated_at','amount_paid','paid_at'];
  ELSE
    v_material_edit :=
      to_jsonb(OLD) - ARRAY['status','updated_at'] IS DISTINCT FROM
      to_jsonb(NEW) - ARRAY['status','updated_at'];
  END IF;

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
  IF TG_TABLE_NAME = 'expenses' AND OLD.status::text = 'PAID' AND v_material_edit THEN
    RAISE EXCEPTION
      'Paid expense cannot be edited - record a reversal instead.';
  END IF;

  -- Quotations/bills/invoices: material fields freeze once confirmed.
  IF TG_TABLE_NAME IN ('quotations','purchase_bills','invoices')
     AND OLD.status::text <> 'DRAFT' AND v_material_edit THEN
    RAISE EXCEPTION
      '% in status % cannot be edited - only DRAFT documents are editable; use the native correction path (reversal / credit note / purchase return).',
      v_label, OLD.status;
  END IF;

  RETURN NEW;
END;
$$;

