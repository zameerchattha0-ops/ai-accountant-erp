"use client";

import { Check, BrainCircuit, Sparkles, Clock, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import type { IntentProgression } from "@/lib/types/api";

interface Props {
  progression?: IntentProgression | null;
  className?: string;
}

export default function IntentProgressionTracker({ progression, className }: Props) {
  if (!progression || (!progression.verified_facts?.length && !progression.active_reasoning)) {
    return null;
  }

  const { status, verified_facts, active_reasoning, missing_info, intent } = progression;

  const isCompleted = status === "completed";
  const isReviewing = status === "reviewing";
  const isClarifying = status === "clarifying" || (!isCompleted && !isReviewing);
  const isNonPostingOrder = [
    "create_purchase_order",
    "update_purchase_order_status",
    "create_quotation",
    "create_sales_order",
  ].includes((intent ?? "").toLowerCase());

  const statusBadge = isCompleted
    ? {
        label: isNonPostingOrder ? "Order Recorded" : "Posted & Reconciled",
        className: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800",
        icon: Check,
      }
    : isReviewing
    ? {
        label: "Ready for Confirmation",
        className: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800",
        icon: Sparkles,
      }
    : {
        label: "Gathering Verified Details",
        className: "bg-ai-50 text-ai-700 border-ai-200 dark:bg-ai-950/40 dark:text-ai-300 dark:border-ai-800",
        icon: Clock,
      };

  const StatusIcon = statusBadge.icon;

  return (
    <div
      className={cn(
        "rounded-xl border bg-bg-surface/90 backdrop-blur-xs p-2.5 sm:p-3 shadow-2xs transition-all duration-200",
        isCompleted
          ? "border-emerald-200/80 bg-emerald-50/20"
          : isReviewing
          ? "border-blue-200/80 bg-blue-50/20"
          : "border-border-default hover:border-ai-200",
        className
      )}
    >
      {/* Header Bar */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
          <BrainCircuit className="w-3.5 h-3.5 text-ai-600 shrink-0" />
          <span>Verified Intent Progression</span>
        </div>

        <span
          className={cn(
            "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border shadow-3xs",
            statusBadge.className
          )}
        >
          <StatusIcon className="w-3 h-3 shrink-0" />
          <span>{statusBadge.label}</span>
        </span>
      </div>

      {/* Verified Facts Pills Grid */}
      {verified_facts && verified_facts.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          {verified_facts.map((fact, idx) => (
            <div
              key={`${fact.label}-${idx}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-bg-muted border border-border-subtle text-[11px] text-text-secondary shadow-3xs"
            >
              <Check className="w-2.5 h-2.5 text-emerald-600 shrink-0 stroke-[2.5]" />
              <span className="font-medium text-text-primary">{fact.label}:</span>
              <span className="truncate max-w-[140px] sm:max-w-[200px] font-mono text-[10.5px]">
                {fact.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Active Reasoning Box */}
      {active_reasoning && (
        <div className="text-[11.5px] leading-relaxed text-text-secondary bg-bg-surface/60 rounded-lg px-2.5 py-1.5 border border-border-subtle/60 flex items-start gap-1.5">
          <span className="font-semibold text-ai-700 shrink-0 text-[11px]">Reasoning:</span>
          <span className="line-clamp-2 text-text-muted">{active_reasoning}</span>
        </div>
      )}

      {/* Next Information Needed (When Clarifying) */}
      {isClarifying && missing_info && (
        <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-amber-700 dark:text-amber-300 font-medium px-1">
          <AlertCircle className="w-3 h-3 text-amber-600 shrink-0" />
          <span className="truncate">
            <span className="font-semibold">Next Detail:</span> {missing_info}
          </span>
        </div>
      )}
    </div>
  );
}
