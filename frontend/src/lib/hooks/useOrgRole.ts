"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "./useOrg";

/**
 * Work Stream F: fetch the current user's ACTIVE membership role for the
 * selected organisation so module pages can gate edit/delete buttons the
 * same way the database does (RLS has_org_role(org, 2) for deletes).
 *
 * The database remains the enforcement layer - this hook only hides
 * buttons the server would refuse, so users never discover permissions
 * through error messages.
 */
export function useOrgRole() {
  const { org, loading: orgLoading } = useOrg();
  const [roleCode, setRoleCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!org) {
        if (!orgLoading) setLoading(false);
        return;
      }
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        if (!cancelled) setLoading(false);
        return;
      }
      const { data: m } = await supabase
        .from("organization_members")
        .select("role:organization_roles(code)")
        .eq("user_id", user.id)
        .eq("organization_id", org.organization_id)
        .eq("status", "ACTIVE")
        .limit(1);
      if (cancelled) return;
      const role = m?.[0] as
        | { role?: { code?: string } | { code?: string }[] }
        | undefined;
      const r = Array.isArray(role?.role) ? role?.role[0] : role?.role;
      setRoleCode(r?.code ?? null);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [org, orgLoading]);

  const isAdmin = roleCode === "OWNER" || roleCode === "ADMIN";

  return { roleCode, isAdmin, loading: loading || orgLoading };
}
