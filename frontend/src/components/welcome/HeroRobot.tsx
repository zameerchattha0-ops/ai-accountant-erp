"use client";

/* eslint-disable react-hooks/immutability */
/* Reason: three.js AnimationMixer / AnimationAction objects (via drei's
   useAnimations) are imperative WebGL-side systems, not React state.
   Mutating them — setting loops, crossfading clips — is the library's
   intended API; the immutability rule is designed for React state and
   cannot model external object graphs. */

/* ================================================================== */
/* "Ledger" — the 3D robot mascot                                      */
/*                                                                      */
/* Rendered with react-three-fiber + drei (industry-standard React 3D   */
/* stack). The character is the CC0-licensed RobotExpressive glTF       */
/* (three.js official sample by Tomás Laulhé, modified by Don McCurdy), */
/* which ships 14 baked animation clips — no hand keyframing needed.    */
/*                                                                      */
/* Behaviour state machine:                                             */
/*   entrance Wave → Idle (leans toward the visitor's cursor) →         */
/*   patrols left/right on its platform (Walking) → faces viewer →      */
/*   hover triggers a Wave · click triggers Dance (hero) / ThumbsUp     */
/*   (auth cards). Falls back to a calm Idle under prefers-reduced-     */
/*   motion and pauses rendering when the tab is hidden.                */
/* ================================================================== */

import { Suspense, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame } from "@react-three/fiber";
import { ContactShadows, useAnimations, useGLTF } from "@react-three/drei";

type RobotVariant = "hero" | "compact";
type Phase = "wave" | "idle" | "walk" | "dance" | "thumbsup";

const MODEL_URL = "/models/RobotExpressive.glb";

/* One-shot clips that automatically hand control back to Idle when done */
const ONESHOT = new Set(["Wave", "Dance", "ThumbsUp", "Yes", "No", "Jump"]);

