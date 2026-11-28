-- =====================================================================
-- Migration 104: Linked Multi-Stage Procurement Chain (RFQ -> PO -> GRN -> Bill)
-- =====================================================================
-- Preserves each procurement stage as its own document with distinct numbering:
--   Stage 1: RFQ (RFQ-0000xx, doc_type = 'PURCHASE_RFQ')
--   Stage 2: ORDERED (PO-0000xx, doc_type = 'PURCHASE_ORDER')
--   Stage 3: RECEIVED (GRN-0000xx, doc_type = 'GOODS_RECEIPT_NOTE')
--   Stage 4: BILLED (PUR-0000xx in purchase_bills, linked back to GRN/PO/RFQ)
--
-- Each promoted parent row retains its stage record & number and stores
-- promoted_to_order_id / promoted_to_bill_id / promoted_at, while child stages
-- and purchase_bills store backward lineage foreign keys for full provenance.
-- =====================================================================

-- 1. Lineage columns on purchase_orders
alter table public.purchase_orders
  add column if not exists parent_order_id uuid references public.purchase_orders(id) on delete set null,
  add column if not exists source_rfq_id uuid references public.purchase_orders(id) on delete set null,
  add column if not exists source_po_id uuid references public.purchase_orders(id) on delete set null,
  add column if not exists promoted_to_order_id uuid references public.purchase_orders(id) on delete set null,
  add column if not exists promoted_to_bill_id uuid references public.purchase_bills(id) on delete set null,
  add column if not exists promoted_at timestamptz;

create index if not exists idx_purchase_orders_parent
  on public.purchase_orders (organization_id, parent_order_id);

create index if not exists idx_purchase_orders_source_rfq
  on public.purchase_orders (organization_id, source_rfq_id);

create index if not exists idx_purchase_orders_source_po
  on public.purchase_orders (organization_id, source_po_id);

create index if not exists idx_purchase_orders_promoted_order
  on public.purchase_orders (organization_id, promoted_to_order_id);

create index if not exists idx_purchase_orders_promoted_bill
  on public.purchase_orders (organization_id, promoted_to_bill_id);

-- 2. Backward procurement lineage columns on purchase_bills
alter table public.purchase_bills
  add column if not exists source_order_id uuid references public.purchase_orders(id) on delete set null,
  add column if not exists source_rfq_id uuid references public.purchase_orders(id) on delete set null,
  add column if not exists source_po_id uuid references public.purchase_orders(id) on delete set null,
  add column if not exists source_grn_id uuid references public.purchase_orders(id) on delete set null;

create index if not exists idx_purchase_bills_source_order
  on public.purchase_bills (organization_id, source_order_id);

create index if not exists idx_purchase_bills_source_po
  on public.purchase_bills (organization_id, source_po_id);

-- 3. Seed/align separate sequences per procurement stage prefix so RFQs, POs,
--    and GRNs each have independent sequential numbering without collisions.
insert into public.document_sequences (organization_id, doc_type, prefix, next_value)
select
  o.id,
  'PURCHASE_RFQ',
  'RFQ',
  coalesce((
    select max((regexp_match(po.po_number, '^RFQ-(\d+)$'))[1]::bigint) + 1
    from public.purchase_orders po
    where po.organization_id = o.id
  ), 1)
from public.organizations o
on conflict (organization_id, doc_type)
do update set
  prefix = excluded.prefix,
  next_value = greatest(public.document_sequences.next_value, excluded.next_value);

insert into public.document_sequences (organization_id, doc_type, prefix, next_value)
select
  o.id,
  'PURCHASE_ORDER',
  'PO',
  coalesce((
    select max((regexp_match(po.po_number, '^PO-(\d+)$'))[1]::bigint) + 1
    from public.purchase_orders po
    where po.organization_id = o.id
  ), 1)
from public.organizations o
on conflict (organization_id, doc_type)
do update set
  prefix = 'PO',
  next_value = excluded.next_value;

insert into public.document_sequences (organization_id, doc_type, prefix, next_value)
select
  o.id,
  'GOODS_RECEIPT_NOTE',
  'GRN',
  coalesce((
    select max((regexp_match(po.po_number, '^GRN-(\d+)$'))[1]::bigint) + 1
    from public.purchase_orders po
    where po.organization_id = o.id
  ), 1)
