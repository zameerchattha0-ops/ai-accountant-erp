"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { CheckCircle2, XCircle, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { aiProgress } from "@/lib/api/client";
import { agentRunStore } from "@/lib/agent/agentRunStore";
import type { AgentProgress, ProgressStep } from "@/lib/types/api";

const POLL_MS = 1500;

/* Hard ceiling on polling. A stale conversation id (a run whose executor
   was killed mid-flight) never reaches a terminal status, so an unbounded
   poll would hammer the API for as long as the tab stayed open. */
const POLL_DEADLINE_MS = 10 * 60 * 1000;

const PHASE_LABELS: Record<string, string> = {
  RECEIVED: "Request received",
  INTERPRETING: "Understanding intent",
  PLANNING: "Building plan",
  CONTEXT_LOADING: "Loading ERP context",
  AWAITING_CLARIFICATION: "Missing information",
  AWAITING_CONFIRMATION: "Awaiting your confirmation",
  EXECUTING: "Executing trusted tools",
  VALIDATING: "Validating results",
  VERIFYING: "Verifying database state",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
  REJECTED: "Cancelled",
};

const PHASE_ORDER = [
  "RECEIVED",
  "INTERPRETING",
  "PLANNING",
  "CONTEXT_LOADING",
  "EXECUTING",
  "VALIDATING",
  "VERIFYING",
  "COMPLETED",
];

// Multi-colour pipeline - each phase has its own identity colour so the
// user can SEE the agent move through the machine.
const PHASE_COLORS: Record<string, { dot: string; text: string; coreBg: string; glowBg: string }> = {
  RECEIVED: { dot: "bg-info-500", text: "text-info-600", coreBg: "bg-info-500", glowBg: "bg-info-400" },
  INTERPRETING: { dot: "bg-ai-500", text: "text-ai-600", coreBg: "bg-ai-500", glowBg: "bg-ai-400" },
  PLANNING: { dot: "bg-purple-500", text: "text-purple-600", coreBg: "bg-purple-500", glowBg: "bg-purple-400" },
  CONTEXT_LOADING: { dot: "bg-warning-500", text: "text-warning-600", coreBg: "bg-warning-500", glowBg: "bg-warning-400" },
  EXECUTING: { dot: "bg-success-500", text: "text-success-600", coreBg: "bg-success-500", glowBg: "bg-success-400" },
  VALIDATING: { dot: "bg-info-500", text: "text-info-600", coreBg: "bg-info-500", glowBg: "bg-info-400" },
  VERIFYING: { dot: "bg-ai-600", text: "text-ai-700", coreBg: "bg-ai-600", glowBg: "bg-ai-500" },
  COMPLETED: { dot: "bg-success-500", text: "text-success-600", coreBg: "bg-success-500", glowBg: "bg-success-400" },
};

// Rotating, human thoughts per phase - swaps every ~1.2s so the waiting
// feels ALIVE instead of frozen (perceived-latency psychology).
const PHASE_THOUGHTS: Record<string, string[]> = {
  RECEIVED: [
    "Request received…",
    "Waking up the agent…",
  ],
  INTERPRETING: [
    "Thinking…",
    "Understanding what you mean…",
    "Reading between the lines…",
    "Identifying the nature of this transaction…",
  ],
  PLANNING: [
    "Reasoning…",
    "Choosing the right tools…",
    "Drafting an execution plan…",
    "Weighing the accounting impact…",
  ],
  CONTEXT_LOADING: [
    "Fetching your data…",
    "Checking customers, suppliers & accounts…",
    "Gathering ERP context…",
  ],
  AWAITING_CLARIFICATION: [
    "Waiting for your answer…",
  ],
  AWAITING_CONFIRMATION: [
    "Waiting for your approval…",
  ],
  EXECUTING: [
    "Recording the transaction…",
    "Working with trusted tools…",
    "Writing to the ledger…",
  ],
  VALIDATING: [
    "Validating accounting rules…",
    "Checking debits = credits…",
  ],
  VERIFYING: [
    "Verifying the database…",
    "Cross-checking balances…",
    "Almost there…",
  ],
  COMPLETED: ["Done"],
  FAILED: ["Something went wrong"],
};

const TERMINAL_STATUSES = [
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "REJECTED",
  "WAITING_FOR_USER",
];

