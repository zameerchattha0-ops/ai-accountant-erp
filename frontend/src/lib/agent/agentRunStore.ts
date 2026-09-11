/* ==================================================================
   AgentRunStore — navigation-proof agent run controller.
   ==================================================================
   The agent's run state (progress, live steps, result card, awaiting
   clarification/confirmation) lives HERE, at module level — never in
   a component's useState. Consequences:

   * Clicking any sidebar tab unmounts AICommandBox, but the run's
     fetch/SSE promise chain keeps streaming into this store — the work
     being executed is NEVER killed or lost.
   * Returning to the dashboard re-renders the exact state (progress,
     awaiting-question card, result) instantly from the snapshot.
   * A compact AgentRunDock mounted in the dashboard layout shows live
     status on EVERY tab while the agent works.
   * Full page reloads reattach via /api/ai/sessions/latest-active
     (the run continues server-side through the disconnect).

   Components subscribe with useSyncExternalStore; updates are plain
   immutable snapshots. */
import {
  aiClarify,
  aiConfirm,
  aiExecuteStream,
  aiEnqueueJob,
  aiGetJob,
  isApiErrorWithStatus,
  latestActiveSession,
  runBackgroundJob,
} from "@/lib/api/client";
import type { AgentResponse, UserRequest } from "@/lib/types/api";
import { ExecutionStatus } from "@/lib/types/enums";

/* Structurally identical to AIProgress's LiveStepEvent (kept here to
   avoid a lib → components import; TS structural typing bridges them). */
export interface AgentLiveStep {
  step_type: string;
  phase: string | null;
  status: string | null;
  created_at: string | null;
}

export interface AgentRunState {
  loading: boolean;
  activeRequestId: string | null;
  liveSteps: AgentLiveStep[];
  response: AgentResponse | null;
  error: string;
  reattached: boolean;
  stalledJobId: string | null;
}

let state: AgentRunState = {
  loading: false,
  activeRequestId: null,
  liveSteps: [],
  response: null,
  error: "",
  reattached: false,
  stalledJobId: null,
};

const listeners = new Set<() => void>();

function set(partial: Partial<AgentRunState>) {
  state = { ...state, ...partial };
  listeners.forEach((l) => l());
}

/* Background runs are the DEFAULT path when a supervised worker drains
   ai.worker_jobs (local dev). A serverless host (Vercel) has no worker,
   so background mode is enabled only when the backend is local or
   explicitly forced — mirroring the backend run contracts. */
export const USE_BACKGROUND_RUNS =
  process.env.NEXT_PUBLIC_BACKGROUND_RUNS === "1" ||
  /^(https?:)?\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(
    process.env.NEXT_PUBLIC_API_URL ?? ""
  );

/* Fired whenever the agent FINISHES a mutation (or fails one) so every
   listening page reloads its data instantly — no manual browser refresh. */
function notifyDataChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("erp:data-changed"));
  }
}

const requestId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;

function isTerminal(res: AgentResponse): boolean {
  return (
    res.status === ExecutionStatus.COMPLETED ||
    res.status === ExecutionStatus.FAILED ||
    res.status === ExecutionStatus.REJECTED
  );
}

function applyResponse(res: AgentResponse) {
  const terminal = isTerminal(res);
  set({
    response: res,
    loading: false,
    liveSteps: [],
    ...(terminal ? { activeRequestId: null, reattached: false, stalledJobId: null } : {}),
  });
  if (terminal) notifyDataChanged();
}

async function runForeground(request: UserRequest) {
  const res = await aiExecuteStream(request, {
    onStep: (step) =>
      set({
        liveSteps: [
          ...state.liveSteps,
          {
            step_type: step.step_type,
            phase: step.phase ?? null,
            status: step.status ?? null,
            created_at: step.created_at ?? null,
          },
        ],
      }),
  });
  applyResponse(res);
}

function runBackground(request: UserRequest) {
  return runBackgroundJob({
    enqueue: () => aiEnqueueJob(request),
    getJob: aiGetJob,
    onResult: applyResponse,
    onError: (msg) => set({ error: msg, loading: false }),
    onStalled: (jobId) => set({ stalledJobId: jobId }),
  });
}

