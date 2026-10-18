"""One-off demo (2026-10-18): catalogue-hinted nature question.

A purchase of a stock-tracked catalogue item ('office chairs' -> 'chairs')
from a SUPPLIER WITH NO HISTORY must ask the inventory-first question.
"""
import asyncio
import sys

sys.path.insert(0, r"E:\Qoder\Ai Accountant\ERP\scripts")

import _e2e_live
from _e2e_live import p, resolve_identity, run_record

_e2e_live.RECORD_MSG = (
    "Bought 2 office chairs from ALPHA TRADERS for 90000 on credit today"
)


async def main() -> None:
    ctx = await resolve_identity()
    await run_record(ctx)
    p("\n===== CATALOGUE-DEMO COMPLETE =====")


if __name__ == "__main__":
    asyncio.run(main())
