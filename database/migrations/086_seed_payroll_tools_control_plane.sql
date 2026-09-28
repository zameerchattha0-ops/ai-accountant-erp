-- ============================================================================
-- 086 — Seed the Payroll tools in the AI control plane
-- ============================================================================
-- Two tools (worker: app/tools/__init__.py):
--   run_payroll         MUTATION  payroll   Dr Salaries / Cr Accrued Salaries
--   pay_employee_salary MUTATION  payroll   Dr Accrued Salaries / Cr bank-cash
-- Without these rows the runtime authorize_tool() gate denies the slugs.
--
-- The LLM structures the user's sentence (which tool, which date, whether the
-- salaries are paid or accrued); Python computes every amount from the
-- employee records (basic + active MONTHLY allowances − deductions) and posts
-- the journal through the accounting engine — the model never supplies a
-- computed figure.
-- Idempotent: guarded by NOT EXISTS checks.
-- ============================================================================

-- ---- 1. ai.tools -----------------------------------------------------------
insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
                      read_only, requires_confirmation, requires_validation,
                      requires_accounting_engine, organization_scoped,
                      risk_level, status, implementation_reference)
select 'Run Payroll', 'run_payroll',
       'Run payroll for every active employee: computes each salary from the employee records (basic + monthly allowances − deductions) and posts ONE journal — Dr Salaries / Cr Accrued Salaries, or Cr bank/cash when payment_method=PAID',
       'Record the monthly salary run for the whole roster',
       (select module_id from ai.tools where slug = 'create_customer' limit 1),
       'MUTATION', false, true, true, true, true, 'MEDIUM', 'IMPLEMENTED',
       'app.services.payroll_service.run_payroll via tools._run_payroll'
where not exists (select 1 from ai.tools x where x.slug = 'run_payroll');

insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
                      read_only, requires_confirmation, requires_validation,
                      requires_accounting_engine, organization_scoped,
                      risk_level, status, implementation_reference)
select 'Pay Employee Salary', 'pay_employee_salary',
       'Pay ONE employee''s salary: resolves the employee, debits Accrued Salaries (or the Salaries expense account when no accrual ledger exists) and credits bank/cash',
       'Pay a single employee''s salary',
       (select module_id from ai.tools where slug = 'create_customer' limit 1),
       'MUTATION', false, true, true, true, true, 'MEDIUM', 'IMPLEMENTED',
       'app.services.payroll_service.pay_employee_salary via tools._pay_employee_salary'
where not exists (select 1 from ai.tools x where x.slug = 'pay_employee_salary');

-- ---- 2. ai.tool_parameters -------------------------------------------------
insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, p.parameter_name, p.description, p.data_type, p.required, p.position
from ai.tools t
join (values
  ('transaction_date',           'Payroll date YYYY-MM-DD (also selects the period and which allowance components are in force)', 'string', false, 1),
  ('payment_method',             'ACCRUED (salary owed — credits Accrued Salaries; default) or PAID (money leaves bank/cash now)',   'string', false, 2),
  ('department',                 'Restrict the run to one department (optional)',                                                    'string', false, 3),
  ('payment_account_id',         'Explicit bank/cash account uuid for a PAID run (optional)',                                       'string', false, 4),
  ('salary_expense_account_id',  'Explicit salaries expense account uuid (optional)',                                               'string', false, 5),
  ('accrued_salaries_account_id','Explicit accrued-salaries liability account uuid (optional)',                                     'string', false, 6),
  ('description',                'Journal description override (optional)',                                                         'string', false, 7)
) as p(parameter_name, description, data_type, required, position)
on true
where t.slug = 'run_payroll'
  and not exists (
    select 1 from ai.tool_parameters ep
    where ep.tool_id = t.id and ep.parameter_name = p.parameter_name
  );

insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, p.parameter_name, p.description, p.data_type, p.required, p.position
from ai.tools t
join (values
  ('employee',                   'Employee code (EMP-…), full name or id (mandatory)',                         'string', true,  1),
  ('amount',                     'Explicit net amount to pay — only when the user stated a figure (optional)', 'number', false, 2),
  ('transaction_date',           'Payment date YYYY-MM-DD (optional; defaults to today)',                      'string', false, 3),
  ('payment_account_id',         'Explicit bank/cash account uuid (optional)',                                 'string', false, 4),
  ('accrued_salaries_account_id','Explicit accrued-salaries liability account uuid (optional)',                'string', false, 5),
  ('salary_expense_account_id',  'Explicit salaries expense account uuid (optional)',                          'string', false, 6),
  ('description',                'Journal description override (optional)',                                    'string', false, 7)
) as p(parameter_name, description, data_type, required, position)
on true
where t.slug = 'pay_employee_salary'
  and not exists (
    select 1 from ai.tool_parameters ep
    where ep.tool_id = t.id and ep.parameter_name = p.parameter_name
  );

-- ---- 3. ai.permissions: the payroll capability ------------------------------
-- Same shape 041 used for 'assets': the capability row is derived from an
-- existing one for the SAME agent, so every agent that may run the books may
-- also run payroll (the runtime intersects capabilities with the caller's
-- role: OWNER/ADMIN and accounting:full / ai:full hold it).
insert into ai.permissions (agent_id, capability, allowed_tools, denied_tools, status)
select p.agent_id,
       'payroll',
       '["run_payroll","pay_employee_salary"]'::jsonb,
       '[]'::jsonb,
       'ACTIVE'
from ai.permissions p
where p.capability = 'master_data'
  and not exists (select 1 from ai.permissions where capability = 'payroll');

