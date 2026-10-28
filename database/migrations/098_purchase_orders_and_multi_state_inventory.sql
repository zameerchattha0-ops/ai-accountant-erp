-- =====================================================================
-- Migration 098: purchase_orders, purchase_order_items & multi-state stock pipeline
-- =====================================================================
-- Lifecycle:
--   RFQ / Draft Quotation -> ORDERED (Vendor Confirmed PO / In-Transit)
--   -> RECEIVED (Goods Received Note / Warehouse Stock)
--   -> BILLED (Purchase Bill) -> CANCELLED
-- =====================================================================

create table if not exists public.purchase_orders (
  id                      uuid primary key default gen_random_uuid(),
  organization_id         uuid not null references organizations(id) on delete cascade,
  po_number               text not null,
  supplier_id             uuid references suppliers(id) on delete set null,
  status                  text not null default 'RFQ' check (status in ('RFQ', 'ORDERED', 'RECEIVED', 'BILLED', 'CANCELLED')),
  order_date              date not null default current_date,
  expected_delivery_date  date,
  currency_code           char(3) references currencies(code),
  subtotal                numeric(18,2) not null default 0,
  tax_total               numeric(18,2) not null default 0,
  total                   numeric(18,2) not null default 0,
  notes                   text,
  terms                   text,
  created_by              uuid references auth.users(id),
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  unique (organization_id, po_number)
);

create index if not exists idx_purchase_orders_org_status
  on public.purchase_orders (organization_id, status);

create index if not exists idx_purchase_orders_supplier
  on public.purchase_orders (organization_id, supplier_id);

alter table public.purchase_orders enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename  = 'purchase_orders'
      and policyname = 'purchase_orders_org_access'
  ) then
    create policy purchase_orders_org_access on purchase_orders
      for all to authenticated
      using (public.is_org_member(organization_id))
      with check (public.is_org_member(organization_id));
  end if;
end $$;

-- ---------------------------------------------------------------------
-- Line items
-- ---------------------------------------------------------------------
create table if not exists public.purchase_order_items (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references organizations(id) on delete cascade,
  purchase_order_id uuid not null references purchase_orders(id) on delete cascade,
  line_number       smallint not null default 1,
  product_id        uuid references products(id) on delete set null,
  description       text not null,
  quantity          numeric(18,4) not null default 1 check (quantity > 0),
  unit_price        numeric(18,2) not null default 0 check (unit_price >= 0),
  tax_rate_id       uuid references tax_rates(id) on delete set null,
  tax_amount        numeric(18,2) not null default 0,
  line_total        numeric(18,2) not null default 0,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_purchase_order_items_po
  on public.purchase_order_items (organization_id, purchase_order_id);

create index if not exists idx_purchase_order_items_product
  on public.purchase_order_items (organization_id, product_id);

alter table public.purchase_order_items enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename  = 'purchase_order_items'
      and policyname = 'purchase_order_items_org_access'
  ) then
    create policy purchase_order_items_org_access on purchase_order_items
      for all to authenticated
      using (public.is_org_member(organization_id))
      with check (public.is_org_member(organization_id));
  end if;
end $$;

-- ---------------------------------------------------------------------
-- Multi-Stage Stock Pipeline View:
-- Segregates inventory into 5 stages:
-- 1. qty_on_hand: Physical stock inside warehouse (from perpetual ledger)
-- 2. qty_inbound_transit: Purchased goods on confirmed PO (in transit)
-- 3. qty_requisitioned: RFQ / vendor quotation (pre-order)
-- 4. qty_reserved: Stock committed to accepted sales orders / quotations
-- 5. qty_customer_premises: Dispatched to customer for trial/consignment/project
-- 6. qty_available: Usable stock = max(0, qty_on_hand - qty_reserved)
-- ---------------------------------------------------------------------
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
  group by poi.organization_id, poi.product_id
) inbound on inbound.product_id = p.id and inbound.organization_id = p.organization_id
left join (
  select poi.organization_id, poi.product_id, sum(poi.quantity) as qty_rfq
  from public.purchase_order_items poi
  join public.purchase_orders po on po.id = poi.purchase_order_id
  where po.status = 'RFQ'
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

grant select on public.purchase_orders to authenticated, service_role;
grant select on public.purchase_order_items to authenticated, service_role;
grant select on public.v_product_stock_pipeline to authenticated, service_role;
revoke all on public.v_product_stock_pipeline from anon;
