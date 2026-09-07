-- Migration: seed_reference_data
-- Reference data only. NEVER seed demo financial records.
-- Fixed UUIDs keep cross-environment restores consistent.

-- ---- Currencies (PKR default) ----
insert into currencies (code, name, symbol, decimal_places, is_active) values
  ('PKR', 'Pakistani Rupee',  'Rs.', 2, true),
  ('USD', 'US Dollar',        '$',   2, true),
  ('EUR', 'Euro',             '€',   2, true),
  ('GBP', 'Pound Sterling',   '£',   2, true),
  ('AED', 'UAE Dirham',       'د.إ', 2, true),
  ('SAR', 'Saudi Riyal',      '﷼',   2, true),
  ('INR', 'Indian Rupee',     '₹',   2, true),
  ('CNY', 'Chinese Yuan',     '¥',   2, true),
  ('JPY', 'Japanese Yen',     '¥',   0, true),
  ('CAD', 'Canadian Dollar',  'C$',  2, true),
  ('AUD', 'Australian Dollar','A$',  2, true)
on conflict (code) do nothing;

-- ---- Account types (5) ----
insert into account_types (id, code, name, normal_balance, sort_order, description) values
  ('5b0ae03c-ddb4-470a-abd0-c1d67e89df2b', 'ASSET',    'Assets',     'DEBIT',  1, 'Resources controlled by the organization'),
  ('4ce6383e-9af6-4570-85bf-ceb46114d5aa', 'LIABILITY','Liabilities', 'CREDIT', 2, 'Present obligations of the organization'),
  ('d7e32f73-a45e-4dba-9c5d-a6996bf0dd0c', 'EQUITY',   'Equity',      'CREDIT', 3, 'Residual interest in the assets'),
  ('9d561b4e-4d9d-4d41-b1c6-281ab9967627', 'REVENUE',  'Revenue',     'CREDIT', 4, 'Increases in economic benefits'),
  ('25680a5d-fada-45be-9f53-0b5781d687f9', 'EXPENSE',  'Expenses',    'DEBIT',  5, 'Decreases in economic benefits')
on conflict (code) do nothing;

-- ---- Account categories (26) ----
insert into account_categories (code, name, description, account_type_id)
select v.code, v.name, v.description, at.id
from (values
  ('RECEIVABLE',         'Accounts Receivable',    'Amounts due from customers',              'ASSET'),
  ('BANK',               'Bank',                   'Bank accounts',                           'ASSET'),
  ('CASH',               'Cash',                   'Cash on hand and petty cash',             'ASSET'),
  ('FIXED_ASSET',        'Fixed Assets',           'Long-lived tangible assets',              'ASSET'),
  ('ACCUM_DEPRECIATION', 'Accumulated Depreciation','Contra-asset for depreciation',          'ASSET'),
  ('PREPAID',            'Prepaid Expenses',       'Payments made in advance',                'ASSET'),
  ('INVENTORY',          'Inventory',              'Goods held for sale (only where applicable)','ASSET'),
  ('OTHER_ASSET',        'Other Assets',           'Miscellaneous assets',                    'ASSET'),
  ('PAYABLE',            'Accounts Payable',       'Amounts due to suppliers',                'LIABILITY'),
  ('TAX_PAYABLE',        'Taxes Payable',          'Sales and withholding taxes owed',        'LIABILITY'),
  ('ACCRUED',            'Accrued Expenses',       'Expenses incurred but unpaid',            'LIABILITY'),
  ('UNEARNED_REVENUE',   'Unearned Revenue',       'Payments received in advance',            'LIABILITY'),
  ('LOAN',               'Loans',                  'Borrowed funds',                          'LIABILITY'),
  ('CREDIT_CARD',        'Credit Cards',           'Card balances',                           'LIABILITY'),
  ('OTHER_LIABILITY',    'Other Liabilities',      'Miscellaneous liabilities',               'LIABILITY'),
  ('OWNER_CAPITAL',      'Owner Capital',          'Contributions by owners',                 'EQUITY'),
  ('RETAINED_EARNINGS',  'Retained Earnings',      'Accumulated profits',                     'EQUITY'),
  ('DRAWINGS',           'Drawings',               'Distributions to owners',                 'EQUITY'),
  ('OPERATING_REVENUE',  'Operating Revenue',      'Revenue from core operations',            'REVENUE'),
  ('OTHER_INCOME',       'Other Income',           'Non-operating income',                    'REVENUE'),
  ('COGS',               'Cost of Sales',          'Direct costs of goods/services sold',     'EXPENSE'),
  ('PAYROLL',            'Payroll',                'Salaries, wages and freelancers',         'EXPENSE'),
  ('OPERATING_EXPENSE',  'Operating Expenses',     'General operating costs',                 'EXPENSE'),
  ('DEPRECIATION_EXPENSE','Depreciation',          'Allocated cost of fixed assets',          'EXPENSE'),
  ('TAX_EXPENSE',        'Tax Expense',            'Income taxes',                            'EXPENSE'),
  ('OTHER_EXPENSE',      'Other Expenses',         'Non-operating expenses',                  'EXPENSE')
) as v(code, name, description, account_type_code)
join account_types at on at.code = v.account_type_code
on conflict do nothing;

