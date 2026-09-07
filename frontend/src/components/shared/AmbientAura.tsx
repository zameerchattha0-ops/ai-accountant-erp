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

/**
 * Palette-rotation hook: advances the palette index every AURA_CYCLE_MS.
 * (The pure rotation logic lives in auraPalette.ts and is unit-tested.)
 */
export function useAuraPalette(): number {
  const [paletteIndex, setPaletteIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setPaletteIndex((current) =>
        nextPaletteIndex(current, AURA_PALETTES.length)
      );
    }, AURA_CYCLE_MS);
    return () => clearInterval(id);
  }, []);

  return paletteIndex;
}

/**
 * AmbientAura - a perpetually moving, color-shifting light shade BEHIND the
 * dashboard content.
 *
 * Contract:
 * - absolutely positioned layer, pointer-events-none, behind all content
 *   (-z-10), overflow-hidden, aria-hidden - it can never obstruct or
 *   compete with the layout or create scrollbars.
 * - 3 large blurred radial-gradient blobs (blur 100px, border-radius 50%),
 *   light cool colors only, base opacity 0.10-0.16.
 * - each blob drifts on its own desynchronized slow loop (22s/30s/38s),
 *   CSS keyframes animating transform ONLY.
 * - the palette crossfades to a new combination every 7s with a 1.8s CSS
 *   transition - never an abrupt jump, perpetual and seamless.
 * - prefers-reduced-motion pauses the drift (static faint tint remains);
 *   the print block in globals.css hides the layer entirely.
 */
export default function AmbientAura() {
  const paletteIndex = useAuraPalette();
  const palette = AURA_PALETTES[paletteIndex];

  return (
    <div className="ambient-aura" aria-hidden="true" data-testid="ambient-aura">
      {Array.from({ length: AURA_BLOB_COUNT }).map((_, i) => (
        <span
          key={i}
          className={`ambient-aura-blob ambient-aura-blob-${i + 1}`}
          data-testid={`ambient-aura-blob-${i + 1}`}
          style={{
            // Solid colour + blur(100px) == soft radial glow, and
            // background-color transitions reliably in EVERY browser
            // (background-image gradients do not crossfade in Firefox).
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
