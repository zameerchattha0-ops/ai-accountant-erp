-- Migration: seed_ai_control_plane_metadata
-- Seed initial Agent, modules, instruction version, model configuration,
-- tools, context sources, context rules, and workflows.

do $$
declare
  v_agent_id         uuid;
  v_model_config_id  uuid;
  v_mod_orch         uuid;
  v_mod_planner      uuid;
  v_mod_ctx          uuid;
  v_mod_router       uuid;
  v_mod_validator    uuid;
  v_mod_accounting   uuid;
  v_mod_reporting    uuid;
  v_mod_formatter    uuid;
begin
  -- ============================================================
  -- 1. Initial system Agent
  -- ============================================================
  insert into ai.agents (
    name, slug, description, purpose, role,
    status, is_system_agent, current_version, current_instruction_version
  ) values (
    'ERP Accounting Agent',
    'erp-accounting-agent',
    'AI-native operational interface for the accounting and financial ERP',
    'Orchestrate AI-driven accounting operations including sales, purchases, payments, reporting, and journal management',
    'ERP AI Orchestrator',
    'ACTIVE', true, '1.0.0', '1.0.0'
  ) returning id into v_agent_id;

  -- ============================================================
  -- 2. Gemini model configuration (NO secrets)
  -- ============================================================
  insert into ai.model_configurations (
    provider, model_name, model_version, configuration, status, is_default
  ) values (
    'Google',
    'gemini',
    '2.5-flash',
    '{"temperature": 0.1, "max_output_tokens": 8192, "top_p": 0.95, "top_k": 40}'::jsonb,
    'ACTIVE', true
  ) returning id into v_model_config_id;

  update ai.agents
  set default_model_configuration_id = v_model_config_id
  where id = v_agent_id;

  -- ============================================================
  -- 3. Agent modules
  -- ============================================================
  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Agent Orchestrator', 'ORCHESTRATOR',
   'Coordinates the complete AI request lifecycle from intake to response',
   'Manage the end-to-end flow: receive user request, delegate to modules, track progress, return result', 1)
  returning id into v_mod_orch;

  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Planner', 'PLANNER',
   'Determines what needs to happen based on the user request',
   'Analyse intent, select workflow, determine execution steps and required tools', 2)
  returning id into v_mod_planner;

  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Context Manager', 'CONTEXT_MANAGER',
   'Determines what information is required and retrieves relevant context',
   'Query context rules, fetch data through approved tools, assemble runtime context for Gemini', 3)
  returning id into v_mod_ctx;

  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Tool Router', 'TOOL_ROUTER',
   'Routes AI decisions to approved ERP capabilities',
   'Map planned actions to registered tools, enforce security model, dispatch calls', 4)
  returning id into v_mod_router;

  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Validator', 'VALIDATOR',
   'Determines whether an operation is valid and permitted',
   'Validate business rules, check period status, verify account existence, enforce constraints', 5)
  returning id into v_mod_validator;

  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Accounting Engine', 'ACCOUNTING_ENGINE',
   'Determines deterministic accounting consequences',
   'Generate journal entries, calculate debit/credit, ensure balanced entries, post journals', 6)
  returning id into v_mod_accounting;

  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Reporting Agent', 'REPORTING',
   'Generates financial reports and statements',
   'Produce trial balance, P&L, balance sheet, cash flow, ledger reports', 7)
  returning id into v_mod_reporting;

  insert into ai.agent_modules (agent_id, module_name, module_type, description, purpose, execution_order) values
  (v_agent_id, 'Response Formatter', 'RESPONSE_FORMATTER',
   'Formats the AI response for the user',
   'Compose clear, structured responses summarising actions and results', 8)
  returning id into v_mod_formatter;

  -- ============================================================
  -- 4. Initial instruction version (ERP_AGENT_CONSTITUTION.md)
  -- ============================================================
  insert into ai.instruction_versions (
    agent_id, version, name, description, source_reference, status, activated_at
  ) values (
    v_agent_id, '1.0.0', 'ERP_AGENT_CONSTITUTION.md',
    'Initial agent constitution defining behaviour, rules, and constraints',
    'Ai Accountant/ERP/ERP_AGENT_CONSTITUTION.md',
    'ACTIVE', now()
  );

  -- ============================================================
  -- 5. Initial agent version
  -- ============================================================
  insert into ai.agent_versions (
    agent_id, version, description, configuration, status, released_at
  ) values (
    v_agent_id, '1.0.0',
    'Initial release of the ERP Accounting Agent',
    '{"modules": 8, "tools_planned": 34, "workflows_planned": 13}'::jsonb,
    'ACTIVE', now()
  );

  -- ============================================================
  -- 6. Tool catalog — PLANNED status (backend not yet implemented)
  -- ============================================================

  -- Customer tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Search Customer',    'search_customer',      'Search customers by name, code, or contact',       'Find existing customers',                   v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/customer_service.py'),
  ('Create Customer',    'create_customer',       'Create a new customer record',                    'Register a new customer in the ERP',        v_mod_router, 'MUTATION', false, false, false, false, true, 'LOW',    'PLANNED', 'services/customer_service.py'),
  ('Get Customer',       'get_customer',          'Retrieve full customer details',                  'Load customer master data',                 v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/customer_service.py'),
  ('Get Customer Ledger','get_customer_ledger',   'Retrieve customer ledger with running balance',   'Show all transactions for a customer',      v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'repositories/customer_repository.py');

  -- Supplier tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Search Supplier',    'search_supplier',       'Search suppliers by name, code, or contact',      'Find existing suppliers',                   v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/supplier_service.py'),
  ('Create Supplier',    'create_supplier',       'Create a new supplier record',                    'Register a new supplier in the ERP',        v_mod_router, 'MUTATION', false, false, false, false, true, 'LOW',    'PLANNED', 'services/supplier_service.py'),
  ('Get Supplier',       'get_supplier',          'Retrieve full supplier details',                  'Load supplier master data',                 v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/supplier_service.py'),
  ('Get Supplier Ledger','get_supplier_ledger',   'Retrieve supplier ledger with running balance',   'Show all transactions for a supplier',      v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'repositories/supplier_repository.py');

  -- Accounting tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Search Account',          'search_account',          'Search chart of accounts by name or code',  'Find accounts',                             v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/account_service.py'),
  ('Create Account',          'create_account',           'Create a new account in chart of accounts','Add a new ledger account',                  v_mod_router, 'MUTATION', false, true,  false, false, true, 'MEDIUM', 'PLANNED', 'services/account_service.py'),
  ('Get Chart of Accounts',   'get_chart_of_accounts',    'Retrieve the full chart of accounts',     'Load account hierarchy',                    v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'repositories/account_repository.py'),
  ('Prepare Journal',         'prepare_journal',          'Prepare a draft journal entry',            'Create a DRAFT journal entry',              v_mod_router, 'MUTATION', false, false, true,  true,  true, 'MEDIUM', 'PLANNED', 'services/journal_service.py'),
  ('Validate Journal',        'validate_journal',         'Validate a draft journal entry',           'Check balanced entry before posting',       v_mod_router, 'MUTATION', false, false, true,  true,  true, 'MEDIUM', 'PLANNED', 'services/journal_service.py'),
  ('Post Journal',            'post_journal',             'Post a validated journal entry',           'Commit journal to the ledger',              v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'HIGH',   'PLANNED', 'services/journal_service.py'),
  ('Reverse Journal',         'reverse_journal',          'Reverse a posted journal entry',           'Create reversal entry with swapped debits/credits', v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'HIGH',   'PLANNED', 'services/journal_service.py');

  -- Sales tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Create Quotation', 'create_quotation', 'Create a sales quotation',    'Generate a quotation for a customer',       v_mod_router, 'MUTATION', false, false, false, false, true, 'LOW',    'PLANNED', 'services/quotation_service.py'),
  ('Create Invoice',   'create_invoice',   'Create a sales invoice',      'Generate an invoice and record revenue',     v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'MEDIUM', 'PLANNED', 'services/invoice_service.py'),
  ('Get Invoice',      'get_invoice',      'Retrieve invoice details',    'Load invoice with line items',              v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/invoice_service.py'),
  ('Create Credit Note','create_credit_note','Create a credit note',      'Issue a credit note against an invoice',    v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'MEDIUM', 'PLANNED', 'services/credit_note_service.py');

  -- Purchase tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Create Purchase Bill',   'create_purchase_bill',   'Create a purchase bill',     'Record a supplier bill',                 v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'MEDIUM', 'PLANNED', 'services/purchase_service.py'),
  ('Get Purchase Bill',      'get_purchase_bill',      'Retrieve purchase bill',     'Load bill with line items',            v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/purchase_service.py'),
  ('Create Purchase Return', 'create_purchase_return', 'Create a purchase return',   'Record return against a bill',       v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'MEDIUM', 'PLANNED', 'services/purchase_service.py');

  -- Expense tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Create Expense',   'create_expense',    'Record a business expense',  'Register an expense in the ERP',         v_mod_router, 'MUTATION', false, false, true,  true,  true, 'LOW',    'PLANNED', 'services/expense_service.py'),
  ('Classify Expense', 'classify_expense',  'Classify expense category',  'Determine correct expense account',        v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/expense_service.py');

  -- Payment tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Record Customer Receipt', 'record_customer_receipt', 'Record payment from customer',  'Register receipt against invoices', v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'MEDIUM', 'PLANNED', 'services/receipt_service.py'),
  ('Record Supplier Payment', 'record_supplier_payment', 'Record payment to supplier',    'Register payment against bills',    v_mod_router, 'MUTATION', false, true,  true,  true,  true, 'MEDIUM', 'PLANNED', 'services/payment_service.py'),
  ('Record Expense Payment',  'record_expense_payment',  'Record payment for an expense', 'Register expense payment',          v_mod_router, 'MUTATION', false, false, true,  true,  true, 'LOW',    'PLANNED', 'services/payment_service.py');

  -- Project tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Create Project',            'create_project',             'Create a new project',              'Register a project in the ERP',             v_mod_router, 'MUTATION', false, false, false, false, true, 'LOW',    'PLANNED', 'services/project_service.py'),
  ('Get Project',               'get_project',                'Retrieve project details',          'Load project master data',                    v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'services/project_service.py'),
  ('Get Project Profitability', 'get_project_profitability',  'Analyse project profitability',     'Revenue vs costs for a project',            v_mod_router, 'QUERY',    true,  false, false, false, true, 'LOW',    'PLANNED', 'repositories/project_repository.py');

  -- Reporting tools
  insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
    read_only, requires_confirmation, requires_validation, requires_accounting_engine,
    organization_scoped, risk_level, status, implementation_reference) values
  ('Get General Ledger',  'get_general_ledger',  'Retrieve general ledger entries',  'Posted journal lines enriched with names', v_mod_reporting, 'REPORT', true, false, false, false, true, 'LOW', 'PLANNED', 'repositories/reporting_repository.py'),
  ('Get Trial Balance',   'get_trial_balance',   'Retrieve trial balance',           'Account balances summary',                 v_mod_reporting, 'REPORT', true, false, false, false, true, 'LOW', 'PLANNED', 'repositories/reporting_repository.py'),
  ('Get Profit Loss',     'get_profit_loss',     'Retrieve income statement',        'Revenue and expense summary',              v_mod_reporting, 'REPORT', true, false, false, false, true, 'LOW', 'PLANNED', 'repositories/reporting_repository.py'),
  ('Get Balance Sheet',   'get_balance_sheet',   'Retrieve balance sheet',           'Assets, liabilities, equity',              v_mod_reporting, 'REPORT', true, false, false, false, true, 'LOW', 'PLANNED', 'repositories/reporting_repository.py'),
  ('Get Cash Flow',       'get_cash_flow',       'Retrieve cash flow statement',     'Cash inflows and outflows',                v_mod_reporting, 'REPORT', true, false, false, false, true, 'LOW', 'PLANNED', 'repositories/reporting_repository.py'),
  ('Generate Report',     'generate_report',     'Generate a custom report',         'Flexible report generation',               v_mod_reporting, 'REPORT', true, false, false, false, true, 'LOW', 'PLANNED', 'services/report_service.py');

  -- ============================================================
  -- 7. Context sources (mapped to actual Supabase tables/views)
  -- ============================================================
  insert into ai.context_sources (name, slug, source_type, description, schema_name, table_name, view_name, sensitivity, organization_scoped) values
  ('Customer Master',     'customer_master',     'TABLE',    'Customer records with contacts and addresses', 'public', 'customers',        null,                    'INTERNAL',     true),
  ('Supplier Master',     'supplier_master',     'TABLE',    'Supplier records with contacts and addresses', 'public', 'suppliers',        null,                    'INTERNAL',     true),
  ('Chart of Accounts',   'chart_of_accounts',   'TABLE',    'Account hierarchy and classifications',        'public', 'accounts',         null,                    'INTERNAL',     true),
  ('Invoices',            'invoices',            'TABLE',    'Sales invoices with line items',                'public', 'invoices',         null,                    'CONFIDENTIAL', true),
  ('Purchase Bills',      'purchase_bills',      'TABLE',    'Supplier purchase bills with line items',       'public', 'purchase_bills',   null,                    'CONFIDENTIAL', true),
  ('Expenses',            'expenses',            'TABLE',    'Business expense records',                      'public', 'expenses',         null,                    'INTERNAL',     true),
  ('Payments',            'payments',            'TABLE',    'Supplier payments and customer receipts',       'public', 'payments',         null,                    'CONFIDENTIAL', true),
  ('Receipts',            'receipts',            'TABLE',    'Customer payment receipts',                     'public', 'receipts',         null,                    'CONFIDENTIAL', true),
  ('Projects',            'projects',            'TABLE',    'Project master data with milestones',           'public', 'projects',         null,                    'INTERNAL',     true),
  ('Financial Years',     'financial_years',     'TABLE',    'Financial year definitions',                    'public', 'financial_years',  null,                    'INTERNAL',     true),
  ('Accounting Periods',  'accounting_periods',  'TABLE',    'Monthly accounting periods with status',        'public', 'accounting_periods',null,                   'INTERNAL',     true),
  ('Journal Entries',     'journal_entries',     'TABLE',    'Journal entry headers',                         'public', 'journal_entries',  null,                    'CONFIDENTIAL', true),
  ('Journal Lines',       'journal_lines',       'TABLE',    'Journal entry line items',                      'public', 'journal_lines',    null,                    'CONFIDENTIAL', true),
  ('General Ledger',      'general_ledger',      'VIEW',     'Posted journal lines enriched with names',      'public', null,               'v_general_ledger',      'CONFIDENTIAL', true),
  ('Customer Ledger',     'customer_ledger',     'VIEW',     'Customer transactions with running balance',     'public', null,               'v_customer_ledger',     'CONFIDENTIAL', true),
  ('Supplier Ledger',     'supplier_ledger',     'VIEW',     'Supplier transactions with running balance',     'public', null,               'v_supplier_ledger',     'CONFIDENTIAL', true),
  ('Trial Balance',       'trial_balance',       'VIEW',     'Account-level debit/credit summary',            'public', null,               'v_trial_balance',       'CONFIDENTIAL', true),
  ('Income Statement',    'income_statement',    'VIEW',     'Revenue and expense account summary',           'public', null,               'v_income_statement',    'CONFIDENTIAL', true),
  ('Balance Sheet',       'balance_sheet',       'VIEW',     'Asset, liability, and equity summary',          'public', null,               'v_balance_sheet',       'CONFIDENTIAL', true),
  ('Bank Accounts',       'bank_accounts',       'TABLE',    'Organisation bank account records',             'public', 'bank_accounts',    null,                    'CONFIDENTIAL', true),
  ('Fixed Assets',        'fixed_assets',        'TABLE',    'Fixed asset register with depreciation',         'public', 'fixed_assets',     null,                    'INTERNAL',     true);

  -- ============================================================
  -- 8. Context rules (intent → required sources)
  -- ============================================================
  insert into ai.context_rules (agent_id, name, intent, description, priority, required_sources, optional_sources) values
  (v_agent_id, 'Customer Balance',        'customer_balance',
   'Retrieve outstanding balance for a customer', 10,
   '["customer_master","customer_ledger","invoices","receipts"]'::jsonb,
   '["credit_notes"]'::jsonb),

  (v_agent_id, 'Supplier Balance',        'supplier_balance',
   'Retrieve outstanding balance for a supplier', 10,
   '["supplier_master","supplier_ledger","purchase_bills","payments"]'::jsonb,
   '[]'::jsonb),

  (v_agent_id, 'Create Invoice',          'create_invoice',
   'Context needed for creating a sales invoice', 20,
   '["customer_master","chart_of_accounts","accounting_periods"]'::jsonb,
   '["projects","tax_rates"]'::jsonb),

  (v_agent_id, 'Record Credit Purchase',  'record_credit_purchase',
   'Context for recording a credit purchase bill', 20,
   '["supplier_master","chart_of_accounts","accounting_periods"]'::jsonb,
   '["projects"]'::jsonb),

  (v_agent_id, 'Record Payment',          'record_payment',
   'Context for recording supplier or customer payment', 15,
   '["supplier_master","customer_master","bank_accounts","accounting_periods"]'::jsonb,
   '["purchase_bills","invoices"]'::jsonb),

  (v_agent_id, 'Project Profitability',   'project_profitability',
   'Analyse revenue vs costs for a project', 10,
   '["projects","general_ledger","accounting_periods"]'::jsonb,
   '[]'::jsonb),

  (v_agent_id, 'Generate Trial Balance',  'generate_trial_balance',
   'Context for generating a trial balance report', 5,
   '["trial_balance","accounting_periods"]'::jsonb,
   '[]'::jsonb),

  (v_agent_id, 'Generate Financial Statements', 'generate_financial_statements',
   'Context for P&L, balance sheet, cash flow', 5,
   '["income_statement","balance_sheet","accounting_periods"]'::jsonb,
   '["trial_balance"]'::jsonb);

  -- ============================================================
  -- 9. Workflows (PLANNED — backend not yet implemented)
  -- ============================================================
  insert into ai.workflows (agent_id, name, slug, description, intent, risk_level, requires_confirmation, status) values
  (v_agent_id, 'Record Cash Sale',                 'record_cash_sale',                'Record an immediate cash sale',                         'record_sale',          'MEDIUM', false, 'PLANNED'),
  (v_agent_id, 'Record Credit Sale',               'record_credit_sale',              'Record a credit sale creating an accounts receivable',  'record_credit_sale',   'MEDIUM', true,  'PLANNED'),
  (v_agent_id, 'Create Invoice',                   'create_invoice',                  'Create a sales invoice for a customer',                 'create_invoice',       'MEDIUM', true,  'PLANNED'),
  (v_agent_id, 'Record Cash Purchase',             'record_cash_purchase',            'Record an immediate cash purchase',                     'record_purchase',      'MEDIUM', false, 'PLANNED'),
  (v_agent_id, 'Record Credit Purchase',            'record_credit_purchase',          'Record a credit purchase creating an accounts payable', 'record_credit_purchase','MEDIUM', true,  'PLANNED'),
  (v_agent_id, 'Record Expense',                   'record_expense',                  'Record a business expense',                             'record_expense',       'LOW',    false, 'PLANNED'),
  (v_agent_id, 'Record Customer Payment',           'record_customer_payment',         'Record payment received from a customer',               'record_receipt',       'MEDIUM', true,  'PLANNED'),
  (v_agent_id, 'Record Supplier Payment',           'record_supplier_payment',         'Record payment made to a supplier',                     'record_payment',       'MEDIUM', true,  'PLANNED'),
  (v_agent_id, 'Generate Customer Ledger',          'generate_customer_ledger',        'Generate ledger report for a customer',                 'customer_balance',     'LOW',    false, 'PLANNED'),
  (v_agent_id, 'Generate Supplier Ledger',          'generate_supplier_ledger',        'Generate ledger report for a supplier',                 'supplier_balance',     'LOW',    false, 'PLANNED'),
  (v_agent_id, 'Generate Trial Balance',            'generate_trial_balance',          'Generate trial balance report',                         'generate_trial_balance','LOW',    false, 'PLANNED'),
  (v_agent_id, 'Generate Financial Statements',     'generate_financial_statements',   'Generate P&L, balance sheet, and cash flow',            'generate_financial_statements','LOW',false,'PLANNED'),
  (v_agent_id, 'Generate Project Profitability',    'generate_project_profitability',  'Analyse profitability of a project',                    'project_profitability','LOW',    false, 'PLANNED');

end $$;
