-- =========================================================================
-- Migration 030: Expose ai schema to PostgREST + seed test organization
-- Date: 2026-08-29 (applied live via Supabase MCP; mirrored here)
--
-- Root cause fixed: the ai.* Control Plane tables were unreachable through
-- the Supabase REST API (PGRST106 "Invalid schema: ai" / PGRST205 schema
-- cache / 42501 permission denied). Three things were needed:
--   1. Expose the ai schema in the PostgREST schema list
--   2. Reload the PostgREST schema cache
--   3. GRANT USAGE + table privileges to service_role (the backend connects
--      with the service-role key; security hardening had revoked schema
--      access without re-granting to service_role)
--
-- Security note: all 20 ai.* tables have RLS enabled, so anon/authenticated
-- REST clients remain filtered by RLS. Only service_role bypasses RLS.
-- =========================================================================

-- 1. Expose the ai schema to the auto-generated API ------------------------
ALTER ROLE authenticator SET pgrst.db_schemas = 'public, graphql_public, ai';

-- 2. Service-role access (least privilege: service_role only) --------------
GRANT USAGE ON SCHEMA ai TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA ai TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ai TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ai GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ai GRANT USAGE ON SEQUENCES TO service_role;

-- 3. Ask PostgREST to reload config + schema cache --------------------------
-- (These NOTIFY statements are needed at deployment time; they are safe to
--  re-run and are also triggered automatically by Supabase on some deploys.)
NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';

-- =========================================================================
-- Test data seed (idempotent) — enables live end-to-end testing
--   user  00000000-0000-4000-8000-000000000001  test.owner@erptest.local
--         (password: Test1234!)
--   org   00000000-0000-4000-8000-000000000010  Test Traders (Pvt) Ltd
--   FY    00000000-0000-4000-8000-000000000020  FY 2026 (12 monthly OPEN periods)
--   COA   21 accounts from the IT Services template
-- =========================================================================
DO $$
DECLARE
  v_user_id uuid := '00000000-0000-4000-8000-000000000001';
  v_org_id uuid := '00000000-0000-4000-8000-000000000010';
  v_fy_id uuid := '00000000-0000-4000-8000-000000000020';
  v_owner_role uuid := 'c6bc0316-6c82-4491-a58e-cc0d5efd88cf'; -- OWNER
  v_template_id uuid := '48b969a4-dd60-477e-95d5-20f5384d22e2'; -- IT Services
  v_month int;
  v_start date;
  v_end date;
BEGIN
  -- 1. Test user (password: Test1234!)
  INSERT INTO auth.users (id, instance_id, aud, role, email, encrypted_password,
                          email_confirmed_at, raw_app_meta_data,
                          raw_user_meta_data, created_at, updated_at)
  VALUES (v_user_id, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',
          'test.owner@erptest.local', crypt('Test1234!', gen_salt('bf')),
          now(), '{"provider":"email","providers":["email"]}'::jsonb,
          '{"full_name":"Test Owner"}'::jsonb, now(), now())
  ON CONFLICT (id) DO NOTHING;

  -- 2. Test organization
  INSERT INTO public.organizations (id, name, slug, legal_name, business_type,
                                    base_currency_code, country_code, timezone)
  VALUES (v_org_id, 'Test Traders (Pvt) Ltd', 'test-traders',
          'Test Traders (Private) Limited', 'OTHER', 'PKR', 'PK', 'Asia/Karachi')
  ON CONFLICT (id) DO NOTHING;

  -- 3. OWNER membership (ACTIVE)
  INSERT INTO public.organization_members (id, organization_id, user_id, role_id, status, joined_at)
  VALUES ('00000000-0000-4000-8000-000000000030', v_org_id, v_user_id, v_owner_role, 'ACTIVE', now())
  ON CONFLICT (id) DO NOTHING;

  -- 4. Financial year 2026 + 12 monthly OPEN periods
  INSERT INTO public.financial_years (id, organization_id, name, start_date, end_date, status, is_current)
  VALUES (v_fy_id, v_org_id, 'FY 2026', '2026-01-01', '2026-12-31', 'OPEN', true)
  ON CONFLICT (id) DO NOTHING;

  FOR v_month IN 1..12 LOOP
    v_start := make_date(2026, v_month, 1);
    v_end := (v_start + interval '1 month - 1 day')::date;
    INSERT INTO public.accounting_periods (organization_id, financial_year_id, period_number,
                                           name, start_date, end_date, status)
    SELECT v_org_id, v_fy_id, v_month,
           trim(to_char(v_start, 'Month')) || ' 2026', v_start, v_end, 'OPEN'
    WHERE NOT EXISTS (
      SELECT 1 FROM public.accounting_periods p
      WHERE p.organization_id = v_org_id
        AND p.financial_year_id = v_fy_id
        AND p.period_number = v_month
    );
  END LOOP;

  -- 5. Chart of accounts from the IT Services template
  INSERT INTO public.accounts (organization_id, code, name, account_type, normal_balance,
                               is_system, is_active, description)
  SELECT v_org_id, ti.code, ti.name, ti.account_type,
         CASE WHEN ti.account_type IN ('ASSET','EXPENSE')
              THEN 'DEBIT' ELSE 'CREDIT' END::public.normal_balance_code,
         false, true, 'Seeded from IT Services account template'
  FROM public.account_template_items ti
  WHERE ti.template_id = v_template_id
    AND NOT EXISTS (
      SELECT 1 FROM public.accounts a
      WHERE a.organization_id = v_org_id AND a.code = ti.code
    );
END $$;
