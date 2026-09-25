-- Migration: add_th_api_key_vault_helper
-- Encrypted storage for the Token Harbor Universal Key (DeepSeek V4.1 +
-- Mimo 2.6 gateway) using Supabase Vault — the same service-role-only
-- pattern as the Gemini key (025), so the DEPLOYED backend can resolve the
-- primary AI key without any Vercel env change (the stored Vercel token is
-- SAML-scope blocked from managing project env vars).
-- The secret VALUE is created at runtime (never stored in migrations/git):
--   select vault.create_secret('<key>', 'TH_API_KEY', 'Token Harbor Universal Key for the ERP AI agent');
-- Only the service role (backend / edge functions) may retrieve it.

create or replace function public.get_th_api_key()
returns text
language sql
security definer
set search_path = vault, public
as $$
  select decrypted_secret
  from vault.decrypted_secrets
  where name = 'TH_API_KEY'
$$;

revoke execute on function public.get_th_api_key() from public, anon, authenticated;
grant  execute on function public.get_th_api_key() to service_role;

comment on function public.get_th_api_key() is
  'Returns the Token Harbor API key from Supabase Vault. Service role only: the key must never reach the browser.';
