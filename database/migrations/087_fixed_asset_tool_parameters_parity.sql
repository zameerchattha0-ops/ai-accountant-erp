-- =====================================================================
-- 087 — FIXED-ASSET TOOL PARAMETERS PARITY (register/dispose/depreciate)
-- =====================================================================
-- PARITY LAW (same as 044): the model's parameter contract must expose what
-- the SERVICE actually accepts.  041 seeded only 7 params for
-- register_fixed_asset (5 for dispose, 4 for depreciation), while
-- services/fixed_asset_service.py accepts salvage_value, description,
-- depreciation_method, category_id, the explicit GL ids, supplier_id and the
-- proceeds/gain-loss accounts — so the model was never TOLD about them and
-- could not supply the depreciation answers it had already collected from the
-- user (production 2026-10-01/02 plant sessions).
--
-- ai.tools / ai.tool_parameters are GLOBAL (no organization_id column).
-- Idempotent: guarded by NOT EXISTS per (tool, parameter).
-- Positions continue after the rows 041 seeded (register 1..7,
-- dispose 1..5, depreciation 1..4).
-- =====================================================================

insert into ai.tool_parameters
  (tool_id, parameter_name, description, data_type, required, position)
select t.id, v.parameter_name, v.description, v.data_type, false, v.position
from ai.tools t
join (values
  -- register_fixed_asset (8..15)
  ('register_fixed_asset', 'depreciation_method',
     'STRAIGHT_LINE or REDUCING_BALANCE (defaults to STRAIGHT_LINE)', 'string', 8),
  ('register_fixed_asset', 'salvage_value',
     'Residual value at the end of the useful life (0)', 'number', 9),
  ('register_fixed_asset', 'description',
     'Purchase description stored on the asset', 'string', 10),
  ('register_fixed_asset', 'supplier_id',
     'Supplier UUID (preferred over supplier_name when known)', 'string', 11),
  ('register_fixed_asset', 'payment_account_id',
     'Explicit cash/bank GL account UUID for the payment (resolved when omitted)', 'string', 12),
  ('register_fixed_asset', 'category_id',
     'Fixed-asset category UUID (supplies default life/method/accounts)', 'string', 13),
  ('register_fixed_asset', 'depreciation_expense_account_id',
     'Depreciation Expense GL account UUID (best effort at registration)', 'string', 14),
  ('register_fixed_asset', 'accumulated_depreciation_account_id',
     'Accumulated Depreciation GL account UUID (best effort at registration)', 'string', 15),
  -- dispose_fixed_asset (6..7)
  ('dispose_fixed_asset', 'proceeds_account_id',
     'GL account UUID receiving the disposal proceeds', 'string', 6),
  ('dispose_fixed_asset', 'gain_loss_account_id',
     'GL account UUID posting the gain or loss on disposal', 'string', 7),
  -- record_asset_depreciation (5..6)
  ('record_asset_depreciation', 'depreciation_expense_account_id',
     'Depreciation Expense GL account UUID (uses the asset''s stored default when omitted)', 'string', 5),
  ('record_asset_depreciation', 'accumulated_depreciation_account_id',
     'Accumulated Depreciation GL account UUID (uses the asset''s stored default when omitted)', 'string', 6)
) as v(slug, parameter_name, description, data_type, position)
  on t.slug = v.slug
where t.status = 'IMPLEMENTED'
  and not exists (
    select 1 from ai.tool_parameters tp
    where tp.tool_id = t.id and tp.parameter_name = v.parameter_name
  );

-- Verify (expected: register 15, dispose 7, depreciation 6 rows)
select t.slug, count(tp.id) as parameter_count
from ai.tools t
left join ai.tool_parameters tp on tp.tool_id = t.id
where t.slug in ('register_fixed_asset', 'dispose_fixed_asset', 'record_asset_depreciation')
group by t.slug
order by t.slug;
