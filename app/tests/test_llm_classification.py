"""
LLM DECISION LAYER pins (app/llm_classification.py)
===================================================
The classifier's REASONING zones belong to the LLM: nature decisions
(income vs expense, asset vs liability, capitalise vs expense) and the
account that receives the posting.  Python gathers candidates, validates
every pick against accounting invariants, and falls back to the
deterministic chain when the layer is off/unreachable/invalid.

THE PRODUCTION INCIDENT PINNED HERE: "bought a motorbike on credit" was
debited to 1500 Computer Equipment because the deterministic term search
("computer equipment" first) matched before any item-relevance check.
With the decision layer on, the model picks the Vehicles account (or asks
/ proposes it); a pick that violates the nature's account types is
REJECTED and the deterministic fallback runs â€” never the wrong debit.
"""

import json
import uuid

import pytest

import app.classifier as clf
import app.llm_classification as llm_cls
from app.config import get_settings

ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture(autouse=True)
def _offline_repositories(offline_account_lookups):
    """The classifier's account searches must not query the live chart.

    See app/tests/conftest.py::_no_live_database: these lookups are best-effort
    and swallow failures, so a real round-trip (or its timeout) silently chose
    which branch of the classifier ran.
    """
    return None

CE_ID = str(uuid.uuid4())       # 1500 Computer Equipment (ASSET)
VEH_ID = str(uuid.uuid4())      # 1530 Vehicles (ASSET)
UTIL_ID = str(uuid.uuid4())     # 6100 Utilities Expense (EXPENSE)
SALES_ID = str(uuid.uuid4())    # 4100 Sales Revenue (REVENUE)
LOAN_ID = str(uuid.uuid4())     # 2100 Bank Loan (LIABILITY)
CAP_ID = str(uuid.uuid4())      # 3000 Owner's Capital (EQUITY)


def _rows():
    return [
        {"id": CE_ID, "code": "1500", "name": "Computer Equipment",
         "account_type": "ASSET", "normal_balance": "DEBIT", "is_active": True,
         "is_control_account": False},
        {"id": VEH_ID, "code": "1530", "name": "Vehicles",
         "account_type": "ASSET", "normal_balance": "DEBIT", "is_active": True,
         "is_control_account": False},
        {"id": UTIL_ID, "code": "6100", "name": "Utilities Expense",
         "account_type": "EXPENSE", "normal_balance": "DEBIT", "is_active": True,
         "is_control_account": False},
        {"id": SALES_ID, "code": "4100", "name": "Sales Revenue",
         "account_type": "REVENUE", "normal_balance": "CREDIT", "is_active": True,
         "is_control_account": False},
        {"id": LOAN_ID, "code": "2100", "name": "Bank Loan",
         "account_type": "LIABILITY", "normal_balance": "CREDIT", "is_active": True,
         "is_control_account": False},
        {"id": CAP_ID, "code": "3000", "name": "Owner's Capital",
         "account_type": "EQUITY", "normal_balance": "CREDIT", "is_active": True,
         "is_control_account": False},
        # --- must ALL be filtered out of the candidate set ----------------
        {"id": str(uuid.uuid4()), "code": "1590", "name": "Accumulated Depreciation",
         "account_type": "ASSET", "normal_balance": "CREDIT", "is_active": True,
         "is_control_account": False},
        {"id": str(uuid.uuid4()), "code": "1100", "name": "Accounts Receivable",
         "account_type": "ASSET", "normal_balance": "DEBIT", "is_active": True,
         "is_control_account": True},
        {"id": str(uuid.uuid4()), "code": "1100-0001", "name": "Acme (receivable)",
         "account_type": "ASSET", "normal_balance": "DEBIT", "is_active": True,
         "is_control_account": False},
        {"id": str(uuid.uuid4()), "code": "9999", "name": "Closed Ledger",
         "account_type": "EXPENSE", "normal_balance": "DEBIT", "is_active": False,
         "is_control_account": False},
    ]


