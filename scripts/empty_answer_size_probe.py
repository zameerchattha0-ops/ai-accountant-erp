"""Read-only live probe: REALISTIC-SIZE reasoning prompt vs tiny prompt.

Replicates what run_reasoning_loop does (orchestrator.generate_text with the
configured model chain) and reports elapsed, emptiness and head/tail of the
reply — to discriminate timeout vs provider error vs empty content.
"""

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.ai_orchestrator import get_client

    client = get_client()

    # --- 1. tiny control -------------------------------------------------
    t0 = time.monotonic()
    tiny = await client.generate_text(
        prompt='Reply with exactly this JSON and nothing else: {"ok": true}'
    )
    t_tiny = time.monotonic() - t0
    print(f"TINY   {t_tiny:6.2f}s  len={len(tiny):4d}  {tiny[:120]!r}")

    # --- 2. realistic reasoning-style prompt (large, JSON-contract) ------
    big_prompt = (
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
    t0 = time.monotonic()
    try:
        big = await client.generate_text(prompt=big_prompt)
        t_big = time.monotonic() - t0
        print(f"BIG    {t_big:6.2f}s  len={len(big):4d}  head={big[:160]!r}")
        if not big.strip():
            print("BIG -> EMPTY CONTENT (finish_reason consumed by reasoning?)")
    except Exception as exc:  # noqa: BLE001 — probe reports, never raises
        t_big = time.monotonic() - t0
        print(f"BIG    {t_big:6.2f}s  EXCEPTION {type(exc).__name__}: {str(exc)[:300]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
