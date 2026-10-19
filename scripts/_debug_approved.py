"""Debug: run the approved-plan test world directly and dump everything."""
import asyncio
import sys
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "tests"))

from _pytest.monkeypatch import MonkeyPatch  # noqa: E402

import test_approved_plan_short_circuit as T  # noqa: E402


async def main() -> None:
    mp = MonkeyPatch()
    try:
        rec = T._approved_world(mp, planner_clarification=True)
        resp = await T.resume_with_confirmation(
            session_id=uuid.UUID(rec["session"]["id"]),
            approved=True,
            user_id=T.USER,
            organization_id=T.ORG,
        )
        print("STATUS:", resp.status)
        print("SUMMARY:", getattr(resp, "summary", None))
        print("ERROR:", getattr(resp, "error", None))
        print("STEPS:")
        for s in rec["steps"]:
            print("   ", s[1], "|", str(s[2])[:180] if len(s) > 2 else "")
        print("TOOL RUNS:", rec.get("tool_runs"))
        print("CLARIFICATIONS:", len(rec.get("clarifications") or []))
    finally:
        mp.undo()


if __name__ == "__main__":
    asyncio.run(main())
