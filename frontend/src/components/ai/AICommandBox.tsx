"use client";

import React, { useState, useRef, useCallback, useEffect, useSyncExternalStore } from "react";
import {
  Send,
  Paperclip,
  X,
  Loader2,
  Sparkles,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import type {
  AttachmentRef,
  UserRequest,
} from "@/lib/types/api";
import {
  ALLOWED_UPLOAD_MIMES,
  MAX_UPLOAD_BYTES,
} from "@/lib/types/api";
import { ExecutionStatus } from "@/lib/types/enums";
import {
  agentRunStore,
  USE_BACKGROUND_RUNS,
  type AgentRunState,
} from "@/lib/agent/agentRunStore";
import AIProgress from "./AIProgress";
import AIActionCard from "./AIActionCard";
import AIClarification from "./AIClarification";
import AIConfirmation from "./AIConfirmation";

const PLACEHOLDERS = [
  "Ask anything or record a transaction (e.g. 'Cash purchase of Rs. 25,000')...",
  "Check bank balance or ask 'What is the WHT on IT services?'...",
  "Tell me what happened or upload a receipt to book it...",
  "Show this month's profit or ask 'Is PRA 16% on services?'...",
];

const QUICK_CHIPS = [
  { label: "💰 Cash Position", prompt: "What is our current cash and bank balance across all accounts?" },
  { label: "📊 Net Profit", prompt: "Show me this month's revenue, expenses, and net profit." },
  { label: "📜 WHT Sec 153", prompt: "What are the latest Section 153 withholding tax rates for goods vs IT services?" },
  { label: "🧾 Unpaid Bills", prompt: "Show me all outstanding supplier bills and upcoming due dates." },
];

export default function AICommandBox() {
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  useEffect(() => {
    setPlaceholderIdx(Math.floor(Math.random() * PLACEHOLDERS.length));
  }, []);

  const [message, setMessage] = useState("");
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const run: AgentRunState = useSyncExternalStore(
    agentRunStore.subscribe,
    agentRunStore.getSnapshot,
    agentRunStore.getSnapshot
  );
  const {
    loading,
    response,
    error,
    notice,
    liveSteps,
    activeRequestId,
    reattached,
    stalledJobId,
  } = run;

  // Boot reattach watcher once per session
  useEffect(() => {
    agentRunStore.ensureReattach();
  }, []);

  const autoGrow = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
    }
  }, []);

  const buildRequest = useCallback(
    (customText?: string): UserRequest => ({
      message: (customText ?? message).trim(),
      attachments: attachments.length > 0 ? attachments : undefined,
    }),
    [message, attachments]
  );

  const handleSend = async (customText?: string) => {
    const textToSend = (customText ?? message).trim();
    if (!textToSend && attachments.length === 0) return;
    const req = buildRequest(textToSend);
    setMessage("");
    setAttachments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    await agentRunStore.startRun(req);
  };

  const handleClarify = async (answer: string) => {
    await agentRunStore.clarify(answer);
  };

  const handleConfirm = async (approved: boolean, notes?: string) => {
    await agentRunStore.confirm(approved, notes);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleDismissResult = () => {
    agentRunStore.clearResponse();
  };

  return (
    <div className="w-full max-w-4xl mx-auto space-y-3">
      {/* Sleek, Compact Hero Input Bar */}
      <div className="glass rounded-2xl p-1.5 shadow-md border border-border-default hover:border-ai-300 focus-within:border-ai-400 focus-within:ring-2 focus-within:ring-ai-100 transition-all bg-bg-surface">
        <div className="flex items-start gap-2.5 px-3 py-1.5">
          <div className="p-1.5 text-ai-500 shrink-0 mt-0.5">
            <Sparkles className="w-4 h-4" />
          </div>

          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => {
              setMessage(e.target.value);
              autoGrow();
            }}
            onKeyDown={handleKeyDown}
            placeholder={PLACEHOLDERS[placeholderIdx]}
            rows={1}
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted resize-none focus:outline-none py-1 min-h-[38px] max-h-[140px] leading-relaxed"
          />

          {/* Model indicator & Action Controls */}
          <div className="flex items-center gap-1.5 shrink-0 self-center">
            <label
              className="p-2 rounded-xl text-text-muted hover:text-text-secondary hover:bg-bg-muted cursor-pointer transition-colors"
              title="Attach invoice image or receipt"
            >
              <Paperclip className="w-4 h-4" />
              <input
                type="file"
                className="hidden"
                multiple
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  const files = Array.from(e.target.files || []);
                  e.target.value = "";
                  const valid = files.filter((f) => {
                    if (!ALLOWED_UPLOAD_MIMES.has(f.type)) {
                      agentRunStore.setError(`${f.name}: only PNG, JPEG or WEBP images are supported.`);
                      return false;
                    }
                    if (f.size > MAX_UPLOAD_BYTES) {
                      agentRunStore.setError(`${f.name}: file is larger than 8 MB.`);
                      return false;
                    }
                    return true;
                  });

                  valid.forEach((f) => {
                    const reader = new FileReader();
                    reader.onload = () => {
                      const dataUrl = String(reader.result || "");
                      const base64 = dataUrl.split(",")[1] || "";
                      setAttachments((prev) => [
                        ...prev,
                        {
                          file_name: f.name,
                          file_url: URL.createObjectURL(f),
                          mime_type: f.type,
                          file_size: f.size,
                          data_base64: base64,
                        },
                      ]);
                    };
                    reader.readAsDataURL(f);
                  });
                }}
              />
            </label>

            <button
              type="button"
              onClick={() => handleSend()}
              disabled={loading || (!message.trim() && attachments.length === 0)}
              className={cn(
                "btn-3d flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all",
                loading
                  ? "bg-ai-100 text-ai-500 cursor-wait"
                  : "bg-ai-500 hover:bg-ai-600 text-white shadow-2xs"
              )}
            >
              {loading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Thinking</span>
                </>
              ) : (
                <>
                  <Send className="w-3.5 h-3.5" />
                  <span>Ask AI</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Attachment Previews */}
        {attachments.length > 0 && (
          <div className="flex gap-2 px-3 pb-2 flex-wrap">
            {attachments.map((att, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 px-2.5 py-1 bg-bg-muted rounded-lg text-xs text-text-secondary"
              >
                <Paperclip className="w-3 h-3 text-ai-500" />
                <span className="max-w-28 truncate font-mono text-[11px]">{att.file_name}</span>
                <button
                  type="button"
                  onClick={() => setAttachments((a) => a.filter((_, j) => j !== i))}
                  className="text-text-muted hover:text-text-primary"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Quick Prompts Bar (Always Compact & Non-Intrusive) */}
      <div className="flex items-center justify-between gap-2 px-1 flex-wrap">
        <div className="flex items-center gap-1.5 flex-wrap">
          {QUICK_CHIPS.map((chip, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => handleSend(chip.prompt)}
              className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-bg-surface hover:bg-bg-muted border border-border-subtle hover:border-ai-200 text-text-secondary hover:text-text-primary transition-all shadow-3xs"
            >
              {chip.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1 text-[10px] text-text-muted font-mono">
          <Zap className="w-3 h-3 text-emerald-500 fill-emerald-500" />
          <span>Gemini 3.8 Flash</span>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-3 rounded-2xl bg-error-50 border border-error-200 text-xs text-error-700 flex items-center justify-between">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => agentRunStore.clearError()}
            className="text-error-400 hover:text-error-700"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Notice Banner */}
      {notice && !loading && (
        <div className="p-3 rounded-2xl bg-warning-50 border border-warning-200 text-xs text-warning-800 flex items-center justify-between">
          <span>{notice}</span>
          <button
            type="button"
            onClick={() => agentRunStore.dismissNotice()}
            className="text-warning-400 hover:text-warning-700"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Loading Progress (Compact Step Display) */}
      {loading && (
        <div className="space-y-2">
          {reattached && (
            <p className="text-xs text-text-muted">
              Reattached to active run. Real-time updates streaming below:
            </p>
          )}
          <AIProgress
            conversationId={activeRequestId}
            liveSteps={!reattached && !USE_BACKGROUND_RUNS ? liveSteps : undefined}
          />
        </div>
      )}

      {/* Stalled Worker fallback */}
      {stalledJobId && !loading && (
        <div className="p-3 rounded-2xl bg-warning-50 border border-warning-200 text-xs text-warning-800 flex items-center justify-between gap-3">
          <span>Background job queued. You can execute directly in foreground.</span>
          <button
            onClick={() => agentRunStore.runStalledInForeground(buildRequest())}
            className="px-3 py-1 rounded-xl bg-warning-600 text-white font-medium text-[11px] shadow-2xs hover:bg-warning-700 transition-colors"
          >
            Run in foreground
          </button>
        </div>
      )}

      {/* Response Card Section (Dismissible, self-contained, no nested command boxes) */}
      {response && !loading && (
        <div className="relative rounded-2xl bg-bg-surface border border-border-default shadow-lg p-1 overflow-hidden transition-all animate-in fade-in slide-in-from-top-2 duration-200">
          {/* Header bar with Dismiss (X) button */}
          <div className="flex items-center justify-between px-4 py-2 border-b border-border-subtle bg-bg-muted/40">
            <div className="flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-ai-600" />
              <span className="text-xs font-semibold text-text-primary">
                AI Accountant Response
              </span>
            </div>
            <button
              onClick={handleDismissResult}
              className="p-1 rounded-lg text-text-muted hover:text-text-primary hover:bg-bg-muted transition-colors"
              title="Dismiss response (shows dashboard KPIs)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body Content */}
          <div className="p-4 max-h-[460px] overflow-y-auto space-y-4">
            {response.status === ExecutionStatus.AWAITING_CLARIFICATION && (
              <AIClarification
                question={response.question || "I need a bit more information."}
                options={response.options}
                questionOptions={response.question_options}
                onAnswer={handleClarify}
                disabled={loading}
              />
            )}

            {response.status === ExecutionStatus.AWAITING_CONFIRMATION && (
              <AIConfirmation
                summary={response.summary || ""}
                riskLevel={response.risk_level}
                accountingImpact={response.accounting_impact}
                transactionDate={
                  typeof response.data?.transaction_date === "string"
                    ? response.data.transaction_date
                    : undefined
                }
                dateDefaulted={Boolean(response.data?.date_defaulted)}
                onDecision={handleConfirm}
                disabled={loading}
              />
            )}

            {response.status === ExecutionStatus.COMPLETED && (
              <AIActionCard response={response} />
            )}

            {response.status === ExecutionStatus.REJECTED && (
              <div className="p-4 rounded-xl bg-bg-muted text-xs text-text-secondary space-y-1">
                <p className="font-semibold text-text-primary">Action cancelled</p>
                <p className="text-text-muted">
                  {response.summary || "The proposed transaction was rejected and nothing was posted."}
                </p>
              </div>
            )}

            {response.status === ExecutionStatus.FAILED && (
              <div className="p-4 rounded-xl bg-error-50 text-xs text-error-700 space-y-1">
                <p className="font-semibold">Operation failed</p>
                <p className="text-error-600">
                  {response.summary || "The operation could not be completed."}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
