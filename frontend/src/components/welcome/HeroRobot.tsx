"use client";

/* ================================================================== */
/* "Ledger" — the free-roaming 3D robot companion                      */
/*                                                                     */
/* 100% procedural (react-three-fiber) — no external model. Glossy     */
/* chibi robot: white shell, orange accents, dark-glass visor,         */
/* glowing cyan eyes.                                                  */
/*                                                                     */
/* Mounted as a FIXED, FULL-VIEWPORT overlay that never blocks the     */
/* page (pointer-events pass through everywhere except the speech      */
/* bubble). Ledger wanders the whole viewport forever, picking random  */
/* activities: walking to random spots · idle breathing · looking      */
/* around · waving · clapping · dancing · reading his ledger ·         */
/* sitting · hop-spins.                                                */
/*                                                                     */
/* Placement adapts per page:                                          */
/*   mode="free" (landing)  → roams the entire viewport                */
/*   mode="auth" (login/signup) → stays clear of the central card on   */
/*   desktop; hovers in the top band on phones.                        */
/*                                                                     */
/* The premium glass speech bubble typewrites random AI/finance        */
/* quotes with authors; clicking it makes him celebrate (hop + spin)   */
/* and say something new. Reduced-motion users get a calm static pose. */
/* ================================================================== */

import { Component, Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, Html } from "@react-three/drei";

export type RobotMode = "free" | "auth";
type Phase =
  | "wave"
  | "idle"
  | "walk"
  | "look"
  | "dance"
  | "read"
  | "clap"
  | "sit"
  | "hop";

/* ---- Quote deck — the bubble typewrites these forever ---- */
const QUOTES: { text: string; by: string }[] = [
  { text: "Beware of little expenses; a small leak will sink a great ship.", by: "Benjamin Franklin" },
  { text: "Accounting is the language of business — and I am fluent.", by: "Ledger" },
  { text: "An investment in knowledge pays the best interest.", by: "Benjamin Franklin" },
  { text: "Price is what you pay. Value is what you get.", by: "Warren Buffett" },
  { text: "Every debit finds its soulmate: the credit.", by: "Ledger" },
  { text: "Do not save what is left after spending; spend what is left after saving.", by: "Warren Buffett" },
  { text: "Automation applied to an efficient operation magnifies efficiency.", by: "Bill Gates" },
  { text: "Cash flow is the heartbeat of a business. I keep my finger on the pulse.", by: "Ledger" },
  { text: "The best way to predict the future is to create it.", by: "Peter Drucker" },
  { text: "I balance your books while you build your empire.", by: "Ledger" },
  { text: "Numbers tell stories. I just translate them.", by: "Ledger" },
  { text: "It is not how much money you make, but how much you keep.", by: "Robert Kiyosaki" },
  { text: "Errors fear me. Reconciliations love me.", by: "Ledger" },
  { text: "Simplicity is the ultimate sophistication — even in bookkeeping.", by: "after Leonardo da Vinci" },
  { text: "A balanced book is a peaceful mind.", by: "Ledger" },
  { text: "Ask me anything. I speak fluent accounting.", by: "Ledger" },
  { text: "Wealth consists not in having great possessions, but in having few wants.", by: "Epictetus" },
  { text: "I never sleep, so your ledger never rests.", by: "Ledger" },
];

function pickQuote(exclude: number): number {
  let i = Math.floor(Math.random() * QUOTES.length);
  if (i === exclude) i = (i + 1) % QUOTES.length;
  return i;
}

/* ---- Shared glossy materials — created once per instance ---- */
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

/* ---- Viewport → world placement --------------------------------------
   Camera sits at (0, 0.9, 8.5) looking straight ahead, fov 26 — so the
   visible plane is H = 2·tan(fov/2)·8.5 world units tall. We map
   "fractions from the top of the screen" to world Y and clamp the
   walkable band per page mode. --------------------------------------- */
interface StageView {
  scale: number;
  groundY: number;
  xMin: number;
  xMax: number;
  avoid: number; // half-width of a forbidden central band (0 = none)
}

