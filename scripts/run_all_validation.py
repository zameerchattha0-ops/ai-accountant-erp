#!/usr/bin/env python3
"""Run All Validation Suites.

Executes:
1. Unit Tests (Strict Matching, Treatment Review Budget, Sandboxing, Core Invariants)
2. Live Effectiveness Battery (28 Invariants)
3. Live Fixed Asset E2E (12 Invariants)

Fails closed: Exits with non-zero status code if any step fails.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parent.parent

def run_step(step_name: str, cmd: list[str]) -> bool:
    print(f"\n=======================================================", flush=True)
    print(f"RUNNING: {step_name}", flush=True)
    print(f"COMMAND: {' '.join(cmd)}", flush=True)
    print(f"=======================================================\n", flush=True)
    
    proc = subprocess.run(cmd, cwd=str(ERP_ROOT))
    if proc.returncode != 0:
        print(f"\n[FAILED] {step_name} exited with code {proc.returncode}\n", flush=True)
        return False
    print(f"\n[PASSED] {step_name}\n", flush=True)
    return True

def main() -> int:
    steps = [
        (
            "Targeted Unit Tests & New Invariant Pinning",
            [
                sys.executable,
                "-m",
                "pytest",
                "app/tests/test_answer_routing_and_llm_skips.py",
                "app/tests/test_single_call_questionnaire.py",
                "app/tests/test_llm_classification.py",
                "app/tests/test_accounting_service_strict_match.py",
                "app/tests/test_treatment_review_budget.py",
                "app/tests/test_founder_chat_sandbox.py",
            ],
        ),
        (
            "Live Effectiveness Battery (28 Invariants)",
            [sys.executable, "scripts/_live_effectiveness_battery.py"],
        ),
        (
            "Live Multi-turn Fixed Asset E2E (12 Invariants)",
            [sys.executable, "scripts/_live_fixed_asset_e2e.py"],
        ),
    ]

    for name, cmd in steps:
        ok = run_step(name, cmd)
        if not ok:
            print(f"\nCI/VALIDATION STOPPED: Step '{name}' did not pass.\n", flush=True)
            return 1

    print("\n=======================================================", flush=True)
    print("ALL VALIDATION SUITES PASSED (100% GREEN)", flush=True)
    print("=======================================================\n", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())

