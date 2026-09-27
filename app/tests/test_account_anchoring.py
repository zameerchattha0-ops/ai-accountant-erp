"""ACCOUNT ANCHORING pins — Python never picks a ledger by term order.

Production incident (Task C): a motorbike purchase was debited to
"1500 Computer Equipment" because ``_search_account_by_nature(FIXED_ASSET,
…)`` iterated bare terms ("computer equipment", "office equipment", …) and
returned the FIRST term with ANY match — regardless of item relevance.
Deciding that a motorbike IS "computer equipment" is a SEMANTIC judgement;
the LLM decision layer (app/llm_classification.py) owns it.  The
deterministic chain may only return:

    (a) an account the ITEM ITSELF names  ("3 computers" → Computer
        Equipment) — a measurable fact; or
    (b) a curated item→category expense rule ("electricity" → Utilities
        Expense) — a deterministic mapping, never term order.

Anything else returns None and the flow CLARIFIES — offering the existing
accounts plus creation of the right account under the right heading — so a
wrong ledger is never silently debited.
"""

import uuid

import pytest

from app import classifier as clf

ORG = uuid.uuid4()

CHART = [
    {"id": "ce", "code": "1500", "name": "Computer Equipment",
     "account_type": "ASSET", "is_active": True},
    {"id": "mv", "code": "1520", "name": "Motor Vehicles",
     "account_type": "ASSET", "is_active": True},
    {"id": "od", "code": "1590",
     "name": "Accumulated Depreciation - Computer Equipment",
     "account_type": "ASSET", "is_active": True},
    {"id": "ut", "code": "6100", "name": "Utilities Expense",
     "account_type": "EXPENSE", "is_active": True},
    {"id": "sa", "code": "6200", "name": "Salaries Expense",
     "account_type": "EXPENSE", "is_active": True},
]


@pytest.fixture(autouse=True)
def _chart(monkeypatch):
    from app.repositories import account_repository as a_repo

    async def fake_search(org, *, query, limit=50):
        q = (query or "").lower()
        return [
            a for a in CHART
            if q in (a.get("name") or "").lower() or q in (a.get("code") or "")
        ]

    async def fake_chart(org, *, account_type=None, is_active=True, limit=500):
        return [
            a for a in CHART
            if account_type is None or a.get("account_type") == account_type
        ]

    monkeypatch.setattr(a_repo, "search_accounts", fake_search)
    monkeypatch.setattr(a_repo, "get_chart_of_accounts", fake_chart)


class TestAnchoredAcceptance:
    @pytest.mark.asyncio
    async def test_the_incident_motorbike_never_matches_computer_equipment(self):
        """Term "computer equipment" matches 1500 — the item does not."""
        found = await clf._search_account_by_nature(ORG, "FIXED_ASSET", "motorbike")
        assert found is None

    @pytest.mark.asyncio
    async def test_an_item_that_names_the_account_anchors(self):
        found = await clf._search_account_by_nature(ORG, "FIXED_ASSET", "3 computers")
        assert found is not None
        assert found["name"] == "Computer Equipment"

    @pytest.mark.asyncio
    async def test_semantic_category_is_not_guessed_in_the_fallback(self):
        """laptop → Computer Equipment needs the LLM; the chain stays silent."""
        assert await clf._search_account_by_nature(ORG, "FIXED_ASSET", "laptop") is None

    @pytest.mark.asyncio
    async def test_vehicle_word_anchors_motor_vehicles(self):
        found = await clf._search_account_by_nature(ORG, "FIXED_ASSET", "vehicle")
        assert found is not None
        assert found["name"] == "Motor Vehicles"

    @pytest.mark.asyncio
    async def test_curated_expense_mapping_still_routes(self):
        found = await clf._search_account_by_nature(
            ORG, "OPERATING_EXPENSE", "electricity bill"
        )
        assert found is not None
        assert found["name"] == "Utilities Expense"

    @pytest.mark.asyncio
    async def test_a_contra_account_never_decides_even_when_anchored(self):
        found = await clf._search_account_by_nature(
            ORG, "FIXED_ASSET", "accumulated depreciation computers"
        )
        # the contra is rejected outright; the legitimate ledger wins
        assert found is not None
        assert found["name"] == "Computer Equipment"

    @pytest.mark.asyncio
    async def test_unmapped_expense_without_an_anchor_stays_open(self):
        """'bonus' must not land in Salaries just because 'salaries' matched."""
        assert await clf._search_account_by_nature(
            ORG, "OPERATING_EXPENSE", "staff bonus payout"
        ) is None


class TestClassifierEscalates:
    @pytest.mark.asyncio
    async def test_user_stated_fixed_asset_without_anchor_asks(self):
        """The incident end-to-end: NEVER Computer Equipment for a motorbike."""
        result = await clf.classify_transaction(
            organization_id=ORG,
            intent="record_purchase",
            entities={
                "item_description": "motorbike",
                "transaction_nature": "FIXED_ASSET",
                "amount": 320000,
            },
            message="I purchased a motorbike for 320000 on credit",
        )
        assert result.account_hint_id is None
        assert result.account_hint_name is None
        assert result.requires_clarification is True
        assert "No fixed-asset account" in (result.clarification_reason or "")

    @pytest.mark.asyncio
    async def test_the_llm_decision_is_used_verbatim_when_available(self, monkeypatch):
        """Python never overrides the model: its deliberate pick stands."""
        from app.models.schemas import TransactionClassification

        async def fake_decision(org, *, intent, entities, message, nature_hint=None):
            return TransactionClassification(
                transaction_nature=nature_hint or "FIXED_ASSET",
                confidence="HIGH",
                source="LLM_DECISION",
                account_hint_id="ce",
                account_hint_code="1500",
                account_hint_name="Computer Equipment",
                requires_clarification=False,
            )

        monkeypatch.setattr(clf, "_llm_decision", fake_decision)
        result = await clf.classify_transaction(
            organization_id=ORG,
            intent="record_purchase",
            entities={
                "item_description": "motorbike",
                "transaction_nature": "FIXED_ASSET",
                "amount": 320000,
            },
            message="I purchased a motorbike for 320000 on credit",
        )
        assert result.account_hint_name == "Computer Equipment"
        # honest provenance: the nature stayed the user's, the account the model's
        assert result.source == "USER_ANSWER"
