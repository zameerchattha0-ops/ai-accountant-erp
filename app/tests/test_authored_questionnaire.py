"""Token Harbor WRITES the questions — the template is off the ask path.

The requirement: the same provider that analyses the request writes the
clarification questions in a fixed JSON format aligned with the frontend
(field/kind/question/options), and Python only validates.  The reasoning
request already asks for it (`_RESPONSE_SHAPE` question block, Path A);
`author_questionnaire` covers the planner-gap path (Path B) where the
deterministic bank used to author every visible question.

Pinned here:
  * the provider receives the request + facts + answered history + routing
    vocabulary and its OWN question wording reaches the payload (no bank
    text anywhere);
  * validation drops unknown fields and never asks a known fact;
  * provider failure / garbage / zero valid questions -> None (the agent's
    deterministic floor stands — a material gap is never dropped);
  * the payload is the frontend contract and its tap VALUES route through
    the answer merge (field-tagged, wording-independent).
"""

import json

import pytest

from app import questionnaire as qmod
from app.planner import _merge_clarification_answers, _missing_fields


class _StubClient:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompt = None

    async def generate_text_light(self, prompt: str) -> str:
        self.prompt = prompt
        return self.reply


class _BoomClient:
    async def generate_text_light(self, prompt: str) -> str:
        raise RuntimeError("token harbor 503")


AUTHORED = {
    "intro": "Three details before I post this.",
    "questions": [
        {
            "field": "transaction_nature",
            "kind": "choice",
            "question": (
                "Is this car a long-term fleet asset, resale stock, an "
                "everyday running cost, or a service?"
            ),
            "options": [
                {"value": "FIXED_ASSET", "label": "Long-term (capitalise)"},
                {"value": "INVENTORY", "label": "Resale stock"},
                {"value": "OPERATING_EXPENSE", "label": "Running cost"},
                {"value": "SERVICE", "label": "Service"},
            ],
            "why": "it decides the ledger and the depreciation",
        },
        {
            "field": "payment_type",
            "kind": "choice",
            "question": (
                "Was the 1,360,000 paid now, or taken on credit from Beta Autos?"
            ),
            "options": [
                {"value": "CASH", "label": "Paid now"},
                {"value": "CREDIT", "label": "On credit"},
            ],
        },
        {
            "field": "transaction_date",
            "kind": "date",
            "question": "Which date should this car purchase be recorded on?",
            "options": [
                {"value": "TODAY", "label": "Today"},
                {"value": "YESTERDAY", "label": "Yesterday"},
            ],
        },
    ],
}

_ENTS = {
    "supplier_name": "Beta Autos",
    "amount": 1360000.0,
    "item_description": "car",
    "capitalization_threshold": 50000.0,
}
_MISSING = ["transaction_nature", "payment_type", "transaction_date"]


_NO_CLIENT = object()


async def _author(reply, **over):
    client = over.pop("client", _NO_CLIENT)
    if client is _NO_CLIENT:
        client = _StubClient(
            json.dumps(AUTHORED) if reply is None else str(reply)
        )
    kwargs = dict(
        client=client,
        user_request="I purchased a car for 1360000 from beta autos",
        intent="record_purchase",
        missing_fields=over.pop("missing_fields", _MISSING),
        entities=over.pop("entities", dict(_ENTS)),
        history=over.pop("history", None),
        today=over.pop("today", "2026-09-27"),
    )
    kwargs.update(over)
    return await qmod.author_questionnaire(**kwargs)


