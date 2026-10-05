/**
 * HERO_TAGLINES — the rotating headline sentences for the welcome hero.
 *
 * Each line carries a dwell duration (in ms) matched to its reading length
 * so longer taglines get more breath before the next swap. The array is the
 * single source of truth for both the live glass carousel and the sr-only
 * fallback used by crawlers and assistive technology.
 */
export const HERO_TAGLINES = [
  { text: "No Accountant? No Problem. Run Your Books Yourself.", dur: 5400 },
  { text: "Built for Founders Who Don't Speak Accounting.", dur: 4600 },
  { text: "Fire Your Bookkeeper. Hire Your AI Agent.", dur: 4500 },
  { text: "The AI-Native ERP That Replaces the Need for an Accountant.", dur: 5800 },
  { text: "Just Type What Happened. Our AI Does the Accounting.", dur: 5100 },
] as const;