"""Read-only: dump the latest production sessions + their recorded steps.

Answers: which branch produced "The AI provider did not answer in time"
(agent.py `_provider_down` gate vs planning stall), and what the reasoning
round actually recorded (rounds, status, provider_failed).
"""

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> int:
    from app.database import fetch_many

    sessions = await fetch_many(
        "ai_execution_sessions",
        filters={},
        order="updated_at.desc",
        limit=6,
        select="id,status,user_request,created_at,updated_at",
    )
    for s in sessions:
        print(
            "SESSION", str(s.get("id"))[:8], s.get("status"),
            (s.get("updated_at") or "")[:19],
            repr((s.get("user_request") or "")[:70]),
        )
        steps = await fetch_many(
            "ai_execution_steps",
            filters={"execution_session_id": str(s["id"])},
            order="created_at.asc",
            select="step_type,description,input_summary,created_at",
        )
        for st in steps:
            desc = (st.get("description") or "")[:120]
            summ = (st.get("input_summary") or "")[:400]
            print(
                "   STEP", (st.get("created_at") or "")[11:19],
                st.get("step_type"), "|", desc, "|", summ.replace("\n", " "),
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
