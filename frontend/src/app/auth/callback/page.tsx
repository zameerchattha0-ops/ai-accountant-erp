"use client";

/* OAuth callback — Google redirects here with a PKCE `code` param.
   The code is exchanged explicitly for a session (no reliance on
   detectSessionInUrl auto-exchange), then we route into the app.

   WHY EXPLICIT: newer supabase-js stores the PKCE verifier in a
   per-flow cookie slot and expects the flow id back as a `sb_flow_id`
   URL param. The hosted auth server strips that param from the final
   redirect, so the auto-exchange can't find the verifier and silently
   does nothing (observed in auth logs: no /token request at all).
   Recovery: scan cookies for `sb-<ref>-flow-<id>-code-verifier` slots
   and retry the exchange once per candidate flow id. */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createBrowserClient } from "@supabase/ssr";
import { Loader2 } from "lucide-react";

const FLOW_ID_PARAM = "sb_flow_id";
const FLOW_SLOT_RE = /sb-[^=\s;]+-flow-([0-9a-f]{32})-code-verifier/;

function parseParams(): Record<string, string> {
  const out: Record<string, string> = {};
  new URLSearchParams(window.location.search).forEach((v, k) => {
    out[k] = v;
  });
  return out;
}

/* Flow ids we could possibly exchange with, most-reliable first: the one
   captured at sign-in time (sessionStorage), the one in the URL (if the
   server kept it), then every verifier slot still in the cookies. */
function candidateFlowIds(fromUrl: string | null): (string | undefined)[] {
  const ids: string[] = [];
  try {
    const stored = sessionStorage.getItem("pkce_flow_id");
    if (stored) ids.push(stored);
  } catch {
    /* storage unavailable */
  }
  if (fromUrl && !ids.includes(fromUrl)) ids.push(fromUrl);
  document.cookie.split(";").forEach((pair) => {
    const m = pair.match(FLOW_SLOT_RE);
    if (m && !ids.includes(m[1])) ids.push(m[1]);
  });
  /* No slotted verifiers at all → try the legacy shared verifier key. */
  return ids.length ? ids : [undefined];
}

function clearUrlParams() {
  const url = new URL(window.location.href);
  url.search = "";
  window.history.replaceState(window.history.state, "", url.toString());
}

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const params = parseParams();
    /* OAuth provider errors (?error=access_denied, etc.) — no code to
       exchange, show it right away. */
    if (params.error) {
      setError(
        params.error_description
          ? `Google sign-in was cancelled: ${params.error_description}`
          : "Google sign-in was cancelled. Please try again."
      );
      return;
    }

    const code = params.code;
    if (!code) {
      setError("Missing sign-in code in the callback URL. Please start the sign-in again.");
      return;
    }

    /* Strip params immediately so a refresh can't reuse a consumed code. */
    clearUrlParams();

    const supabase = createBrowserClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      { auth: { detectSessionInUrl: false, flowType: "pkce" } }
    );

    const finish = () => {
      router.replace("/");
      router.refresh();
    };

    (async () => {
      const candidates = candidateFlowIds(params[FLOW_ID_PARAM] ?? null);
      let lastError: string | null = null;

      for (const flowId of candidates) {
        const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(
          code,
          flowId ? { flowId } : undefined
        );
        if (!exchangeError) {
          try {
            sessionStorage.removeItem("pkce_flow_id");
          } catch {
            /* ignore */
          }
          clearUrlParams();
          finish();
          return;
        }
        lastError = exchangeError.message;
      }

      clearUrlParams();
      setError(
        lastError
          ? `Google sign-in could not be completed (${lastError}). Please try again — or use email & password.`
          : "Google sign-in could not be completed. Please try again — or use email & password."
      );
    })();
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
