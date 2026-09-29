"""Debug: what does the provider actually return for a tiny prompt?"""

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> int:
    from app.ai_orchestrator import get_client

    client = get_client()
    reply = await client.generate_text(
        prompt="Reply with exactly this JSON and nothing else: {\"ok\": true}"
    )
    print("TYPE:", type(reply).__name__)
    print("REPR:", repr(reply)[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
