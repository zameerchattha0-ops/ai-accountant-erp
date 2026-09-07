"use client";

import { useEffect, useRef } from "react";

/* ==================================================================
   HeroCanvas — the "elite universe" layer.
   A slow-drifting constellation of stars that GRAVITATES toward the
   cursor and links nearby stars with faint teal filaments. Fully
   self-contained: DPR-aware, resize-safe, pauses when the tab hides
   and renders a single static frame under prefers-reduced-motion.
   ================================================================== */
export default function HeroCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const mouse = { x: -9999, y: -9999, tx: -9999, ty: -9999 };
    const PULL_RADIUS = 190;

    type Star = { x: number; y: number; vx: number; vy: number; r: number; tw: number; ts: number; c: string };
    // Multi-colour palette tuned for a LIGHT stage (surreal glass-clay).
    const PALETTE = ["13,148,136", "79,70,229", "217,119,6", "219,39,119", "2,132,199"];
    let width = 0;
    let height = 0;
    let raf = 0;
    let stars: Star[] = [];

    const seed = () => {
      const count = Math.min(130, Math.max(40, Math.floor((width * height) / 15000)));
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        r: 0.5 + Math.random() * 1.3,
        tw: Math.random() * Math.PI * 2,
        ts: 0.006 + Math.random() * 0.02,
        c: PALETTE[Math.floor(Math.random() * PALETTE.length)],
      }));
    };

    const resize = () => {
      width = canvas.offsetWidth;
      height = canvas.offsetHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    };

    const drawFrame = () => {
      ctx.clearRect(0, 0, width, height);

      // Ease the virtual cursor toward the real one (organic lag).
      mouse.x += (mouse.tx - mouse.x) * 0.07;
      mouse.y += (mouse.ty - mouse.y) * 0.07;

      for (const s of stars) {
        // Gentle gravitational pull toward the cursor.
        const dx = mouse.x - s.x;
        const dy = mouse.y - s.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < PULL_RADIUS * PULL_RADIUS) {
          const d = Math.sqrt(d2) || 1;
          const f = (1 - d / PULL_RADIUS) * 0.012;
          s.vx += (dx / d) * f;
          s.vy += (dy / d) * f;
        }
        // Damping keeps drift calm; never let stars fully stop.
        s.vx = Math.max(-0.5, Math.min(0.5, s.vx * 0.992));
        s.vy = Math.max(-0.5, Math.min(0.5, s.vy * 0.992));
        s.x += s.vx;
        s.y += s.vy;
        if (s.x < -8) s.x = width + 8;
        if (s.x > width + 8) s.x = -8;
        if (s.y < -8) s.y = height + 8;
        if (s.y > height + 8) s.y = -8;
        s.tw += s.ts;
      }

      // Filaments between close stars.
      const LINK = 115;
      for (let i = 0; i < stars.length; i++) {
        const a = stars[i];
        for (let j = i + 1; j < stars.length; j++) {
          const b = stars[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < LINK * LINK) {
            const t = 1 - Math.sqrt(d2) / LINK;
            ctx.strokeStyle = `rgba(79, 70, 229, ${(t * 0.12).toFixed(3)})`;
            ctx.lineWidth = 0.6;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      // Multi-colour stars with a soft halo twinkle.
      for (const s of stars) {
        const tw = 0.5 + 0.5 * Math.sin(s.tw);
        ctx.fillStyle = `rgba(${s.c}, ${(0.35 + tw * 0.45).toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
        if (s.r > 1.2) {
          ctx.fillStyle = `rgba(${s.c}, ${(tw * 0.22).toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(s.x, s.y, s.r * 2.4, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    };

    const loop = () => {
      drawFrame();
      raf = requestAnimationFrame(loop);
    };

    const onMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouse.tx = e.clientX - rect.left;
      mouse.ty = e.clientY - rect.top;
    };
    const onLeave = () => {
      mouse.tx = -9999;
      mouse.ty = -9999;
    };
    const onVisibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(raf);
      } else if (!reduced) {
        raf = requestAnimationFrame(loop);
      }
    };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);

    if (reduced) {
      drawFrame(); // single static frame
    } else {
      raf = requestAnimationFrame(loop);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="absolute inset-0 h-full w-full"
    />
  );
}
