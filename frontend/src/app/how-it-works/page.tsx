"use client";

/* How It Works — the 8-step core workflow from the project summary */

import PageShell from "@/components/welcome/PageShell";
import {
  MessageSquareText, Brain, HelpCircle, ShieldCheck, Zap, Workflow,
  FileBarChart, PencilLine,
} from "lucide-react";

const STEPS = [
  { icon: MessageSquareText, n: "01", title: "Describe", detail: "Tell the AI what happened in natural language — no forms, no tabs, no jargon.", c: "from-teal-500 to-emerald-400" },
  { icon: Brain, n: "02", title: "Understand", detail: "The AI identifies the transaction and reasons about its accounting nature.", c: "from-indigo-500 to-violet-400" },
  { icon: HelpCircle, n: "03", title: "Clarify", detail: "Targeted questions for anything missing: amount, purpose, cash or credit, party, asset or expense.", c: "from-amber-500 to-orange-400" },
  { icon: ShieldCheck, n: "04", title: "Confirm", detail: "You approve the understanding and the proposed accounting treatment where required.", c: "from-rose-500 to-pink-400" },
  { icon: Zap, n: "05", title: "Execute", detail: "The AI creates the journal entry and updates the ledger automatically — no manual entry.", c: "from-sky-500 to-blue-400" },
  { icon: Workflow, n: "06", title: "Connect", detail: "Entries flow through Journal → Ledger → Trial Balance → Chart of Accounts → Statements.", c: "from-violet-500 to-purple-400" },
  { icon: FileBarChart, n: "07", title: "Report & Document", detail: "Invoices, quotations, aging, receivable/payable and financial reports — from the same system.", c: "from-emerald-500 to-teal-400" },
  { icon: PencilLine, n: "08", title: "Manual Recording", detail: "Prefer traditional control? Record journal entries and transactions manually, anytime.", c: "from-pink-500 to-rose-400" },
];

const FLOW = ["Business Activity", "AI Input", "Reasoning", "Clarification", "Confirmation", "Recording", "Ledger", "Trial Balance", "Statements"];

export default function HowItWorksPage() {
  return (
    <PageShell
      eyebrow="From sentence to statement"
      title="One sentence in. A perfect"
      accent="ledger"
      titleTail="out."
      subtitle="The whole accounting cycle, driven by conversation — with you in control at every gate."
    >
      {/* workflow steps — alternating timeline */}
      <section className="py-16 sm:py-20">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 space-y-6">
          {STEPS.map((s, i) => (
            <div
              key={s.n}
              className="relative rounded-3xl bg-white/90 backdrop-blur border border-white/80 shadow-[0_22px_48px_-24px_rgba(27,42,74,0.35)] p-6 sm:p-7 flex gap-5 items-start"
              style={{ animation: `heroRise 0.9s cubic-bezier(0.19,1,0.22,1) ${100 + i * 80}ms both` }}
            >
              <span
                className={`shrink-0 w-12 h-12 rounded-2xl bg-gradient-to-br ${s.c} flex items-center justify-center shadow-lg`}
              >
                <s.icon className="w-5 h-5 text-white" />
              </span>
              <div className="min-w-0">
                <div className="flex items-baseline gap-2.5">
                  <span className={`text-xs font-black bg-gradient-to-r ${s.c} bg-clip-text text-transparent`}>{s.n}</span>
                  <h2 className="text-lg font-bold text-brand-navy">{s.title}</h2>
                </div>
                <p className="mt-1.5 text-sm text-[#3d4b66] leading-relaxed">{s.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* overall flow strip */}
      <section className="pb-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="rounded-[2rem] bg-white/80 backdrop-blur border border-white/80 shadow-[0_24px_54px_-26px_rgba(27,42,74,0.4)] px-6 py-8">
            <h2
              className="text-center text-xl sm:text-2xl font-semibold text-brand-navy mb-6"
              style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}
            >
              The <span className="text-aurora italic">complete</span> flow
            </h2>
            <div className="flex flex-wrap items-center justify-center gap-2.5">
              {FLOW.map((f, i) => (
                <span key={f} className="inline-flex items-center gap-2.5">
                  <span className="rounded-full bg-white border border-white shadow-sm px-3.5 py-1.5 text-xs font-semibold text-brand-navy">
                    {f}
                  </span>
                  {i < FLOW.length - 1 && (
                    <span className="w-1.5 h-1.5 rounded-full bg-gradient-to-br from-teal-400 to-indigo-500" />
                  )}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
