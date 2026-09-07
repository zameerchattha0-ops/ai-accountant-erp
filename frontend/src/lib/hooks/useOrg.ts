"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";

export interface OrgContext {
  organization_id: string;
  name: string;
  slug: string;
  base_currency_code: string;
  country_code: string | null;
  timezone: string;
  fiscal_year_end_month: number;
  business_type: string;
  legal_name: string | null;
  tax_number: string | null;
  registration_number: string | null;
  logo_url: string | null;
}

export interface UseOrgResult {
  org: OrgContext | null;
  roleCode: string;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Resolves the signed-in user's ACTIVE organization membership (with role).
 * All tenant-scoped queries key off `org.organization_id`.
 */
export function useOrg(): UseOrgResult {
  const [org, setOrg] = useState<OrgContext | null>(null);
  const [roleCode, setRoleCode] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const supabase = createClient();
        const { data: { user } } = await supabase.auth.getUser();
        if (!user) throw new Error("Not signed in");

        const { data, error: dbError } = await supabase
          .from("organization_members")
          .select(
            `organization_id,
             status,
             organization:organizations(
               id, name, slug, business_type, base_currency_code, country_code,
               timezone, fiscal_year_end_month, legal_name, tax_number,
               registration_number, logo_url
             ),
             role:organization_roles(code)`
          )
          .eq("user_id", user.id)
          .eq("status", "ACTIVE")
          .order("created_at");

        if (dbError) throw dbError;
        if (cancelled) return;

        const membership = data?.[0];
        if (!membership) {
          setOrg(null);
          setLoading(false);
          return;
        }

        const orgRow = (membership.organization as unknown as OrgContext[])?.[0]
          ?? (membership.organization as unknown as OrgContext);
        const role = (membership.role as unknown as { code: string }[])?.[0]?.code
          ?? (membership.role as unknown as { code: string })?.code
          ?? "";

        setOrg({ ...orgRow, organization_id: membership.organization_id });
        setRoleCode(role);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load organization");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [tick]);

  return { org, roleCode, loading, error, refresh };
}
