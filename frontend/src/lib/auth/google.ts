/* Google provider availability check (client-side).
   The login/signup buttons pre-check Supabase's public auth settings
   before redirecting, so users never land on the raw
   "Unsupported provider: provider is not enabled" JSON page when the
   Google provider has not been enabled on the Supabase project yet.
   Once the provider is toggled on in the Supabase dashboard, this
   returns true automatically — no code change or redeploy needed. */
export async function isGoogleProviderEnabled(): Promise<boolean> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return false;
  try {
    const res = await fetch(`${url.replace(/\/+$/, "")}/auth/v1/settings`, {
      headers: { apikey: key },
      cache: "no-store",
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { external?: { google?: boolean } };
    return data?.external?.google === true;
  } catch {
    return false;
  }
}
