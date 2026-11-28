"use client";

import React, { useState } from "react";
import {
  Layers,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Sparkles,
  CheckCircle2,
  Play,
  Edit3,
  AlertTriangle,
  Brain,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import type {
  LivingDraft,
  ActionButton as ActionButtonType,
} from "@/lib/types/api";

interface LivingDraftCardProps {
  draft: LivingDraft;
  className?: string;
  defaultExpanded?: boolean;
  onAction?: (actionType: string, payload: Record<string, unknown>) => void;
  disabled?: boolean;
}

export default function LivingDraftCard({
  draft,
  className,
  defaultExpanded = true,
  onAction,
  disabled = false,
}: LivingDraftCardProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [showProvisionalEntries, setShowProvisionalEntries] = useState(false);

  // Extract interactive controls if attached
  const artifact = draft?.interactive_artifact;
  const btnCtrl = artifact?.controls?.find((c) => c.control_type === "action_button_group");

  if (!draft) return null;

  const stage = draft.progression_stage || (
    draft.status === "posted"
      ? "posted"
      : draft.status === "ready_for_confirmation"
      ? "ready_for_execution"
      : draft.missing_fields && draft.missing_fields.length > 0
      ? "fact_gathering"
      : "reasoning"
  );

  const isReady = stage === "ready_for_execution" || stage === "posted";

  const stageHeaderInfo = {
    fact_gathering: {
      stepBadge: "Gathering Context",
      title: "Fact Verification & Scoping",
      subtitle: "Verifying facts from your instructions and live records — no assumptions made.",
      color: "bg-amber-500/10 text-amber-600 border-amber-500/20",
    },
    reasoning: {
      stepBadge: "Reasoning",
      title: "Accounting Reasoning & Standards",
      subtitle: "Evaluating economic reality and statutory compliance (IAS 16, Section 73, Section 153).",
      color: "bg-blue-500/10 text-blue-600 border-blue-500/20",
    },
    ready_for_execution: {
      stepBadge: "Ready to Post",
      title: "Balanced Voucher Ready to Post",
      subtitle: "All accounting requirements authenticated. Ready for General Ledger execution.",
      color: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
    },
    posted: {
      stepBadge: "Finalized",
      title: "Posted to General Ledger",
      subtitle: "Double-entry voucher posted and verified against company books.",
      color: "bg-purple-500/10 text-purple-600 border-purple-500/20",
    },
  }[stage] || {
    stepBadge: "Live",
    title: "Accounting Progression",
    subtitle: "Real-time accounting evaluation.",
    color: "bg-ai-500/10 text-ai-600 border-ai-500/20",
  };

  const formattedAmount =
    typeof draft.total_amount === "number"
      ? `PKR ${draft.total_amount.toLocaleString("en-PK", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`
      : "Amount Pending";

  const handleButtonClick = (btn: ActionButtonType) => {
    if (disabled) return;
    if (btn.requires_confirmation && btn.confirmation_message) {
      if (!window.confirm(btn.confirmation_message)) return;
    }
    onAction?.("trigger_button", { action_id: btn.action_id });
  };

  return (
    <div
      className={cn(
        "rounded-2xl border border-border-default bg-bg-surface shadow-sm overflow-hidden transition-all duration-200",
        className
      )}
    >
      {/* 1. PROGRESSION HEADER */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-bg-muted/40 cursor-pointer select-none border-b border-border-subtle"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-1.5 rounded-lg bg-ai-500/10 border border-ai-500/20 text-ai-600 shrink-0">
            <Brain className="w-4 h-4" />
          </div>
          <div className="truncate">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-mono font-medium border uppercase tracking-wider", stageHeaderInfo.color)}>
                {stageHeaderInfo.stepBadge}
              </span>
              <span className="text-xs font-semibold text-text-primary truncate">
                {stageHeaderInfo.title}
              </span>
            </div>
            <p className="text-[11px] text-text-secondary truncate mt-0.5">
              {stageHeaderInfo.subtitle}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {formattedAmount !== "Amount Pending" && (
            <span className="text-xs font-mono font-semibold text-text-primary hidden sm:inline">
              {formattedAmount}
            </span>
          )}
          <button
            type="button"
            className="p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-bg-muted transition-colors"
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {isExpanded && (
        <div className="p-4 space-y-4 text-xs text-text-secondary">
          {/* ESTABLISHED & FINALIZED FACTS (Green checks — strictly facts confirmed from user) */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 font-semibold text-text-primary text-[11px]">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
              <span>Established Facts (Verified from your input)</span>
            </div>

            {draft.finalized_facts && draft.finalized_facts.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {draft.finalized_facts.map((fact, idx) => (
                  <div key={idx} className="p-2.5 rounded-xl bg-emerald-50/40 border border-emerald-200/60 dark:bg-emerald-950/20 dark:border-emerald-800/40">
                    <span className="text-[10px] text-emerald-700 dark:text-emerald-400 block font-medium">
                      ✓ {fact.label}
                    </span>
                    <p className="font-semibold text-text-primary mt-0.5 truncate text-[11px]">
                      {fact.value}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-2.5 rounded-xl bg-bg-muted/40 border border-border-subtle text-[11px] text-text-muted">
                Extracting facts from initial instruction...
              </div>
            )}
          </div>

          {/* ACTIVE ACCOUNTING REASONING (Standards, Rules & Governance) */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 font-semibold text-text-primary text-[11px]">
              <Sparkles className="w-3.5 h-3.5 text-ai-600" />
              <span>Active Accounting Reasoning & Standards</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {draft.reasoning_steps && draft.reasoning_steps.length > 0 ? (
                draft.reasoning_steps.map((step, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded-xl bg-ai-50/40 border border-ai-200/60 dark:bg-ai-950/20 dark:border-ai-800/40 space-y-1"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-semibold text-ai-800 dark:text-ai-300">
                        {step.title}
                      </span>
                      <span
                        className={cn(
                          "px-1.5 py-0.2 rounded text-[9px] font-mono font-medium uppercase",
                          step.status === "completed" || step.status === "compliant"
                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                            : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                        )}
                      >
                        {step.status}
                      </span>
                    </div>
                    <p className="text-[10px] text-text-secondary leading-normal">
                      {step.description}
                    </p>
                  </div>
                ))
              ) : (
                <div className="p-2.5 rounded-xl bg-bg-muted/40 border border-border-subtle text-[11px] text-text-muted col-span-2">
                  Evaluating double-entry rules and statutory thresholds...
                </div>
              )}
            </div>
          </div>

          {/* PENDING REQUIREMENTS (Remaining open accounting decisions) */}
          {draft.pending_requirements && draft.pending_requirements.length > 0 && !isReady && (
            <div className="space-y-1.5 p-3 rounded-xl bg-amber-50/60 border border-amber-200/80 dark:bg-amber-950/20 dark:border-amber-800/40">
              <div className="flex items-center gap-1.5 font-semibold text-amber-900 dark:text-amber-300 text-[11px]">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                <span>Open Accounting Decisions</span>
              </div>
              <p className="text-[10px] text-amber-800 dark:text-amber-300/80">
                The transaction cannot be posted with assumptions. Please provide answers to:
              </p>
              <ul className="list-disc list-inside space-y-0.5 text-[11px] text-amber-950 dark:text-amber-200 font-medium pt-0.5">
                {draft.pending_requirements.map((req, idx) => (
                  <li key={idx} className="leading-snug">{req}</li>
                ))}
              </ul>
            </div>
          )}

          {/* STEP 4: FINAL BALANCED VOUCHER OR COLLAPSIBLE PROVISIONAL PREVIEW */}
          {isReady ? (
            <div className="space-y-2 pt-1 border-t border-border-subtle">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-semibold text-text-primary text-[11px]">
                  <Layers className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Final Double-Entry Journal Voucher</span>
                </div>
                <span className="text-[10px] font-mono font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                  Balanced (DR = CR)
                </span>
              </div>

              {draft.voucher_preview && draft.voucher_preview.length > 0 && (
                <div className="rounded-xl border border-border-default overflow-hidden bg-bg-surface">
                  <table className="w-full text-left text-[11px] divide-y divide-border-subtle">
                    <thead className="bg-bg-muted/60 text-text-muted font-medium">
                      <tr>
                        <th className="py-1.5 px-3">Account Head</th>
                        <th className="py-1.5 px-3 text-right">Debit (PKR)</th>
                        <th className="py-1.5 px-3 text-right">Credit (PKR)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle font-mono">
                      {draft.voucher_preview.map((line, idx) => (
                        <tr key={idx} className="hover:bg-bg-muted/20">
                          <td className="py-1.5 px-3 font-sans text-text-primary">
                            <div className="font-medium">{line.account_name}</div>
                            {line.description && (
                              <div className="text-[10px] text-text-muted truncate max-w-xs">
                                {line.description}
                              </div>
                            )}
                          </td>
                          <td className="py-1.5 px-3 text-right text-text-primary">
                            {line.debit > 0
                              ? line.debit.toLocaleString("en-PK", { minimumFractionDigits: 2 })
                              : "-"}
                          </td>
                          <td className="py-1.5 px-3 text-right text-text-primary">
                            {line.credit > 0
                              ? line.credit.toLocaleString("en-PK", { minimumFractionDigits: 2 })
                              : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            /* During fact-gathering, keep provisional voucher preview optional/collapsible so user isn't misled */
            draft.voucher_preview && draft.voucher_preview.length > 0 && (
              <div className="pt-1 border-t border-border-subtle">
                <button
                  type="button"
                  onClick={() => setShowProvisionalEntries(!showProvisionalEntries)}
                  className="flex items-center justify-between w-full p-2 rounded-xl bg-bg-muted/30 hover:bg-bg-muted/60 border border-border-subtle text-[11px] text-text-muted hover:text-text-primary transition-colors"
                >
                  <span className="flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-text-muted" />
                    <span>View Estimated Journal Impact (Pending Clarifications)</span>
                  </span>
                  <span className="text-[10px] font-mono">
                    {showProvisionalEntries ? "Hide" : "Show"}
                  </span>
                </button>

                {showProvisionalEntries && (
                  <div className="mt-2 rounded-xl border border-border-default overflow-hidden bg-bg-surface animate-in fade-in duration-150">
                    <table className="w-full text-left text-[11px] divide-y divide-border-subtle">
                      <thead className="bg-bg-muted/60 text-text-muted font-medium">
                        <tr>
                          <th className="py-1.5 px-3">Account Head</th>
                          <th className="py-1.5 px-3 text-right">Debit (PKR)</th>
                          <th className="py-1.5 px-3 text-right">Credit (PKR)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border-subtle font-mono">
                        {draft.voucher_preview.map((line, idx) => (
                          <tr key={idx} className="hover:bg-bg-muted/20">
                            <td className="py-1.5 px-3 font-sans text-text-primary">
                              <div>{line.account_name}</div>
                            </td>
                            <td className="py-1.5 px-3 text-right text-text-primary">
                              {line.debit > 0
                                ? line.debit.toLocaleString("en-PK", { minimumFractionDigits: 2 })
                                : "-"}
                            </td>
                            <td className="py-1.5 px-3 text-right text-text-primary">
                              {line.credit > 0
                                ? line.credit.toLocaleString("en-PK", { minimumFractionDigits: 2 })
                                : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )
          )}

          {/* Statutory Compliance Notes */}
          {draft.compliance_notes && draft.compliance_notes.length > 0 && (
            <div className="space-y-1 pt-1">
              {draft.compliance_notes.map((note, idx) => (
                <div
                  key={idx}
                  className={cn(
                    "p-2 rounded-lg text-[11px] leading-relaxed flex items-start gap-1.5",
                    note.includes("⚠️")
                      ? "bg-amber-50 text-amber-800 border border-amber-200 dark:bg-amber-950/20 dark:border-amber-800/40 dark:text-amber-300"
                      : "bg-emerald-50 text-emerald-800 border border-emerald-200 dark:bg-emerald-950/20 dark:border-emerald-800/40 dark:text-emerald-300"
                  )}
                >
                  <ShieldCheck className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>{note}</span>
                </div>
              ))}
            </div>
          )}

          {/* Action Buttons (e.g. Post to Ledger, Modify) */}
          {btnCtrl?.buttons && btnCtrl.buttons.length > 0 && (
            <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-subtle">
              {btnCtrl.buttons.map((btn) => (
                <button
                  key={btn.action_id}
                  type="button"
                  disabled={disabled || !btn.enabled}
                  onClick={() => handleButtonClick(btn)}
                  className={cn(
                    "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5 shadow-2xs",
                    btn.variant === "primary"
                      ? "bg-ai-600 hover:bg-ai-700 text-white"
                      : btn.variant === "secondary"
                      ? "bg-bg-muted hover:bg-border-default text-text-primary"
                      : "bg-bg-surface border border-border-default hover:bg-bg-muted text-text-secondary"
                  )}
                >
                  {btn.action_id === "post_to_ledger" && <CheckCircle2 className="w-3.5 h-3.5" />}
                  {btn.action_id === "modify_terms" && <Edit3 className="w-3.5 h-3.5" />}
                  {btn.action_id === "run_scenario" && <Play className="w-3.5 h-3.5" />}
                  <span>{btn.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
