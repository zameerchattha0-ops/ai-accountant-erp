import json
import uuid
import pytest
from app.treatment_review import (
    TreatmentReview,
    _budget_treatment_prompt,
    _INSTRUCTION,
    review_plan_treatment,
)
from app.config import get_settings

class DummyCall:
    def __init__(self, tool_name, arguments):
        self.tool_name = tool_name
        self.arguments = arguments

class DummyClassification:
    def __init__(self, transaction_nature="INVENTORY", source="analyst"):
        self.transaction_nature = transaction_nature
        self.source = source

class MockClient:
    def __init__(self, reply_json):
        self.reply_json = reply_json

    async def generate_text_light(self, prompt: str) -> str:
        # Verify prompt contains valid JSON structure
        json_part = prompt.replace(_INSTRUCTION, "").strip()
        data = json.loads(json_part)
        assert "confirmed_facts" in data
        assert "canonical_plan" in data
        return json.dumps(self.reply_json)

def test_budget_treatment_prompt_large_order():
    # 30 items
    items = [{"item": f"SKU-{i}", "description": f"Detailed description for item {i}" * 5, "price": 100 * i} for i in range(30)]
    facts = {
        "intent": "create_purchase_bill",
        "items": items,
        "item_description": "A very long detailed order description " * 10,
    }
    plan = [
        {
            "tool": "create_purchase_bill",
            "arguments": {
                "transaction_nature": "INVENTORY",
                "items": items,
                "total": 50000,
            }
        }
    ]

    prompt = _budget_treatment_prompt(_INSTRUCTION, facts, plan, max_chars=4000)
    assert _INSTRUCTION in prompt
    json_part = prompt.replace(_INSTRUCTION, "").strip()
    # Must decode cleanly as valid JSON!
    parsed = json.loads(json_part)
    assert "confirmed_facts" in parsed
    assert "canonical_plan" in parsed
    # Truncated summary marker is present
    assert len(parsed["canonical_plan"][0]["arguments"]["items"]) <= 11

@pytest.mark.asyncio
async def test_review_plan_treatment_tax_deviation_authority_split(monkeypatch):
    monkeypatch.setattr(get_settings(), "treatment_review_enabled", True)

    entities = {
        "subtotal": 1000.0,
        "printed_tax": 250.0, # 25% printed vs 17% computed (170.0) -> diff 80.0 > 1.0
        "tax_code": "STANDARD",
    }
    calls = [DummyCall("create_purchase_bill", {"subtotal": 1000.0, "total": 1250.0})]

    review = await review_plan_treatment(
        organization_id=uuid.uuid4(),
        intent="create_purchase_bill",
        classification=DummyClassification(),
        entities=entities,
        calls=calls,
        client=None, # Does not reach LLM
    )

    assert review.blocked is True
    assert review.ok is False
    assert any("Printed tax (250.0) differs from computed tax (170.0)" in f["why"] for f in review.flags)
    assert "Please clarify the correct tax amount" in review.question

@pytest.mark.asyncio
async def test_review_plan_treatment_clean_pass(monkeypatch):
    monkeypatch.setattr(get_settings(), "treatment_review_enabled", True)

    entities = {
        "subtotal": 1000.0,
        "printed_tax": 170.0, # exact match with 17% STANDARD
        "tax_code": "STANDARD",
    }
    calls = [DummyCall("create_purchase_bill", {"subtotal": 1000.0, "total": 1170.0})]
    client = MockClient({"contradictions": [], "missing_material_facts": []})

    review = await review_plan_treatment(
        organization_id=uuid.uuid4(),
        intent="create_purchase_bill",
        classification=DummyClassification(),
        entities=entities,
        calls=calls,
        client=client,
    )

    assert review.ran is True
    assert review.ok is True
    assert review.blocked is False
    assert len(review.flags) == 0

