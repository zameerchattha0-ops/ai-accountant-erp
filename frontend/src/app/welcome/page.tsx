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

/* ---- Feature card ---- */
function FeatureCard({
  icon: Icon,
  title,
  description,
  delay,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
  delay: string;
}) {
  const { ref, inView } = useInView();
  return (
    <div
      ref={ref}
      className={cn(
        "opacity-0 rounded-2xl bg-bg-surface border border-border-subtle p-6 transition-shadow hover:shadow-lg",
        inView && "animate-scale-in",
      )}
      style={{ animationDelay: delay }}
    >
      <div className="w-11 h-11 rounded-xl bg-ai-50 flex items-center justify-center mb-4">
        <Icon className="w-5 h-5 text-ai-600" />
      </div>
      <h3 className="text-sm font-semibold text-text-primary mb-1.5">{title}</h3>
      <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
    </div>
  );
}

/* ---- Step card for How It Works ---- */
function StepCard({
  step,
  icon: Icon,
  title,
  description,
  delay,
}: {
  step: number;
  icon: React.ElementType;
  title: string;
  description: string;
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
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-teal to-brand-navy flex items-center justify-center mb-4 shadow-lg shadow-brand-teal/20">
        <Icon className="w-7 h-7 text-white" />
      </div>
      <span className="text-xs font-bold text-ai-600 uppercase tracking-widest mb-1">
        Step {step}
      </span>
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
    },
    {
      icon: BarChart3,
      title: "Real-time Financial Reports",
      description:
        "Profit and Loss, Balance Sheet, Cash Flow, Trial Balance. All reports update the moment entries are posted.",
    },
    {
      icon: Building2,
      title: "Multi-tenant Architecture",
      description:
        "Each organization gets isolated data with row-level security. Your books stay private and compliant.",
    },
    {
      icon: BookOpen,
      title: "Automated Journal Engine",
      description:
        "Documents like invoices and purchase bills automatically generate balanced journal entries. No manual debits and credits.",
    },
    {
      icon: Search,
      title: "Smart Entity Search",
      description:
        "Find customers, suppliers, accounts, and transactions instantly with fuzzy search across your entire ledger.",
    },
    {
      icon: ShieldCheck,
      title: "Enterprise Compliance",
      description:
        "Role-based permissions, audit trails, confirmation gates for high-risk operations, and full accounting period management.",
    },
  ];

  return (
    <div className={cn(cinzel.variable, cormorant.variable, "min-h-screen bg-bg-primary")}>
      {/* ============================================================ */}
      {/* NAVBAR — high contrast against the dark stage                */}
      {/* ============================================================ */}
      <nav
        className={cn(
          "fixed top-0 left-0 right-0 z-50 transition-all duration-500",
          scrolled
            ? "bg-[#04070d]/85 backdrop-blur-xl border-b border-white/10 py-2.5"
            : "bg-gradient-to-b from-[#04070d]/85 via-[#04070d]/40 to-transparent py-4",
        )}
      >
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex items-center justify-between">
          <Link href="/" className="flex items-center">
            {/* The logo artwork is dark navy — seat it on a light chip so it
                always reads against the dark stage. */}
            <span className="inline-flex items-center rounded-lg bg-white px-3 py-1.5 shadow-lg shadow-black/50">
              <Image
                src="/ai-accountant.png"
                alt="AI Accountant"
                width={132}
                height={36}
                className="h-6 w-auto object-contain"
                priority
              />
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="px-4 py-2 rounded-xl text-sm font-medium text-white/85 hover:text-white border border-white/15 hover:border-white/35 hover:bg-white/5 backdrop-blur-sm transition-all"
            >
              Login
            </Link>
            <Link
              href="/signup"
              className="px-5 py-2 rounded-xl bg-brand-teal hover:bg-teal-400 text-[#03150f] text-sm font-semibold transition-all shadow-lg shadow-brand-teal/25 hover:shadow-brand-teal/45 hover:-translate-y-px"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* ============================================================ */}
      {/* HERO — the elite universe                                    */}
      {/* ============================================================ */}
      <section
        ref={heroRef}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
        className="hero-stage relative min-h-screen flex items-center"
      >
        {/* Interactive constellation layer */}
        <HeroCanvas />

        {/* Ambient scene layers */}
        <div className="hero-aurora hero-aurora-a" />
        <div className="hero-aurora hero-aurora-b" />
        <div className="hero-grid" />
        <div className="hero-grain" />
        <div className="hero-vignette" />

        <div className="hero-copy relative z-10 w-full max-w-6xl mx-auto px-4 sm:px-6 py-32">
          <div className="max-w-3xl">
            <p
              className="hero-eyebrow inline-flex items-center gap-3 text-[11px] font-medium uppercase text-teal-200/90 mb-7"
              style={{ animationDelay: "80ms" }}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-teal-300 animate-pulse" />
              AI-native accounting for modern businesses
            </p>

            <h1
              className="text-white text-5xl sm:text-6xl lg:text-7xl leading-[1.08] font-semibold"
              style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
            >
              <span className="reveal-line">
                <span style={{ "--d": "200ms" } as React.CSSProperties}>Your books,</span>
              </span>
              <span className="reveal-line">
                <span style={{ "--d": "420ms" } as React.CSSProperties}>
                  <span
                    className="hero-gradient-word font-medium italic"
                    style={{ fontFamily: "var(--font-cormorant), Georgia, serif" }}
                  >
                    balanced
                  </span>{" "}
                  by AI.
                </span>
              </span>
            </h1>

            <p
              className="mt-7 text-lg sm:text-xl text-white/85 leading-relaxed max-w-xl font-light"
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
                className="hero-btn-primary inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-gradient-to-b from-teal-300 to-teal-500 text-[#03150f] font-semibold text-base transition-all shadow-xl shadow-teal-500/25 hover:shadow-teal-400/45 hover:-translate-y-0.5"
              >
                Start Free <ArrowRight className="w-4 h-4" />
              </Link>
              <Link
                href="/login"
                className="inline-flex items-center px-8 py-4 rounded-xl text-white font-medium text-base border border-white/20 bg-white/5 hover:bg-white/10 hover:border-white/40 backdrop-blur-sm transition-all"
              >
                Sign In
              </Link>
            </div>
          </div>
        </div>

        {/* Scroll cue */}
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2 text-white/60">
          <span
            className="text-[10px] uppercase tracking-[0.3em]"
            style={{ fontFamily: "var(--font-cinzel), Georgia, serif" }}
          >
            Scroll
          </span>
          <span className="hero-scrollcue block w-px h-9 bg-gradient-to-b from-teal-300/80 to-transparent" />
        </div>

        {/* Bottom gradient fade into the page */}
        <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-bg-primary to-transparent z-[5]" />
      </section>

      {/* ============================================================ */}
      {/* FEATURES                                                      */}
      {/* ============================================================ */}
      <section className="py-24 sm:py-32">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <Section className="text-center mb-16">
            <span className="text-xs font-bold text-ai-600 uppercase tracking-widest mb-3 block">
              Features
            </span>
            <h2 className="text-3xl sm:text-4xl font-bold text-text-primary mb-4">
              Everything your accountant needs
            </h2>
            <p className="text-text-secondary text-lg max-w-2xl mx-auto">
              A complete ERP built for small businesses that want accurate
              books without the complexity.
            </p>
          </Section>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
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
      <section className="py-24 sm:py-32 bg-brand-aqua-soft/60">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <Section className="text-center mb-16">
            <span className="text-xs font-bold text-ai-600 uppercase tracking-widest mb-3 block">
              How It Works
            </span>
            <h2 className="text-3xl sm:text-4xl font-bold text-text-primary mb-4">
              Up and running in minutes
            </h2>
            <p className="text-text-secondary text-lg max-w-xl mx-auto">
              Three simple steps to transform how you manage your finances.
            </p>
          </Section>

          <div className="grid md:grid-cols-3 gap-12 md:gap-8">
            <StepCard
              step={1}
              icon={UserPlus}
              title="Create Your Account"
              description="Sign up with your email. Verify your identity and you are ready to go."
              delay="0ms"
            />
            <StepCard
              step={2}
              icon={Settings2}
              title="Set Up Your Organization"
              description="Enter your business details. Your chart of accounts, financial year, and document numbering are created automatically."
              delay="150ms"
            />
            <StepCard
              step={3}
              icon={TrendingUp}
              title="Start Accounting"
              description="Tell the AI about your transactions. Invoices, purchases, expenses, and reports are handled end to end."
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
          <div className="grid sm:grid-cols-3 gap-8 text-center">
            <Section animation="animate-scale-in" delay="0ms">
              <div className="text-4xl sm:text-5xl font-bold text-brand-navy mb-2">
                <Counter target={36} />
              </div>
              <p className="text-text-secondary text-sm">AI-powered tools</p>
            </Section>
            <Section animation="animate-scale-in" delay="120ms">
              <div className="text-4xl sm:text-5xl font-bold text-brand-navy mb-2">
                <Counter target={12} />
              </div>
              <p className="text-text-secondary text-sm">Financial report types</p>
            </Section>
            <Section animation="animate-scale-in" delay="240ms">
              <div className="text-4xl sm:text-5xl font-bold text-brand-navy mb-2">
                <Counter target={78} />
              </div>
              <p className="text-text-secondary text-sm">Validated parameters</p>
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
            <div className="rounded-3xl bg-gradient-to-br from-brand-navy via-[#1f3560] to-brand-navy p-10 sm:p-16 text-center relative overflow-hidden">
              {/* Subtle teal glow */}
              <div className="absolute top-0 right-0 w-72 h-72 bg-brand-teal/10 rounded-full blur-3xl" />
              <div className="absolute bottom-0 left-0 w-56 h-56 bg-brand-teal/5 rounded-full blur-3xl" />

              <div className="relative z-10">
                <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
                  Ready to automate your accounting?
                </h2>
                <p className="text-white/60 text-lg max-w-xl mx-auto mb-8">
                  Join businesses that trust AI Accountant to keep their
                  books balanced, accurate, and audit-ready.
                </p>
                <Link
                  href="/signup"
                  className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-brand-teal hover:bg-teal-400 text-white font-semibold text-base transition-all shadow-lg shadow-brand-teal/30"
                >
                  Get Started Free <ArrowRight className="w-4 h-4" />
                </Link>
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
