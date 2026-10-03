"""
ERP AI Agent — FastAPI Application
=====================================
HTTP endpoints for the AI agent.

Endpoints:
  POST /api/ai/execute         — Send a natural-language message
  POST /api/ai/clarify         — Answer a clarification question
  POST /api/ai/confirm         — Approve/reject a confirmation
  GET  /api/ai/sessions        — List recent execution sessions
  GET  /api/ai/sessions/{id}   — Get a single session with details
  GET  /api/health             — Health check
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.auth import (
    AuthContext,
    UserContext,
    authenticate_header,
    authenticate_user_header,
)
from app.config import get_settings
from app.database import fetch_many, fetch_one, insert_one, set_session_phase
from app.models.schemas import (
    AgentResponse,
    ClarificationAnswer,
    ConfirmationDecision,
    UserRequest,
)

# NOTE: `app.agent` (planner → reasoning → tools → AI providers) is
# intentionally NOT imported at module level. On serverless platforms the
# whole module graph is imported per cold start; importing the agent stack
# here pushed initialisation past the function time limit ("Worker timed
# out"). Each AI endpoint lazy-imports what it needs instead.

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    settings = get_settings()
    log.info("app.startup", env=settings.app_env, port=settings.app_port)

    # Pre-warm the AI orchestrator (Qwen primary / Gemini fallback).
    # Provider initialisation is lazy and MUST NEVER block or crash
    # startup — a broken/missing provider only degrades availability.
    try:
        from app.ai_orchestrator import get_client
        client = get_client()
        try:
            client._get_qwen()
            log.info("app.qwen_client", status="ready",
                     model=get_settings().qwen_model)
        except Exception as exc:
            log.warning("app.qwen_client_warm_failed", error=str(exc))
        try:
            client._get_gemini()
            log.info("app.gemini_client", status="ready")
        except Exception as exc:
            log.warning("app.gemini_client_warm_failed", error=str(exc))
    except Exception as exc:
        log.warning("app.ai_orchestrator_warm_failed", error=str(exc))

    # Pre-import the heavy agent stack in the BACKGROUND (never blocks
    # startup, so cold-start budgets are respected). The first user request
    # then skips the multi-second `import app.agent` — the agent starts
    # working noticeably sooner.
    def _prewarm_agent() -> None:
        try:
            import importlib

            importlib.import_module("app.agent")
            log.info("app.agent_prewarm", status="ready")
        except Exception as exc:  # noqa: BLE001 — prewarm is best-effort
            log.warning("app.agent_prewarm_failed", error=str(exc)[:200])

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _prewarm_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("app.agent_prewarm_scheduling_failed", error=str(exc))
    yield
    log.info("app.shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ERP AI Agent",
    description="AI-powered accounting & financial ERP agent",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — added at module level before any requests are served.
# Guarded: on serverless platforms (e.g. Vercel) the function cold-starts
# by importing this module for EVERY request. If required environment
# variables are missing there, Settings() would raise and crash the
# function (FUNCTION_INVOCATION_FAILED) — hiding even /api/health from
# diagnostics. Degrade to empty CORS origins instead; endpoints that
# need config will still fail loudly at request time with a clear error.
try:
    _cors_origins: List[str] = get_settings().cors_origin_list
    _config_ok: bool = True
except Exception as exc:  # pragma: no cover — misconfigured deployment
    log.error("config.settings_invalid", error=str(exc))
    _cors_origins = []
    _config_ok = False
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth dependency — supports JWT (production) and header fallback (dev)
# ---------------------------------------------------------------------------
async def get_current_user(
    auth: AuthContext = Depends(authenticate_header),
) -> AuthContext:
    """FastAPI dependency: authenticate via JWT or legacy headers.

    Returns an AuthContext with user_id, organization_id, role, and permissions.
    The organisation_id is ALWAYS resolved from the user's membership,
    never trusted from client-supplied headers alone.
    """
    return auth


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    """Liveness probe — safe to call even when the environment is misconfigured."""
    return {"status": "ok", "version": "1.0.0", "config_ok": _config_ok}


@app.get("/api/ai/warm")
async def ai_warm():
    """P2-⑭ (forensic report ⑭): cold-start mitigation hook.

    Forces the lazy heavy agent stack to import NOW so a platform warm-up
    ping (cron/monitor) pays the import cost instead of the user's first
    request. No DB, no auth (like /api/health): importing modules is
    side-effect-bounded and exposes no data. Import-graph trimming and
    provisioned concurrency stay infra follow-ups, scored once P2-⑪
    CLIENT_TTFB percentiles are queryable from SQL.
    """
    import importlib

    modules = (
        "app.agent",
        "app.accounting_reasoning",
        "app.books_evidence",
        "app.classifier",
        "app.context_manager",
        "app.plan_materialization",
        "app.reasoning",
    )
    try:
        started = time.perf_counter()
        warmed = [importlib.import_module(m) for m in modules]
        return {
            "status": "ok",
            "warmed": [m.__name__ for m in warmed],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 — warm ping must never 500
        return {"status": "error", "detail": str(exc)[:200]}


@app.post("/api/ai/client-timing")
async def ai_client_timing(
    timing: Dict[str, Any] = Body(...),
    auth: AuthContext = Depends(get_current_user),
):
    """P2-⑪: client-side TTFB (cold start happens BEFORE started_at and is
    invisible to server-side step timings). Stored as a CLIENT_TTFB step
    for SQL percentiles; best-effort — failures never surface to the UI.
    """
    from app.agent import _attach_client_ttfb  # lazy: heavy agent stack

    try:
        session_id = uuid.UUID(str(timing.get("execution_id") or ""))
        ttfb_ms = float(timing.get("ttfb_ms") or 0)
    except (ValueError, TypeError, AttributeError):
        return {"ok": False, "detail": "invalid payload"}
    ok = await _attach_client_ttfb(
        session_id=session_id,
        ttfb_ms=ttfb_ms,
        transport=str(timing.get("transport") or "unknown")[:16],
        organization_id=auth.organization_id,
    )
    return {"ok": ok}


@app.get("/api/ai/providers")
async def ai_providers(
    force: bool = False,
    auth: AuthContext = Depends(get_current_user),
):
    """AI provider health/status — is Qwen (primary) or Gemini (fallback) available?

    Never raises: each provider reports configured/available/detail
    independently, so the ERP can degrade gracefully. Results are cached
    briefly (see provider_health_ttl_seconds); pass ?force=true to refresh.

    AUTH REQUIRED: probing providers performs real round-trips to the AI
    vendors (each selecting/initialising a client), so an unauthenticated
    caller could both burn vendor quota and read the internal workspace
    endpoint. Only an authenticated org member may trigger it.
    """
    from app.ai_orchestrator import get_client

    try:
        status = await get_client().get_providers_status(force=force)
        return {"status": "ok", **status}
    except Exception as exc:  # noqa: BLE001 — status must never 500
        return {"status": "error", "detail": str(exc)[:200], "providers": {}}


@app.post("/api/ai/execute", response_model=AgentResponse)
async def ai_execute(
    request: UserRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Process a natural-language message through the AI agent."""
    from app.agent import execute  # lazy: heavy agent stack (serverless cold-start)
    # c1f3faf regression: this name was referenced WITHOUT the local import,
    # so every plain POST /api/ai/execute died with
    # ``NameError: name 'get_client' is not defined`` (bare 500) before the
    # agent ever ran.  Keep the lazy-import pattern used at lines 241/1071.
    from app.ai_orchestrator import get_client

    log.info(
        "api.execute",
        user_id=str(auth.user_id),
        org_id=str(auth.organization_id),
        role=auth.role_code,
        message_len=len(request.message),
    )

    response = await execute(
        user_message=request.message,
        user_id=auth.user_id,
        organization_id=auth.organization_id,
        auth=auth,
        conversation_id=request.conversation_id,
        attachments=request.attachments,
        # FIXED-FORMAT QUESTIONNAIRE: the provider is injected HERE (the API
        # boundary) so the agent can have the LLM author its clarification
        # questions; hermetic tests call execute() directly and stay fully
        # deterministic.
        questionnaire_client=get_client(),
    )
    return response