def _candidates() -> llm_cls.CandidateSet:
    return llm_cls.CandidateSet(accounts=[
        r for r in _rows()
        if r["is_active"] and not r["is_control_account"]
        and "accumulated" not in r["name"].lower()
        and "-" not in r["code"]
    ])


def _enable(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "llm_classification_enabled", True
    )


class _StubClient:
    """Provider stub: canned light-tier reply (or an error to raise)."""

    def __init__(self, reply=None, error=None):
        self._reply = reply
        self._error = error
        self.prompts = []

    async def generate_text_light(self, *a, **k):
        self.prompts.append(k.get("prompt") or (a[0] if a else ""))
        if self._error is not None:
            raise self._error
        return self._reply


def _reply(**payload) -> str:
    base = {
        "nature": None, "account_id": None, "confidence": "HIGH",
        "needs_clarification": False, "question": "", "options": [],
        "propose_account": None, "rationale": "test",
    }
    base.update(payload)
    return json.dumps(base)


# ---------------------------------------------------------------------------
# gather_candidates â€” the FILTERS (contra / control / party / inactive)
# ---------------------------------------------------------------------------
class TestGatherCandidates:
    @pytest.mark.asyncio
    async def test_filters_non_posting_accounts(self, monkeypatch):
        async def fake_chart(*a, **k):
            return _rows()

        monkeypatch.setattr(
            "app.repositories.account_repository.get_chart_of_accounts",
            fake_chart,
        )
        cs = await llm_cls.gather_candidates(ORG)
        codes = {a["code"] for a in cs.accounts}
        assert codes == {"1500", "1530", "6100", "4100", "2100", "3000"}



# ---------------------------------------------------------------------------
# validate() â€” the invariants. Every violation â†’ None â†’ deterministic
# fallback (never a partial decision).
# ---------------------------------------------------------------------------
class TestValidationInvariants:
    def test_valid_pick_accepted(self):
        c = llm_cls.validate(
            {"nature": "FIXED_ASSET", "account_id": VEH_ID, "confidence": "HIGH",
             "needs_clarification": False, "question": "", "options": [],
             "propose_account": None, "rationale": "motorbike"},
            candidates=_candidates(),
        )
        assert c is not None
        assert c.transaction_nature == "FIXED_ASSET"
        assert c.account_hint_id == VEH_ID
        assert c.account_hint_name == "Vehicles"
        assert c.source == "LLM_DECISION"
        assert c.requires_clarification is False

    def test_unknown_nature_rejected(self):
        c = llm_cls.validate(
            {"nature": "WIDGETS", "account_id": VEH_ID},
            candidates=_candidates(),
        )
        assert c is None

    def test_account_not_in_candidates_rejected(self):
        c = llm_cls.validate(
            {"nature": "FIXED_ASSET", "account_id": str(uuid.uuid4())},
            candidates=_candidates(),
        )
        assert c is None

    def test_account_type_not_fitting_nature_rejected(self):
        # FIXED_ASSET may only carry an ASSET account â€” a utilities expense
        # account is a wrong posting, not a taste choice.
        c = llm_cls.validate(
            {"nature": "FIXED_ASSET", "account_id": UTIL_ID},
            candidates=_candidates(),
        )
        assert c is None

    def test_normal_balance_inconsistency_rejected(self):
        cands = _candidates()
        cands.accounts.append({
            "id": "bad-1", "code": "6199", "name": "Broken Expense",
            "account_type": "EXPENSE", "normal_balance": "CREDIT",
            "is_active": True, "is_control_account": False,
        })
        c = llm_cls.validate(
            {"nature": "OPERATING_EXPENSE", "account_id": "bad-1"},
            candidates=cands,
        )
        assert c is None

    def test_clarify_without_question_rejected(self):
        c = llm_cls.validate(
            {"nature": None, "needs_clarification": True, "question": ""},
            candidates=_candidates(),
        )
        assert c is None

    def test_do_nothing_decision_rejected(self):
        c = llm_cls.validate(
            {"nature": "FIXED_ASSET", "account_id": None,
             "needs_clarification": False, "propose_account": None},
            candidates=_candidates(),
        )
        assert c is None


