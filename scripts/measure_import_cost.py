#!/usr/bin/env python
"""P2-⑭ (forensic latency report ⑭): cold import-cost measurement.

"Measure first" — each module imports in a FRESH subprocess so the numbers
mirror a real serverless cold start (no cross-module warmth). Run from
anywhere (the script forces cwd to the ERP root):

    venv\\Scripts\\python scripts/measure_import_cost.py

How to read it: the ``import cost`` column is raw wall time minus the
python-startup baseline — those deltas are the import-graph trimming
targets. Whatever stays expensive belongs on /api/ai/warm's list so a
platform cron ping pays the cost instead of the user's first request;
provisioned concurrency remains the infra fallback, scored once the
P2-⑪ CLIENT_TTFB percentiles land in SQL (docs/LATENCY_QUERIES.sql #1).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parents[1]

# Traversal order roughly follows a cold API request's import chain:
# database → evidence/classifier/context → reasoning → agent → app.main.
MODULES = (
    "app.database",
    "app.ai_orchestrator",
    "app.books_evidence",
    "app.classifier",
    "app.context_manager",
    "app.accounting_reasoning",
    "app.plan_materialization",
    "app.reasoning",
    "app.agent",
    "app.main",
)


def _run(code: str) -> tuple[float, int, str]:
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ERP_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return (time.perf_counter() - started) * 1000, proc.returncode, proc.stderr


def main() -> int:
    baseline_ms, _, _ = _run("pass")
    print(f"python startup baseline           : {baseline_ms:8.0f} ms")
    print("-" * 78)
    worst = 0.0
    failures = 0
    for module in MODULES:
        ms, code, err = _run(f"import {module}")
        if code == 0:
            delta = ms - baseline_ms
            worst = max(worst, delta)
            print(
                f"{module:<32} {ms:8.0f} ms  "
                f"(import cost ~= {delta:6.0f} ms)  OK"
            )
        else:
            failures += 1
            first = (err or "").strip().splitlines()[-1][:90] if err else "unknown"
            print(f"{module:<32} {ms:8.0f} ms  FAIL: {first}")
    print("-" * 78)
    print(f"largest single-module import cost  ~= {worst:6.0f} ms")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
