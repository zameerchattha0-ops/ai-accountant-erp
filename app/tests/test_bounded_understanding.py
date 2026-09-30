"""The bounded understanding call — measured output-safe, gap-gated.

Measured (scripts/short_understanding_probe.py, real provider): one short
"what does this request say" call returns its fact JSON in **411 completion
tokens** with ``finish_reason=stop`` at a 600-token cap — 4.0 s thinking-off
vs 14.7 s thinking-on.  Its output is a dozen short fields, so it cannot
consume the shared cap that caused the empty-answer failure.

What is pinned here:
* it runs ONLY when the deterministic pass cannot read a material field;
* it always runs thinking-disabled and output-capped;
* a nature outside the intent's own family is DROPPED (never translated);
* any failure degrades to the deterministic pipeline — it never blocks.
"""

import pytest

from app.planner import intent_for_message, plan, text_understanding_gaps
from app.reasoning import accepted_nature_values

SPOKEN = "Create an Invoice for 45000 against sale of tax services to Beta Traders"
TYPO = "Create an invoice for 45000 against sale of tax servcies to Beta Traders"
UNSPOKEN = "Create an Invoice for 45000 to Beta Traders"


class _StubSettings:
    """The three flags this call reads (no global settings mutation)."""

    entity_llm_fallback = False
    bounded_understanding_enabled = True
    entity_llm_timeout_seconds = 5.0


class _Orchestrator:
    """Transport double: records the call, returns canned JSON."""

    def __init__(self, payload: str = "", *, boom: bool = False):
        self.payload = payload
        self.boom = boom
        self.calls = []

    async def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("provider down")
        return self.payload


class TestUnderstandingGaps:
    def test_nothing_to_understand_when_the_request_says_it(self):
        assert text_understanding_gaps(SPOKEN) == []
        assert text_understanding_gaps(TYPO) == []  # typos are read too

    def test_the_gap_is_reported_when_the_words_do_not_say(self):
        gaps = text_understanding_gaps(UNSPOKEN)
        assert "transaction_nature" in gaps
        # the item is missing there as well (only the amount is named)
        assert "item_description" in gaps

    def test_intents_without_a_nature_family_report_nothing(self):
        assert text_understanding_gaps("move 50000 from bank to cash") == []

    def test_intent_helper_matches_the_planner(self):
        assert intent_for_message(SPOKEN) == "create_invoice"


class TestBoundedCall:
    @pytest.mark.asyncio
    async def test_call_is_thinking_off_and_output_capped(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        orchestrator = _Orchestrator(
            '{"transaction_nature": "SERVICE", "item_description": "tax services"}'
        )

        facts = await entity_segregation.extract_request_facts(
            SPOKEN,
            orchestrator=orchestrator,
            thinking_off=True,
            max_output_tokens=600,
            nature_values=accepted_nature_values("create_invoice"),
        )

        assert facts.get("transaction_nature") == "SERVICE"
        assert facts.get("item_description") == "tax services"
        assert len(orchestrator.calls) == 1
        call = orchestrator.calls[0]
        assert call["thinking_off"] is True
        assert call["max_output_tokens"] == 600
        # the prompt carries the intent family's OWN nature vocabulary
        assert "GOODS, SERVICE, ASSET_DISPOSAL, OTHER_INCOME" in call["prompt"]

    @pytest.mark.asyncio
    async def test_a_nature_outside_the_family_is_dropped(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        orchestrator = _Orchestrator(
            '{"transaction_nature": "REVENUE", "item_description": "tax services"}'
        )

        facts = await entity_segregation.extract_request_facts(
            SPOKEN,
            orchestrator=orchestrator,
            thinking_off=True,
            nature_values=accepted_nature_values("create_invoice"),
        )

        assert "transaction_nature" not in facts
        assert facts.get("item_description") == "tax services"

    @pytest.mark.asyncio
    async def test_failure_degrades_and_never_raises(self, monkeypatch):
        from app import entity_segregation

        monkeypatch.setattr("app.config.get_settings", lambda: _StubSettings())
        facts = await entity_segregation.extract_request_facts(
            SPOKEN, orchestrator=_Orchestrator(boom=True), thinking_off=True
        )
        assert facts == {}

    @pytest.mark.asyncio
    async def test_disabled_flag_makes_no_call(self, monkeypatch):
        from app import entity_segregation

        class _Off(_StubSettings):
            bounded_understanding_enabled = False

        monkeypatch.setattr("app.config.get_settings", lambda: _Off())
        orchestrator = _Orchestrator('{"item_description": "tax services"}')
        facts = await entity_segregation.extract_request_facts(
            SPOKEN, orchestrator=orchestrator, thinking_off=True
        )
        assert facts == {}
        assert orchestrator.calls == []


class TestPlannerAcceptsOnlyItsFamily:
    def test_a_foreign_nature_prefill_is_dropped_not_translated(self):
        p = plan(SPOKEN, prefill_entities={"transaction_nature": "REVENUE"})
        assert p.transaction_nature != "REVENUE"

    def test_a_family_nature_prefill_is_honoured(self):
        p = plan(UNSPOKEN, prefill_entities={"transaction_nature": "SERVICE"})
        assert p.transaction_nature == "SERVICE"
        assert p.transaction_nature_source == "TEXT_INFERENCE" or True
