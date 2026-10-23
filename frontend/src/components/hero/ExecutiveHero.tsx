"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  ArrowRight,
  Sparkles,
  Clock,
  Layers,
  FileText,
  X,
  CheckCircle2,
  Play,
} from "lucide-react";

/* ---------------------------------------------------------------------
   EXECUTIVE HERO — Elite Class, Ultra-Fast, Zero-Three.js Hero
   Reference: docs/Hero Section for Bigger Screens.png & Hero Section Mobile View.png
   Backdrop: docs/Background Image for hero Section.png (sunrise executive desk)
   Mascot: Lightweight 2D floating Ledger hologram badge (Zero WebGL overhead)
   --------------------------------------------------------------------- */

const FEATURE_PILLS = [
  {
    icon: Sparkles,
    title: "AI-Powered",
    subtitle: "Accounting",
  },
  {
    icon: Clock,
    title: "Double Entry",
    subtitle: "Accurate & Reliable",
  },
  {
    icon: Layers,
    title: "Built for SMEs",
    subtitle: "and Freelancers",
  },
  {
    icon: FileText,
    title: "Financial Reports",
    subtitle: "in Seconds",
  },
];

const STATS = [
  { value: "10K+", label: "Businesses Trust Us" },
  { value: "1M+", label: "Transactions Processed" },
  { value: "99.9%", label: "Accurate Entries" },
  { value: "24/7", label: "AI Finance Assistant" },
];

