"""Replay production round-4 history of the building session through plan().

Session 63126a1d (2026-10-01): the merged entities LOST useful_life_years /
depreciation_method / salvage_value that round 3 had, so the planner re-asked
them.  This probe replays the exact clarification rows (same order as
get_clarification_history: created_at asc) and prints what plan() produces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx


def _show(exc_type, exc, tb):
    import traceback

    traceback.print_exception(exc_type, exc, tb, file=sys.stdout)


sys.excepthook = _show

ERP = Path(r"e:\Qoder\Ai Accountant\ERP")
sys.path.insert(0, str(ERP))  # `python scripts\x.py` puts scripts/, not the repo root, on sys.path
env = {}
for line in (ERP / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

KEY = env["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept-Profile": "ai"}

SESSION = sys.argv[1] if len(sys.argv) > 1 else "63126a1d-3994-4398-b706-1c896c7d2877"
MESSAGE = "I purchase a Building of 5,000,000 on Cash, Yesterday"

rows = httpx.get(
    f"{env['SUPABASE_URL']}/rest/v1/clarifications",
    headers=HEADERS,
    params={
        "select": "question,user_response,required_information,status,created_at",
        "execution_session_id": f"eq.{SESSION}",
        "order": "created_at.asc",
        "limit": "40",
    },
    timeout=30,
).json()
assert isinstance(rows, list), json.dumps(rows)[:300]

history = [
    {
        "question": str(r.get("question") or ""),
        "answer": str(r.get("user_response") or ""),
        "required_information": list(r.get("required_information") or []),
    }
    for r in rows
    if r.get("user_response")
]
# Only the rows that existed BEFORE this round's own question (last row).
history = history[:-1]

from app.planner import _merge_clarification_answers, plan  # noqa: E402

print(f"session={SESSION}  history rows={len(history)}")
for i, qa in enumerate(history, 1):
    print(f"  {i}. Q: {qa['question'][:90]!r}  A: {qa['answer'][:60]!r}")

p = plan(MESSAGE, clarification_history=history)
print("\nintent:", p.intent)
print("missing_fields:", p.missing_fields)
ents = p.extracted_entities
for k in (
    "transaction_nature",
    "useful_life_years",
    "depreciation_method",
    "salvage_value",
    "asset_name",
    "amount",
    "payment_method",
    "transaction_date",
):
    print(f"  {k} = {ents.get(k)!r}")

# Also show what the merge alone does, step by step.
from app.planner import _explode_multi_answers, _resolve_same_answers  # noqa: E402

print("\n-- exploded pairs the merge iterates --")
for i, qa in enumerate(_explode_multi_answers(_resolve_same_answers(history)), 1):
    print(f"  {i}. Q: {qa['question'][:80]!r}  A: {qa['answer'][:50]!r}")
