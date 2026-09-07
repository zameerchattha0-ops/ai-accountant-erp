-- =====================================================================
-- 044 — INVOICE/PURCHASE ITEMS PARITY: expose the `items` contract
-- =====================================================================
-- PARITY LAW: the AI tool path and the manual UI path must produce the
-- SAME rows.  invoice_service.create_invoice and
-- purchase_service.create_purchase_bill now accept `items` (validated,
-- line_total computed server-side, persisted via the item repositories).
-- The model's parameter contract must expose the SAME parameter:
--
--   items: array of {
--     description        string  required
--     quantity           number  required (> 0)
--     unit_price         number  required (>= 0)
--     product_id? / service_id?
--     discount_amount? / tax_rate_id? / tax_amount?
--     revenue_account_id?   (sales lines)
--     expense_account_id? / fixed_asset_id?   (purchase lines)
--   }
--
-- ai.tools / ai.tool_parameters are GLOBAL (no organization_id column).
-- Idempotent: guarded by NOT EXISTS.
-- =====================================================================

insert into ai.tool_parameters
  (tool_id, parameter_name, description, data_type, required, default_value, validation_rules, position)
select t.id, 'items',
       'Line items for the document. Each object: description (required), quantity (required, > 0), unit_price (required, >= 0), optional product_id, service_id, discount_amount, tax_rate_id, tax_amount, revenue_account_id (sales) / expense_account_id, fixed_asset_id (purchases). line_total is computed by the service — never supply it.',
       'array', false, null,
       jsonb_build_object(
         'item_shape', jsonb_build_object(
           'description',       'string (required, non-empty)',
           'quantity',          'number (required, > 0)',
           'unit_price',        'number (required, >= 0)',
           'product_id',        'uuid (optional)',
           'service_id',        'uuid (optional)',
           'discount_amount',   'number (optional, >= 0, <= quantity*unit_price)',
           'tax_rate_id',       'uuid (optional)',
           'tax_amount',        'number (optional)',
           'revenue_account_id','uuid (optional — sales lines)',
           'expense_account_id','uuid (optional — purchase lines)',
           'fixed_asset_id',    'uuid (optional — purchase lines capitalised as assets)'
         ),
         'note', 'Header totals are recomputed from the validated lines by the service.'
       ),
       coalesce((select max(tp.position) + 1 from ai.tool_parameters tp where tp.tool_id = t.id), 1)
from ai.tools t
where t.slug in ('create_invoice', 'create_purchase_bill')
  and not exists (
    select 1 from ai.tool_parameters tp
    where tp.tool_id = t.id and tp.parameter_name = 'items'
  );
