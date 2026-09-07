"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  Brain, BarChart3, Building2, BookOpen, Search, ShieldCheck,
  UserPlus, Settings2, TrendingUp, ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { useInView } from "@/lib/hooks/useInView";

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

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

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
    <div className="min-h-screen bg-bg-primary">
      {/* ============================================================ */}
      {/* NAVBAR                                                        */}
      {/* ============================================================ */}
      <nav
        className={cn(
          "fixed top-0 left-0 right-0 z-50 transition-all duration-300",
          scrolled
            ? "glass border-b border-border-subtle/50 py-2.5"
            : "bg-transparent py-4",
        )}
      >
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex items-center justify-between">
          <Link href="/welcome" className="flex items-center gap-2.5">
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
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Login
            </Link>
            <Link
              href="/signup"
              className="px-5 py-2 rounded-xl bg-brand-teal hover:bg-brand-navy text-white text-sm font-semibold transition-colors shadow-md shadow-brand-teal/20"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* ============================================================ */}
      {/* HERO                                                          */}
      {/* ============================================================ */}
      <section className="relative min-h-screen flex items-center overflow-hidden">
        {/* Background image */}
        <div className="absolute inset-0">
          <Image
            src="/hero-bg.png"
            alt=""
            fill
            className="object-cover"
            priority
          />
          {/* Dark gradient overlay for text readability */}
          <div className="absolute inset-0 bg-gradient-to-r from-brand-navy/92 via-brand-navy/75 to-brand-navy/50" />
        </div>

        <div className="relative z-10 max-w-6xl mx-auto px-4 sm:px-6 py-32">
          <div className="max-w-2xl">
            <Section animation="animate-fade-in-up" delay="100ms">
              <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/10 backdrop-blur-sm border border-white/10 text-xs font-medium text-white/80 mb-6">
                <span className="w-1.5 h-1.5 rounded-full bg-brand-teal animate-pulse" />
                AI-native accounting for modern businesses
              </span>
            </Section>

            <Section animation="animate-fade-in-up" delay="250ms">
              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-white leading-[1.1] mb-6">
                Your books,{" "}
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-teal to-emerald-300">
                  balanced
                </span>{" "}
                by AI.
              </h1>
            </Section>

            <Section animation="animate-fade-in-up" delay="400ms">
              <p className="text-lg sm:text-xl text-white/70 leading-relaxed mb-8 max-w-xl">
                Record transactions in plain English. Get instant financial
                reports. Let the AI handle debits, credits, and compliance
                while you focus on growing your business.
              </p>
            </Section>

            <Section animation="animate-fade-in-up" delay="550ms">
              <div className="flex flex-wrap gap-3">
                <Link
                  href="/signup"
                  className="px-7 py-3.5 rounded-xl bg-brand-teal hover:bg-teal-400 text-white font-semibold text-base transition-all shadow-lg shadow-brand-teal/30 hover:shadow-brand-teal/40 flex items-center gap-2"
                >
                  Start Free <ArrowRight className="w-4 h-4" />
                </Link>
                <Link
                  href="/login"
                  className="px-7 py-3.5 rounded-xl bg-white/10 hover:bg-white/15 text-white font-medium text-base backdrop-blur-sm border border-white/10 transition-all"
                >
                  Sign In
                </Link>
              </div>
            </Section>
          </div>
        </div>

        {/* Bottom gradient fade */}
        <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-bg-primary to-transparent" />
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
