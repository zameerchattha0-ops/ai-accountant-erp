"use client";

import React, { useState, useRef, useCallback, useEffect, useSyncExternalStore } from "react";
import {
  Send,
  Paperclip,
  X,
  Loader2,
  Sparkles,
  Zap,
  MessageCircleQuestion,
  History,
  Plus,
  User,
  Bot,
  RotateCcw,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import type {
  AttachmentRef,
  UserRequest,
  LivingDraft,
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
import LivingDraftCard from "./LivingDraftCard";
import AIChatHistoryDrawer from "./AIChatHistoryDrawer";
import IntentProgressionTracker from "./IntentProgressionTracker";
import type { IntentProgression } from "@/lib/types/api";

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

function getClarificationSummary(rawQuestion?: string): string {
  if (!rawQuestion) return "Clarification needed";
  const clean = rawQuestion
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/`/g, "")
    .trim();
  const firstLine = clean.split("\n")[0].trim();
  if (firstLine.toLowerCase().includes("clarif") && clean.includes("1.")) {
    const q1 = clean.match(/1[.)]\s*(.+?)(?:\n|$)/);
    if (q1 && q1[1]) return q1[1].trim();
  }
  return firstLine.length > 55 ? firstLine.slice(0, 52) + "..." : firstLine;
}

export default function AICommandBox() {
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  useEffect(() => {
    setPlaceholderIdx(Math.floor(Math.random() * PLACEHOLDERS.length));
  }, []);

  const [message, setMessage] = useState("");
  const [lastSubmittedText, setLastSubmittedText] = useState("");
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

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
    conversationId,
    conversationTitle,
  } = run;

  // Boot reattach watcher once per session
  useEffect(() => {
    agentRunStore.ensureReattach();
  }, []);

  // Auto-scroll chat to bottom inside its container (without scrolling the outer window/page)
  useEffect(() => {
    const container = chatContainerRef.current;
    if (container && messages.length > 0) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages.length, run.streamingText, response]);

  const isAwaitingClarification =
    response?.status === ExecutionStatus.AWAITING_CLARIFICATION &&
    Boolean(response?.execution_id);
  const clarificationSummary = isAwaitingClarification
    ? getClarificationSummary(response?.question)
    : "";

  const latestAssistantMessage = [...messages].reverse().find((m) => m.role === "assistant");
  const activeProgression: IntentProgression | undefined =
    response?.intent_progression ||
    (response?.data?.intent_progression as IntentProgression | undefined) ||
    latestAssistantMessage?.response?.intent_progression ||
    (latestAssistantMessage?.response?.data?.intent_progression as IntentProgression | undefined);

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
    if (loading) return;
    const textToSend = (customText ?? message).trim();
    if (!textToSend && attachments.length === 0) return;
    setLastSubmittedText(textToSend);

    // If currently awaiting clarification, typing an answer into the command bar submits the clarification
    if (
      response?.status === ExecutionStatus.AWAITING_CLARIFICATION &&
      response?.execution_id &&
      attachments.length === 0
    ) {
      setMessage("");
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
      await handleClarify(textToSend);
      return;
    }

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
      if (loading) return;
      handleSend();
    }
  };

  const handleDismissResult = () => {
    agentRunStore.clearResponse();
  };

  const handleNewChat = () => {
    agentRunStore.newChat();
    setMessage("");
    setAttachments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus();
    }
  };

  const hasMessages = messages.length > 0;

  return (
    <div className="w-full max-w-4xl mx-auto space-y-3">
      {/* Top Header / Thread Bar */}
      <div className="flex items-center justify-between px-2 py-1 text-xs">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-ai-50 border border-ai-200 text-ai-800 font-medium">
            <Sparkles className="w-3.5 h-3.5 text-ai-600" />
            <span className="truncate max-w-[220px] sm:max-w-xs font-semibold">
              {conversationTitle || "AI Accountant Partner"}
            </span>
          </div>
          {conversationId && (
            <span className="hidden sm:inline-block text-[10px] text-text-muted font-mono bg-bg-muted px-2 py-0.5 rounded-md">
              Thread Active
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setIsHistoryOpen(true)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-muted border border-border-subtle transition-colors text-xs"
            title="Open conversation sessions history"
          >
            <History className="w-3.5 h-3.5 text-ai-600" />
            <span className="hidden sm:inline">Sessions</span>
          </button>

          <button
            type="button"
            onClick={handleNewChat}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-bg-surface hover:bg-bg-muted text-text-secondary hover:text-text-primary border border-border-subtle shadow-3xs transition-colors text-xs"
            title="Start fresh conversation"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Chat</span>
          </button>
        </div>
      </div>

      {/* Main Conversation Stream (Claude-Style Multi-Turn Thread) */}
      {hasMessages && (
        <div
          ref={chatContainerRef}
          className="rounded-2xl border border-border-default bg-bg-surface/80 backdrop-blur-xs shadow-md p-4 max-h-[65vh] md:max-h-[70vh] overflow-y-auto space-y-5 animate-in fade-in duration-200"
        >
          {messages.map((msg, index) => {
            const isUser = msg.role === "user";
            const isLatestAssistant = !isUser && index === messages.length - 1;
            const msgResponse = msg.response || (isLatestAssistant ? response : null);
            const livingDraft = msgResponse?.living_draft || (msgResponse?.data?.living_draft as LivingDraft);

            return (
              <div
                key={msg.id || index}
                className={cn(
                  "flex gap-3 text-sm animate-in fade-in slide-in-from-bottom-1 duration-150",
                  isUser ? "justify-end" : "justify-start"
                )}
              >
                {!isUser && (
                  <div className="w-7 h-7 rounded-full bg-ai-600 text-white flex items-center justify-center shrink-0 shadow-3xs mt-0.5">
                    <Bot className="w-4 h-4" />
                  </div>
                )}

                <div
                  className={cn(
                    "space-y-3 max-w-[90%] md:max-w-[85%]",
                    isUser ? "flex flex-col items-end" : "flex-1"
                  )}
                >
                  {/* Message Bubble (suppressed for clarification cards to prevent duplicate question rendering) */}
                  {(!msgResponse || msgResponse.status !== ExecutionStatus.AWAITING_CLARIFICATION) && (
                    <div
                      className={cn(
                        "px-4 py-2.5 rounded-2xl shadow-3xs leading-relaxed",
                        isUser
                          ? "bg-ai-600 text-white rounded-tr-xs"
                          : "bg-bg-muted/70 text-text-primary border border-border-subtle rounded-tl-xs"
                      )}
                    >
                      {msg.content ? (
                        <div className="whitespace-pre-wrap">{msg.content}</div>
                      ) : msg.streaming && loading ? (
                        <div className="flex items-center gap-2 text-text-muted py-0.5">
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-ai-600" />
                          <span className="text-xs">Analyzing accounting policies & records...</span>
                        </div>
                      ) : null}
                    </div>
                  )}

                  {/* Assistant Interactive Cards & Live Draft (Rendered seamlessly in-flow) */}
                  {!isUser && msgResponse && (
                    <div className="space-y-3 w-full">
                      {/* Real-time Living Draft Voucher Card (only rendered when reviewing, never during clarification) */}
                      {Boolean(livingDraft) && msgResponse.status !== ExecutionStatus.AWAITING_CLARIFICATION && (
                        <LivingDraftCard
                          draft={livingDraft!}
                          className="w-full shadow-xs"
                          onAction={(actionType, payload) => {
                            const actionId = (payload?.action_id as string) || actionType;
                            if (actionId === "post_to_ledger" || actionId === "submit") {
                              handleConfirm(true);
                            } else if (actionId === "modify_terms") {
                              textareaRef.current?.focus();
                            } else if (actionId === "run_scenario") {
                              handleSend("Simulate lease vs buy for this asset");
                            } else if (actionType === "select_account" && payload?.account_name) {
                              handleClarify(`Use account ${payload.account_code || ""} (${payload.account_name})`);
                            } else if (actionType === "adjust_slider" && payload?.slider_value) {
                              handleClarify(`Set useful life to ${payload.slider_value} years`);
                            } else if (actionType === "toggle_wht") {
                              handleClarify(payload?.is_enabled ? "Apply Section 153 WHT deduction" : "Do not deduct Section 153 WHT");
                            }
                          }}
                        />
                      )}

                      {/* Clarification Round */}
                      {msgResponse.status === ExecutionStatus.AWAITING_CLARIFICATION && (
                        <AIClarification
                          question={msgResponse.question || "I need a bit more information."}
                          options={msgResponse.options}
                          questionOptions={msgResponse.question_options}
                          onAnswer={handleClarify}
                          disabled={loading}
                        />
                      )}

                      {/* Confirmation Round */}
                      {msgResponse.status === ExecutionStatus.AWAITING_CONFIRMATION && (
                        <AIConfirmation
                          summary={msgResponse.summary || ""}
                          riskLevel={msgResponse.risk_level}
                          accountingImpact={msgResponse.accounting_impact}
                          transactionDate={
                            typeof msgResponse.data?.transaction_date === "string"
                              ? msgResponse.data.transaction_date
                              : undefined
                          }
                          dateDefaulted={Boolean(msgResponse.data?.date_defaulted)}
                          onDecision={handleConfirm}
                          disabled={loading}
                        />
                      )}

                      {/* Completed Action Card */}
                      {msgResponse.status === ExecutionStatus.COMPLETED && (
                        <AIActionCard response={msgResponse} />
                      )}

                      {/* Rejected State */}
                      {msgResponse.status === ExecutionStatus.REJECTED && (
                        <div className="p-3.5 rounded-xl bg-bg-muted text-xs text-text-secondary space-y-1 border border-border-subtle">
                          <p className="font-semibold text-text-primary">Action cancelled</p>
                          <p className="text-text-muted">
                            {msgResponse.summary || "The proposed transaction was rejected and nothing was posted."}
                          </p>
                        </div>
                      )}

                      {/* Failed State with One-Click Retry */}
                      {msgResponse.status === ExecutionStatus.FAILED && (
                        <div className="p-3.5 rounded-xl bg-error-50 text-xs text-error-700 space-y-2 border border-error-200">
                          <div className="flex items-center justify-between">
                            <p className="font-semibold text-error-800">Operation could not be completed</p>
                            {Boolean(lastSubmittedText) && (
                              <button
                                type="button"
                                onClick={() => handleSend(lastSubmittedText)}
                                className="px-2.5 py-1 text-[11px] font-medium bg-white hover:bg-error-50 text-error-700 border border-error-200 rounded-lg shadow-2xs transition-colors flex items-center gap-1"
                              >
                                <RotateCcw className="w-3 h-3" />
                                <span>Retry</span>
                              </button>
                            )}
                          </div>
                          <p className="text-error-600">
                            {msgResponse.summary || "The operation could not be completed. Please try again."}
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="text-[10px] text-text-muted font-mono px-1">
                    {msg.createdAt
                      ? new Date(msg.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : ""}
                  </div>
                </div>

                {isUser && (
                  <div className="w-7 h-7 rounded-full bg-bg-muted border border-border-default text-text-secondary flex items-center justify-center shrink-0 shadow-3xs mt-0.5">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Live Intent Progression Tracker pinned directly above the command input bar */}
      {activeProgression && (
        <IntentProgressionTracker progression={activeProgression} className="animate-in fade-in slide-in-from-bottom-1 duration-200" />
      )}

      {/* Hero / Command Input Box */}
      <div className={cn(
        "glass rounded-2xl p-1.5 shadow-md border transition-all bg-bg-surface",
        isAwaitingClarification
          ? "border-ai-300 ring-2 ring-ai-100"
          : "border-border-default hover:border-ai-300 focus-within:border-ai-400 focus-within:ring-2 focus-within:ring-ai-100"
      )}>
        {/* Active Clarification Turn Indicator Pill */}
        {isAwaitingClarification && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 mb-1 mx-1 rounded-xl bg-ai-50 border border-ai-200 text-ai-800 text-xs shadow-3xs animate-in fade-in duration-150">
            <MessageCircleQuestion className="w-3.5 h-3.5 text-ai-600 shrink-0" />
            <span className="truncate flex-1">
              <span className="font-semibold text-ai-900">Answering:</span>{" "}
              <span className="text-ai-700">{clarificationSummary}</span>
            </span>
            <button
              type="button"
              onClick={handleDismissResult}
              title="Dismiss clarification and start new command"
              className="text-ai-400 hover:text-ai-700 hover:bg-ai-100 p-0.5 rounded-md transition-colors shrink-0"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        )}

        <div className="flex items-start gap-2.5 px-3 py-1.5">
          <div className="p-1.5 text-ai-500 shrink-0 mt-0.5">
            <Sparkles className="w-4 h-4" />
          </div>

          <textarea
            id="ai-command-input"
            name="ai-command-input"
            aria-label="AI accountant command prompt"
            ref={textareaRef}
            value={message}
            onChange={(e) => {
              setMessage(e.target.value);
              autoGrow();
            }}
            onKeyDown={handleKeyDown}
            placeholder={
              isAwaitingClarification
                ? `Answering: "${clarificationSummary}" (or type answer here)...`
                : hasMessages
                ? "Ask a follow-up or give instruction (e.g. 'Use Meezan Bank', 'Simulate lease vs buy')..."
                : PLACEHOLDERS[placeholderIdx]
            }
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
                  : isAwaitingClarification && message.trim()
                  ? "bg-ai-600 hover:bg-ai-700 text-white shadow-2xs"
                  : "bg-ai-500 hover:bg-ai-600 text-white shadow-2xs"
              )}
            >
              {loading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Thinking</span>
                </>
              ) : isAwaitingClarification ? (
                <>
                  <Send className="w-3.5 h-3.5" />
                  <span>Submit Answer</span>
                </>
              ) : (
                <>
                  <Send className="w-3.5 h-3.5" />
                  <span>Send</span>
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

      {/* Quick Prompts Bar */}
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

      {/* Loading Progress (Compact Step Display when no stream is in progress) */}
      {loading && !hasMessages && (
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

      {/* Sessions History Drawer */}
      <AIChatHistoryDrawer
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        run={run}
      />
    </div>
  );
}
