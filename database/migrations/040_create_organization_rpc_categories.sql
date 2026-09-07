-- =====================================================================
-- Migration 040: create_organization RPCs carry account_category_id
-- =====================================================================
-- Both overloads now insert ti.account_category_id when seeding the
-- chart of accounts from business templates (previously dropped, which
-- left every seeded account uncategorised and cash-flow reporting
-- structurally empty).

create or replace function public.create_organization(
  p_name text,
  p_business_type business_type_code default 'OTHER',
  p_base_currency_code character default 'PKR',
  p_country_code character default 'PK',
  p_timezone text default 'Asia/Karachi',
  p_fiscal_year_end_month smallint default 6,
  p_legal_name text default null,
  p_tax_number text default null,
  p_registration_number text default null,
  p_core_services text default null,
  p_industry_details text default null
) returns uuid
language plpgsql security definer
set search_path = public
as $$
DECLARE
  v_user_id uuid := auth.uid();
  v_org_id uuid; v_fy_id uuid; v_template_id uuid;
  v_start_month int; v_start date; v_end date; v_year int; v_month int;
  v_owner_role_id uuid; v_slug text; v_suffix text;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;
  IF p_name IS NULL OR length(trim(p_name)) < 2 THEN
    RAISE EXCEPTION 'Organization name must be at least 2 characters';
  END IF;

  v_slug := lower(regexp_replace(trim(p_name), '[^a-zA-Z0-9]+', '-', 'g'));
  v_slug := regexp_replace(v_slug, '^-+|-+$', '', 'g');
  IF v_slug = '' OR length(v_slug) < 2 THEN v_slug := 'org'; END IF;
  v_suffix := substr(replace(gen_random_uuid()::text, '-', ''), 1, 6);
  v_slug := left(v_slug, 40) || '-' || v_suffix;

  INSERT INTO public.organizations (name, slug, legal_name, business_type,
                                    tax_number, registration_number,
                                    base_currency_code, country_code, timezone,
                                    fiscal_year_end_month)
  VALUES (trim(p_name), v_slug, p_legal_name, p_business_type,
          p_tax_number, p_registration_number,
          p_base_currency_code, p_country_code, p_timezone,
          p_fiscal_year_end_month)
  RETURNING id INTO v_org_id;

  SELECT id INTO v_owner_role_id FROM public.organization_roles
  WHERE code = 'OWNER' LIMIT 1;
  IF v_owner_role_id IS NULL THEN
    RAISE EXCEPTION 'OWNER role not found in organization_roles';
  END IF;
  INSERT INTO public.organization_members (organization_id, user_id, role_id, status, joined_at)
  VALUES (v_org_id, v_user_id, v_owner_role_id, 'ACTIVE', now());

  INSERT INTO public.organization_settings (organization_id, invoice_prefix,
      quotation_prefix, bill_prefix, credit_note_prefix, journal_prefix,
      payment_prefix, receipt_prefix, customer_prefix, supplier_prefix,
      project_prefix, expense_prefix, asset_prefix, return_prefix,
      default_payment_terms_days, settings)
  VALUES (v_org_id, 'INV', 'QUT', 'BIL', 'CRN', 'JV', 'PAY', 'RCT',
      'CUS', 'SUP', 'PRJ', 'EXP', 'AST', 'RET', 30,
      jsonb_build_object('invoice_template', 'modern'));

  INSERT INTO public.organization_onboarding (organization_id, business_type,
      core_services, industry_details, recommended_accounts_generated,
      onboarding_completed_at)
  VALUES (v_org_id, p_business_type, p_core_services, p_industry_details,
      false, now());

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

  SELECT t.id INTO v_template_id
  FROM public.account_templates t
  WHERE t.is_active
  ORDER BY (t.business_type = p_business_type) DESC,
           (t.code = 'GENERAL_SERVICE') DESC,
           t.created_at
  LIMIT 1;

  IF v_template_id IS NOT NULL THEN
    INSERT INTO public.accounts (organization_id, code, name, account_type,
                                 normal_balance, account_category_id,
                                 is_system, is_active, description)
    SELECT v_org_id, ti.code, ti.name, ti.account_type,
           CASE WHEN ti.account_type IN ('ASSET','EXPENSE')
                THEN 'DEBIT'::public.normal_balance_code
                ELSE 'CREDIT'::public.normal_balance_code END,
           ti.account_category_id,
           false, true,
           'Seeded from ' || (SELECT name FROM public.account_templates WHERE id = v_template_id)
    FROM public.account_template_items ti
    WHERE ti.template_id = v_template_id;

    UPDATE public.organization_onboarding
    SET recommended_accounts_generated = true
    WHERE organization_id = v_org_id;
  END IF;

  RETURN v_org_id;
END;
$$;

-- ---- 12-argument overload (with p_fiscal_year_start_year) ------------