# ---------------------------------------------------------------------------
# INCOME vs EXPENSE and ASSET vs LIABILITY â€” the decisions the old 9-value
# vocabulary could not even express (REVENUE/LIABILITY/EQUITY added).
# ---------------------------------------------------------------------------
class TestCrossStatementDecisions:
    def test_income_decision_routes_to_revenue(self):
        c = llm_cls.validate(
            {"nature": "REVENUE", "account_id": SALES_ID, "confidence": "HIGH",
             "needs_clarification": False, "question": "", "options": [],
             "propose_account": None, "rationale": "sale of goods"},
            candidates=_candidates(),
            entity="goods sold",
        )
        assert c is not None and c.transaction_nature == "REVENUE"
        assert c.account_hint_name == "Sales Revenue"

    def test_liability_decision_routes_to_liability(self):
        c = llm_cls.validate(
            {"nature": "LIABILITY", "account_id": LOAN_ID, "confidence": "HIGH",
             "needs_clarification": False, "question": "", "options": [],
             "propose_account": None, "rationale": "bank loan received"},
            candidates=_candidates(),
        )
        assert c is not None and c.transaction_nature == "LIABILITY"
        assert c.account_hint_name == "Bank Loan"

    def test_equity_decision_routes_to_equity(self):
        c = llm_cls.validate(
            {"nature": "EQUITY", "account_id": CAP_ID, "confidence": "HIGH",
             "needs_clarification": False, "question": "", "options": [],
             "propose_account": None, "rationale": "owner paid in capital"},
            candidates=_candidates(),
        )
        assert c is not None and c.transaction_nature == "EQUITY"

    def test_expense_nature_with_revenue_account_rejected(self):
        # Income vs expense: an EXPENSE nature may never post to Sales.
        c = llm_cls.validate(
            {"nature": "OPERATING_EXPENSE", "account_id": SALES_ID},
            candidates=_candidates(),
        )
        assert c is None

    def test_asset_nature_with_liability_account_rejected(self):
        # Asset vs liability: acquiring an asset never posts into a loan.
        c = llm_cls.validate(
            {"nature": "FIXED_ASSET", "account_id": LOAN_ID},
            candidates=_candidates(),
        )
        assert c is None

    def test_nature_hint_is_authoritative_over_model(self):
        # The user SAID fixed asset; the model's OPERATING_EXPENSE is
        # overridden and the utilities pick then fails the hint's types.
        c = llm_cls.validate(
            {"nature": "OPERATING_EXPENSE", "account_id": UTIL_ID},
            candidates=_candidates(),
            nature_hint="FIXED_ASSET",
        )
        assert c is None  # hint forced FIXED_ASSET â†’ UTIL no longer fits
        c2 = llm_cls.validate(
            {"nature": "OPERATING_EXPENSE", "account_id": VEH_ID},
            candidates=_candidates(),
            nature_hint="FIXED_ASSET",
        )
        assert c2 is not None and c2.transaction_nature == "FIXED_ASSET"


