"""Stock linkage + questionnaire guards (user asks 2026-10-18).

1. The purchase catalogue-sync MUST reuse an existing stock product by
   word-level match ('office chairs' -> 'chairs') — the exact-only check
   created the live duplicate PRD-000004 and credited the receipt to the
   wrong item.
2. The authored questionnaire MUST never re-ask a classifier-RESOLVED
   nature (drop_resolved_fields) and MUST preserve the catalogue-hinted
   question VERBATIM with tappable nature options when the classifier did
   park on it.
"""
import uuid

import pytest

from app.models.schemas import TransactionClassification
from app.questionnaire import author_questionnaire, drop_resolved_fields
from app.services import inventory_service, product_service


CHAIRS = {
    "id": str(uuid.uuid4()),
    "name": "chairs",
    "product_code": "PRD-000002",
    "is_stock_tracked": True,
}


# --- drop_resolved_fields --------------------------------------------------
def test_resolved_nature_is_stripped_from_missing_fields():
    cls = TransactionClassification(
        transaction_nature="INVENTORY", source="USER_ANSWER",
        requires_clarification=False,
    )
    assert drop_resolved_fields(
        ["transaction_nature", "quantity"], cls
    ) == ["quantity"]


def test_parked_or_absent_nature_stays_missing():
    parked = TransactionClassification(
        transaction_nature=None, requires_clarification=True,
    )
    assert drop_resolved_fields(["transaction_nature"], parked) == [
        "transaction_nature"
    ]
    assert drop_resolved_fields(["transaction_nature"], None) == [
        "transaction_nature"
    ]


# --- author_questionnaire verbatim preservation ----------------------------
class _FakeClient:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def generate_text_light(self, *, prompt: str) -> str:  # noqa: ARG002
        return self._payload


@pytest.mark.asyncio
async def test_catalogue_hinted_nature_question_is_preserved_verbatim():
    import json

    client = _FakeClient(json.dumps({
        "intro": "Quick check:",
        "questions": [{
            "field": "transaction_nature",
            "kind": "choice",
            "question": "Are they inventory-stocked products for resale, "
                        "or fixed assets to be used in the business?",
            "options": [
                {"value": "INVENTORY", "label": "Resale stock"},
                {"value": "FIXED_ASSET", "label": "Fixed asset"},
            ],
        }],
    }))
    classification = TransactionClassification(
        transaction_nature=None,
        requires_clarification=True,
        entity="office chair",
        catalogue_hint={
            "name": "chairs", "product_code": "PRD-000002",
            "is_stock_tracked": True,
        },
    )
    q = await author_questionnaire(
        client=client,
        user_request="Bought 2 office chairs from Alpha Traders",
        intent="record_credit_purchase",
        missing_fields=["transaction_nature"],
        entities={},
        classification=classification,
    )
    assert q is not None and not q.is_empty()
    nature_q = next(x for x in q.questions if x.field == "transaction_nature")
    # the model's rephrasing is REPLACED by the verbatim hinted question
    assert "chairs (PRD-000002)" in nature_q.question
    assert "(a) YES" in nature_q.question
    assert "inventory-stocked" not in nature_q.question
    # tappable nature-vocabulary options, inventory first
    assert [v for v, _lbl in nature_q.options] == [
        "INVENTORY", "FIXED_ASSET", "CONSUMABLE", "SERVICE",
    ]



