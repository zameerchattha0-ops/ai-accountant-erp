"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import { HERO_TAGLINES } from "@/data/heroTaglines";

// Elite glass transition easing — a fast, weightless exit curve that gives
// glass panels their signature floaty pop. The softer exit curve slows the
// leaving line so the crossfade never feels rushed.
const ELASTIC = [0.16, 1, 0.3, 1] as const;
const SOFT_EXIT = [0.22, 1, 0.36, 1] as const;

// Sweep: a frosted glass line that wipes across behind the text.
const SWEEP_VARIANTS = {
  hidden: {
    opacity: 0,
    scaleX: 0.3,
    transition: { duration: 0.75, ease: ELASTIC },
  },
  visible: {
    opacity: 0.95,
    scaleX: 1,
    transition: { duration: 0.75, ease: ELASTIC },
  },
  exit: {
    opacity: 0,
    scaleX: 0.3,
    transition: { duration: 0.6, ease: SOFT_EXIT },
  },
};

// Chip: the frosted backdrop-blur glass card that holds the line.
const CHIP_VARIANTS = {
  hidden: {
    opacity: 0,
    filter: "blur(12px)",
    transition: { duration: 0.85, ease: ELASTIC },
  },
  visible: {
    opacity: 1,
    filter: "blur(0px)",
    transition: {
      duration: 0.85,
      ease: ELASTIC,
      delay: 0.06,
    },
  },
  exit: {
    opacity: 0,
    filter: "blur(12px)",
    transition: { duration: 0.6, ease: SOFT_EXIT },
  },
};

// Text: rises out of the blur and settles into focus.
const TEXT_VARIANTS = {
  hidden: {
    opacity: 0,
    y: 20,
    filter: "blur(10px)",
    transition: { duration: 0.85, ease: ELASTIC },
  },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: {
      duration: 0.85,
      ease: ELASTIC,
      delay: 0.04,
    },
  },
  exit: {
    opacity: 0,
    y: -20,
    filter: "blur(10px)",
    transition: { duration: 0.7, ease: SOFT_EXIT },
  },
};

export default function GlassTaglineCarousel() {
  const idxRef = useRef(0);
  const [idx, setIdx] = useState(0);
  const [prevIdx, setPrevIdx] = useState<number | null>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.matches) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = () => {
      if (cancelled) return;
      const prev = idxRef.current;
      const next = (prev + 1) % HERO_TAGLINES.length;
      setPrevIdx(prev);
      idxRef.current = next;
      setIdx(next);
      timer = setTimeout(tick, HERO_TAGLINES[next].dur);
    };

    // First swap after the initial reveal lands + one full dwell.
    timer = setTimeout(tick, HERO_TAGLINES[0].dur + 1200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  // Retire the outgoing line once its exit animation has fully played.
  useEffect(() => {
    if (prevIdx === null) return;
    const id = setTimeout(() => setPrevIdx(null), 850);
    return () => clearTimeout(id);
  }, [prevIdx]);

  return (
    <div className="tagline-reveal-wrap">
      <AnimatePresence mode="popLayout">
        <motion.div
          key={`sweep-${idx}`}
          variants={SWEEP_VARIANTS}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="glass-sweep-line"
        />
        <motion.div
          key={idx}
          variants={CHIP_VARIANTS}
          initial="hidden"
          animate="visible"
          exit="exit"
          layout
          className="glass-tagline-chip"
        >
          <motion.span
            key={`text-${idx}`}
            variants={TEXT_VARIANTS}
            className="tagline-pastel-text"
            style={{
              fontFamily: "var(--font-bodoni), Georgia, serif",
              fontStyle: "italic",
              fontWeight: 700,
              fontSize: "inherit",
            }}
          >
            {HERO_TAGLINES[idx].text}
          </motion.span>
        </motion.div>
      </AnimatePresence>
      <span className="sr-only">{HERO_TAGLINES[idx].text}</span>
    </div>
  );
}