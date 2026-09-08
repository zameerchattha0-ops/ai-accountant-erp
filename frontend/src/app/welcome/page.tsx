"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { Cinzel, Cormorant_Garamond } from "next/font/google";
import {
  Brain, BarChart3, Building2, BookOpen, Search, ShieldCheck,
  ArrowRight, MessageSquareText, HelpCircle, Zap, Workflow,
  FileBarChart, PencilLine, Mail, MessageCircle, ChevronRight,
  BadgeCheck, FileText, Send, ShoppingCart, Sparkles,
  TrendingUp, TrendingDown,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { useInView } from "@/lib/hooks/useInView";
import HeroCanvas from "@/components/welcome/HeroCanvas";
import dynamic from "next/dynamic";

/* "Ledger" — the hero-stage 3D mascot. Client-only: WebGL never runs on
   the server; renders nothing until the scene is interactive. */
const HeroRobotStage = dynamic(() => import("@/components/welcome/HeroRobot"), {
  ssr: false,
  loading: () => null,
});


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

/* Brand glyph — lucide-react no longer ships brand icons (Linkedin was
   removed from the library), so the LinkedIn mark is inlined here. */
function LinkedInIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 1 1 0-4.125 2.062 2.062 0 0 1 0 4.125zM7.119 20.452H3.555V9h3.564v11.452z" />
    </svg>
  );
}

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
  icon: LucideIcon;
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

/* ---- Workflow step card — one stage of the core AI pipeline ---- */
function WorkflowCard({
  icon: Icon,
  step,
  title,
  description,
  tone,
  delay,
}: {
  icon: LucideIcon;
  step: number;
  title: string;
  description: string;
  tone: { chip: string; icon: string; badge: string; from: string; to: string };
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
      <div className="glass-panel rounded-[calc(1.5rem-1.5px)] p-5 h-full">
        <div className="flex items-center justify-between mb-4">
          <div
            className={cn(
              "w-11 h-11 rounded-xl flex items-center justify-center clay-chip transition-transform duration-300 group-hover:scale-110 group-hover:rotate-3",
              tone.chip,
            )}
          >
            <Icon className={cn("w-5 h-5", tone.icon)} />
          </div>
          <span
            className={cn(
              "w-7 h-7 rounded-full text-white text-xs font-bold flex items-center justify-center shadow-md",
              tone.badge,
            )}
          >
            {step}
          </span>
        </div>
        <h3 className="text-sm font-semibold text-brand-navy mb-1.5">{title}</h3>
        <p className="text-xs text-[#3d4b66] leading-relaxed">{description}</p>
      </div>
    </div>
  );
}

/* ---- Floating glass chip that orbits Ledger's hero stage ---- */
function FloatChip({
  icon: Icon,
  chip,
  icon2,
  title,
  sub,
  delay,
  target,
}: {
  icon: LucideIcon;
  chip: string;
  icon2: string;
  title: string;
  sub: string;
  delay: string;
  target?: string;
}) {
  return (
    <div
      data-ledger-target={target}
      className="hero-float glass-panel glass-soft rounded-2xl px-4 py-3 flex items-center gap-3 shadow-lg"
      style={{ animation: `floaty 6s ease-in-out ${delay} infinite` }}
    >
      <span className={cn("w-9 h-9 rounded-xl clay-chip flex items-center justify-center shrink-0", chip)}>
        <Icon className={cn("w-4 h-4", icon2)} />
      </span>
      <span className="min-w-0 max-w-[10.5rem]">
        <span className="block text-[13px] font-semibold text-brand-navy">{title}</span>
        <span className="block text-[11px] text-[#3d4b66] truncate">{sub}</span>
      </span>
    </div>
  );
}

