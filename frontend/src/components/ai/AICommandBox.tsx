"use client";

import React, { useState, useRef, useCallback, useEffect, useSyncExternalStore } from "react";
import {
  Send,
  Paperclip,
  X,
  Loader2,
  Sparkles,
  RotateCcw,
  Bot,
  User,
  Zap,
  CheckCircle2,
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

const QUICK_PROMPTS = [
  {
    label: "Cash & Bank Balance",
    prompt: "What is our current cash and bank balance across all accounts?",
  },
  {
    label: "WHT Rates (Sec 153)",
    prompt: "What are the latest Section 153 withholding tax rates for goods vs IT services?",
  },
  {
    label: "FBR vs Provincial Tax",
    prompt: "Explain the difference between Federal GST on goods and Provincial Sales Tax on services (PRA/SRB).",
  },
  {
    label: "Unpaid Bills",
    prompt: "Show me all outstanding supplier bills and upcoming due dates.",
  },
];

export default function AICommandBox() {
  const [message, setMessage] = useState("");
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
    messages,
  } = run;

  // Boot reattach watcher once per session
  useEffect(() => {
    agentRunStore.ensureReattach();
  }, []);

  // Auto-scroll to bottom of conversation
  useEffect(() => {
    if (messagesEndRef.current && (messages.length > 0 || loading)) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, loading]);

  const autoGrow = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
    }
  }, []);

  const buildRequest = useCallback(
    (text?: string): UserRequest => ({
      message: (text || message).trim(),
      attachments: attachments.length > 0 ? attachments : undefined,
    }),
    [message, attachments]
  );

  const handleSend = async (overridePrompt?: string) => {
    const promptToSend = (overridePrompt || message).trim();
    if (!promptToSend && attachments.length === 0) return;
    const req = buildRequest(promptToSend);
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

  return (
    <div className="w-full max-w-4xl mx-auto flex flex-col rounded-3xl bg-bg-surface border border-border-default shadow-xl overflow-hidden transition-all">
      {/* Copilot Header */}
      <div className="flex items-center justify-between px-6 py-3.5 border-b border-border-subtle bg-bg-muted/40">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-ai-500 to-ai-600 flex items-center justify-center text-white shadow-2xs">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-text-primary tracking-wide">
                AI Accountant & Tax Copilot
              </span>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                <Zap className="w-2.5 h-2.5 fill-emerald-500 text-emerald-500" />
                Gemini 3.8 Flash
              </span>
            </div>
            <p className="text-[11px] text-text-muted">
              Real-time conversational accounting & statutory FBR/Provincial compliance
            </p>
          </div>
        </div>

        {messages.length > 0 && (
          <button
            onClick={() => agentRunStore.clearConversation()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-border-default bg-bg-surface text-text-secondary hover:text-text-primary hover:border-ai-300 text-xs font-medium transition-colors"
            title="Start a new conversation"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>New Chat</span>
          </button>
        )}
      </div>

      {/* Messages Feed Area */}
      <div className="p-6 space-y-6 max-h-[560px] overflow-y-auto">
        {messages.length === 0 ? (
          <div className="py-8 text-center space-y-4">
            <div className="w-12 h-12 rounded-2xl bg-ai-50 text-ai-600 mx-auto flex items-center justify-center shadow-xs">
              <Bot className="w-6 h-6" />
            </div>
            <div className="max-w-md mx-auto space-y-1">
              <h3 className="text-sm font-semibold text-text-primary">
                How can I assist your business today?
              </h3>
              <p className="text-xs text-text-secondary leading-relaxed">
                Ask any bookkeeping question, request a CA tax analysis, or instruct me to book invoices, bills, and payments.
              </p>
            </div>

            {/* Quick Prompt Suggestions */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-xl mx-auto pt-2 text-left">
              {QUICK_PROMPTS.map((qp, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => handleSend(qp.prompt)}
                  className="p-3 rounded-2xl border border-border-subtle bg-bg-primary/60 hover:bg-bg-muted hover:border-ai-200 text-left transition-all group"
                >
                  <span className="text-xs font-medium text-text-primary group-hover:text-ai-600 transition-colors">
                    {qp.label}
                  </span>
                  <p className="text-[11px] text-text-muted line-clamp-1 mt-0.5">
                    {qp.prompt}
                  </p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, index) => {
            const isUser = msg.role === "user";
            const isLastAssistant = !isUser && index === messages.length - 1;

            return (
              <div
                key={msg.id}
                className={cn(
                  "flex gap-3",
                  isUser ? "justify-end" : "justify-start"
                )}
              >
                {!isUser && (
                  <div className="w-8 h-8 rounded-xl bg-ai-50 text-ai-600 shrink-0 flex items-center justify-center mt-1 border border-ai-100">
                    <Bot className="w-4 h-4" />
                  </div>
                )}

                <div
                  className={cn(
                    "max-w-[85%] space-y-3",
                    isUser ? "items-end" : "items-start"
                  )}
                >
                  {/* Message Bubble */}
                  <div
                    className={cn(
                      "px-4 py-3 rounded-2xl text-sm leading-relaxed",
                      isUser
                        ? "bg-ai-500 text-white rounded-tr-none shadow-sm font-medium"
                        : "bg-bg-primary border border-border-subtle text-text-primary rounded-tl-none shadow-2xs"
                    )}
                  >
                    {isUser ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : (
                      <div className="space-y-2">
                        {/* Live Steps while in flight */}
                        {msg.streaming && msg.steps && msg.steps.length > 0 && (
                          <div className="pb-2 mb-2 border-b border-border-subtle flex flex-wrap gap-1.5 items-center">
                            {msg.steps.slice(-3).map((st, i) => (
                              <span
                                key={i}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-bg-muted text-text-secondary"
                              >
                                <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                                {st.phase || st.step_type}
                              </span>
                            ))}
                          </div>
                        )}

                        {/* Streaming Text Content */}
                        <div className="whitespace-pre-wrap">
                          {msg.content || (msg.streaming ? "Thinking and evaluating ledger..." : "")}
                          {msg.streaming && (
                            <span className="inline-block w-1.5 h-4 ml-1 bg-ai-500 animate-pulse align-middle" />
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Render Associated Interactive Action Cards on Last Assistant Message */}
                  {isLastAssistant && (
                    <div className="w-full space-y-3 pt-1">
                      {/* Clarification prompt */}
                      {response?.status === ExecutionStatus.AWAITING_CLARIFICATION && (
                        <AIClarification
                          question={response.question || "I need more information."}
                          options={response.options}
                          questionOptions={response.question_options}
                          onAnswer={handleClarify}
                          disabled={loading}
                        />
                      )}

                      {/* Confirmation prompt */}
                      {response?.status === ExecutionStatus.AWAITING_CONFIRMATION && (
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

                      {/* Completed Action Card (with TaxComplianceCard) */}
                      {response?.status === ExecutionStatus.COMPLETED && (
                        <AIActionCard response={response} />
                      )}

                      {/* Rejected */}
                      {response?.status === ExecutionStatus.REJECTED && (
                        <div className="p-3.5 rounded-2xl bg-bg-muted border border-border-subtle text-xs text-text-secondary">
                          <p className="font-semibold text-text-primary">Action cancelled</p>
                          <p className="mt-0.5 text-text-muted">
                            {response.summary || "The action was cancelled and no journal entries were recorded."}
                          </p>
                        </div>
                      )}

                      {/* Error State */}
                      {response?.status === ExecutionStatus.FAILED && (
                        <div className="p-3.5 rounded-2xl bg-error-50 border border-error-200 text-xs text-error-700">
                          <p className="font-semibold">Operation failed</p>
                          <p className="mt-0.5 text-error-600">
                            {response.summary || "The operation could not be completed."}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {isUser && (
                  <div className="w-8 h-8 rounded-xl bg-bg-muted text-text-secondary shrink-0 flex items-center justify-center mt-1 border border-border-subtle">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Global Loading Indicator when starting fresh */}
        {loading && messages.length === 0 && (
          <div className="space-y-2">
            <AIProgress
              conversationId={activeRequestId}
              liveSteps={!reattached && !USE_BACKGROUND_RUNS ? liveSteps : undefined}
            />
          </div>
        )}

        {/* Stalled Worker Notice */}
        {stalledJobId && !loading && (
          <div className="p-3 rounded-2xl bg-warning-50 border border-warning-200 text-xs text-warning-800 flex items-center justify-between gap-3">
            <span>Background worker is queued. You can execute directly in foreground.</span>
            <button
              onClick={() => agentRunStore.runStalledInForeground(buildRequest())}
              className="px-3 py-1 rounded-xl bg-warning-600 text-white font-medium text-[11px] shadow-2xs hover:bg-warning-700 transition-colors"
            >
              Run in foreground
            </button>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="p-3 rounded-2xl bg-error-50 border border-error-200 text-xs text-error-700">
            {error}
          </div>
        )}

        {/* Notice banner */}
        {notice && !loading && (
          <div className="p-3 rounded-2xl bg-warning-50 border border-warning-200 text-xs text-warning-800 flex items-center justify-between">
            <span>{notice}</span>
            <button
              onClick={() => agentRunStore.dismissNotice()}
              className="text-text-muted hover:text-text-primary"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="p-4 border-t border-border-subtle bg-bg-primary/40">
        {/* Attachment Previews */}
        {attachments.length > 0 && (
          <div className="flex gap-2 pb-2.5 flex-wrap">
            {attachments.map((att, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 px-2.5 py-1 bg-bg-surface border border-border-default rounded-xl text-xs text-text-secondary shadow-2xs"
              >
                <Paperclip className="w-3.5 h-3.5 text-ai-500" />
                <span className="max-w-32 truncate font-mono text-[11px]">{att.file_name}</span>
                <button
                  type="button"
                  onClick={() => setAttachments((a) => a.filter((_, j) => j !== i))}
                  className="text-text-muted hover:text-error-600 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2 bg-bg-surface border border-border-default rounded-2xl p-2 focus-within:ring-2 focus-within:ring-ai-100 focus-within:border-ai-400 transition-all shadow-sm">
          {/* File Upload Button */}
          <label className="p-2 rounded-xl text-text-muted hover:text-text-primary hover:bg-bg-muted cursor-pointer transition-colors shrink-0">
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

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => {
              setMessage(e.target.value);
              autoGrow();
            }}
            onKeyDown={handleKeyDown}
            placeholder="Type your instruction (e.g. 'Record cash purchase of Rs 40,000' or 'What is our profit?')..."
            rows={1}
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted resize-none focus:outline-none py-1.5 px-1 min-h-[38px] max-h-[160px]"
          />

          {/* Send Button */}
          <button
            type="button"
            onClick={() => handleSend()}
            disabled={loading || (!message.trim() && attachments.length === 0)}
            className={cn(
              "p-2.5 rounded-xl text-white font-medium transition-all shrink-0",
              loading
                ? "bg-ai-200 text-ai-500 cursor-wait"
                : "bg-ai-500 hover:bg-ai-600 shadow-2xs active:scale-95"
            )}
            title="Send (Enter)"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  );
}
