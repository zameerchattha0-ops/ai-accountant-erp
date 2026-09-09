"use client";

/* ================================================================== */
/* "Ledger" — the 3D robot mascot. Lives INSIDE its stage (the hero's  */
/* right column / a corner of the auth pages) — never fixed to the     */
/* viewport, never covering copy.                                      */
/*                                                                      */
/* Geometry now matches the approved brand reference (ERP/Robot.png):  */
/* white glossy shell, deep-teal accents, dark glass visor, glowing    */
/* cyan face, "Ai" chest badge, tablet in hand (see robot/RobotModel). */
/*                                                                      */
/* Behaviour: a random activity loop — wave · idle · walk · hop ·      */
/* dance · clap · read · sit — roaming the stage's empty areas. The    */
/* facial expression follows the activity (excited / sleepy / focus).  */
/* Falls back to a calm idle under prefers-reduced-motion.             */
/* ================================================================== */

import { Component, Suspense, useEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows } from "@react-three/drei";
import { RobotModel, type FaceMode } from "@/components/robot/RobotModel";

type Variant = "hero" | "compact";
type Phase = "wave" | "idle" | "walk" | "hop" | "dance" | "clap" | "read" | "sit" | "interact";
type PokeTarget = "invoice" | "journal" | "trial" | "overview" | "ask";

/* Hero hotspots Ledger can walk up to and physically interact with.
   xf = x position as a fraction of the roam bound; reach = [armX, armZ]
   tailored to where the element sits (high card vs low pill). */
const HOTSPOTS: Record<PokeTarget, { xf: number; line: string; reach: [number, number] }> = {
  invoice: {
    xf: -0.92,
    line: "Invoice INV-2025-001 — created and posted!",
    reach: [-0.6, 1.9],
  },
  journal: {
    xf: -0.88,
    line: "Journal entry recorded. Debits equal credits — always.",
    reach: [-0.55, 1.8],
  },
  trial: {
    xf: -0.84,
    line: "Trial balance updated. Everything adds up.",
    reach: [-0.5, 1.7],
  },
  overview: {
    xf: 0.95,
    line: "Fresh numbers, hot off the ledger!",
    reach: [-0.35, 2.15],
  },
  ask: {
    xf: 0.7,
    line: "Ask me anything — I speak fluent accounting.",
    reach: [-0.95, 1.15],
  },
};
const POKEABLE: PokeTarget[] = ["invoice", "journal", "trial", "overview", "ask"];

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}
function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/* Facial expression follows the current activity */
function faceForPhase(p: Phase): FaceMode {
  if (p === "dance" || p === "clap" || p === "hop" || p === "wave") return "excited";
  if (p === "sit") return "sleepy";
  if (p === "read") return "focus";
  return "happy";
}

