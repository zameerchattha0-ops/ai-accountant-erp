"""Return-family and "buy" routing — production post-mortem, 2026-09-30.

Two live sessions fell through the keyword ladder to ``intent=unknown`` and
were then dropped into the GENERIC LLM execution loop (up to 10 model
round-trips, hidden reasoning ON) inside the fixed 120s wall-clock budget,
which expired:

* ``387b7cb8`` — "Alpha Associates Returned Chairs amounting to 34000".
  The return patterns demanded the literal words "goods" + "customer", so
  the sentence matched NOTHING: no party check, no questionnaire, no
  confirmation gate — straight into the tool loop, FAILED at exactly 120s.
  PRELIMINARY_EXTRACTION also swallowed party + item into one blob
  ("Alpha Associates Returned Chairs"), so nothing anchored the goods.
* ``f2166d3f`` — "we buy a car for 6000000 on cash".  The ladder had
  purchase/bought/purchased but NOT "buy", so even after four clarified
  answers (amount 6,000,000 · CASH · FIXED_ASSET · account "Vehicle - Car")
  the final turn still ran ``intent=unknown`` → the same 120s death.

Pinned here:

* the phrasings classify — sale return (credit note) vs purchase return vs
  purchase — and "return on investment" prose never becomes a credit note;
* the party/item split for "<Party> returned <items>", and "we" is never
  read as a party name;
* the credit-note plan OFFERS the readers the CA flow needs: fetch the
  party's ledger/invoices → identify the returned sale → create the note
  against it;
* the execution loop runs THINKING OFF end-to-end (the provider chain leads
  with a thinking model measured at 20.4s / 0 answer chars on a mechanical
  prompt, and the loop must fit several round-trips in 120s).
"""

import pytest

from app.planner import (
    _context_for_intent,
    _extract_item,
    _tools_for_intent,
    plan,
)


class TestReturnRouting:
    def test_customer_returned_items_is_a_credit_note(self):
        """The reported production request: everything must be extracted."""
        p = plan("Alpha Associates Returned Chairs amounting to 34000")
        assert p.intent == "create_credit_note"
        assert p.extracted_entities.get("customer_name") == "Alpha Associates"
        assert (
            p.extracted_entities.get("item_description") or ""
        ).strip().lower() == "chairs"
        assert p.extracted_entities.get("amount") == 34000.0

    @pytest.mark.parametrize(
        "message",
        [
            "Alpha Associates Returned Chairs amounting to 34000",
            "Beta Traders returned the damaged goods to us",
            "customer returned goods worth 12000",
        ],
    )
    def test_sale_side_return_phrasings(self, message):
        assert plan(message).intent == "create_credit_note"

    @pytest.mark.parametrize(
        "message",
        [
            "we returned the defective chairs to the supplier",
            "we sent the damaged laptops back to the vendor",
            "purchase return of 5000 to supplier",
        ],
    )
    def test_purchase_side_return_phrasings(self, message):
        assert plan(message).intent == "create_purchase_return"

    def test_return_on_investment_prose_is_never_a_credit_note(self):
        """Only the RETURN OF GOODS is a return; ROI chatter is not."""
        p = plan("return on investment improved this quarter")
        assert p.intent != "create_credit_note"

    def test_we_is_never_a_party_name(self):
        """The purchase-side phrasing must not invent a customer "we"."""
        message = "we returned the defective chairs to the supplier"
        p = plan(message)
        assert not p.extracted_entities.get("customer_name")
        assert "chairs" in (_extract_item(message) or "")



class TestBuyRouting:
    def test_buy_is_a_cash_purchase_after_refinement(self):
        """The car session: "buy" must classify and keep every entity."""
        p = plan("we buy a car for 6000000 on cash")
        assert p.intent == "record_cash_purchase"
        assert p.extracted_entities.get("payment_method") == "CASH"
        assert p.extracted_entities.get("item_description") == "car"
        assert p.extracted_entities.get("amount") == 6000000.0

    def test_buying_on_credit_refines_to_credit_purchase(self):
        p = plan("buying furniture for 250000 on credit")
        assert p.intent == "record_credit_purchase"


