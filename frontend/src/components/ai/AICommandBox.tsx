"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Send, Paperclip, X, Loader2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { aiClarify, aiConfirm, aiExecuteStream, aiEnqueueJob, aiGetJob, isApiErrorWithStatus, latestActiveSession, runBackgroundJob } from "@/lib/api/client";
import type {
  AgentResponse,
  AttachmentRef,
} from "@/lib/types/api";
import {
  ALLOWED_UPLOAD_MIMES,
  MAX_UPLOAD_BYTES,
} from "@/lib/types/api";
import { ExecutionStatus } from "@/lib/types/enums";
import AIProgress, { type LiveStepEvent } from "./AIProgress";
import AIActionCard from "./AIActionCard";
import AIClarification from "./AIClarification";
import AIConfirmation from "./AIConfirmation";

const PLACEHOLDERS = [
  "Tell me what happened...",
  "Create an invoice for ABC Technologies...",
  "Record an expense of Rs. 25,000...",
  "Show me this month's profit...",
  "Upload a receipt and I'll help record it.",
];

// Work Stream C: background runs are the DEFAULT path. A request is
// enqueued (POST /api/ai/jobs), progress is shown by AIProgress polling
// the run's conversation_id, and the result card renders when the job
// reaches a terminal state. Set this constant to false to restore the
// synchronous SSE path as the primary route.
const USE_BACKGROUND_RUNS = true;

/** Fired whenever the agent FINISHES a mutation (or fails one) so every
 *  listening page reloads its data instantly - no manual browser refresh. */
function notifyDataChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("erp:data-changed"));
  }
}