function computeView(mode: RobotMode, W: number, H: number): StageView {
  const portrait = W / H < 0.85;
  if (mode === "auth") {
    if (portrait) {
      return { scale: 0.42, groundY: 0.9 + (0.5 - 0.34) * H, xMin: -W * 0.18, xMax: W * 0.18, avoid: 0 };
    }
    return { scale: 0.52, groundY: 0.9 + (0.5 - 0.82) * H, xMin: -W / 2 + 0.5, xMax: W / 2 - 0.5, avoid: W * 0.24 };
  }
  if (portrait) {
    return { scale: 0.46, groundY: 0.9 + (0.5 - 0.34) * H, xMin: -W * 0.3, xMax: W * 0.3, avoid: 0 };
  }
  return { scale: 0.6, groundY: 0.9 + (0.5 - 0.86) * H, xMin: -W / 2 + 0.55, xMax: W / 2 - 0.55, avoid: 0 };
}

/* ==== RIG ==== */

function RobotCharacter({
  mode,
  reduced,
  compact,
  pokeRef,
}: {
  mode: RobotMode;
  reduced: boolean;
  compact: boolean;
  pokeRef: React.MutableRefObject<number>;
}) {
  const mats = useRobotMaterials();

  const root = useRef<THREE.Group>(null);
  const squash = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const legL = useRef<THREE.Group>(null);
  const legR = useRef<THREE.Group>(null);
  const eyeL = useRef<THREE.Mesh>(null);
  const eyeR = useRef<THREE.Mesh>(null);
  const book = useRef<THREE.Group>(null);
  const anchor = useRef<THREE.Group>(null);

  /* --- behaviour state (refs, not React state: this runs at 60fps) --- */
  const phase = useRef<Phase>("wave");
  const timer = useRef(2.8);
  const tx = useRef(0);
  const hopT = useRef(-1);
  const lastPoke = useRef(0);
  const blinkIn = useRef(2.4);
  const blinkT = useRef(0);
  const bookS = useRef(0);
  const t = useRef(0);
  const init = useRef(false);

  useFrame((state, rawDelta) => {
    const g = root.current;
    const sq = squash.current;
    if (!g || !sq) return;
    const dt = Math.min(rawDelta, 0.05); // clamp tab-switch spikes
    t.current += dt;

    /* viewport → world placement */
    const cam = state.camera as THREE.PerspectiveCamera;
    const H = 2 * Math.tan(((cam.fov ?? 26) * Math.PI) / 360) * cam.position.z;
    const W = H * (state.size.width / Math.max(state.size.height, 1));
    const v = computeView(mode, W, H);

    if (!init.current) {
      init.current = true;
      g.scale.setScalar(v.scale);
      g.position.set(0, v.groundY, 0);
    }

    const d = (cur: number, target: number, lambda = 10) =>
      THREE.MathUtils.damp(cur, target, lambda, dt);

    /* neutral pose; each phase mutates it, then everything is damped */
    const p = {
      aLx: 0, aLz: -0.16, aRx: 0, aRz: 0.16,
      lLx: 0, lRx: 0,
      headX: 0, headY: 0,
      rotY: 0, rotZ: 0, yOff: 0, sq: 1,
      follow: true,
    };

    const choose = () => {
      const r = Math.random();
      if (r < 0.34) {
        /* walk to a fresh random spot (avoiding the auth card zone) */
        let target = v.xMin + Math.random() * (v.xMax - v.xMin);
        if (v.avoid > 0 && Math.abs(target) < v.avoid) {
          target = (target >= 0 ? 1 : -1) * (v.avoid + Math.random() * 0.6);
          target = THREE.MathUtils.clamp(target, v.xMin, v.xMax);
        }
        tx.current = target;
        phase.current = "walk";
      } else if (r < 0.47) { phase.current = "idle"; timer.current = 1.6 + Math.random() * 1.8; }
      else if (r < 0.55) { phase.current = "look"; timer.current = 2.4; }
      else if (r < 0.65) { phase.current = "wave"; timer.current = 2.6; }
      else if (r < 0.73) { phase.current = "clap"; timer.current = 2.8; }
      else if (r < 0.83) { phase.current = "dance"; timer.current = 3.4; }
      else if (r < 0.91) { phase.current = "read"; timer.current = 4.2; }
      else if (r < 0.96) { phase.current = "sit"; timer.current = 3.4; }
      else { phase.current = "hop"; hopT.current = 0; timer.current = 1.2; }
    };

    if (reduced) {
      /* calm static pose — no wandering, no timers */
      const restX = v.avoid > 0 ? Math.max(v.xMin, -(W / 2 - 0.7)) : 0;
      g.position.x = d(g.position.x, restX, 3);
      g.position.y = d(g.position.y, v.groundY, 3);
      g.scale.setScalar(d(g.scale.x, v.scale, 3));
    } else {
      /* visitor poked the bubble → celebrate */
      if (pokeRef.current !== lastPoke.current) {
        lastPoke.current = pokeRef.current;
        phase.current = "hop";
        hopT.current = 0;
        timer.current = 1.2;
      }

      switch (phase.current) {
        case "wave":
          p.aRz = 2.35 + Math.sin(t.current * 9) * 0.35;
          p.rotY = -0.18;
          p.headY = 0.2;
          p.headX = -0.05;
          break;
        case "walk": {
          const dx = tx.current - g.position.x;
          const dir = dx >= 0 ? 1 : -1;
          const speed = 0.9 * v.scale;
          g.position.x += Math.sign(dx) * Math.min(Math.abs(dx), speed * dt);
          const sw = Math.sin(t.current * 9);
          p.lLx = sw * 0.55; p.lRx = -sw * 0.55;
          p.aLx = -sw * 0.45; p.aRx = sw * 0.45;
          p.yOff = Math.abs(Math.sin(t.current * 9)) * 0.05;
          p.rotY = dir * 0.5;
          p.headY = dir * 0.28;
          p.follow = false;
          if (Math.abs(dx) < 0.05) choose();
          break;
        }
        case "look":
          p.headY = Math.sin(t.current * 1.7) * 0.75;
          p.rotY = Math.sin(t.current * 1.7) * 0.16;
          break;
        case "clap":
          p.aLx = -1.25 + Math.sin(t.current * 11) * 0.35;
          p.aRx = p.aLx;
          p.aLz = -0.3; p.aRz = 0.3;
          p.yOff = Math.abs(Math.sin(t.current * 11)) * 0.025;
          p.headX = -0.08;
          break;
        case "dance":
          p.yOff = Math.abs(Math.sin(t.current * 6.5)) * 0.11;
          p.rotZ = Math.sin(t.current * 3.25) * 0.14;
          p.aLz = -(0.9 + Math.sin(t.current * 6.5) * 0.85);
          p.aRz = 0.9 + Math.sin(t.current * 6.5) * 0.85;
          p.rotY = Math.sin(t.current * 3.25) * 0.22;
          p.headY = Math.sin(t.current * 3.25) * 0.35;
          break;

        case "read":
          p.aLx = -1.35; p.aRx = -1.35;
          p.aLz = -0.32; p.aRz = 0.32;
          p.headX = 0.42;
          p.rotY = Math.sin(t.current * 0.9) * 0.06;
          break;
        case "sit":
          p.lLx = -1.5; p.lRx = -1.5;
          p.aLx = -0.35; p.aRx = -0.35;
          p.yOff = -0.3;
          p.headX = -0.05 + Math.sin(t.current * 0.8) * 0.08;
          break;
        case "hop": {
          if (hopT.current < 0) hopT.current = 0;
          hopT.current = Math.min(hopT.current + dt / 0.9, 1);
          const k = hopT.current;
          p.yOff = Math.sin(Math.PI * k) * 0.6;
          p.rotY = k * Math.PI * 2;
          p.sq = 1 + Math.sin(Math.PI * k) * 0.1;
          p.aLz = -1.4; p.aRz = 1.4;
          p.follow = false;
          if (k >= 1) {
            hopT.current = -1;
            g.rotation.y = 0; // land facing the visitor again
            choose();
          }
          break;
        }
        case "idle":
        default:
          break;
      }

      /* non-walking phases run on their countdown timer */
      if (phase.current !== "walk" && phase.current !== "hop") {
        timer.current -= dt;
        if (timer.current <= 0) choose();
      }

      g.position.y = d(g.position.y, v.groundY + p.yOff * v.scale, 6);
      g.scale.setScalar(d(g.scale.x, v.scale, 5));
    }

    /* idle micro-life: gentle breathing on top of any pose */
    if (!reduced && phase.current !== "hop") {
      p.sq += Math.sin(t.current * 2.3) * 0.015;
    }

    /* head follows the visitor's cursor unless busy walking */
    if (p.follow && !reduced) {
      p.headY += state.pointer.x * 0.5;
      p.headX += -state.pointer.y * 0.28;
    }

    /* apply the pose with damping — every transition is buttery */
    if (armL.current) {
      armL.current.rotation.x = d(armL.current.rotation.x, p.aLx, 9);
      armL.current.rotation.z = d(armL.current.rotation.z, p.aLz, 9);
    }
    if (armR.current) {
      armR.current.rotation.x = d(armR.current.rotation.x, p.aRx, 9);
      armR.current.rotation.z = d(armR.current.rotation.z, p.aRz, 9);
    }
    if (legL.current) legL.current.rotation.x = d(legL.current.rotation.x, p.lLx, 9);
    if (legR.current) legR.current.rotation.x = d(legR.current.rotation.x, p.lRx, 9);
    if (head.current) {
      head.current.rotation.y = d(head.current.rotation.y, p.headY, 7);
      head.current.rotation.x = d(head.current.rotation.x, p.headX, 7);
    }
    g.rotation.y = d(g.rotation.y, p.rotY, 10);
    g.rotation.z = d(g.rotation.z, p.rotZ, 8);
    sq.scale.y = d(sq.scale.y, p.sq, 9);
    sq.scale.x = sq.scale.z = d(sq.scale.x, 1 - (p.sq - 1) * 0.6, 9);

    /* blinking */
    blinkIn.current -= dt;
    if (blinkIn.current <= 0) {
      blinkT.current = 0.12;
      blinkIn.current = 2.2 + Math.random() * 2.8;
    }
    if (blinkT.current > 0) blinkT.current -= dt;
    const eyeS = blinkT.current > 0 ? 0.08 : 1;
    if (eyeL.current) eyeL.current.scale.y = eyeS;
    if (eyeR.current) eyeR.current.scale.y = eyeS;

    /* the tiny ledger he "reads" pops in only while reading */
    if (book.current) {
      bookS.current = d(bookS.current, phase.current === "read" ? 1 : 0, 8);
      book.current.visible = bookS.current > 0.02;
      book.current.scale.setScalar(Math.max(bookS.current, 0.001));
    }

    /* speech-bubble anchor: above the head on desktop, beside on phones */
    if (anchor.current) {
      anchor.current.position.y = d(anchor.current.position.y, compact ? 0.62 : 1.98, 6);
    }
  });

  return (
    <group ref={root}>
      <group ref={squash}>
        {/* body */}
        <mesh position={[0, 0.66, 0]} material={mats.shell}>
          <capsuleGeometry args={[0.36, 0.44, 12, 32]} />
        </mesh>
        {/* chest core */}
        <mesh position={[0, 0.72, 0.315]} material={mats.dark}>
          <torusGeometry args={[0.11, 0.028, 12, 40]} />
        </mesh>
        <mesh position={[0, 0.72, 0.325]} material={mats.glow}>
          <circleGeometry args={[0.095, 32]} />
        </mesh>

        {/* head */}
        <group ref={head} position={[0, 1.36, 0]}>
          <mesh scale={[1, 0.94, 0.96]} material={mats.shell}>
            <sphereGeometry args={[0.44, 48, 48]} />
          </mesh>
          {/* visor */}
          <mesh position={[0, 0.02, 0.16]} scale={[1, 0.82, 0.55]} material={mats.visor}>
            <sphereGeometry args={[0.34, 48, 48]} />
          </mesh>
          {/* eyes */}
          <mesh ref={eyeL} position={[-0.115, 0.05, 0.33]} material={mats.eye}>
            <sphereGeometry args={[0.055, 24, 24]} />
          </mesh>
          <mesh ref={eyeR} position={[0.115, 0.05, 0.33]} material={mats.eye}>
            <sphereGeometry args={[0.055, 24, 24]} />
          </mesh>
          {/* smile */}
          <mesh position={[0, -0.05, 0.345]} rotation={[0.25, 0, Math.PI]} material={mats.eye}>
            <torusGeometry args={[0.075, 0.014, 10, 24, Math.PI]} />
          </mesh>
          {/* ear discs */}
          <mesh position={[-0.45, 0.02, 0]} rotation={[0, 0, Math.PI / 2]} material={mats.accent}>
            <cylinderGeometry args={[0.1, 0.1, 0.07, 32]} />
          </mesh>
          <mesh position={[0.45, 0.02, 0]} rotation={[0, 0, Math.PI / 2]} material={mats.accent}>
            <cylinderGeometry args={[0.1, 0.1, 0.07, 32]} />
          </mesh>
          {/* antenna */}
          <mesh position={[0, 0.52, 0]} material={mats.dark}>
            <cylinderGeometry args={[0.02, 0.03, 0.16, 16]} />
          </mesh>
          <mesh position={[0, 0.63, 0]} material={mats.glow}>
            <sphereGeometry args={[0.055, 24, 24]} />
          </mesh>
        </group>

        {/* arms (pivot at the shoulders) */}
        <group ref={armL} position={[-0.43, 1.0, 0]}>
          <mesh position={[0, -0.2, 0]} material={mats.shell}>
            <capsuleGeometry args={[0.095, 0.26, 8, 24]} />
          </mesh>
          <mesh position={[0, -0.42, 0]} material={mats.accent}>
            <sphereGeometry args={[0.11, 24, 24]} />
          </mesh>
        </group>
        <group ref={armR} position={[0.43, 1.0, 0]}>
          <mesh position={[0, -0.2, 0]} material={mats.shell}>
            <capsuleGeometry args={[0.095, 0.26, 8, 24]} />
          </mesh>
          <mesh position={[0, -0.42, 0]} material={mats.accent}>
            <sphereGeometry args={[0.11, 24, 24]} />
          </mesh>
        </group>

        {/* legs (pivot at the hips) */}
        <group ref={legL} position={[-0.17, 0.24, 0]}>
          <mesh position={[0, -0.12, 0]} material={mats.shell}>
            <capsuleGeometry args={[0.1, 0.14, 8, 24]} />
          </mesh>
          <mesh position={[0, -0.26, 0.04]} scale={[1, 0.55, 1.35]} material={mats.accent}>
            <sphereGeometry args={[0.12, 24, 24]} />
          </mesh>
        </group>
        <group ref={legR} position={[0.17, 0.24, 0]}>
          <mesh position={[0, -0.12, 0]} material={mats.shell}>
            <capsuleGeometry args={[0.1, 0.14, 8, 24]} />
          </mesh>
          <mesh position={[0, -0.26, 0.04]} scale={[1, 0.55, 1.35]} material={mats.accent}>
            <sphereGeometry args={[0.12, 24, 24]} />
          </mesh>
        </group>

        {/* the tiny ledger he "reads" */}
        <group ref={book} position={[0, 0.82, 0.42]} rotation={[-0.45, 0, 0]} visible={false}>
          <mesh position={[-0.09, 0, 0]} rotation={[0, 0.35, 0]}>
            <boxGeometry args={[0.2, 0.02, 0.28]} />
            <meshStandardMaterial color="#0ea5a4" roughness={0.4} />
          </mesh>
          <mesh position={[0.09, 0, 0]} rotation={[0, -0.35, 0]}>
            <boxGeometry args={[0.2, 0.02, 0.28]} />
            <meshStandardMaterial color="#f8fafc" roughness={0.5} />
          </mesh>
          <mesh position={[0, 0.015, 0]}>
            <boxGeometry args={[0.045, 0.03, 0.3]} />
            <meshStandardMaterial color="#0d9488" roughness={0.4} />
          </mesh>
        </group>
      </group>

      {/* speech-bubble anchor rides above the head (beside on phones) */}
      <group ref={anchor} position={[0, 1.98, 0]}>
        <SpeechBubble pokeRef={pokeRef} compact={compact} />
      </group>

      {/* grounding shadow that follows him everywhere */}
      <ContactShadows
        position={[0, 0.005, 0]}
        opacity={0.2}
        scale={2.2}
        blur={2.6}
        far={1.2}
        color="#1e3a5f"
      />
    </group>
  );
}

