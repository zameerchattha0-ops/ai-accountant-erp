-- Migration: create_rls_policies
-- Tenant isolation via membership helpers (is_org_member / has_org_role),
-- NOT simplistic auth.uid() = user_id. RLS was already enabled on every table
-- (Supabase auto-enables RLS on public tables via its rls_auto_enable event trigger);
-- this migration attaches the policies.

-- ---- Tenant tables: full access scoped to organization membership ----
do $$
declare
  t text;
begin
  foreach t in array array[
    'accounting_periods','accounts','ai_confirmations','ai_execution_actions','ai_execution_plans',
    'ai_execution_results','ai_requests','ai_tool_calls','asset_categories',
    'asset_depreciation_schedules','asset_transactions','bank_accounts','bank_reconciliation_items',
    'bank_reconciliations','bank_statement_imports','bank_statement_lines','bank_transactions',
    'business_account_recommendations','cash_accounts','chart_of_accounts','credit_note_items',
    'credit_notes','customer_addresses','customer_contacts','customers','document_links','documents',
    'expense_categories','expense_items','expenses','financial_years','fixed_assets','generated_reports',
    'invoice_items','invoices','journal_entries','journal_lines','organization_onboarding',
    'organization_settings','payment_allocations','payments','product_categories','products',
    'project_members','project_milestones','project_settings','projects','purchase_bill_items',
    'purchase_bills','purchase_return_items','purchase_returns','quotation_items','quotations',
    'receipt_allocations','receipts','report_requests','service_categories','services',
    'supplier_addresses','supplier_contacts','suppliers','tax_transactions'
  ]
  loop
    execute format(
      'create policy %I on %I for all to authenticated
         using (public.is_org_member(organization_id))
         with check (public.is_org_member(organization_id))',
      t || '_org_access', t
    );
  end loop;
end $$;

-- ---- organizations: membership-based read/update, open insert, owner-only delete ----
create policy org_select on organizations
  for select to authenticated
  using (public.is_org_member(id));

create policy org_update on organizations
  for update to authenticated
  using (public.is_org_member(id))
  with check (public.is_org_member(id));

create policy org_insert on organizations
  for insert to authenticated
  with check (true);

create policy org_delete on organizations
  for delete to authenticated
  using (public.has_org_role(id, 1::smallint));  -- OWNER rank only

-- ---- organization_members: members see own row or any row of an org they belong to ----
create policy members_select on organization_members
  for select to authenticated
  using (user_id = auth.uid() or public.is_org_member(organization_id));

create policy members_update on organization_members
  for update to authenticated
  using (user_id = auth.uid() or public.is_org_member(organization_id))
  with check (user_id = auth.uid() or public.is_org_member(organization_id));

create policy members_insert on organization_members
  for insert to authenticated
  with check (public.is_org_member(organization_id));

create policy members_delete on organization_members
  for delete to authenticated
  using (public.is_org_member(organization_id));

-- ---- audit_logs: append-only via backend; read-only for members ----
create policy audit_logs_select on audit_logs
  for select to authenticated
  using (public.is_org_member(organization_id));

-- ---- Global reference tables: read-only for authenticated ----
do $$
declare
  t text;
begin
  foreach t in array array[
    'account_categories','account_template_items','account_templates','account_types',
    'currencies','exchange_rates','organization_roles','tax_categories','tax_rates','taxes'
  ]
  loop
    execute format(
      'create policy %I on %I for select to authenticated using (true)',
      t || '_read_all', t
    );
  end loop;
end $$;

-- ---- document_sequences: intentionally NO policy ----
-- RLS is enabled with zero policies = deny-all for anon/authenticated.
-- Only the backend service role may read/write the numbering counters;
-- clients must never touch this table directly.
comment on table document_sequences is
  'Concurrent-safe document numbering counters. RLS enabled with NO policy by design: only the backend service role may touch this table; clients must never read or write it.';
