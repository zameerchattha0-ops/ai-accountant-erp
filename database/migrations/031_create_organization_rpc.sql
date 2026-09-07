-- =========================================================================
-- Migration 031: create_organization RPC for the Onboarding Wizard
-- Date: 2026-08-29 (applied live via Supabase MCP; mirrored here)
--
-- The frontend onboarding wizard calls this single atomic function instead of
-- issuing 7 client-side inserts. Needed because the organization_members
-- INSERT policy (is_org_member) prevents a brand-new user from adding their
-- own OWNER membership to a freshly created organization (chicken-and-egg).
--
-- SECURITY DEFINER is safe here because the only user-derived input is
-- auth.uid() (used verbatim as the OWNER member); all other parameters are
-- plain data validated by column constraints.
--
-- Creates: organizations row, OWNER membership (ACTIVE), organization_settings,
-- organization_onboarding, first financial_year + 12 monthly accounting_periods,
-- and the chart of accounts copied from the matching account_templates row.
-- =========================================================================

CREATE OR REPLACE FUNCTION public.create_organization(
  p_name text,
  p_business_type public.business_type_code DEFAULT 'OTHER',
  p_base_currency_code char(3) DEFAULT 'PKR',
  p_country_code char(2) DEFAULT 'PK',
  p_timezone text DEFAULT 'Asia/Karachi',
  p_fiscal_year_end_month smallint DEFAULT 6,
  p_legal_name text DEFAULT NULL,
  p_tax_number text DEFAULT NULL,
  p_registration_number text DEFAULT NULL,
  p_core_services text DEFAULT NULL,
  p_industry_details text DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_user_id uuid := auth.uid();
  v_org_id uuid;
  v_fy_id uuid;
  v_template_id uuid;
  v_start_month int;
  v_start date;
  v_end date;
  v_year int;
  v_month int;
  v_owner_role_id uuid;
  v_slug text;
  v_suffix text;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;
  IF p_name IS NULL OR length(trim(p_name)) < 2 THEN
    RAISE EXCEPTION 'Organization name must be at least 2 characters';
  END IF;

  -- Unique slug: name-derived + random suffix
  v_slug := lower(regexp_replace(trim(p_name), '[^a-zA-Z0-9]+', '-', 'g'));
  v_slug := regexp_replace(v_slug, '^-+|-+$', '', 'g');
  IF v_slug = '' OR length(v_slug) < 2 THEN v_slug := 'org'; END IF;
  v_suffix := substr(replace(gen_random_uuid()::text, '-', ''), 1, 6);
  v_slug := left(v_slug, 40) || '-' || v_suffix;

  -- 1. Organization
  INSERT INTO public.organizations (name, slug, legal_name, business_type,
                                    tax_number, registration_number,
                                    base_currency_code, country_code, timezone,
                                    fiscal_year_end_month)
  VALUES (trim(p_name), v_slug, p_legal_name, p_business_type,
          p_tax_number, p_registration_number,
          p_base_currency_code, p_country_code, p_timezone,
          p_fiscal_year_end_month)
  RETURNING id INTO v_org_id;

  -- 2. OWNER membership (ACTIVE) — the reason this function exists
  SELECT id INTO v_owner_role_id FROM public.organization_roles
  WHERE code = 'OWNER' LIMIT 1;
  IF v_owner_role_id IS NULL THEN
    RAISE EXCEPTION 'OWNER role not found in organization_roles';
  END IF;
  INSERT INTO public.organization_members (organization_id, user_id, role_id, status, joined_at)
  VALUES (v_org_id, v_user_id, v_owner_role_id, 'ACTIVE', now());

  -- 3. Organization settings (default document prefixes)
  INSERT INTO public.organization_settings (organization_id, invoice_prefix,
      quotation_prefix, bill_prefix, credit_note_prefix, journal_prefix,
      payment_prefix, receipt_prefix, customer_prefix, supplier_prefix,
      project_prefix, expense_prefix, asset_prefix, return_prefix,
      default_payment_terms_days, settings)
  VALUES (v_org_id, 'INV', 'QUT', 'BIL', 'CRN', 'JV', 'PAY', 'RCT',
      'CUS', 'SUP', 'PRJ', 'EXP', 'AST', 'RET', 30,
      jsonb_build_object('invoice_template', 'modern'));

  -- 4. Onboarding record
  INSERT INTO public.organization_onboarding (organization_id, business_type,
      core_services, industry_details, recommended_accounts_generated,
      onboarding_completed_at)
  VALUES (v_org_id, p_business_type, p_core_services, p_industry_details,
      false, now());

  -- 5. First financial year + 12 monthly periods
  v_start_month := (p_fiscal_year_end_month % 12) + 1;
  v_year := extract(year from current_date)::int;
  IF v_start_month > extract(month from current_date)::int THEN
    v_year := v_year - 1;
  END IF;
  v_start := make_date(v_year, v_start_month, 1);
  v_end := (v_start + interval '1 year - 1 day')::date;

  INSERT INTO public.financial_years (organization_id, name, start_date, end_date,
                                      status, is_current)
  VALUES (v_org_id,
          'FY ' || to_char(v_start, 'YYYY') || '-' || to_char(v_end, 'YY'),
          v_start, v_end, 'OPEN', true)
  RETURNING id INTO v_fy_id;

  FOR v_month IN 0..11 LOOP
    INSERT INTO public.accounting_periods (organization_id, financial_year_id,
        period_number, name, start_date, end_date, status)
    VALUES (v_org_id, v_fy_id, v_month + 1,
            to_char(v_start + (v_month || ' months')::interval, 'Month YYYY'),
            (v_start + (v_month || ' months')::interval)::date,
            (v_start + ((v_month + 1) || ' months')::interval)::date - 1,
            'OPEN');
  END LOOP;

  -- 6. Chart of accounts from the matching template (exact business_type
  --    match, else the GENERAL_SERVICE fallback, else the first active)
  SELECT t.id INTO v_template_id
  FROM public.account_templates t
  WHERE t.is_active
  ORDER BY (t.business_type = p_business_type) DESC,
           (t.code = 'GENERAL_SERVICE') DESC,
           t.created_at
  LIMIT 1;

  IF v_template_id IS NOT NULL THEN
    INSERT INTO public.accounts (organization_id, code, name, account_type,
                                 normal_balance, is_system, is_active, description)
    SELECT v_org_id, ti.code, ti.name, ti.account_type,
           CASE WHEN ti.account_type IN ('ASSET','EXPENSE')
                THEN 'DEBIT'::public.normal_balance_code
                ELSE 'CREDIT'::public.normal_balance_code END,
           false, true,
           'Seeded from ' || (SELECT name FROM public.account_templates WHERE id = v_template_id)
    FROM public.account_template_items ti
    WHERE ti.template_id = v_template_id;

    UPDATE public.organization_onboarding
    SET recommended_accounts_generated = true
    WHERE organization_id = v_org_id;
  END IF;

  RETURN v_org_id;
END $$;

REVOKE ALL ON FUNCTION public.create_organization(text, public.business_type_code,
  char(3), char(2), text, smallint, text, text, text, text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_organization(text, public.business_type_code,
  char(3), char(2), text, smallint, text, text, text, text, text) TO authenticated;
