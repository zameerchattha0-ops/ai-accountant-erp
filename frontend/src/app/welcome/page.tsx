"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { Cinzel, Cormorant_Garamond } from "next/font/google";
import {
  Brain, BarChart3, Building2, BookOpen, Search, ShieldCheck,
  UserPlus, Settings2, TrendingUp, ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { useInView } from "@/lib/hooks/useInView";
import HeroCanvas from "@/components/welcome/HeroCanvas";

/* Premium editorial type: Cinzel = Roman inscriptional display capitals
   (Trajan-style, extended edges) for the hero; Cormorant Garamond italic
   for the accent word. Body text keeps the app's sans stack. */
const cinzel = Cinzel({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-cinzel",
  display: "swap",
});
const cormorant = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-cormorant",
  display: "swap",
});

/* ---- Reusable animated section wrapper ---- */
function Section({
  children,
  className,
  animation = "animate-fade-in-up",
  delay = "0ms",
}: {
  children: React.ReactNode;
  className?: string;
  animation?: string;
  delay?: string;
}) {
  const { ref, inView } = useInView();
  return (
    <div
      ref={ref}
      className={cn(
        "opacity-0",
        inView && animation,
        className,
      )}
      style={{ animationDelay: delay }}
    >
      {children}
    </div>
  );
}

/* ---- Animated counter ---- */
function Counter({ target, suffix = "" }: { target: number; suffix?: string }) {
  const { ref, inView } = useInView();
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!inView) return;
    let start = 0;
    const duration = 1800;
    const step = Math.max(1, Math.floor(target / (duration / 16)));
    const timer = setInterval(() => {
      start += step;
      if (start >= target) {
        setCount(target);
        clearInterval(timer);
      } else {
        setCount(start);
      }
    }, 16);
    return () => clearInterval(timer);
  }, [inView, target]);

  return <span ref={ref}>{count.toLocaleString()}{suffix}</span>;
}

/* ---- Feature card — glass pane in a gradient hairline ring ---- */
function FeatureCard({
  icon: Icon,
  title,
  description,
  tone,
  delay,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
  tone: { chip: string; icon: string; from: string; to: string };
  delay: string;
}) {
  const { ref, inView } = useInView();
  return (
    <div
      ref={ref}
      className={cn(
        "opacity-0 group relative rounded-3xl p-[1.5px] transition-transform duration-300 hover:-translate-y-1.5",
        inView && "animate-scale-in",
      )}
      style={{
        animationDelay: delay,
        background: `linear-gradient(135deg, ${tone.from}, ${tone.to})`,
      }}
    >
      <div className="glass-panel rounded-[calc(1.5rem-1.5px)] p-6 h-full">
        <div
          className={cn(
            "w-12 h-12 rounded-2xl flex items-center justify-center mb-4 clay-chip transition-transform duration-300 group-hover:scale-110 group-hover:rotate-3",
            tone.chip,
          )}
        >
          <Icon className={cn("w-5 h-5", tone.icon)} />
        </div>
        <h3 className="text-sm font-semibold text-text-primary mb-1.5">{title}</h3>
        <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
      </div>
    </div>
  );
}

/* ---- Step card for How It Works — claymorphic disc ---- */
function StepCard({
  step,
  icon: Icon,
  title,
  description,
  tone,
  delay,
}: {
  step: number;
  icon: React.ElementType;
  title: string;
  description: string;
  tone: { disc: string; stepText: string; badge: string };
  delay: string;
}) {
  const { ref, inView } = useInView();
  return (
    <div
      ref={ref}
      className={cn(
        "opacity-0 flex flex-col items-center text-center",
        inView && "animate-slide-in-left",
      )}
      style={{ animationDelay: delay }}
    >
      <div
        className={cn(
          "relative w-16 h-16 rounded-3xl flex items-center justify-center mb-4 clay-chip transition-transform duration-300 hover:scale-110",
          tone.disc,
        )}
      >
        <Icon className={cn("w-7 h-7", tone.stepText)} />
        <span
          className={cn(
            "absolute -top-2 -right-2 w-7 h-7 rounded-full text-white text-xs font-bold flex items-center justify-center shadow-md",
            tone.badge,
          )}
        >
          {step}
        </span>
      </div>
      <h3 className="text-base font-semibold text-text-primary mb-2">{title}</h3>
      <p className="text-sm text-text-secondary leading-relaxed max-w-64">{description}</p>
    </div>
  );
}

