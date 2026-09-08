"use client";

/* Pricing — early-access plans */

import Link from "next/link";
import PageShell from "@/components/welcome/PageShell";
import { Check, ArrowRight } from "lucide-react";

const PLANS = [
  {
    name: "Starter",
    tagline: "For solo founders finding their feet",
    monthly: "Free",
    period: "during early access",
    features: ["1 organization", "AI transaction recording", "Journal → Ledger → Trial Balance", "Core financial statements", "Email support"],
    cta: "Start Free",
    href: "/signup",
    highlight: false,
    c: "from-teal-500 to-emerald-400",
  },
  {
    name: "Pro",
    tagline: "For growing businesses that move fast",
    monthly: "PKR 4,900",
    period: "per organization / month",
    features: ["Everything in Starter", "Invoicing, quotations & receipts", "Purchases, payables & banking", "Aging & project profitability reports", "Priority support"],
    cta: "Get Started",
    href: "/signup",
    highlight: true,
    c: "from-indigo-500 to-violet-500",
  },
  {
    name: "Business",
    tagline: "For teams that need full control",
    monthly: "PKR 12,900",
    period: "per organization / month",
    features: ["Everything in Pro", "Role-based permissions & audit trails", "Confirmation gates & period management", "Multi-organization management", "Direct line to the founder"],
    cta: "Talk to Zameer",
    href: "https://pk.linkedin.com/in/zameerhaiderchattha",
    highlight: false,
    c: "from-rose-500 to-pink-500",
  },
];

export default function PricingPage() {
  return (
    <PageShell
      eyebrow="Simple, honest pricing"
      title="Pricing that grows"
      accent="with"
      titleTail="you."
      subtitle="Start free during early access. Upgrade only when your books — not our paywall — tell you it's time."
    >
      <section className="py-16 sm:py-20 pb-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 grid md:grid-cols-3 gap-6 items-stretch">
          {PLANS.map((p, i) => (
            <div
              key={p.name}
              className={`relative rounded-[2rem] bg-white/90 backdrop-blur border shadow-[0_26px_54px_-26px_rgba(27,42,74,0.4)] p-8 flex flex-col ${
                p.highlight ? "border-transparent ring-2 ring-indigo-400/60 md:-translate-y-3" : "border-white/80"
              }`}
              style={{ animation: `heroRise 0.9s cubic-bezier(0.19,1,0.22,1) ${120 + i * 110}ms both` }}
            >
              {p.highlight && (
                <span className="absolute -top-3.5 left-1/2 -translate-x-1/2 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 text-white text-[11px] font-bold px-4 py-1.5 shadow-lg shadow-indigo-500/30">
                  Most Popular
                </span>
              )}
              <span className={`block h-1.5 w-12 rounded-full bg-gradient-to-r ${p.c} mb-5`} />
              <h2 className="text-xl font-bold text-brand-navy">{p.name}</h2>
              <p className="text-xs text-[#64748b] mt-1">{p.tagline}</p>
              <div className="mt-5 flex items-baseline gap-2">
                <span className="text-3xl font-black text-brand-navy">{p.monthly}</span>
              </div>
              <span className="text-[11px] text-[#64748b]">{p.period}</span>
              <ul className="mt-6 space-y-2.5 flex-1">
                {p.features.map((f) => (
                  <li key={f} className="flex items-start gap-2.5 text-sm text-[#3d4b66]">
                    <span className={`w-4.5 h-4.5 mt-0.5 w-[18px] h-[18px] rounded-full bg-gradient-to-br ${p.c} flex items-center justify-center shrink-0`}>
                      <Check className="w-2.5 h-2.5 text-white" strokeWidth={3.5} />
                    </span>
                    {f}
                  </li>
                ))}
              </ul>
              {p.href.startsWith("http") ? (
                <a
                  href={p.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`mt-7 inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold text-white bg-gradient-to-r ${p.c} shadow-lg hover:-translate-y-0.5 transition-all`}
                >
                  {p.cta} <ArrowRight className="w-4 h-4" />
                </a>
              ) : (
                <Link
                  href={p.href}
                  className={`mt-7 inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold text-white bg-gradient-to-r ${p.c} shadow-lg hover:-translate-y-0.5 transition-all`}
                >
                  {p.cta} <ArrowRight className="w-4 h-4" />
                </Link>
              )}
            </div>
          ))}
        </div>
        <p className="mt-10 text-center text-xs text-[#64748b]">
          Early-access pricing — locked in for lifetime when you join now. No credit card required to start.
        </p>
      </section>
    </PageShell>
  );
}
