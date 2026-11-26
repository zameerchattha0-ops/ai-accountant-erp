"use client";

import { useMemo } from "react";
import { MessageCircleQuestion, ArrowRight, CornerDownLeft } from "lucide-react";
import { legacyChipOptions } from "@/lib/ai/clarification";
import { mdToDisplayText } from "@/lib/ai/markdown";
import type { QuestionOption } from "@/lib/types/api";

interface Props {
  question: string;
  options?: string[];
  /** backend-emitted options per numbered sub-question */
  questionOptions?: QuestionOption[][];
  onAnswer: (answer: string) => void;
  /** While a resume request is in flight every control is disabled */
  disabled?: boolean;
}

export default function AIClarification({
  question,
  options,
  questionOptions,
  onAnswer,
  disabled = false,
}: Props) {
  // Extract and deduplicate all structured suggestion chips
  const suggestionChips = useMemo(() => {
    const list: Array<{ value: string; label: string }> = [];
    const seen = new Set<string>();

    if (questionOptions && questionOptions.length > 0) {
      for (const group of questionOptions) {
        if (group) {
          for (const opt of group) {
            const val = opt.value || opt.label;
            const norm = val.trim().toLowerCase();
            if (val && !seen.has(norm)) {
              seen.add(norm);
              list.push(opt);
            }
          }
        }
      }
    }

    if (options && options.length > 0) {
      const remaining = legacyChipOptions(options, list);
      for (const opt of remaining) {
        const norm = opt.trim().toLowerCase();
        if (opt && !seen.has(norm)) {
          seen.add(norm);
          list.push({ value: opt, label: opt });
        }
      }
    }

    return list;
  }, [questionOptions, options]);

  return (
    <div className="rounded-2xl border border-ai-200 bg-ai-50/40 p-4 shadow-xs space-y-3 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-ai-900">
          <MessageCircleQuestion className="w-4 h-4 text-ai-600 shrink-0" />
          <span>Accounting Clarification Needed</span>
        </div>
        <span className="text-[10.5px] font-medium px-2 py-0.5 rounded-full bg-ai-100 text-ai-700 border border-ai-200">
          Awaiting Your Reply
        </span>
      </div>

      {/* Conversational Question Text */}
      <div className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap font-normal">
        {mdToDisplayText(question)}
      </div>

      {/* Suggested Quick Options (Tappable Pills) */}
      {suggestionChips.length > 0 && (
        <div className="pt-2 border-t border-ai-100/80 space-y-1.5">
          <div className="text-[11px] font-medium text-text-muted flex items-center gap-1">
            <span>Quick Suggestions (tap to reply or type below):</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {suggestionChips.map((chip, idx) => (
              <button
                key={`${chip.value}-${idx}`}
                type="button"
                disabled={disabled}
                onClick={() => onAnswer(chip.value || chip.label)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-bg-surface hover:bg-ai-100 text-ai-800 border border-ai-200 hover:border-ai-300 transition-all shadow-3xs hover:shadow-2xs active:scale-95 disabled:opacity-50"
              >
                <span>{chip.label}</span>
                <ArrowRight className="w-3 h-3 text-ai-500" />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Helper text pointing to unified command input bar */}
      <div className="text-[11px] text-text-muted flex items-center gap-1 pt-0.5">
        <CornerDownLeft className="w-3 h-3 text-ai-500 shrink-0" />
        <span>Type your response in the command bar below and press Enter.</span>
      </div>
    </div>
  );
}
