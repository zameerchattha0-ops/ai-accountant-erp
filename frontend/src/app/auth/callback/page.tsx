"use client";

/* OAuth callback — Google redirects here with a PKCE `code` param.
   The browser Supabase client detects the code in the URL on init
   (detectSessionInUrl) and exchanges it for a session automatically;
   this page just waits for that session, then routes into the app.
   No code exchange happens server-side (this app keeps sessions in
   browser sb-* cookies, same as password login). */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Loader2 } from "lucide-react";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const supabase = createClient();
    let settled = false;

    /* Success path: fires the moment the auto-exchange stores the session */
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event) => {
        if ((event === "SIGNED_IN" || event === "INITIAL_SESSION") && !settled) {
          /* INITIAL_SESSION with a session means the exchange already
             finished before the listener attached. */
          supabase.auth.getSession().then(({ data: { session } }) => {
            if (session && !settled) {
              settled = true;
              subscription.unsubscribe();
              router.replace("/");
              router.refresh();
            }
          });
        }
      }
    );

    /* Poll + timeout fallback (covers slow exchanges and error returns
       like ?error=access_denied, which never produce a session). */
    const poll = setInterval(async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (session && !settled) {
        settled = true;
        clearInterval(poll);
        subscription.unsubscribe();
        router.replace("/");
        router.refresh();
      }
    }, 300);

    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        clearInterval(poll);
        subscription.unsubscribe();
        setError(
          "Google sign-in could not be completed. If Google sign-in is not enabled yet, use email & password — or try again."
        );
      }
    }, 10000);

    return () => {
      clearInterval(poll);
      clearTimeout(timeout);
      subscription.unsubscribe();
    };
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center space-y-4">
      {!error ? (
        <>
          <Loader2 className="w-8 h-8 animate-spin text-brand-teal" />
          <h1 className="text-lg font-semibold text-brand-navy">Signing you in…</h1>
          <p className="text-sm text-text-secondary">Completing Google sign-in</p>
        </>
      ) : (
        <>
          <h1 className="text-lg font-semibold text-brand-navy">Sign-in failed</h1>
          <p className="text-sm text-text-secondary max-w-xs">{error}</p>
          <a
            href="/login"
            className="inline-block mt-2 px-6 py-2.5 btn-3d btn-shine rounded-xl bg-brand-teal text-white text-sm font-medium hover:bg-brand-navy transition"
          >
            Back to Sign In
          </a>
        </>
      )}
    </div>
  );
}
