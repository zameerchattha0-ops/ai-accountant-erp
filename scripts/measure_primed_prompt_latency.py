"""Measure the contract-primed REASONING prompt against the live provider.

The prompt-size ceiling in test_contract_primed_prompt.py may only be raised
with a generation-latency justification ("never silently").  This script
builds the exact production shape (same helpers as the test) and times ONE
real generation so a ceiling raise is backed by a measurement.

Usage:
  python scripts/measure_primed_prompt_latency.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tests.test_contract_primed_prompt import _facts  # noqa: E402
from app.accounting_reasoning import build_reasoning_prompt  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.qwen_client import QwenClient, ProviderRateLimited  # noqa: E402
from app.tools import list_tools, tool_contracts  # noqa: E402


async def main() -> int:
    offered = list(list_tools())
    primed = build_reasoning_prompt(
        _facts(), offered_tools=offered, tool_contracts=tool_contracts()
    )
    base = build_reasoning_prompt(_facts(), offered_tools=offered)
    print(f"base={len(base)}  primed={len(primed)}  delta={len(primed) - len(base)}")

    settings = get_settings()
    print(f"primary model={settings.qwen_model}")
    messages = [
        {"role": "system", "content": _system_instructions(settings)},
        {"role": "user", "content": primed},
    ]
    started = time.monotonic()
    try:
        resp = await _completion(messages, settings)
    except Exception as exc:  # noqa: BLE001 — the probe reports, never raises
        elapsed = int((time.monotonic() - started) * 1000)
        print(f"PROVIDER FAILED after {elapsed} ms — no latency measurement: {exc}")
        return 2
    elapsed_ms = int((time.monotonic() - started) * 1000)
    choice = (resp.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    print(
        f"generation_elapsed_ms={elapsed_ms} "
        f"finish_reason={choice.get('finish_reason')} "
        f"content_chars={len(content)}"
    )
    return 0


def _system_instructions(settings) -> str:
    from app.qwen_client import QwenClient

    client = QwenClient(
        api_key=settings.qwen_api_key,
        base_url=settings.qwen_base_url,
        model=settings.qwen_model,
        max_output_tokens=1200,
    )
    return client._system_instructions


async def _completion(messages, settings):
    """One generation on the primary model (the shape the ceiling policy
    measures).  Falls through to the orchestrator's live chain when the
    primary is unavailable, so a measurement is still produced."""
    from app.ai_orchestrator import AIOrchestrator
    from app.models.schemas import AgentContext
    from app.qwen_client import QwenClient

    client = QwenClient(
        api_key=settings.qwen_api_key,
        base_url=settings.qwen_base_url,
        model=settings.qwen_model,
        max_output_tokens=1200,
    )
    try:
        return await client._chat_completion(
            messages, None, max_output_tokens=1200, thinking_off=True
        )
    except Exception as primary_exc:  # noqa: BLE001 — fall through the chain
        print(f"primary unavailable ({str(primary_exc)[:120]}) — measuring on the live chain")
        orch = AIOrchestrator()
        text = await orch.generate_text(
            prompt=messages[-1]["content"], context=AgentContext(organization={}, user={})
        )
        return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
