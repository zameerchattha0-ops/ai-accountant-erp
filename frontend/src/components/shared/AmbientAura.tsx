"use client";

import { useEffect, useState } from "react";
import {
  AURA_BLOB_COUNT,
  AURA_BLOB_DURATIONS,
  AURA_BLOB_OPACITIES,
  AURA_CROSSFADE_CSS,
  AURA_CYCLE_MS,
  AURA_PALETTES,
  nextPaletteIndex,
} from "./auraPalette";
import { useDeviceTier } from "@/lib/utils/devicePerf";

/**
 * Palette-rotation hook: advances the palette index every AURA_CYCLE_MS.
 * Pauses automatically when tab is hidden or device has low resources.
 */
export function useAuraPalette(enabled = true): number {
  const [paletteIndex, setPaletteIndex] = useState(0);

  useEffect(() => {
    if (!enabled) return;

    let id: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (id || typeof document === "undefined" || document.hidden) return;
      id = setInterval(() => {
        setPaletteIndex((current) =>
          nextPaletteIndex(current, AURA_PALETTES.length)
        );
      }, AURA_CYCLE_MS);
    };

    const stop = () => {
      if (id) {
        clearInterval(id);
        id = null;
      }
    };

    const handleVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        start();
      }
    };

    start();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [enabled]);

  return paletteIndex;
}

/**
 * AmbientAura - adaptive background ambiance.
 *
 * Performance Contract:
 * - On standard desktop/high-end devices: 3 drifting blurred radial blobs
 * - On low-end devices / slow networks / battery-saver mode:
 *   Immediately drops to a zero-CPU, zero-GPU static CSS tint layer.
 *   Eliminates all continuous 84px Gaussian blurs, GPU texture composite
 *   loops, and 7-second timer wakeups.
 */
export default function AmbientAura() {
  const { shouldReduceEffects } = useDeviceTier();
  const paletteIndex = useAuraPalette(!shouldReduceEffects);
  const palette = AURA_PALETTES[paletteIndex];

  // Low-spec / Data-saver eco mode: single static lightweight tint, 0% CPU
  if (shouldReduceEffects) {
    return (
      <div
        className="ambient-aura ambient-aura-eco pointer-events-none fixed inset-0 -z-10 overflow-hidden"
        aria-hidden="true"
        data-testid="ambient-aura"
      >
        <div
          className="absolute inset-0 opacity-15"
          style={{
            background: `radial-gradient(circle at 10% 10%, #14b8a6 0%, transparent 40%),
                         radial-gradient(circle at 90% 20%, #7dd3fc 0%, transparent 40%),
                         radial-gradient(circle at 50% 90%, #c4b5fd 0%, transparent 40%)`,
          }}
        />
      </div>
    );
  }

  return (
    <div className="ambient-aura" aria-hidden="true" data-testid="ambient-aura">
      {Array.from({ length: AURA_BLOB_COUNT }).map((_, i) => (
        <span
          key={i}
          className={`ambient-aura-blob ambient-aura-blob-${i + 1}`}
          data-testid={`ambient-aura-blob-${i + 1}`}
          style={{
            backgroundColor: palette[i],
            opacity: AURA_BLOB_OPACITIES[i],
            animationDuration: AURA_BLOB_DURATIONS[i],
            transition: AURA_CROSSFADE_CSS,
          }}
        />
      ))}
    </div>
  );
}
