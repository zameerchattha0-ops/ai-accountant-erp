import { redirect } from "next/navigation";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * Onboarding shell (no sidebar). Users who already have an ACTIVE membership
 * are sent straight to the dashboard.
 */
export default async function OnboardingLayout({
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

  return (
    <div className="min-h-screen bg-bg-primary flex flex-col">
      {children}
    </div>
  );
}