# ---------------------------------------------------------------------------
# Ask-when-missing and propose-the-missing-ledger (the owner's directive:
# a missing prerequisite is DETECTED and asked for, never silently guessed).
# ---------------------------------------------------------------------------
class TestClarifyAndPropose:
    def test_clarify_keeps_only_existing_candidate_options(self):
        c = llm_cls.validate(
            {"nature": None, "needs_clarification": True,
             "question": "Is this a vehicle for business use or for resale?",
             "options": ["Vehicles", "Made-Up Ledger", "Utilities Expense"],
             "account_id": None, "propose_account": None},
            candidates=_candidates(),
        )
        assert c is not None and c.requires_clarification is True
        assert c.candidate_accounts == ["Vehicles", "Utilities Expense"]

    def test_propose_missing_ledger_produces_confirmation_round(self):
        c = llm_cls.validate(
            {"nature": "FIXED_ASSET", "account_id": None,
             "needs_clarification": False, "question": "", "options": [],
             "propose_account": {"name": "Motor Vehicles", "code": "1530",
                                 "account_type": "ASSET"},
             "confidence": "HIGH", "rationale": "no vehicle ledger exists"},
            candidates=_candidates(),
        )
        assert c is not None
        assert c.proposed_account_name == "Motor Vehicles"
        assert c.proposed_account_code == "1530"
        # Never silent: creation goes through the user-confirmation round.
        assert c.requires_clarification is True
        assert "Motor Vehicles" in (c.clarification_reason or "")

    def test_proposal_type_not_fitting_nature_dropped(self):
        c = llm_cls.validate(
            {"nature": "LIABILITY", "account_id": None,
             "needs_clarification": True, "question": "Which lender?",
             "options": [],
             "propose_account": {"name": "Bad", "code": "1530",
                                 "account_type": "ASSET"}},
            candidates=_candidates(),
        )
        # The proposal is dropped; the question still stands.
        assert c is not None and c.requires_clarification is True
        assert c.proposed_account_name is None