@app.post("/api/ai/clarify", response_model=AgentResponse)
async def ai_clarify(
    answer: ClarificationAnswer,
    auth: AuthContext = Depends(get_current_user),
):
    """Resume a session with the user's answer to a clarification."""
    from app.agent import (  # lazy: heavy agent stack (serverless cold-start)
        resume_with_clarification,
    )
    # c1f3faf regression (THE production 500): ``questionnaire_client=
    # get_client()`` below evaluated an UNDEFINED name — Python raises
    # NameError while building the keyword arguments, i.e. BEFORE
    # resume_with_clarification runs.  The user's answer was therefore never
    # recorded (clarification stayed WAITING_FOR_USER with user_response
    # NULL) and the client saw only a bare "Internal Server Error" body.
    from app.ai_orchestrator import get_client

    response = await resume_with_clarification(
        session_id=answer.session_id,
        user_answer=answer.answer,
        user_id=auth.user_id,
        organization_id=auth.organization_id,
        auth=auth,
        # FIELD-ROUTED ANSWERS from the fixed-format questionnaire: each
        # entry names the field it fills, so a reworded (LLM-authored)
        # question can never lose its answer.
        structured_answers=answer.answers,
        questionnaire_client=get_client(),
    )
    return response


@app.post("/api/ai/confirm", response_model=AgentResponse)
async def ai_confirm(
    decision: ConfirmationDecision,
    auth: AuthContext = Depends(get_current_user),
):
    """Approve or reject a pending confirmation."""
    from app.agent import (  # lazy: heavy agent stack (serverless cold-start)
        resume_with_confirmation,
    )

    response = await resume_with_confirmation(
        session_id=decision.session_id,
        approved=decision.approved,
        user_id=auth.user_id,
        organization_id=auth.organization_id,
        auth=auth,
    )
    return response