function RobotActor({ variant, reduced }: { variant: Variant; reduced: boolean }) {
  const root = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const legL = useRef<THREE.Group>(null);
  const legR = useRef<THREE.Group>(null);
  const face = useRef<FaceMode>("happy");

  /* --- behaviour state (refs on purpose: 60fps, no re-renders) --- */
  const phase = useRef<Phase>("wave");
  const t = useRef(0);
  const dur = useRef(reduced ? Infinity : 2.4);
  const dir = useRef<1 | -1>(1);
  useEffect(() => {
    dir.current = Math.random() > 0.5 ? 1 : -1;
  }, []);

  const { viewport } = useThree();
  /* Hero: roam the open centre corridor, plus the card edges when he is
     off to interact with them. The floating cards only render ≥ md. */
  const bound =
    variant === "hero"
      ? Math.min(Math.max(0.55, viewport.width / 2 - 1.0), 1.0)
      : Math.max(0.3, viewport.width / 2 - 0.95);

  /* Cards exist only from md up — track so mobile never "pokes" air */
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    setWide(mq.matches);
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  /* --- interaction state --- */
  const targetRef = useRef<PokeTarget>("invoice");
  const firedRef = useRef(false);
  const zTarget = useRef(0);

  useFrame((state, rawDelta) => {
    const g = root.current;
    if (!g) return;
    const d = Math.min(rawDelta, 0.05);
    t.current += d;
    const time = state.clock.elapsedTime;

    /* random activity loop */
    if (t.current >= dur.current && !reduced) {
      t.current = 0;
      const canPoke = wide && variant === "hero";
      const pool: Phase[] = canPoke
        ? ["walk", "walk", "idle", "wave", "dance", "clap", "read", "sit", "hop", "interact", "interact"]
        : ["walk", "walk", "idle", "wave", "dance", "clap", "read", "sit", "hop"];
      let next = pick(pool);
      if (next === phase.current) next = pick(pool);
      phase.current = next;
      if (next === "interact") {
        targetRef.current = pick(POKEABLE);
        firedRef.current = false;
        dur.current = 4.6;
        zTarget.current = 0.55; // step forward, off his usual spot
      } else if (next === "walk") {
        dur.current = rand(3.5, 6.5);
        zTarget.current = rand(-0.15, 0.5); // wander the depth of the stage too
      } else {
        dur.current = rand(2.6, 4.4);
        zTarget.current = 0.08;
      }
    }
    if (reduced) phase.current = "idle";
    const p = phase.current;
    face.current = reduced ? "happy" : faceForPhase(p);

    /* movement: roam the floor, or walk UP TO a card and interact with it */
    let faceY: number;
    const hs = p === "interact" ? HOTSPOTS[targetRef.current] : null;
    if (hs) {
      const tx = hs.xf * bound;
      const dx = tx - g.position.x;
      g.position.x = THREE.MathUtils.damp(g.position.x, tx, 1.9, d);
      /* face where he is walking, then face the visitor once in position */
      faceY =
        t.current < 1.0 && Math.abs(dx) > 0.06
          ? THREE.MathUtils.clamp(dx, -1, 1) * 0.9
          : Math.sin(time * 0.6) * 0.06;
      /* the actual "poke": fire once as his hand lands */
      if (t.current > 1.5 && !firedRef.current) {
        firedRef.current = true;
        window.dispatchEvent(new CustomEvent("ledger-poke", { detail: { target: targetRef.current } }));
      }
    } else if (p === "walk") {
      g.position.x += dir.current * 0.5 * d;
      if (g.position.x > bound) dir.current = -1;
      else if (g.position.x < -bound) dir.current = 1;
      faceY = dir.current * 0.55;
    } else if (p === "clap" || p === "read" || p === "sit") {
      faceY = 0;
    } else {
      faceY = Math.sin(time * 0.6) * 0.12;
    }
    g.position.z = THREE.MathUtils.damp(g.position.z, zTarget.current, 2, d);
    g.rotation.y = THREE.MathUtils.damp(g.rotation.y, faceY, 4, d);
    g.rotation.z = p === "dance" ? Math.sin(t.current * 4) * 0.1 : THREE.MathUtils.damp(g.rotation.z, 0, 4, d);

    const bob = p === "walk" ? Math.abs(Math.sin(t.current * 9)) * 0.05 : Math.sin(time * 2) * 0.035;
    const hopY = p === "hop" ? Math.max(0, Math.sin(t.current * 5.5)) * 0.42 : 0;
    const sitY = p === "sit" ? -0.3 : 0;
    g.position.y = THREE.MathUtils.damp(g.position.y, bob + hopY + sitY, 10, d);

    /* limbs */
    const dampTo = (o: RefObject<THREE.Group | null>, x: number, z: number) => {
      if (!o.current) return;
      o.current.rotation.x = THREE.MathUtils.damp(o.current.rotation.x, x, 6, d);
      o.current.rotation.z = THREE.MathUtils.damp(o.current.rotation.z, z, 6, d);
    };
    const swing = p === "walk" ? Math.sin(t.current * 9) * 0.55 : 0;
    let axL = 0;
    let azL = 0;
    let axR = 0;
    let azR = 0;
    if (p === "wave") {
      azR = 2.35 + Math.sin(t.current * 10) * 0.3;
    } else if (p === "dance") {
      azL = -2.5 + Math.sin(t.current * 7) * 0.45;
      azR = 2.5 + Math.cos(t.current * 7) * 0.45;
      axL = axR = 0.25;
    } else if (p === "clap") {
      axL = axR = -1.15;
      azL = 0.32 + Math.max(0, Math.sin(t.current * 7)) * 0.5;
      azR = -azL;
    } else if (p === "read") {
      /* tablet arm lifts so the screen faces him; he looks down at it */
      axL = -1.15;
      axR = -0.9;
      azL = -0.25;
      azR = 0.3;
    } else if (p === "sit") {
      axL = -0.45;
      axR = -0.45;
      azL = -0.15;
      azR = 0.15;
    } else if (p === "walk") {
      axL = swing;
      axR = -swing;
    } else if (p === "interact") {
      /* reach out to the element; a small press-bounce as the hand lands */
      const [rx, rz] = HOTSPOTS[targetRef.current].reach;
      const press = t.current > 1.5 ? Math.max(0, Math.sin((t.current - 1.5) * 9)) * 0.3 : 0;
      axR = rx;
      azR = rz + press;
      azL = -0.1 + Math.sin(time * 1.7) * 0.05;
    } else {
      azL = -0.08 + Math.sin(time * 1.7) * 0.05;
      azR = 0.08 - Math.sin(time * 1.7) * 0.05;
    }
    dampTo(armL, axL, azL);
    dampTo(armR, axR, azR);

    const legSwing = p === "walk" ? Math.sin(t.current * 9) * 0.5 : 0;
    const sitLeg = p === "sit" ? -1.45 : 0;
    dampTo(legL, sitLeg + legSwing, 0);
    dampTo(legR, sitLeg - legSwing, 0);

    /* head: look down while reading, follow the cursor otherwise */
    if (head.current) {
      const look = reduced ? 0 : -state.pointer.y * 0.12;
      const down = (p === "read" ? 0.42 : 0) + (p === "sit" ? 0.08 : 0);
      head.current.rotation.x = THREE.MathUtils.damp(head.current.rotation.x, down + look, 5, d);
      head.current.rotation.y = reduced
        ? 0
        : THREE.MathUtils.damp(head.current.rotation.y, state.pointer.x * 0.25, 5, d);
    }
  });

  return (
    <RobotModel
      root={root}
      head={head}
      armL={armL}
      armR={armR}
      legL={legL}
      legR={legR}
      face={face}
      variant={variant}
      reduced={reduced}
    >
    </RobotModel>
  );
}

class RobotErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/* Colour-cycling glass podium. Soft, low-opacity, hue-cycling halo rings —
   it reads as part of the page's own gradient UI, not a bolt-on platform. */
function Podium({ compact }: { compact?: boolean }) {
  const haloA = useRef<THREE.MeshBasicMaterial>(null);
  const haloB = useRef<THREE.MeshBasicMaterial>(null);
  const haloC = useRef<THREE.MeshBasicMaterial>(null);
  const glowM = useRef<THREE.MeshBasicMaterial>(null);
  const top = useRef<THREE.MeshStandardMaterial>(null);
  const rim = useRef<THREE.MeshStandardMaterial>(null);

  useFrame((s) => {
    const t = s.clock.elapsedTime;
    if (haloA.current) haloA.current.color.setHSL((t * 0.045) % 1, 0.85, 0.6);
    if (haloB.current) haloB.current.color.setHSL((t * 0.045 + 0.33) % 1, 0.85, 0.6);
    if (haloC.current) haloC.current.color.setHSL((t * 0.045 + 0.66) % 1, 0.85, 0.64);
    if (glowM.current) glowM.current.color.setHSL((t * 0.045 + 0.2) % 1, 0.85, 0.7);
    if (top.current) top.current.color.setHSL((t * 0.03) % 1, 0.4, 0.97);
    if (rim.current) rim.current.color.setHSL((t * 0.03 + 0.5) % 1, 0.5, 0.93);
  });

  const R = compact ? 0.95 : 1.42;

  return (
    <group scale={compact ? [1.12, 1, 0.8] : [1.9, 1, 0.75]}>
      {/* glow halo bleeding onto the page — makes the disc feel native */}
      <mesh position={[0, -0.002, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[R * 1.4, 64]} />
        <meshBasicMaterial ref={glowM} transparent opacity={0.14} depthWrite={false} />
      </mesh>
      {/* body — whisper-clear glass, no hard edges */}
      <mesh position={[0, -0.08, 0]}>
        <cylinderGeometry args={[R, R * 1.08, 0.16, 64]} />
        <meshStandardMaterial ref={rim} color="#ffffff" roughness={0.15} metalness={0.05} transparent opacity={0.32} />
      </mesh>
      {/* top — faintly tinted glass */}
      <mesh position={[0, 0.001, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[R, 64]} />
        <meshStandardMaterial ref={top} color="#f6f9ff" roughness={0.3} metalness={0.04} transparent opacity={0.68} />
      </mesh>
      {/* three perpetually hue-cycling halo rings */}
      <mesh position={[0, 0.006, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[R * 0.85, R, 64]} />
        <meshBasicMaterial ref={haloA} transparent opacity={0.85} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0.011, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[R * 0.6, R * 0.68, 64]} />
        <meshBasicMaterial ref={haloB} transparent opacity={0.45} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0.014, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[R * 0.28, R * 0.36, 48]} />
        <meshBasicMaterial ref={haloC} transparent opacity={0.32} depthWrite={false} />
      </mesh>
    </group>
  );
}

function CameraRig({ variant }: { variant: Variant }) {
  const { camera } = useThree();
  useEffect(() => {
    /* hero: framing pinned LOW — his feet + podium sit at the bottom edge
       of the canvas, which itself reaches the backdrop's bottom border.
       compact pulls back + lifts the framing for the auth-page corner. */
    camera.position.set(0, variant === "hero" ? 1.4 : 1.18, variant === "hero" ? 4.6 : 4.75);
    camera.lookAt(0, variant === "hero" ? 1.2 : 1.02, 0);
  }, [camera, variant]);
  return null;
}

/* The stage the robot lives in. Sized by its parent — the hero's right
   column or a corner box on the auth pages. Transparent background:
   he floats directly over the page UI. */
export default function HeroRobotStage({ variant = "hero" }: { variant?: Variant }) {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return (
    <div className="relative h-full w-full" aria-hidden="true">
      <Canvas
        dpr={[1, 2]}
        performance={{ min: 0.5 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={{ position: [0, 1.4, 4.6], fov: 33 }}
        style={{ background: "transparent" }}
      >
        <CameraRig variant={variant} />

        {/* Lighting rig: soft studio key + teal rim = premium toy look */}
        <ambientLight intensity={0.6} />
        <hemisphereLight args={["#e0f2fe", "#ccfbf1", 0.6]} />
        <directionalLight position={[2.5, 4, 3]} intensity={1.5} />
        <directionalLight position={[-3, 2, -2.5]} intensity={1.1} color="#5eead4" />
        <pointLight position={[0, 0.5, 2.4]} intensity={0.4} color="#cffafe" />

        <Suspense fallback={null}>
          <RobotErrorBoundary>
            <RobotActor variant={variant} reduced={reduced} />
          </RobotErrorBoundary>
          {/* Colour-cycling glass podium — melts into the page UI */}
          <Podium compact={variant !== "hero"} />
          {/* Soft contact shadow grounds him on the platform */}
          <ContactShadows
            position={[0, 0.001, 0]}
            opacity={0.2}
            scale={3.4}
            blur={2.6}
            far={1.8}
            color="#1e3a5f"
          />
        </Suspense>
      </Canvas>
    </div>
  );
}