function RobotModel({ variant, reduced }: { variant: RobotVariant; reduced: boolean }) {
  const group = useRef<THREE.Group>(null);
  const { scene, animations } = useGLTF(MODEL_URL);
  const { actions, mixer } = useAnimations(animations, group);

  const phase = useRef<Phase>("wave");
  const timer = useRef(0);
  const dir = useRef(1);
  const patrol = variant === "hero" && !reduced;
  const WALK_TIME = 2.1;
  const RANGE = 0.42;
  const SPEED = 0.38;

  /* Crossfade helper — fades out whatever is playing, fades the next clip in */
  const play = (name: string, once: boolean) => {
    const next = actions[name] ?? actions["Idle"];
    if (!next) return;
    Object.entries(actions).forEach(([key, action]) => {
      if (action && key !== next.getClip().name) action.fadeOut(0.35);
    });
    next.reset();
    next.setLoop(once ? THREE.LoopOnce : THREE.LoopRepeat, once ? 1 : Infinity);
    next.clampWhenFinished = once;
    next.timeScale = variant === "compact" ? 0.9 : 1;
    next.fadeIn(0.35).play();
  };

  const enterIdle = (dwell: number) => {
    phase.current = "idle";
    timer.current = dwell;
    play("Idle", false);
  };

  useEffect(() => {
    /* Robots cast soft shadows on the glass platform */
    scene.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        obj.castShadow = true;
      }
    });

    const onFinished = (e: { action?: THREE.AnimationAction }) => {
      const clipName = e.action?.getClip().name;
      if (clipName && ONESHOT.has(clipName)) enterIdle(1.6 + Math.random() * 1.6);
    };
    mixer.addEventListener("finished", onFinished as (e: THREE.Event) => void);

    if (reduced) {
      /* Calm static loop for reduced-motion users — no entrance, no patrol */
      play("Idle", false);
      phase.current = "idle";
    } else {
      /* Entrance: a friendly wave, then settle into idle */
      phase.current = "wave";
      play("Wave", true);
    }

    return () => {
      mixer.removeEventListener("finished", onFinished as (e: THREE.Event) => void);
      mixer.stopAllAction();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, actions, mixer, reduced]);

  useFrame((state, rawDelta) => {
    const g = group.current;
    if (!g) return;
    const delta = Math.min(rawDelta, 0.05); // clamp tab-switch jumps
    timer.current -= delta;

    if (phase.current === "idle" && timer.current <= 0 && patrol) {
      /* Set off on patrol — walk to the other side of the platform */
      dir.current *= -1;
      phase.current = "walk";
      timer.current = WALK_TIME;
      play("Walking", false);
    }

    if (phase.current === "walk") {
      g.position.x = THREE.MathUtils.clamp(
        g.position.x + dir.current * SPEED * delta,
        -RANGE,
        RANGE,
      );
      /* Face the direction of travel */
      const targetYaw = dir.current > 0 ? Math.PI / 2.4 : -Math.PI / 2.4;
      g.rotation.y = THREE.MathUtils.lerp(g.rotation.y, targetYaw, delta * 6);
      if (timer.current <= 0) {
        enterIdle(2.2 + Math.random() * 2.4);
      }
    } else {
      /* Face the viewer, then lean toward the visitor's cursor */
      const pointerYaw = reduced ? 0 : state.pointer.x * 0.45;
      g.rotation.y = THREE.MathUtils.lerp(g.rotation.y, pointerYaw, delta * 4);
      /* Gentle idle bob (suppressed for reduced motion) */
      if (!reduced) {
        g.position.y = Math.sin(state.clock.elapsedTime * 1.6) * 0.015;
      }
    }
  });

  const hoverGreet = () => {
    if (reduced || phase.current !== "idle") return;
    phase.current = "wave";
    play("Wave", true);
  };

  const interact = () => {
    if (reduced || (phase.current !== "idle" && phase.current !== "wave")) return;
    if (variant === "hero") {
      phase.current = "dance";
      play("Dance", true);
    } else {
      phase.current = "thumbsup";
      play("ThumbsUp", true);
    }
  };

  return (
    <group
      ref={group}
      scale={variant === "hero" ? 0.5 : 0.42}
      onPointerOver={hoverGreet}
      onClick={interact}
    >
      <primitive object={scene} />
    </group>
  );
}

useGLTF.preload(MODEL_URL);

/* ================================================================== */
/* Stage — glass platform + lighting rig + canvas                      */
/* ================================================================== */
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
      {/* Frosted glass stage the robot stands on */}
      <div className="absolute inset-0 rounded-[2rem] border border-white/70 bg-gradient-to-b from-white/60 via-white/30 to-white/10 shadow-xl shadow-indigo-500/10 backdrop-blur-md overflow-hidden" />

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
          dpr={[1, 1.75]}
          performance={{ min: 0.5 }}
          gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
          camera={{ position: [0, 1.05, 2.5], fov: 42 }}
          onCreated={({ camera }) => camera.lookAt(0, 0.82, 0)}
        >
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
            {/* Glass platform disc + teal rim */}
            <mesh rotation-x={-Math.PI / 2} position={[0, 0, 0]}>
              <circleGeometry args={[variant === "hero" ? 1.0 : 0.85, 64]} />
              <meshPhysicalMaterial
                color="#bae6fd"
                transparent
                opacity={0.28}
                roughness={0.18}
                metalness={0.12}
                clearcoat={0.8}
              />
            </mesh>
            <mesh rotation-x={-Math.PI / 2} position={[0, -0.002, 0]}>
              <ringGeometry args={[variant === "hero" ? 0.97 : 0.82, variant === "hero" ? 1.02 : 0.87, 64]} />
              <meshBasicMaterial color="#67e8f9" transparent opacity={0.35} />
            </mesh>

            <RobotModel variant={variant} reduced={reduced} />

            <ContactShadows
              position={[0, 0.005, 0]}
              opacity={0.32}
              scale={4}
              blur={2.4}
              far={1.6}
              color="#1e3a5f"
            />
          </Suspense>
        </Canvas>
      </div>
    </div>
  );
}
