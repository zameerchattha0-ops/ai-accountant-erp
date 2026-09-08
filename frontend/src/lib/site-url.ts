/* Resolves the public site URL used for auth email redirects (signup
   verification, future password resets, etc.).

   Priority:
     1. NEXT_PUBLIC_SITE_URL env (set in Vercel → production URL)
     2. Hardcoded production domain when built for production
     3. Current browser origin (local dev → http://localhost:3000)

   IMPORTANT: Supabase silently ignores an `emailRedirectTo` that is not in
   Authentication → URL Configuration → "Redirect URLs", falling back to the
   dashboard "Site URL". Keep both set to the production URL there, or the
   confirmation mail will route to whatever the Site URL says (e.g. localhost). */
const PRODUCTION_SITE_URL = "https://ai-accountant-erp.vercel.app";

export function getSiteUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_SITE_URL;
  if (envUrl) return envUrl.replace(/\/+$/, "");
  if (process.env.NODE_ENV === "production") return PRODUCTION_SITE_URL;
  if (typeof window !== "undefined") return window.location.origin;
  return "http://localhost:3000";
}
