"""Read-only raw probe: WHY is the content empty? Captures finish_reason,
reasoning_content length and content length for a realistic prompt."""

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.config import get_settings
    from app.qwen_client import QwenClient

    s = get_settings()
    print("settings: th_text_model =", s.th_text_model, "| th_timeout =", s.th_timeout_seconds)

    client = QwenClient(
        api_key=s.th_api_key,
        base_url=s.th_base_url,
        model=s.th_text_model,
    )
    print("client max_output_tokens =", client.max_output_tokens)

    big_prompt = (
        "You are the accounting reasoning layer of an ERP. Given the request "
        "and books context, reply ONLY with the JSON decision object.\n\n"
        "USER REQUEST: Prchased Car on cash for 4000000\n\n"
        + ("CONTEXT ROW: organization=Zameer Labs PVT Ltd, currency PKR, "
           "capitalization_threshold=50000.0; chart of accounts contains "
           "1000 Cash, 1100 Accounts Receivable, 2010 Accounts Payable.\n") * 40
        + 'REPLY ONLY JSON: {"status": "PROPOSAL"}'
    )
    messages = [
        {"role": "system", "content": client._system_instructions},
        {"role": "user", "content": big_prompt},
    ]
    t0 = time.monotonic()
    resp = await client._chat_completion(messages, None)
    elapsed = time.monotonic() - t0
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    usage = resp.get("usage") or {}
    print(f"elapsed={elapsed:.2f}s finish_reason={choice.get('finish_reason')!r}")
    print(f"content len={len(msg.get('content') or '')!r}")
    print(f"reasoning_content len={len(msg.get('reasoning_content') or '')!r}")
    print(f"usage={usage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
