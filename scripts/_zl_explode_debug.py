"""Debug: what does _explode_multi_answers do to MODEL_QUESTION + answers."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app.planner import _explode_multi_answers, _merge_clarification_answers

MODEL_QUESTION = (
    "I need your decision on how to proceed:\n\n"
    "1. Should I create a new inventory account (e.g. \"Inventory\" or "
    "\"Merchandise Inventory\") to record this purchase correctly? This "
    "requires your explicit approval since new accounts need owner sign-off.\n\n"
    "2. Or is there an existing account you want me to use that I may have "
    "missed?"
)

for answer in (
    "Yes",
    "Yes, use an existing account instead",
    "Yes, Create Merchandise Inventory",
    "No",
    "1) Yes, Create Inventory Account\n2) No",
):
    print(f"=== answer: {answer!r} ===")
    rows = _explode_multi_answers(
        [{"question": MODEL_QUESTION, "answer": answer}]
    )
    for i, qa in enumerate(rows):
        q = (qa.get("question") or "").replace("\n", " ")[:80]
        a = (qa.get("answer") or "").replace("\n", " ")[:60]
        print(f"  [{i}] Q={q!r}\n      A={a!r}")
    merged = _merge_clarification_answers(
        {"transaction_nature": "INVENTORY"},
        [{"question": MODEL_QUESTION, "answer": answer}],
    )
    print(f"  merged create_account={merged.get('create_account')!r}"
          f" account_name={merged.get('account_name')!r}")
    print()
