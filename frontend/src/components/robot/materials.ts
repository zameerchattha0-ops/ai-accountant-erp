"use client";

/* ================================================================== */
/* Shared materials for "Ledger" — palette extracted from the          */
/* approved reference render (ERP/Robot.png): glossy white shell,      */
/* deep-teal accents, dark glass visor, glowing cyan face/eyes.        */
/* Created once per component instance; never re-created on re-render. */
/* ================================================================== */

import { useMemo } from "react";
import * as THREE from "three";

export const PALETTE = {
  shell: "#f2f6f7",
  teal: "#0e5e5e",
  joint: "#0c4750",
  visor: "#0a1116",
  eyeCyan: "#45d4ff",
  glowCyan: "#35c8f5",
  tablet: "#a9b2ba",
  screen: "#152730",
} as const;

export function useRobotMaterials() {
  return useMemo(
    () => ({
      shell: new THREE.MeshStandardMaterial({
        color: PALETTE.shell, roughness: 0.22, metalness: 0.05,
      }),
      teal: new THREE.MeshStandardMaterial({
        color: PALETTE.teal, roughness: 0.3, metalness: 0.1,
      }),
      joint: new THREE.MeshStandardMaterial({
        color: PALETTE.joint, roughness: 0.42, metalness: 0.15,
      }),
      visor: new THREE.MeshPhysicalMaterial({
        color: PALETTE.visor, roughness: 0.08, metalness: 0.35,
        clearcoat: 1, clearcoatRoughness: 0.08,
      }),
      eye: new THREE.MeshStandardMaterial({
        color: "#08131c",
        emissive: new THREE.Color(PALETTE.eyeCyan),
        emissiveIntensity: 2.6, roughness: 0.25,
      }),
      ring: new THREE.MeshStandardMaterial({
        color: "#07222b",
        emissive: new THREE.Color(PALETTE.glowCyan),
        emissiveIntensity: 1.8, roughness: 0.3,
      }),
      tablet: new THREE.MeshStandardMaterial({
        color: PALETTE.tablet, roughness: 0.32, metalness: 0.55,
      }),
      screen: new THREE.MeshStandardMaterial({
        color: PALETTE.screen, roughness: 0.15, metalness: 0.4,
        emissive: new THREE.Color("#1d3a4a"), emissiveIntensity: 0.5,
      }),
    }),
    [],
  );
}
