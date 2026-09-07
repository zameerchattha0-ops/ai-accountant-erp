-- =====================================================================
-- 037_seed_catalog_and_asset_tools_control_plane.sql
-- Sync the AI Control Plane with the Python tool registry for the
-- product-catalog and fixed-asset-lifecycle domains.
-- Applied to the live DB via Supabase MCP (2026-09-03).  Idempotent.
--
-- Database contracts verified before writing the application layer:
--   public.products        (product_code UNIQUE per org; NO code trigger
--                           — the repository generates it via
--                           next_document_number RPC)
--   public.fixed_assets    (asset_code auto-assigned by
--                           trg_fixed_assets_number; asset_status enum)
--   public.asset_transactions / asset_depreciation_schedules
--   NO stock-ledger / warehouse tables exist — stock QUANTITY
--   operations are intentionally NOT exposed as tools.
-- =====================================================================

-- 1. Register the tools ----------------------------------------------------

insert into ai.tools (slug, name, status) values
  ('search_product',           'Search Product Catalog',        'IMPLEMENTED'),
  ('create_product',           'Create Product',                'IMPLEMENTED'),
  ('search_fixed_asset',       'Search Fixed Assets',           'IMPLEMENTED'),
  ('get_fixed_asset',          'Get Fixed Asset',               'IMPLEMENTED'),
  ('register_fixed_asset',     'Register Fixed Asset',          'IMPLEMENTED'),
  ('dispose_fixed_asset',      'Dispose Fixed Asset',           'IMPLEMENTED'),
  ('record_asset_depreciation','Record Asset Depreciation',     'IMPLEMENTED')
on conflict (slug) do update set status = 'IMPLEMENTED';

-- 2. Tool parameter contracts (function-calling schemas) -------------------

insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, v.parameter_name, v.description, v.data_type, v.required, v.position
from ai.tools t
join (values
  ('search_product',    'query',            'Product name or part of name',                        'string',  false, 1),
  ('create_product',    'name',             'Product name',                                        'string',  true,  1),
  ('create_product',    'unit_price',       'Selling price per unit',                              'number',  true,  2),
  ('create_product',    'cost_price',       'Purchase cost per unit (optional)',                   'number',  false, 3),
  ('create_product',    'unit',             'Unit of measure (e.g. pcs, box)',                     'string',  false, 4),
  ('create_product',    'description',      'Product description',                                 'string',  false, 5),
  ('search_fixed_asset', 'query',           'Asset name or code',                                  'string',  false, 1),
  ('get_fixed_asset',   'asset_id',         'Asset UUID',                                          'string',  true,  1),
  ('register_fixed_asset', 'name',          'Asset name',                                          'string',  true,  1),
  ('register_fixed_asset', 'purchase_cost', 'Acquisition cost (capitalised, never expensed)',      'number',  true,  2),
  ('register_fixed_asset', 'payment_method','CASH or CREDIT (ask if unknown — never assume)',      'string',  false, 3),
  ('register_fixed_asset', 'supplier_name', 'Supplier name (required for credit purchases)',       'string',  false, 4),
  ('register_fixed_asset', 'asset_account_id','Fixed-asset GL account id (or a unique account hint is resolved)', 'string', false, 5),
  ('register_fixed_asset', 'useful_life_years', 'Useful life in years (enables straight-line depreciation)', 'integer', false, 6),
  ('register_fixed_asset', 'transaction_date', 'Acquisition date (defaults to today)',             'string',  false, 7),
  ('dispose_fixed_asset',  'asset_name',       'Asset name (or asset_id)',                        'string',  false, 1),
  ('dispose_fixed_asset',  'asset_id',         'Asset UUID',                                      'string',  false, 2),
  ('dispose_fixed_asset',  'disposal_amount',  'Sale proceeds (0 for write-off)',                 'number',  false, 3),
  ('dispose_fixed_asset',  'disposal_type',    'DISPOSAL, SALE or WRITE_OFF',                     'string',  false, 4),
  ('dispose_fixed_asset',  'transaction_date', 'Disposal date (defaults to today)',               'string',  false, 5),
  ('record_asset_depreciation', 'asset_name',  'Asset name (or asset_id)',                        'string',  false, 1),
  ('record_asset_depreciation', 'asset_id',    'Asset UUID',                                      'string',  false, 2),
  ('record_asset_depreciation', 'depreciation_amount', 'Explicit depreciation amount (otherwise computed from useful life)', 'number', false, 3),
  ('record_asset_depreciation', 'transaction_date', 'Depreciation date (defaults to today)',     'string',  false, 4)
) as v(slug, parameter_name, description, data_type, required, position)
  on t.slug = v.slug
where not exists (
  select 1 from ai.tool_parameters tp
  where tp.tool_id = t.id and tp.parameter_name = v.parameter_name
);

-- 3. Capabilities ------------------------------------------------------------
-- Product catalog tools join master_data; asset lifecycle gets its own
-- 'assets' capability.

update ai.permissions
set allowed_tools = allowed_tools || '["search_product","create_product"]'::jsonb
where capability = 'master_data'
  and not allowed_tools @> '["search_product"]'::jsonb;

insert into ai.permissions (agent_id, capability, allowed_tools, denied_tools, status)
select p.agent_id,
       'assets',
       '["search_fixed_asset","get_fixed_asset","register_fixed_asset","dispose_fixed_asset","record_asset_depreciation"]'::jsonb,
       '[]'::jsonb,
       'ACTIVE'
from ai.permissions p
where p.capability = 'master_data'
  and not exists (select 1 from ai.permissions where capability = 'assets');
