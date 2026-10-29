"use client";

import { useEffect, useState } from "react";

interface NetworkInformation extends EventTarget {
  saveData?: boolean;
  effectiveType?: "slow-2g" | "2g" | "3g" | "4g";
  downlink?: number;
  rtt?: number;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
}

interface NavigatorWithPerf extends Navigator {
  deviceMemory?: number;
  connection?: NetworkInformation;
}

/**
 * Checks if client device is low-spec (budget Android, older dual-core PC, <=4GB RAM).
 */
export function isLowSpecDevice(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;

  const nav = navigator as NavigatorWithPerf;

  // 1. Hardware Concurrency (CPU cores): <= 4 cores is typical for low-end / budget mobile
  if (nav.hardwareConcurrency && nav.hardwareConcurrency <= 4) {
    return true;
  }

  // 2. Device Memory (RAM in GB): <= 4GB indicates budget / entry device
  if (nav.deviceMemory && nav.deviceMemory <= 4) {
    return true;
  }

  // 3. User explicit preference for reduced motion
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return true;
  }

  return false;
}

/**
 * Checks if network is constrained (2G, 3G, high RTT, or user enabled Save-Data).
 */
export function isSlowNetwork(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;

  const nav = navigator as NavigatorWithPerf;
  const conn = nav.connection;
  if (!conn) return false;

  if (conn.saveData) return true;
  if (conn.effectiveType === "slow-2g" || conn.effectiveType === "2g" || conn.effectiveType === "3g") {
    return true;
  }
  if (conn.rtt && conn.rtt >= 400) {
    return true;
  }

  return false;
}

/**
 * Hook to reactively adapt UI complexity, animations, and polling frequency.
 */
export function useDeviceTier() {
  const [tier, setTier] = useState(() => ({
    isLowSpec: false,
    isSlowNetwork: false,
    isSaveData: false,
    shouldReduceEffects: false,
  }));

  useEffect(() => {
    const evaluate = () => {
      const lowSpec = isLowSpecDevice();
      const slowNet = isSlowNetwork();
      const nav = navigator as NavigatorWithPerf;
      const saveData = Boolean(nav.connection?.saveData);
      const reduced = lowSpec || slowNet || saveData;

      setTier({
        isLowSpec: lowSpec,
        isSlowNetwork: slowNet,
        isSaveData: saveData,
        shouldReduceEffects: reduced,
      });

      // Synchronize dataset flag on <html> for CSS styling
      if (document.documentElement) {
        if (reduced) {
          document.documentElement.dataset.lowPerf = "true";
        } else {
          delete document.documentElement.dataset.lowPerf;
        }

        if (saveData) {
          document.documentElement.dataset.saveData = "true";
        } else {
          delete document.documentElement.dataset.saveData;
        }
      }
    };

    evaluate();

    const nav = navigator as NavigatorWithPerf;
    const conn = nav.connection;
    if (conn && conn.addEventListener) {
      conn.addEventListener("change", evaluate);
      return () => conn.removeEventListener("change", evaluate);
    }
  }, []);

  return tier;
}