/* ================================================================== */
/* LANDING PAGE                                                         */
/* ================================================================== */
export default function WelcomePage() {
  const [scrolled, setScrolled] = useState(false);
  const heroRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  /* Cursor parallax: writes normalised pointer offsets into --px/--py on
     the hero stage; the aurora glows drift AGAINST the cursor while the
     copy lifts WITH it — a subtle, physical sense of depth. */
  const handlePointerMove = (e: React.PointerEvent) => {
    const el = heroRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--px", ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
    el.style.setProperty("--py", ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
  };
  const handlePointerLeave = () => {
    const el = heroRef.current;
    if (!el) return;
    el.style.setProperty("--px", "0");
    el.style.setProperty("--py", "0");
  };

  const features = [
    {
      icon: Brain,
      title: "AI Accounting Agent",
      description:
        "Tell the AI what happened in plain language. It handles the journal entries, posting, and reconciliation automatically.",
      tone: {
        chip: "bg-gradient-to-br from-teal-100 to-teal-50",
        icon: "text-teal-600",
        from: "#2dd4bf",
        to: "#0ea5e9",
      },
    },
    {
      icon: BarChart3,
      title: "Real-time Financial Reports",
      description:
        "Profit and Loss, Balance Sheet, Cash Flow, Trial Balance. All reports update the moment entries are posted.",
      tone: {
        chip: "bg-gradient-to-br from-indigo-100 to-indigo-50",
        icon: "text-indigo-600",
        from: "#818cf8",
        to: "#6366f1",
      },
    },
    {
      icon: Building2,
      title: "Multi-tenant Architecture",
      description:
        "Each organization gets isolated data with row-level security. Your books stay private and compliant.",
      tone: {
        chip: "bg-gradient-to-br from-rose-100 to-rose-50",
        icon: "text-rose-600",
        from: "#fb7185",
        to: "#e11d48",
      },
    },
    {
      icon: BookOpen,
      title: "Automated Journal Engine",
      description:
        "Documents like invoices and purchase bills automatically generate balanced journal entries. No manual debits and credits.",
      tone: {
        chip: "bg-gradient-to-br from-amber-100 to-amber-50",
        icon: "text-amber-600",
        from: "#fbbf24",
        to: "#f59e0b",
      },
    },
    {
      icon: Search,
      title: "Smart Entity Search",
      description:
        "Find customers, suppliers, accounts, and transactions instantly with fuzzy search across your entire ledger.",
      tone: {
        chip: "bg-gradient-to-br from-sky-100 to-sky-50",
        icon: "text-sky-600",
        from: "#38bdf8",
        to: "#0284c7",
      },
    },
    {
      icon: ShieldCheck,
      title: "Enterprise Compliance",
      description:
        "Role-based permissions, audit trails, confirmation gates for high-risk operations, and full accounting period management.",
      tone: {
        chip: "bg-gradient-to-br from-violet-100 to-violet-50",
        icon: "text-violet-600",
        from: "#a78bfa",
        to: "#7c3aed",
      },
    },
  ];

  return (
    <div className={cn(cinzel.variable, cormorant.variable, "min-h-screen bg-bg-primary")}>
      {/* ============================================================ */}
      {/* NAVBAR — light floating glass                                 */}
      {/* ============================================================ */}
      <nav
        className={cn(
          "fixed top-0 left-0 right-0 z-50 transition-all duration-500",
          scrolled
            ? "bg-white/70 backdrop-blur-2xl border-b border-white/80 shadow-[0_10px_40px_-18px_rgba(27,42,74,0.25)] py-2.5"
            : "bg-transparent py-4",
        )}
      >
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex items-center justify-between">
          <Link href="/" className="flex items-center">
            <Image
              src="/ai-accountant.png"
              alt="AI Accountant"
              width={140}
              height={38}
              className="h-8 w-auto object-contain"
              priority
            />
          </Link>
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="px-4 py-2 rounded-xl text-sm font-semibold text-brand-navy hover:text-ai-700 border border-transparent hover:border-border-default hover:bg-white/70 transition-all"
            >
              Login
            </Link>
            <Link
              href="/signup"
              className="lp-btn-primary px-5 py-2 rounded-xl bg-gradient-to-r from-teal-500 to-indigo-500 text-white text-sm font-semibold transition-all shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/45 hover:-translate-y-px"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* ============================================================ */}
      {/* HERO — surrealist glass-clay light stage                      */}
      {/* ============================================================ */}
      <section
        ref={heroRef}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
        className="lp-stage relative min-h-screen flex items-center"
      >
        {/* Interactive multi-colour constellation */}
        <HeroCanvas />

        {/* Surrealist colour clouds */}
        <div className="lp-blob lp-blob-a" />
        <div className="lp-blob lp-blob-b" />
        <div className="lp-blob lp-blob-c" />

        {/* Floating glass geometry */}
        <div className="lp-shape lp-shape-square" />
        <div className="lp-shape lp-shape-square-2" />
        <div className="lp-shape lp-shape-ring" />

        {/* Whisper of grain */}
        <div className="lp-grain" />

        <div className="lp-copy relative z-10 w-full max-w-6xl mx-auto px-4 sm:px-6 py-32">
          <div className="max-w-3xl">
            <p
              className="hero-eyebrow inline-flex items-center gap-3 text-[11px] font-bold uppercase text-brand-navy/70 mb-7"
              style={{ animationDelay: "80ms" }}
            >
              <span className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse [animation-delay:200ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse [animation-delay:400ms]" />
              </span>
              AI-native accounting for modern businesses
            </p>

            <h1
              className="text-brand-navy text-5xl sm:text-6xl lg:text-7xl leading-[1.08] font-semibold"
              style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
            >
              <span className="reveal-line">
                <span style={{ "--d": "200ms" } as React.CSSProperties}>Your books,</span>
              </span>
              <span className="reveal-line">
                <span style={{ "--d": "420ms" } as React.CSSProperties}>
                  <span
                    className="text-aurora font-medium italic"
                    style={{ fontFamily: "var(--font-cormorant), Georgia, serif" }}
                  >
                    balanced
                  </span>{" "}
                  by AI.
                </span>
              </span>
            </h1>

            <p
              className="mt-7 text-lg sm:text-xl text-[#3d4b66] leading-relaxed max-w-xl font-light"
              style={{ animation: "heroRise 1s cubic-bezier(0.19,1,0.22,1) 650ms both" }}
            >
              Record transactions in plain English. Get instant financial
              reports. Let the AI handle debits, credits, and compliance
              while you focus on growing your business.
            </p>

            <div
              className="flex flex-wrap gap-4 mt-10"
              style={{ animation: "heroRise 1s cubic-bezier(0.19,1,0.22,1) 820ms both" }}
            >
              <Link
                href="/signup"
                className="lp-btn-primary inline-flex items-center gap-2 px-8 py-4 rounded-2xl bg-gradient-to-r from-teal-500 to-indigo-500 text-white font-semibold text-base transition-all shadow-xl shadow-indigo-500/30 hover:shadow-indigo-500/50 hover:-translate-y-0.5"
              >
                Start Free <ArrowRight className="w-4 h-4" />
              </Link>
              <Link
                href="/login"
                className="inline-flex items-center px-8 py-4 rounded-2xl glass-panel text-brand-navy font-semibold text-base transition-all hover:-translate-y-0.5"
              >
                Sign In
              </Link>
            </div>
          </div>
        </div>

        {/* Scroll cue */}
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2 text-brand-navy/50">
          <span
            className="text-[10px] uppercase tracking-[0.3em]"
            style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
          >
            Scroll
          </span>
          <span className="lp-scrollcue block w-px h-9 bg-gradient-to-b from-indigo-500/70 to-transparent" />
        </div>
      </section>

      {/* ============================================================ */}
      {/* FEATURES                                                      */}
      {/* ============================================================ */}
      <section className="py-24 sm:py-32">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <Section className="text-center mb-16">
            <span className="text-xs font-bold text-ai-700 uppercase tracking-widest mb-3 block">
              Features
            </span>
            <h2 className="text-3xl sm:text-4xl font-bold text-brand-navy mb-4">
              Everything your <span className="text-aurora">accountant</span> needs
            </h2>
            <p className="text-[#3d4b66] text-lg max-w-2xl mx-auto">
              A complete ERP built for small businesses that want accurate
              books without the complexity.
            </p>
          </Section>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((f, i) => (
              <FeatureCard
                key={f.title}
                {...f}
                delay={`${i * 80}ms`}
              />
            ))}
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* HOW IT WORKS                                                   */}
      {/* ============================================================ */}
      <section className="relative py-24 sm:py-32">
        {/* Surreal colour wash behind the steps */}
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-brand-aqua-soft/70 to-transparent pointer-events-none" />
        <div className="relative max-w-6xl mx-auto px-4 sm:px-6">
          <Section className="text-center mb-16">
            <span className="text-xs font-bold text-indigo-600 uppercase tracking-widest mb-3 block">
              How It Works
            </span>
            <h2 className="text-3xl sm:text-4xl font-bold text-brand-navy mb-4">
              Up and running in <span className="text-aurora">minutes</span>
            </h2>
            <p className="text-[#3d4b66] text-lg max-w-xl mx-auto">
              Three simple steps to transform how you manage your finances.
            </p>
          </Section>

          <div className="grid md:grid-cols-3 gap-12 md:gap-8">
            <StepCard
              step={1}
              icon={UserPlus}
              title="Create Your Account"
              description="Sign up with your email. Verify your identity and you are ready to go."
              tone={{ disc: "bg-teal-50", stepText: "text-teal-600", badge: "bg-teal-500" }}
              delay="0ms"
            />
            <StepCard
              step={2}
              icon={Settings2}
              title="Set Up Your Organization"
              description="Enter your business details. Your chart of accounts, financial year, and document numbering are created automatically."
              tone={{ disc: "bg-indigo-50", stepText: "text-indigo-600", badge: "bg-indigo-500" }}
              delay="150ms"
            />
            <StepCard
              step={3}
              icon={TrendingUp}
              title="Start Accounting"
              description="Tell the AI about your transactions. Invoices, purchases, expenses, and reports are handled end to end."
              tone={{ disc: "bg-amber-50", stepText: "text-amber-600", badge: "bg-amber-500" }}
              delay="300ms"
            />
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* STATS                                                          */}
      {/* ============================================================ */}
      <section className="py-24 sm:py-32">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="grid sm:grid-cols-3 gap-6">
            <Section animation="animate-scale-in" delay="0ms">
              <div className="glass-panel rounded-3xl p-8 text-center transition-transform duration-300 hover:-translate-y-1">
                <div
                  className="text-4xl sm:text-5xl font-bold mb-2 text-aurora"
                  style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
                >
                  <Counter target={36} />
                </div>
                <p className="text-[#3d4b66] text-sm font-medium">AI-powered tools</p>
              </div>
            </Section>
            <Section animation="animate-scale-in" delay="120ms">
              <div className="glass-panel rounded-3xl p-8 text-center transition-transform duration-300 hover:-translate-y-1">
                <div
                  className="text-4xl sm:text-5xl font-bold mb-2 text-brand-navy"
                  style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
                >
                  <Counter target={12} />
                </div>
                <p className="text-[#3d4b66] text-sm font-medium">Financial report types</p>
              </div>
            </Section>
            <Section animation="animate-scale-in" delay="240ms">
              <div className="glass-panel rounded-3xl p-8 text-center transition-transform duration-300 hover:-translate-y-1">
                <div
                  className="text-4xl sm:text-5xl font-bold mb-2 text-brand-navy"
                  style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
                >
                  <Counter target={78} />
                </div>
                <p className="text-[#3d4b66] text-sm font-medium">Validated parameters</p>
              </div>
            </Section>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* CTA                                                            */}
      {/* ============================================================ */}
      <section className="py-24 sm:py-32">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <Section>
            <div className="relative rounded-[2rem] p-[1.5px]" style={{ background: "linear-gradient(135deg, #2dd4bf, #6366f1 45%, #f59e0b 80%, #ec4899)" }}>
              <div className="glass-panel rounded-[calc(2rem-1.5px)] p-10 sm:p-16 text-center relative overflow-hidden">
                {/* Surreal floating accents inside the panel */}
                <div className="absolute -top-16 -right-16 w-56 h-56 rounded-full bg-gradient-to-br from-teal-200/50 to-transparent blur-3xl pointer-events-none" />
                <div className="absolute -bottom-20 -left-16 w-64 h-64 rounded-full bg-gradient-to-tr from-indigo-200/50 to-transparent blur-3xl pointer-events-none" />
                <div className="lp-shape lp-shape-square !w-16 !h-16 !top-8 !left-10 opacity-70" />

                <div className="relative z-10">
                  <h2 className="text-3xl sm:text-4xl font-bold text-brand-navy mb-4">
                    Ready to <span className="text-aurora">automate</span> your accounting?
                  </h2>
                  <p className="text-[#3d4b66] text-lg max-w-xl mx-auto mb-8">
                    Join businesses that trust AI Accountant to keep their
                    books balanced, accurate, and audit-ready.
                  </p>
                  <Link
                    href="/signup"
                    className="lp-btn-primary inline-flex items-center gap-2 px-8 py-4 rounded-2xl bg-gradient-to-r from-teal-500 to-indigo-500 text-white font-semibold text-base transition-all shadow-xl shadow-indigo-500/30 hover:shadow-indigo-500/50 hover:-translate-y-0.5"
                  >
                    Get Started Free <ArrowRight className="w-4 h-4" />
                  </Link>
                </div>
              </div>
            </div>
          </Section>
        </div>
      </section>

      {/* ============================================================ */}
      {/* FOOTER                                                         */}
      {/* ============================================================ */}
      <footer className="border-t border-border-subtle py-8">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Image
              src="/ai-accountant.png"
              alt="AI Accountant"
              width={100}
              height={28}
              className="h-6 w-auto object-contain opacity-70"
            />
          </div>
          <p className="text-xs text-text-muted">
            &copy; {new Date().getFullYear()} AI Accountant. Developed by Zameer Haider.
          </p>
          <div className="flex items-center gap-4 text-xs text-text-muted">
            <Link href="/login" className="hover:text-text-primary transition-colors">
              Login
            </Link>
            <Link href="/signup" className="hover:text-text-primary transition-colors">
              Sign Up
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
