-- ============================================================================
-- 036 — Seed the trusted cash-sale domain tool in the AI control plane
-- ============================================================================
-- P1 fix (final verification pass): cash sales must flow through a trusted
-- domain operation (record_cash_sale) instead of the model manually
-- assembling prepare/validate/post journal calls (live defects S4/S7: the
-- model looped on search_account and produced no journal).
--
-- 1. ai.tools row (FK target for ai.tool_calls + tool_parameters source)
-- 2. ai.tool_parameters (the model's parameter contract)
-- 3. ai.permissions: the sales capability may use it
-- Idempotent: guarded by NOT EXISTS / @> checks.
-- ============================================================================

insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
                      read_only, requires_confirmation, requires_validation,
                      requires_accounting_engine, organization_scoped,
                      risk_level, status, implementation_reference)
select 'Record Cash Sale', 'record_cash_sale',
       'Record an immediate cash sale: resolves the Cash and Revenue accounts, prepares, validates and posts the journal via the accounting engine',
       'Record a cash sale transaction',
       t.module_id, 'MUTATION', false, false, true, true, true, 'MEDIUM', 'IMPLEMENTED',
       'accounting_engine.record_cash_sale via tools._record_cash_sale'
from ai.tools t
where t.slug = 'create_expense'
  and not exists (select 1 from ai.tools x where x.slug = 'record_cash_sale');

insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, p.parameter_name, p.description, p.data_type, p.required, p.position
from ai.tools t
join (values
  ('amount',           'Total cash amount received',                        'number', true,  1),
  ('description',      'What was sold',                                     'string', false, 2),
  ('transaction_date', 'Date of the sale (YYYY-MM-DD)',                     'string', false, 3),
  ('customer_id',      'Optional customer id for the cash-sale dimension',  'string', false, 4)
) as p(parameter_name, description, data_type, required, position)
on true
where t.slug = 'record_cash_sale'
  and not exists (
    select 1 from ai.tool_parameters ep
    where ep.tool_id = t.id and ep.parameter_name = p.parameter_name
  );

update ai.permissions
set allowed_tools = allowed_tools || '["record_cash_sale"]'::jsonb,
    updated_at = now()
where capability = 'sales'
  and not (allowed_tools @> '["record_cash_sale"]'::jsonb);