-- ---- Organization roles (5) ----
insert into organization_roles (id, code, name, description, rank, permissions) values
  ('c6bc0316-6c82-4491-a58e-cc0d5efd88cf', 'OWNER',      'Owner',       'Full control of the organization',                    1,
   '["org:manage","members:manage","billing:manage","accounting:full","documents:full","ai:full","settings:full"]'),
  ('b64dd7a3-0215-4da5-b7bf-348cb08fc6a8', 'ADMIN',      'Administrator','Administrative management of the organization',      2,
   '["org:manage","members:manage","accounting:full","documents:full","ai:full","settings:full"]'),
  ('dca46461-74ff-4e66-b6e7-f9e159169a8e', 'ACCOUNTANT', 'Accountant',  'Accounting operations and period management',          3,
   '["accounting:full","documents:full","ai:full","reports:full"]'),
  ('2e562c55-c791-485a-abad-319d63db7a1b', 'MANAGER',    'Manager',     'Business operations, sales and purchases',             4,
   '["customers:manage","suppliers:manage","sales:manage","purchases:manage","projects:manage","reports:read"]'),
  ('f8839fe5-c5e1-4c3e-9b49-8f690f40158c', 'VIEWER',     'Viewer',      'Read-only access',                                     5,
   '["reports:read"]')
on conflict (code) do nothing;

-- ---- Tax categories & taxes ----
insert into tax_categories (id, code, name, description) values
  ('ff088e33-8ac7-4daa-a20d-44c9e2d4040f', 'SALES_TAX',       'Sales Tax / GST',  'Goods and services tax collected on sales'),
  ('dc14b948-91e0-42a1-9a49-6a3185814e93', 'WITHHOLDING_TAX','Withholding Tax', 'Tax withheld on payments'),
  ('2a0354b6-3bc2-496b-b503-3dc1dd638616', 'INCOME_TAX',      'Income Tax',      'Tax on business income')
on conflict (code) do nothing;

insert into taxes (name, description, tax_category_id, is_active)
select v.name, v.description, tc.id, true
from (values
  ('Sales Tax (GST)',   'Standard sales tax on goods and services', 'SALES_TAX'),
  ('Withholding Tax',   'Tax withheld at source on payments',       'WITHHOLDING_TAX'),
  ('Income Tax',        'Corporate/business income tax',            'INCOME_TAX')
) as v(name, description, category_code)
join tax_categories tc on tc.code = v.category_code
on conflict do nothing;

insert into tax_rates (tax_id, name, rate_percent, is_default, is_active, effective_from)
select t.id, v.name, v.rate_percent, v.is_default, true, date '2019-07-01'
from (values
  ('Sales Tax (GST)',   'Standard Rate 17%', 17, true),
  ('Sales Tax (GST)',   'Reduced Rate 5%',    5, false),
  ('Sales Tax (GST)',   'Zero Rated 0%',      0, false),
  ('Withholding Tax',   'WHT on Services 8%', 8, false),
  ('Withholding Tax',   'WHT on Imports 6%',  6, false),
  ('Income Tax',        'Corporate 29%',     29, false)
) as v(tax_name, name, rate_percent, is_default)
join taxes t on t.name = v.tax_name
on conflict do nothing;

