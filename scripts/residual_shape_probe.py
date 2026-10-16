"""Phase 0 residual probe — the two remaining call SHAPES, end-to-end.

Read-only live probe (no DB, no writes).  Sends REAL production prompts at
realistic size through the real gateway (thinking OFF — the verified
discipline), then runs the REAL contract validators:

  A. CALL 1 questionnaire authoring  — app.questionnaire builds the prompt,
     validate_authored_questions (known-facts + applicable-gaps filter)
     decides survival.
  B. CALL 2 classification decision  — app.llm_classification.build_prompt
     with a realistic CandidateSet, llm_classification.validate decides.

Records finish_reason, tokens, latency, parse result and CONTRACT result —
the acceptance evidence in docs/LLM_PRIMARY_IMPLEMENTATION_PLAN.md.

Run:  python scripts/residual_shape_probe.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _client(settings):
    from app.qwen_client import QwenClient

    return QwenClient(
        api_key=settings.th_api_key,
        base_url=settings.th_base_url,
        model=settings.th_text_model,
        temperature=settings.qwen_temperature,
        max_output_tokens=900,
        timeout_seconds=90,
    )


async def _call(client, prompt: str, *, max_tokens: int) -> dict:
    started = time.monotonic()
    try:
        response = await client._chat_completion(
            [{"role": "user", "content": prompt}],
            None,
            max_output_tokens=max_tokens,
            thinking_off=True,
        )
    except Exception as exc:  # noqa: BLE001 — a probe reports, never raises
        return {"error": str(exc)[:200]}
    elapsed = time.monotonic() - started
    choice = (response.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    usage = response.get("usage") or {}
    return {
        "finish_reason": choice.get("finish_reason"),
        "content_chars": len(content),
        "completion_tokens": usage.get("completion_tokens"),
        "elapsed_s": round(elapsed, 1),
        "content": content,
    }


async def probe_questionnaire(client) -> dict:
    from app import questionnaire as qmod

    classification = SimpleNamespace(
        transaction_nature="OPERATING_EXPENSE",
        account_hint_name="Travel & Transport Expense",
        account_hint_code="6160",
    )
    missing = ["settlement_position", "transaction_date"]
    prompt = qmod._authored_questionnaire_prompt(
        user_request="23000 Paid for Travelling",
        intent="record_expense",
        missing_fields=missing,
        entities={"amount": 23000.0, "transaction_purpose": "TRAVEL"},
        history=[],
        today="2026-10-16",
        classification=classification,
    )
    raw = await _call(client, prompt, max_tokens=800)
    payload = qmod._extract_json(raw.pop("content", ""))
    kept = []
    if payload:
        kept = [
            q.field
            for q in qmod.validate_authored_questions(
                payload.get("questions"), {"amount": 23000.0,
                                           "transaction_purpose": "TRAVEL"},
                applicable=missing,
            )
        ]
    return {**raw, "prompt_chars": len(prompt), "json_ok": bool(payload),
            "contract_kept_fields": kept}


async def probe_classification(client) -> dict:
    from app.llm_classification import (
        CandidateSet,
        _extract_json,
        build_prompt,
        validate,
    )

    accounts = [
        {"id": f"a{i}", "code": str(1500 + i * 10), "name": name,
         "account_type": "ASSET"}
        for i, name in enumerate([
            "Cash on Hand", "Bank Account", "Accounts Receivable",
            "Inventory", "Vehicles", "Computer Equipment", "Office Equipment",
            "Tools & Equipment", "Buildings", "Furniture & Fixtures",
        ])
    ]
    headings = [
        {"code": "1500", "name": "Property, Plant & Equipment",
         "account_type": "ASSET"},
        {"code": "1000", "name": "Current Assets", "account_type": "ASSET"},
    ]
    candidates = CandidateSet(accounts=accounts, headings=headings)
    prompt = build_prompt(
        intent="record_purchase",
        entities={"amount": 4000000.0, "item_description": "car",
                  "payment_method": "CASH"},
        message="Prchased Car on cash for 4000000",
        nature_hint="FIXED_ASSET",
        candidates=candidates,
    )
    raw = await _call(client, prompt, max_tokens=700)
    payload = _extract_json(raw.pop("content", ""))
    decision = None
    if payload:
        v = validate(
            payload, candidates=candidates, nature_hint="FIXED_ASSET",
            entity="car",
        )
        decision = None if v is None else {
            "nature": v.transaction_nature,
            "hint_account": v.account_hint_name,
            "requires_clarification": v.requires_clarification,
            "source": v.source,
        }
    return {**raw, "prompt_chars": len(prompt), "json_ok": bool(payload),
            "contract_decision": decision}


async def main() -> int:
    from app.config import get_settings

    which = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    client = _client(get_settings())
    if which in ("q", "both"):
        print("A) questionnaire-authoring shape (CALL 1):")
        print(json.dumps(await probe_questionnaire(client), ensure_ascii=False))
    if which in ("c", "both"):
        print("\nB) classification-decision shape (CALL 2):")
        print(json.dumps(await probe_classification(client), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
