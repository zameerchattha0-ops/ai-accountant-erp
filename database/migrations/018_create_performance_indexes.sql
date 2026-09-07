-- Migration: create_performance_indexes
-- Standalone performance indexes (constraint-backed indexes live with their tables).
-- Fuzzy-search GIN indexes require the pg_trgm extension (created in migration 001).

-- ---- Chart of accounts ----
create index idx_accounts_org         on accounts (organization_id);
create index idx_accounts_org_type    on accounts (organization_id, account_type);
create index idx_accounts_org_active  on accounts (organization_id, is_active);
create index idx_accounts_parent      on accounts (parent_account_id);
create index idx_accounts_name_trgm   on accounts using gin (name gin_trgm_ops);

-- ---- Parties ----
create index idx_customers_org         on customers (organization_id);
create index idx_customers_org_active  on customers (organization_id, is_active);
create unique index uq_customers_org_name on customers (organization_id, lower(name));
create index idx_customers_name_trgm   on customers using gin (name gin_trgm_ops);
create index idx_customer_contacts_cust    on customer_contacts (customer_id);
create index idx_customer_addresses_cust   on customer_addresses (customer_id);
create index idx_suppliers_org         on suppliers (organization_id);
create index idx_suppliers_org_active  on suppliers (organization_id, is_active);
create unique index uq_suppliers_org_name on suppliers (organization_id, lower(name));
create index idx_suppliers_name_trgm   on suppliers using gin (name gin_trgm_ops);
create index idx_supplier_contacts_sup    on supplier_contacts (supplier_id);
create index idx_supplier_addresses_sup   on supplier_addresses (supplier_id);

-- ---- Projects ----
create index idx_projects_org         on projects (organization_id);
create index idx_projects_org_status  on projects (organization_id, status);
create index idx_projects_customer    on projects (organization_id, customer_id);
create index idx_projects_name_trgm   on projects using gin (name gin_trgm_ops);
create index idx_project_milestones_proj on project_milestones (project_id);

-- ---- Products & services ----
create index idx_products_org        on products (organization_id);
create index idx_products_name_trgm  on products using gin (name gin_trgm_ops);
create index idx_services_org        on services (organization_id);
create index idx_services_name_trgm  on services using gin (name gin_trgm_ops);

-- ---- Journal engine ----
create index idx_journal_entries_org_date    on journal_entries (organization_id, transaction_date desc);
create index idx_journal_entries_org_status  on journal_entries (organization_id, status);
create index idx_journal_entries_period      on journal_entries (accounting_period_id);
create index idx_journal_entries_source      on journal_entries (organization_id, source_type, source_id);
create index idx_journal_lines_account       on journal_lines (account_id);
create index idx_journal_lines_org_account   on journal_lines (organization_id, account_id);
create index idx_journal_lines_customer      on journal_lines (organization_id, customer_id);
create index idx_journal_lines_supplier      on journal_lines (organization_id, supplier_id);
create index idx_journal_lines_project       on journal_lines (organization_id, project_id);

-- ---- Sales ----
create index idx_quotations_org           on quotations (organization_id);
create index idx_quotations_org_customer  on quotations (organization_id, customer_id);
create index idx_quotation_items_quote    on quotation_items (quotation_id);
create index idx_invoices_org             on invoices (organization_id);
create index idx_invoices_org_status      on invoices (organization_id, status);
create index idx_invoices_org_customer    on invoices (organization_id, customer_id);
create index idx_invoices_org_date        on invoices (organization_id, invoice_date desc);
create index idx_invoices_due             on invoices (organization_id, due_date)
  where status in ('ISSUED','PARTIALLY_PAID','OVERDUE');
create index idx_invoice_items_invoice    on invoice_items (invoice_id);
create index idx_credit_notes_org         on credit_notes (organization_id);
create index idx_credit_notes_org_customer on credit_notes (organization_id, customer_id);
create index idx_credit_note_items_note   on credit_note_items (credit_note_id);

-- ---- Purchases & expenses ----
create index idx_purchase_bills_org            on purchase_bills (organization_id);
create index idx_purchase_bills_org_status     on purchase_bills (organization_id, status);
create index idx_purchase_bills_org_supplier   on purchase_bills (organization_id, supplier_id);
create index idx_purchase_bills_org_date       on purchase_bills (organization_id, bill_date desc);
create index idx_purchase_bills_due            on purchase_bills (organization_id, due_date)
  where status in ('OPEN','PARTIALLY_PAID','OVERDUE');
create index idx_purchase_bill_items_bill      on purchase_bill_items (bill_id);
create index idx_purchase_returns_org          on purchase_returns (organization_id);
create index idx_purchase_return_items_ret     on purchase_return_items (return_id);
create index idx_expenses_org                  on expenses (organization_id);
create index idx_expenses_org_date             on expenses (organization_id, expense_date desc);
create index idx_expense_items_expense         on expense_items (expense_id);

-- ---- Fixed assets ----
create index idx_fixed_assets_org         on fixed_assets (organization_id);
create index idx_fixed_assets_org_status  on fixed_assets (organization_id, status);
create index idx_asset_dep_schedules_asset on asset_depreciation_schedules (asset_id);
create index idx_asset_transactions_asset  on asset_transactions (asset_id);

-- ---- Banking ----
create index idx_bank_accounts_org              on bank_accounts (organization_id);
create index idx_cash_accounts_org              on cash_accounts (organization_id);
create index idx_bank_transactions_org          on bank_transactions (organization_id, transaction_date desc);
create index idx_bank_transactions_account      on bank_transactions (bank_account_id, transaction_date desc);
create index idx_bank_transactions_status       on bank_transactions (organization_id, status);
create index idx_bank_statement_lines_import    on bank_statement_lines (import_id);

-- ---- Payments & receipts ----
create index idx_payments_org            on payments (organization_id);
create index idx_payments_org_supplier   on payments (organization_id, supplier_id);
create index idx_payment_allocations_pay on payment_allocations (payment_id);
create index idx_payment_allocations_bill on payment_allocations (bill_id);
create index idx_receipts_org            on receipts (organization_id);
create index idx_receipts_org_customer   on receipts (organization_id, customer_id);
create index idx_receipt_allocations_rcpt on receipt_allocations (receipt_id);
create index idx_receipt_allocations_inv  on receipt_allocations (invoice_id);

-- ---- Taxes & documents ----
create index idx_tax_transactions_org     on tax_transactions (organization_id, transaction_date desc);
create index idx_tax_transactions_source  on tax_transactions (source_type, source_id);
create index idx_documents_org            on documents (organization_id);
create index idx_document_links_doc       on document_links (document_id);
create index idx_document_links_entity    on document_links (organization_id, entity_type, entity_id);

-- ---- AI & reporting ----
create index idx_ai_requests_org         on ai_requests (organization_id, created_at desc);
create index idx_ai_tool_calls_request   on ai_tool_calls (ai_request_id);
create index idx_ai_actions_request      on ai_execution_actions (ai_request_id);
create index idx_report_requests_org     on report_requests (organization_id, created_at desc);
