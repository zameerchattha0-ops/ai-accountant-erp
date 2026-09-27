"""Answer-routing + LLM skip-and-fill pins (the re-ask incident).

Production (screenshots): the user tapped the questionnaire chips —
"Fixed asset" (value FIXED_ASSET), "Cash" (CASH), "Yesterday" (YESTERDAY)
— and sent all answers.  CASH and YESTERDAY merged into entities;
FIXED_ASSET did NOT: the keyword pass matched "fixed asset" but never the
underscored chip token.  The nature stayed missing and the NEXT round
re-asked it ("answers not getting into the brain").

Pinned here:

  1. every tapped chip VALUE in the nature matrix routes;
  2. the screenshot scenario end-to-end — round-1 chips reach entities
     and NOTHING remains missing;
  3. the questionnaire model may SKIP-AND-FILL a missing field when the
     fact already exists in the provided facts/history — Python validates
     the value (choice vocabulary / date parse / numeric) and a rejected
     fill keeps the deterministic question (the gap floor never drops).
"""

import json
import re
import uuid

import pytest

from app import questionnaire as qmod
from app import reasoning
from app.planner import (
    _merge_clarification_answers,
    _missing_fields,
    _questions_for_fields,
)


class TestChipTokensRoute:
    def test_purchase_nature_chips(self):
        q = reasoning.NATURE_DECISION_QUESTION
        assert reasoning.resolve_nature_answer(q, "FIXED_ASSET") == "FIXED_ASSET"
        assert reasoning.resolve_nature_answer(q, "INVENTORY") == "INVENTORY"
        assert reasoning.resolve_nature_answer(q, "CONSUMABLE") == "OPERATING_EXPENSE"
        assert reasoning.resolve_nature_answer(q, "SERVICE") == "SERVICE"

    def test_sale_nature_chips(self):
        q = reasoning._NATURE_MATRIX["sale"]["question"]
        assert reasoning.resolve_nature_answer(q, "GOODS") == "GOODS"
        assert reasoning.resolve_nature_answer(q, "OTHER_INCOME") == "OTHER_INCOME"
        assert reasoning.resolve_nature_answer(q, "ASSET_DISPOSAL") == "ASSET_DISPOSAL"

    def test_letters_and_words_still_route(self):
        q = reasoning.NATURE_DECISION_QUESTION
        assert reasoning.resolve_nature_answer(q, "a") == "FIXED_ASSET"
        assert reasoning.resolve_nature_answer(q, "fixed asset") == "FIXED_ASSET"


class TestScreenshotScenario:
    def test_round_one_chips_reach_the_entities_and_stop_the_re_ask(self):
        ents = {
            "supplier_name": "Beta Autos",
            "amount": 1360000.0,
            "item_description": "car",
            "capitalization_threshold": 50000.0,
        }
        missing = _missing_fields("record_purchase", ents)
        assert missing == [
            "transaction_nature", "payment_type", "transaction_date",
        ]
        qs = _questions_for_fields("record_purchase", missing, ents)
        text = qmod.build_questionnaire(
            missing, qs, ents, "record_purchase"
        ).render_text()
        assert text

        merged = _merge_clarification_answers(
            dict(ents),
            [{"question": text, "answer": "1) FIXED_ASSET\n2) CASH\n3) YESTERDAY"}],
        )
        assert merged["transaction_nature"] == "FIXED_ASSET"
        assert merged["payment_method"] == "CASH"
        assert merged.get("transaction_date")
        # nothing is left open — the next round asks NOTHING again
        assert _missing_fields("record_purchase", merged) == []


class _StubClient:
    def __init__(self, reply: str):
        self.reply = reply

    async def generate_text_light(self, prompt: str) -> str:  # noqa: D401
        return self.reply


