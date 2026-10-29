import { PageSkeleton } from "@/components/shared/States";

/**
 * Next.js Instant Streaming Route Skeleton for the (dashboard) shell.
 * Renders immediately when a user navigates between routes over poor/rural
 * networks, eliminating white flashes and layout shift.
 */
export default function DashboardLoading() {
  return <PageSkeleton />;
}

