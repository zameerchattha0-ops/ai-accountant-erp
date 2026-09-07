-- =====================================================================
-- 035_seed_banking_tools_control_plane.sql
-- Sync AI Control Plane with the Python tool registry.
-- Applied to live DB via Supabase MCP on 2026-09-01 (migration
-- `seed_banking_tools_control_plane`). Mirrored here to fix drift.
-- The banking trio exists in app/tools/__init__.py but was never seeded,
-- and the four statement-report tools had no ai.tool_parameters rows.
-- ai.tools / ai.tool_parameters are GLOBAL (no organization_id column).
-- =====================================================================

INSERT INTO ai.tools (
    name, slug, description, purpose, module_id,
    tool_type, read_only, requires_confirmation, requires_validation,
    requires_accounting_engine, organization_scoped, risk_level, status,
    implementation_reference
)
SELECT v.name, v.slug, v.description, v.purpose,
       (SELECT module_id FROM ai.tools WHERE slug = 'record_customer_receipt'),
       v.tool_type::ai.tool_type_code, v.read_only, v.requires_confirmation,
       v.requires_validation, v.requires_accounting_engine, true,
       v.risk_level::ai.risk_level_code, 'IMPLEMENTED', v.impl
FROM (VALUES
    ('List Bank Accounts', 'list_bank_accounts',
     'List the organization''s bank accounts',
     'Show available bank accounts for payments and receipts',
     'QUERY', true, false, false, false, 'LOW', 'services/bank_service.py'),
    ('Create Bank Account', 'create_bank_account',
     'Create a new bank account with its linked GL account',
     'Register a bank account so payments and receipts can use it',
     'MUTATION', false, false, false, false, 'LOW', 'services/bank_service.py'),
    ('Record Bank Transfer', 'record_bank_transfer',
     'Record a transfer between two bank accounts with journal',
     'Move money between bank accounts and post the journal entry',
     'MUTATION', false, true, true, true, 'MEDIUM', 'services/payment_service.py')
) AS v(name, slug, description, purpose, tool_type, read_only,
      requires_confirmation, requires_validation, requires_accounting_engine,
      risk_level, impl)
WHERE NOT EXISTS (SELECT 1 FROM ai.tools t WHERE t.slug = v.slug);

INSERT INTO ai.tool_parameters (tool_id, parameter_name, description, data_type, required, default_value, validation_rules, position)
SELECT t.id, v.parameter_name, 'Create a new bank account with its linked GL account',
       v.data_type, v.required, v.default_value, '{}'::jsonb, v.position
FROM ai.tools t
CROSS JOIN (VALUES
    ('account_name',          'string',  true,  NULL, 1),
    ('bank_name',             'string',  true,  NULL, 2),
    ('account_number_masked', 'string',  false, NULL, 3),
    ('iban',                  'string',  false, NULL, 4),
    ('branch_code',           'string',  false, NULL, 5),
    ('currency_code',         'string',  false, 'PKR', 6),
    ('is_default',            'boolean', false, 'false', 7)
) AS v(parameter_name, data_type, required, default_value, position)
WHERE t.slug = 'create_bank_account'
  AND NOT EXISTS (SELECT 1 FROM ai.tool_parameters tp WHERE tp.tool_id = t.id);

INSERT INTO ai.tool_parameters (tool_id, parameter_name, description, data_type, required, default_value, validation_rules, position)
SELECT t.id, v.parameter_name, 'Record a transfer between two bank accounts with journal',
       v.data_type, v.required, v.default_value, '{}'::jsonb, v.position
FROM ai.tools t
CROSS JOIN (VALUES
    ('source_bank_account_id',      'string', true,  NULL, 1),
    ('destination_bank_account_id', 'string', true,  NULL, 2),
    ('amount',                      'number', true,  NULL, 3),
    ('transfer_date',               'string', false, NULL, 4),
    ('reference',                   'string', false, NULL, 5),
    ('notes',                       'string', false, NULL, 6)
) AS v(parameter_name, data_type, required, default_value, position)
WHERE t.slug = 'record_bank_transfer'
  AND NOT EXISTS (SELECT 1 FROM ai.tool_parameters tp WHERE tp.tool_id = t.id);

INSERT INTO ai.tool_parameters (tool_id, parameter_name, description, data_type, required, default_value, validation_rules, position)
SELECT t.id, 'limit', 'Maximum number of rows to return', 'integer', false, '500', '{}'::jsonb, 1
FROM ai.tools t
WHERE t.slug IN ('get_trial_balance', 'get_profit_loss', 'get_balance_sheet', 'get_cash_flow')
  AND NOT EXISTS (SELECT 1 FROM ai.tool_parameters tp WHERE tp.tool_id = t.id);

UPDATE ai.permissions
SET allowed_tools = allowed_tools || '["list_bank_accounts","create_bank_account","record_bank_transfer"]'::jsonb,
    updated_at = now()
WHERE capability = 'payments'
  AND NOT (allowed_tools @> '["record_bank_transfer"]'::jsonb);