class TestProviderWritesTheQuestions:
    @pytest.mark.asyncio
    async def test_the_models_own_wording_reaches_the_payload(self):
        q = await _author(None)
        assert q is not None
        assert q.source == "llm_authored"
        rendered = q.render_text()
        # the model's wording, verbatim — NOT the deterministic bank's
        assert "Is this car a long-term fleet asset" in rendered
        assert "Was the 1,360,000 paid now" in rendered
        assert "1, 2 or 3" not in rendered
        assert "Please answer with a, b, c or d" not in rendered

    @pytest.mark.asyncio
    async def test_prompt_carries_request_facts_history_and_vocabulary(self):
        stub = _StubClient(json.dumps(AUTHORED))
        await _author(None, client=stub)
        prompt = stub.prompt
        assert prompt is not None
        assert "USER_REQUEST" in prompt
        assert "I purchased a car for 1360000 from beta autos" in prompt
        assert "MISSING_MATERIAL_FACTS" in prompt
        assert "KNOWN_FACTS" in prompt
        assert "ANSWERED_HISTORY" in prompt
        assert "FIELD_VOCABULARY" in prompt
        assert "transaction_nature" in prompt
        assert '"TODAY": "2026-09-27"' in prompt

    @pytest.mark.asyncio
    async def test_unknown_field_and_known_fact_are_dropped(self):
        reply = json.dumps(
            {
                "intro": "One thing.",
                "questions": [
                    {"field": "invented_thing", "question": "Nope?"},
                    {
                        "field": "transaction_nature",
                        "question": "Long-term asset, resale stock, running cost, or service?",
                        "options": [
                            {"value": "FIXED_ASSET", "label": "Asset"},
                            {"value": "INVENTORY", "label": "Stock"},
                        ],
                    },
                ],
            }
        )
        # the nature is ALREADY KNOWN -> the model's question about it is
        # dropped (the other two gaps are genuinely open)
        q = await _author(None, entities={"transaction_nature": "FIXED_ASSET"})
        assert q is not None
        assert [x.field for x in q.questions] == [
            "payment_type", "transaction_date",
        ]

        # unknown field dropped, valid one kept when the fact is open
        q2 = await _author(reply, entities={"amount": 1360000.0})
        assert q2 is not None
        assert [x.field for x in q2.questions] == ["transaction_nature"]

    @pytest.mark.asyncio
    async def test_provider_failure_garbage_and_empty_return_none(self):
        assert await _author(None, client=_BoomClient()) is None
        assert await _author("not json at all") is None
        assert await _author(json.dumps({"intro": "x", "questions": []})) is None
        # no client at all (hermetic tests) -> deterministic floor duty
        assert await _author(None, client=None) is None
        # no open gaps -> nothing to author
        assert await _author(None, missing_fields=[]) is None


class TestFrontendContractAndRouting:
    @pytest.mark.asyncio
    async def test_payload_is_the_frontend_shape(self):
        q = await _author(None)
        payload = q.to_payload()
        assert payload["version"] == qmod.SCHEMA_VERSION
        assert payload["intent"] == "record_purchase"
        assert payload["source"] == "llm_authored"
        assert payload["intro"] == "Three details before I post this."
        for i, entry in enumerate(payload["questions"], start=1):
            assert entry["id"] == f"q{i}"
            assert entry["field"] in _MISSING
            assert entry["kind"] in qmod._KINDS
            assert entry["question"]
            assert entry["required"] is True
            for opt in entry["options"] or []:
                assert opt["value"] and opt["label"]
        # tap chips, index-aligned with the numbered text
        opts = q.render_options()
        assert opts and len(opts) == 3
        assert opts[0][0]["value"] == "FIXED_ASSET"
        assert opts[1][0]["value"] == "CASH"

    @pytest.mark.asyncio
    async def test_typed_numbered_answer_routes_by_position_not_wording(self):
        from app.agent import _tag_numbered_answers

        q = await _author(None)
        row = {
            # the model's own wording — no bank markers to match on
            "question": q.render_text(),
            "answer": "1) FIXED_ASSET\n2) CASH\n3) YESTERDAY",
            "required_information": [x.field for x in q.questions],
        }
        tagged = _tag_numbered_answers([row])
        assert [t["field"] for t in tagged] == [
            "transaction_nature", "payment_type", "transaction_date",
        ]
        assert tagged[0]["answer"] == "FIXED_ASSET"
        merged = _merge_clarification_answers(dict(_ENTS), [row, *tagged])
        assert merged["transaction_nature"] == "FIXED_ASSET"
        assert merged["payment_method"] == "CASH"
        assert merged.get("transaction_date")
        assert _missing_fields("record_purchase", merged) == []

    @pytest.mark.asyncio
    async def test_tagger_only_tags_aligned_rounds(self):
        from app.agent import _tag_numbered_answers

        # no required fields (seeded fills / legacy rows) -> nothing to zip
        assert _tag_numbered_answers(
            [{"question": "q", "answer": "1) a\n2) b", "required_information": []}]
        ) == []
        # line/field count mismatch -> never guess the zip
        assert _tag_numbered_answers(
            [{"question": "q", "answer": "only one line", "required_information": ["a", "b"]}]
        ) == []
        assert _tag_numbered_answers(
            [{"question": "q", "answer": "1) a", "required_information": ["a", "b"]}]
        ) == []
        # single-field round: the whole (single-line) answer IS that field
        assert _tag_numbered_answers(
            [
                {
                    "question": "q",
                    "answer": "3) FIXED_ASSET",
                    "required_information": ["transaction_nature"],
                }
            ]
        ) == [
            {
                "field": "transaction_nature",
                "question": "transaction_nature",
                "answer": "FIXED_ASSET",
            }
        ]
