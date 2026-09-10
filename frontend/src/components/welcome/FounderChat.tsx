"use client";

/* ==================================================================
   FounderChat — the public-site assistant (home page only).
   Talks to the SAME FastAPI backend as the ERP agent
   (POST /api/public/founder-chat), but that endpoint has NO tools
   and NO database access: it answers only informational questions
   about the product and its founder (Zameer Haider). Data-shaped
   questions are refused server-side before the model is ever called.

   Hidden entirely for logged-in users — they already have the full
   permissioned in-app AI agent.
   ================================================================== */

import { useEffect, useRef, useState } from "react";
import { Bot, MessageCircle, Send, X } from "lucide-react";

type Msg = { role: "user" | "assistant"; text: string };

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

const GREETING: Msg = {
  role: "assistant",
  text: "Hi! I'm Ledger — ask me anything about AI Accountant or its founder, Zameer Haider. (Informational questions only — your business data lives safely inside the app.)",
};

export default function FounderChat() {
  const [open, setOpen] = useState(false);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([GREETING]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  /* Logged-in users already have the in-app agent — no site chatbot. */
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { createClient } = await import("@/lib/supabase/client");
        const { data } = await createClient().auth.getSession();
        if (alive) setAuthed(!!data.session);
      } catch {
        if (alive) setAuthed(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (open) {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [msgs, open, busy]);

  if (authed) return null;

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const history = msgs
      .filter((m) => m !== GREETING)
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.text }));
    setMsgs((m) => [...m, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/public/founder-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history }),
      });
      const data = await res.json().catch(() => ({}));
      const reply =
        (data && data.reply) ||
        "I couldn't reach the assistant just now — please try again in a moment.";
      setMsgs((m) => [...m, { role: "assistant", text: reply }]);
    } catch {
      setMsgs((m) => [
        ...m,
        {
          role: "assistant",
          text: "Network hiccup — please try again in a moment.",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2.5">
      {open && (
        <div
          className="w-[calc(100vw-2rem)] max-w-sm rounded-3xl bg-white/95 backdrop-blur-2xl border border-white shadow-[0_30px_70px_-24px_rgba(27,42,74,0.5)] overflow-hidden flex flex-col h-[min(480px,70vh)]"
          style={{ animation: "heroRise 0.35s cubic-bezier(0.19,1,0.22,1) both" }}
          role="dialog"
          aria-label="Founder assistant chat"
        >
          {/* header */}
          <div className="flex items-center gap-2.5 px-4 py-3 bg-gradient-to-r from-teal-500 to-cyan-500 text-white">
            <span className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center shrink-0">
              <Bot className="w-[18px] h-[18px]" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-bold leading-tight">Ledger</span>
              <span className="block text-[10px] opacity-90 leading-tight">
                Founder&apos;s assistant · info only
              </span>
            </span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close chat"
              className="ml-auto w-7 h-7 rounded-full hover:bg-white/20 flex items-center justify-center transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3.5 space-y-2.5">
            {msgs.map((m, i) => (
              <div
                key={i}
                className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <span
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-[13px] leading-relaxed ${
                    m.role === "user"
                      ? "bg-gradient-to-r from-teal-500 to-cyan-500 text-white rounded-br-md"
                      : "bg-[#f1f5f9] text-[#1e293b] rounded-bl-md"
                  }`}
                >
                  {m.text}
                </span>
              </div>
            ))}
            {busy && (
              <div className="flex justify-start">
                <span className="bg-[#f1f5f9] text-[#64748b] rounded-2xl rounded-bl-md px-3.5 py-2 text-[13px]">
                  Ledger is thinking…
                </span>
              </div>
            )}
          </div>

          {/* input */}
          <div className="border-t border-border-default p-2.5 flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask about the product or the founder…"
              maxLength={600}
              className="flex-1 min-w-0 rounded-full border border-border-default bg-white px-4 py-2.5 text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-teal-500/40"
            />
            <button
              type="button"
              onClick={send}
              disabled={busy || !input.trim()}
              aria-label="Send message"
              className="w-10 h-10 rounded-full bg-gradient-to-r from-teal-500 to-cyan-500 text-white flex items-center justify-center shadow-lg shadow-teal-500/30 transition-all hover:-translate-y-0.5 disabled:opacity-40 disabled:translate-y-0 shrink-0"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* launcher */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? "Close assistant" : "Open assistant"}
        aria-expanded={open}
        className="w-14 h-14 rounded-full bg-gradient-to-br from-teal-500 to-cyan-600 text-white flex items-center justify-center shadow-xl shadow-teal-500/40 transition-all hover:-translate-y-1 hover:shadow-2xl active:scale-95"
      >
        {open ? <X className="w-6 h-6" /> : <MessageCircle className="w-6 h-6" />}
      </button>
    </div>
  );
}
