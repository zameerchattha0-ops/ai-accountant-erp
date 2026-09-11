import { redirect } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import TopBar from "@/components/layout/TopBar";
import AmbientAura from "@/components/shared/AmbientAura";
import AgentRunDock from "@/components/ai/AgentRunDock";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * Protected ERP shell. A signed-in user without an ACTIVE organization
 * membership is routed to the onboarding wizard.
 */
export default async function DashboardLayout({
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
    if (!memberships || memberships.length === 0) {
      redirect("/onboarding");
    }
  }

  return (
    <div className="relative isolate flex h-screen overflow-hidden bg-bg-primary">
      {/* Ambient aura - full-viewport app background (fixed layer, behind
          everything; the sidebar and topbar are translucent so the tint
          shows through them too). */}
      <AmbientAura />
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6 print:overflow-visible print:p-0">
          {children}
        </main>
      </div>
      {/* Persistent agent status — live on EVERY sidebar tab; the run
          itself continues in agentRunStore regardless of navigation. */}
      <AgentRunDock />
    </div>
  );
}
