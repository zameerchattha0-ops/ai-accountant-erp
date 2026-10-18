"use client";

import { ArrowRight, Check, Sparkles } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { HERO_TAGLINES } from "@/data/heroTaglines";
import GlassTaglineCarousel from "@/components/hero/GlassTaglineCarousel";

/* Ledger — client-only (WebGL never runs on the server), same as classic. */
const HeroRobotStage = dynamic(
  () => import("@/components/hero/HeroRobotStage"),
  { ssr: false }
);

/* ---------------------------------------------------------------------
   NAVY HERO — the premium variant (2026-10-14 palette recommendation).

   Psychology: a deep-navy anchor (#131E33 -> #1B2A4A) is the most trusted
   field in fintech, it makes the teal accent POP, and white headline text
   hits ~14:1 contrast (instant legibility = retention).  60-30-10 rule:
   60% navy field, 30% white type/surfaces, 10% teal — spent ONLY on the
   primary CTA, the checks and one radial glow.  One easing family (the
   house cubic-bezier(0.19,1,0.22,1)), entrances staggered 80ms, all
   motion opacity/transform only; prefers-reduced-motion is honoured by
   the global kill-switch in globals.css.

   REVERSIBLE: the classic light stage is preserved verbatim in
   welcome/page.tsx — set NEXT_PUBLIC_HERO_VARIANT=classic to restore it.
   --------------------------------------------------------------------- */

function LinkedInIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 1 1 0-4.125 2.062 2.062 0 0 1 0 4.125zM7.119 20.452H3.555V9h3.564v11.452z" />
    </svg>
  );
}

const ease = "cubic-bezier(0.19,1,0.22,1)";
const rise = (delayMs: number) => ({
  animation: `heroRise 1s ${ease} ${delayMs}ms both`,
});