/* ---- Reattach (page refresh mid-run) — module-level, idempotent ----
   The poller watches the latest in-flight session until it reaches a
   terminal state. It is NOT tied to any component: navigating away
   and back never interrupts it, and unmounts cannot stop it. */
let reattachStarted = false;

function ensureReattach() {
  if (reattachStarted || state.loading) return;
  reattachStarted = true;

  (async () => {
    try {
      const info = await latestActiveSession();
      if (!info.found || !info.session) {
        reattachStarted = false;
        return;
      }
      const status = (info.session.status || "").toUpperCase();
      const convId = info.session.conversation_id;
      if (
        (status === "EXECUTING" || status === "PLANNING" || status === "PENDING") &&
        convId
      ) {
        set({ activeRequestId: convId, loading: true, reattached: true });
      } else {
        reattachStarted = false;
        return;
      }

      const id = setInterval(async () => {
        try {
          const again = await latestActiveSession();
          if (!again.found) {
            clearInterval(id);
            reattachStarted = false;
            set({ loading: false, activeRequestId: null, reattached: false });
            notifyDataChanged();
          }
        } catch {
          /* keep polling — transient network errors must not detach */
        }
      }, 4000);
    } catch {
      reattachStarted = false; /* backend offline — nothing to reattach */
    }
  })();
}

export const agentRunStore = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  getSnapshot: (): AgentRunState => state,

  /* Boot the reattach watcher (called on any dashboard mount — idempotent) */
  ensureReattach,

  setError: (msg: string) => set({ error: msg }),
  clearError: () => set({ error: "" }),

  /* Start a run. The promise chain lives in THIS module — sidebar
     navigation cannot abort, unmount or orphan it. */
  async startRun(request: UserRequest) {
    if (state.loading) return; // one run at a time
    set({
      loading: true,
      response: null,
      error: "",
      stalledJobId: null,
      reattached: false,
      liveSteps: [],
    });
    const rid = requestId();
    set({ activeRequestId: rid });
    try {
      if (USE_BACKGROUND_RUNS) {
        try {
          await runBackground({ ...request, conversation_id: rid });
        } catch (jobErr) {
          if (!isApiErrorWithStatus(jobErr, 404)) throw jobErr;
          await runForeground({ ...request, conversation_id: rid }); // older backend
        }
      } else {
        await runForeground({ ...request, conversation_id: rid });
      }
    } catch (err) {
      set({
        error:
          err instanceof Error
            ? /failed to fetch|networkerror|net::err/i.test(err.message)
              ? "The AI service is offline. Start the backend server (port 8000) and try again."
              : err.message
            : "Something went wrong",
      });
    } finally {
      set({ loading: false, activeRequestId: null, liveSteps: [] });
    }
  },

  async clarify(answer: string) {
    if (!state.response?.execution_id) return;
    set({ loading: true, error: "" });
    try {
      const res = await aiClarify({
        session_id: state.response.execution_id,
        answer,
      });
      applyResponse(res);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to send answer" });
    } finally {
      set({ loading: false });
    }
  },

  async confirm(approved: boolean, notes?: string) {
    if (!state.response?.execution_id) return;
    set({ loading: true, error: "" });
    try {
      const res = await aiConfirm({
        session_id: state.response.execution_id,
        approved,
        notes,
      });
      applyResponse(res);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to send decision" });
    } finally {
      set({ loading: false });
    }
  },

  /* One-click foreground fallback when the queue is not being drained. */
  async runStalledInForeground(request: UserRequest) {
    set({ stalledJobId: null, loading: true, error: "" });
    const rid = requestId();
    set({ activeRequestId: rid });
    try {
      await runForeground({ ...request, conversation_id: rid });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Something went wrong" });
    } finally {
      set({ loading: false, activeRequestId: null, liveSteps: [] });
    }
  },

  /* Dismiss the result card / dock chip after reading it. */
  dismissResult() {
    set({ response: null, error: "", reattached: false, stalledJobId: null });
  },
};