class TestSkipAndFillValidation:
    def test_choice_value_must_be_one_of_the_fields_own_options(self):
        allowed = {"transaction_nature": qmod.spec_for("transaction_nature")}
        ok = qmod._validate_llm_fill(
            {
                "field": "transaction_nature",
                "already_answered": True,
                "value": "fixed asset",  # separator-insensitive -> option VALUE
            },
            allowed,
        )
        assert ok == ("transaction_nature", "FIXED_ASSET")
        assert qmod._validate_llm_fill(
            {
                "field": "transaction_nature",
                "already_answered": True,
                "value": "MAYBE",
            },
            allowed,
        ) is None

    def test_date_fill_must_parse(self):
        allowed = {
            "transaction_date": qmod.QuestionSpec(
                field="transaction_date",
                kind=qmod.KIND_DATE,
                question="What is the transaction date?",
            )
        }
        ok = qmod._validate_llm_fill(
            {
                "field": "transaction_date",
                "already_answered": True,
                "value": "yesterday",
            },
            allowed,
        )
        assert ok and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ok[1])
        assert qmod._validate_llm_fill(
            {
                "field": "transaction_date",
                "already_answered": True,
                "value": "whenever",
            },
            allowed,
        ) is None

    def test_money_fill_must_be_numeric(self):
        allowed = {
            "amount": qmod.QuestionSpec(
                field="amount", kind=qmod.KIND_MONEY, question="How much?",
            )
        }
        assert qmod._validate_llm_fill(
            {"field": "amount", "already_answered": True, "value": "1,360,000"},
            allowed,
        ) == ("amount", "1360000.0")
        assert qmod._validate_llm_fill(
            {"field": "amount", "already_answered": True, "value": "a lot"},
            allowed,
        ) is None

    def test_unknown_field_and_missing_flag_are_rejected(self):
        allowed = {"transaction_nature": qmod.spec_for("transaction_nature")}
        assert qmod._validate_llm_fill(
            {"field": "invented_field", "already_answered": True, "value": "x"},
            allowed,
        ) is None
        assert qmod._validate_llm_fill(
            {"field": "transaction_nature", "value": "FIXED_ASSET"},
            allowed,
        ) is None


class TestSkipAndFillBuild:
    @pytest.mark.asyncio
    async def test_valid_fill_drops_the_question_and_records_the_fact(self):
        ents = {
            "supplier_name": "Beta Autos",
            "amount": 1360000.0,
            "item_description": "car",
            "capitalization_threshold": 50000.0,
        }
        reply = json.dumps(
            {
                "intro": "One quick thing.",
                "questions": [
                    {
                        "field": "payment_type",
                        "already_answered": True,
                        "value": "CASH",
                    },
                    {
                        "field": "transaction_nature",
                        "question": "What kind of item is this car?",
                        "kind": "choice",
                        "options": [
                            {"value": "FIXED_ASSET", "label": "Fixed asset"},
                            {"value": "OPERATING_EXPENSE", "label": "Expense"},
                        ],
                    },
                ],
            }
        )
        q = await qmod.build_questionnaire_with_llm(
            missing_fields=["transaction_nature", "payment_type"],
            questions=[],
            entities=ents,
            intent="record_purchase",
            client=_StubClient(reply),
        )
        assert q.filled_facts == {"payment_type": "CASH"}
        assert [x.field for x in q.questions] == ["transaction_nature"]
        assert q.to_payload()["filled"] == {"payment_type": "CASH"}

    @pytest.mark.asyncio
    async def test_invalid_fill_keeps_the_deterministic_question(self):
        reply = json.dumps(
            {
                "questions": [
                    {
                        "field": "payment_type",
                        "already_answered": True,
                        "value": "MAYBE",
                    }
                ]
            }
        )
        q = await qmod.build_questionnaire_with_llm(
            missing_fields=["transaction_nature", "payment_type"],
            questions=[],
            entities={"item_description": "car"},
            intent="record_purchase",
            client=_StubClient(reply),
        )
        assert q.filled_facts == {}
        assert [x.field for x in q.questions] == [
            "transaction_nature", "payment_type",
        ]

    @pytest.mark.asyncio
    async def test_all_filled_keeps_one_question_standing(self):
        reply = json.dumps(
            {
                "questions": [
                    {
                        "field": "transaction_nature",
                        "already_answered": True,
                        "value": "FIXED_ASSET",
                    },
                    {
                        "field": "payment_type",
                        "already_answered": True,
                        "value": "CASH",
                    },
                ]
            }
        )
        q = await qmod.build_questionnaire_with_llm(
            missing_fields=["transaction_nature", "payment_type"],
            questions=[],
            entities={"item_description": "car"},
            intent="record_purchase",
            client=_StubClient(reply),
        )
        assert [x.field for x in q.questions] == ["transaction_nature"]
        assert q.filled_facts == {"payment_type": "CASH"}

    @pytest.mark.asyncio
    async def test_garbage_reply_falls_back_to_the_bank(self):
        q = await qmod.build_questionnaire_with_llm(
            missing_fields=["transaction_nature", "payment_type"],
            questions=[],
            entities={"item_description": "car"},
            intent="record_purchase",
            client=_StubClient("not json at all"),
        )
        assert q.filled_facts == {}
        assert [x.field for x in q.questions] == [
            "transaction_nature", "payment_type",
        ]
        assert q.source == "deterministic"
