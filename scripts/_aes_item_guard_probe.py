"""Sanity probe for the two item-source guards (2026-10-07)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.planner import _extract_item

CASES = [
    # --- fix 1: purchase verb, source side is never the item ---
    ("bought from Dell", None),
    ("purchased from Dell", None),
    ("procured 5 laptops from Dell", "laptops"),
    # --- fix 2: sale verb, the customer side is never the item ---
    ("Sold to Murkez Technologies pvt Limited", None),
    ("sold to Zameer Labs", None),
    ("sold chairs to Alpha Associates", "chairs"),
    # --- regressions: normal items still extract (incl. trailing 's' at EOS) ---
    ("bought chairs", "chairs"),
    ("purchased a chair from Dell", "chair"),
    ("sale of two motorbikes for 367,000", "two motorbikes"),
    ("supply of cement to Khan Traders", "cement"),
    ("purchase of laptops from Dell", "laptops"),
    ("sold 2 ovens to ljk pvt limited", "ovens"),
]

failed = 0
for msg, expected in CASES:
    got = _extract_item(msg)
    status = "OK " if got == expected else "FAIL"
    if got != expected:
        failed += 1
    print(f"{status} {msg!r:60} -> {got!r} (expected {expected!r})")

print(f"\n{failed} failure(s)")
raise SystemExit(1 if failed else 0)