-- ---- Account templates (7) ----
insert into account_templates (id, code, name, business_type, description, is_active) values
  ('1437a385-dc51-49ea-a1ef-e14cc72b5b41', 'SOFTWARE_HOUSE',  'Software House',           'SOFTWARE_HOUSE',        'Technology businesses building custom software and apps', true),
  ('04007f02-5e12-4d47-b4be-ecc494d202f1', 'SAAS_STARTUP',   'SaaS Startup',             'SAAS_STARTUP',          'Subscription software businesses', true),
  ('48b969a4-dd60-477e-95d5-20f5384d22e2', 'IT_SERVICES',    'IT Services Company',      'IT_SERVICES',           'IT support, infrastructure and managed services', true),
  ('34a60347-5ded-4aec-804c-8fcdebf689bb', 'DIGITAL_AGENCY', 'Digital Agency',           'DIGITAL_AGENCY',        'Creative and marketing agencies', true),
  ('59dbc26a-a84d-4f8b-9599-e3db4e0e23a4', 'TECH_CONSULTANT','Technology Consultant',    'TECHNOLOGY_CONSULTANT', 'Independent technology consultants', true),
  ('e76777ff-3427-4797-950a-b1c24b64ef98', 'FREELANCER',     'Freelancer',               'FREELANCER',            'Solo professionals and freelancers', true),
  ('1285b08f-964c-491b-8c4e-8c94a5581e55', 'GENERAL_SERVICE','General Service Business',  'OTHER',                 'Baseline chart for small service businesses', true)
on conflict (code) do nothing;

