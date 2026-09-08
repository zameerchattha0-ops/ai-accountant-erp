"use client";

/* ================================================================== */
/* "Ledger" — the 3D robot mascot. Lives INSIDE its stage (the hero's  */
/* right column / a corner of the auth pages) — never fixed to the     */
/* viewport, never covering copy.                                      */
/*                                                                      */
/* 100% procedural (react-three-fiber): glossy white shell, orange     */
/* accents, dark glass visor, glowing cyan eyes. Smooth surfaces,      */
/* no textures, no model downloads.                                    */
/*                                                                      */
/* Behaviour: a random activity loop — wave · idle · walk · hop ·      */
/* dance · clap · read · sit — roaming the stage's empty areas. A      */
/* premium glass speech bubble pops up at RANDOM intervals (it does    */
/* not stick around) with AI/accounting wit, typed out letter by       */
/* letter as if he is speaking it. Falls back to a calm idle under     */
/* prefers-reduced-motion.                                             */
/* ================================================================== */

import { Component, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, Html } from "@react-three/drei";

type Variant = "hero" | "compact";
type Phase = "wave" | "idle" | "walk" | "hop" | "dance" | "clap" | "read" | "sit";
type SpeechLine = { k: number; text: string };

/* Random AI / accounting wit for the speech bubble */
const SPEECH: string[] = [
  "Hi! I'm Ledger — your AI accountant.",
  "Debits on the left, dreams on the right. I balance both.",
  "Every entry tells a story. I write yours in real time.",
  "One sentence from you. A perfect journal entry from me.",
  "AI won't replace accountants — but AI-powered ones will replace the rest.",
  "Your books, balanced while you sip your chai.",
  "Trial balance happy? That's my love language.",
  "Invoices, ledgers, reports — done before your coffee cools.",
  "Focus on growing the business. I'll guard the numbers.",
  "Reconciliation is my cardio.",
  "Journal, Ledger, Trial Balance, Statements — I run the whole relay.",
  "Accounting in plain English. That's the whole trick.",
];

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}
function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/* Shared smooth materials — created once per instance */
function useRobotMaterials() {
  return useMemo(
    () => ({
      shell: new THREE.MeshStandardMaterial({ color: "#f5f7fa", roughness: 0.28, metalness: 0.06 }),
      accent: new THREE.MeshStandardMaterial({ color: "#ef8b2c", roughness: 0.35, metalness: 0.12 }),
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

/* Typewriter — the bubble "speaks" the line letter by letter */
function TypedText({ text }: { text: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    const iv = setInterval(() => {
      setN((v) => {
        if (v >= text.length) {
          clearInterval(iv);
          return v;
        }
        return v + 1;
      });
    }, 26);
    return () => clearInterval(iv);
  }, [text]);
  return (
    <>
      {text.slice(0, n)}
      {n < text.length && <span className="ledger-caret" />}
    </>
  );
}

function RobotCharacter({ variant, reduced }: { variant: Variant; reduced: boolean }) {
  const mats = useRobotMaterials();

  const root = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const legL = useRef<THREE.Group>(null);
  const legR = useRef<THREE.Group>(null);
  const book = useRef<THREE.Group>(null);
  const eyeL = useRef<THREE.Mesh>(null);
  const eyeR = useRef<THREE.Mesh>(null);

  /* --- behaviour state (refs on purpose: 60fps, no re-renders) --- */
  const phase = useRef<Phase>("wave");
  const t = useRef(0);
  const dur = useRef(reduced ? Infinity : 2.4);
  const dir = useRef<1 | -1>(1);
  useEffect(() => {
    dir.current = Math.random() > 0.5 ? 1 : -1;
  }, []);

  const { viewport } = useThree();
  /* Hero: stay in the open centre corridor between the floating cards
     (chips on the left edge, overview card on the right edge). */
  const bound =
    variant === "hero"
      ? Math.min(Math.max(0.55, viewport.width / 2 - 1.0), 1.0)
      : Math.max(0.3, viewport.width / 2 - 0.95);

  /* --- speech bubble: appears at RANDOM intervals, never sticky --- */
  const clock = useRef(0);
  const nextLine = useRef(2.2);
  const hideAt = useRef(0);
  const lineRef = useRef<SpeechLine | null>(null);
  const [line, setLine] = useState<SpeechLine | null>(null);
  const say = (l: SpeechLine | null) => {
    lineRef.current = l;
    setLine(l);
  };

  useFrame((state, rawDelta) => {
    const g = root.current;
    if (!g) return;
    const d = Math.min(rawDelta, 0.05);
    t.current += d;
    clock.current += d;
    const time = state.clock.elapsedTime;

    /* random speech timing */
    if (!reduced) {
      if (!lineRef.current && clock.current >= nextLine.current) {
        say({ k: clock.current, text: pick(SPEECH) });
        hideAt.current = clock.current + 6.5;
      } else if (lineRef.current && clock.current >= hideAt.current) {
        say(null);
        nextLine.current = clock.current + rand(6, 13);
      }
    }

    /* random activity loop */
    if (t.current >= dur.current && !reduced) {
      t.current = 0;
      const pool: Phase[] = ["walk", "walk", "idle", "wave", "dance", "clap", "read", "sit", "hop"];
      let next = pick(pool);
      if (next === phase.current) next = pick(pool);
      phase.current = next;
      dur.current = next === "walk" ? rand(3.5, 6.5) : rand(2.6, 4.4);
    }
    if (reduced) phase.current = "idle";
    const p = phase.current;

    /* roam the stage's empty floor */
    if (p === "walk") {
      g.position.x += dir.current * 0.5 * d;
      if (g.position.x > bound) dir.current = -1;
      else if (g.position.x < -bound) dir.current = 1;
    }
    const faceY =
      p === "walk"
        ? dir.current * 0.55
        : p === "clap" || p === "read" || p === "sit"
          ? 0
          : Math.sin(time * 0.6) * 0.12;
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
      axL = axR = -1.05;
      azL = -0.12;
      azR = 0.12;
    } else if (p === "sit") {
      axL = -0.45;
      axR = -0.45;
      azL = -0.15;
      azR = 0.15;
    } else if (p === "walk") {
      axL = swing;
      axR = -swing;
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
      const down = (p === "read" ? 0.38 : 0) + (p === "sit" ? 0.08 : 0);
      head.current.rotation.x = THREE.MathUtils.damp(head.current.rotation.x, down + look, 5, d);
      head.current.rotation.y = reduced
        ? 0
        : THREE.MathUtils.damp(head.current.rotation.y, state.pointer.x * 0.25, 5, d);
    }
    if (book.current) book.current.visible = p === "read";

    /* blink */
    const blink = time % 3.7 < 0.12 ? 0.15 : 1;
    if (eyeL.current) eyeL.current.scale.y = blink;
    if (eyeR.current) eyeR.current.scale.y = blink;
  });

  return (
    <group ref={root} scale={variant === "compact" ? 0.82 : 0.85}>
      {/* legs */}
      <group ref={legL} position={[-0.15, 0.46, 0]}>
        <mesh position={[0, -0.14, 0]} material={mats.dark}>
          <capsuleGeometry args={[0.05, 0.16, 6, 16]} />
        </mesh>
        <mesh position={[0, -0.3, 0.05]} scale={[1, 0.55, 1.4]} material={mats.accent}>
          <sphereGeometry args={[0.085, 24, 24]} />
        </mesh>
      </group>
      <group ref={legR} position={[0.15, 0.46, 0]}>
        <mesh position={[0, -0.14, 0]} material={mats.dark}>
          <capsuleGeometry args={[0.05, 0.16, 6, 16]} />
        </mesh>
        <mesh position={[0, -0.3, 0.05]} scale={[1, 0.55, 1.4]} material={mats.accent}>
          <sphereGeometry args={[0.085, 24, 24]} />
        </mesh>
      </group>

      {/* torso + glowing core + belt */}
      <mesh position={[0, 0.88, 0]} material={mats.shell}>
        <capsuleGeometry args={[0.3, 0.4, 12, 32]} />
      </mesh>
      <mesh position={[0, 0.95, 0.26]} material={mats.glow}>
        <sphereGeometry args={[0.055, 20, 20]} />
      </mesh>
      <mesh position={[0, 0.62, 0]} rotation={[Math.PI / 2, 0, 0]} material={mats.accent}>
        <torusGeometry args={[0.27, 0.03, 12, 40]} />
      </mesh>

      {/* arms */}
      <group ref={armL} position={[-0.37, 1.06, 0]}>
        <mesh material={mats.accent}>
          <sphereGeometry args={[0.085, 20, 20]} />
        </mesh>
        <mesh position={[0, -0.18, 0]} material={mats.shell}>
          <capsuleGeometry args={[0.05, 0.2, 6, 16]} />
        </mesh>
        <mesh position={[0, -0.34, 0]} material={mats.accent}>
          <sphereGeometry args={[0.07, 20, 20]} />
        </mesh>
      </group>
      <group ref={armR} position={[0.37, 1.06, 0]}>
        <mesh material={mats.accent}>
          <sphereGeometry args={[0.085, 20, 20]} />
        </mesh>
        <mesh position={[0, -0.18, 0]} material={mats.shell}>
          <capsuleGeometry args={[0.05, 0.2, 6, 16]} />
        </mesh>
        <mesh position={[0, -0.34, 0]} material={mats.accent}>
          <sphereGeometry args={[0.07, 20, 20]} />
        </mesh>
      </group>

      {/* neck + head */}
      <mesh position={[0, 1.24, 0]} material={mats.dark}>
        <cylinderGeometry args={[0.06, 0.08, 0.1, 16]} />
      </mesh>
      <group ref={head} position={[0, 1.6, 0]}>
        <mesh scale={[1, 0.92, 1]} material={mats.shell}>
          <sphereGeometry args={[0.36, 48, 48]} />
        </mesh>
        <mesh position={[0, 0.02, 0.26]} scale={[1, 0.78, 0.45]} material={mats.visor}>
          <sphereGeometry args={[0.24, 32, 32]} />
        </mesh>
        <mesh ref={eyeL} position={[-0.085, 0.04, 0.335]} material={mats.eye}>
          <sphereGeometry args={[0.042, 16, 16]} />
        </mesh>
        <mesh ref={eyeR} position={[0.085, 0.04, 0.335]} material={mats.eye}>
          <sphereGeometry args={[0.042, 16, 16]} />
        </mesh>
        {/* ear discs */}
        <mesh position={[-0.38, 0, 0]} rotation={[0, 0, Math.PI / 2]} material={mats.accent}>
          <cylinderGeometry args={[0.09, 0.09, 0.05, 24]} />
        </mesh>
        <mesh position={[0.38, 0, 0]} rotation={[0, 0, Math.PI / 2]} material={mats.accent}>
          <cylinderGeometry args={[0.09, 0.09, 0.05, 24]} />
        </mesh>
        {/* antenna */}
        <mesh position={[0, 0.4, 0]} material={mats.dark}>
          <cylinderGeometry args={[0.015, 0.02, 0.12, 12]} />
        </mesh>
        <mesh position={[0, 0.5, 0]} material={mats.glow}>
          <sphereGeometry args={[0.045, 16, 16]} />
        </mesh>
      </group>

      {/* reading book — appears only while reading */}
      <group ref={book} position={[0, 0.98, 0.42]} rotation={[-0.35, 0, 0]} visible={false}>
        <mesh rotation={[0, 0.35, 0]} position={[-0.07, 0, 0]} material={mats.shell}>
          <boxGeometry args={[0.16, 0.02, 0.22]} />
        </mesh>
        <mesh rotation={[0, -0.35, 0]} position={[0.07, 0, 0]} material={mats.shell}>
          <boxGeometry args={[0.16, 0.02, 0.22]} />
        </mesh>
        <mesh position={[0, -0.015, 0]} material={mats.accent}>
          <boxGeometry args={[0.3, 0.02, 0.24]} />
        </mesh>
      </group>

      {/* speech bubble — anchored above the head, follows him while roaming */}
      {!reduced && (
        <Html position={[0, 2.3, 0]} center zIndexRange={[40, 0]} style={{ pointerEvents: "none" }}>
          {line && (
            <div key={line.k} className="ledger-bubble">
              <div className="ledger-bubble-head">
                <span className="ledger-dot" />
                <span className="ledger-tag">✦ Ledger says</span>
              </div>
              <div className="ledger-quote">
                <TypedText text={line.text} />
              </div>
              <div className="ledger-tail" />
            </div>
          )}
        </Html>
      )}
    </group>
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
    camera.position.set(0, variant === "hero" ? 1.15 : 1.1, variant === "hero" ? 4.9 : 4.4);
    camera.lookAt(0, 0.95, 0);
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
        camera={{ position: [0, 1.15, 4.9], fov: 33 }}
        style={{ background: "transparent" }}
      >
        <CameraRig variant={variant} />

        {/* Lighting rig: soft studio key + teal rim = premium toy look */}
        <ambientLight intensity={0.6} />
        <hemisphereLight args={["#e0f2fe", "#fdf2f8", 0.6]} />
        <directionalLight position={[2.5, 4, 3]} intensity={1.5} />
        <directionalLight position={[-3, 2, -2.5]} intensity={0.9} color="#67e8f9" />
        <pointLight position={[0, 0.5, 2.4]} intensity={0.4} color="#fef3c7" />

        <Suspense fallback={null}>
          <RobotErrorBoundary>
            <RobotCharacter variant={variant} reduced={reduced} />
          </RobotErrorBoundary>
          {/* Soft contact shadow grounds him without any platform */}
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