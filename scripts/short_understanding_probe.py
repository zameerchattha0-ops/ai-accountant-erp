"""Is a SHORT understanding call output-chars-limit safe?

The empty-answer failure (docs/EMPTY_ANSWER_ROOT_CAUSE.md) was a thinking
model whose hidden reasoning consumed the whole shared output cap:
finish_reason=length, 0 content chars.  This probe measures the SHORT
understanding call we want to rely on for nature/field reading:

  * thinking ON  (baseline)  vs  thinking OFF (the bounded path)
  * output chars, completion tokens, finish_reason, latency

Run:  python scripts/short_understanding_probe.py
"""

from __future__ import annotations

import asyncio
import json
import time

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.qwen_client import QwenClient  # noqa: E402

REQUEST = "Create an Invoice for 45000 against sale of tax servcies to Beta Traders"

PROMPT = (
    "Read the user's business request and return ONE small JSON object only.\n"
    '{"transaction_nature": one of FIXED_ASSET|INVENTORY|CONSUMABLE|SERVICE|'
    "OPERATING_EXPENSE|REVENUE|OTHER_INCOME|ASSET_DISPOSAL,\n"
    ' "item_description": the item/service named (verbatim),\n'
    ' "quantity": number or null, "amount": number or null,\n'
    ' "transaction_purpose": short purpose or null}\n'
    "Rules: copy text verbatim from the request; omit anything not stated; "
    "never invent. A misspelling is still the thing it means.\n\n"
    f"User request:\n{REQUEST}"
)


async def run(*, thinking_off: bool, max_tokens: int) -> dict:
    settings = get_settings()
    client = QwenClient(
        api_key=settings.th_api_key,
        base_url=settings.th_base_url,
        model=settings.th_text_model,
        temperature=settings.qwen_temperature,
        max_output_tokens=max_tokens,
        timeout_seconds=90,
    )
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": REQUEST},
    ]
    started = time.monotonic()
    try:
        response = await client._chat_completion(
            messages, None, max_output_tokens=max_tokens, thinking_off=thinking_off
        )
    except Exception as exc:  # noqa: BLE001 — a probe reports, never raises
        return {"thinking_off": thinking_off, "error": str(exc)[:200]}
    elapsed = time.monotonic() - started
    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    usage = response.get("usage") or {}
    return {
        "thinking_off": thinking_off,
        "max_tokens": max_tokens,
        "finish_reason": choice.get("finish_reason"),
        "content_chars": len(content),
        "completion_tokens": usage.get("completion_tokens"),
        "elapsed_s": round(elapsed, 1),
        "json_ok": isinstance(_json_or_none(content), dict),
        "head": content[:120].replace("\n", " "),
    }


def _json_or_none(text: str):
    try:
        return json.loads(text.strip().removeprefix("```json").removesuffix("```"))
    except Exception:  # noqa: BLE001
        return None


async def main() -> int:
    print(f"request: {REQUEST}\n")
    for thinking_off in (False, True):
        for max_tokens in (600,):
            result = await run(thinking_off=thinking_off, max_tokens=max_tokens)
            print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
