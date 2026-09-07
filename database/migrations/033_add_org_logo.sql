-- Migration: 033_add_org_logo
-- Add logo_url column to organizations table for custom org branding.
-- Also add logo_preference to organization_settings (stored in jsonb).

-- Add logo_url to organizations
alter table organizations
  add column if not exists logo_url text;

comment on column organizations.logo_url is
  'Public URL of the organization logo image (Supabase Storage). Null means use display name.';
