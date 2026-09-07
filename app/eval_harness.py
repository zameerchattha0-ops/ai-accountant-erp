"""
ERP AI Agent - Evaluation Harness (Work Stream K)
==================================================
Replays a golden set of real-shaped requests through the deterministic
planner (NO LLM, no live data outside the request text) and asserts the
outcomes recorded in ``tests/golden/*.json``:

* expected intent
* expected entity subset (exact values for the listed keys)
* expected batch document count
* requires_clarification flag and required missing-field members

The golden files were seeded from the VERIFIED behavior of the suite
(490 passing tests at seed time).  Any future prompt/model/planner
change can be validated against them: a changed outcome is a visible,
reviewable diff - never a silent behavior drift.

Usage:
    venv\\Scripts\\python scripts\\eval_harness.py          # run, print pass-rate
    venv\\Scripts\\python scripts\\eval_harness.py --seed   # (re)write goldens
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from app.planner import plan
from app.reasoning import nature_question_for_intent

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"

DATE_Q = (
    "What is the transaction date? Reply TODAY, or the date as "
    "YYYY-MM-DD or DD/MM/YYYY (for example 2026-09-04 or 04/09/2026)."
)
# Work Stream R - the per-module nature/purpose questions (deterministic).
PURCHASE_NATURE_Q = nature_question_for_intent("record_purchase")
SALE_NATURE_Q = nature_question_for_intent("record_sale")
EXPENSE_NATURE_Q = nature_question_for_intent("record_expense")
QUOTATION_NATURE_Q = nature_question_for_intent("create_quotation")

# Seed cases: message + the CURRENT verified planner outcome.  Entity
# expectations list only the stable subset (amounts, payment methods,
# item descriptions) - party-name extraction shapes are intentionally
# not frozen here.
GOLDEN_SEEDS: List[Dict[str, Any]] = [
    # Work Stream R: the Dell-laptop purchase is complete EXCEPT the
    # nature/purpose decision - the ONE question now asked (deliberate,
    # reviewed behavior change: nature is decided, never guessed).
    {"name": "cash_purchase_complete", "message": "I bought a Dell laptop for Rs.150,000 in cash yesterday.",
     "expected": {"intent": "record_cash_purchase", "requires_clarification": True,
                   "missing_includes": ["transaction_nature"],
                   "question_includes": ["fixed asset"],
                   "entities": {"amount": 150000.0, "payment_method": "CASH"}}},
    {"name": "mutation_without_date_asks", "message": "bought a chair for Rs.5,000",
     "expected": {"intent": "record_purchase", "requires_clarification": True,
                   "missing_includes": ["transaction_date", "transaction_nature"],
                   "entities": {"amount": 5000.0}}},
    {"name": "generic_expense", "message": "record expense: internet Rs.5,000",
     "expected": {"intent": "record_expense", "missing_includes": ["transaction_date", "transaction_purpose", "settlement_position"],
                   "question_includes": ["what is this expense for"],
                   "question_excludes": ["nature of this expense"],
                   "entities": {"amount": 5000.0}}},
    {"name": "trial_balance_report", "message": "show me the trial balance",
     "expected": {"intent": "generate_trial_balance", "requires_clarification": False}},
    {"name": "balance_sheet_report", "message": "generate the balance sheet",
     "expected": {"intent": "generate_balance_sheet", "requires_clarification": False}},
    {"name": "bank_transfer", "message": "transfer Rs.50,000 from HBL to Meezan",
     "expected": {"intent": "record_bank_transfer",
                   "missing_includes": ["transaction_date"],
                   "entities": {"amount": 50000.0}}},
    {"name": "receipt_intent", "message": "received payment of Rs.20,000 from the customer",
     "expected": {"intent": "record_receipt", "missing_includes": ["transaction_date", "transaction_nature", "payment_type"],
                   "question_includes": ["business operation"],
                   "entities": {"amount": 20000.0}}},
    {"name": "invoice_intent", "message": "create an invoice for Rs.30,000",
     "expected": {"intent": "create_invoice", "missing_includes": ["transaction_date", "transaction_nature"],
                   "entities": {"amount": 30000.0}}},
    {"name": "credit_note_intent", "message": "issue a credit note for the damaged goods",
     "expected": {"intent": "create_credit_note",
                   "missing_includes": ["transaction_nature"],
                   "question_includes": ["return of goods"]}},
    {"name": "purchase_return_intent", "message": "purchase return to the supplier",
     "expected": {"intent": "create_purchase_return",
                   "missing_includes": ["transaction_nature"]}},
    {"name": "fixed_asset_registration", "message": "register a new fixed asset generator for Rs.850,000",
     "expected": {"intent": "register_fixed_asset", "missing_includes": ["asset_name"],
                   "question_excludes": ["nature"],
                   "entities": {"amount": 850000.0}}},
    {"name": "depreciation_only_date_missing", "message": "Record depreciation for Office Laptop",
     "expected": {"intent": "record_asset_depreciation",
                   "missing_fields": ["transaction_date"]}},
    {"name": "supplier_payment_intent", "message": "paid the supplier Rs.12,000",
     "expected": {"intent": "record_payment", "missing_includes": ["transaction_nature"],
                   "entities": {"amount": 12000.0}}},
    {"name": "customer_balance_lookup", "message": "how much does the customer owe",
     "expected": {"intent": "customer_balance", "requires_clarification": False}},
    {"name": "list_banks", "message": "list bank accounts",
     "expected": {"intent": "list_bank_accounts", "requires_clarification": False}},
    {"name": "quotation_intent", "message": "create a quotation for the customer",
     "expected": {"intent": "create_quotation",
                   "missing_includes": ["transaction_date", "transaction_nature"],
                   "question_includes": ["is this quotation for"]}},
    {"name": "create_product_intent", "message": "add a new product HP printer",
     "expected": {"intent": "create_product"}},
    {"name": "batch_two_expenses",
     "message": "Record these 2 expenses:\n1. Office supplies Rs.5,000\n2. Fuel Rs.3,000",
     "expected": {"intent": "record_expense", "batch_items": 2,
                   "requires_clarification": True,
                   "question_includes": ["what is this expense for"]}},
    {"name": "date_answer_resolves", "message": "bought a chair for Rs.5,000",
     "history": [{"question": DATE_Q, "answer": "04/09/2026"}],
     "expected": {"intent": "record_purchase", "requires_clarification": True,
                   "missing_includes": ["payment_type", "transaction_nature"],
                   "entities": {"transaction_date": "2026-09-04"}}},
    {"name": "org_preference_payment_NOT_assumed", "message": "I bought a laptop",
     "prefs": {"payment_method": "CREDIT"},
     "expected": {"intent": "record_purchase",
                   "missing_includes": ["payment_type", "transaction_nature"],
                   "entities": {}}},
    {"name": "org_preference_payment_user_override", "message": "I bought a laptop on credit",
     "prefs": {"payment_method": "CASH"},
     "expected": {"intent": "record_credit_purchase",
                   "entities": {"payment_method": "CREDIT"}}},
    # ------------------------------------------------------------------
    # Work Stream R - CA-grade nature/purpose goldens (added deliberately).
    # ------------------------------------------------------------------
    {"name": "nature_first_round_purchased_table", "message": "I purchased a table",
     "expected": {"intent": "record_purchase", "requires_clarification": True,
                   "missing_includes": ["transaction_nature", "payment_type",
                                         "amount", "transaction_date"],
                   "question_includes": ["fixed asset", "inventory", "consumable"]}},
    {"name": "nature_answer_fixed_asset_routes_to_asset",
     "message": "I purchased a table for Rs.25,000",
     "history": [
         {"question": PURCHASE_NATURE_Q, "answer": "a"},
         {"question": "Was this paid in cash or on credit?", "answer": "cash"},
         {"question": DATE_Q, "answer": "04/09/2026"},
     ],
     "expected": {"intent": "register_fixed_asset", "requires_clarification": False,
                   "entities": {"transaction_nature": "FIXED_ASSET",
                                 "payment_method": "CASH",
                                 "amount": 25000.0,
                                 "transaction_date": "2026-09-04"}}},
    {"name": "nature_credit_expense_stays_on_bill_path",
     "message": "I purchased a charger",
     "history": [
         {"question": PURCHASE_NATURE_Q, "answer": "c"},
         {"question": "Was this paid in cash or on credit?", "answer": "credit"},
         {"question": DATE_Q, "answer": "04/09/2026"},
     ],
     "expected": {"intent": "record_credit_purchase",
                   "entities": {"transaction_nature": "OPERATING_EXPENSE",
                                 "payment_method": "CREDIT"}}},
    {"name": "sale_nature_disposal_routes_to_disposal",
     "message": "I sold a table for Rs.15,000",
     "history": [{"question": SALE_NATURE_Q, "answer": "c"}],
     "expected": {"intent": "dispose_fixed_asset",
                   "entities": {"transaction_nature": "ASSET_DISPOSAL",
                                 "amount": 15000.0}}},
    {"name": "quotation_nature_goods_answer",
     "message": "create a quotation for the customer",
     "history": [{"question": QUOTATION_NATURE_Q, "answer": "a"}],
     "expected": {"intent": "create_quotation",
                   "entities": {"transaction_nature": "GOODS"},
                   "missing_includes": ["transaction_date"]}},
    {"name": "expense_nature_capitalisable_routes_to_asset",
     "message": "record expense: office renovation Rs.80,000",
     "history": [{"question": EXPENSE_NATURE_Q, "answer": "c"}],
     "expected": {"intent": "register_fixed_asset",
                   "entities": {"transaction_nature": "FIXED_ASSET"}}},
    {"name": "learned_nature_preference_suppresses_question",
     "message": "I purchased a table",
     "prefs": {"transaction_nature": "INVENTORY"},
     "expected": {"intent": "record_purchase",
                   "question_excludes": ["fixed asset"],
                   "missing_excludes": ["transaction_nature"],
                   "entities": {"transaction_nature": "INVENTORY"}}},
]


def load_cases() -> List[Dict[str, Any]]:
    """Load every golden case from tests/golden/*.json (sorted)."""
    cases: List[Dict[str, Any]] = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        cases.append(json.loads(path.read_text(encoding="utf-8")))
    return cases


def evaluate_case(case: Dict[str, Any]) -> List[str]:
    """Run one golden case through the planner; return a list of failures."""
    p = plan(
        case["message"],
        clarification_history=case.get("history"),
        org_preferences=case.get("prefs"),
    )
    expected = case.get("expected") or {}
    failures: List[str] = []

    if expected.get("intent") and p.intent != expected["intent"]:
        failures.append(f"intent {p.intent!r} != {expected['intent']!r}")
    for key, value in (expected.get("entities") or {}).items():
        actual = p.extracted_entities.get(key)
        if actual != value:
            failures.append(f"entity {key}={actual!r} != {value!r}")
    for field in expected.get("missing_includes") or []:
        if field not in p.missing_fields:
            failures.append(f"missing_fields lacks {field!r}")
    for field in expected.get("missing_excludes") or []:
        if field in p.missing_fields:
            failures.append(
                f"missing_fields unexpectedly contains {field!r}"
            )
    if "missing_fields" in expected and p.missing_fields != expected["missing_fields"]:
        failures.append(
            f"missing_fields {p.missing_fields!r} != {expected['missing_fields']!r}"
        )
    if "batch_items" in expected:
        actual_batch = len(p.batch_items or [])
        if actual_batch != expected["batch_items"]:
            failures.append(
                f"batch_items {actual_batch} != {expected['batch_items']}"
            )
    if "requires_clarification" in expected:
        if p.requires_clarification != expected["requires_clarification"]:
            failures.append(
                f"requires_clarification {p.requires_clarification!r} != "
                f"{expected['requires_clarification']!r}"
            )
    # Work Stream R: assert on the QUESTIONNAIRE content of the first
    # round (e.g. the nature/purpose question must be present/absent).
    joined_questions = "\n".join(p.clarification_questions or []).lower()
    for needle in expected.get("question_includes") or []:
        if needle.lower() not in joined_questions:
            failures.append(f"clarification questions lack {needle!r}")
    for needle in expected.get("question_excludes") or []:
        if needle.lower() in joined_questions:
            failures.append(
                f"clarification questions unexpectedly contain {needle!r}"
            )
    return failures


def seed() -> int:
    """(Re)write the golden files from the current verified behavior."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for case in GOLDEN_SEEDS:
        path = GOLDEN_DIR / f"{case['name']}.json"
        path.write_text(
            json.dumps(case, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return len(GOLDEN_SEEDS)


def run(out: Any = None) -> float:
    """Evaluate all golden cases; return the pass rate (0.0-1.0)."""
    cases = load_cases()
    if not cases:
        print(
            "No golden cases found - run with --seed first.",
            file=out or sys.stdout,
        )
        return 0.0
    passed = 0
    for case in cases:
        failures = evaluate_case(case)
        if failures:
            print(
                f"FAIL {case['name']}: " + "; ".join(failures),
                file=out or sys.stdout,
            )
        else:
            passed += 1
    rate = passed / len(cases)
    print(
        f"\nEval pass-rate: {passed}/{len(cases)} ({rate:.0%})",
        file=out or sys.stdout,
    )
    return rate

