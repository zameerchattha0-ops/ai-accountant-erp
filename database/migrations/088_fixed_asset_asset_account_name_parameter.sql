-- =====================================================================
-- 088 — register_fixed_asset: EXPOSE asset_account_name (parity)
-- =====================================================================
-- PARITY LAW (044/087): ai.tool_parameters must expose what the SERVICE
-- actually accepts, or the model is never TOLD the parameter exists.
--
-- 087 gave the model asset_account_id (pin an EXISTING ledger).  Production
-- 2026-10-03 ("Building @ Model Town" for 35,000,000) showed the other half
-- of the contract: when NO fitting ledger exists, the plan must CREATE one
-- first with a descriptive name and pin it by NAME.  register_asset now
-- accepts asset_account_name; the model must see exactly that:
-- EXACTLY ONE of asset_account_id | asset_account_name — never both,
-- never neither.
--
-- ai.tools / ai.tool_parameters are GLOBAL (no organization_id column).
-- Idempotent: guarded by NOT EXISTS.  Position continues after 087
-- (register 1..15).
-- =====================================================================

insert into ai.tool_parameters
  (tool_id, parameter_name, description, data_type, required, position)
select t.id, v.parameter_name, v.description, v.data_type, false, v.position
from ai.tools t
join (values
  ('register_fixed_asset', 'asset_account_name',
     'EXACT ledger name to pin when NO fitting ledger exists yet — the plan '
     || 'creates it FIRST (create_account) with a descriptive name, e.g. '
     || '''Building - Model Town''. Provide EXACTLY ONE of asset_account_id | '
     || 'asset_account_name — never both, never neither',
     'string', 16)
) as v(slug, parameter_name, description, data_type, position)
  on t.slug = v.slug
where t.status = 'IMPLEMENTED'
  and not exists (
    select 1 from ai.tool_parameters tp
    where tp.tool_id = t.id and tp.parameter_name = v.parameter_name
  );

-- Verify (expected: register 16, dispose 7, depreciation 6 rows)
select t.slug, count(tp.id) as parameter_count
from ai.tools t
left join ai.tool_parameters tp on tp.tool_id = t.id
where t.slug in ('register_fixed_asset', 'dispose_fixed_asset', 'record_asset_depreciation')
group by t.slug
order by t.slug;