# --- purchase catalogue-sync: LLM ANALYST reuse (2026-10-20) ----------------
@pytest.mark.asyncio
async def test_purchase_sync_reuses_stock_product_via_llm_analyst(monkeypatch):
    """'Is this the SAME product as an existing entry?' is a SEMANTIC judgment
    the LLM makes over the FETCHED candidates — the model says 'office chairs'
    IS catalogue 'chairs', so it reuses (never creates a duplicate)."""
    from app.config import get_settings

    get_settings().llm_catalogue_match_enabled = True

    class _StubClient:
        async def generate_text_light(self, prompt):
            # the fetched list has one candidate (chairs) -> index 1
            return '{"match_index": 1, "reason": "same product"}'

    import app.ai_orchestrator as orch
    monkeypatch.setattr(orch, "get_client", lambda: _StubClient())

    async def _no_exact(*_a, **_k):
        return []

    async def _catalogue(*_a, **_k):
        return [CHAIRS]

    async def _never_create(*_a, **_k):
        raise AssertionError("must REUSE, never create a duplicate")

    monkeypatch.setattr(product_service, "search", _no_exact)
    monkeypatch.setattr("app.database.fetch_many", _catalogue)
    monkeypatch.setattr(product_service, "create", _never_create)
    row = await inventory_service.find_or_create_catalogue_product(
        uuid.uuid4(), name="office chairs", quantity=2, unit_cost=45000,
    )
    assert row and row["name"] == "chairs"
    assert row["reused"] is True  # honest note in the bill result


@pytest.mark.asyncio
async def test_purchase_sync_creates_when_llm_says_distinct(monkeypatch):
    """The analyst judging 'office chairs' DISTINCT from 'office desks' means a
    NEW product — never a silent merge on a shared word."""
    from app.config import get_settings

    get_settings().llm_catalogue_match_enabled = True

    DESKS = {"id": str(uuid.uuid4()), "name": "office desks",
             "product_code": "PRD-000099", "is_stock_tracked": True}

    class _StubClient:
        async def generate_text_light(self, prompt):
            return '{"match_index": null, "reason": "different good"}'

    import app.ai_orchestrator as orch
    monkeypatch.setattr(orch, "get_client", lambda: _StubClient())

    async def _no_exact(*_a, **_k):
        return []

    async def _catalogue(*_a, **_k):
        return [DESKS]

    created = []

    async def _create(org, **kw):
        created.append(kw.get("name"))
        return {"id": str(uuid.uuid4()), "name": kw.get("name"),
                "reused": False}

    monkeypatch.setattr(product_service, "search", _no_exact)
    monkeypatch.setattr("app.database.fetch_many", _catalogue)
    monkeypatch.setattr(product_service, "create", _create)
    row = await inventory_service.find_or_create_catalogue_product(
        uuid.uuid4(), name="office chairs", quantity=1, unit_cost=100,
    )
    assert created == ["office chairs"]  # distinct -> a real new product
    assert row and row.get("reused") is False


@pytest.mark.asyncio
async def test_purchase_sync_exact_match_reuse_carries_honest_flag(monkeypatch):
    async def _exact(*_a, **_k):
        return [{"id": str(uuid.uuid4()), "name": "Office Chair",
                 "product_code": "PRD-000004", "is_stock_tracked": True}]

    async def _never_create(*_a, **_k):
        raise AssertionError("must REUSE, never create a duplicate")

    monkeypatch.setattr(product_service, "search", _exact)
    monkeypatch.setattr(product_service, "create", _never_create)
    row = await inventory_service.find_or_create_catalogue_product(
        uuid.uuid4(), name="office chair", quantity=1, unit_cost=15000,
    )
    assert row and row["name"] == "Office Chair" and row["reused"] is True


@pytest.mark.asyncio
async def test_purchase_sync_creates_only_when_no_match(monkeypatch):
    async def _no_exact(*_a, **_k):
        return []

    async def _no_catalogue(*_a, **_k):
        return []

    created = {}

    async def _create(org_id, **kw):  # noqa: ARG001
        created.update(kw)
        return {"id": str(uuid.uuid4()), "name": kw.get("name"),
                "product_code": "PRD-000009", "is_stock_tracked": True}

    monkeypatch.setattr(product_service, "search", _no_exact)
    monkeypatch.setattr("app.database.fetch_many", _no_catalogue)
    monkeypatch.setattr(product_service, "create", _create)
    row = await inventory_service.find_or_create_catalogue_product(
        uuid.uuid4(), name="standing lamp", quantity=3, unit_cost=7000,
    )
    assert row and row.get("product_code") == "PRD-000009"
    assert created.get("name") == "standing lamp"
    assert created.get("is_stock_tracked") is True
    assert row.get("reused") is not True  # it was CREATED
