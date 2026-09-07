-- =====================================================================
-- 038_seed_service_catalog_tools_control_plane.sql
-- Sync the AI Control Plane with the Python tool registry for the
-- service-catalog domain.  Applied to the live DB via Supabase MCP.
-- Idempotent.
--
-- Database contract verified before implementation:
--   public.services — service_code NOT NULL UNIQUE(org) with NO code
--   trigger (repository generates via next_document_number RPC);
--   billing_unit is service_unit_code (HOUR/DAY/MONTH/FIXED/ITEM);
--   standard_rate >= 0 CHECK; cost_rate NULL or >= 0 CHECK;
--   NO generated columns; NO inventory semantics.
-- =====================================================================

insert into ai.tools (slug, name, status) values
  ('search_service', 'Search Service Catalog', 'IMPLEMENTED'),
  ('create_service', 'Create Service',         'IMPLEMENTED')
on conflict (slug) do update set status = 'IMPLEMENTED';

insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, v.parameter_name, v.description, v.data_type, v.required, v.position
from ai.tools t
join (values
  ('search_service', 'query',         'Service name or part of name',              'string',  false, 1),
  ('create_service', 'name',          'Service name',                              'string',  true,  1),
  ('create_service', 'standard_rate', 'Standard billing rate per billing unit',    'number',  true,  2),
  ('create_service', 'billing_unit',  'HOUR, DAY, MONTH, FIXED or ITEM',           'string',  false, 3),
  ('create_service', 'cost_rate',     'Internal cost rate (optional)',             'number',  false, 4),
  ('create_service', 'description',   'Service description',                       'string',  false, 5)
) as v(slug, parameter_name, description, data_type, required, position)
  on t.slug = v.slug
where not exists (
  select 1 from ai.tool_parameters tp
  where tp.tool_id = t.id and tp.parameter_name = v.parameter_name
);

update ai.permissions
set allowed_tools = allowed_tools || '["search_service","create_service"]'::jsonb
where capability = 'master_data'
  and not allowed_tools @> '["search_service"]'::jsonb;
