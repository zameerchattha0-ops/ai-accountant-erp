"use client";

/* Features — every capability of the AI Accountant ERP */

import PageShell from "@/components/welcome/PageShell";
import {
  Brain, BarChart3, Building2, BookOpen, Search, ShieldCheck,
} from "lucide-react";

const FEATURES = [
  {
    icon: Brain,
    title: "AI Accounting Agent",
    description:
      "Tell the AI what happened in plain language. It reasons about the accounting nature, asks for anything missing, and handles journal entries, posting, and reconciliation automatically.",
    chip: "bg-gradient-to-br from-teal-100 to-teal-50",
    icon2: "text-teal-600",
  },
  {
    icon: BarChart3,
    title: "Real-time Financial Reports",
    description:
      "Profit and Loss, Balance Sheet, Cash Flow, Trial Balance — every report updates the instant an entry is posted. No month-end scramble, ever.",
    chip: "bg-gradient-to-br from-indigo-100 to-indigo-50",
    icon2: "text-indigo-600",
  },
  {
    icon: Building2,
    title: "Multi-tenant Architecture",
    description:
      "Each organization gets fully isolated data with row-level security. Your books stay private, segregated, and compliant by construction.",
    chip: "bg-gradient-to-br from-rose-100 to-rose-50",
    icon2: "text-rose-600",
  },
  {
    icon: BookOpen,
    title: "Automated Journal Engine",
    description:
      "Invoices, bills, and receipts automatically generate balanced journal entries. No manual debits and credits — the engine does the thinking.",
    chip: "bg-gradient-to-br from-amber-100 to-amber-50",
    icon2: "text-amber-600",
  },
  {
    icon: Search,
    title: "Smart Entity Search",
    description:
      "Find customers, suppliers, accounts, and transactions instantly with fuzzy search across your entire ledger — even when you only half-remember the name.",
    chip: "bg-gradient-to-br from-sky-100 to-sky-50",
    icon2: "text-sky-600",
  },
  {
    icon: ShieldCheck,
    title: "Enterprise Compliance",
    description:
      "Role-based permissions, complete audit trails, confirmation gates for high-risk operations, and full accounting-period management.",
    chip: "bg-gradient-to-br from-violet-100 to-violet-50",
    icon2: "text-violet-600",
  },
];

const MODULES = [
  { title: "Sales & Receivables", detail: "Invoices, quotations, credit notes, receipts, aging reports" },
  { title: "Purchases & Payables", detail: "Bills, purchase returns, supplier ledgers, payable ageing" },
  { title: "Banking", detail: "Bank-position tracking and reconciliation-ready records" },
  { title: "Reports", detail: "P&L, Balance Sheet, Cash Flow, aging, project profitability" },
];

export default function FeaturesPage() {
  return (
    <PageShell
      eyebrow="Everything in one ledger"
      title="Every feature your"
      accent="money"
      titleTail="deserves."
      subtitle="From the first spoken sentence to the final signed-off balance sheet — one AI-native system, zero tab-hopping."
    >
      {/* feature cards — 3-column grid, clay-curved */}
      <section className="py-16 sm:py-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className="rounded-3xl bg-white/90 backdrop-blur border border-white/80 shadow-[0_22px_48px_-24px_rgba(27,42,74,0.35)] p-7 transition-transform hover:-translate-y-1"
              style={{ animation: `heroRise 0.9s cubic-bezier(0.19,1,0.22,1) ${120 + i * 90}ms both` }}
            >
              <span className={`w-12 h-12 rounded-2xl ${f.chip} clay-chip flex items-center justify-center mb-5`}>
                <f.icon className={`w-5 h-5 ${f.icon2}`} />
              </span>
              <h2 className="text-lg font-bold text-brand-navy">{f.title}</h2>
              <p className="mt-2.5 text-sm text-[#3d4b66] leading-relaxed">{f.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* modules strip */}
      <section className="pb-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <h2
            className="text-center text-2xl sm:text-3xl font-semibold text-brand-navy mb-10"
            style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}
          >
            Every module, <span className="text-aurora italic">connected</span>.
          </h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {MODULES.map((m, i) => (
              <div
                key={m.title}
                className="rounded-3xl bg-white/80 backdrop-blur border border-white/80 shadow-[0_18px_40px_-22px_rgba(27,42,74,0.3)] px-5 py-6 text-center"
                style={{ animation: `heroRise 0.9s cubic-bezier(0.19,1,0.22,1) ${i * 90}ms both` }}
              >
                <span className="block w-2.5 h-2.5 rounded-full mx-auto mb-3 bg-gradient-to-br from-teal-400 to-indigo-500" />
                <span className="block text-sm font-bold text-brand-navy">{m.title}</span>
                <span className="block mt-1.5 text-xs text-[#64748b] leading-relaxed">{m.detail}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </PageShell>
  );
}
