"""Decisive probe: the EXACT failing prompt shape + thinking-toggle knobs.

1. Baseline call (thinking ON, default payload) on the production-size prompt
   -> capture finish_reason + content length (expect: empty content).
2. Same prompt with each candidate thinking-OFF knob, to learn which the
   gateway honours (so the fix is measured, not guessed).
"""

import asyncio
import sys
import time

sys.path.insert(0, ".")


def _big_prompt() -> str:
    return (
        "You are the accounting reasoning layer of an ERP. Given the request "
        "and books context, reply ONLY with the JSON decision object.\n\n"
        "USER REQUEST: Prchased Car on cash for 4000000\n\n"
        "FACTS: {'amount': 4000000.0, 'payment_method': 'CASH', "
        "'transaction_nature': 'FIXED_ASSET', 'create_account': 'Vehicles', "
        "'create_parent_name': 'Accounts Receivable'}\n\n"
        + ("CONTEXT ROW: organization=Zameer Labs PVT Ltd, currency PKR, "
           "capitalization_threshold=50000.0; chart of accounts contains "
           "1000 Cash, 1100 Accounts Receivable, 2010 Accounts Payable, "
           "1500 Computer Equipment and party sub-ledgers 1100-0001..0006.\n"
           ) * 40
        + 'REPLY WITH ONLY THIS JSON: {"status": "...", "understanding": '
        '{"economic_event": "...", "what_user_wants": "...", "basis": "...", '
        '"event_type": "new_event"}, "proposal": null, "refusal": null, '
        '"complete": false, "question": null}'
    )


async def _one(client, label: str, extra: dict) -> None:
    import httpx

    messages = [
        {"role": "system", "content": client._system_instructions},
        {"role": "user", "content": _big_prompt()},
    ]
    payload = client._payload(messages, None, None)
    payload.update(extra)
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
            r = await c.post(
                f"{client.base_url}/chat/completions",
                headers=client._headers(),
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] TRANSPORT {type(exc).__name__}: {str(exc)[:160]}")
        return
    elapsed = time.monotonic() - t0
    if r.status_code != 200:
        print(f"[{label}] HTTP {r.status_code} in {elapsed:.1f}s: {r.text[:220]}")
        return
    body = r.json()
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    usage = body.get("usage") or {}
    print(
        f"[{label}] {elapsed:5.1f}s finish={choice.get('finish_reason')!r} "
        f"content={len(content)}ch reasoning={len(reasoning)}ch "
        f"completion_tokens={usage.get('completion_tokens')} "
        f"head={content[:70]!r}"
    )


async def main() -> int:
    from app.config import get_settings
    from app.qwen_client import QwenClient

    s = get_settings()
    client = QwenClient(
        api_key=s.th_api_key, base_url=s.th_base_url, model=s.th_text_model
    )
    print("model:", s.th_text_model, "| client cap:", client.max_output_tokens)

    await _one(client, "baseline(thinking ON)", {})
    await _one(client, "enable_thinking=false", {"enable_thinking": False})
    await _one(client, "reasoning_effort=none", {"reasoning_effort": "none"})
    await _one(client, "thinking disabled obj", {"thinking": {"type": "disabled"}})
    await _one(client, "cap 8192 thinking ON", {"max_tokens": 8192})
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
