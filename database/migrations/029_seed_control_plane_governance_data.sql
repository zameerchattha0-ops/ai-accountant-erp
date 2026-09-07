-- Migration: seed_control_plane_governance_data
-- Seeds: agent permissions, validation rules, workflow steps for key workflows,
-- and updates instruction_versions to Constitution v1.1.0.

do $$
declare
  v_agent_id  uuid;
  v_wf_credit_sale uuid;
  v_wf_credit_purchase uuid;
  v_wf_create_invoice uuid;
  v_wf_record_expense uuid;
  v_wf_customer_payment uuid;
  v_wf_supplier_payment uuid;
begin
  -- Resolve agent
  select id into v_agent_id from ai.agents where slug = 'erp-accounting-agent';

  -- ============================================================
  -- 1. Agent Permissions (capability boundaries)
  -- ============================================================
  insert into ai.permissions (agent_id, capability, description, allowed_workflows, allowed_tools) values

  (v_agent_id, 'sales',
   'Create sales documents: quotations, invoices, credit notes',
   '["record_cash_sale","record_credit_sale","create_invoice"]'::jsonb,
   '["search_customer","get_customer","create_quotation","create_invoice","get_invoice","create_credit_note"]'::jsonb),

  (v_agent_id, 'purchases',
   'Record purchase bills and returns',
   '["record_cash_purchase","record_credit_purchase"]'::jsonb,
   '["search_supplier","get_supplier","create_purchase_bill","get_purchase_bill","create_purchase_return"]'::jsonb),

  (v_agent_id, 'expenses',
   'Record and classify business expenses',
   '["record_expense"]'::jsonb,
   '["create_expense","classify_expense","search_account","create_account"]'::jsonb),

  (v_agent_id, 'payments',
   'Record customer receipts and supplier payments',
   '["record_customer_payment","record_supplier_payment"]'::jsonb,
   '["record_customer_receipt","record_supplier_payment","record_expense_payment","search_customer","search_supplier","get_invoice","get_purchase_bill"]'::jsonb),

  (v_agent_id, 'reporting',
   'Generate financial reports and statements',
   '["generate_customer_ledger","generate_supplier_ledger","generate_trial_balance","generate_financial_statements","generate_project_profitability"]'::jsonb,
   '["get_general_ledger","get_trial_balance","get_profit_loss","get_balance_sheet","get_cash_flow","generate_report","get_customer_ledger","get_supplier_ledger","get_project_profitability"]'::jsonb),

  (v_agent_id, 'master_data',
   'Create and manage customer/supplier/project master records',
   '[]'::jsonb,
   '["search_customer","create_customer","get_customer","search_supplier","create_supplier","get_supplier","create_project","get_project"]'::jsonb),

  (v_agent_id, 'journal_management',
   'Prepare, validate, post, and reverse journal entries',
   '[]'::jsonb,
   '["prepare_journal","validate_journal","post_journal","reverse_journal","search_account","get_chart_of_accounts"]'::jsonb);

  -- ============================================================
  -- 2. Validation Rules
  -- ============================================================
  insert into ai.validation_rules (name, slug, rule_type, description, applies_to, condition, error_message, priority) values

  ('Customer must exist',
   'customer_exists',
   'ENTITY_EXISTS',
   'The referenced customer must exist in the organization',
   'create_invoice',
   '{"entity": "customer", "field": "customer_id"}'::jsonb,
   'Customer not found. Please create the customer first.',
   100),

  ('Accounting period must be open',
   'period_open_for_invoice',
   'PERIOD_OPEN',
   'The invoice date must fall within an open accounting period',
   'create_invoice',
   '{"date_field": "invoice_date"}'::jsonb,
   'No open accounting period for this date. Contact your administrator.',
   90),

  ('Invoice amount must be positive',
   'invoice_amount_positive',
   'AMOUNT_POSITIVE',
   'All line item amounts must be greater than zero',
   'create_invoice',
   '{"fields": ["unit_price", "quantity"]}'::jsonb,
   'Invoice line amounts must be positive numbers.',
   80),

  ('Journal entry must balance',
   'journal_balanced',
   'BALANCED',
   'Total debits must equal total credits',
   'post_journal',
   '{"debit_field": "total_debit", "credit_field": "total_credit"}'::jsonb,
   'Journal entry is not balanced. Debits must equal credits.',
   100),

  ('Accounting period must be open for posting',
   'period_open_for_journal',
   'PERIOD_OPEN',
   'Cannot post journal entries to closed or locked periods',
   'post_journal',
   '{"date_field": "transaction_date"}'::jsonb,
   'The accounting period for this date is closed or locked.',
   95),

  ('Supplier must exist',
   'supplier_exists',
   'ENTITY_EXISTS',
   'The referenced supplier must exist in the organization',
   'create_purchase_bill',
   '{"entity": "supplier", "field": "supplier_id"}'::jsonb,
   'Supplier not found. Please create the supplier first.',
   100),

  ('Accounting period must be open for bills',
   'period_open_for_bill',
   'PERIOD_OPEN',
   'The bill date must fall within an open accounting period',
   'create_purchase_bill',
   '{"date_field": "bill_date"}'::jsonb,
   'No open accounting period for this date.',
   90),

  ('Customer must exist for receipt',
   'customer_exists_for_receipt',
   'ENTITY_EXISTS',
   'The customer must exist before recording a receipt',
   'record_customer_payment',
   '{"entity": "customer", "field": "customer_id"}'::jsonb,
   'Customer not found.',
   100),

  ('Supplier must exist for payment',
   'supplier_exists_for_payment',
   'ENTITY_EXISTS',
   'The supplier must exist before recording a payment',
   'record_supplier_payment',
   '{"entity": "supplier", "field": "supplier_id"}'::jsonb,
   'Supplier not found.',
   100),

  ('Expense amount must be positive',
   'expense_amount_positive',
   'AMOUNT_POSITIVE',
   'Expense total must be greater than zero',
   'record_expense',
   '{"fields": ["amount"]}'::jsonb,
   'Expense amount must be a positive number.',
   80);

  -- ============================================================
  -- 3. Workflow Steps for key workflows
  -- ============================================================

  -- record_credit_sale
  select id into v_wf_credit_sale from ai.workflows
    where agent_id = v_agent_id and slug = 'record_credit_sale';

  if v_wf_credit_sale is not null then
    insert into ai.workflow_steps (workflow_id, step_order, name, description, step_type, required, failure_behavior) values
    (v_wf_credit_sale,  1, 'Interpret Request',       'Parse user request into structured intent',          'REASON',    true, 'ABORT'),
    (v_wf_credit_sale,  2, 'Resolve Customer',        'Find or clarify the target customer',                'RETRIEVE',  true, 'ABORT'),
    (v_wf_credit_sale,  3, 'Resolve Products/Services','Identify items, quantities, and prices',             'RETRIEVE',  true, 'ABORT'),
    (v_wf_credit_sale,  4, 'Resolve Accounts',        'Determine revenue and receivable accounts',           'RETRIEVE',  true, 'ABORT'),
    (v_wf_credit_sale,  5, 'Validate Period',         'Check accounting period is open',                     'VALIDATE',  true, 'ABORT'),
    (v_wf_credit_sale,  6, 'Validate Amounts',        'Verify positive amounts and calculations',           'VALIDATE',  true, 'ABORT'),
    (v_wf_credit_sale,  7, 'Generate Preview',        'Build human-readable preview for confirmation',       'RESPOND',   true, 'ABORT'),
    (v_wf_credit_sale,  8, 'Confirm with User',       'Present preview and await explicit approval',         'CONFIRM',   true, 'ABORT'),
    (v_wf_credit_sale,  9, 'Create Invoice',          'Execute invoice creation via backend service',        'EXECUTE',   true, 'ABORT'),
    (v_wf_credit_sale, 10, 'Verify Result',           'Confirm invoice exists in ERP with correct totals',   'VERIFY',    true, 'ABORT'),
    (v_wf_credit_sale, 11, 'Report Result',           'Summarise outcome to user',                           'RESPOND',   true, 'ABORT');
  end if;

  -- create_invoice
  select id into v_wf_create_invoice from ai.workflows
    where agent_id = v_agent_id and slug = 'create_invoice';

  if v_wf_create_invoice is not null then
    insert into ai.workflow_steps (workflow_id, step_order, name, description, step_type, required, failure_behavior) values
    (v_wf_create_invoice,  1, 'Interpret Request',       'Parse user request into structured intent',          'REASON',    true, 'ABORT'),
    (v_wf_create_invoice,  2, 'Resolve Customer',        'Find or clarify the target customer',                'RETRIEVE',  true, 'ABORT'),
    (v_wf_create_invoice,  3, 'Resolve Line Items',      'Identify items, accounts, quantities, prices',       'RETRIEVE',  true, 'ABORT'),
    (v_wf_create_invoice,  4, 'Resolve Tax Config',      'Determine applicable tax rates',                     'RETRIEVE',  false,'SKIP'),
    (v_wf_create_invoice,  5, 'Validate Period',         'Check accounting period is open',                     'VALIDATE',  true, 'ABORT'),
    (v_wf_create_invoice,  6, 'Validate Amounts',        'Verify positive amounts',                             'VALIDATE',  true, 'ABORT'),
    (v_wf_create_invoice,  7, 'Confirm with User',       'Present invoice preview for approval',               'CONFIRM',   true, 'ABORT'),
    (v_wf_create_invoice,  8, 'Create Invoice',          'Execute via invoice service',                         'EXECUTE',   true, 'ABORT'),
    (v_wf_create_invoice,  9, 'Verify Result',           'Confirm invoice in ERP',                              'VERIFY',    true, 'ABORT'),
    (v_wf_create_invoice, 10, 'Report Result',           'Summarise to user',                                   'RESPOND',   true, 'ABORT');
  end if;

  -- record_credit_purchase
  select id into v_wf_credit_purchase from ai.workflows
    where agent_id = v_agent_id and slug = 'record_credit_purchase';

  if v_wf_credit_purchase is not null then
    insert into ai.workflow_steps (workflow_id, step_order, name, description, step_type, required, failure_behavior) values
    (v_wf_credit_purchase,  1, 'Interpret Request',       'Parse user request',                                  'REASON',    true, 'ABORT'),
    (v_wf_credit_purchase,  2, 'Resolve Supplier',        'Find or clarify the target supplier',                 'RETRIEVE',  true, 'ABORT'),
    (v_wf_credit_purchase,  3, 'Resolve Items',           'Identify purchased items and amounts',                'RETRIEVE',  true, 'ABORT'),
    (v_wf_credit_purchase,  4, 'Resolve Accounts',        'Determine expense/asset and payable accounts',        'RETRIEVE',  true, 'ABORT'),
    (v_wf_credit_purchase,  5, 'Validate Period',         'Check accounting period is open',                     'VALIDATE',  true, 'ABORT'),
    (v_wf_credit_purchase,  6, 'Confirm with User',       'Present bill preview for approval',                   'CONFIRM',   true, 'ABORT'),
    (v_wf_credit_purchase,  7, 'Create Purchase Bill',    'Execute via purchase service',                        'EXECUTE',   true, 'ABORT'),
    (v_wf_credit_purchase,  8, 'Verify Result',           'Confirm bill in ERP',                                 'VERIFY',    true, 'ABORT'),
    (v_wf_credit_purchase,  9, 'Report Result',           'Summarise to user',                                   'RESPOND',   true, 'ABORT');
  end if;

  -- record_expense
  select id into v_wf_record_expense from ai.workflows
    where agent_id = v_agent_id and slug = 'record_expense';

  if v_wf_record_expense is not null then
    insert into ai.workflow_steps (workflow_id, step_order, name, description, step_type, required, failure_behavior) values
    (v_wf_record_expense, 1, 'Interpret Request',   'Parse expense request',              'REASON',    true, 'ABORT'),
    (v_wf_record_expense, 2, 'Classify Expense',    'Determine expense category/account', 'RETRIEVE',  true, 'ABORT'),
    (v_wf_record_expense, 3, 'Validate Period',     'Check accounting period is open',     'VALIDATE',  true, 'ABORT'),
    (v_wf_record_expense, 4, 'Validate Amount',     'Verify positive amount',              'VALIDATE',  true, 'ABORT'),
    (v_wf_record_expense, 5, 'Record Expense',      'Execute via expense service',         'EXECUTE',   true, 'ABORT'),
    (v_wf_record_expense, 6, 'Verify Result',       'Confirm expense in ERP',              'VERIFY',    true, 'ABORT'),
    (v_wf_record_expense, 7, 'Report Result',       'Summarise to user',                   'RESPOND',   true, 'ABORT');
  end if;

  -- record_customer_payment
  select id into v_wf_customer_payment from ai.workflows
    where agent_id = v_agent_id and slug = 'record_customer_payment';

  if v_wf_customer_payment is not null then
    insert into ai.workflow_steps (workflow_id, step_order, name, description, step_type, required, failure_behavior) values
    (v_wf_customer_payment, 1, 'Interpret Request',    'Parse payment request',              'REASON',    true, 'ABORT'),
    (v_wf_customer_payment, 2, 'Resolve Customer',     'Find the customer',                  'RETRIEVE',  true, 'ABORT'),
    (v_wf_customer_payment, 3, 'Resolve Open Invoices','Find outstanding invoices',           'RETRIEVE',  true, 'ABORT'),
    (v_wf_customer_payment, 4, 'Resolve Bank Account', 'Identify receiving bank account',    'RETRIEVE',  true, 'ABORT'),
    (v_wf_customer_payment, 5, 'Validate Period',      'Check accounting period is open',    'VALIDATE',  true, 'ABORT'),
    (v_wf_customer_payment, 6, 'Confirm with User',    'Present payment preview',             'CONFIRM',   true, 'ABORT'),
    (v_wf_customer_payment, 7, 'Record Receipt',       'Execute via receipt service',         'EXECUTE',   true, 'ABORT'),
    (v_wf_customer_payment, 8, 'Verify Result',        'Confirm receipt in ERP',              'VERIFY',    true, 'ABORT'),
    (v_wf_customer_payment, 9, 'Report Result',        'Summarise to user',                   'RESPOND',   true, 'ABORT');
  end if;

  -- record_supplier_payment
  select id into v_wf_supplier_payment from ai.workflows
    where agent_id = v_agent_id and slug = 'record_supplier_payment';

  if v_wf_supplier_payment is not null then
    insert into ai.workflow_steps (workflow_id, step_order, name, description, step_type, required, failure_behavior) values
    (v_wf_supplier_payment, 1, 'Interpret Request',    'Parse payment request',              'REASON',    true, 'ABORT'),
    (v_wf_supplier_payment, 2, 'Resolve Supplier',     'Find the supplier',                  'RETRIEVE',  true, 'ABORT'),
    (v_wf_supplier_payment, 3, 'Resolve Open Bills',   'Find outstanding bills',             'RETRIEVE',  true, 'ABORT'),
    (v_wf_supplier_payment, 4, 'Resolve Bank Account', 'Identify paying bank account',       'RETRIEVE',  true, 'ABORT'),
    (v_wf_supplier_payment, 5, 'Validate Period',      'Check accounting period is open',    'VALIDATE',  true, 'ABORT'),
    (v_wf_supplier_payment, 6, 'Confirm with User',    'Present payment preview',             'CONFIRM',   true, 'ABORT'),
    (v_wf_supplier_payment, 7, 'Record Payment',       'Execute via payment service',         'EXECUTE',   true, 'ABORT'),
    (v_wf_supplier_payment, 8, 'Verify Result',        'Confirm payment in ERP',              'VERIFY',    true, 'ABORT'),
    (v_wf_supplier_payment, 9, 'Report Result',        'Summarise to user',                   'RESPOND',   true, 'ABORT');
  end if;

  -- ============================================================
  -- 4. Update instruction_versions to Constitution v1.1.0
  -- ============================================================
  insert into ai.instruction_versions (
    agent_id, version, name, description, source_reference, status, activated_at
  ) values (
    v_agent_id, '1.1.0', 'ERP_AGENT_CONSTITUTION.md',
    'Comprehensive governance document: Control Plane schema, intent resolution, context rules, tool contracts, permissions, validation rules, confirmation lifecycle, atomicity, execution state machine',
    'Ai Accountant/ERP/ERP_AGENT_CONSTITUTION.md',
    'ACTIVE', now()
  );

  -- Retire previous version
  update ai.instruction_versions
  set status = 'ARCHIVED', retired_at = now()
  where agent_id = v_agent_id
    and version = '1.0.0'
    and status = 'ACTIVE';

  -- Update agent reference
  update ai.agents
  set current_instruction_version = '1.1.0'
  where id = v_agent_id;

end $$;
