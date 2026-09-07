-- Migration: add_gemini_key_vault_helper
-- Encrypted storage for the Gemini API key using Supabase Vault.
-- The secret VALUE is created at runtime (never stored in migrations/git):
--   select vault.create_secret('<key>', 'GEMINI_API_KEY', 'Google Gemini API key for the ERP AI agent');
-- Only the service role (backend / edge functions) may retrieve it.

create or replace function public.get_gemini_api_key()
returns text
language sql
security definer
set search_path = vault, public
as $$
  select decrypted_secret
  from vault.decrypted_secrets
  where name = 'GEMINI_API_KEY'
$$;

revoke execute on function public.get_gemini_api_key() from public, anon, authenticated;
grant  execute on function public.get_gemini_api_key() to service_role;

comment on function public.get_gemini_api_key() is
  'Returns the Gemini API key from Supabase Vault. Service role only: the key must never reach the browser.';
