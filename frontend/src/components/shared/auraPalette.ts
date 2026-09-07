/**
 * AmbientAura - pure palette-rotation logic (no React).
 *
 * Split out of AmbientAura.tsx so the rotation logic can be unit-tested
 * with fake timers WITHOUT a DOM renderer.
 *
 * EIGHT light-theme palettes (multi-colour: soft teal, sky, aqua,
 * lavender, periwinkle, mint, pale rose, soft lilac). The palette index
 * advances every 7 seconds and wraps seamlessly - each blob keeps its
 * position/size and only its COLOR crossfades, so the effect is a
 * perpetually colour-shifting light shade that never moves the layout.
 */

/** Light cool/warm-pastel colors ONLY - faded tints, never saturated blocks. */
export const AURA_PALETTES: ReadonlyArray<readonly [string, string, string]> = [
  ["#14b8a6", "#7dd3fc", "#c4b5fd"], // teal, sky, lavender
  ["#a7f3d0", "#a5f3fc", "#818cf8"], // mint, aqua, soft indigo
  ["#c4b5fd", "#fbcfe8", "#67e8f9"], // lavender, pale rose, cyan
  ["#7dd3fc", "#a7f3d0", "#fbcfe8"], // sky, mint, rose
  ["#818cf8", "#67e8f9", "#a7f3d0"], // soft indigo, cyan, mint
  ["#14b8a6", "#c4b5fd", "#7dd3fc"], // teal, lavender, sky
  ["#fbcfe8", "#a5f3fc", "#a7f3d0"], // pale rose, aqua, mint
  ["#67e8f9", "#c4b5fd", "#fbcfe8"], // cyan, lavender, pale rose
];

/** Palette crossfades to the next combination every 7 seconds. */
export const AURA_CYCLE_MS = 7000;

/** 3 large blurred blobs - desynchronized, perpetually drifting. */
export const AURA_BLOB_COUNT = 3;

/** Desynchronized slow drift loops per blob (GPU-friendly transform only). */
export const AURA_BLOB_DURATIONS = ["22s", "30s", "38s"];

/** Base opacity per blob - faded but perceivable on the light shell
 * (0.12-0.20): felt as a moving tint, never competing with content. */
export const AURA_BLOB_OPACITIES = [0.16, 0.12, 0.2];

/** CSS transition duration for the palette crossfade (never an abrupt jump). */
export const AURA_CROSSFADE_CSS = "background 1.8s ease, opacity 1.8s ease";

/** Pure rotation: (index + 1) mod count - perpetual and seamless. */
export function nextPaletteIndex(current: number, count: number): number {
  return (current + 1) % count;
}
