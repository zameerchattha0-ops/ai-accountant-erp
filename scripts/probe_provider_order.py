"""Print the live provider candidate order (no network calls).

Usage: python scripts/probe_provider_order.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai_orchestrator import AIOrchestrator
from app.config import get_settings


def main() -> int:
    settings = get_settings()
    orch = AIOrchestrator()
    print(f"th_text_chain  : {settings.th_text_chain_list}")
    print(f"th_thinking_off: {settings.th_thinking_off}")
    print(f"qwen_chain     : {settings.qwen_chain_list}")

    def show(label: str, **kw) -> None:
        print(f"\n{label}")
        for i, c in enumerate(orch._candidate_providers(**kw), start=1):
            print(f"  {i}. {c['provider']}/{c['model']}")

    show("default (text/tools):", requires_vision=False)
    show(
        "reasoning tier (tier_first):",
        requires_vision=False,
        text_chain=settings.accounting_reasoning_model_chain_list
        if hasattr(settings, "accounting_reasoning_model_chain_list")
        else ["qwen3-max", "qwen-max"],
        tier_first=True,
    )
    show("vision:", requires_vision=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())