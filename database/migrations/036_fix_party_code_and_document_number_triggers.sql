-- =====================================================================
-- 036_fix_party_code_and_document_number_triggers.sql
-- Applied to live DB via Supabase MCP (migration
-- `fix_party_code_and_document_number_triggers`, 2026-09-02).
-- Fix: these trigger functions assigned NEW columns via dynamic SQL
-- ("execute format('new.%I := ...')") which is invalid — plpgsql EXECUTE
-- runs SQL only. Every first insert into customers/suppliers/quotations/
-- invoices/credit_notes/purchase_bills/purchase_returns/expenses/
-- fixed_assets/payments/receipts failed with
-- 42601: syntax error at or near "new".
-- =====================================================================

CREATE OR REPLACE FUNCTION public.trg_party_code_assign()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'extensions'
AS $function$
declare
  v_prefix text;
  v_next text;
  v_doc_type text := tg_argv[0];
  v_prefix_col text := tg_argv[1];
  v_code_col text := tg_argv[2];
  v_default text := tg_argv[3];
begin
  if to_jsonb(new) ->> v_code_col is null or to_jsonb(new) ->> v_code_col = '' then
    execute format('select coalesce(s.%I, %L) from public.organization_settings s where s.organization_id = $1', v_prefix_col, v_default)
      into v_prefix using new.organization_id;
    v_next := public.next_document_number(new.organization_id, v_doc_type, coalesce(v_prefix, v_default));
    case v_code_col
      when 'customer_code' then new.customer_code := v_next;
      when 'supplier_code' then new.supplier_code := v_next;
      else raise exception 'trg_party_code_assign: unsupported code column %', v_code_col;
    end case;
  end if;
  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION public.trg_document_number_assign()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'extensions'
AS $function$
declare
  v_prefix text;
  v_next text;
  v_doc_type text := tg_argv[0];
  v_prefix_col text := tg_argv[1];
  v_number_col text := tg_argv[2];
begin
  if to_jsonb(new) ->> v_number_col is null or to_jsonb(new) ->> v_number_col = '' then
    execute format('select coalesce(s.%I, %L) from public.organization_settings s where s.organization_id = $1', v_prefix_col, tg_argv[3])
      into v_prefix using new.organization_id;
    v_next := public.next_document_number(new.organization_id, v_doc_type, coalesce(v_prefix, tg_argv[3]));
    case v_number_col
      when 'quotation_number'    then new.quotation_number := v_next;
      when 'invoice_number'      then new.invoice_number := v_next;
      when 'credit_note_number'  then new.credit_note_number := v_next;
      when 'bill_number'         then new.bill_number := v_next;
      when 'return_number'       then new.return_number := v_next;
      when 'expense_number'      then new.expense_number := v_next;
      when 'asset_code'          then new.asset_code := v_next;
      when 'payment_number'      then new.payment_number := v_next;
      when 'receipt_number'      then new.receipt_number := v_next;
      else raise exception 'trg_document_number_assign: unsupported number column %', v_number_col;
    end case;
  end if;
  return new;
end;
$function$;
