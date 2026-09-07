"""
AI Worker - DB-backed background job processor (Work Stream C)
===============================================================
A SUPERVISED process (not a FastAPI background task) that claims queued
AI runs from ``ai.worker_jobs`` (FOR UPDATE SKIP LOCKED via
``ai.claim_worker_job``) and executes them through the SAME trusted
``agent.execute()`` pipeline as the synchronous endpoint.

Usage:
    venv\\Scripts\\python scripts\\ai_worker.py            # poll forever
    venv\\Scripts\\python scripts\\ai_worker.py --once     # drain one job

Jobs are enqueued by POST /api/ai/jobs; clients poll GET /api/ai/jobs/{id}
or /api/ai/progress?conversation_id=... (the run records its steps exactly
like a synchronous run, because it IS the same pipeline).

Authorisation model: enqueueing requires a valid JWT (enforced by the
API). The worker executes with service privileges - it NEVER accepts jobs
that did not come from an authenticated user.
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog

log = structlog.get_logger(__name__)

WORKER_ID = f"ai-worker-{uuid.uuid4().hex[:8]}"
POLL_INTERVAL_SECONDS = 1.0


async def process_one(client) -> bool:
    """Claim and run one job. Returns True when a job was processed."""
    from app.agent import execute
    from app.models.schemas import AttachmentRef

    response = (
        client.schema("ai")  # the function lives in the ai schema (052)
        .rpc(
            "claim_worker_job",
            {"p_worker": WORKER_ID, "p_lease_seconds": 300},
        )
        .execute()
    )
    rows = response.data or []
    # The function RETURNS a single ai.worker_jobs row (NULL when nothing
    # is claimable), so PostgREST yields an OBJECT or null - not an array.
    # Normalise both shapes; a scalar/None simply means "no job".
    if isinstance(rows, dict):
        rows = [rows]
    if not rows or not isinstance(rows[0], dict):
        return False
    job = rows[0]
    job_id = job.get("id")
    if not job_id:
        # PostgREST represents a NULL single-composite return (nothing
        # claimable) as an object of nulls - there is no job to run.
        return False
    payload = job.get("payload") or {}
    log.info("worker.claimed", job_id=job_id, worker=WORKER_ID)

    try:
        agent_response = await execute(
            user_message=payload.get("message", ""),
            user_id=uuid.UUID(job["user_id"]),
            organization_id=uuid.UUID(job["organization_id"]),
            auth=None,  # already authenticated at enqueue time (API gate)
            conversation_id=payload.get("conversation_id"),
            attachments=[
                AttachmentRef(**a) for a in (payload.get("attachments") or [])
            ],
        )
        (
            client.schema("ai")
            .table("worker_jobs")
            .update(
                {
                    "status": "SUCCEEDED",
                    "result": agent_response.model_dump(mode="json"),
                    "error": None,
                    "lease_expires_at": None,
                }
            )
            .eq("id", job_id)
            .execute()
        )
        log.info("worker.completed", job_id=job_id,
                 status=agent_response.status.value)
    except Exception as exc:  # noqa: BLE001 - job failure is recorded, not raised
        log.error("worker.failed", job_id=job_id, error=str(exc))
        (
            client.schema("ai")
            .table("worker_jobs")
            .update(
                {
                    "status": "FAILED",
                    "error": str(exc)[:2000],
                    "lease_expires_at": None,
                }
            )
            .eq("id", job_id)
            .execute()
        )
    return True


async def main(once: bool = False) -> None:
    from app.database import get_service_client

    client = get_service_client()
    log.info("worker.started", worker=WORKER_ID)
    while True:
        try:
            processed = await process_one(client)
        except Exception as exc:  # noqa: BLE001 - the worker must survive
            # A malformed claim/row must never kill the supervised loop;
            # the job's lease lapses and it is re-claimed automatically.
            log.error("worker.loop_error", error=str(exc))
            processed = False
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        if once and processed:
            break
        if not processed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        if once:
            break


if __name__ == "__main__":
    asyncio.run(main(once="--once" in sys.argv))