create or replace function public.create_organization(
  p_name text,
  p_business_type business_type_code default 'OTHER',
  p_base_currency_code character default 'PKR',
  p_country_code character default 'PK',
  p_timezone text default 'Asia/Karachi',
  p_fiscal_year_end_month smallint default 6,
  p_legal_name text default null,
  p_tax_number text default null,
  p_registration_number text default null,
  p_core_services text default null,
  p_industry_details text default null,
  p_fiscal_year_start_year integer default null
) returns uuid
language plpgsql security definer
set search_path = public
as $$
DECLARE
  v_user_id uuid := auth.uid();
  v_org_id uuid; v_fy_id uuid; v_template_id uuid;
  v_start_month int; v_start date; v_end date; v_year int; v_month int;
  v_owner_role_id uuid; v_slug text; v_suffix text;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;
  IF p_name IS NULL OR length(trim(p_name)) < 2 THEN
    RAISE EXCEPTION 'Organization name must be at least 2 characters';
  END IF;

  v_slug := lower(regexp_replace(trim(p_name), '[^a-zA-Z0-9]+', '-', 'g'));
  v_slug := regexp_replace(v_slug, '^-+|-+$', '', 'g');
  IF v_slug = '' OR length(v_slug) < 2 THEN v_slug := 'org'; END IF;
  v_suffix := substr(replace(gen_random_uuid()::text, '-', ''), 1, 6);
  v_slug := left(v_slug, 40) || '-' || v_suffix;

  INSERT INTO public.organizations (name, slug, legal_name, business_type,
                                    tax_number, registration_number,
                                    base_currency_code, country_code, timezone,
                                    fiscal_year_end_month)
  VALUES (trim(p_name), v_slug, p_legal_name, p_business_type,
          p_tax_number, p_registration_number,
          p_base_currency_code, p_country_code, p_timezone,
          p_fiscal_year_end_month)
  RETURNING id INTO v_org_id;

  SELECT id INTO v_owner_role_id FROM public.organization_roles
  WHERE code = 'OWNER' LIMIT 1;
  IF v_owner_role_id IS NULL THEN
    RAISE EXCEPTION 'OWNER role not found in organization_roles';
  END IF;
  INSERT INTO public.organization_members (organization_id, user_id, role_id, status, joined_at)
  VALUES (v_org_id, v_user_id, v_owner_role_id, 'ACTIVE', now());

  INSERT INTO public.organization_settings (organization_id, invoice_prefix,
      quotation_prefix, bill_prefix, credit_note_prefix, journal_prefix,
      payment_prefix, receipt_prefix, customer_prefix, supplier_prefix,
      project_prefix, expense_prefix, asset_prefix, return_prefix,
      default_payment_terms_days, settings)
  VALUES (v_org_id, 'INV', 'QUT', 'BIL', 'CRN', 'JV', 'PAY', 'RCT',
      'CUS', 'SUP', 'PRJ', 'EXP', 'AST', 'RET', 30,
      jsonb_build_object('invoice_template', 'modern'));

  INSERT INTO public.organization_onboarding (organization_id, business_type,
      core_services, industry_details, recommended_accounts_generated,
      onboarding_completed_at)
  VALUES (v_org_id, p_business_type,
      CASE WHEN p_core_services IS NOT NULL AND trim(p_core_services) != ''
           THEN to_jsonb(ARRAY[p_core_services])
           ELSE '[]'::jsonb END,
      p_industry_details,
      false, now());

  v_start_month := (p_fiscal_year_end_month % 12) + 1;
  IF p_fiscal_year_start_year IS NOT NULL THEN
    v_year := p_fiscal_year_start_year;
  ELSE
    v_year := extract(year from current_date)::int;
    IF v_start_month > extract(month from current_date)::int THEN
      v_year := v_year - 1;
    END IF;
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

  SELECT t.id INTO v_template_id
  FROM public.account_templates t
  WHERE t.is_active
  ORDER BY (t.business_type = p_business_type) DESC,
           (t.code = 'GENERAL_SERVICE') DESC,
           t.created_at
  LIMIT 1;

  IF v_template_id IS NOT NULL THEN
    INSERT INTO public.accounts (organization_id, code, name, account_type,
                                 normal_balance, account_category_id,
                                 is_system, is_active, description)
    SELECT v_org_id, ti.code, ti.name, ti.account_type,
           CASE WHEN ti.account_type IN ('ASSET','EXPENSE')
                THEN 'DEBIT'::public.normal_balance_code
                ELSE 'CREDIT'::public.normal_balance_code END,
           ti.account_category_id,
           false, true,
           'Seeded from ' || (SELECT name FROM public.account_templates WHERE id = v_template_id)
    FROM public.account_template_items ti
    WHERE ti.template_id = v_template_id;

    UPDATE public.organization_onboarding
    SET recommended_accounts_generated = true
    WHERE organization_id = v_org_id;
  END IF;

  RETURN v_org_id;
END;
$$;
