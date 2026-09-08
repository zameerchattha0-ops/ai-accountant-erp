"use client";

/* ================================================================== */
/* "Ledger" — the 3D robot mascot                                      */
/*                                                                      */
/* Built 100% procedurally with react-three-fiber — no external model.  */
/* Every surface is a high-segment smooth primitive with a glossy       */
/* studio material: white shell, orange accents, dark glass visor and   */
/* glowing cyan eyes — a premium chibi toy-robot look (no low-poly      */
/* facets, no pixelation).                                              */
/*                                                                      */
/* Behaviour state machine:                                             */
/*   entrance Wave → Idle (breathes, blinks, follows your cursor with   */
/*   head and body) → patrols left/right (hero only) → hover triggers   */
/*   a Wave · click triggers a hop-and-spin. Falls back to a calm Idle  */
/*   under prefers-reduced-motion.                                      */
/* ================================================================== */

import { Component, Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows } from "@react-three/drei";

type RobotVariant = "hero" | "compact";
type Phase = "wave" | "idle" | "walk" | "hop";

/* Shared smooth materials — glossy white shell, orange accents,
   dark glass visor, glowing cyan eyes. Created once per instance. */
function useRobotMaterials() {
  return useMemo(
    () => ({
      shell: new THREE.MeshStandardMaterial({ color: "#f5f7fa", roughness: 0.32, metalness: 0.08 }),
      accent: new THREE.MeshStandardMaterial({ color: "#ef8b2c", roughness: 0.38, metalness: 0.12 }),
      visor: new THREE.MeshStandardMaterial({ color: "#0c1420", roughness: 0.12, metalness: 0.45 }),
      eye: new THREE.MeshStandardMaterial({
        color: "#061018",
        emissive: new THREE.Color("#3ee5ff"),
        emissiveIntensity: 2.6,
        roughness: 0.2,
      }),
      glow: new THREE.MeshStandardMaterial({
        color: "#04211f",
        emissive: new THREE.Color("#2dd4bf"),
        emissiveIntensity: 2.2,
        roughness: 0.3,
      }),
      dark: new THREE.MeshStandardMaterial({ color: "#2b3340", roughness: 0.5, metalness: 0.35 }),
    }),
    [],
  );
}

