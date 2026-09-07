"""
ERP AI Agent - Parallel Tool Execution
=======================================
Work Stream A1: executes planned tool calls with READ-ONLY parallelism.

Contract (mirrors the tool registry in app/tools/__init__.py):
* Registered tools expose ``read_only`` in the registry.
* Independent READ-ONLY calls run CONCURRENTLY via ``asyncio.gather``.
* MUTATION tools run strictly SEQUENTIALLY and preserve their original
  relative order - accounting order matters.
* A read-only call planned AFTER a mutation always runs AFTER that
  mutation (it may legitimately read state the mutation created).
* Unknown tools are NEVER assumed read-only (safe default: sequential).
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from app.models.schemas import ToolCall
from app.tools import get_handler

log = structlog.get_logger(__name__)

# executor(tool_name, arguments) -> result_data dict
Executor = Callable[[str, dict], Awaitable[Dict[str, Any]]]


def is_read_only_tool(tool_name: str) -> bool:
    """True when the registry marks *tool_name* read-only.

    An unknown tool is treated as a MUTATION (sequential) - never as
    read-only. This is the conservative, safe default.
    """
    entry = get_handler(tool_name)
    if not entry:
        return False
    return bool(entry.get("read_only", False))


async def execute_planned_tool_calls(
    tool_calls: List[ToolCall],
    executor: Executor,
) -> List[Dict[str, Any]]:
    """Execute a batch of planned tool calls and return result_data dicts
    ALIGNED WITH *tool_calls* BY INDEX.

    Algorithm: walk the plan in order, buffering read-only calls; flush
    the buffer CONCURRENTLY (asyncio.gather) when a mutation is reached or
    at the end of the plan. Mutations execute one-by-one in plan order.

    Executor exceptions are converted to ``{"success": False, "error": ...}``
    so one failing tool never aborts its siblings (error is data, not a
    control-flow failure) - identical semantics to the previous serial
    loop, just faster.
    """
    if not tool_calls:
        return []

    results: List[Optional[Dict[str, Any]]] = [None] * len(tool_calls)

    async def _run(index: int, tc: ToolCall) -> None:
        try:
            data = await executor(tc.tool_name, tc.arguments or {})
        except Exception as exc:  # noqa: BLE001 - tool errors are data
            log.warning(
                "tool_execution.call_failed",
                tool=tc.tool_name,
                error=str(exc),
            )
            data = {"success": False, "error": str(exc)}
        if not isinstance(data, dict):
            data = {"success": True, "data": data}
        results[index] = data

    pending: List[asyncio.Task] = []

    async def _flush_buffer() -> None:
        if pending:
            await asyncio.gather(*pending)
            pending.clear()

    for i, tc in enumerate(tool_calls):
        if is_read_only_tool(tc.tool_name):
            pending.append(asyncio.ensure_future(_run(i, tc)))
        else:
            # Flush reads planned before this mutation, then run the
            # mutation itself synchronously in plan order.
            await _flush_buffer()
            await _run(i, tc)

    await _flush_buffer()
    return [r for r in results if r is not None]