function stepSummaryLabel(step: ProgressStep): string {
  const s = (step.summary || {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof s.intent === "string") parts.push(s.intent.replace(/_/g, " "));
  const ents = s.extracted_entities as Record<string, unknown> | undefined;
  if (ents && typeof ents === "object" && !Array.isArray(ents)) {
    for (const [key, value] of Object.entries(ents)) {
      if (typeof value === "string" && value.trim()) {
        parts.push(`${key.replace(/_/g, " ")}: ${value}`);
      } else if (typeof value === "number") {
        parts.push(`${key.replace(/_/g, " ")}: ${value.toLocaleString()}`);
      }
    }
  }
  const counts = ["customers", "suppliers", "accounts", "projects", "documents"] as const;
  for (const key of counts) {
    const value = s[key];
    if (typeof value === "number") parts.push(`${value} ${key.replace(/_/g, " ")}`);
  }
  if (typeof s.attachments === "number") {
    parts.push(`${s.attachments} attachment${s.attachments === 1 ? "" : "s"} read`);
  }
  if (typeof s.transaction_nature === "string") parts.push(s.transaction_nature);
  if (typeof s.question === "string" && s.question) {
    parts.push(String(s.question).slice(0, 120));
  }
  return parts.slice(0, 4).join(" · ");
}

/**
 * A step event pushed LIVE over SSE. Shape mirrors the
 * polled ProgressStep so the render path is identical.
 */
export interface LiveStepEvent {
  step_type: string;
  phase?: string | null;
  status?: string | null;
  created_at?: string | null;
}

export default function AIProgress({
  conversationId,
  liveSteps,
}: {
  conversationId: string | null;
  /** When provided, steps stream in over SSE and polling is skipped. */
  liveSteps?: LiveStepEvent[];
}) {
  const [progress, setProgress] = useState<AgentProgress | null>(null);
  const [expanded, setExpanded] = useState(false);
  // Rotating "thought" index - the visible status changes every ~1.2s so
  // the wait feels alive (perceived-latency psychology).
  const [thoughtIdx, setThoughtIdx] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  // Cancel-in-flight flag (store-owned — the dock's button shares it).
  const { cancelling } = useSyncExternalStore(
    agentRunStore.subscribe,
    agentRunStore.getSnapshot,
    agentRunStore.getSnapshot
  );

  useEffect(() => {
    const t = setInterval(() => {
      setThoughtIdx((i) => i + 1);
      setElapsed((s) => s + 1);
    }, 1150);
    return () => clearInterval(t);
  }, []);

  // Polls the BACKEND-RECORDED state (ai.execution_steps / session phase).
  // The panel reflects what the agent ACTUALLY did - no fake animations.
  // Skipped entirely when steps are streamed in live (SSE mode).
  useEffect(() => {
    if (!conversationId || liveSteps) return;
    let cancelled = false;
    const deadline = Date.now() + POLL_DEADLINE_MS;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const next = await aiProgress(conversationId);
        if (cancelled) return;
        setProgress(next);
        const done =
          next.status && TERMINAL_STATUSES.includes(next.status);
        if (done && next.steps.length > 0) {
          setExpanded(true);
          return; // terminal - stop polling
        }
      } catch {
        // Backend briefly unreachable - stay calm and keep polling.
      }
      // Give up once the ceiling is reached: nothing is coming.
      if (!cancelled && Date.now() < deadline) timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [conversationId, liveSteps]);

  // SSE mode: derive the rendered steps directly from the live stream
  // (identical shape to the polled ProgressStep rows).
  const streamedSteps = (liveSteps ?? []).map((s, i) => ({
    step_type: s.step_type,
    phase: s.phase || s.step_type,
    status: s.status ?? "COMPLETED",
    created_at: s.created_at ?? new Date().toISOString(),
    summary: {} as Record<string, unknown>,
    _order: i,
  }));
  const steps = liveSteps ? streamedSteps : progress?.steps ?? [];
  const tools = progress?.tools ?? [];
  const currentPhase = liveSteps
    ? streamedSteps[streamedSteps.length - 1]?.phase
    : progress?.current_phase;
  const terminal = Boolean(
    progress?.status && TERMINAL_STATUSES.includes(progress.status)
  );

  // Canonical stages that have REAL evidence (recorded steps or live phase).
  const phasesWithEvidence = new Set<string>();
  for (const step of steps) {
    const phase = step.phase || step.step_type;
    if (phase) phasesWithEvidence.add(phase);
  }
  if (currentPhase) phasesWithEvidence.add(currentPhase);
  const stagesToRender = PHASE_ORDER.filter(
    (p) => phasesWithEvidence.has(p) && p !== "RECEIVED"
  );

  const thoughts = PHASE_THOUGHTS[currentPhase ?? ""] ?? ["Working…"];
  const thought = thoughts[thoughtIdx % thoughts.length];
  const activeColor = PHASE_COLORS[currentPhase ?? ""] ?? {
    dot: "bg-ai-500",
    text: "text-ai-600",
  };
  const stepIndex = currentPhase ? PHASE_ORDER.indexOf(currentPhase) : -1;

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/60 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-[0_12px_36px_-10px_rgba(27,42,74,0.12)] p-4.5 transition-all duration-300">
      {/* Top border quantum luminous sheen sweep */}
      {!terminal && (
        <div className="absolute top-0 left-0 right-0 h-[2px] overflow-hidden pointer-events-none">
          <div className="w-1/2 h-full bg-gradient-to-r from-transparent via-ai-400 to-transparent animate-sheen-sweep" />
        </div>
      )}

      {/* Header row - Quantum Neural Core + Real-time Flux + Inspector toggle */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex-1 flex items-center gap-3.5 text-sm font-medium text-text-primary text-left group"
          aria-expanded={expanded}
        >
          {terminal && progress?.status === "COMPLETED" ? (
            <div className="w-9 h-9 rounded-full bg-success-50 border border-success-200/60 flex items-center justify-center shrink-0 shadow-sm">
              <CheckCircle2 className="w-5 h-5 text-success-600" />
            </div>
          ) : terminal ? (
            <div className="w-9 h-9 rounded-full bg-error-50 border border-error-200/60 flex items-center justify-center shrink-0 shadow-sm">
              <XCircle
                className={cn(
                  "w-5 h-5",
                  progress?.status === "FAILED" ? "text-error-600" : "text-text-muted"
                )}
              />
            </div>
          ) : (
            /* Quantum Neural Orb with concentric orbital flux and core pulsing */
            <div className="relative w-9 h-9 shrink-0 flex items-center justify-center">
              {/* Outer soft atmospheric aura */}
              <span
                className={cn(
                  "absolute inset-0 rounded-full opacity-35 blur-[3px] animate-pulse-slow",
                  activeColor.glowBg
                )}
              />
              {/* Concentric rotating orbital ring */}
              <span className="absolute inset-0 rounded-full border border-dashed border-ai-400/50 dark:border-ai-300/40 animate-quantum-spin" />
              {/* Orbiting particle */}
              <span className="absolute -top-0.5 left-1/2 -translate-x-1/2 w-1.5 h-1.5 rounded-full bg-ai-500 shadow-[0_0_8px_rgba(99,102,241,0.9)] animate-quantum-spin" />
              {/* Inner quantum core */}
              <span
                className={cn(
                  "relative w-4 h-4 rounded-full shadow-md flex items-center justify-center animate-quantum-pulse",
                  activeColor.coreBg
                )}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-white shadow-inner" />
              </span>
            </div>
          )}

          <div className="flex-1 min-w-0">
            {terminal ? (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-text-primary text-sm">
                  Agent progress
                </span>
                {currentPhase && (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-bg-muted text-text-secondary border border-border-subtle">
                    {PHASE_LABELS[currentPhase] || currentPhase.toLowerCase()}
                  </span>
                )}
              </div>
            ) : (
              <div>
                {/* Rotating thought stream */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    key={thought}
                    className={cn(
                      "block font-semibold text-sm tracking-tight animate-fade-swap",
                      activeColor.text
                    )}
                  >
                    {thought}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  <span className="text-[11px] font-medium text-text-secondary">
                    {PHASE_LABELS[currentPhase ?? ""] || "Live Reasoning"}
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-ai-50 text-ai-700 dark:bg-ai-950/60 dark:text-ai-300 border border-ai-200/50">
                    {elapsed}s elapsed
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Real-time Quantum Waveform / Frequency Bars (working stage visualizer) */}
          {!terminal && (
            <div
              className="hidden sm:flex items-end gap-1 h-5 px-2 py-1 rounded-lg bg-bg-muted/80 backdrop-blur-sm border border-border-subtle/60 shrink-0"
              title="Real-time neural flux waveform"
            >
              <span className="w-1 h-full bg-ai-500 rounded-full animate-bar-1" />
              <span className="w-1 h-full bg-ai-600 rounded-full animate-bar-2" />
              <span className="w-1 h-full bg-indigo-500 rounded-full animate-bar-3" />
              <span className="w-1 h-full bg-purple-500 rounded-full animate-bar-4" />
              <span className="w-1 h-full bg-cyan-500 rounded-full animate-bar-5" />
            </div>
          )}

          <div className="p-1 rounded-lg text-text-muted group-hover:text-text-primary transition-colors">
            {expanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </div>
        </button>

        {!terminal && (
          <button
            type="button"
            onClick={() => void agentRunStore.cancel()}
            disabled={cancelling}
            aria-label="Cancel this request"
            className="shrink-0 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold uppercase tracking-wide text-error-600 border border-error-100 hover:bg-error-50 transition-colors disabled:opacity-60"
          >
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        )}
      </div>

      {/* Elite Glassmorphic Stage Stepper Pills */}
      {!terminal && stepIndex >= 0 && (
        <div className="mt-3.5 pt-3 border-t border-border-subtle/50 flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
          {PHASE_ORDER.slice(0, -1).map((phase, i) => {
            const done = i < stepIndex;
            const active = phase === currentPhase;
            const label = PHASE_LABELS[phase] || phase;
            return (
              <div
                key={phase}
                className={cn(
                  "shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all duration-200 border",
                  done
                    ? "bg-success-50/80 text-success-700 border-success-200/70"
                    : active
                    ? "bg-ai-50/90 text-ai-700 border-ai-300 ring-2 ring-ai-100 dark:ring-ai-900 shadow-sm"
                    : "bg-bg-muted/40 text-text-muted border-border-subtle/40"
                )}
                title={label}
              >
                <span
                  className={cn(
                    "w-1.5 h-1.5 rounded-full shrink-0",
                    done
                      ? "bg-success-500"
                      : active
                      ? "bg-ai-500 animate-pulse"
                      : "bg-border-default"
                  )}
                />
                <span className="truncate max-w-[90px]">{label}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Collapsible Execution Inspector */}
      {expanded && (
        <div className="mt-3.5 pt-3 border-t border-border-subtle/60 max-h-64 overflow-y-auto pr-1 space-y-2">
          {steps.length === 0 && tools.length === 0 && !currentPhase && (
            <p className="text-xs text-text-muted">
              Waiting for the agent to accept the request…
            </p>
          )}

          {stagesToRender.map((phase) => {
            const isActive = phase === currentPhase && !terminal;
            const label = PHASE_LABELS[phase] || phase.replace(/_/g, " ");
            const matching = steps.filter(
              (s) => (s.phase || s.step_type) === phase
            );
            const labels = matching
              .map(stepSummaryLabel)
              .filter(Boolean);
            return (
              <div key={phase} className="flex items-start gap-2.5 text-sm p-1.5 rounded-xl hover:bg-bg-muted/40 transition-colors">
                {isActive ? (
                  <span className="relative w-4 h-4 mt-0.5 shrink-0 flex items-center justify-center">
                    <span className="absolute inset-0 rounded-full bg-ai-500 opacity-40 animate-ping" />
                    <span className="relative w-2 h-2 rounded-full bg-ai-500 animate-quantum-pulse" />
                  </span>
                ) : (
                  <CheckCircle2 className="w-4 h-4 mt-0.5 text-success-500 shrink-0" />
                )}
                <div className="min-w-0">
                  <span
                    className={cn(
                      isActive
                        ? "text-text-primary font-semibold"
                        : "text-text-secondary font-medium"
                    )}
                  >
                    {label}
                  </span>
                  {labels.length > 0 && (
                    <p className="text-xs text-text-muted mt-0.5 break-words">
                      {labels[0]}
                    </p>
                  )}
                </div>
              </div>
            );
          })}

          {tools.length > 0 && (
            <div className="text-xs text-text-muted pt-2 border-t border-border-subtle/50">
              <span className="font-semibold text-text-secondary">
                Trusted tools utilized:{" "}
              </span>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {tools.map((t) => (
                  <span
                    key={t.tool}
                    className="px-2 py-0.5 rounded-md bg-bg-muted text-[11px] font-mono text-text-secondary border border-border-subtle"
                  >
                    {t.tool.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
