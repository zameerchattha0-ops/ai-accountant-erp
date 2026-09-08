"use client";

/* Solutions — who the AI Accountant is built for */

import PageShell from "@/components/welcome/PageShell";

const SEGMENTS = [
  {
    emoji: "🚀",
    title: "Startups",
    detail: "Move at founder speed. Speak a transaction out loud between meetings and know your runway the moment it changes — without hiring a bookkeeper first.",
    chip: "from-teal-100 to-teal-50",
    ring: "from-teal-400 to-emerald-400",
  },
  {
    emoji: "🛍️",
    title: "Retail & Traders",
    detail: "Daily sales, supplier bills, cash and credit purchases — dictated in seconds. Inventory-adjacent purchases classified correctly, automatically.",
    chip: "from-amber-100 to-amber-50",
    ring: "from-amber-400 to-orange-400",
  },
  {
    emoji: "💼",
    title: "Freelancers & Consultants",
    detail: "Invoice clients, track receivables, and see profit per project. Your whole practice, balanced by an accountant that never sleeps.",
    chip: "from-indigo-100 to-indigo-50",
    ring: "from-indigo-400 to-violet-400",
  },
  {
    emoji: "🏗️",
    title: "Agencies & Services",
    detail: "Project profitability, supplier payables, and recurring expenses — every engagement's true margin, reported in real time.",
    chip: "from-sky-100 to-sky-50",
    ring: "from-sky-400 to-blue-400",
  },
  {
    emoji: "🏢",
    title: "Small & Medium Businesses",
    detail: "Multi-tenant isolation, role-based permissions, audit trails, and confirmation gates — finance controls that grow with your team.",
    chip: "from-rose-100 to-rose-50",
    ring: "from-rose-400 to-pink-400",
  },
  {
    emoji: "🧾",
    title: "Accounting Practices",
    detail: "Let the AI do the data entry while you do the judgment. Review AI-posted entries, approve gates, and deliver statements faster.",
    chip: "from-violet-100 to-violet-50",
    ring: "from-violet-400 to-purple-400",
  },
];

export default function SolutionsPage() {
  return (
    <PageShell
      eyebrow="Built for every ledger"
      title="One AI accountant,"
      accent="every"
      titleTail="kind of business."
      subtitle="Wherever money moves — sales, purchases, payroll-adjacent spend, assets — Ledger speaks your industry's language."
    >
      <section className="py-16 sm:py-20 pb-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {SEGMENTS.map((s, i) => (
            <div
              key={s.title}
              className="rounded-3xl bg-white/90 backdrop-blur border border-white/80 shadow-[0_22px_48px_-24px_rgba(27,42,74,0.35)] p-7 transition-transform hover:-translate-y-1"
              style={{ animation: `heroRise 0.9s cubic-bezier(0.19,1,0.22,1) ${100 + i * 90}ms both` }}
            >
              <span
                className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${s.chip} clay-chip flex items-center justify-center text-2xl mb-5`}
              >
                {s.emoji}
              </span>
              <h2 className="text-lg font-bold text-brand-navy">{s.title}</h2>
              <p className="mt-2.5 text-sm text-[#3d4b66] leading-relaxed">{s.detail}</p>
              <span className={`mt-5 block h-1 w-14 rounded-full bg-gradient-to-r ${s.ring}`} />
            </div>
          ))}
        </div>
      </section>
    </PageShell>
  );
}