export default function AICommandBox() {
  // Hydration safety: the FIRST render (server and client) must be
  // byte-identical.  A module-scope Math.random() placeholder was evaluated
  // separately on the server and the client, producing different
  // placeholder attributes and the "Hydration failed because the server
  // rendered HTML didn't match the client" error.  Use a deterministic
  // initial placeholder and only randomise AFTER hydration (useEffect).
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  useEffect(() => {
    setPlaceholderIdx(Math.floor(Math.random() * PLACEHOLDERS.length));
  }, []);
  const [message, setMessage] = useState("");
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [error, setError] = useState("");
  // Client-generated request id for the in-flight execution. The backend
  // stores it as the session's conversation_id, so AIProgress can poll the
  // REAL recorded reasoning state for THIS specific request.
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  // Work Stream D: reasoning steps streamed LIVE over SSE while the run
  // executes (rendered by AIProgress without polling).
  const [liveSteps, setLiveSteps] = useState<LiveStepEvent[]>([]);
  // Work Stream C: job id of a QUEUED run no worker has claimed within the
  // stall window - the UI offers a one-click foreground fallback.
  const [stalledJobId, setStalledJobId] = useState<string | null>(null);
  // Work Stream C: true when the progress view was reattached to a run
  // that was already in flight before this page loaded (browser refresh).
  const [reattached, setReatt] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Work Stream C: resume-by-conversation. On mount, check for a still
  // in-flight execution session (PENDING / PLANNING / EXECUTING) and
  // reattach AIProgress to it so a browser refresh mid-run does NOT lose
  // the live view. WAITING_FOR_USER sessions are intentionally ignored -
  // they need an answer through the normal clarify flow, not a poller.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const info = await latestActiveSession();
        if (cancelled || !info.found || !info.session) return;
        const status = (info.session.status || "").toUpperCase();
        const convId = info.session.conversation_id;
        if (
          (status === "EXECUTING" || status === "PLANNING" || status === "PENDING") &&
          convId
        ) {
          setActiveRequestId(convId);
          setLoading(true);
          setReatt(true);
        }
      } catch {
        /* backend offline - nothing to reattach */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // While reattached, watch the session until it reaches a terminal state
  // (the endpoint stops returning it), then end the progress view. The
  // original HTTP response is gone after a refresh, so the result card is
  // not re-rendered - the recorded result stays available in AI Activity.
  useEffect(() => {
    if (!reattached) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const info = await latestActiveSession();
        if (cancelled) return;
        if (!info.found) {
          clearInterval(id);
          setLoading(false);
          setReatt(false);
          setActiveRequestId(null);
          notifyDataChanged();
        }
      } catch {
        /* keep polling - transient network errors must not detach */
      }
    }, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [reattached]);

  const autoGrow = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, []);

  const applyResponse = useCallback((res: AgentResponse) => {
    setResponse(res);
    if (res.status === ExecutionStatus.COMPLETED || res.status === ExecutionStatus.FAILED) {
      setMessage("");
      setAttachments([]);
      notifyDataChanged();
    }
  }, []);

  const handleSend = async () => {
    if (!message.trim() && attachments.length === 0) return;
    setError("");
    setLoading(true);
    setResponse(null);
    // crypto.randomUUID() - available in all modern browsers over localhost.
    const requestId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setActiveRequestId(requestId);
    setLiveSteps([]);

    // Work Stream D (kept behind the constant): stream the run over SSE -
    // each recorded reasoning step arrives live, and the result card
    // renders ONLY when the final (verified) response arrives.
    const runForeground = async () => {
      const res = await aiExecuteStream(
        {
          message: message.trim(),
          conversation_id: requestId,
          attachments: attachments.length > 0 ? attachments : undefined,
        },
        {
          onStep: (step) =>
            setLiveSteps((prev) => [
              ...prev,
              {
                step_type: step.step_type,
                phase: step.phase,
                status: step.status,
                created_at: step.created_at,
              },
            ]),
        }
      );
      applyResponse(res);
    };

    // Work Stream C: the run is enqueued, AIProgress polls the run's
    // conversation_id for recorded steps, and the result card renders from
    // the polled job result. A 404 (older backend without the jobs
    // endpoint) falls back to the SSE path automatically.
    const runBackground = () =>
      runBackgroundJob({
        enqueue: () =>
          aiEnqueueJob({
            message: message.trim(),
            conversation_id: requestId,
            attachments: attachments.length > 0 ? attachments : undefined,
          }),
        getJob: aiGetJob,
        onResult: applyResponse,
        onError: setError,
        onStalled: setStalledJobId,
      });

    try {
      if (USE_BACKGROUND_RUNS) {
        try {
          await runBackground();
        } catch (jobErr) {
          if (!isApiErrorWithStatus(jobErr, 404)) throw jobErr;
          await runForeground(); // older backend: no jobs endpoint
        }
      } else {
        await runForeground();
      }
    } catch (err) {
      setError(err instanceof Error
        ? /failed to fetch|networkerror|net::err/i.test(err.message)
          ? "The AI service is offline. Start the backend server (port 8000) and try again."
          : err.message
        : "Something went wrong");
    } finally {
      setLoading(false);
      setActiveRequestId(null);
      setLiveSteps([]);
    }
  };

  // One-click foreground fallback when the queue is not being drained.
  const runStalledJobInForeground = async () => {
    setStalledJobId(null);
    if (!message.trim() && attachments.length === 0) return;
    setError("");
    setLoading(true);
    const requestId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setActiveRequestId(requestId);
    try {
      await aiExecuteStream(
        {
          message: message.trim(),
          conversation_id: requestId,
          attachments: attachments.length > 0 ? attachments : undefined,
        },
        {
          onStep: (step) =>
            setLiveSteps((prev) => [
              ...prev,
              {
                step_type: step.step_type,
                phase: step.phase,
                status: step.status,
                created_at: step.created_at,
              },
            ]),
        }
      ).then(applyResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
      setActiveRequestId(null);
      setLiveSteps([]);
    }
  };

  const handleClarify = async (answer: string) => {
    if (!response?.execution_id) return;
    setLoading(true);
    setError("");
    try {
      const res = await aiClarify({ session_id: response.execution_id, answer });
      setResponse(res);
      if (
        res.status === ExecutionStatus.COMPLETED ||
        res.status === ExecutionStatus.FAILED ||
        res.status === ExecutionStatus.REJECTED
      ) {
        notifyDataChanged();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send answer");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (approved: boolean, notes?: string) => {
    if (!response?.execution_id) return;
    setLoading(true);
    setError("");
    try {
      const res = await aiConfirm({ session_id: response.execution_id, approved, notes });
      setResponse(res);
      if (
        res.status === ExecutionStatus.COMPLETED ||
        res.status === ExecutionStatus.FAILED ||
        res.status === ExecutionStatus.REJECTED
      ) {
        notifyDataChanged();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send decision");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto space-y-4">
      {/* Input box */}
      <div className="glass rounded-2xl p-1 shadow-lg">
        <div className="flex items-start gap-2 p-2">
          <div className="p-2 text-ai-500">
            <Sparkles className="w-5 h-5" />
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
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted resize-none focus:outline-none py-2 min-h-[40px] max-h-[200px]"
          />
        </div>

        {/* Attachment previews */}
        {attachments.length > 0 && (
          <div className="flex gap-2 px-3 pb-2 flex-wrap">
            {attachments.map((att, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 px-2.5 py-1.5 bg-bg-muted rounded-lg text-xs text-text-secondary"
              >
                <Paperclip className="w-3 h-3" />
                <span className="max-w-24 truncate">{att.file_name}</span>
                <button
                  onClick={() => setAttachments((a) => a.filter((_, j) => j !== i))}
                  className="text-text-muted hover:text-text-primary"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Bottom bar */}
        <div className="flex items-center justify-between px-2 pb-1">
          <div className="flex items-center gap-1">
            <label className="p-2 rounded-lg text-text-muted hover:text-text-secondary hover:bg-bg-muted cursor-pointer transition-colors">
              <Paperclip className="w-4 h-4" />
              <input
                type="file"
                className="hidden"
                multiple
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  const files = Array.from(e.target.files || []);
                  e.target.value = ""; // allow re-selecting the same file
                  const errors: string[] = [];
                  const valid = files.filter((f) => {
                    if (!ALLOWED_UPLOAD_MIMES.has(f.type)) {
                      errors.push(`${f.name}: only PNG, JPEG or WEBP images are supported.`);
                      return false;
                    }
                    if (f.size > MAX_UPLOAD_BYTES) {
                      errors.push(`${f.name}: file is larger than 8 MB.`);
                      return false;
                    }
                    return true;
                  });
                  if (errors.length > 0) setError(errors.join(" "));

                  // Read each file as base64 so the backend receives the
                  // ACTUAL document for vision extraction (blob URLs never
                  // leave the browser).
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
                    reader.onerror = () =>
                      setError(`${f.name}: could not read the file.`);
                    reader.readAsDataURL(f);
                  });
                }}
              />
            </label>
          </div>
          <button
            onClick={handleSend}
            disabled={loading || (!message.trim() && attachments.length === 0)}
            className={cn(
              "btn-3d btn-shine flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold transition-all",
              loading
                ? "bg-ai-100 text-ai-500 cursor-wait"
                : "bg-gradient-to-b from-ai-500 to-ai-600 text-white hover:from-ai-400 hover:to-ai-600"
            )}
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {loading ? "Processing" : "Send"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 rounded-xl bg-error-50 border border-error-100 text-sm text-error-600">
          {error}
        </div>
      )}

      {/* Loading progress - REAL agent state polled from the backend */}
      {loading && (
        <div className="space-y-2">
          {reattached && (
            <p className="text-xs text-text-muted">
              Reattached to a run that was already in progress. The result will
              be available in AI Activity when it completes.
            </p>
          )}
          <AIProgress
            conversationId={activeRequestId}
            liveSteps={
              !reattached && !USE_BACKGROUND_RUNS ? liveSteps : undefined
            }
          />
        </div>
      )}

      {/* Work Stream C: queued but not picked up by any worker - offer the
          one-click foreground fallback instead of an endless wait. */}
      {stalledJobId && !loading && (
        <div className="p-3 rounded-xl bg-warning-50 border border-warning-100 text-sm text-text-secondary flex items-center justify-between gap-3">
          <span>
            No background worker has picked up this run yet. Start one with
            &quot;python scripts/ai_worker.py&quot; or run it here instead.
          </span>
          <button
            onClick={runStalledJobInForeground}
            className="btn-3d-soft shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium"
          >
            Run in foreground instead
          </button>
        </div>
      )}

      {/* Response rendering */}
      {response && !loading && (
        <>
          {response.status === ExecutionStatus.AWAITING_CLARIFICATION && (
            <AIClarification
              question={response.question || "I need more information."}
              options={response.options}
              questionOptions={response.question_options}
              onAnswer={handleClarify}
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
            />
          )}
          {response.status === ExecutionStatus.COMPLETED && (
            <AIActionCard response={response} />
          )}
          {response.status === ExecutionStatus.REJECTED && (
            <div className="p-4 rounded-xl bg-bg-muted border border-border-subtle">
              <p className="text-sm font-medium text-text-secondary">Action cancelled</p>
              <p className="text-sm text-text-muted mt-1">
                {response.summary || "The action was rejected and nothing was recorded."}
              </p>
            </div>
          )}
          {response.status === ExecutionStatus.FAILED && (
            <div className="p-4 rounded-xl bg-error-50 border border-error-100">
              <p className="text-sm font-medium text-error-600">Something went wrong</p>
              <p className="text-sm text-error-500 mt-1">{response.summary || "The operation could not be completed."}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
