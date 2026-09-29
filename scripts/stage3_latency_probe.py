"""Stage 3 §27 — one LIVE two-call run to record the real latency baseline.

Prints call_1_ms / python_ms / call_2_ms / total_ms exactly as the runtime
measured them.  Read-only request; the runtime cannot execute anything.
"""

import asyncio
import json
import sys
import uuid

sys.path.insert(0, ".")


async def main() -> int:
    from app.ai_orchestrator import get_client
    from app.two_call_runtime import run_two_call_runtime

    outcome = await run_two_call_runtime(
        user_request=(
            "record the credit purchase of 3 Dell laptops for 450,000 "
            "from FDS Labs Pvt"
        ),
        organization_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
        orchestrator=get_client(),
    )
    print(json.dumps({
        "status": outcome.status,
        "reason": outcome.reason,
        "call_1_ms": outcome.timings.get("call_1_ms"),
        "python_acquisition_ms": outcome.timings.get("python_ms"),
        "call_2_ms": outcome.timings.get("call_2_ms"),
        "total_ms": outcome.timings.get("total_ms"),
        "intent": (outcome.candidate or {}).get("intent"),
        "violations": outcome.violations[:4],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
