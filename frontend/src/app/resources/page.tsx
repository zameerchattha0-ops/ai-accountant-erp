"use client";

/* Resources — guides, docs, and direct support */

import Link from "next/link";
import PageShell from "@/components/welcome/PageShell";
import { BookOpen, Workflow, Landmark, ShieldCheck, MessageCircle, Mail, ArrowRight } from "lucide-react";

const GUIDES = [
  {
    icon: Workflow,
    title: "The 8-step AI workflow",
    detail: "How a spoken sentence becomes a balanced journal entry — Describe, Understand, Clarify, Confirm, Execute, Connect, Report, Manual.",
    chip: "bg-gradient-to-br from-teal-100 to-teal-50",
    icon2: "text-teal-600",
  },
  {
    icon: Landmark,
    title: "Chart of Accounts, explained",
    detail: "How the AI classifies asset, liability, equity, revenue, and expense accounts — and how you can reshape the tree to fit your business.",
    chip: "bg-gradient-to-br from-indigo-100 to-indigo-50",
    icon2: "text-indigo-600",
  },
  {
    icon: BookOpen,
    title: "From journal to statements",
    detail: "The relay: Journal → Ledger → Trial Balance → Financial Statements. What updates the moment an entry posts, and what to check before sign-off.",
    chip: "bg-gradient-to-br from-amber-100 to-amber-50",
    icon2: "text-amber-600",
  },
  {
    icon: ShieldCheck,
    title: "Trust, security & control",
    detail: "Row-level tenant isolation, role-based access, audit trails, and confirmation gates — why AI-posted entries are safe entries.",
    chip: "bg-gradient-to-br from-rose-100 to-rose-50",
    icon2: "text-rose-600",
  },
];

const LINKS = [
  { label: "Explore Features", href: "/features" },
  { label: "See How It Works", href: "/how-it-works" },
  { label: "Find Your Solution", href: "/solutions" },
  { label: "View Pricing", href: "/pricing" },
];

export default function ResourcesPage() {
  return (
    <PageShell
      eyebrow="Learn the system"
      title="Resources for"
      accent="confident"
      titleTail="books."
      subtitle="Short, honest guides on how the AI thinks, posts, and protects your numbers."
    >
      <section className="py-16 sm:py-20">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 grid sm:grid-cols-2 gap-6">
          {GUIDES.map((g, i) => (
            <div
              key={g.title}
              className="rounded-3xl bg-white/90 backdrop-blur border border-white/80 shadow-[0_22px_48px_-24px_rgba(27,42,74,0.35)] p-7 transition-transform hover:-translate-y-1"
              style={{ animation: `heroRise 0.9s cubic-bezier(0.19,1,0.22,1) ${100 + i * 90}ms both` }}
            >
              <span className={`w-12 h-12 rounded-2xl ${g.chip} clay-chip flex items-center justify-center mb-5`}>
                <g.icon className={`w-5 h-5 ${g.icon2}`} />
              </span>
              <h2 className="text-lg font-bold text-brand-navy">{g.title}</h2>
              <p className="mt-2.5 text-sm text-[#3d4b66] leading-relaxed">{g.detail}</p>
            </div>
          ))}
        </div>
      </section>

      {/* direct support */}
      <section className="pb-24">
        <div className="max-w-3xl mx-auto px-4 sm:px-6">
          <div className="rounded-[2rem] bg-white/85 backdrop-blur border border-white/80 shadow-[0_26px_54px_-26px_rgba(27,42,74,0.4)] px-7 sm:px-10 py-9 text-center">
            <h2
              className="text-2xl font-semibold text-brand-navy"
              style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}
            >
              Talk to the <span className="text-aurora italic">human</span> behind the AI.
            </h2>
            <p className="mt-3 text-sm text-[#3d4b66]">
              Feature requests, accounting questions, or a live walkthrough — Zameer answers personally.
            </p>
            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <a
                href="https://wa.me/923230714288"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-gradient-to-r from-emerald-500 to-teal-500 text-white text-sm font-semibold shadow-lg shadow-emerald-500/25 hover:-translate-y-0.5 transition-all"
              >
                <MessageCircle className="w-4 h-4" /> WhatsApp
              </a>
              <a
                href="mailto:zameerchattha0@gmail.com"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-white border border-white text-brand-navy text-sm font-semibold shadow-lg hover:-translate-y-0.5 transition-all"
              >
                <Mail className="w-4 h-4 text-indigo-500" /> Email
              </a>
            </div>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[13px] text-[#3d4b66]">
              {LINKS.map((l) => (
                <Link key={l.label} href={l.href} className="inline-flex items-center gap-1 hover:text-brand-navy transition-colors">
                  {l.label} <ArrowRight className="w-3 h-3 opacity-50" />
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