function RobotCharacter({ variant, reduced }: { variant: RobotVariant; reduced: boolean }) {
  const mats = useRobotMaterials();

  const root = useRef<THREE.Group>(null);
  const squash = useRef<THREE.Group>(null);
  const patrolG = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const legL = useRef<THREE.Group>(null);
  const legR = useRef<THREE.Group>(null);
  const eyeL = useRef<THREE.Mesh>(null);
  const eyeR = useRef<THREE.Mesh>(null);

  /* --- behaviour state (kept out of React state on purpose: 60fps) --- */
  const phase = useRef<Phase>("wave");
  const timer = useRef(reduced ? 0 : 2.4);
  const walkDir = useRef<1 | -1>(1);
  const canPatrol = variant === "hero" && !reduced;

  const setPhase = (p: Phase, seconds: number) => {
    phase.current = p;
    timer.current = seconds;
  };

  useFrame((state, rawDelta) => {
    const g = root.current;
    if (!g) return;
    const d = Math.min(rawDelta, 0.05); // clamp tab-switch jumps
    const t = state.clock.elapsedTime;

    /* -------- phase machine -------- */
    if (!reduced) {
      timer.current -= d;
      if (timer.current <= 0) {
        if (phase.current === "wave") setPhase("idle", 2.6 + Math.random() * 1.6);
        else if (phase.current === "idle") {
          if (canPatrol) {
            walkDir.current = Math.random() > 0.5 ? 1 : -1;
            setPhase("walk", 1.9 + Math.random() * 1.2);
          } else setPhase("idle", 3 + Math.random() * 2);
        } else if (phase.current === "walk") setPhase("idle", 2.5 + Math.random() * 2);
        else if (phase.current === "hop") setPhase("idle", 2.5);
      }
    }
    const p = phase.current;

    /* -------- locomotion: patrol on foot, otherwise breathe -------- */
    let bob = 0;
    let legSwing = 0;
    if (p === "walk" && patrolG.current) {
      patrolG.current.position.x = THREE.MathUtils.damp(
        patrolG.current.position.x,
        walkDir.current * 0.5,
        1.4,
        d,
      );
      legSwing = Math.sin(t * 8);
      bob = Math.abs(Math.sin(t * 8)) * 0.045;
    } else if (patrolG.current) {
      patrolG.current.position.x = THREE.MathUtils.damp(patrolG.current.position.x, 0, 1.8, d);
      bob = reduced ? 0 : Math.sin(t * 2.1) * 0.028;
    }

    /* -------- hop-and-spin (click) -------- */
    let hopY = 0;
    let stretch = 1;
    let spinDelta = 0;
    if (p === "hop") {
      const u = Math.min(1, Math.max(0, 1 - timer.current / 0.75));
      hopY = 1.36 * u * (1 - u);
      stretch = 1 + 0.14 * Math.sin(u * Math.PI);
      spinDelta = (d * u * Math.PI * 2) / 0.75;
    }
    g.position.y = THREE.MathUtils.lerp(g.position.y, hopY + bob, 0.5);
    if (squash.current) {
      squash.current.scale.y = THREE.MathUtils.damp(squash.current.scale.y, stretch, 10, d);
      squash.current.scale.x = THREE.MathUtils.damp(squash.current.scale.x, 2 - stretch, 10, d);
      if (p === "hop") squash.current.rotation.y += spinDelta;
      else squash.current.rotation.y = THREE.MathUtils.damp(squash.current.rotation.y, 0, 4, d);
    }

    /* -------- arms: swing while walking, raise when waving -------- */
    const swing = p === "walk" ? Math.sin(t * 8) * 0.35 : 0;
    let armRTarget = 0.16 + swing;
    const armLTarget = -0.16 - swing;
    if (p === "wave") armRTarget = 2.35 + Math.sin(t * 7.5) * 0.3;
    if (armR.current)
      armR.current.rotation.z = THREE.MathUtils.damp(armR.current.rotation.z, armRTarget, 7, d);
    if (armL.current)
      armL.current.rotation.z = THREE.MathUtils.damp(armL.current.rotation.z, armLTarget, 7, d);

    /* -------- legs -------- */
    if (legL.current)
      legL.current.rotation.x = THREE.MathUtils.damp(
        legL.current.rotation.x,
        legSwing * 0.5,
        10,
        d,
      );
    if (legR.current)
      legR.current.rotation.x = THREE.MathUtils.damp(
        legR.current.rotation.x,
        -legSwing * 0.5,
        10,
        d,
      );

    /* -------- head follows the visitor's cursor + idle tilt -------- */
    if (head.current) {
      const fx = reduced ? 0 : state.pointer.x * 0.4;
      const fy = reduced ? 0 : -state.pointer.y * 0.18;
      head.current.rotation.y = THREE.MathUtils.damp(head.current.rotation.y, fx, 5, d);
      head.current.rotation.x = THREE.MathUtils.damp(
        head.current.rotation.x,
        fy + (reduced ? 0 : Math.sin(t * 1.7) * 0.04),
        5,
        d,
      );
    }

    /* -------- body leans toward the cursor -------- */
    if (!reduced) g.rotation.y = THREE.MathUtils.damp(g.rotation.y, state.pointer.x * 0.12, 4, d);

    /* -------- blink -------- */
    const blinkT = (t + 1.2) % 3.7;
    const eyeScale = blinkT < 0.14 ? 0.12 : 1;
    if (eyeL.current)
      eyeL.current.scale.y = THREE.MathUtils.lerp(eyeL.current.scale.y, eyeScale, 0.5);
    if (eyeR.current)
      eyeR.current.scale.y = THREE.MathUtils.lerp(eyeR.current.scale.y, eyeScale, 0.5);
  });

  const triggerWave = () => {
    if (!reduced) setPhase("wave", 2.1);
  };
  const triggerHop = () => {
    if (!reduced) setPhase("hop", 0.75);
  };

  /* Proportions (world units, ground at y=0):
     feet → hip 0.42 · body capsule 0.33→1.23 · shoulders 0.95 ·
     head centre 1.58 (r 0.58) · antenna tip ≈ 2.42.
     Chibi ratio: head ≈ 2× body — big-head cute, like a premium toy.
     Scaled down per-variant so he stays small and never crops. */
  const hipY = 0.42;

  return (
    <group
      ref={root}
      scale={variant === "hero" ? 0.72 : 0.56}
      onPointerOver={(e) => {
        e.stopPropagation();
        triggerWave();
      }}
      onPointerDown={(e) => {
        e.stopPropagation();
        triggerHop();
      }}
    >
      {/* generous invisible hit-area so hover/click feels effortless */}
      <mesh visible={false} position={[0, 1.15, 0]}>
        <sphereGeometry args={[1.4, 8, 8]} />
        <meshBasicMaterial />
      </mesh>

      <group ref={squash}>
        <group ref={patrolG}>
          {/* ===== LEGS ===== */}
          {([["L", -0.17, legL], ["R", 0.17, legR]] as const).map(([side, x, ref]) => (
            <group key={side} ref={ref} position={[x, hipY, 0]}>
              <mesh material={mats.shell}>
                <capsuleGeometry args={[0.085, 0.16, 8, 24]} />
              </mesh>
              {/* boot */}
              <mesh material={mats.accent} position={[0, -0.34, 0.05]} scale={[1, 0.55, 1.35]}>
                <sphereGeometry args={[0.135, 32, 24]} />
              </mesh>
            </group>
          ))}

          {/* ===== BODY ===== */}
          <mesh material={mats.shell} position={[0, 0.78, 0]}>
            <capsuleGeometry args={[0.3, 0.3, 12, 48]} />
          </mesh>
          {/* orange belly panel */}
          <mesh material={mats.accent} position={[0, 0.76, 0.17]} scale={[1, 0.85, 0.5]}>
            <sphereGeometry args={[0.21, 32, 24]} />
          </mesh>
          {/* belly light */}
          <mesh material={mats.glow} position={[0, 0.76, 0.3]}>
            <sphereGeometry args={[0.045, 16, 16]} />
          </mesh>
          {/* waist ring */}
          <mesh material={mats.dark} position={[0, 0.47, 0]} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.265, 0.035, 12, 48]} />
          </mesh>

          {/* ===== ARMS ===== */}
          {([["L", -0.34, armL], ["R", 0.34, armR]] as const).map(([side, x, ref]) => (
            <group key={side} ref={ref} position={[x, 0.95, 0]}>
              {/* shoulder ball */}
              <mesh material={mats.dark}>
                <sphereGeometry args={[0.105, 24, 20]} />
              </mesh>
              <mesh material={mats.shell} position={[0, -0.18, 0]}>
                <capsuleGeometry args={[0.068, 0.2, 8, 24]} />
              </mesh>
              {/* mitten hand */}
              <mesh material={mats.accent} position={[0, -0.37, 0]}>
                <sphereGeometry args={[0.105, 24, 20]} />
              </mesh>
            </group>
          ))}

          {/* ===== HEAD (oversized = cute) ===== */}
          <group ref={head} position={[0, 1.2, 0]}>
            <mesh material={mats.shell} position={[0, 0.38, 0]} scale={[1, 0.92, 0.95]}>
              <sphereGeometry args={[0.58, 48, 40]} />
            </mesh>
            {/* glossy dark visor */}
            <mesh material={mats.visor} position={[0, 0.4, 0.26]} scale={[1.02, 0.74, 0.62]}>
              <sphereGeometry args={[0.44, 48, 36]} />
            </mesh>
            {/* glowing cyan eyes (blink by scaling Y) */}
            {([["L", -0.16, eyeL], ["R", 0.16, eyeR]] as const).map(([side, x, ref]) => (
              <mesh
                key={side}
                ref={ref}
                material={mats.eye}
                position={[x, 0.41, 0.5]}
                scale={[1, 1.5, 0.5]}
              >
                <sphereGeometry args={[0.062, 24, 20]} />
              </mesh>
            ))}
            {/* ear pods */}
            {([["L", -0.56], ["R", 0.56]] as const).map(([side, x]) => (
              <group key={side} position={[x, 0.4, 0]} rotation={[0, 0, Math.PI / 2]}>
                <mesh material={mats.accent}>
                  <cylinderGeometry args={[0.1, 0.1, 0.07, 24]} />
                </mesh>
                <mesh material={mats.shell} position={[side === "L" ? -0.045 : 0.045, 0, 0]}>
                  <cylinderGeometry args={[0.06, 0.06, 0.02, 24]} />
                </mesh>
              </group>
            ))}
            {/* antenna + glowing tip */}
            <mesh material={mats.dark} position={[0, 1.02, 0]}>
              <cylinderGeometry args={[0.02, 0.028, 0.2, 12]} />
            </mesh>
            <mesh material={mats.glow} position={[0, 1.16, 0]}>
              <sphereGeometry args={[0.055, 20, 16]} />
            </mesh>
            {/* forehead seam */}
            <mesh material={mats.accent} position={[0, 0.74, 0]} rotation={[Math.PI / 2, 0, 0]}>
              <torusGeometry args={[0.5, 0.018, 10, 48]} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}