/* ---- Premium speech bubble — typewrites random quotes forever ---- */
function SpeechBubble({
  pokeRef,
  compact,
}: {
  pokeRef: React.MutableRefObject<number>;
  compact: boolean;
}) {
  const [idx, setIdx] = useState(() => Math.floor(Math.random() * QUOTES.length));
  const [typed, setTyped] = useState("");
  const [done, setDone] = useState(false);

  /* typewriter */
  useEffect(() => {
    setTyped("");
    setDone(false);
    const text = QUOTES[idx].text;
    let i = 0;
    const timer = setInterval(() => {
      i += 1;
      setTyped(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(timer);
        setDone(true);
      }
    }, compact ? 16 : 21);
    return () => clearInterval(timer);
  }, [idx, compact]);

  /* dwell, then say the next thing */
  useEffect(() => {
    if (!done) return;
    const timer = setTimeout(() => setIdx((cur) => pickQuote(cur)), 6500);
    return () => clearTimeout(timer);
  }, [done, idx]);

  const celebrate = () => {
    pokeRef.current += 1;
    setIdx((cur) => pickQuote(cur));
  };

  return (
    <Html zIndexRange={[46, 40]} wrapperClass="ledger-html">
      <div className={`ledger-bubble-wrap ${compact ? "is-compact" : ""}`}>
        <div
          key={idx}
          role="status"
          onClick={celebrate}
          className={`ledger-bubble lp-trace ${compact ? "ledger-bubble-sm" : ""}`}
        >
          <div className="ledger-bubble-head">
            <span className="ledger-dot" />
            <span className="ledger-tag">Ledger · AI Companion</span>
          </div>
          <p className={`ledger-quote ${done ? "" : "ledger-caret"}`}>
            <span className="ledger-qmark">“</span>
            {typed}
            {done && <span className="ledger-qmark">”</span>}
          </p>
          <p className="ledger-by">— {QUOTES[idx].by}</p>
        </div>
        <div className="ledger-tail" />
      </div>
    </Html>
  );
}

