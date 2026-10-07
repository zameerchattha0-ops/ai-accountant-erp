"""Reproduce: why the Zameer Labs approval did not set create_account."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app.planner import _explode_multi_answers, _merge_clarification_answers

# Exact rows from ai.clarifications (session afcfecae-…), Q/A pair #3.
QUESTION = (
    "I'll analyze this transaction. Let me review the key facts:\n\n"
    "- Cash purchase of 2 bikes for resale (inventory) — PKR 450,000\n"
    "- Date: 2026-10-07\n- Payment: CASH\n"
    "- Economic event: ACQUISITION (cash_bank, inventory, journal, "
    "documents affected; party_ledger NOT affected)\n\n"
    "Since this is a **cash** purchase, the supplier is informational "
    "only — no supplier ledger is required. Let me check the chart of "
    "accounts for the correct inventory account.\n"
    "Let me look at the full chart of accounts to find the appropriate "
    "inventory account.\n"
    "I've reviewed the chart of accounts. There is a material problem I "
    "need to flag before recording anything.\n\n"
    "The transaction is classified as **INVENTORY** (goods bought for "
    "resale). However, the chart of accounts contains **no inventory "
    "account** — no \"Inventory\", \"Stock\", \"Merchandise\", or "
    "\"Purchases\" account exists. The only asset accounts are Bank, Cash, "
    "Accounts Receivable, Prepaid Expenses, Computer Equipment, and "
    "Vehicle - Car. None of these is appropriate for goods held for "
    "resale.\n\n"
    "The classification instructions say: use the most appropriate "
    "EXISTING account and do NOT create new accounts (new accounts "
    "require explicit owner approval). But there is genuinely no "
    "existing account that correctly represents inventory. Posting a "
    "bike purchase for resale into \"Computer Equipment\" or \"Vehicle - "
    "Car\" would be a misclassification, and falling back to a generic "
    "expense account is explicitly prohibited.\n\n"
    "I need your decision on how to proceed:\n\n"
    "1. Should I create a new inventory account (e.g. \"Inventory\" or "
    "\"Merchandise Inventory\") to record this purchase correctly? This "
    "requires your explicit approval since new accounts need owner "
    "sign-off.\n\n"
    "2. Or is there an existing account you want me to use that I may "
    "have missed?\n\n"
    "I won't post this transaction until the correct inventory account "
    "is settled, since recording it against the wrong account would "
    "misstate your books."
)
ANSWER = "1) Yes, Create Inventory Account\n2) No"

history = [{"question": QUESTION, "answer": ANSWER}]

print("=== 1) does the RAW question satisfy the documented TEXT CONTRACT? ===")
import re

m = re.search(r"no '(.+?)' account", QUESTION)
print(f"  regex no '...' account  -> {m!r}")
print(f"  'should i create' in q  -> {'should i create' in QUESTION.lower()}")
print(f"  'no \\' in q (gap_already_asked half) -> {chr(39) in QUESTION.split('no ')[-1][:3]}")

print("\n=== 2) does _explode_multi_answers split the numbered answer? ===")
exploded = _explode_multi_answers(history)
for i, qa in enumerate(exploded):
    q = (qa.get("question") or "").replace("\n", " ")[:90]
    a = (qa.get("answer") or "").replace("\n", " ")[:60]
    print(f"  [{i}] Q={q!r}\n      A={a!r}")

print("\n=== 3) the merge the planner actually runs ===")
merged = _merge_clarification_answers({}, history)
print(f"  create_account -> {merged.get('create_account')!r}")
print(f"  account_name   -> {merged.get('account_name')!r}")
print(f"  create_parent_name -> {merged.get('create_parent_name')!r}")
print(f"  all keys -> {sorted(merged)}")

print("\n=== 4) does the planner append the tool? ===")
print(f"  entities.get('create_account') -> {merged.get('create_account')!r}")
print("  -> planner.py:1252 append of 'create_account' FIRES"
      if merged.get("create_account") else
      "  -> planner.py:1252 append of 'create_account' DOES NOT FIRE")

print("\n=== 5) control: the CANONICAL question_for_gap text ===")
from app.account_resolution import question_for_gap, gap_for_nature

gap = gap_for_nature("Inventory", "INVENTORY", "nature")
print(f"  gap_for_nature(INVENTORY) -> {gap!r}")
if gap:
    q = question_for_gap(gap)
    print(f"  canonical Q = {q!r}")
    merged2 = _merge_clarification_answers({}, [{"question": q, "answer": "Yes, create it"}])
    print(f"  merge(create_account) -> {merged2.get('create_account')!r}")
