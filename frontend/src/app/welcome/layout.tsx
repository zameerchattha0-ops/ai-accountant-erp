import { redirect } from "next/navigation";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * Clean full-width layout for the marketing landing page.
 * Authenticated users with an active org are sent to the dashboard.
 */
export default async function WelcomeLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    const { data: memberships } = await supabase
      .from("organization_members")
      .select("id")
      .eq("user_id", user.id)
      .eq("status", "ACTIVE")
      .limit(1);
    if (memberships && memberships.length > 0) {
      redirect("/");
    }
  }

  return <>{children}</>;
}