# ---------------------------------------------------------------------------
# BACKGROUND AI RUNS (DB claim/lease queue + worker process)
# ---------------------------------------------------------------------------
# POST /api/ai/jobs queues the run and returns IMMEDIATELY; a supervised
# worker process (scripts/ai_worker.py) claims and executes it via the same
# trusted execute() pipeline. Clients poll GET /api/ai/jobs/{id} or the
# existing /api/ai/progress endpoint for the live state.
# ---------------------------------------------------------------------------
@app.post("/api/ai/jobs")
async def enqueue_ai_job(
    request: UserRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Queue a natural-language AI run and return without waiting."""
    job = await insert_one(
        "ai_worker_jobs",
        data={
            "organization_id": str(auth.organization_id),
            "user_id": str(auth.user_id),
            "job_type": "ai_execute",
            "payload": {
                "message": request.message,
                "conversation_id": request.conversation_id,
                "attachments": [
                    a.model_dump(mode="json")
                    for a in (request.attachments or [])
                ],
            },
        },
    )
    log.info("api.job_queued", job_id=job["id"], user_id=str(auth.user_id))
    return {
        "queued": True,
        "job_id": job["id"],
        "conversation_id": request.conversation_id,
    }


@app.get("/api/ai/jobs/{job_id}")
async def get_ai_job(
    job_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user),
):
    """Status/result of a queued AI run (owner-scoped)."""
    job = await fetch_one(
        "ai_worker_jobs",
        filters={
            "id": str(job_id),
            "organization_id": str(auth.organization_id),
            "user_id": str(auth.user_id),
        },
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = job.get("payload") or {}
    return {
        "job_id": job["id"],
        "status": job["status"],
        "conversation_id": payload.get("conversation_id"),
        "result": job.get("result"),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
    }


# ---------------------------------------------------------------------------
# STREAMING EXECUTION (SSE)
# ---------------------------------------------------------------------------
# Same trusted execute() pipeline as POST /api/ai/execute, but the response
# streams progress: an `event: step` message for every reasoning step as it
# is recorded, and one `event: final` message with the complete
# AgentResponse once verification finished (the result card only renders on
# `final`). The non-streaming POST contract is unchanged.
# ---------------------------------------------------------------------------
@app.post("/api/ai/execute-stream")
async def ai_execute_stream(
    request: UserRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Run the agent and stream steps + the final response over SSE."""

    async def event_stream():
        # Instant ack: the progress UI starts on the very first byte —
        # before the heavy agent import and the first DB poll.
        yield (
            "event: step\n"
            + "data: "
            + json.dumps(
                {
                    "step_type": "RECEIVED",
                    "phase": "RECEIVED",
                    "status": "started",
                    "created_at": "",
                }
            )
            + "\n\n"
        )
        from app.agent import execute  # lazy: heavy agent stack (serverless cold-start)
        # c1f3faf intent ("provider injection at the API boundary"): this is
        # the PRIMARY prod path, yet it never passed a questionnaire client —
        # fresh sends always fell back to deterministic phrasing while the
        # clarify/execute endpoints injected one.  Inject the same singleton;
        # build_questionnaire_with_llm swallows provider failures, so a down
        # provider degrades to the deterministic questionnaire, never a 500.
        from app.ai_orchestrator import get_client

        run_task = asyncio.create_task(
            execute(
                user_message=request.message,
                user_id=auth.user_id,
                organization_id=auth.organization_id,
                auth=auth,
                conversation_id=request.conversation_id,
                attachments=request.attachments,
                questionnaire_client=get_client(),
            )
        )
        seen_step_ids: set[str] = set()
        session_row: Optional[Dict[str, Any]] = None
        heartbeat = 0

        while not run_task.done():
            # Resolve the session once via the conversation_id.
            if session_row is None:
                session_row = await fetch_one(
                    "ai_execution_sessions",
                    filters={"conversation_id": request.conversation_id},
                )
            if session_row is not None:
                steps = await fetch_many(
                    "ai_execution_steps",
                    filters={
                        "execution_session_id": session_row["id"],
                    },
                    order="created_at.asc",
                    limit=200,
                )
                for step in steps:
                    sid = str(step.get("id"))
                    if sid in seen_step_ids:
                        continue
                    seen_step_ids.add(sid)
                    yield (
                        "event: step\n"
                        + "data: "
                        + json.dumps(
                            {
                                "step_type": step.get("step_type"),
                                # The PHASE - not the coarse enum.  `description`
                                # holds the real phase name (INTERPRETING,
                                # PLANNING, CONTEXT_LOADING, EXECUTING, ...),
                                # which is what the progress UI maps to a label
                                # and colours.  Sending the enum (REASON/
                                # RETRIEVE) matched nothing in the UI's
                                # PHASE_ORDER, so every run displayed the
                                # fallback string "Agent working" and the
                                # pipeline stages never lit up.  This now
                                # matches /api/ai/progress exactly.
                                "phase": step.get("description") or step.get("step_type"),
                                "status": step.get("status"),
                                "created_at": str(step.get("created_at")),
                                # P2-⑪: lets the client attach its TTFB
                                # measurement to THIS session's steps.
                                "execution_id": str(session_row["id"]),
                            }
                        )
                        + "\n\n"
                    )
            # Keepalive comment every ~15 polls so proxies never time out.
            heartbeat += 1
            if heartbeat % 15 == 0:
                yield ": keepalive\n\n"
            # P2-⑬ (forensic report ⑬): 250ms poll — halves the per-run DB
            # polling load (server-side only; user-perceived step latency
            # stays well under a quarter second, invisible).
            await asyncio.sleep(0.25)

        response = await run_task
        yield (
            "event: final\n"
            + "data: "
            + response.model_dump_json()
            + "\n\n"
        )
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Reasoning progress — SAFE projection of real agent state (no chain-of-thought)
# ---------------------------------------------------------------------------
@app.get("/api/ai/progress")
async def ai_progress(
    conversation_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    """Real-time, user-safe reasoning progress for an in-flight execution.

    The frontend polls this while POST /api/ai/execute runs. It returns the
    REAL recorded execution steps from ai.execution_steps (plus tool slugs
    from ai.tool_calls) — never model prompts, raw reasoning, or hidden
    chain-of-thought. Scoping is strict: session rows must match BOTH the
    caller's organization and user.
    """
    # conversation_id is a UUID column — reject malformed ids gracefully.
    try:
        uuid.UUID(conversation_id)
    except (ValueError, AttributeError):
        return {
            "found": False,
            "current_phase": None,
            "status": None,
            "steps": [],
            "tools": [],
        }

    sessions = await fetch_many(
        "ai_execution_sessions",
        filters={
            "conversation_id": conversation_id,
            "organization_id": str(auth.organization_id),
            "user_id": str(auth.user_id),
        },
        order="created_at.desc",
        limit=1,
    )
    if not sessions:
        return {
            "found": False,
            "current_phase": None,
            "status": None,
            "steps": [],
            "tools": [],
        }

    session = sessions[0]
    session_id = session["id"]

    steps: List[Dict[str, Any]] = []
    raw_steps = await fetch_many(
        "ai_execution_steps",
        filters={"execution_session_id": session_id},
        order="created_at.asc",
        limit=50,
    )
    # Whitelisted summary keys — safe for user display.
    allowed_keys = {
        "intent",
        "extracted_entities",
        "attachments",
        "context_chars",
        "customers",
        "suppliers",
        "accounts",
        "projects",
        "documents",
        "transaction_nature",
        "confidence",
        "source",
        "question",
        "reason",
        "reason_failed",
    }
    for step in raw_steps:
        summary: Dict[str, Any] = {}
        raw_summary = step.get("input_summary")
        if isinstance(raw_summary, str) and raw_summary:
            try:
                parsed = json.loads(raw_summary)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                for key in allowed_keys:
                    if key in parsed and parsed[key] is not None:
                        summary[key] = parsed[key]
        steps.append(
            {
                "step_type": step.get("step_type"),
                "phase": step.get("description"),
                "status": step.get("status"),
                "created_at": step.get("created_at"),
                "summary": summary,
            }
        )

    # Tool calls — slugs + status only (never payloads, which may carry data).
    tool_calls = await fetch_many(
        "ai_tool_calls",
        filters={"execution_session_id": session_id},
        limit=50,
    )
    tool_slugs: List[Dict[str, Any]] = []
    if tool_calls:
        tool_rows = await fetch_many("ai_tools", filters={}, limit=200)
        slug_by_id = {t.get("id"): t.get("slug") for t in tool_rows}
        tool_slugs = [
            {
                "tool": slug_by_id.get(tc.get("tool_id")) or "unknown",
                "status": tc.get("status"),
            }
            for tc in tool_calls
        ]

    return {
        "found": True,
        "current_phase": session.get("current_phase"),
        "status": session.get("status"),
        "steps": steps,
        "tools": tool_slugs,
    }


@app.get("/api/ai/sessions")
async def list_sessions(
    limit: int = 20,
    offset: int = 0,
    auth: AuthContext = Depends(get_current_user),
):
    """List recent execution sessions for the current user."""
    sessions = await fetch_many(
        "ai_execution_sessions",
        filters={
            "organization_id": str(auth.organization_id),
            "user_id": str(auth.user_id),
        },
        order="created_at.desc",
        limit=limit,
        offset=offset,
    )
    return {"sessions": sessions, "count": len(sessions)}


# ---------------------------------------------------------------------------
# RESUME-BY-CONVERSATION — the stale-run window
# ---------------------------------------------------------------------------
# A run only ever advances while its serverless invocation is alive. When the
# host kills that invocation (FUNCTION_INVOCATION_TIMEOUT, cold-start
# eviction) nothing is left to write the terminal state, so the row stays
# PENDING / PLANNING / EXECUTING for ever. Returning such a corpse made every
# dashboard load re-attach to a dead run: an endless "Processing" spinner plus
# a poll loop that never stopped, with no user input involved at all. Rows are
# now aged out (and stamped FAILED) so a stranded run is never re-attached and
# the leak cannot accumulate either.
_ACTIVE_RUN_TTL_SECONDS = 180.0         # PENDING / PLANNING / EXECUTING
_AWAITING_USER_TTL_SECONDS = 45 * 60.0  # WAITING_FOR_USER (human latency)
_ACTIVE_RUN_STATUSES = {"PENDING", "PLANNING", "EXECUTING"}


def _row_age_seconds(row: Dict[str, Any]) -> Optional[float]:
    """Seconds since the row last moved (None when no timestamp parses).

    ``updated_at`` is maintained by the ``set_updated_at()`` trigger, so it
    tracks the last control-plane write for the session.
    """
    for key in ("updated_at", "started_at", "created_at"):
        raw = row.get(key)
        if not raw:
            continue
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - stamp).total_seconds()
    return None


async def _stamp_stranded_run(row: Dict[str, Any], age: float) -> None:
    """Close a run whose executor died, so it stops being re-attached.

    Best-effort by design: a failed write must never turn this resume
    endpoint into a 500.
    """
    session_id = row.get("id")
    if not session_id:
        return
    try:
        await set_session_phase(
            uuid.UUID(str(session_id)),
            phase="FAILED",
            status="FAILED",
            completed=True,
        )
        log.info(
            "api.latest_active.stranded_run_closed",
            session_id=str(session_id),
            status=row.get("status"),
            age_seconds=round(age, 1),
        )
    except Exception as exc:  # noqa: BLE001 — resume must stay available
        log.warning(
            "api.latest_active.stranded_run_close_failed",
            session_id=str(session_id),
            error=str(exc)[:200],
        )


@app.get("/api/ai/sessions/latest-active")
async def latest_active_session(
    auth: AuthContext = Depends(get_current_user),
):
    """resume-by-conversation.

    Returns the latest LIVE execution session for this user+org — PENDING /
    PLANNING / EXECUTING, or WAITING_FOR_USER parked on a question — so the
    frontend can reattach the progress view after a browser refresh instead of
    losing the live run. Terminal sessions (COMPLETED / FAILED / CANCELLED) are
    never returned.

    Runs that stopped moving are treated as stranded (their executor was
    killed mid-flight) and are closed rather than returned: a dead run must
    never be re-attached, because nothing will ever finish it.
    """
    sessions = await fetch_many(
        "ai_execution_sessions",
        filters={
            "organization_id": str(auth.organization_id),
            "user_id": str(auth.user_id),
        },
        order="created_at.desc",
        limit=20,
    )
    for s in sessions or []:
        status = str(s.get("status") or "").upper()
        if status not in _ACTIVE_RUN_STATUSES and status != "WAITING_FOR_USER":
            # TERMINAL — and that is a hard boundary, not just "skip this row".
            # A newer run has SETTLED, so nothing older can still be pending.
            # Falling through to an older parked session is wrong: after a
            # run COMPLETED, reattach must not walk past it and report a
            # superseded WAITING_FOR_USER row, showing "your last request is
            # still waiting for your answer" about a request already abandoned.
            break
        age = _row_age_seconds(s)
        ttl = (
            _AWAITING_USER_TTL_SECONDS
            if status == "WAITING_FOR_USER"
            else _ACTIVE_RUN_TTL_SECONDS
        )
        if age is not None and age > ttl:
            # STRANDED (executor killed mid-flight) — close it and keep
            # looking: a stranded row must never mask a genuinely live run
            # sitting behind it.
            await _stamp_stranded_run(s, age)
            continue
        return {
            "found": True,
            "session": {
                "session_id": s.get("id"),
                "conversation_id": s.get("conversation_id"),
                "status": status,
                "current_phase": s.get("current_phase"),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
                "age_seconds": round(age, 1) if age is not None else None,
            },
        }
    return {"found": False, "session": None}


@app.get("/api/ai/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user),
):
    """Get a single execution session with details."""
    session = await fetch_one(
        "ai_execution_sessions",
        filters={
            "id": str(session_id),
            "organization_id": str(auth.organization_id),
        },
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Fetch related records
    steps = await fetch_many(
        "ai_execution_steps",
        filters={"execution_session_id": str(session_id)},
        order="created_at.asc",
    )
    tool_calls = await fetch_many(
        "ai_tool_calls",
        filters={"execution_session_id": str(session_id)},
        order="created_at.asc",
    )
    clarifications = await fetch_many(
        "ai_clarifications",
        filters={"execution_session_id": str(session_id)},
        order="created_at.asc",
    )
    confirmations = await fetch_many(
        "ai_confirmations",
        filters={"execution_session_id": str(session_id)},
        order="created_at.asc",
    )

    return {
        "session": session,
        "steps": steps,
        "tool_calls": tool_calls,
        "clarifications": clarifications,
        "confirmations": confirmations,
    }


# ---------------------------------------------------------------------------
# ORGANIZATION ONBOARDING — AI-assisted first-time setup
# ---------------------------------------------------------------------------
# This runs BEFORE the user belongs to any organization (that is the whole
# point of it), so it authenticates the USER only — never an organization
# membership, which does not exist yet for a first-time signup.
#
# Nothing here writes anything.  The description is analysed against the
# LIVE backend contract (field names, defaults, validation rules, business
# types, currencies and account bundles, all read from the database at
# runtime) and the result is returned as a PROPOSAL the user reviews and
# edits.  Creating the organization still goes through the existing
# create_organization + apply_organization_onboarding RPCs, called from the
# browser with the user's own JWT — so RLS, role checks and the audit trail
# are exactly as they were.
_ONBOARDING_RL: Dict[str, deque] = defaultdict(deque)
_ONBOARDING_RL_MAX = 20
_ONBOARDING_RL_WINDOW = 300.0


@app.get("/api/onboarding/schema")
async def onboarding_schema(
    business_type: Optional[str] = None,
    auth: UserContext = Depends(authenticate_user_header),
):
    """Real backend-compatible onboarding options.

    Business types (with the chart of accounts each one produces), the
    supported currencies, the required fields and the optional account
    bundles — read from the database contract, never hard-coded, so the
    onboarding UI cannot offer a choice the backend rejects.  Passing
    ``business_type`` also returns the catalog for that business type (the
    accounts the organization will actually get).
    """
    from app.onboarding_analysis import (
        build_schema_payload,
        load_catalog,
        load_contract,
    )

    contract = await load_contract()
    catalog = await load_catalog(business_type) if business_type else None
    log.info(
        "api.onboarding_schema",
        user_id=str(auth.user_id),
        business_type=business_type,
        contract_available=bool(contract),
    )
    return build_schema_payload(contract, catalog, business_type)


@app.post("/api/onboarding/analyze")
async def onboarding_analyze(
    payload: Dict[str, Any] = Body(default={}),
    auth: UserContext = Depends(authenticate_user_header),
):
    """Turn a plain-language business description into an onboarding proposal.

    Body:
      description   — the owner's own words (required on the first call)
      business_type — the value already selected in the form, as a hint
      answers       — [{"field": ..., "answer": ...}] clarifications already given
      history       — [{"role": ..., "content": ...}] question/answer transcript

    The response reports what was understood, what was NOT stated (so it is
    never invented), the questions that must still be answered, and the
    account bundles that apply — each with its reason.  It never creates or
    finalises an organization.
    """
    key = str(auth.user_id)
    now = time.monotonic()
    bucket = _ONBOARDING_RL[key]
    while bucket and now - bucket[0] > _ONBOARDING_RL_WINDOW:
        bucket.popleft()
    if len(bucket) >= _ONBOARDING_RL_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many onboarding analyses — please wait a moment and try again.",
        )
    bucket.append(now)

    description = str(payload.get("description") or "")
    if len(description) > 4000:
        description = description[:4000]
    business_type = payload.get("business_type")
    business_type = str(business_type).strip().upper() if business_type else None
    answers = payload.get("answers") if isinstance(payload.get("answers"), list) else []
    history = payload.get("history") if isinstance(payload.get("history"), list) else []

    from app.onboarding_analysis import analyze_organization

    log.info(
        "api.onboarding_analyze",
        user_id=key,
        description_len=len(description),
        business_type_hint=business_type,
        answers=len(answers),
    )

    return await analyze_organization(
        description=description,
        business_type=business_type,
        answers=answers,
        history=history,
    )


# ---------------------------------------------------------------------------
# PUBLIC FOUNDER CHAT — marketing-site assistant (NO auth, NO DB, NO tools)
# ---------------------------------------------------------------------------
# Runs on the SAME AI orchestrator as the ERP agent, but:
#   * it has NO tools and NO database access of any kind,
#   * it answers ONLY informational questions about the AI Accountant
#     product and its founder (Zameer Haider),
#   * any request that smells like organization/financial data access is
#     refused instantly (regex guard, before the LLM is ever called).
# Used exclusively by the public welcome page. Logged-in users get the
# full in-app agent instead and never see this.
_FOUNDER_BRIEF = """\
PRODUCT — AI Accountant ("Ai Accountant", developed by Zameer Haider):
* An AI-native accounting & financial ERP for small businesses.
* Full double-entry core: sales, purchases, expenses, banking, fixed
  assets, and financial statements (P&L, balance sheet, cash flow,
  trial balance, general ledger, aging, project profitability).
* Driven by a natural-language AI agent that reasons about business
  events, asks consolidated clarifying questions, requires explicit
  confirmation for sensitive mutations, and independently verifies
  every execution against the database.
* Key modules: AI Accounting Agent, real-time financial reports,
  automated journal engine, invoicing & quotations, banking, smart
  entity search, enterprise compliance, multi-tenant security.
* Pricing: EVERY plan (Starter, Pro, Business) is free for all types
  of users. No credit card required.

FOUNDER — Zameer Haider:
* Developer and founder of AI Accountant.
* Contact: zameerchattha0@gmail.com /
  https://pk.linkedin.com/in/zameerhaiderchattha
* Built the system for the national AI hackathon demo.
"""

# Anything that looks like an organization-data / mutation request is
# refused BEFORE the model is ever called (no LLM cost, no DB touch).
_DATA_GUARD_RE = re.compile(
    r"\b("
    r"invoice|invoices|bill|bills|expense|expenses|transaction|transactions"
    r"|record |create |delete |update |post |journal|ledger|trial balance"
    r"|balance sheet|profit|loss|cash flow|customer|customers|supplier"
    r"|suppliers|vendor|payment|payments|receipt|receipts|debit|credit"
    r"|my data|our data|database|organi[sz]ation|org data|company data"
    r"|sales|purchases|revenue|payable|receivable|reconcil"
    r")\b",
    re.IGNORECASE,
)

_REFUSAL = (
    "I'm just the website guide — I can only answer informational "
    "questions about AI Accountant and its founder, Zameer Haider. "
    "For anything that touches your business data, please sign up and "
    "use the in-app AI agent — it is purpose-built, permissioned and "
    "secured for exactly that."
)

# Tiny in-memory rate limiter (per IP): 20 requests / 60 seconds.
_FOUNDER_RL: Dict[str, deque] = defaultdict(deque)
_FOUNDER_RL_MAX = 20
_FOUNDER_RL_WINDOW = 60.0


@app.post("/api/public/founder-chat")
async def founder_chat(
    payload: Dict[str, Any] = Body(default={"message": "", "history": []}),
    request: Request = None,  # type: ignore[assignment]
):
    """Public informational chat about the product and its founder.

    NEVER touches the database or tools. Data-shaped questions are
    refused instantly by the guard; everything else is answered from a
    closed knowledge brief on the same AI provider chain as the agent.
    """
    import time as _time

    client_ip = request.client.host if (request and request.client) else "unknown"
    now = _time.monotonic()
    bucket = _FOUNDER_RL[client_ip]
    while bucket and now - bucket[0] > _FOUNDER_RL_WINDOW:
        bucket.popleft()
    if len(bucket) >= _FOUNDER_RL_MAX:
        return {
            "reply": "You're sending messages a little too quickly — please wait a moment."
        }
    bucket.append(now)

    message = str(payload.get("message") or "").strip()
    history = payload.get("history") or []
    if not message:
        return {"reply": "Ask me anything about AI Accountant or its founder!"}
    if len(message) > 600:
        message = message[:600]

    # Data-shaped questions are refused instantly — never reach the model.
    if _DATA_GUARD_RE.search(message):
        return {"reply": _REFUSAL}

    transcript = ""
    for turn in history[-6:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            transcript += f"{'User' if role == 'user' else 'Assistant'}: {content[:400]}\n"

    prompt = (
        "SYSTEM BEHAVIOUR OVERRIDE — the ERP agent constitution and any "
        "accounting-agent instructions DO NOT APPLY to this request. This "
        "is a public marketing-site chat, completely separate from the ERP.\n"
        "You are \"Ledger\", the friendly assistant on the AI Accountant "
        "public website, speaking for the founder Zameer Haider.\n"
        "STRICT RULES:\n"
        "1. Answer ONLY informational questions about the AI Accountant "
        "product and its founder, using the knowledge brief below.\n"
        "2. You have NO database access and NO tools. Never claim to have "
        "read, created, changed or checked any organization's data. If "
        "asked, politely decline and suggest signing up to use the in-app "
        "AI agent.\n"
        "3. Never invent facts beyond the brief. If unsure, say so and "
        "offer the founder's email (zameerchattha0@gmail.com).\n"
        "4. Keep replies short (under ~120 words), warm, plain text, no "
        "markdown headings or bullet lists.\n\n"
        f"KNOWLEDGE BRIEF:\n{_FOUNDER_BRIEF}\n"
    )
    if transcript:
        prompt += f"CONVERSATION SO FAR:\n{transcript}\n"
    prompt += f"User: {message}\nAssistant:"

    try:
        from app.ai_orchestrator import get_client

        reply = await get_client().generate_text(prompt=prompt, context=None)
    except Exception as exc:  # noqa: BLE001 — availability must never 500
        log.warning("founder_chat.provider_failed", error=str(exc)[:200])
        reply = ""
    reply = (reply or "").strip()
    if not reply:
        reply = (
            "I couldn't reach my brain just now — please try again in a "
            "moment, or email zameerchattha0@gmail.com."
        )
    return {"reply": reply}


# ---------------------------------------------------------------------------
# CATALOGUE — products & services management (the dedicated page's API)
# ---------------------------------------------------------------------------
# Why this is an API and not a direct browser query (unlike the customers page):
# * ``product_code`` / ``service_code`` are NOT NULL and generated server-side
#   by the ``next_document_number`` RPC — a client insert would violate it;
# * the delete rule must know whether any document references the item, a
#   cross-table question the browser cannot answer safely;
# * validation, duplicate-name refusal and the "deactivate instead of delete"
#   instruction live in ONE place (the service), so the page and the agent
#   cannot disagree.
def _catalogue_error(kind: str, exc: ValueError) -> HTTPException:
    """ValueError -> 409 (a rule refused it) / 404 (absent), message preserved.

    The services raise ValueError for both cases and always carry the
    instruction the page should show, so it is passed through verbatim instead
    of being replaced by a generic error.
    """
    text = str(exc)
    status_code = 404 if "not found" in text.lower() else 409
    log.info("api.catalogue.refused", kind=kind, status=status_code,
             reason=text[:200])
    return HTTPException(status_code=status_code, detail=text)


async def _catalogue_list(table: str, auth: AuthContext, query: str, status: str):
    from app.services import catalogue_rules, product_service, service_service

    svc = product_service if table == "products" else service_service
    rows = await svc.list_catalog(auth.organization_id, query=query, status=status)
    return {
        "items": rows,
        "counts": catalogue_rules.status_counts(rows),
        "status": catalogue_rules.normalise_status(status),
    }


@app.get("/api/catalogue/products")
async def list_products(
    query: str = "",
    status: str = "ALL",
    auth: AuthContext = Depends(get_current_user),
):
    """Every product in the caller's organisation (blank ``query`` = all)."""
    return await _catalogue_list("products", auth, query, status)


@app.post("/api/catalogue/products")
async def create_product(
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Add a product. ``product_code`` is generated by the server."""
    from app.services import product_service

    if not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=409, detail="Product name is required.")
    try:
        item = await product_service.create(
            auth.organization_id,
            name=payload.get("name"),
            description=payload.get("description"),
            unit=payload.get("unit"),
            is_stock_tracked=bool(payload.get("is_stock_tracked") or False),
            unit_price=payload.get("unit_price") or 0,
            cost_price=payload.get("cost_price"),
            revenue_account_id=payload.get("revenue_account_id"),
        )
    except ValueError as exc:
        raise _catalogue_error("products", exc)
    return {"item": item, "reused": bool(item.get("reused"))}


@app.patch("/api/catalogue/products/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Edit a product. Only editable fields are accepted; the code never changes."""
    from app.services import product_service

    try:
        item = await product_service.update(
            auth.organization_id, product_id=product_id, **payload
        )
    except ValueError as exc:
        raise _catalogue_error("products", exc)
    return {"item": item}


@app.post("/api/catalogue/products/{product_id}/status")
async def set_product_status(
    product_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Activate / deactivate (soft delete — history keeps resolving the item)."""
    from app.services import product_service

    try:
        item = await product_service.set_active(
            auth.organization_id,
            product_id=product_id,
            active=bool(payload.get("active")),
        )
    except ValueError as exc:
        raise _catalogue_error("products", exc)
    return {"item": item}


@app.delete("/api/catalogue/products/{product_id}")
async def delete_product(
    product_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user),
):
    """Remove a product — refused while any document references it."""
    from app.services import product_service

    try:
        await product_service.delete(auth.organization_id, product_id=product_id)
    except ValueError as exc:
        raise _catalogue_error("products", exc)
    return {"deleted": True}




@app.get("/api/catalogue/services")
async def list_catalogue_services(
    query: str = "",
    status: str = "ALL",
    auth: AuthContext = Depends(get_current_user),
):
    """Every service in the caller's organisation (blank ``query`` = all)."""
    return await _catalogue_list("services", auth, query, status)


@app.post("/api/catalogue/services")
async def create_catalogue_service(
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Add a service. ``service_code`` is generated by the server."""
    from app.services import service_service

    if not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=409, detail="Service name is required.")
    try:
        item = await service_service.create(
            auth.organization_id,
            name=payload.get("name"),
            description=payload.get("description"),
            billing_unit=payload.get("billing_unit") or "HOUR",
            standard_rate=payload.get("standard_rate") or 0,
            cost_rate=payload.get("cost_rate"),
            revenue_account_id=payload.get("revenue_account_id"),
        )
    except ValueError as exc:
        raise _catalogue_error("services", exc)
    return {"item": item, "reused": bool(item.get("reused"))}


@app.patch("/api/catalogue/services/{service_id}")
async def update_catalogue_service(
    service_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Edit a service. Only editable fields are accepted; the code never changes."""
    from app.services import service_service

    try:
        item = await service_service.update(
            auth.organization_id, service_id=service_id, **payload
        )
    except ValueError as exc:
        raise _catalogue_error("services", exc)
    return {"item": item}


@app.post("/api/catalogue/services/{service_id}/status")
async def set_catalogue_service_status(
    service_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Activate / deactivate (soft delete — history keeps resolving the item)."""
    from app.services import service_service

    try:
        item = await service_service.set_active(
            auth.organization_id,
            service_id=service_id,
            active=bool(payload.get("active")),
        )
    except ValueError as exc:
        raise _catalogue_error("services", exc)
    return {"item": item}


@app.delete("/api/catalogue/services/{service_id}")
async def delete_catalogue_service(
    service_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user),
):
    """Remove a service — refused while any document references it."""
    from app.services import service_service

    try:
        await service_service.delete(auth.organization_id, service_id=service_id)
    except ValueError as exc:
        raise _catalogue_error("services", exc)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# FIXED ASSETS — the asset register (list / register / detail / depreciate /
# dispose).
#
# Why this is an API and not a direct browser query (unlike the customers
# page): registering an asset posts an acquisition JOURNAL, and depreciation /
# disposal post their own entries — the accounting engine is the authority, so
# every mutation goes through ``fixed_asset_service``.  The page and the AI
# agent therefore share ONE implementation, and the register's computed columns
# (accumulated depreciation, book value, status) can never disagree between the
# UI and the agent.
# ---------------------------------------------------------------------------
_FIXED_ASSET_STATUSES = (
    "ACTIVE", "FULLY_DEPRECIATED", "DISPOSED", "SOLD", "WRITTEN_OFF",
)


@app.get("/api/fixed-assets")
async def list_fixed_assets_endpoint(
    query: str = "",
    status: str = "ALL",
    auth: AuthContext = Depends(get_current_user),
):
    """The register + status counts + the accounting summary (one DB read).

    Counts and the summary cover EVERY asset (they describe the register, not
    the current filter); ``query``/``status`` narrow the returned ``items``.
    """
    from app.services import fixed_asset_service

    rows = await fixed_asset_service.list_assets(auth.organization_id)
    counts: Dict[str, int] = {"ALL": len(rows)}
    for name in _FIXED_ASSET_STATUSES:
        counts[name] = sum(1 for r in rows if str(r.get("status")) == name)

    totals = {
        "purchase_cost": 0.0,
        "accumulated_depreciation": 0.0,
        "book_value": 0.0,
    }
    for row in rows:
        cost = float(row.get("purchase_cost") or 0)
        acc = float(row.get("accumulated_depreciation") or 0)
        book = row.get("book_value")
        totals["purchase_cost"] += cost
        totals["accumulated_depreciation"] += acc
        totals["book_value"] += float(book if book is not None else cost - acc)

    wanted = (status or "ALL").strip().upper() or "ALL"
    needle = (query or "").strip().lower()
    items = [
        row
        for row in rows
        if (wanted == "ALL" or str(row.get("status")) == wanted)
        and (
            not needle
            or needle in str(row.get("name") or "").lower()
            or needle in str(row.get("asset_code") or "").lower()
        )
    ]
    return {
        "items": items,
        "counts": counts,
        "summary": {key: round(value, 2) for key, value in totals.items()},
        "status": wanted,
    }


def _optional_uuid(value: Any) -> Optional[uuid.UUID]:
    """A client-supplied id: None when blank, 409 when it is not a UUID."""
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail=f"Unknown id: {value}")


# Asset CATEGORIES — configuration only (default life / method / GL accounts).
# Declared BEFORE the /{asset_id} routes: path segments are matched in order,
# and "categories" would otherwise be parsed as a UUID and 422.
@app.get("/api/fixed-assets/categories")
async def list_fixed_asset_categories_endpoint(
    auth: AuthContext = Depends(get_current_user),
):
    """The organisation's asset categories (what the register form prefills)."""
    from app.services import fixed_asset_service

    return {"items": await fixed_asset_service.list_asset_categories(auth.organization_id)}


@app.post("/api/fixed-assets/categories", status_code=201)
async def create_fixed_asset_category_endpoint(
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Add a category (e.g. Vehicles: 5 yrs, straight line, PPE accounts)."""
    from app.services import fixed_asset_service

    try:
        item = await fixed_asset_service.create_asset_category(
            auth.organization_id,
            name=payload.get("name"),
            description=payload.get("description"),
            default_useful_life_years=payload.get("default_useful_life_years"),
            default_depreciation_method=payload.get("default_depreciation_method"),
            default_asset_account_id=_optional_uuid(
                payload.get("default_asset_account_id")
            ),
            default_depreciation_expense_account_id=_optional_uuid(
                payload.get("default_depreciation_expense_account_id")
            ),
            default_accumulated_depreciation_account_id=_optional_uuid(
                payload.get("default_accumulated_depreciation_account_id")
            ),
        )
    except ValueError as exc:
        raise _catalogue_error("asset_categories", exc)
    return {"item": item}


@app.patch("/api/fixed-assets/categories/{category_id}")
async def update_fixed_asset_category_endpoint(
    category_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Edit a category's defaults (ownership checked inside the service)."""
    from app.services import fixed_asset_service

    fields = dict(payload)
    for key in (
        "default_asset_account_id",
        "default_depreciation_expense_account_id",
        "default_accumulated_depreciation_account_id",
    ):
        if key in fields:
            parsed = _optional_uuid(fields[key])
            fields[key] = parsed.id if parsed else None
    try:
        item = await fixed_asset_service.update_asset_category(
            auth.organization_id, category_id=category_id, **fields
        )
    except ValueError as exc:
        raise _catalogue_error("asset_categories", exc)
    return {"item": item}


@app.post("/api/fixed-assets", status_code=201)
async def create_fixed_asset_endpoint(
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Register (capitalise) a fixed asset: record + acquisition journal.

    ``asset_code`` is assigned by the database trigger, never by the client.
    A credit acquisition requires a supplier (the service refuses otherwise).
    """
    from app.services import fixed_asset_service

    if not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=409, detail="Asset name is required.")

    raw_life = payload.get("useful_life_years")
    life_years: Optional[int] = None
    if str(raw_life or "").strip():
        try:
            life_years = int(float(raw_life))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=409,
                detail="Useful life must be a whole number of years.",
            )
        if life_years <= 0:
            raise HTTPException(
                status_code=409,
                detail="Useful life must be a positive number of years.",
            )

    try:
        item = await fixed_asset_service.register_asset(
            auth.organization_id,
            name=payload.get("name"),
            purchase_cost=payload.get("purchase_cost") or 0,
            transaction_date=(
                payload.get("purchase_date") or payload.get("transaction_date")
            ),
            payment_method=str(payload.get("payment_method") or "CASH").upper(),
            supplier_name=payload.get("supplier_name"),
            asset_account_id=_optional_uuid(payload.get("asset_account_id")),
            # The plan/service pin the ASSET-COST ledger by NAME too (e.g.
            # 'Building - Model Town' created first in the same run).  This
            # endpoint used to DROP the name silently, so a caller that named
            # the ledger fell back to the ambiguous keyword search and died
            # with "No fixed-asset account could be determined".
            asset_account_name=payload.get("asset_account_name"),
            useful_life_years=life_years,
            depreciation_method=str(
                payload.get("depreciation_method") or "STRAIGHT_LINE"
            ).upper(),
            salvage_value=payload.get("salvage_value") or 0,
            description=payload.get("description"),
            category_id=_optional_uuid(payload.get("category_id")),
            depreciation_expense_account_id=_optional_uuid(
                payload.get("depreciation_expense_account_id")
            ),
            accumulated_depreciation_account_id=_optional_uuid(
                payload.get("accumulated_depreciation_account_id")
            ),
            created_by=auth.user_id,
        )
    except ValueError as exc:
        raise _catalogue_error("fixed_assets", exc)
    return {"item": item}


@app.get("/api/fixed-assets/{asset_id}")
async def get_fixed_asset_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user),
):
    """One asset, organisation-scoped."""
    from app.services import fixed_asset_service

    asset = await fixed_asset_service.get(auth.organization_id, asset_id=asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Fixed asset not found.")
    return {"item": asset}


@app.post("/api/fixed-assets/{asset_id}/depreciation")
async def record_fixed_asset_depreciation_endpoint(
    asset_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Post one depreciation charge for an asset.

    With no explicit amount the service applies the asset's OWN policy
    ((cost − salvage) ÷ life ÷ 12, straight line) and never depreciates below
    salvage — the policy is configurable, never invented.
    """
    from app.services import fixed_asset_service

    raw_amount = payload.get("depreciation_amount")
    amount: Optional[float] = None
    if str(raw_amount or "").strip():
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=409, detail="Depreciation amount must be a number."
            )

    try:
        item = await fixed_asset_service.record_depreciation(
            auth.organization_id,
            asset_id=str(asset_id),
            depreciation_amount=amount,
            transaction_date=payload.get("transaction_date"),
            depreciation_expense_account_id=_optional_uuid(
                payload.get("depreciation_expense_account_id")
            ),
            accumulated_depreciation_account_id=_optional_uuid(
                payload.get("accumulated_depreciation_account_id")
            ),
        )
    except ValueError as exc:
        raise _catalogue_error("fixed_assets", exc)
    return {"item": item}


@app.post("/api/fixed-assets/{asset_id}/dispose")
async def dispose_fixed_asset_endpoint(
    asset_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Dispose of / sell / write off an asset (posts the disposal journal)."""
    from app.services import fixed_asset_service

    raw_proceeds = payload.get("disposal_amount")
    try:
        proceeds = float(raw_proceeds) if str(raw_proceeds or "").strip() else 0.0
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=409, detail="Disposal proceeds must be a number."
        )

    try:
        item = await fixed_asset_service.dispose_asset(
            auth.organization_id,
            asset_id=str(asset_id),
            disposal_amount=proceeds,
            transaction_date=payload.get("transaction_date"),
            disposal_type=str(payload.get("disposal_type") or "DISPOSAL").upper(),
        )
    except ValueError as exc:
        raise _catalogue_error("fixed_assets", exc)
    return {"item": item}


# ---------------------------------------------------------------------------
# CREDIT NOTES (sales) — proper endpoints for the Credit Note module
# (list/detail/create/status).  Journal posting happens deterministically
# inside the create TOOL (agent path); document creation here mirrors the
# UI's DRAFT-then-issue flow.
# ---------------------------------------------------------------------------
@app.get("/api/sales/credit-notes")
async def list_credit_notes_endpoint(
    query: str = "",
    status: str = "ALL",
    auth: AuthContext = Depends(get_current_user),
):
    """Every credit note in the caller's organisation (newest first)."""
    from app.repositories import credit_note_repository as cn_repo

    rows = await cn_repo.list_credit_notes(auth.organization_id)
    customers = await fetch_many(
        "customers",
        filters={"organization_id": str(auth.organization_id)},
        select="id, name",
        limit=1000,
    )
    names = {str(c.get("id")): str(c.get("name") or "") for c in customers or []}
    q = (query or "").strip().lower()
    status_up = (status or "ALL").upper()
    items = []
    for row in rows or []:
        if status_up != "ALL" and str(row.get("status") or "").upper() != status_up:
            continue
        customer_name = names.get(str(row.get("customer_id")), "")
        if q and not (
            q in str(row.get("credit_note_number") or "").lower()
            or q in customer_name.lower()
            or q in str(row.get("reason") or "").lower()
        ):
            continue
        items.append({**row, "customer_name": customer_name})
    return {"items": items, "count": len(items)}


@app.get("/api/sales/credit-notes/{credit_note_id}")
async def get_credit_note_endpoint(
    credit_note_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user),
):
    """One credit note with its line items."""
    from app.repositories import credit_note_repository as cn_repo

    note = await cn_repo.get_credit_note(
        auth.organization_id, credit_note_id=credit_note_id
    )
    if not note:
        raise HTTPException(status_code=404, detail="Credit note not found.")
    items = await cn_repo.get_credit_note_items(
        auth.organization_id, credit_note_id=credit_note_id
    )
    return {"item": {**note, "items": items}}


@app.post("/api/sales/credit-notes", status_code=201)
async def create_credit_note_endpoint(
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Create a credit note (DRAFT) with line items. Reason is mandatory."""
    from app.services import credit_note_service

    if not str(payload.get("reason") or "").strip():
        raise HTTPException(
            status_code=409, detail="A reason is required for a credit note."
        )
    if not payload.get("items"):
        raise HTTPException(
            status_code=409, detail="A credit note needs at least one line item."
        )
    if not (payload.get("customer_id") or payload.get("customer_name")):
        raise HTTPException(status_code=409, detail="A customer is required.")
    args = {
        k: payload.get(k)
        for k in (
            "customer_id", "customer_name", "items", "invoice_id",
            "reason", "credit_note_date", "currency_code",
        )
        if k in payload
    }
    try:
        note = await credit_note_service.create_credit_note(
            organization_id=auth.organization_id, **args
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"item": note}


@app.patch("/api/sales/credit-notes/{credit_note_id}")
async def update_credit_note_status_endpoint(
    credit_note_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Status-only transition (DRAFT → ISSUED → VOIDED, etc.)."""
    from app.repositories import credit_note_repository as cn_repo

    status = str(payload.get("status") or "").upper()
    if status not in ("DRAFT", "ISSUED", "VOIDED"):
        raise HTTPException(
            status_code=409,
            detail="Status must be DRAFT, ISSUED or VOIDED.",
        )
    note = await cn_repo.get_credit_note(
        auth.organization_id, credit_note_id=credit_note_id
    )
    if not note:
        raise HTTPException(status_code=404, detail="Credit note not found.")
    updated = await cn_repo.set_status(
        credit_note_id=credit_note_id, status=status
    )
    return {"item": updated}


# ---------------------------------------------------------------------------
# DEBIT NOTES (purchases) — the Debit Note module is the purchase_returns
# document (goods returned to a supplier).  Same journal discipline as the
# credit note: the reversal journal posts inside the create TOOL.
# ---------------------------------------------------------------------------
@app.get("/api/purchases/debit-notes")
async def list_debit_notes_endpoint(
    query: str = "",
    status: str = "ALL",
    auth: AuthContext = Depends(get_current_user),
):
    """Every debit note (purchase return) in the caller's organisation."""
    from app.repositories import purchase_return_repository as pr_repo

    rows = await pr_repo.list_purchase_returns(auth.organization_id)
    suppliers = await fetch_many(
        "suppliers",
        filters={"organization_id": str(auth.organization_id)},
        select="id, name",
        limit=1000,
    )
    names = {str(s.get("id")): str(s.get("name") or "") for s in suppliers or []}
    q = (query or "").strip().lower()
    status_up = (status or "ALL").upper()
    items = []
    for row in rows or []:
        if status_up != "ALL" and str(row.get("status") or "").upper() != status_up:
            continue
        supplier_name = names.get(str(row.get("supplier_id")), "")
        if q and not (
            q in str(row.get("return_number") or "").lower()
            or q in supplier_name.lower()
            or q in str(row.get("reason") or "").lower()
        ):
            continue
        items.append({**row, "supplier_name": supplier_name})
    return {"items": items, "count": len(items)}


@app.get("/api/purchases/debit-notes/{return_id}")
async def get_debit_note_endpoint(
    return_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user),
):
    """One debit note (purchase return) with its line items."""
    from app.repositories import purchase_return_repository as pr_repo

    note = await pr_repo.get_purchase_return(
        auth.organization_id, return_id=return_id
    )
    if not note:
        raise HTTPException(status_code=404, detail="Debit note not found.")
    items = await pr_repo.get_purchase_return_items(
        auth.organization_id, return_id=return_id
    )
    return {"item": {**note, "items": items}}


@app.post("/api/purchases/debit-notes", status_code=201)
async def create_debit_note_endpoint(
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Create a debit note / purchase return (DRAFT). Reason is mandatory."""
    from app.services import purchase_return_service

    if not str(payload.get("reason") or "").strip():
        raise HTTPException(
            status_code=409, detail="A reason is required for a debit note."
        )
    if not payload.get("items"):
        raise HTTPException(
            status_code=409, detail="A debit note needs at least one line item."
        )
    if not (payload.get("supplier_id") or payload.get("supplier_name")):
        raise HTTPException(status_code=409, detail="A supplier is required.")
    args = {
        k: payload.get(k)
        for k in (
            "supplier_id", "supplier_name", "items", "bill_id",
            "reason", "return_date", "currency_code",
        )
        if k in payload
    }
    try:
        note = await purchase_return_service.create_purchase_return(
            organization_id=auth.organization_id, **args
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"item": note}


@app.patch("/api/purchases/debit-notes/{return_id}")
async def update_debit_note_status_endpoint(
    return_id: uuid.UUID,
    payload: Dict[str, Any] = Body(default={}),
    auth: AuthContext = Depends(get_current_user),
):
    """Status-only transition (DRAFT → OPEN → VOIDED)."""
    from app.repositories import purchase_return_repository as pr_repo

    status = str(payload.get("status") or "").upper()
    if status not in ("DRAFT", "OPEN", "VOIDED"):
        raise HTTPException(
            status_code=409,
            detail="Status must be DRAFT, OPEN or VOIDED.",
        )
    note = await pr_repo.get_purchase_return(
        auth.organization_id, return_id=return_id
    )
    if not note:
        raise HTTPException(status_code=404, detail="Debit note not found.")
    updated = await pr_repo.set_status(return_id=return_id, status=status)
    return {"item": updated}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
    )
