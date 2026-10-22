"use client";

import { useOrg } from "./useOrg";

/**
 * fetch the current user's ACTIVE membership role for the
 * selected organisation so module pages can gate edit/delete buttons the
 * same way the database does (RLS has_org_role(org, 2) for deletes).
 *
 * The database remains the enforcement layer - this hook only hides
 * buttons the server would refuse, so users never discover permissions
 * through error messages.
 *
 * Performance core: reads from the session-wide org cache in useOrg()
 * rather than dispatching duplicate Supabase auth and organization_members
 * queries on every component mount.
 */
export function useOrgRole() {
  const { roleCode: orgRoleCode, loading } = useOrg();
  const roleCode = orgRoleCode || null;
  const isAdmin = roleCode === "OWNER" || roleCode === "ADMIN";

  return { roleCode, isAdmin, loading };
}
