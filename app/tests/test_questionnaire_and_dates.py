"""
Regression pins for the two clarification-engine fixes:

A. DATES — a relative date the user stated ("yesterday", "2 days ago",
   "day before yesterday", "26 sep", "26/09") is resolved
   deterministically, so the transaction-date question never exists for a
   request that already names its date (the live incident: "… on Credit
   Yesterday" still asked "What is the transaction date?").

B. FIXED-FORMAT QUESTIONNAIRE — one machine shape
   (app/questionnaire.py) behind every clarification round.  The LLM may
   author/rephrase the questions inside that schema, but validation keeps
   the hard laws: only known ERP fields, never a fact already known, the
   deterministic bank always standing behind it.  Answers route back BY
   FIELD, so wording can never lose an answer.

C. CREDIT FIXED-ASSET PURCHASE — a capitalised asset bought on credit is
   an asset acquisition (register + depreciation policy), never a plain
   bill: useful life / method / salvage are ASKED in the same round.
"""

import uuid

import pytest

from app.date_parser import parse_transaction_date, resolve_relative_date_text
from app.planner import plan
from app.questionnaire import (
    build_questionnaire,
    build_questionnaire_with_llm,
    questionnaire_from_authored,
    validate_authored_questions,
)

BIKES = "I Purchased two Bikes from Beta Autos for 3400000 on Credit Yesterday"

class _StubClient:
    """Provider stub returning a canned payload (or raising)."""

    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.calls = 0

    async def generate_text_light(self, *a, **k):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._payload


# ---------------------------------------------------------------------------
# A. DATE RESOLUTION
# ---------------------------------------------------------------------------
def test_relative_phrases_parse_as_whole_answers():
    base = __import__("datetime").date(2026, 9, 27)
    assert parse_transaction_date("yesterday", today=base).iso_date == "2026-09-26"
    assert parse_transaction_date("2 days ago", today=base).iso_date == "2026-09-25"
    assert (
        parse_transaction_date("day before yesterday", today=base).iso_date
        == "2026-09-25"
    )
    assert parse_transaction_date("3 weeks ago", today=base).iso_date == "2026-09-06"
    assert parse_transaction_date("26/09", today=base).iso_date == "2026-09-26"
    assert parse_transaction_date("26 sep 2026", today=base).iso_date == "2026-09-26"
    assert (
        parse_transaction_date("September 26, 2026", today=base).iso_date
        == "2026-09-26"
    )


def test_free_text_resolver_finds_the_stated_date():
    base = __import__("datetime").date(2026, 9, 27)
    resolved = resolve_relative_date_text(BIKES, today=base)
    assert resolved is not None and resolved.iso_date == "2026-09-26"
    assert (
        resolve_relative_date_text("paid 50000 on credit 2 days ago", today=base).iso_date
        == "2026-09-25"
    )
    assert resolve_relative_date_text("no date mentioned here", today=base) is None


def test_planner_never_asks_a_date_the_user_stated():
    # "Yesterday" in the request: the date entity is resolved and the
    # questionnaire asks ONLY the nature.
    p = plan(BIKES)
    assert p.extracted_entities.get("transaction_date") == _yesterday_iso()
    assert "transaction_date" not in (p.missing_fields or [])
    assert not any("transaction date" in q.lower() for q in p.clarification_questions)

    # "2 days ago" (previous gap): resolved too.
    p2 = plan("purchased a laptop for 250000 on credit 2 days ago")
    assert p2.extracted_entities.get("transaction_date") == _two_days_ago_iso()
    assert "transaction_date" not in (p2.missing_fields or [])


def _yesterday_iso() -> str:
    import datetime as _dt

    return (_dt.date.today() - _dt.timedelta(days=1)).isoformat()


def _two_days_ago_iso() -> str:
    import datetime as _dt

    return (_dt.date.today() - _dt.timedelta(days=2)).isoformat()


# ---------------------------------------------------------------------------
# B. FIXED-FORMAT QUESTIONNAIRE
# ---------------------------------------------------------------------------
def test_questionnaire_payload_is_the_fixed_schema():
    q = build_questionnaire(
        ["useful_life_years", "depreciation_method", "transaction_date"],
        [],
        {"amount": 3400000, "transaction_date": "2026-09-26"},
        intent="register_fixed_asset",
    )
    payload = q.to_payload()
    assert payload["version"] == 1
    assert payload["intent"] == "register_fixed_asset"
    kinds = {entry["field"]: entry["kind"] for entry in payload["questions"]}
    # A known date is NEVER asked; the two policy fields are.
    assert "transaction_date" not in kinds
    assert kinds["useful_life_years"] == "number"
    assert kinds["depreciation_method"] == "choice"
    method = next(
        entry for entry in payload["questions"]
        if entry["field"] == "depreciation_method"
    )
    assert [opt["value"] for opt in method["options"]] == [
        "STRAIGHT_LINE", "REDUCING_BALANCE", "NONE",
    ]
    # Numbered text renders from the SAME object (answer-merge contract).
    assert q.render_text().startswith("To record this transaction")


def test_authored_questions_are_validated_not_trusted():
    known = {"amount": 3400000, "transaction_date": "2026-09-26"}
    specs = validate_authored_questions(
        [
            {  # valid, unanswered
                "field": "useful_life_years", "kind": "number",
                "question": "How many years will the bikes be in use?",
                "options": [], "why": "depreciation",
            },
            {  # already known -> dropped
                "field": "transaction_date", "kind": "date",
                "question": "When did you buy them?",
            },
            {  # unknown field -> dropped
                "field": "favourite_colour", "kind": "text",
                "question": "Which colour?",
            },
            {  # markdown -> cleaned text is still valid
                "field": "depreciation_method", "kind": "choice",
                "question": "**Which** method?",
                "options": [
                    {"value": "STRAIGHT_LINE", "label": "Straight line"},
                    {"value": "REDUCING_BALANCE", "label": "Reducing balance"},
                ],
            },
        ],
        known,
    )
    fields = [s.field for s in specs]
    assert fields == ["useful_life_years", "depreciation_method"]
    assert "**" not in specs[1].question


def test_authored_payload_builds_a_questionnaire_with_back_compat():
    authored = {
        "text": "A couple of things before I record the bikes:\n1. Life?\n2. Method?",
        "questions": [
            {
                "field": "useful_life_years", "kind": "number",
                "question": "What is the useful life of the bikes in years?",
                "options": [],
            },
            {
                "field": "depreciation_method", "kind": "choice",
                "question": "Which depreciation method should I use?",
                "options": [
                    {"value": "STRAIGHT_LINE", "label": "Straight line"},
                    {"value": "REDUCING_BALANCE", "label": "Reducing balance"},
                ],
            },
        ],
    }
    q = questionnaire_from_authored(authored, intent="register_fixed_asset")
    assert q is not None and q.source == "reasoning_llm"
    assert q.fields() == ["useful_life_years", "depreciation_method"]
    assert q.to_payload()["questions"][1]["options"][0]["label"] == "Straight line"

    # Older output (numbered text + options_per_part) still reaches ONE shape.
    legacy = questionnaire_from_authored(
        {
            "text": "To record this I need:\n1. Was it cash or credit?\n2. What amount?",
            "options_per_part": [["CASH", "CREDIT"], []],
        }
    )
    assert legacy is not None
    assert legacy.questions[0].options == (("CASH", "CASH"), ("CREDIT", "CREDIT"))

