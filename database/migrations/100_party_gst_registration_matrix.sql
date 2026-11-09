-- =====================================================================
-- Migration 100: Sales Tax (GST) Party Registration Matrix & Tax Profiles
-- =====================================================================
-- Adds explicit STRN (Sales Tax Registration Number) and sales_tax_status
-- to organizations, suppliers, and customers for Pakistan Sales Tax Act 1990
-- compliance (P-01 to P-07 purchase matrix and S-01 to S-06 sales matrix).
--
-- Status values:
--   - 'REGISTERED_ACTIVE'   : Active on FBR Sales Tax Active Taxpayer List (ATL)
--   - 'REGISTERED_INACTIVE' : Registered with FBR, but suspended/inactive on ATL
--   - 'UNREGISTERED'        : Not registered for Sales Tax
-- =====================================================================

alter table public.organizations add column if not exists strn text;
alter table public.organizations add column if not exists sales_tax_status text not null default 'UNREGISTERED';

alter table public.suppliers add column if not exists strn text;
alter table public.suppliers add column if not exists sales_tax_status text not null default 'UNREGISTERED';

alter table public.customers add column if not exists strn text;
alter table public.customers add column if not exists sales_tax_status text not null default 'UNREGISTERED';

create index if not exists idx_suppliers_gst_status on public.suppliers (organization_id, sales_tax_status);
create index if not exists idx_customers_gst_status on public.customers (organization_id, sales_tax_status);