export default function NavyHero() {
  return (
    <section className="lp-stage relative min-h-screen flex items-center overflow-hidden">
      {/* The navy field — one gradient, one grain, one teal breath of glow
          behind the mascot. Nothing else competes for the eye. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(135deg, #131E33 0%, #1B2A4A 55%, #16233F 100%)",
        }}
      />
      {/* Teal radial glow behind Ledger — the single decorative accent. */}
      <div
        className="absolute right-[-6%] top-1/2 -translate-y-1/2 w-[46rem] h-[46rem] rounded-full blur-3xl opacity-60 pointer-events-none"
        style={{
          background:
            "radial-gradient(circle, rgba(20,184,166,0.20) 0%, rgba(20,184,166,0.06) 45%, transparent 70%)",
        }}
      />
      <div className="lp-grain" />

      <div className="relative z-10 w-full max-w-6xl mx-auto px-4 sm:px-6 pt-28 pb-24 lg:pt-32 lg:pb-28 lg:self-stretch lg:flex lg:flex-col lg:justify-center">
        <div className="grid grid-cols-1 lg:grid-cols-[1.04fr_0.96fr] gap-6 lg:gap-8 items-center">
          {/* COPY COLUMN — eyebrow, rotating headline, subline, one solid
              CTA + one ghost, then the trust strip. */}
          <div className="max-w-xl min-w-0">
            <p
              className="hero-eyebrow inline-flex items-center gap-2.5 rounded-full bg-white/5 border border-white/10 px-4 py-2 text-[10px] sm:text-[11px] font-bold uppercase tracking-[0.16em] text-ai-200 mb-7"
              style={rise(80)}
            >
              <Sparkles className="w-3.5 h-3.5 text-ai-200 shrink-0" />
              <span className="min-w-0">AI-native accounting for modern businesses</span>
            </p>

            <h1
              className="text-white text-[1.55rem] sm:text-[1.9rem] lg:text-[2.25rem] leading-[1.26] tracking-[0.01em] font-bold max-w-[36rem] lg:pr-6"
              style={{ fontFamily: "var(--font-bodoni), Georgia, serif" }}
            >
              <span className="sr-only">{HERO_TAGLINES[0].text}</span>
              <GlassTaglineCarousel />
            </h1>

            <p
              className="mt-7 text-lg sm:text-xl text-white/75 leading-relaxed max-w-xl font-light"
              style={rise(220)}
            >
              Record transactions in plain English. Get instant financial
              reports. Let the AI handle debits, credits, and compliance
              while you focus on growing your business.
            </p>

            <div className="flex flex-wrap items-center gap-4 mt-10" style={rise(300)}>
              <Link
                href="/signup"
                className="inline-flex items-center gap-2.5 px-8 py-4 rounded-full bg-ai-600 hover:bg-ai-700 text-white font-semibold text-base shadow-[0_18px_40px_-16px_rgba(20,184,166,0.45)] hover:shadow-[0_22px_48px_-16px_rgba(20,184,166,0.55)] hover:-translate-y-0.5 transition-all duration-150"
              >
                Start Free <ArrowRight className="w-4 h-4" />
              </Link>
              <a
                href="https://pk.linkedin.com/in/zameerhaiderchattha"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-3 pl-3 pr-7 py-3 rounded-full border border-white/20 text-white/90 hover:bg-white/5 hover:border-white/40 font-semibold text-base transition-all duration-150"
              >
                <span className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center">
                  <LinkedInIcon className="w-4 h-4 text-ai-200" />
                </span>
                Contact
              </a>
            </div>

            {/* Trust strip — the 10% accent budget, nothing more. */}
            <div className="flex flex-wrap gap-x-6 gap-y-2.5 mt-8" style={rise(380)}>
              {["No credit card required", "Set up in minutes", "Built for startups & SMEs"].map((tb) => (
                <span key={tb} className="inline-flex items-center gap-2 text-[13px] font-medium text-white/60">
                  <span className="w-[18px] h-[18px] rounded-full bg-ai-500/15 border border-ai-500/40 flex items-center justify-center shrink-0">
                    <Check className="w-3 h-3 text-ai-200" strokeWidth={3.5} />
                  </span>
                  {tb}
                </span>
              ))}
            </div>
          </div>



          {/* LEDGER'S STAGE — same geometry as classic so switching
              variants never reflows the page; dark glass chips instead of
              the light ones. Click Ledger for his routines. */}
          <div
            className="relative h-[420px] sm:h-[500px] md:h-[540px] -mb-24 lg:mb-0 -mx-3 sm:mx-0 lg:absolute lg:z-20 lg:inset-y-0 lg:mx-0 lg:h-auto lg:left-1/2 lg:w-[50vw]"
            onPointerDown={(e) => {
              if (!(e.target instanceof HTMLCanvasElement)) return;
              const reactions = ["bow", "robotdance", "wave", "kungfu"] as const;
              const cmd = reactions[Math.floor(Math.random() * reactions.length)];
              window.dispatchEvent(new CustomEvent("ledger-command", { detail: { command: cmd } }));
            }}
          >
            <div className="absolute inset-0 z-10 cursor-pointer">
              <HeroRobotStage variant="hero" />
            </div>

            {/* The proof-of-automation chip — for an accounting product,
                "AI just posted" converts better than any illustration. */}
            <div
              className="hero-float absolute top-[12%] left-[2%] md:left-[6%] z-0 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-md px-4 py-3 shadow-[0_16px_40px_-18px_rgba(0,0,0,0.5)] pointer-events-none"
              style={rise(460)}
            >
              <span className="block text-[11px] font-bold text-white">AI posted 42 entries</span>
              <span className="flex items-center gap-1.5 text-[10px] font-semibold text-ai-200 mt-0.5">
                <Check className="w-2.5 h-2.5" strokeWidth={3} /> 2 min ago · balanced
              </span>
            </div>

            <div
              className="hero-float absolute bottom-[18%] right-[2%] md:right-[8%] z-0 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-md px-4 py-3 shadow-[0_16px_40px_-18px_rgba(0,0,0,0.5)] pointer-events-none"
              style={rise(540)}
            >
              <span className="block text-[11px] font-bold text-white">Sales Invoice</span>
              <span className="flex items-center gap-1 text-[10px] font-semibold text-ai-200">
                <Check className="w-2.5 h-2.5" strokeWidth={3} /> Created · INV-2025-001
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Scroll cue — white/40 type, teal hairline. */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2 text-white/40">
        <span
          className="text-[10px] uppercase tracking-[0.3em]"
          style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
        >
          Scroll
        </span>
        <span className="lp-scrollcue block w-px h-9 bg-gradient-to-b from-ai-500/70 to-transparent" />
      </div>
    </section>
  );
}
