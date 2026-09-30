"""Measure the real contrast of the hero headline ramp.

The headline sits in the LEFT copy column of the landing hero, over
`hero-office.png` covered by the veil gradient
`bg-gradient-to-r from-white/95 via-white/70 to-white/5`.

This script composites that veil over the actual image pixels, then reports
the WCAG contrast ratio of every ramp stop against the worst (darkest)
composited background the headline can sit on — so the "premium, highly
contrasting" choice is verified against the real backdrop instead of an
assumed one.

Operator tooling, not a test: it needs Pillow (``pip install Pillow``), which
is deliberately NOT in ``requirements.txt``.  Run it directly:

    python scripts/hero_headline_contrast.py
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - operator tooling
    raise SystemExit(
        "This diagnostic needs Pillow for image pixel access: pip install Pillow"
    )

ERP_ROOT = Path(__file__).resolve().parents[1]
HERO = ERP_ROOT / "frontend" / "public" / "hero-office.png"

# The ramp stops (see --hero-headline-gradient in globals.css) and the
# background each one is actually painted on:
#   * the rotating landing headline sits over the hero photograph + veil;
#   * the .text-aurora accent is used INSIDE headings on light page
#     backgrounds (PageShell), so pure white is its worst case.
RAMPS = {
    "headline": {
        "stops": [(0x1B, 0x2A, 0x4A), (0x11, 0x5E, 0x59), (0x15, 0x5E, 0x75), (0x13, 0x4E, 0x4A)],
        "on_hero": True,
    },
    "accent": {
        "stops": [(0x0F, 0x76, 0x6E), (0x0E, 0x74, 0x90), (0x15, 0x5E, 0x75)],
        "on_hero": False,
    },
    "old_cyan_headline": {
        "stops": [(0x0F, 0x76, 0x6E), (0x08, 0x91, 0xB2), (0x06, 0xB6, 0xD4)],
        "on_hero": True,
    },
    "old_cyan_accent": {
        "stops": [(0x0F, 0x76, 0x6E), (0x08, 0x91, 0xB2), (0x22, 0xD3, 0xEE)],
        "on_hero": False,
    },
}


def _linear(channel: int) -> float:
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(rgb) -> float:
    r, g, b = (_linear(int(c)) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg) -> float:
    a, b = luminance(fg), luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def veil_alpha(x_ratio: float) -> float:
    """from-white/95 via-white/70 to-white/5, interpolated linearly."""
    if x_ratio <= 0.5:
        return (0.95 + (0.70 - 0.95) * (x_ratio / 0.5))
    return 0.70 + (0.05 - 0.70) * ((x_ratio - 0.5) / 0.5)


def main() -> int:
    image = Image.open(HERO).convert("RGB")
    width, height = image.size

    # The headline occupies the left copy column of a max-w-6xl (1152px)
    # container, with the h1 sized within `max-w-xl` (576px).  Sample the
    # band where the headline actually sits, generously: x 4%..46% of the
    # viewport, y 28%..62%.
    x0, x1 = int(width * 0.04), int(width * 0.46)
    y0, y1 = int(height * 0.28), int(height * 0.62)

    darkest = None
    darkest_at = (0, 0)
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            alpha = veil_alpha(x / width)
            r, g, b = image.getpixel((x, y))
            composite = tuple(alpha * 255 + (1 - alpha) * channel for channel in (r, g, b))
            if darkest is None or luminance(composite) < luminance(darkest):
                darkest = composite
                darkest_at = (x, y)

    print(f"hero image: {width}x{height}")
    print(f"headline band sampled: x {x0}-{x1}, y {y0}-{y1}")
    print(f"darkest composited background under the headline: "
          f"rgb({int(darkest[0])},{int(darkest[1])},{int(darkest[2])}) at {darkest_at}")
    print(f"  (that is the WORST case for contrast across the whole headline area)")
    print()

    failed = False
    for name, spec in RAMPS.items():
        stops = spec["stops"]
        backgrounds = [(255, 255, 255)] + ([tuple(darkest)] if spec["on_hero"] else [])
        worst = min(contrast(stop, bg) for stop in stops for bg in backgrounds)
        against_white = min(contrast(stop, (255, 255, 255)) for stop in stops)
        where = "hero backdrop" if spec["on_hero"] else "light page background"
        print(f"{name:19s} worst vs {where:21s}: {worst:5.2f}:1   vs pure white: {against_white:5.2f}:1")
        if not name.startswith("old_") and worst < 4.5:
            failed = True
            print("                    ^ below WCAG AA (4.5:1) — the ramp needs to be darker")

    print()
    if failed:
        print("FAIL: the chosen ramp does not hold 4.5:1 everywhere the heading sits")
        return 1
    print("PASS: every stop of the chosen ramps holds >= 4.5:1 on the backgrounds they")
    print("      are actually painted on — including the darkest part of the real hero")
    print("      image under its veil.  (The old light-cyan ends did not: see old_* above.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())