-- ---- Account template items (148) ----
insert into account_template_items (template_id, code, name, account_type, account_category_id, suggested_parent_code, sort_order)
select tp.id, v.code, v.name, v.account_type::account_type_code, ac.id, v.parent_code, v.sort_order
from (values
  -- ===== SOFTWARE_HOUSE (23) =====
  ('SOFTWARE_HOUSE','1010','Bank','ASSET','BANK',null,1),
  ('SOFTWARE_HOUSE','1020','Cash','ASSET','CASH',null,2),
  ('SOFTWARE_HOUSE','1100','Accounts Receivable','ASSET','RECEIVABLE',null,3),
  ('SOFTWARE_HOUSE','1300','Prepaid Expenses','ASSET','PREPAID',null,4),
  ('SOFTWARE_HOUSE','1500','Computer Equipment','ASSET','FIXED_ASSET',null,5),
  ('SOFTWARE_HOUSE','1510','Accumulated Depreciation - Computer Equipment','ASSET','ACCUM_DEPRECIATION','1500',6),
  ('SOFTWARE_HOUSE','2010','Accounts Payable','LIABILITY','PAYABLE',null,7),
  ('SOFTWARE_HOUSE','2110','Sales Tax Payable','LIABILITY','TAX_PAYABLE',null,8),
  ('SOFTWARE_HOUSE','2130','Accrued Salaries','LIABILITY','ACCRUED',null,9),
  ('SOFTWARE_HOUSE','3010','Owner Capital','EQUITY','OWNER_CAPITAL',null,10),
  ('SOFTWARE_HOUSE','3200','Retained Earnings','EQUITY','RETAINED_EARNINGS',null,11),
  ('SOFTWARE_HOUSE','4010','Software Development Revenue','REVENUE','OPERATING_REVENUE',null,12),
  ('SOFTWARE_HOUSE','4020','Consulting Revenue','REVENUE','OPERATING_REVENUE',null,13),
  ('SOFTWARE_HOUSE','4030','Maintenance Revenue','REVENUE','OPERATING_REVENUE',null,14),
  ('SOFTWARE_HOUSE','4900','Other Income','REVENUE','OTHER_INCOME',null,15),
  ('SOFTWARE_HOUSE','6010','Salaries','EXPENSE','PAYROLL',null,16),
  ('SOFTWARE_HOUSE','6020','Freelancers','EXPENSE','PAYROLL',null,17),
  ('SOFTWARE_HOUSE','6100','Cloud Infrastructure','EXPENSE','OPERATING_EXPENSE',null,18),
  ('SOFTWARE_HOUSE','6110','Software Subscriptions','EXPENSE','OPERATING_EXPENSE',null,19),
  ('SOFTWARE_HOUSE','6120','Internet','EXPENSE','OPERATING_EXPENSE',null,20),
  ('SOFTWARE_HOUSE','6130','Office Expenses','EXPENSE','OPERATING_EXPENSE',null,21),
  ('SOFTWARE_HOUSE','6200','Depreciation Expense','EXPENSE','DEPRECIATION_EXPENSE',null,22),
  ('SOFTWARE_HOUSE','6300','Bank Charges','EXPENSE','OTHER_EXPENSE',null,23),
  -- ===== SAAS_STARTUP (22) =====
  ('SAAS_STARTUP','1010','Bank','ASSET','BANK',null,1),
  ('SAAS_STARTUP','1020','Cash','ASSET','CASH',null,2),
  ('SAAS_STARTUP','1100','Accounts Receivable','ASSET','RECEIVABLE',null,3),
  ('SAAS_STARTUP','1500','Computer Equipment','ASSET','FIXED_ASSET',null,4),
  ('SAAS_STARTUP','1510','Accumulated Depreciation - Computer Equipment','ASSET','ACCUM_DEPRECIATION','1500',5),
  ('SAAS_STARTUP','2010','Accounts Payable','LIABILITY','PAYABLE',null,6),
  ('SAAS_STARTUP','2110','Sales Tax Payable','LIABILITY','TAX_PAYABLE',null,7),
  ('SAAS_STARTUP','2210','Deferred Revenue','LIABILITY','UNEARNED_REVENUE',null,8),
  ('SAAS_STARTUP','3010','Owner Capital','EQUITY','OWNER_CAPITAL',null,9),
  ('SAAS_STARTUP','3200','Retained Earnings','EQUITY','RETAINED_EARNINGS',null,10),
  ('SAAS_STARTUP','4010','Services Revenue','REVENUE','OPERATING_REVENUE',null,11),
  ('SAAS_STARTUP','4110','Subscription Revenue','REVENUE','OPERATING_REVENUE',null,12),
  ('SAAS_STARTUP','4020','Other Operating Revenue','REVENUE','OPERATING_REVENUE',null,13),
  ('SAAS_STARTUP','4900','Other Income','REVENUE','OTHER_INCOME',null,14),
  ('SAAS_STARTUP','6010','Salaries','EXPENSE','PAYROLL',null,15),
  ('SAAS_STARTUP','6020','Freelancers','EXPENSE','PAYROLL',null,16),
  ('SAAS_STARTUP','6100','Office Expenses','EXPENSE','OPERATING_EXPENSE',null,17),
  ('SAAS_STARTUP','6110','Software Subscriptions','EXPENSE','OPERATING_EXPENSE',null,18),
  ('SAAS_STARTUP','6120','Internet','EXPENSE','OPERATING_EXPENSE',null,19),
  ('SAAS_STARTUP','6130','Cloud Infrastructure','EXPENSE','OPERATING_EXPENSE',null,20),
  ('SAAS_STARTUP','6200','Depreciation Expense','EXPENSE','DEPRECIATION_EXPENSE',null,21),
  ('SAAS_STARTUP','6300','Bank Charges','EXPENSE','OTHER_EXPENSE',null,22),
  -- ===== IT_SERVICES (21) =====
  ('IT_SERVICES','1010','Bank','ASSET','BANK',null,1),
  ('IT_SERVICES','1020','Cash','ASSET','CASH',null,2),
  ('IT_SERVICES','1100','Accounts Receivable','ASSET','RECEIVABLE',null,3),
  ('IT_SERVICES','1500','Computer Equipment','ASSET','FIXED_ASSET',null,4),
  ('IT_SERVICES','1510','Accumulated Depreciation - Computer Equipment','ASSET','ACCUM_DEPRECIATION','1500',5),
  ('IT_SERVICES','2010','Accounts Payable','LIABILITY','PAYABLE',null,6),
  ('IT_SERVICES','2110','Sales Tax Payable','LIABILITY','TAX_PAYABLE',null,7),
  ('IT_SERVICES','3010','Owner Capital','EQUITY','OWNER_CAPITAL',null,8),
  ('IT_SERVICES','3200','Retained Earnings','EQUITY','RETAINED_EARNINGS',null,9),
  ('IT_SERVICES','4010','Services Revenue','REVENUE','OPERATING_REVENUE',null,10),
  ('IT_SERVICES','4050','Managed Services Revenue','REVENUE','OPERATING_REVENUE',null,11),
  ('IT_SERVICES','4020','Other Operating Revenue','REVENUE','OPERATING_REVENUE',null,12),
  ('IT_SERVICES','4900','Other Income','REVENUE','OTHER_INCOME',null,13),
  ('IT_SERVICES','6010','Salaries','EXPENSE','PAYROLL',null,14),
  ('IT_SERVICES','6020','Freelancers','EXPENSE','PAYROLL',null,15),
  ('IT_SERVICES','6100','Office Expenses','EXPENSE','OPERATING_EXPENSE',null,16),
  ('IT_SERVICES','6110','Software Subscriptions','EXPENSE','OPERATING_EXPENSE',null,17),
  ('IT_SERVICES','6120','Internet','EXPENSE','OPERATING_EXPENSE',null,18),
  ('IT_SERVICES','6150','Hardware Purchases','EXPENSE','OPERATING_EXPENSE',null,19),
  ('IT_SERVICES','6200','Depreciation Expense','EXPENSE','DEPRECIATION_EXPENSE',null,20),
  ('IT_SERVICES','6300','Bank Charges','EXPENSE','OTHER_EXPENSE',null,21),
  -- ===== DIGITAL_AGENCY (22) =====
  ('DIGITAL_AGENCY','1010','Bank','ASSET','BANK',null,1),
  ('DIGITAL_AGENCY','1020','Cash','ASSET','CASH',null,2),
  ('DIGITAL_AGENCY','1100','Accounts Receivable','ASSET','RECEIVABLE',null,3),
  ('DIGITAL_AGENCY','1500','Computer Equipment','ASSET','FIXED_ASSET',null,4),
  ('DIGITAL_AGENCY','1510','Accumulated Depreciation - Computer Equipment','ASSET','ACCUM_DEPRECIATION','1500',5),
  ('DIGITAL_AGENCY','2010','Accounts Payable','LIABILITY','PAYABLE',null,6),
  ('DIGITAL_AGENCY','2110','Sales Tax Payable','LIABILITY','TAX_PAYABLE',null,7),
  ('DIGITAL_AGENCY','3010','Owner Capital','EQUITY','OWNER_CAPITAL',null,8),
  ('DIGITAL_AGENCY','3200','Retained Earnings','EQUITY','RETAINED_EARNINGS',null,9),
  ('DIGITAL_AGENCY','4010','Services Revenue','REVENUE','OPERATING_REVENUE',null,10),
  ('DIGITAL_AGENCY','4030','Creative Services Revenue','REVENUE','OPERATING_REVENUE',null,11),
  ('DIGITAL_AGENCY','4040','Media Buying Revenue','REVENUE','OPERATING_REVENUE',null,12),
  ('DIGITAL_AGENCY','4020','Other Operating Revenue','REVENUE','OPERATING_REVENUE',null,13),
  ('DIGITAL_AGENCY','4900','Other Income','REVENUE','OTHER_INCOME',null,14),
  ('DIGITAL_AGENCY','6010','Salaries','EXPENSE','PAYROLL',null,15),
  ('DIGITAL_AGENCY','6020','Freelancers','EXPENSE','PAYROLL',null,16),
  ('DIGITAL_AGENCY','6100','Office Expenses','EXPENSE','OPERATING_EXPENSE',null,17),
  ('DIGITAL_AGENCY','6110','Software Subscriptions','EXPENSE','OPERATING_EXPENSE',null,18),
  ('DIGITAL_AGENCY','6120','Internet','EXPENSE','OPERATING_EXPENSE',null,19),
  ('DIGITAL_AGENCY','6140','Advertising Expenses','EXPENSE','OPERATING_EXPENSE',null,20),
  ('DIGITAL_AGENCY','6200','Depreciation Expense','EXPENSE','DEPRECIATION_EXPENSE',null,21),
  ('DIGITAL_AGENCY','6300','Bank Charges','EXPENSE','OTHER_EXPENSE',null,22),
  -- ===== TECH_CONSULTANT (20) =====
  ('TECH_CONSULTANT','1010','Bank','ASSET','BANK',null,1),
  ('TECH_CONSULTANT','1020','Cash','ASSET','CASH',null,2),
  ('TECH_CONSULTANT','1100','Accounts Receivable','ASSET','RECEIVABLE',null,3),
  ('TECH_CONSULTANT','1500','Computer Equipment','ASSET','FIXED_ASSET',null,4),
  ('TECH_CONSULTANT','1510','Accumulated Depreciation - Computer Equipment','ASSET','ACCUM_DEPRECIATION','1500',5),
  ('TECH_CONSULTANT','2010','Accounts Payable','LIABILITY','PAYABLE',null,6),
  ('TECH_CONSULTANT','2110','Sales Tax Payable','LIABILITY','TAX_PAYABLE',null,7),
  ('TECH_CONSULTANT','3010','Owner Capital','EQUITY','OWNER_CAPITAL',null,8),
  ('TECH_CONSULTANT','3200','Retained Earnings','EQUITY','RETAINED_EARNINGS',null,9),
  ('TECH_CONSULTANT','4010','Services Revenue','REVENUE','OPERATING_REVENUE',null,10),
  ('TECH_CONSULTANT','4060','Advisory Revenue','REVENUE','OPERATING_REVENUE',null,11),
  ('TECH_CONSULTANT','4020','Other Operating Revenue','REVENUE','OPERATING_REVENUE',null,12),
  ('TECH_CONSULTANT','4900','Other Income','REVENUE','OTHER_INCOME',null,13),
  ('TECH_CONSULTANT','6010','Salaries','EXPENSE','PAYROLL',null,14),
  ('TECH_CONSULTANT','6020','Freelancers','EXPENSE','PAYROLL',null,15),
  ('TECH_CONSULTANT','6100','Office Expenses','EXPENSE','OPERATING_EXPENSE',null,16),
  ('TECH_CONSULTANT','6110','Software Subscriptions','EXPENSE','OPERATING_EXPENSE',null,17),
  ('TECH_CONSULTANT','6120','Internet','EXPENSE','OPERATING_EXPENSE',null,18),
  ('TECH_CONSULTANT','6200','Depreciation Expense','EXPENSE','DEPRECIATION_EXPENSE',null,19),
  ('TECH_CONSULTANT','6300','Bank Charges','EXPENSE','OTHER_EXPENSE',null,20),
  -- ===== FREELANCER (21) =====
  ('FREELANCER','1010','Bank','ASSET','BANK',null,1),
  ('FREELANCER','1020','Cash','ASSET','CASH',null,2),
  ('FREELANCER','1100','Accounts Receivable','ASSET','RECEIVABLE',null,3),
  ('FREELANCER','1500','Computer Equipment','ASSET','FIXED_ASSET',null,4),
  ('FREELANCER','1510','Accumulated Depreciation - Computer Equipment','ASSET','ACCUM_DEPRECIATION','1500',5),
  ('FREELANCER','2010','Accounts Payable','LIABILITY','PAYABLE',null,6),
  ('FREELANCER','2110','Sales Tax Payable','LIABILITY','TAX_PAYABLE',null,7),
  ('FREELANCER','3010','Owner Capital','EQUITY','OWNER_CAPITAL',null,8),
  ('FREELANCER','3200','Retained Earnings','EQUITY','RETAINED_EARNINGS',null,9),
  ('FREELANCER','3300','Drawings','EQUITY','DRAWINGS',null,10),
  ('FREELANCER','4010','Services Revenue','REVENUE','OPERATING_REVENUE',null,11),
  ('FREELANCER','4070','Project Revenue','REVENUE','OPERATING_REVENUE',null,12),
  ('FREELANCER','4020','Other Operating Revenue','REVENUE','OPERATING_REVENUE',null,13),
  ('FREELANCER','4900','Other Income','REVENUE','OTHER_INCOME',null,14),
  ('FREELANCER','6010','Salaries','EXPENSE','PAYROLL',null,15),
  ('FREELANCER','6020','Freelancers','EXPENSE','PAYROLL',null,16),
  ('FREELANCER','6100','Office Expenses','EXPENSE','OPERATING_EXPENSE',null,17),
  ('FREELANCER','6110','Software Subscriptions','EXPENSE','OPERATING_EXPENSE',null,18),
  ('FREELANCER','6120','Internet','EXPENSE','OPERATING_EXPENSE',null,19),
  ('FREELANCER','6200','Depreciation Expense','EXPENSE','DEPRECIATION_EXPENSE',null,20),
  ('FREELANCER','6300','Bank Charges','EXPENSE','OTHER_EXPENSE',null,21),
  -- ===== GENERAL_SERVICE (19) =====
  ('GENERAL_SERVICE','1010','Bank','ASSET','BANK',null,1),
  ('GENERAL_SERVICE','1020','Cash','ASSET','CASH',null,2),
  ('GENERAL_SERVICE','1100','Accounts Receivable','ASSET','RECEIVABLE',null,3),
  ('GENERAL_SERVICE','1500','Computer Equipment','ASSET','FIXED_ASSET',null,4),
  ('GENERAL_SERVICE','1510','Accumulated Depreciation - Computer Equipment','ASSET','ACCUM_DEPRECIATION','1500',5),
  ('GENERAL_SERVICE','2010','Accounts Payable','LIABILITY','PAYABLE',null,6),
  ('GENERAL_SERVICE','2110','Sales Tax Payable','LIABILITY','TAX_PAYABLE',null,7),
  ('GENERAL_SERVICE','3010','Owner Capital','EQUITY','OWNER_CAPITAL',null,8),
  ('GENERAL_SERVICE','3200','Retained Earnings','EQUITY','RETAINED_EARNINGS',null,9),
  ('GENERAL_SERVICE','4010','Services Revenue','REVENUE','OPERATING_REVENUE',null,10),
  ('GENERAL_SERVICE','4020','Other Operating Revenue','REVENUE','OPERATING_REVENUE',null,11),
  ('GENERAL_SERVICE','4900','Other Income','REVENUE','OTHER_INCOME',null,12),
  ('GENERAL_SERVICE','6010','Salaries','EXPENSE','PAYROLL',null,13),
  ('GENERAL_SERVICE','6020','Freelancers','EXPENSE','PAYROLL',null,14),
  ('GENERAL_SERVICE','6100','Office Expenses','EXPENSE','OPERATING_EXPENSE',null,15),
  ('GENERAL_SERVICE','6110','Software Subscriptions','EXPENSE','OPERATING_EXPENSE',null,16),
  ('GENERAL_SERVICE','6120','Internet','EXPENSE','OPERATING_EXPENSE',null,17),
  ('GENERAL_SERVICE','6200','Depreciation Expense','EXPENSE','DEPRECIATION_EXPENSE',null,18),
  ('GENERAL_SERVICE','6300','Bank Charges','EXPENSE','OTHER_EXPENSE',null,19)
) as v(template_code, code, name, account_type, category_code, parent_code, sort_order)
join account_templates tp on tp.code = v.template_code
join account_categories ac on ac.code = v.category_code
on conflict do nothing;