/* If anything in the 3D scene throws (WebGL context loss, driver glitch),
   degrade to an empty stage instead of crashing the page. */
class RobotErrorBoundary extends Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.warn("[Ledger] 3D mascot unavailable:", error);
  }
  render() {
    if (this.state.failed) return null;
    return this.props.children;
  }
}

/* ================================================================== */
/* Stage — transparent canvas + lighting rig                           */
/* ================================================================== */

/* Frames the robot (≈1.74 / 1.36 world-units tall after scaling) with
   generous headroom — small, cute, never cropped or over-zoomed. */
function CameraRig({ variant }: { variant: RobotVariant }) {
  const { camera } = useThree();
  useEffect(() => {
    const hero = variant === "hero";
    camera.position.set(0, hero ? 1.05 : 0.85, hero ? 4.5 : 3.7);
    camera.lookAt(0, hero ? 0.88 : 0.72, 0);
  }, [camera, variant]);
  return null;
}

export default function HeroRobotStage({ variant = "hero" }: { variant?: RobotVariant }) {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const stageHeight =
    variant === "hero"
      ? "h-[250px] sm:h-[300px] lg:h-[430px]"
      : "h-[185px]";

  return (
    <div className={`relative w-full ${stageHeight}`} aria-hidden="true">
      {/* No dedicated background — the robot floats directly over the page UI.
          A faint glow keeps him readable on busy sections without a "box". */}
      <div className="absolute inset-x-8 bottom-2 h-24 rounded-full bg-teal-200/30 blur-3xl pointer-events-none" />

      {/* Speech bubble — the mascot introduces itself */}
      <div className="absolute left-4 top-4 z-10">
        <div className="clay-chip bg-white/80 px-3.5 py-2 text-xs font-semibold text-brand-navy shadow-lg backdrop-blur">
          Hi, I&apos;m <span className="text-ai-700">Ledger</span> — your AI accountant
          {variant === "hero" && !reduced && (
            <span className="ml-2 text-[10px] font-medium text-text-muted hidden sm:inline">
              (click me!)
            </span>
          )}
        </div>
      </div>

      <div className="absolute inset-0 cursor-pointer [&>canvas]:outline-none">
        <Canvas
          dpr={[1, 2]}
          performance={{ min: 0.5 }}
          gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
          camera={{ position: [0, 1.05, 4.5], fov: 33 }}
        >
          {/* Frame the robot (1.74 / 1.36 units tall after scaling): camera
              looks at chest height with generous headroom — never cropped. */}
          <CameraRig variant={variant} />

          {/* Lighting rig: soft ambient + warm key + teal rim = premium studio look */}
          <ambientLight intensity={0.55} />
          <hemisphereLight args={["#e0f2fe", "#fdf2f8", 0.55]} />
          <directionalLight
            position={[2.5, 4, 3]}
            intensity={1.5}
            castShadow
            shadow-mapSize={[512, 512]}
          />
          <directionalLight position={[-3, 2, -2.5]} intensity={0.9} color="#67e8f9" />
          <pointLight position={[0, 0.4, 2.2]} intensity={0.35} color="#fef3c7" />

          <Suspense fallback={null}>
            <RobotErrorBoundary>
              <RobotCharacter variant={variant} reduced={reduced} />
            </RobotErrorBoundary>

            {/* Soft floating shadow ellipse — grounds the robot without a
                dedicated platform, so he sits "on" the page itself */}
            <ContactShadows
              position={[0, 0, 0]}
              opacity={0.22}
              scale={2.6}
              blur={2.8}
              far={1.4}
              color="#1e3a5f"
            />
          </Suspense>
        </Canvas>
      </div>
    </div>
  );
}