/* ---- Error boundary: if WebGL is unavailable, silently vanish ---- */
class RobotErrorBoundary extends Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/* ---- Fixed camera — placement math depends on these exact values ---- */
function CameraRig() {
  const { camera } = useThree();
  useEffect(() => {
    camera.position.set(0, 0.9, 8.5);
    camera.lookAt(0, 0.9, 0);
  }, [camera]);
  return null;
}

/* ================================================================== */
/* RobotCompanion — the public component                               */
/* Fixed full-viewport overlay; the page stays fully interactive       */
/* (only the speech bubble captures the pointer).                      */
/* ================================================================== */
export default function RobotCompanion({ mode = "free" }: { mode?: RobotMode }) {
  const [reduced, setReduced] = useState(false);
  const [compact, setCompact] = useState(false);
  const pokeRef = useRef(0);

  useEffect(() => {
    const mqR = window.matchMedia("(prefers-reduced-motion: reduce)");
    const mqC = window.matchMedia("(max-width: 640px)");
    setReduced(mqR.matches);
    setCompact(mqC.matches);
    const onR = (e: MediaQueryListEvent) => setReduced(e.matches);
    const onC = (e: MediaQueryListEvent) => setCompact(e.matches);
    mqR.addEventListener("change", onR);
    mqC.addEventListener("change", onC);
    return () => {
      mqR.removeEventListener("change", onR);
      mqC.removeEventListener("change", onC);
    };
  }, []);

  return (
    <div className="fixed inset-0 z-[45] pointer-events-none" aria-hidden="true">
      <Canvas
        dpr={[1, 1.75]}
        performance={{ min: 0.4 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={{ position: [0, 0.9, 8.5], fov: 26 }}
        style={{ pointerEvents: "none" }}
      >
        <CameraRig />

        {/* soft studio lighting — key, cool rim, warm fill */}
        <ambientLight intensity={0.6} />
        <hemisphereLight args={["#e0f2fe", "#fdf2f8", 0.6]} />
        <directionalLight position={[2.5, 4, 3]} intensity={1.4} />
        <directionalLight position={[-3, 2, -2.5]} intensity={0.8} color="#67e8f9" />
        <pointLight position={[0, 0.4, 2.2]} intensity={0.3} color="#fef3c7" />

        <Suspense fallback={null}>
          <RobotErrorBoundary>
            <RobotCharacter mode={mode} reduced={reduced} compact={compact} pokeRef={pokeRef} />
          </RobotErrorBoundary>
        </Suspense>
      </Canvas>
    </div>
  );
}




