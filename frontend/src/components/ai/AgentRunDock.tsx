"use client";

import { useSyncExternalStore } from "react";
import { usePathname, useRouter } from "next/navigation";
import { CheckCircle2, ChevronRight, Loader2, X } from "lucide-react";
import { agentRunStore, type AgentRunState } from "@/lib/agent/agentRunStore";
import { ExecutionStatus } from "@/lib/types/enums";

/**
 * AgentRunDock — persistent agent status for EVERY sidebar tab.
 *
 * Mounted once in the dashboard layout, it never unmounts on
 * navigation. While the agent works, a compact live card shows the
 * current phase on any page; when a run finishes (including while the
 * user was elsewhere), a result chip appears with one-click "View
 * result" routing back to the dashboard's command box, which re-renders
 * the full card from the shared store.
 *
 * Hidden on the dashboard itself (the full command box already renders
 * there — no duplicate surface).
 */
export default function AgentRunDock() {
  const router = useRouter();
  const pathname = usePathname();
  const run: AgentRunState = useSyncExternalStore(
    agentRunStore.subscribe,
    agentRunStore.getSnapshot,
    agentRunStore.getSnapshot,
  );

  if (pathname === "/") return null;

  const { loading, response } = run;
  /* Show while the agent works, or when a result/question awaits the
     user on a tab other than the dashboard. Error-only state never
     nags — it surfaces on the dashboard box. */
  if (!loading && !response) return null;

  const lastStep = run.liveSteps[run.liveSteps.length - 1];
  const finishedOk =
    !loading &&
    response &&
    (response.status === ExecutionStatus.COMPLETED ||
      response.status === ExecutionStatus.FAILED ||
      response.status === ExecutionStatus.REJECTED ||
      response.status === ExecutionStatus.AWAITING_CLARIFICATION ||
      response.status === ExecutionStatus.AWAITING_CONFIRMATION);

  return (
    <div className="fixed bottom-4 right-4 z-40 print:hidden">
      {loading ? (
        <button
          type="button"
          onClick={() => router.push("/")}
          aria-label="Agent working — open the live progress"
          className="w-[calc(100vw-2rem)] max-w-xs rounded-2xl bg-bg-surface/95 backdrop-blur-xl border border-ai-200 shadow-[0_22px_48px_-20px_rgba(27,42,74,0.5)] p-3.5 flex items-center gap-3 text-left transition-transform hover:-translate-y-0.5"
        >
          <span className="w-9 h-9 rounded-full bg-ai-50 flex items-center justify-center shrink-0">
            <Loader2 className="w-4.5 h-4.5 w-[18px] h-[18px] animate-spin text-ai-600" />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-text-primary">
              Agent working…
            </span>
            <span className="block text-xs text-text-muted truncate">
              {lastStep?.phase
                ? `${lastStep.phase}`
                : "Reasoning about your request"}
            </span>
          </span>
          <ChevronRight className="w-4 h-4 text-text-muted shrink-0" />
        </button>
      ) : finishedOk ? (
        <div
          className="w-[calc(100vw-2rem)] max-w-xs rounded-2xl bg-bg-surface/95 backdrop-blur-xl border border-border-subtle shadow-[0_22px_48px_-20px_rgba(27,42,74,0.5)] p-3.5 flex items-center gap-3"
          role="status"
        >
          <span className="w-9 h-9 rounded-full bg-success-50 flex items-center justify-center shrink-0">
            <CheckCircle2 className="w-[18px] h-[18px] text-success-600" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-text-primary">
              {response.status === ExecutionStatus.FAILED
                ? "Agent run failed"
                : response.status === ExecutionStatus.AWAITING_CLARIFICATION
                  ? "Agent needs your answer"
                  : response.status === ExecutionStatus.AWAITING_CONFIRMATION
                    ? "Agent needs your approval"
                    : "Agent finished"}
            </span>
            <span className="block text-xs text-text-muted">
              Result ready on the dashboard
            </span>
          </span>
          <button
            type="button"
            onClick={() => router.push("/")}
            aria-label="View the agent result"
            className="btn-3d-soft shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-ai-600"
          >
            View <ChevronRight className="w-3 h-3" />
          </button>
          <button
            type="button"
            onClick={() => agentRunStore.dismissResult()}
            aria-label="Dismiss"
            className="shrink-0 p-1 rounded-lg text-text-muted hover:text-text-primary transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ) : null}
    </div>
  );
}