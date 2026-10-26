"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import {
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Sparkles,
  Cpu,
  ShieldCheck,
  Zap,
  Activity,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils/cn";
import { aiProgress } from "@/lib/api/client";
import { agentRunStore } from "@/lib/agent/agentRunStore";
import type { AgentProgress, ProgressStep } from "@/lib/types/api";

// Adaptive fast polling: 500ms for fast feedback, ceiling at 10 minutes.
const FAST_POLL_MS = 500;
const NORMAL_POLL_MS = 900;
const POLL_DEADLINE_MS = 10 * 60 * 1000;

const PHASE_LABELS: Record<string, string> = {
  RECEIVED: "Request Received",
  INTERPRETING: "Cognitive Perception",
  PLANNING: "Intelligent Reasoning",
  CONTEXT_LOADING: "Loading ERP Context",
  AWAITING_CLARIFICATION: "Clarification Needed",
  AWAITING_CONFIRMATION: "Awaiting Approval",
  EXECUTING: "Executing Trusted Tools",
  VALIDATING: "Rule Verification",
  VERIFYING: "Verifying Database State",
  COMPLETED: "Operation Completed",
  FAILED: "Execution Failed",
  CANCELLED: "Cancelled",
  REJECTED: "Rejected",
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

const PHASE_THEMES: Record<
  string,
  {
    ring: string;
    core: string;
    glow: string;
    badge: string;
    text: string;
    icon: typeof Sparkles;
  }
> = {
  RECEIVED: {
    ring: "border-sky-400/60",
    core: "bg-sky-500",
    glow: "from-sky-500/20 via-blue-500/10 to-indigo-500/20",
    badge: "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-400/30",
    text: "text-sky-600 dark:text-sky-400",
    icon: Zap,
  },
  INTERPRETING: {
    ring: "border-violet-400/70",
    core: "bg-violet-500",
    glow: "from-violet-500/25 via-purple-500/15 to-indigo-500/20",
    badge: "bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-400/30",
    text: "text-violet-600 dark:text-violet-400",
    icon: Cpu,
  },
  PLANNING: {
    ring: "border-purple-400/70",
    core: "bg-purple-500",
    glow: "from-purple-500/25 via-fuchsia-500/15 to-pink-500/20",
    badge: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-400/30",
    text: "text-purple-600 dark:text-purple-400",
    icon: Sparkles,
  },
  CONTEXT_LOADING: {
    ring: "border-amber-400/70",
    core: "bg-amber-500",
    glow: "from-amber-500/25 via-yellow-500/15 to-orange-500/20",
    badge: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-400/30",
    text: "text-amber-600 dark:text-amber-400",
    icon: Activity,
  },
  EXECUTING: {
    ring: "border-emerald-400/70",
    core: "bg-emerald-500",
    glow: "from-emerald-500/25 via-teal-500/15 to-cyan-500/20",
    badge: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-400/30",
    text: "text-emerald-600 dark:text-emerald-400",
    icon: Zap,
  },
  VALIDATING: {
    ring: "border-cyan-400/70",
    core: "bg-cyan-500",
    glow: "from-cyan-500/25 via-sky-500/15 to-blue-500/20",
    badge: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-400/30",
    text: "text-cyan-600 dark:text-cyan-400",
    icon: ShieldCheck,
  },
  VERIFYING: {
    ring: "border-indigo-400/70",
    core: "bg-indigo-500",
    glow: "from-indigo-500/25 via-blue-500/15 to-violet-500/20",
    badge: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-400/30",
    text: "text-indigo-600 dark:text-indigo-400",
    icon: ShieldCheck,
  },
  COMPLETED: {
    ring: "border-emerald-500",
    core: "bg-emerald-500",
    glow: "from-emerald-500/20 to-teal-500/10",
    badge: "bg-emerald-500/10 text-emerald-600 border-emerald-400/30",
    text: "text-emerald-600 dark:text-emerald-400",
    icon: CheckCircle2,
  },
};

const PHASE_THOUGHTS: Record<string, string[]> = {
  RECEIVED: [
    "Receiving query into AI dispatch…",
    "Allocating execution session…",
  ],
  INTERPRETING: [
    "Analyzing natural language intent across 14 ERP modules…",
    "Extracting semantic entities & literal facts…",
    "Auditing parameter completeness against ERP schema…",
    "Evaluating anti-blind-assumption invariants…",
  ],
  PLANNING: [
    "Synthesizing modular tool execution plan…",
    "Verifying operational bounds (zero-journal impact)…",
    "Formulating targeted parameter verification…",
    "Checking Chart of Accounts and catalog references…",
  ],
  CONTEXT_LOADING: [
    "Fetching live ledger structure & party records…",
    "Correlating customer, supplier and bank registry…",
    "Aligning fiscal context and master data…",
  ],
  AWAITING_CLARIFICATION: [
    "Targeted clarification questions prepared…",
    "Awaiting your input to continue…",
  ],
  AWAITING_CONFIRMATION: [
    "Plan formulated. Awaiting your approval…",
  ],
  EXECUTING: [
    "Executing atomic ERP tool mutations…",
    "Persisting master data without side effects…",
    "Updating modular ledger cards in real time…",
  ],
  VALIDATING: [
    "Validating double-entry balance and constraints…",
    "Auditing schema rules and idempotency tokens…",
  ],
  VERIFYING: [
    "Verifying committed database state…",
    "Finalizing module route and breadcrumbs…",
  ],
  COMPLETED: ["Ready. Execution completed successfully."],
  FAILED: ["Execution halted. Reviewing error diagnostic."],
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
  liveSteps?: LiveStepEvent[];
}) {
  const [progress, setProgress] = useState<AgentProgress | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [thoughtIdx, setThoughtIdx] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);

  const { cancelling } = useSyncExternalStore(
    agentRunStore.subscribe,
    agentRunStore.getSnapshot,
    agentRunStore.getSnapshot
  );

  // Smooth millisecond-level elapsed timer for high-precision live telemetry
  useEffect(() => {
    const start = performance.now();
    const timer = setInterval(() => {
      setElapsedMs(Math.round(performance.now() - start));
    }, 100);
    return () => clearInterval(timer);
  }, []);

  // Thought cycle
  useEffect(() => {
    const t = setInterval(() => {
      setThoughtIdx((i) => i + 1);
    }, 1400);
    return () => clearInterval(t);
  }, []);

  // Adaptive fast polling with backoff
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
        const done = next.status && TERMINAL_STATUSES.includes(next.status);
        if (done && next.steps.length > 0) {
          setExpanded(true);
          return;
        }
      } catch {
        // Degrade smoothly
      }
      if (!cancelled && Date.now() < deadline) {
        // Fast polling in the first 4 seconds, then smooth normal polling
        const pollInterval = elapsedMs < 4000 ? FAST_POLL_MS : NORMAL_POLL_MS;
        timer = setTimeout(tick, pollInterval);
      }
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [conversationId, liveSteps, elapsedMs]);

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
    : progress?.current_phase || "INTERPRETING";
  const terminal = Boolean(
    progress?.status && TERMINAL_STATUSES.includes(progress.status)
  );

  const phasesWithEvidence = new Set<string>();
  for (const step of steps) {
    const phase = step.phase || step.step_type;
    if (phase) phasesWithEvidence.add(phase);
  }
  if (currentPhase) phasesWithEvidence.add(currentPhase);
  const stagesToRender = PHASE_ORDER.filter(
    (p) => phasesWithEvidence.has(p) && p !== "RECEIVED"
  );

  const theme = PHASE_THEMES[currentPhase ?? "INTERPRETING"] ?? PHASE_THEMES.INTERPRETING;
  const thoughts = PHASE_THOUGHTS[currentPhase ?? ""] ?? ["Reasoning with AI model…"];
  const currentThought = thoughts[thoughtIdx % thoughts.length];
  const stepIndex = currentPhase ? PHASE_ORDER.indexOf(currentPhase) : 1;
  const elapsedSec = (elapsedMs / 1000).toFixed(1);

  return (
    <div className="relative group overflow-hidden rounded-2xl p-[1px] transition-all duration-500">
      {/* Dynamic Ambient Iridescent Glow */}
      <div
        className={cn(
          "absolute -inset-1 rounded-2xl bg-gradient-to-r opacity-40 blur-xl transition-all duration-700 animate-pulse",
          theme.glow
        )}
      />

      {/* Main Glassmorphic Panel */}
      <div className="relative rounded-2xl backdrop-blur-2xl bg-white/80 dark:bg-slate-900/85 border border-white/60 dark:border-white/10 shadow-[0_12px_40px_rgba(0,0,0,0.06),0_1px_3px_rgba(0,0,0,0.04)] p-4 sm:p-5 text-text-primary">
        
        {/* Top Telemetry Ribbon */}
        <div className="flex items-center justify-between gap-2 pb-3 mb-3 border-b border-black/[0.04] dark:border-white/[0.06]">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Live Status Pill */}
            <span
              className={cn(
                "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold tracking-wide border shadow-sm backdrop-blur-md",
                theme.badge
              )}
            >
              <span className="relative flex h-2 w-2">
                {!terminal && (
                  <span
                    className={cn(
                      "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75",
                      theme.core
                    )}
                  />
                )}
                <span
                  className={cn(
                    "relative inline-flex rounded-full h-2 w-2",
                    terminal ? "bg-emerald-500" : theme.core
                  )}
                />
              </span>
              {PHASE_LABELS[currentPhase] || currentPhase}
            </span>

            {/* Anti-Assumption Guard Tag */}
            <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium text-slate-600 dark:text-slate-300 bg-slate-100/80 dark:bg-slate-800/80 border border-slate-200/60 dark:border-slate-700/60">
              <ShieldCheck className="w-3 h-3 text-emerald-500" />
              Anti-Assumption Guard
            </span>
          </div>

          {/* Live Execution Clock + Cancel Button */}
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-slate-500 dark:text-slate-400">
              <Activity className="w-3.5 h-3.5 text-ai-500 animate-pulse" />
              {elapsedSec}s
            </span>

            {!terminal && (
              <button
                type="button"
                onClick={() => void agentRunStore.cancel()}
                disabled={cancelling}
                aria-label="Cancel this request"
                className="px-2.5 py-1 rounded-lg text-[11px] font-semibold uppercase tracking-wider text-rose-600 dark:text-rose-400 border border-rose-200/80 dark:border-rose-900/60 hover:bg-rose-50/80 dark:hover:bg-rose-950/40 transition-colors disabled:opacity-50"
              >
                {cancelling ? "Halting…" : "Cancel"}
              </button>
            )}
          </div>
        </div>

        {/* Central Neural Working Stage */}
        <div className="flex items-center gap-3.5 sm:gap-4">
          {/* Holographic Neural Reactor Core */}
          <div className="relative w-11 h-11 shrink-0 flex items-center justify-center">
            {terminal && progress?.status === "COMPLETED" ? (
              <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-500 shadow-lg shadow-emerald-500/20">
                <CheckCircle2 className="w-6 h-6 animate-scale-in" />
              </div>
            ) : terminal ? (
              <div className="w-10 h-10 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-500">
                <XCircle className="w-6 h-6" />
              </div>
            ) : (
              <>
                {/* Outer Iridescent Spinning Ring */}
                <div
                  className={cn(
                    "absolute inset-0 rounded-full border-2 border-dashed animate-[spin_5s_linear_infinite]",
                    theme.ring
                  )}
                />
                {/* Inner Counter-Rotating Orbital Ring */}
                <div className="absolute inset-1.5 rounded-full border border-t-ai-500 border-r-purple-500 border-b-transparent border-l-transparent animate-[spin_2.2s_linear_infinite_reverse]" />
                {/* Glowing Core Crystal */}
                <div
                  className={cn(
                    "relative w-4 h-4 rounded-full shadow-lg transition-transform duration-300 animate-pulse",
                    theme.core
                  )}
                >
                  <div className="absolute inset-0.5 rounded-full bg-white/40 blur-[1px]" />
                </div>
              </>
            )}
          </div>

          {/* Real-time Thought Stream & Status */}
          <div className="flex-1 min-w-0">
            {terminal ? (
              <div>
                <p className="font-semibold text-sm text-text-primary">
                  Task Execution Finished
                </p>
                <p className="text-xs text-text-secondary mt-0.5">
                  All validation and ledger rules satisfied.
                </p>
              </div>
            ) : (
              <div>
                {/* Animated Rotating Thought Stream */}
                <div className="overflow-hidden min-h-[22px]">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={currentThought}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -6 }}
                      transition={{ duration: 0.28, ease: "easeOut" }}
                      className={cn("text-sm font-semibold tracking-tight", theme.text)}
                    >
                      {currentThought}
                    </motion.div>
                  </AnimatePresence>
                </div>
                <div className="flex items-center gap-2 mt-0.5 text-[11px] text-text-muted">
                  <span>Direct Modular Dispatch</span>
                  <span>·</span>
                  <span className="font-mono">Live Grounding Active</span>
                </div>
              </div>
            )}
          </div>

          {/* Expand Details Trigger */}
          <button
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="p-1.5 rounded-xl text-text-muted hover:text-text-primary hover:bg-black/5 dark:hover:bg-white/5 transition-colors shrink-0"
            title="Inspect execution trace"
          >
            {expanded ? (
              <ChevronDown className="w-5 h-5" />
            ) : (
              <ChevronRight className="w-5 h-5" />
            )}
          </button>
        </div>

        {/* Luminous Light-Beam Pipeline Stepper */}
        {!terminal && stepIndex >= 0 && (
          <div className="mt-4 pt-3 border-t border-black/[0.03] dark:border-white/[0.04]">
            <div className="flex items-center gap-0">
              {PHASE_ORDER.slice(0, -1).map((phase, i) => {
                const isDone = i < stepIndex;
                const isActive = phase === currentPhase;
                const stageTheme = PHASE_THEMES[phase] ?? PHASE_THEMES.RECEIVED;
                return (
                  <div key={phase} className="flex items-center flex-1 last:flex-none">
                    {/* Stepper Node */}
                    <div
                      className={cn(
                        "relative flex items-center justify-center transition-all duration-300",
                        isActive ? "scale-125 z-10" : "scale-100"
                      )}
                      title={PHASE_LABELS[phase]}
                    >
                      {isActive && (
                        <span
                          className={cn(
                            "absolute inset-0 rounded-full animate-ping opacity-60",
                            stageTheme.core
                          )}
                        />
                      )}
                      <div
                        className={cn(
                          "w-2.5 h-2.5 rounded-full transition-all duration-300",
                          isDone && "bg-emerald-500 shadow-sm shadow-emerald-500/50",
                          isActive && cn(stageTheme.core, "ring-4 ring-ai-500/20 shadow-md"),
                          !isDone && !isActive && "bg-slate-200 dark:bg-slate-700"
                        )}
                      />
                    </div>

                    {/* Stepper Connector Bar */}
                    {i < PHASE_ORDER.length - 2 && (
                      <div className="h-[2px] flex-1 mx-1 rounded-full overflow-hidden bg-slate-100 dark:bg-slate-800">
                        <div
                          className={cn(
                            "h-full transition-all duration-500",
                            isDone
                              ? "w-full bg-gradient-to-r from-emerald-400 to-emerald-500"
                              : isActive
                              ? "w-1/2 bg-gradient-to-r from-ai-500 to-purple-500 animate-pulse"
                              : "w-0"
                          )}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Interactive Expandable Execution Trace */}
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25 }}
              className="overflow-hidden"
            >
              <div className="mt-4 pt-3 border-t border-black/[0.05] dark:border-white/[0.08] max-h-60 overflow-y-auto space-y-2.5 pr-1">
                {steps.length === 0 && tools.length === 0 && !currentPhase && (
                  <p className="text-xs text-text-muted">
                    Connecting to agent dispatch and initializing workspace…
                  </p>
                )}

                {stagesToRender.map((phase) => {
                  const isActive = phase === currentPhase && !terminal;
                  const label = PHASE_LABELS[phase] || phase.replace(/_/g, " ");
                  const matching = steps.filter(
                    (s) => (s.phase || s.step_type) === phase
                  );
                  const labels = matching.map(stepSummaryLabel).filter(Boolean);

                  return (
                    <div
                      key={phase}
                      className={cn(
                        "p-2.5 rounded-xl border transition-all text-xs flex items-start gap-2.5",
                        isActive
                          ? "bg-ai-500/5 border-ai-500/20 shadow-sm"
                          : "bg-black/[0.02] dark:bg-white/[0.02] border-transparent"
                      )}
                    >
                      {isActive ? (
                        <span className="relative w-3.5 h-3.5 mt-0.5 shrink-0 flex items-center justify-center">
                          <span className="absolute inset-0 rounded-full bg-ai-500 opacity-40 animate-ping" />
                          <span className="relative w-2 h-2 rounded-full bg-ai-500" />
                        </span>
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-500 shrink-0" />
                      )}
                      <div className="min-w-0 flex-1">
                        <span
                          className={cn(
                            "font-medium",
                            isActive ? "text-ai-600 dark:text-ai-400" : "text-text-primary"
                          )}
                        >
                          {label}
                        </span>
                        {labels.length > 0 && (
                          <p className="text-text-muted mt-0.5 break-words font-mono text-[11px]">
                            {labels[0]}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}

                {tools.length > 0 && (
                  <div className="text-[11px] text-text-muted pt-2 border-t border-black/[0.04] dark:border-white/[0.06] flex items-center gap-1.5 flex-wrap">
                    <span className="font-semibold text-text-secondary">
                      Trusted tools invoked:
                    </span>
                    {tools.map((t) => (
                      <span
                        key={t.tool}
                        className="px-2 py-0.5 rounded-md bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20 font-mono text-[10px]"
                      >
                        {t.tool}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
