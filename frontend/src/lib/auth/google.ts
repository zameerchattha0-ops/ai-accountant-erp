/* Google provider availability check (client-side).
   Pre-checks Supabase's public auth settings before redirecting, so users
   never land on the raw "Unsupported provider" JSON page when the Google
   provider is not enabled. Fail-open by design: if the settings endpoint is
   unreachable or the key is rejected, we return true so the OAuth attempt
   proceeds anyway — the /auth/callback page shows a friendly error if it
   genuinely fails. */
export async function isGoogleProviderEnabled(): Promise<boolean> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return true; // fail-open: let Supabase decide
  try {
    const res = await fetch(`${url.replace(/\/+$/, "")}/auth/v1/settings`, {
      headers: { apikey: key },
      cache: "no-store",
    });
    if (!res.ok) return true; // fail-open on 401/5xx/network quirks
    const data = (await res.json()) as { external?: { google?: boolean } };
    // Only block when we got a definitive "google is off" answer.
    return data?.external?.google !== false;
  } catch {
    return true; // fail-open on any fetch error
  }
}

