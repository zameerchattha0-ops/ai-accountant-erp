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
type Phase =
  | "wave" | "idle" | "walk" | "hop" | "dance" | "clap" | "read" | "sit"
  | "interact" | "spin" | "stretch" | "think" | "march" | "peek" | "jumpingjack";
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
  if (p === "read" || p === "think") return "focus";
  if (p === "spin" || p === "jumpingjack" || p === "march" || p === "peek" || p === "stretch") return "excited";
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
  /* Hero: roam the FULL stage width — he owns the whole right column now.
     The floating cards only render ≥ md; he still walks up to them. */
  const bound =
    variant === "hero"
      ? Math.min(Math.max(0.65, viewport.width / 2 - 1.0), 1.1)
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

    /* random activity loop — bigger repertoire, weighted toward motion */
    if (t.current >= dur.current && !reduced) {
      t.current = 0;
      const canPoke = wide && variant === "hero";
      const pool: Phase[] = canPoke
        ? ["walk", "walk", "idle", "wave", "dance", "clap", "read", "sit", "hop",
           "interact", "interact", "spin", "stretch", "think", "march", "peek", "jumpingjack"]
        : ["walk", "walk", "idle", "wave", "dance", "clap", "read", "sit", "hop",
           "spin", "stretch", "think", "march", "peek", "jumpingjack"];
      let next = pick(pool);
      if (next === phase.current) next = pick(pool);
      phase.current = next;
      if (next === "interact") {
        targetRef.current = pick(POKEABLE);
        firedRef.current = false;
        dur.current = 4.6;
        zTarget.current = 0.3; // small step forward — kept shallow so his
        // feet and reaching hand always stay inside the frame (no-crop)
      } else if (next === "walk") {
        dur.current = rand(3.5, 6.5);
        zTarget.current = rand(-0.15, 0.5); // wander the depth of the stage too
      } else if (next === "spin") {
        dur.current = rand(1.6, 2.2);
        zTarget.current = 0.1;
      } else if (next === "jumpingjack" || next === "march") {
        dur.current = rand(2.4, 3.6);
        zTarget.current = 0.12;
      } else if (next === "think" || next === "peek") {
        dur.current = rand(2.2, 3.4);
        zTarget.current = 0.08;
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
      /* no-crop: clamp the step-in point so his raised reaching hand stays
         inside the frame on every viewport size */
      const maxX = Math.max(0.15, state.viewport.width / 2 - 1.05);
      const tx = THREE.MathUtils.clamp(hs.xf * bound, -maxX, maxX);
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
    } else if (p === "clap" || p === "read" || p === "sit" || p === "spin"
      || p === "march" || p === "jumpingjack" || p === "stretch" || p === "think") {
      faceY = 0;
    } else {
      faceY = Math.sin(time * 0.6) * 0.12;
    }
    /* no-crop guard: while an arm sweeps out to the side (wave, dance,
       clap, spin, stretch, jumping jacks) drift him back toward the centre
       so his hand can never cross the canvas border */
    if (!hs && (p === "wave" || p === "dance" || p === "clap" || p === "spin"
      || p === "stretch" || p === "jumpingjack")) {
      g.position.x = THREE.MathUtils.damp(g.position.x, g.position.x * 0.3, 1.5, d);
    }
    g.position.z = THREE.MathUtils.damp(g.position.z, zTarget.current, 2, d);
    g.rotation.y = THREE.MathUtils.damp(g.rotation.y, faceY, 4, d);
    if (p === "spin") g.rotation.y = t.current * 5.2; // a full twirl
    g.rotation.z =
      p === "dance"
        ? Math.sin(t.current * 4) * 0.1
        : p === "peek"
          ? Math.sin(Math.min(t.current * 1.6, Math.PI)) * 0.3
          : THREE.MathUtils.damp(g.rotation.z, 0, 4, d);

    const bob = p === "walk" ? Math.abs(Math.sin(t.current * 9)) * 0.05 : Math.sin(time * 2) * 0.035;
    const hopY =
      p === "hop"
        ? Math.max(0, Math.sin(t.current * 5.5)) * 0.42
        : p === "jumpingjack"
          ? Math.abs(Math.sin(t.current * 6)) * 0.16
          : p === "march"
            ? Math.abs(Math.sin(t.current * 7)) * 0.08
            : 0;
    const sitY = p === "sit" ? -0.3 : 0;
    const toeY = p === "stretch" ? 0.06 : 0;
    g.position.y = THREE.MathUtils.damp(g.position.y, bob + hopY + sitY + toeY, 10, d);

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
    } else if (p === "spin") {
      /* arms tucked for the twirl */
      azL = -1.5;
      azR = 1.5;
      axL = axR = -0.2;
    } else if (p === "stretch") {
      /* both arms reach for the sky with a slow sway, up on his toes */
      const sway = Math.sin(t.current * 2.4) * 0.18;
      azL = -2.55 + sway;
      azR = 2.55 - sway;
      axL = axR = -0.3;
    } else if (p === "think") {
      /* hand to chin, pondering */
      axR = -2.15;
      azR = 0.4;
      azL = -0.12;
    } else if (p === "march") {
      /*vigorous arm pump opposite the knees */
      axL = Math.sin(t.current * 7) * 0.9;
      axR = -Math.sin(t.current * 7) * 0.9;
    } else if (p === "jumpingjack") {
      /* arms sweep up-and-out together with each beat */
      const up = (Math.sin(t.current * 6) + 1) / 2;
      azL = -(0.25 + up * 2.2);
      azR = 0.25 + up * 2.2;
    } else if (p === "peek") {
      /* hands cupped, leaning to peek around */
      azL = -0.5;
      azR = 0.5;
    } else {
      azL = -0.08 + Math.sin(time * 1.7) * 0.05;
      azR = 0.08 - Math.sin(time * 1.7) * 0.05;
    }
    dampTo(armL, axL, azL);
    dampTo(armR, axR, azR);

    const legSwing =
      p === "walk"
        ? Math.sin(t.current * 9) * 0.5
        : p === "march"
          ? Math.sin(t.current * 7) * 0.95
          : p === "jumpingjack"
            ? Math.sin(t.current * 6) * 0.35
            : 0;
    const sitLeg = p === "sit" ? -1.45 : 0;
    dampTo(legL, sitLeg + legSwing, 0);
    dampTo(legR, sitLeg - legSwing, 0);

    /* head: look down while reading, ponder upward while thinking, tilt
       into the peek, follow the cursor otherwise */
    if (head.current) {
      const look = reduced ? 0 : -state.pointer.y * 0.12;
      const down =
        (p === "read" ? 0.42 : 0) + (p === "sit" ? 0.08 : 0) + (p === "think" ? -0.24 : 0);
      const tilt =
        p === "peek"
          ? Math.sin(Math.min(t.current * 1.6, Math.PI)) * 0.3
          : p === "think"
            ? 0.14
            : 0;
      head.current.rotation.x = THREE.MathUtils.damp(head.current.rotation.x, down + look, 5, d);
      head.current.rotation.y = reduced
        ? 0
        : THREE.MathUtils.damp(head.current.rotation.y, state.pointer.x * 0.25, 5, d);
      head.current.rotation.z = THREE.MathUtils.damp(head.current.rotation.z, tilt, 5, d);
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


function CameraRig({ variant }: { variant: Variant }) {
  const { camera } = useThree();
  useEffect(() => {
    /* hero: closer + centred — the canvas now spans the FULL hero row, so
       framing him larger keeps him prominent while his head and boots both
       stay inside the frame at any height. compact pulls back + lifts the
       framing for the auth-page corner. */
    camera.position.set(0, variant === "hero" ? 1.5 : 1.18, variant === "hero" ? 5.8 : 4.75);
    camera.lookAt(0, variant === "hero" ? 1.1 : 1.02, 0);
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
        camera={{ position: [0, 1.5, 5.8], fov: 33 }}
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
          {/* Robot only — no podium, no platform elements. A soft contact
              shadow is all that grounds him on the page backdrop. */}
          <ContactShadows
            position={[0, 0.001, 0]}
            opacity={0.16}
            scale={3.0}
            blur={2.8}
            far={1.8}
            color="#1e3a5f"
          />
        </Suspense>
      </Canvas>
    </div>
  );
}