from public.organizations o
on conflict (organization_id, doc_type)
do update set
  prefix = excluded.prefix,
  next_value = greatest(public.document_sequences.next_value, excluded.next_value);

-- 4. Update Multi-Stage Stock Pipeline View so promoted ancestor stages
--    (already handed off to PO/GRN) are never double-counted in stock pipeline.
create or replace view public.v_product_stock_pipeline
with (security_invoker = true) as
select
  p.organization_id,
  p.id as product_id,
  p.product_code,
  p.name,
  p.unit,
  p.is_stock_tracked,
  coalesce(stock.quantity_on_hand, 0) as qty_on_hand,
  coalesce(stock.average_cost, p.cost_price, 0) as average_cost,
  coalesce(stock.total_value, 0) as valuation,
  coalesce(inbound.qty_inbound, 0) as qty_inbound_transit,
  coalesce(rfq.qty_rfq, 0) as qty_requisitioned,
  coalesce(reserved.qty_reserved, 0) as qty_reserved,
  coalesce(cp.qty_cp, 0) as qty_customer_premises,
  greatest(0, coalesce(stock.quantity_on_hand, 0) - coalesce(reserved.qty_reserved, 0)) as qty_available
from public.products p
left join public.v_product_stock stock
  on stock.product_id = p.id and stock.organization_id = p.organization_id
left join (
  select poi.organization_id, poi.product_id, sum(poi.quantity) as qty_inbound
  from public.purchase_order_items poi
  join public.purchase_orders po on po.id = poi.purchase_order_id
  where po.status = 'ORDERED'
    and po.promoted_to_order_id is null
  group by poi.organization_id, poi.product_id
) inbound on inbound.product_id = p.id and inbound.organization_id = p.organization_id
left join (
  select poi.organization_id, poi.product_id, sum(poi.quantity) as qty_rfq
  from public.purchase_order_items poi
  join public.purchase_orders po on po.id = poi.purchase_order_id
  where po.status = 'RFQ'
    and po.promoted_to_order_id is null
  group by poi.organization_id, poi.product_id
) rfq on rfq.product_id = p.id and rfq.organization_id = p.organization_id
left join (
  select qi.organization_id, qi.product_id, sum(qi.quantity) as qty_reserved
  from public.quotation_items qi
  join public.quotations q on q.id = qi.quotation_id
  where q.status = 'ACCEPTED'
  group by qi.organization_id, qi.product_id
) reserved on reserved.product_id = p.id and reserved.organization_id = p.organization_id
left join (
  select im.organization_id, im.product_id,
         sum(case when im.direction = 'ISSUE' then im.quantity else -im.quantity end) as qty_cp
  from public.inventory_movements im
  where im.source_type in ('customer_premises', 'consignment', 'in_flight')
  group by im.organization_id, im.product_id
) cp on cp.product_id = p.id and cp.organization_id = p.organization_id;

grant select on public.v_product_stock_pipeline to authenticated, service_role;
revoke all on public.v_product_stock_pipeline from anon;