/* ---- Mini feature strip along the hero's bottom edge ---- */
const HERO_STRIP: { icon: LucideIcon; label: string; chip: string; icon2: string }[] = [
  { icon: Sparkles, label: "AI-Powered Accounting", chip: "bg-gradient-to-br from-violet-100 to-violet-50", icon2: "text-violet-600" },
  { icon: FileText, label: "Invoicing & Receivables", chip: "bg-gradient-to-br from-sky-100 to-sky-50", icon2: "text-sky-600" },
  { icon: ShoppingCart, label: "Purchases & Payables", chip: "bg-gradient-to-br from-amber-100 to-amber-50", icon2: "text-amber-600" },
  { icon: BarChart3, label: "Ledger to Financial Statements", chip: "bg-gradient-to-br from-indigo-100 to-indigo-50", icon2: "text-indigo-600" },
  { icon: PencilLine, label: "Manual Entry Supported", chip: "bg-gradient-to-br from-rose-100 to-rose-50", icon2: "text-rose-600" },
  { icon: ShieldCheck, label: "Secure & Compliant", chip: "bg-gradient-to-br from-emerald-100 to-emerald-50", icon2: "text-emerald-600" },
];

/* ================================================================== */
/* LANDING PAGE                                                         */
/* ================================================================== */
export default function WelcomePage() {
  const [scrolled, setScrolled] = useState(false);
  const heroRef = useRef<HTMLElement>(null);
  /* Business Overview chart bars — Ledger re-randomises them when he pokes the card */
  const DEFAULT_BARS = [38, 55, 42, 70, 48, 62, 80, 58, 90, 66, 74, 95, 60, 85, 52, 78, 68, 88];
  const [bars, setBars] = useState<number[]>(DEFAULT_BARS);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  /* Ledger's interactions: when he pokes a hero element, that element
     pops/glows; the Business Overview chart also gets fresh data. */
  useEffect(() => {
    const onPoke = (e: Event) => {
      const target = (e as CustomEvent<{ target: string }>).detail?.target;
      if (!target) return;
      const el = document.querySelector(`[data-ledger-target="${target}"]`);
      if (el) {
        el.classList.remove("ledger-poked");
        void (el as HTMLElement).offsetWidth; // restart the animation
        el.classList.add("ledger-poked");
        window.setTimeout(() => el.classList.remove("ledger-poked"), 1500);
      }
      if (target === "overview") {
        setBars(Array.from({ length: 18 }, () => Math.round(30 + Math.random() * 65)));
      }
    };
    window.addEventListener("ledger-poke", onPoke);
    return () => window.removeEventListener("ledger-poke", onPoke);
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

  /* Core workflow — from the project summary */
  const workflow = [
    {
      icon: MessageSquareText,
      title: "Describe",
      description: "Tell the AI what happened in natural language — no forms, no tabs.",
      tone: { chip: "bg-gradient-to-br from-teal-100 to-teal-50", icon: "text-teal-600", badge: "bg-teal-500", from: "#2dd4bf", to: "#0ea5e9" },
    },
    {
      icon: Brain,
      title: "Understand",
      description: "The AI identifies the transaction and reasons about its accounting nature.",
      tone: { chip: "bg-gradient-to-br from-indigo-100 to-indigo-50", icon: "text-indigo-600", badge: "bg-indigo-500", from: "#818cf8", to: "#6366f1" },
    },
    {
      icon: HelpCircle,
      title: "Clarify",
      description: "Targeted questions for anything missing: amount, purpose, cash or credit, party, asset or expense.",
      tone: { chip: "bg-gradient-to-br from-amber-100 to-amber-50", icon: "text-amber-600", badge: "bg-amber-500", from: "#fbbf24", to: "#f59e0b" },
    },
    {
      icon: ShieldCheck,
      title: "Confirm",
      description: "You approve the understanding and the proposed accounting treatment where required.",
      tone: { chip: "bg-gradient-to-br from-rose-100 to-rose-50", icon: "text-rose-600", badge: "bg-rose-500", from: "#fb7185", to: "#e11d48" },
    },
    {
      icon: Zap,
      title: "Execute",
      description: "The AI creates the journal entry and updates the ledger automatically — no manual tab-by-tab entry.",
      tone: { chip: "bg-gradient-to-br from-sky-100 to-sky-50", icon: "text-sky-600", badge: "bg-sky-500", from: "#38bdf8", to: "#0284c7" },
    },
    {
      icon: Workflow,
      title: "Connect",
      description: "Entries flow through Journal → Ledger → Trial Balance → Chart of Accounts → Financial Statements.",
      tone: { chip: "bg-gradient-to-br from-violet-100 to-violet-50", icon: "text-violet-600", badge: "bg-violet-500", from: "#a78bfa", to: "#7c3aed" },
    },
    {
      icon: FileBarChart,
      title: "Report & Document",
      description: "Invoices, quotations, aging, receivable/payable and financial reports — from the same system.",
      tone: { chip: "bg-gradient-to-br from-emerald-100 to-emerald-50", icon: "text-emerald-600", badge: "bg-emerald-500", from: "#34d399", to: "#059669" },
    },
    {
      icon: PencilLine,
      title: "Manual Recording",
      description: "Prefer traditional control? Record journal entries and transactions manually, anytime.",
      tone: { chip: "bg-gradient-to-br from-pink-100 to-pink-50", icon: "text-pink-600", badge: "bg-pink-500", from: "#f472b6", to: "#db2777" },
    },
  ];

  /* Overall flow strip */
  const FLOW = [
    "Business Activity",
    "AI Input",
    "Reasoning",
    "Clarification",
    "Confirmation",
    "Recording",
    "Ledger",
    "Trial Balance",
    "Financial Statements",
  ];
  const FLOW_DOTS = ["bg-teal-500", "bg-indigo-500", "bg-amber-500", "bg-rose-500", "bg-sky-500", "bg-violet-500", "bg-emerald-500", "bg-pink-500", "bg-teal-500"];

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

        {/* Floating glass geometry — traced by perpetual multi-colour light */}
        <div className="lp-shape lp-shape-square lp-trace" />
        <div className="lp-shape lp-shape-square-2 lp-trace" />
        <div className="lp-shape lp-shape-ring" />

        {/* Whisper of grain */}
        <div className="lp-grain" />

        <div className="lp-copy relative z-10 w-full max-w-6xl mx-auto px-4 sm:px-6 pt-28 pb-24 lg:pt-32 lg:pb-28">
          <div className="grid lg:grid-cols-[1.05fr_1fr] gap-6 lg:gap-4 items-center">
            {/* LEFT — copy. Ledger lives in the stage beside this, never over it. */}
            <div className="max-w-xl min-w-0">
            <p
              className="hero-eyebrow lp-eyebrow inline-flex items-center gap-2.5 sm:gap-3 text-[10px] sm:text-[11px] font-bold uppercase text-brand-navy/70 mb-7"
              style={{ animationDelay: "80ms" }}
            >
              <span className="flex gap-1 shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse [animation-delay:200ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse [animation-delay:400ms]" />
              </span>
              <span className="min-w-0">AI-native accounting for modern businesses</span>
            </p>

            <h1
              className="text-brand-navy text-[2.5rem] sm:text-6xl lg:text-7xl leading-[1.1] font-semibold"
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

              {/* trust badges */}
              <div
                className="flex flex-wrap gap-x-6 gap-y-2.5 mt-8"
                style={{ animation: "heroRise 1s cubic-bezier(0.19,1,0.22,1) 950ms both" }}
              >
                {["No credit card required", "Set up in minutes", "Built for startups & SMEs"].map((tb) => (
                  <span key={tb} className="inline-flex items-center gap-2 text-[13px] font-medium text-[#3d4b66]">
                    <BadgeCheck className="w-[18px] h-[18px] text-emerald-500 shrink-0" />
                    {tb}
                  </span>
                ))}
              </div>
            </div>

            {/* RIGHT — Ledger's stage. He roams THIS area only; the floating
                cards are pointer-transparent glass orbiting him. */}
            <div
              className="relative h-[340px] sm:h-[420px] lg:h-[540px] -mx-3 sm:mx-0"
              style={{ animation: "heroRise 1.2s cubic-bezier(0.19,1,0.22,1) 300ms both" }}
            >
              {/* canvas above the chips so Ledger walks IN FRONT of them */}
              <div className="absolute inset-0 z-10">
                <HeroRobotStage variant="hero" />
              </div>

              {/* document chips — left edge, narrow. Ledger walks over and
                  "posts" each one; the chip pops when his hand lands. */}
              <div className="absolute left-0 top-[7%] hidden md:flex flex-col gap-5 pointer-events-none">
                <FloatChip
                  icon={FileText}
                  chip="bg-gradient-to-br from-emerald-100 to-emerald-50"
                  icon2="text-emerald-600"
                  title="Sales Invoice"
                  sub="Created Successfully ✓ INV-2025-001"
                  delay="0s"
                  target="invoice"
                />
                <FloatChip
                  icon={BookOpen}
                  chip="bg-gradient-to-br from-indigo-100 to-indigo-50"
                  icon2="text-indigo-600"
                  title="Journal Entry"
                  sub="Recorded ✓ 2 Lines Posted"
                  delay="1.1s"
                  target="journal"
                />
                <FloatChip
                  icon={BarChart3}
                  chip="bg-gradient-to-br from-sky-100 to-sky-50"
                  icon2="text-sky-600"
                  title="Trial Balance"
                  sub="Updated ✓ As of today"
                  delay="2.2s"
                  target="trial"
                />
              </div>
              {/* Business Overview card — right edge, below the chip zone.
                  Ledger pokes it → card wiggles and the chart refreshes. */}
              <div
                data-ledger-target="overview"
                className="absolute right-0 top-[30%] hidden md:block pointer-events-none"
                style={{ animation: "floaty 7s ease-in-out 0.8s infinite" }}
              >
                <div className="hero-float glass-panel glass-soft rounded-2xl p-4 w-56 shadow-xl">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold text-brand-navy">Business Overview</span>
                    <span className="text-[10px] font-medium text-[#3d4b66] bg-white/80 border border-white rounded-full px-2 py-0.5">
                      This Month
                    </span>
                  </div>
                  <div className="flex items-end gap-[3px] h-16 mb-3">
                    {bars.map((h, i) => (
                      <span
                        key={i}
                        className="flex-1 rounded-full transition-all duration-700 ease-out"
                        style={{ height: `${h}%`, background: "linear-gradient(180deg, #818cf8, #2dd4bf)" }}
                      />
                    ))}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <div className="text-[11px] font-bold text-brand-navy whitespace-nowrap">PKR 1.25M</div>
                      <div className="text-[9px] text-[#3d4b66] flex items-center gap-1">
                        Revenue <TrendingUp className="w-3 h-3 text-emerald-500" />
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] font-bold text-brand-navy whitespace-nowrap">PKR 420K</div>
                      <div className="text-[9px] text-[#3d4b66] flex items-center gap-1">
                        Expenses <TrendingDown className="w-3 h-3 text-rose-500" />
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] font-bold text-brand-navy whitespace-nowrap">PKR 830K</div>
                      <div className="text-[9px] text-[#3d4b66] flex items-center gap-1">
                        Net Profit <TrendingUp className="w-3 h-3 text-emerald-500" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Ask-anything card — bottom right. Ledger taps it → glow + send pulse. */}
              <div
                data-ledger-target="ask"
                className="absolute right-2 bottom-[7%] hidden md:flex pointer-events-none"
                style={{ animation: "floaty 6.5s ease-in-out 1.4s infinite" }}
              >
                <div className="hero-float glass-panel glass-soft rounded-2xl pl-4 pr-2 py-2 flex items-center gap-3 shadow-xl w-72">
                  <Sparkles className="w-4 h-4 text-indigo-500 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-semibold text-brand-navy">Ask anything…</div>
                    <div className="text-[11px] text-[#3d4b66] truncate">&quot;Create an invoice for ABC Tech&quot;</div>
                  </div>
                  <span className="ledger-send w-8 h-8 rounded-xl bg-gradient-to-br from-teal-500 to-indigo-500 flex items-center justify-center shrink-0 shadow-md">
                    <Send className="w-3.5 h-3.5 text-white" />
                  </span>
                </div>
              </div>

              {/* handwritten whisper — bottom left */}
              <div className="absolute left-1 bottom-[4%] hidden lg:block pointer-events-none">
                <span
                  className="text-2xl text-indigo-500/80 italic"
                  style={{ fontFamily: "var(--font-cormorant), Georgia, serif" }}
                >
                  More time for what matters
                </span>
              </div>
            </div>
          </div>

          {/* mini feature strip */}
          <div
            className="mt-12 lg:mt-16 border-t border-white/70 pt-6"
            style={{ animation: "heroRise 1s cubic-bezier(0.19,1,0.22,1) 1100ms both" }}
          >
            <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
              {HERO_STRIP.map(({ icon: Icon, label, chip, icon2 }) => (
                <span key={label} className="inline-flex items-center gap-2.5">
                  <span className={cn("w-9 h-9 rounded-xl clay-chip flex items-center justify-center shrink-0", chip)}>
                    <Icon className={cn("w-4 h-4", icon2)} />
                  </span>
                  <span className="text-[13px] font-semibold text-brand-navy max-w-[9rem] leading-tight">{label}</span>
                </span>
              ))}
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
      {/* CORE WORKFLOW                                                  */}
      {/* ============================================================ */}
      <section className="relative py-24 sm:py-32">
        {/* Surreal colour wash behind the pipeline */}
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-brand-aqua-soft/70 to-transparent pointer-events-none" />
        <div className="relative max-w-6xl mx-auto px-4 sm:px-6">
          <Section className="text-center mb-16">
            <span className="text-xs font-bold text-indigo-600 uppercase tracking-widest mb-3 block">
              The Core Workflow
            </span>
            <h2 className="text-3xl sm:text-4xl font-bold text-brand-navy mb-4">
              From <span className="text-aurora">words</span> to financial statements
            </h2>
            <p className="text-[#3d4b66] text-lg max-w-2xl mx-auto">
              One connected pipeline — describe what happened, and the AI
              reasons, clarifies, confirms, and records it all the way to
              your financial statements.
            </p>
          </Section>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {workflow.map((s, i) => (
              <WorkflowCard
                key={s.title}
                {...s}
                step={i + 1}
                delay={`${i * 70}ms`}
              />
            ))}
          </div>

          {/* Overall flow strip */}
          <Section className="mt-14">
            <div className="glass-panel rounded-3xl px-6 py-5 flex flex-wrap items-center justify-center gap-x-1.5 gap-y-3">
              {FLOW.map((label, i) => (
                <span key={label} className="inline-flex items-center gap-1.5">
                  <span className="inline-flex items-center gap-2 rounded-full bg-white/80 border border-white px-3 py-1.5 text-xs font-semibold text-brand-navy shadow-sm">
                    <span className={cn("w-1.5 h-1.5 rounded-full", FLOW_DOTS[i])} />
                    {label}
                  </span>
                  {i < FLOW.length - 1 && (
                    <ChevronRight className="w-3.5 h-3.5 text-brand-navy/30 shrink-0" />
                  )}
                </span>
              ))}
            </div>
          </Section>
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
      {/* CONTACT                                                        */}
      {/* ============================================================ */}
      <section className="py-24 sm:py-32">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <Section className="text-center mb-12">
            <span className="text-xs font-bold text-rose-600 uppercase tracking-widest mb-3 block">
              Contact
            </span>
            <h2 className="text-3xl sm:text-4xl font-bold text-brand-navy mb-4">
              Built by <span className="text-aurora">Zameer Haider</span>
            </h2>
            <p className="text-[#3d4b66] text-lg max-w-xl mx-auto">
              Questions, feedback, or a live demo for your business — reach
              out on whichever channel suits you.
            </p>
          </Section>

          <div className="grid sm:grid-cols-3 gap-6">
            {/* LinkedIn */}
            <a
              href="https://pk.linkedin.com/in/zameerhaiderchattha"
              target="_blank"
              rel="noreferrer"
              className="group relative rounded-3xl p-[1.5px] transition-transform duration-300 hover:-translate-y-1.5"
              style={{ background: "linear-gradient(135deg, #38bdf8, #0284c7)" }}
            >
              <div className="glass-panel rounded-[calc(1.5rem-1.5px)] p-6 h-full flex items-center gap-4">
                <span className="w-12 h-12 rounded-2xl bg-gradient-to-br from-sky-100 to-sky-50 clay-chip flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-110">
                  <LinkedInIcon className="w-5 h-5 text-sky-600" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-brand-navy">LinkedIn</span>
                  <span className="block text-xs text-[#3d4b66] truncate">zameerhaiderchattha</span>
                </span>
              </div>
            </a>

            {/* Email */}
            <a
              href="mailto:ZAMEERCHATTHA0@GMAIL.COM"
              className="group relative rounded-3xl p-[1.5px] transition-transform duration-300 hover:-translate-y-1.5"
              style={{ background: "linear-gradient(135deg, #fbbf24, #f59e0b)" }}
            >
              <div className="glass-panel rounded-[calc(1.5rem-1.5px)] p-6 h-full flex items-center gap-4">
                <span className="w-12 h-12 rounded-2xl bg-gradient-to-br from-amber-100 to-amber-50 clay-chip flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-110">
                  <Mail className="w-5 h-5 text-amber-600" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-brand-navy">Email</span>
                  <span className="block text-xs text-[#3d4b66] truncate">ZAMEERCHATTHA0@GMAIL.COM</span>
                </span>
              </div>
            </a>

            {/* WhatsApp */}
            <a
              href="https://wa.me/923230714288"
              target="_blank"
              rel="noreferrer"
              className="group relative rounded-3xl p-[1.5px] transition-transform duration-300 hover:-translate-y-1.5"
              style={{ background: "linear-gradient(135deg, #34d399, #059669)" }}
            >
              <div className="glass-panel rounded-[calc(1.5rem-1.5px)] p-6 h-full flex items-center gap-4">
                <span className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-100 to-emerald-50 clay-chip flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-110">
                  <MessageCircle className="w-5 h-5 text-emerald-600" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-brand-navy">WhatsApp</span>
                  <span className="block text-xs text-[#3d4b66]">+92 323 0714288</span>
                </span>
              </div>
            </a>
          </div>
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
            <a
              href="https://pk.linkedin.com/in/zameerhaiderchattha"
              target="_blank"
              rel="noreferrer"
              aria-label="LinkedIn"
              className="hover:text-sky-600 transition-colors"
            >
              <LinkedInIcon className="w-4 h-4" />
            </a>
            <a
              href="mailto:ZAMEERCHATTHA0@GMAIL.COM"
              aria-label="Email"
              className="hover:text-amber-600 transition-colors"
            >
              <Mail className="w-4 h-4" />
            </a>
            <a
              href="https://wa.me/923230714288"
              target="_blank"
              rel="noreferrer"
              aria-label="WhatsApp"
              className="hover:text-emerald-600 transition-colors"
            >
              <MessageCircle className="w-4 h-4" />
            </a>
            <span className="w-px h-4 bg-border-default" />
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
