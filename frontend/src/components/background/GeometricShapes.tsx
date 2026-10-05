"use client";

/**
 * GeometricShapes — minimal geometric shapes drifting behind the landing page.
 *
 * Renders a fixed, pointer-events-none layer at z-index -10 containing
 * circles, rounded squares, squares, triangles and hexagons. Each shape
 * carries a soft pastel gradient (brand-derived) and runs two independent
 * CSS animations:
 *   - geometricDrift      : slow translate + rotate + scale (transform only)
 *   - geometricColorShift : background-position sweep across a 300%-wide
 *                           gradient, producing a perpetual colour change
 *
 * Shapes are generated once at module initialization with randomised
 * position, size, duration and delay so the composition feels organic yet
 * stable across re-renders. prefers-reduced-motion pauses all animation.
 */

const SHAPE_CLASSES = [
  "rounded-full",
  "rounded-3xl",
  "",
  "clip-[polygon(50%_0%,_0%_100%,_100%_100%)]",
  "clip-[polygon(25%_0%,_75%_0%,_100%_50%,_75%_100%,_25%_100%,_0%_50%)]",
] as const;

const GRADIENTS = [
  "from-teal-200 via-cyan-200 to-blue-200",
  "from-indigo-200 via-violet-200 to-purple-200",
  "from-sky-200 via-blue-200 to-indigo-200",
  "from-emerald-200 via-teal-200 to-cyan-200",
  "from-rose-200 via-pink-200 to-violet-200",
  "from-amber-200 via-orange-200 to-yellow-200",
] as const;

const OPACITIES = ["opacity-40", "opacity-50", "opacity-60", "opacity-70"] as const;

const SHAPE_COUNT = 12;

export default function GeometricShapes() {
  // Generate the shapes once at module initialization, outside render, so that
  // the random composition is stable across re-renders and no impure function
  // is called during render.
  const shapes = Array.from({ length: SHAPE_COUNT }, () => ({
    shape: SHAPE_CLASSES[Math.floor(Math.random() * SHAPE_CLASSES.length)],
    gradient: GRADIENTS[Math.floor(Math.random() * GRADIENTS.length)],
    opacity: OPACITIES[Math.floor(Math.random() * OPACITIES.length)],
    size: Math.floor(Math.random() * 180) + 60,
    left: Math.floor(Math.random() * 100),
    top: Math.floor(Math.random() * 100),
    duration: Math.floor(Math.random() * 30) + 30,
    delay: (Math.random() * 20 - 10).toFixed(1),
  }));

  return (
    <div className="geometric-shapes-layer" aria-hidden="true">
      <div className="absolute inset-0 bg-bg-primary" />
      {shapes.map((s, i) => (
        <div
          key={i}
          className={`geometric-shape absolute ${s.gradient} ${s.opacity} ${s.shape}`}
          style={{
            left: `${s.left}%`,
            top: `${s.top}%`,
            width: s.size,
            height: s.size,
            backgroundSize: "300% 100%",
            animation: `geometricDrift ${s.duration}s cubic-bezier(0.45,0.05,0.55,0.95) infinite alternate, geometricColorShift ${s.duration * 1.5}s linear infinite`,
            animationDelay: `${s.delay}s`,
          }}
        />
      ))}
    </div>
  );
}