-- 5. Extend create_purchase_bill_atomic to persist procurement lineage FKs
create or replace function public.create_purchase_bill_atomic(
  p_organization_id uuid,
  p_header jsonb,
  p_items jsonb default '[]'::jsonb,
  p_journal jsonb default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $function$
declare
  v_bill public.purchase_bills;
  v_item jsonb;
  v_line jsonb;
  v_idx integer := 0;
  v_items jsonb := '[]'::jsonb;
  v_entry_id uuid;
  v_supplier uuid;
begin
  v_supplier := (p_header->>'supplier_id')::uuid;
  if v_supplier is null then
    raise exception 'supplier_id is required' using errcode = '22023';
  end if;
  if not exists (
    select 1 from public.suppliers s
    where s.id = v_supplier and s.organization_id = p_organization_id
  ) then
    raise exception 'supplier % does not belong to organization %',
      v_supplier, p_organization_id using errcode = '42501';
  end if;

  insert into public.purchase_bills (
    organization_id, supplier_id, bill_date, due_date, payment_terms_days,
    supplier_invoice_ref, currency_code, subtotal, discount_total,
    tax_total, total, notes, created_by,
    source_order_id, source_rfq_id, source_po_id, source_grn_id
  )
  values (
    p_organization_id, v_supplier,
    coalesce((p_header->>'bill_date')::date, current_date),
    (p_header->>'due_date')::date,
    coalesce((p_header->>'payment_terms_days')::smallint, 30),
    p_header->>'supplier_invoice_ref',
    (p_header->>'currency_code')::char(3),
    coalesce((p_header->>'subtotal')::numeric, 0),
    coalesce((p_header->>'discount_total')::numeric, 0),
    coalesce((p_header->>'tax_total')::numeric, 0),
    coalesce((p_header->>'total')::numeric, 0),
    p_header->>'notes',
    (p_header->>'created_by')::uuid,
    (p_header->>'source_order_id')::uuid,
    (p_header->>'source_rfq_id')::uuid,
    (p_header->>'source_po_id')::uuid,
    (p_header->>'source_grn_id')::uuid
  )
  returning * into v_bill;

  for v_item in select * from jsonb_array_elements(coalesce(p_items, '[]'::jsonb))
  loop
    v_idx := v_idx + 1;
    insert into public.purchase_bill_items (
      organization_id, bill_id, line_number, description, product_id,
      expense_account_id, project_id, fixed_asset_id, quantity, unit_price,
      discount_amount, tax_rate_id, tax_amount, line_total
    )
    values (
      p_organization_id, v_bill.id, v_idx,
      coalesce(v_item->>'description', ''),
      (v_item->>'product_id')::uuid,
      (v_item->>'expense_account_id')::uuid,
      (v_item->>'project_id')::uuid,
      (v_item->>'fixed_asset_id')::uuid,
      coalesce((v_item->>'quantity')::numeric, 1),
      coalesce((v_item->>'unit_price')::numeric, 0),
      coalesce((v_item->>'discount_amount')::numeric, 0),
      (v_item->>'tax_rate_id')::uuid,
      coalesce((v_item->>'tax_amount')::numeric, 0),
      coalesce((v_item->>'line_total')::numeric, 0)
    )
    returning to_jsonb(purchase_bill_items.*) into v_line;
    v_items := v_items || jsonb_build_array(v_line);
  end loop;

  if p_journal is not null
     and jsonb_typeof(coalesce(p_journal->'lines', 'null'::jsonb)) = 'array'
     and jsonb_array_length(p_journal->'lines') > 0
  then
    if (
      select coalesce(sum(coalesce((l->>'debit')::numeric, 0)), 0)
           - coalesce(sum(coalesce((l->>'credit')::numeric, 0)), 0)
      from jsonb_array_elements(p_journal->'lines') l
    ) <> 0 then
      raise exception 'journal for bill % is not balanced', v_bill.id
        using errcode = '23514';
    end if;

    insert into public.journal_entries (
      organization_id, transaction_date, description, reference,
      status, source_type, source_id, currency_code, created_by
    )
    values (
      p_organization_id,
      coalesce((p_journal->>'transaction_date')::date, v_bill.bill_date),
      coalesce(p_journal->>'description', 'Bill ' || v_bill.bill_number),
      p_journal->>'reference',
      'DRAFT', 'purchase_bill', v_bill.id,
      (p_journal->>'currency_code')::char(3),
      (p_header->>'created_by')::uuid
    )
    returning id into v_entry_id;

    for v_line in select * from jsonb_array_elements(p_journal->'lines')
    loop
      insert into public.journal_lines (
        organization_id, entry_id, account_id, description,
        debit, credit, supplier_id, project_id
      )
      values (
        p_organization_id, v_entry_id,
        (v_line->>'account_id')::uuid,
        v_line->>'description',
        coalesce((v_line->>'debit')::numeric, 0),
        coalesce((v_line->>'credit')::numeric, 0),
        (v_line->>'supplier_id')::uuid,
        (v_line->>'project_id')::uuid
      );
    end loop;

    update public.purchase_bills
    set journal_entry_id = v_entry_id
    where id = v_bill.id
    returning * into v_bill;
  end if;

  return jsonb_build_object(
    'bill', to_jsonb(v_bill),
    'items', v_items,
    'item_count', v_idx,
    'journal_entry_id', v_entry_id
  );
end;
$function$;

revoke all on function public.create_purchase_bill_atomic(uuid, jsonb, jsonb, jsonb) from public;
revoke all on function public.create_purchase_bill_atomic(uuid, jsonb, jsonb, jsonb) from anon;
revoke all on function public.create_purchase_bill_atomic(uuid, jsonb, jsonb, jsonb) from authenticated;
grant execute on function public.create_purchase_bill_atomic(uuid, jsonb, jsonb, jsonb) to service_role;