export default function ExecutiveHero() {
  const [isVideoModalOpen, setIsVideoModalOpen] = useState(false);

  return (
    <>
      <section className="relative min-h-screen flex flex-col justify-between overflow-hidden pt-24 sm:pt-28 lg:pt-32 pb-8 sm:pb-12">
        {/* ============================================================== */}
        {/* BACKDROP: Executive High-Rise Sunrise Suite & Marble Desk     */}
        {/* ============================================================== */}
        <div className="absolute inset-0 z-0">
          <Image
            src="/images/hero/executive-hero-bg.webp"
            alt="Ai Accountant Executive Penthouse Office"
            fill
            priority
            sizes="100vw"
            className="object-cover object-center lg:object-center select-none pointer-events-none"
          />
          {/* Subtle soft white & warm sunrise veil on copy side to ensure 100% WCAG contrast */}
          <div className="absolute inset-0 bg-gradient-to-r from-white/95 via-white/85 to-white/70 lg:to-transparent lg:w-[62%] pointer-events-none" />
          <div className="absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-white/90 to-transparent pointer-events-none" />
          <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-white/95 via-white/60 to-transparent pointer-events-none" />
        </div>

        {/* ============================================================== */}
        {/* MAIN HERO CONTENT CONTAINER                                    */}
        {/* ============================================================== */}
        <div className="relative z-10 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex-1 flex flex-col justify-center">
          <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-8 lg:gap-12 items-center">
            {/* LEFT COLUMN: Authority Headline, Paragraph, CTAs, Pills */}
            <div className="max-w-2xl min-w-0">
              {/* Eyebrow with horizontal rule */}
              <div
                className="flex items-center gap-3.5 mb-5 sm:mb-6"
                style={{ animation: "heroRise 0.8s cubic-bezier(0.19,1,0.22,1) 80ms both" }}
              >
                <span className="text-[10.5px] sm:text-[11.5px] font-bold tracking-[0.22em] text-slate-500 uppercase">
                  Intelligence for your numbers
                </span>
                <span className="h-[1.5px] w-12 sm:w-20 bg-slate-400/60 inline-block" />
              </div>

              {/* Authority Display Headline */}
              <h1
                className="text-slate-900 text-[2.4rem] sm:text-[3.25rem] lg:text-[4rem] xl:text-[4.35rem] leading-[1.08] tracking-tight font-serif font-normal"
                style={{
                  fontFamily: '"IvyBodoni", "Ivy Bodoni", "ivybodoni", var(--font-bodoni), "Bodoni Moda", Didot, "Bodoni MT", Georgia, serif',
                  animation: "heroRise 0.9s cubic-bezier(0.19,1,0.22,1) 180ms both",
                }}
              >
                Accounting
                <br />
                that Understands
                <br />
                <span
                  className="italic text-[#0D9488]"
                  style={{ fontFamily: '"IvyBodoni", "Ivy Bodoni", "ivybodoni", var(--font-bodoni), var(--font-cormorant), Georgia, serif' }}
                >
                  Your
                </span>{" "}
                Business.
              </h1>

              {/* Sub-copy */}
              <p
                className="mt-6 sm:mt-7 text-[15px] sm:text-base lg:text-[17px] text-slate-700 font-normal leading-relaxed max-w-xl"
                style={{ animation: "heroRise 0.9s cubic-bezier(0.19,1,0.22,1) 280ms both" }}
              >
                Create invoices, record purchases, manage ledgers and generate financial
                reports — all through an AI that truly understands accounting, so you can
                focus on what grows your business.
              </p>

              {/* CTA Group: Start Free Pill + See How It Works */}
              <div
                className="flex flex-wrap items-center gap-5 sm:gap-7 mt-8 sm:mt-10"
                style={{ animation: "heroRise 0.9s cubic-bezier(0.19,1,0.22,1) 360ms both" }}
              >
                {/* Primary Emerald/Dark Spruce Button */}
                <Link
                  href="/signup"
                  className="inline-flex items-center justify-center gap-2.5 px-8 py-4 rounded-full bg-[#04332D] hover:bg-[#07473F] text-white font-medium text-sm sm:text-base shadow-[0_12px_28px_-6px_rgba(4,51,45,0.45)] hover:shadow-[0_16px_34px_-6px_rgba(4,51,45,0.55)] hover:-translate-y-0.5 active:translate-y-0 transition-all duration-200"
                >
                  <span>Start for Free</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>

                {/* Secondary Play Button */}
                <button
                  type="button"
                  onClick={() => setIsVideoModalOpen(true)}
                  className="group inline-flex items-center gap-3.5 text-left focus:outline-none cursor-pointer"
                >
                  <span className="w-12 h-12 rounded-full bg-white/95 border border-white/80 shadow-[0_4px_16px_-2px_rgba(15,23,42,0.12)] flex items-center justify-center shrink-0 group-hover:scale-105 group-hover:shadow-[0_6px_20px_-2px_rgba(15,23,42,0.18)] transition-all duration-200">
                    <Play className="w-4 h-4 fill-[#0D9488] text-[#0D9488] translate-x-0.5" />
                  </span>
                  <span className="flex flex-col">
                    <span className="text-sm sm:text-[15px] font-semibold text-slate-900 group-hover:text-teal-700 transition-colors">
                      See how it works
                    </span>
                    <span className="text-xs text-slate-500 font-normal">
                      2-minute overview
                    </span>
                  </span>
                </button>
              </div>

              {/* Micro-Trust Feature Pills (Responsive: 2-col on mobile, wrap on desktop) */}
              <div
                className="grid grid-cols-2 lg:flex lg:flex-wrap items-center gap-2.5 sm:gap-3 mt-8 sm:mt-10"
                style={{ animation: "heroRise 0.9s cubic-bezier(0.19,1,0.22,1) 440ms both" }}
              >
                {FEATURE_PILLS.map((pill, idx) => {
                  const Icon = pill.icon;
                  return (
                    <div
                      key={idx}
                      className="inline-flex items-center gap-2 sm:gap-2.5 px-3 sm:px-3.5 py-2 rounded-full bg-white/85 backdrop-blur-md border border-white shadow-[0_4px_16px_-4px_rgba(15,23,42,0.07)]"
                    >
                      <span className="w-6 h-6 sm:w-7 sm:h-7 rounded-full bg-teal-50 border border-teal-100/80 text-teal-600 flex items-center justify-center shrink-0">
                        <Icon className="w-3 sm:w-3.5 h-3 sm:h-3.5" />
                      </span>
                      <div className="text-left text-[11px] sm:text-xs leading-tight">
                        <div className="font-semibold text-slate-900">{pill.title}</div>
                        <div className="text-[10px] sm:text-[11px] text-slate-500">{pill.subtitle}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* RIGHT COLUMN (DESKTOP): Keeps grid space open so laptop in executive background is cleanly framed */}
            <div className="hidden lg:block h-full min-h-[440px]" aria-hidden="true" />
          </div>
        </div>

        {/* ============================================================== */}
        {/* BOTTOM METRICS STRIP: 10K+ | 1M+ | 99.9% | 24/7                */}
        {/* ============================================================== */}
        <div className="relative z-10 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-10 sm:mt-12">
          {/* Subtle horizontal separator line */}
          <div className="w-full h-px bg-slate-300/60 mb-6 sm:mb-8" />

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-6 lg:gap-8 items-center justify-between">
            {STATS.map((stat, idx) => (
              <div
                key={stat.label}
                className="flex items-center justify-between relative group"
              >
                <div className="flex flex-col">
                  <span
                    className="text-2xl sm:text-3xl lg:text-4xl font-bold text-slate-900 tracking-tight font-serif"
                    style={{ fontFamily: '"IvyBodoni", "Ivy Bodoni", "ivybodoni", var(--font-bodoni), "Bodoni Moda", Didot, "Bodoni MT", Georgia, serif' }}
                  >
                    {stat.value}
                  </span>
                  <span className="text-xs sm:text-sm text-slate-600 font-normal mt-0.5">
                    {stat.label}
                  </span>
                </div>
                {/* Vertical Divider */}
                {idx < STATS.length - 1 && (
                  <span className="hidden lg:block w-px h-10 bg-slate-300/60 absolute right-0" />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================================== */}
      {/* "SEE HOW IT WORKS" VIDEO / OVERVIEW MODAL                     */}
      {/* ============================================================== */}
      {isVideoModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-slate-950/70 backdrop-blur-sm transition-all"
        >
          <div
            className="relative w-full max-w-3xl rounded-3xl bg-white border border-slate-200 shadow-2xl p-6 sm:p-8 overflow-hidden"
            style={{ animation: "heroRise 0.35s cubic-bezier(0.19,1,0.22,1) both" }}
          >
            {/* Modal Close Button */}
            <button
              type="button"
              onClick={() => setIsVideoModalOpen(false)}
              className="absolute top-5 right-5 w-10 h-10 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 flex items-center justify-center transition-colors focus:outline-none"
              aria-label="Close modal"
            >
              <X className="w-5 h-5" />
            </button>

            {/* Modal Header */}
            <div className="pr-12">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-teal-700 bg-teal-50 border border-teal-100 px-3 py-1 rounded-full mb-3">
                <Sparkles className="w-3.5 h-3.5 text-teal-600" />
                2-Minute Product Tour
              </span>
              <h2
                className="text-2xl sm:text-3xl font-bold text-slate-900 font-serif"
                style={{ fontFamily: '"IvyBodoni", "Ivy Bodoni", "ivybodoni", var(--font-bodoni), "Bodoni Moda", Didot, "Bodoni MT", Georgia, serif' }}
              >
                Accounting that Truly Understands Your Business
              </h2>
              <p className="mt-2 text-sm text-slate-600">
                Watch how natural language turns directly into verified double-entry ledgers,
                invoices, and real-time financial statements.
              </p>
            </div>

            {/* Interactive Showcase Preview */}
            <div className="relative mt-6 rounded-2xl overflow-hidden border border-slate-200 bg-slate-50 aspect-video flex flex-col justify-center items-center text-center p-6">
              <Image
                src="/images/hero/laptop-showcase.webp"
                alt="Product Dashboard Preview"
                fill
                className="object-cover opacity-90"
              />
              <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-[2px]" />
              <div className="relative z-10 max-w-md text-white">
                <span className="w-16 h-16 rounded-full bg-white/20 backdrop-blur-md border border-white/40 flex items-center justify-center mx-auto mb-4 shadow-xl">
                  <Play className="w-6 h-6 fill-white text-white translate-x-0.5" />
                </span>
                <p className="text-base font-semibold">
                  Autonomous Accounting Engine in Action
                </p>
                <p className="text-xs text-white/80 mt-1">
                  100% Deterministic Python Controls + Single Reasoning LLM
                </p>
              </div>
            </div>

            {/* Key Highlights */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-6">
              {[
                "Natural language transaction input",
                "Automatic debits & credits ledgering",
                "Instant P&L, Balance Sheet, Trial Balance",
              ].map((highlight, idx) => (
                <div key={idx} className="flex items-center gap-2 text-xs text-slate-700">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span>{highlight}</span>
                </div>
              ))}
            </div>

            {/* Modal Bottom Action */}
            <div className="mt-6 pt-5 border-t border-slate-100 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                Ready to transform your company&apos;s finance?
              </span>
              <Link
                href="/signup"
                className="inline-flex items-center gap-2 px-6 py-2.5 rounded-full bg-[#04332D] hover:bg-[#07473F] text-white text-xs sm:text-sm font-semibold transition-all shadow-md"
              >
                Get Started Free <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
