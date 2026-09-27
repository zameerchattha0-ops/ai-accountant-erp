-- ============================================================================
-- 085 â€” Seed the Employees tools in the AI control plane
-- ============================================================================
-- Four tools (worker: app/tools/__init__.py):
--   search_employee / get_employee     QUERY   master_data
--   create_employee / set_employee_allowances MUTATION master_data
-- Without these rows the runtime authorize_tool() gate denies the slugs.
-- The LLM structures the user's natural-language allowance sentence into the
-- set_employee_allowances `allowances` argument; Python validates each entry
-- (amount numeric, frequency enum, effective date) and executes.
-- Idempotent: guarded by NOT EXISTS / @> checks.
-- ============================================================================

-- ---- 1. ai.tools ------------------------------------------------------------
insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
                      read_only, requires_confirmation, requires_validation,
                      requires_accounting_engine, organization_scoped,
                      risk_level, status, implementation_reference)
select 'Search Employee', 'search_employee',
       'Search employees by name, code, department or designation',
       'Find an employee record in natural language',
       (select module_id from ai.tools where slug = 'create_customer' limit 1),
       'QUERY', true, false, false, false, true, 'LOW', 'IMPLEMENTED',
       'app.services.employee_service.search via tools._search_employee'
where not exists (select 1 from ai.tools x where x.slug = 'search_employee');

insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
                      read_only, requires_confirmation, requires_validation,
                      requires_accounting_engine, organization_scoped,
                      risk_level, status, implementation_reference)
select 'Get Employee', 'get_employee',
       'Get one employee''s full details plus their allowance records',
       'Show an employee record and its allowances',
       (select module_id from ai.tools where slug = 'create_customer' limit 1),
       'QUERY', true, false, false, false, true, 'LOW', 'IMPLEMENTED',
       'app.services.employee_service.get via tools._get_employee'
where not exists (select 1 from ai.tools x where x.slug = 'get_employee');

insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
                      read_only, requires_confirmation, requires_validation,
                      requires_accounting_engine, organization_scoped,
                      risk_level, status, implementation_reference)
select 'Create Employee', 'create_employee',
       'Create an employee record. Mandatory: full_name, date_of_joining, basic_salary. Every other detail is optional and can be added later',
       'Record a new employee',
       (select module_id from ai.tools where slug = 'create_customer' limit 1),
       'MUTATION', false, false, true, false, true, 'LOW', 'IMPLEMENTED',
       'app.services.employee_service.create via tools._create_employee'
where not exists (select 1 from ai.tools x where x.slug = 'create_employee');

insert into ai.tools (name, slug, description, purpose, module_id, tool_type,
                      read_only, requires_confirmation, requires_validation,
                      requires_accounting_engine, organization_scoped,
                      risk_level, status, implementation_reference)
select 'Set Employee Allowances', 'set_employee_allowances',
       'Record an employee''s allowances/benefits. The LLM structures the user''s natural-language sentence into allowances=[{description, amount, frequency, effective_from, allowance_type}]; Python validates every entry (numeric amount, MONTHLY|ONE_TIME|ANNUAL, parseable date) and writes one row per component with the raw sentence kept for audit',
       'Record allowances (rent, fuel, medical, â€¦) for an employee',
       (select module_id from ai.tools where slug = 'create_customer' limit 1),
       'MUTATION', false, false, true, false, true, 'LOW', 'IMPLEMENTED',
       'app.services.employee_service.set_allowances via tools._set_employee_allowances'
where not exists (select 1 from ai.tools x where x.slug = 'set_employee_allowances');

-- ---- 2. ai.tool_parameters (the model's parameter contract) -----------------
insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, p.parameter_name, p.description, p.data_type, p.required, p.position
from ai.tools t
join (values
  ('query', 'Name, code, department or designation to search for', 'string', true,  1),
  ('limit', 'Maximum rows to return (default 25)',                   'number', false, 2)
) as p(parameter_name, description, data_type, required, position)
on true
where t.slug = 'search_employee'
  and not exists (
    select 1 from ai.tool_parameters ep
    where ep.tool_id = t.id and ep.parameter_name = p.parameter_name
  );

insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, p.parameter_name, p.description, p.data_type, p.required, p.position
from ai.tools t
join (values
  ('employee',    'Employee code (EMP-â€¦), full name or id', 'string', true,  1),
  ('employee_id', 'Exact employee uuid when already known',  'string', false, 2)
) as p(parameter_name, description, data_type, required, position)
on true
where t.slug = 'get_employee'
  and not exists (
    select 1 from ai.tool_parameters ep
    where ep.tool_id = t.id and ep.parameter_name = p.parameter_name
  );

insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, p.parameter_name, p.description, p.data_type, p.required, p.position
from ai.tools t
join (values
  ('full_name',           'Employee full name (mandatory)',                  'string', true,  1),
  ('date_of_joining',     'Joining date YYYY-MM-DD (mandatory)',             'string', true,  2),
  ('basic_salary',        'Monthly basic salary (mandatory, > 0)',           'number', true,  3),
  ('designation',         'Job title',                                       'string', false, 4),
  ('department',          'Department',                                      'string', false, 5),
  ('employment_type',     'FULL_TIME | PART_TIME | CONTRACT | INTERN',       'string', false, 6),
  ('cnic',                'National id number',                              'string', false, 7),
  ('phone',               'Contact phone',                                   'string', false, 8),
  ('email',               'Contact email',                                   'string', false, 9),
  ('address',             'Address',                                         'string', false, 10),
  ('bank_name',           'Bank name',                                       'string', false, 11),
  ('bank_account_number', 'Bank account / IBAN',                             'string', false, 12),
  ('tax_number',          'Tax / NTN number',                                'string', false, 13),
  ('pay_day',             'Salary pay day of month (1-31)',                  'number', false, 14),
  ('notes',               'Free notes',                                      'string', false, 15)
) as p(parameter_name, description, data_type, required, position)
on true
where t.slug = 'create_employee'
  and not exists (
    select 1 from ai.tool_parameters ep
    where ep.tool_id = t.id and ep.parameter_name = p.parameter_name
  );

insert into ai.tool_parameters (tool_id, parameter_name, description, data_type, required, position)
select t.id, p.parameter_name, p.description, p.data_type, p.required, p.position
from ai.tools t
join (values
  ('employee',       'Employee code (EMP-â€¦), full name or id', 'string', true,  1),
  ('allowances',     'Structured list the LLM composed from the user''s sentence: [{description, amount, frequency, allowance_type, effective_from}]', 'array', true, 2),
  ('raw_text',       'The user''s original natural-language sentence (kept for audit)', 'string', false, 3),
  ('effective_from', 'Default start date YYYY-MM-DD for every component when not per-entry', 'string', false, 4)
) as p(parameter_name, description, data_type, required, position)
on true
where t.slug = 'set_employee_allowances'
  and not exists (
    select 1 from ai.tool_parameters ep
    where ep.tool_id = t.id and ep.parameter_name = p.parameter_name
  );

-- ---- 3. ai.permissions: master_data may use the Employees tools -------------
update ai.permissions
set allowed_tools = (
      select jsonb_agg(distinct elem)
      from jsonb_array_elements(
        allowed_tools || '["search_employee","get_employee","create_employee","set_employee_allowances"]'::jsonb
      ) as elem
    ),
    updated_at = now()
where capability = 'master_data'
  and not (allowed_tools @> '["create_employee"]'::jsonb);