# ---------------------------------------------------------------------------
# decide() â€” the round-trip with graceful degradation to the rule chain.
# ---------------------------------------------------------------------------
class TestDecideRoundTrip:
    @pytest.mark.asyncio
    async def test_disabled_returns_none_without_provider_call(self, monkeypatch):
        client = _StubClient(reply=_reply(nature="FIXED_ASSET", account_id=VEH_ID))
        out = await llm_cls.decide(
            organization_id=ORG, intent="record_credit_purchase",
            entities={"item_description": "motorbike"}, message="bought a motorbike",
            client=client,
        )
        assert out is None and client.prompts == []

    @pytest.mark.asyncio
    async def test_valid_reply_returns_classification(self, monkeypatch):
        _enable(monkeypatch)

        async def fake_chart(*a, **k):
            return _rows()

        monkeypatch.setattr(
            "app.repositories.account_repository.get_chart_of_accounts",
            fake_chart,
        )
        client = _StubClient(reply=_reply(
            nature="FIXED_ASSET", account_id=VEH_ID, rationale="vehicle for use",
        ))
        out = await llm_cls.decide(
            organization_id=ORG, intent="record_credit_purchase",
            entities={"item_description": "motorbike"}, message="bought a motorbike",
            client=client,
        )
        assert out is not None
        assert out.transaction_nature == "FIXED_ASSET"
        assert out.account_hint_name == "Vehicles"
        assert out.source == "LLM_DECISION"

    @pytest.mark.asyncio
    async def test_provider_failure_returns_none(self, monkeypatch):
        _enable(monkeypatch)

        async def fake_chart(*a, **k):
            return _rows()

        monkeypatch.setattr(
            "app.repositories.account_repository.get_chart_of_accounts",
            fake_chart,
        )
        client = _StubClient(error=RuntimeError("provider down"))
        out = await llm_cls.decide(
            organization_id=ORG, intent="record_credit_purchase",
            entities={"item_description": "motorbike"}, client=client,
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_assertion_error_is_never_swallowed(self, monkeypatch):
        _enable(monkeypatch)

        async def fake_chart(*a, **k):
            return _rows()

        monkeypatch.setattr(
            "app.repositories.account_repository.get_chart_of_accounts",
            fake_chart,
        )
        client = _StubClient(error=AssertionError("test no-LLM guard"))
        with pytest.raises(AssertionError):
            await llm_cls.decide(
                organization_id=ORG, intent="record_credit_purchase",
                entities={"item_description": "motorbike"}, client=client,
            )

    @pytest.mark.asyncio
    async def test_unparseable_reply_returns_none(self, monkeypatch):
        _enable(monkeypatch)

        async def fake_chart(*a, **k):
            return _rows()

        monkeypatch.setattr(
            "app.repositories.account_repository.get_chart_of_accounts",
            fake_chart,
        )
        client = _StubClient(reply="I think it is a vehicle, probably.")
        out = await llm_cls.decide(
            organization_id=ORG, intent="record_credit_purchase",
            entities={"item_description": "motorbike"}, client=client,
        )
        assert out is None


# ---------------------------------------------------------------------------
# classify_transaction INTEGRATION — the judgment zones consult the layer,
# and the deterministic chain remains the fallback.
# ---------------------------------------------------------------------------
class TestClassifierIntegration:
    @pytest.mark.asyncio
    async def test_motorbike_credit_purchase_routes_to_vehicles(
        self, monkeypatch
    ):
        """THE PRODUCTION INCIDENT: 'Purchased two Bikes on credit' must NOT
        debit 1500 Computer Equipment — the model decides FIXED_ASSET +
        Vehicles from the live candidates."""
        _enable(monkeypatch)

        async def fake_chart(*a, **k):
            return _rows()

        monkeypatch.setattr(
            "app.repositories.account_repository.get_chart_of_accounts",
            fake_chart,
        )
        monkeypatch.setattr(
            "app.ai_orchestrator.get_client",
            lambda: _StubClient(reply=_reply(
                nature="FIXED_ASSET", account_id=VEH_ID,
                rationale="motorbike is a vehicle used in the business",
            )),
        )

        result = await clf.classify_transaction(
            organization_id=ORG,
            intent="record_credit_purchase",
            entities={"item_description": "two bikes",
                      "supplier_name": "Beta Autos", "amount": 3400000},
            message="I purchased two Bikes from Beta Autos on credit",
        )
        assert result.transaction_nature == "FIXED_ASSET"
        assert result.account_hint_name == "Vehicles"
        assert result.account_hint_name != "Computer Equipment"
        assert result.source == "LLM_DECISION"
        assert result.requires_clarification is False

    @pytest.mark.asyncio
    async def test_invalid_pick_falls_back_to_deterministic_chain(
        self, monkeypatch
    ):
        """A model pick that violates the nature (EXPENSE account for a
        FIXED_ASSET) is REJECTED — the deterministic chain decides instead
        (here: the durable-goods clarifying question), never a wrong debit."""
        _enable(monkeypatch)

        async def fake_chart(*a, **k):
            return _rows()

        monkeypatch.setattr(
            "app.repositories.account_repository.get_chart_of_accounts",
            fake_chart,
        )
        monkeypatch.setattr(
            "app.ai_orchestrator.get_client",
            lambda: _StubClient(reply=_reply(
                nature="FIXED_ASSET", account_id=UTIL_ID,  # EXPENSE — invalid
            )),
        )
        # Deterministic fallback must not touch the DB in this test:
        async def no_products(*a, **k):
            return []

        monkeypatch.setattr("app.database.fetch_many", no_products)

        result = await clf.classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={"item_description": "two bikes", "amount": 3400000},
            message="I purchased two Bikes from Beta Autos on credit",
        )
        # Rejected by validation → fallback ran; source is NOT LLM_DECISION.
        assert result.source != "LLM_DECISION"
        assert result.transaction_nature != "FIXED_ASSET" or \
            result.account_hint_id != UTIL_ID

    @pytest.mark.asyncio
    async def test_disabled_layer_keeps_deterministic_classification(
        self, monkeypatch
    ):
        """With the layer off the old behaviour is byte-identical: the
        explicit user nature survives with its honest provenance."""
        result = await clf.classify_transaction(
            organization_id=ORG,
            intent="record_expense",
            entities={"transaction_nature": "OPERATING_EXPENSE",
                      "item_description": "computers"},
            message="i purchased 3 computers",
            resolve_account_hints=False,
        )
        assert result.transaction_nature == "OPERATING_EXPENSE"
        assert result.source == "USER_ANSWER"
        assert result.requires_clarification is False

