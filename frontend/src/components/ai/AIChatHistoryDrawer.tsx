"use client";

import React, { useEffect } from "react";
import {
  History,
  MessageSquare,
  Plus,
  Clock,
  ChevronRight,
  X,
  Loader2,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { agentRunStore, type AgentRunState } from "@/lib/agent/agentRunStore";

interface AIChatHistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  run: AgentRunState;
}

export default function AIChatHistoryDrawer({
  isOpen,
  onClose,
  run,
}: AIChatHistoryDrawerProps) {
  const { threads, threadsLoading, conversationId } = run;

  useEffect(() => {
    if (isOpen) {
      agentRunStore.loadThreads();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSelectThread = async (cid: string) => {
    if (cid === conversationId) {
      onClose();
      return;
    }
    await agentRunStore.switchConversation(cid);
    onClose();
  };

  const handleNewChat = () => {
    agentRunStore.newChat();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-xs animate-in fade-in duration-200">
      {/* Click outside to close */}
      <div className="flex-1" onClick={onClose} />

      {/* Drawer panel */}
      <div className="w-full max-w-sm sm:max-w-md bg-bg-surface border-l border-border-default shadow-2xl h-full flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle bg-bg-muted/40">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-ai-600" />
            <h3 className="text-sm font-semibold text-text-primary">
              Conversations History
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-text-muted hover:text-text-primary hover:bg-bg-muted transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Action bar */}
        <div className="p-3 border-b border-border-subtle">
          <button
            type="button"
            onClick={handleNewChat}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold bg-ai-600 hover:bg-ai-700 text-white shadow-2xs transition-all"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Start New Chat</span>
          </button>
        </div>

        {/* Thread list */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {threadsLoading ? (
            <div className="flex flex-col items-center justify-center py-12 text-text-muted space-y-2">
              <Loader2 className="w-5 h-5 animate-spin text-ai-600" />
              <p className="text-xs">Loading conversations...</p>
            </div>
          ) : threads.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center text-text-muted space-y-2">
              <MessageSquare className="w-8 h-8 text-text-muted/60" />
              <p className="text-xs font-medium text-text-secondary">No saved sessions yet</p>
              <p className="text-[11px] max-w-xs">
                Your questions, financial simulations, and voucher drafts will be saved here automatically like in Claude.
              </p>
            </div>
          ) : (
            threads.map((t) => {
              const isSelected = t.conversation_id === conversationId;
              const formattedDate = t.updated_at
                ? new Date(t.updated_at).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "";

              return (
                <button
                  key={t.conversation_id}
                  type="button"
                  onClick={() => handleSelectThread(t.conversation_id)}
                  className={cn(
                    "w-full text-left p-3 rounded-xl border transition-all flex items-start justify-between gap-2 group",
                    isSelected
                      ? "bg-ai-50 border-ai-300 ring-1 ring-ai-200"
                      : "bg-bg-surface hover:bg-bg-muted border-border-subtle hover:border-ai-200 shadow-3xs"
                  )}
                >
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-1.5">
                      <Sparkles className={cn("w-3 h-3 shrink-0", isSelected ? "text-ai-600" : "text-text-muted")} />
                      <p className={cn("text-xs font-semibold truncate", isSelected ? "text-ai-900" : "text-text-primary")}>
                        {t.title || "Untitled Conversation"}
                      </p>
                    </div>
                    {t.last_message && (
                      <p className="text-[11px] text-text-muted line-clamp-1 truncate">
                        {t.last_message}
                      </p>
                    )}
                    <div className="flex items-center gap-2 pt-1 text-[10px] text-text-muted font-mono">
                      <span className="flex items-center gap-1">
                        <Clock className="w-2.5 h-2.5" />
                        {formattedDate}
                      </span>
                      <span>•</span>
                      <span>{t.turn_count} {t.turn_count === 1 ? "turn" : "turns"}</span>
                    </div>
                  </div>
                  <ChevronRight className={cn("w-4 h-4 shrink-0 mt-1 transition-transform group-hover:translate-x-0.5", isSelected ? "text-ai-600" : "text-text-muted")} />
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