class TestReturnReadsThePartysRecords:
    """The CA flow: fetch the party's invoices, THEN identify the sale."""

    def test_credit_note_offers_ledger_and_invoice_readers(self):
        tools = _tools_for_intent("create_credit_note")
        assert "get_customer_ledger" in tools
        assert "get_invoice" in tools
        context = _context_for_intent("create_credit_note")
        assert "invoices" in context
        assert "customer_ledger" in context

    def test_purchase_return_reads_the_supplier_side(self):
        tools = _tools_for_intent("create_purchase_return")
        assert "get_supplier_ledger" in tools
        context = _context_for_intent("create_purchase_return")
        assert "purchase_bills" in context
        assert "supplier_ledger" in context


class TestExecutionLoopThinksOff:
    """The 120s death happened inside the tool loop itself — every layer of
    that call must pass the "no hidden reasoning" request through."""

    @pytest.mark.asyncio
    async def test_qwen_tool_loop_forwards_thinking_off(self, monkeypatch):
        import app.qwen_client as qwen_module
        from app.models.schemas import AgentContext
        from app.qwen_client import QwenClient

        client = QwenClient(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="test-model",
        )
        seen = {}

        async def fake_chat(
            messages, tools, max_output_tokens=None, thinking_off=False
        ):
            seen["thinking_off"] = thinking_off
            return {
                "choices": [{"message": {"content": "ok", "tool_calls": []}}]
            }

        async def no_tools():
            return []

        monkeypatch.setattr(client, "_chat_completion", fake_chat)
        monkeypatch.setattr(qwen_module, "get_gemini_tool_definitions", no_tools)
        monkeypatch.setattr(
            qwen_module, "build_user_content", lambda message, context: message
        )

        out = await client.generate_with_tools(
            user_message="we buy a car for 6000000 on cash",
            context=AgentContext(organization={}, user={}),
            thinking_off=True,
        )
        assert seen["thinking_off"] is True
        assert out["text"] == "ok"

    @pytest.mark.asyncio
    async def test_orchestrator_forwards_thinking_off_when_accepted(
        self, monkeypatch
    ):
        from app.ai_orchestrator import AIOrchestrator
        from app.models.schemas import AgentContext

        class _AcceptsThinking:
            def __init__(self):
                self.kwargs = {}

            async def generate_with_tools(
                self,
                *,
                user_message,
                context,
                max_tool_iterations=10,
                executor=None,
                excluded_tools=None,
                thinking_off=False,
            ):
                self.kwargs["thinking_off"] = thinking_off
                return {"text": "ok", "tool_calls": [], "tool_results": []}

        stub = _AcceptsThinking()
        orchestrator = AIOrchestrator()
        monkeypatch.setattr(
            orchestrator,
            "_candidate_providers",
            lambda **kwargs: [
                {
                    "provider": "stub",
                    "model": "stub-model",
                    "factory": lambda: stub,
                    "capability": "text_tools",
                }
            ],
        )

        result = await orchestrator.generate_with_tools(
            user_message="x",
            context=AgentContext(organization={}, user={}),
            thinking_off=True,
        )
        assert stub.kwargs["thinking_off"] is True
        assert result["text"] == "ok"

    @pytest.mark.asyncio
    async def test_client_without_the_knob_still_runs(self, monkeypatch):
        """A Gemini-style client must never receive an unsupported kwarg."""
        from app.ai_orchestrator import AIOrchestrator
        from app.models.schemas import AgentContext

        class _NoThinking:
            def __init__(self):
                self.called = False

            async def generate_with_tools(
                self,
                *,
                user_message,
                context,
                max_tool_iterations=10,
                executor=None,
                excluded_tools=None,
            ):
                self.called = True
                return {"text": "ok", "tool_calls": [], "tool_results": []}

        stub = _NoThinking()
        orchestrator = AIOrchestrator()
        monkeypatch.setattr(
            orchestrator,
            "_candidate_providers",
            lambda **kwargs: [
                {
                    "provider": "stub",
                    "model": "stub-model",
                    "factory": lambda: stub,
                    "capability": "text_tools",
                }
            ],
        )

        result = await orchestrator.generate_with_tools(
            user_message="x",
            context=AgentContext(organization={}, user={}),
            thinking_off=True,
        )
        assert stub.called is True
        assert result["text"] == "ok"
