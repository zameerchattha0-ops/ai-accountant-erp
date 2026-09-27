"""TREATMENT LADDER pins — the owner directive, end to end.

    "Nature + the CORRECT ACCOUNTING TREATMENT: post to the right ledger
     from the live chart; a relevant-but-not-exact ledger only AFTER
     informing the user; refusal / no relevant ledger -> create the right
     account under the relevant PARENT heading, then post there."

    EXACT   -> posts directly, no interruption                      (llm.validate)
    RELATED -> informed-consent round: contract question carrying
               "the closest existing is '<X>'" + "Should I create it
               under '<HEAD>'" + both answer legs                   (llm.validate)
    NONE    -> proposal + parent_code heading, validated against the
               chart's HEADINGS (wrong/missing section = dropped)   (llm.validate)
    ANSWERS -> "Yes, create it" => create_account + create_parent_name
               "Use <X>" / bare name => entities["account_name"]
               refusal of the related leg => confirms creation        (planner)
    EXECUTE -> confirmed create resolves the validated proposal parent,
               then the "under '<head>'" clause, then the ASSET
               PPE-heading fallback — never an invented parent  (agent helper)
    CONSENT -> the agreed existing account is pinned as a USER_ANSWER
               hint (classifier) and a RELATED hint is never rendered
               as an approved instruction before consent           (prompts)
"""

import uuid

import pytest

from app import llm_classification as llm
from app.llm_classification import CandidateSet, _treatment_question, validate

ORG = uuid.uuid4()

PPE = {
    "id": "11111111-1111-1111-1111-111111111111", "code": "1500",
    "name": "Property, Plant & Equipment", "account_type": "ASSET",
    "normal_balance": "DEBIT",
}
VEH = {
    "id": "22222222-2222-2222-2222-222222222222", "code": "1520",
    "name": "Vehicles", "account_type": "ASSET", "normal_balance": "DEBIT",
}
UTIL = {
    "id": "33333333-3333-3333-3333-333333333333", "code": "6100",
    "name": "Utilities Expense", "account_type": "EXPENSE",
    "normal_balance": "DEBIT",
}
OPEX_HEAD = {
    "id": "44444444-4444-4444-4444-444444444444", "code": "6000",
    "name": "Operating Expenses", "account_type": "EXPENSE",
    "normal_balance": "DEBIT",
}


def _cands(*, headings=True, accounts=None):
    accts = list(accounts) if accounts is not None else [VEH, UTIL]
    heads = [PPE, OPEX_HEAD] if headings else []
    return CandidateSet(accounts=accts, headings=heads)


def _proposal(**kw):
    base = {
        "name": "Motor Vehicles", "code": "1530", "account_type": "ASSET",
        "parent_code": "1500",
    }
    base.update(kw)
    return base


class TestFitSemantics:
    def test_exact_pick_posts_directly(self):
        c = validate(
            {
                "nature": "FIXED_ASSET", "fit": "EXACT",
                "account_id": VEH["id"], "confidence": "HIGH",
                "needs_clarification": False, "rationale": "dedicated ledger",
            },
            candidates=_cands(),
        )
        assert c is not None
        assert c.requires_clarification is False
        assert c.account_hint_id == VEH["id"]
        assert c.account_hint_name == "Vehicles"
        assert c.proposed_account_name is None
        assert c.clarification_reason is None

    def test_fit_none_with_a_picked_account_is_a_contradiction(self):
        assert validate(
            {
                "nature": "FIXED_ASSET", "fit": "NONE",
                "account_id": VEH["id"], "needs_clarification": False,
            },
            candidates=_cands(),
        ) is None

    def test_fit_related_without_an_account_is_rejected(self):
        assert validate(
            {
                "nature": "FIXED_ASSET", "fit": "RELATED",
                "account_id": None, "propose_account": _proposal(),
                "needs_clarification": False,
            },
            candidates=_cands(),
        ) is None

    def test_unknown_fit_is_rejected(self):
        assert validate(
            {
                "nature": "FIXED_ASSET", "fit": "SORT_OF",
                "account_id": VEH["id"], "needs_clarification": False,
            },
            candidates=_cands(),
        ) is None

    def test_exact_fit_with_a_proposal_still_consents(self):
        """A proposal is never silent — it always runs an answer round."""
        c = validate(
            {
                "nature": "FIXED_ASSET", "fit": "EXACT",
                "account_id": VEH["id"], "propose_account": _proposal(),
                "needs_clarification": False,
            },
            candidates=_cands(),
        )
        assert c is not None
        assert c.requires_clarification is True
        assert c.proposed_account_name == "Motor Vehicles"
        assert c.account_hint_id == VEH["id"]


class TestRelatedInformedConsent:
    def _related(self, **over):
        payload = {
            "nature": "FIXED_ASSET", "fit": "RELATED",
            "account_id": VEH["id"], "propose_account": _proposal(),
            "confidence": "HIGH", "needs_clarification": False,
            "options": ["Utilities Expense"],
        }
        payload.update(over)
        return validate(payload, candidates=_cands())

    def test_related_forces_the_contract_question(self):
        import re

        c = self._related()
        assert c is not None
        assert c.requires_clarification is True
        reason = c.clarification_reason or ""
        assert "should i create" in reason.lower()
        m = re.search(r"no '(.+?)' account", reason)
        assert m and m.group(1) == "Motor Vehicles"
        assert "the closest existing is 'Vehicles'" in reason
        assert "under 'Property, Plant & Equipment'" in reason
        # the near-relevant ledger IS the hint (it only posts after consent)
        assert c.account_hint_id == VEH["id"]
        assert c.proposed_parent_id == PPE["id"]
        assert c.proposed_parent_name == "Property, Plant & Equipment"

    def test_related_account_is_the_first_offer(self):
        c = self._related()
        assert c.candidate_accounts
        assert c.candidate_accounts[0] == "Vehicles"

    def test_related_without_proposal_is_rejected(self):
        assert self._related(propose_account=None) is None

    def test_model_phrased_question_is_superseded_by_the_contract(self):
        c = self._related(
            question="Which vehicle ledger do you want?", needs_clarification=True
        )
        reason = c.clarification_reason or ""
        assert "Which vehicle ledger" not in reason
        assert "Should I create it under 'Property, Plant & Equipment'" in reason


class TestProposalParent:
    def test_none_proposal_lands_under_the_heading(self):
        c = validate(
            {
                "nature": "FIXED_ASSET", "fit": "NONE", "account_id": None,
                "propose_account": _proposal(), "needs_clarification": False,
            },
            candidates=_cands(),
        )
        assert c is not None
        assert c.requires_clarification is True
        assert c.account_hint_id is None
        assert c.proposed_account_name == "Motor Vehicles"
        assert c.proposed_parent_id == PPE["id"]
        assert "under 'Property, Plant & Equipment'" in (c.clarification_reason or "")

    def test_missing_parent_code_drops_the_proposal(self):
        """A child in the wrong/absent section is worse than no child."""
        assert validate(
            {
                "nature": "FIXED_ASSET", "fit": "NONE", "account_id": None,
                "propose_account": _proposal(parent_code=None),
                "needs_clarification": False,
            },
            candidates=_cands(),
        ) is None

    def test_unknown_parent_code_drops_the_proposal(self):
        assert validate(
            {
                "nature": "FIXED_ASSET", "fit": "NONE", "account_id": None,
                "propose_account": _proposal(parent_code="9999"),
                "needs_clarification": False,
            },
            candidates=_cands(),
        ) is None

    def test_wrong_section_parent_drops_the_proposal(self):
        assert validate(
            {
                "nature": "FIXED_ASSET", "fit": "NONE", "account_id": None,
                "propose_account": _proposal(parent_code="6000"),  # EXPENSE head
                "needs_clarification": False,
            },
            candidates=_cands(),
        ) is None

    def test_invalid_code_is_dropped_but_the_proposal_stands(self):
        """A free-text code that is not a plain number never reaches the chart."""
        c = validate(
            {
                "nature": "FIXED_ASSET", "fit": "NONE", "account_id": None,
                "propose_account": _proposal(code="AB-12"),
                "needs_clarification": False,
            },
            candidates=_cands(),
        )
        assert c is not None
        assert c.proposed_account_name == "Motor Vehicles"
        assert c.proposed_account_code is None
        assert "(suggested code" not in (c.clarification_reason or "")

    def test_parentless_proposal_when_no_headings_exist(self):
        c = validate(
            {
                "nature": "FIXED_ASSET", "fit": "NONE", "account_id": None,
                "propose_account": _proposal(parent_code=None),
                "needs_clarification": False,
            },
            candidates=_cands(headings=False),
        )
        assert c is not None
        assert c.requires_clarification is True
        assert c.proposed_parent_id is None
        assert "under '" not in (c.clarification_reason or "")


class TestPromptContract:
    def test_candidates_never_contain_headings(self):
        text = llm.build_prompt(
            intent="record_purchase", entities={}, message="bought a car",
            nature_hint=None, candidates=_cands(),
        )
        head_at = text.index("HEADINGS (code | name | account_type)")
        candidates_at = text.index("CANDIDATES (id | code | name | account_type)")
        assert candidates_at < head_at
        posting_block = text[candidates_at:head_at]
        assert "Vehicles" in posting_block
        assert "Property, Plant & Equipment" not in posting_block
        headings_block = text[head_at:]
        assert "Property, Plant & Equipment" in headings_block
        assert "NEVER" in headings_block

    def test_parent_code_rule_is_in_the_prompt(self):
        text = llm.build_prompt(
            intent="record_purchase", entities={}, message="bought a car",
            nature_hint=None, candidates=_cands(),
        )
        assert "parent_code" in text


class TestGatherCandidates:
    @pytest.mark.asyncio
    async def test_heading_split_and_exclusions(self, monkeypatch):
        from app.repositories import account_repository as a_repo

        rows = [
            {"id": "ppe", "code": "1500", "name": "Property, Plant & Equipment",
             "account_type": "ASSET", "parent_account_id": None, "is_active": True},
            {"id": "veh", "code": "1520", "name": "Vehicles",
             "account_type": "ASSET", "parent_account_id": "ppe", "is_active": True},
            {"id": "sal", "code": "6000", "name": "Salaries",
             "account_type": "EXPENSE", "parent_account_id": None, "is_active": True},
            {"id": "os", "code": "6100", "name": "Office Salaries",
             "account_type": "EXPENSE", "parent_account_id": "sal", "is_active": True},
            {"id": "acc", "code": "1590",
             "name": "Accumulated Depreciation - Vehicles",
             "account_type": "ASSET", "parent_account_id": "ppe", "is_active": True},
            {"id": "party", "code": "1100-0007", "name": "ABC Ltd",
             "account_type": "ASSET", "parent_account_id": None, "is_active": True},
            {"id": "dead", "code": "1591", "name": "Old Machinery",
             "account_type": "ASSET", "parent_account_id": None, "is_active": False},
            {"id": "ctrl", "code": "1100", "name": "Accounts Receivable",
             "account_type": "ASSET", "parent_account_id": None,
             "is_active": True, "is_control_account": True},
        ]

        async def fake_chart(org, *, limit=500):
            return rows

        monkeypatch.setattr(a_repo, "get_chart_of_accounts", fake_chart)
        cs = await llm.gather_candidates(ORG)

        names = [a["name"] for a in cs.accounts]
        assert "Vehicles" in names and "Office Salaries" in names
        assert "Property, Plant & Equipment" not in names  # heading, not a posting account
        assert "Salaries" not in names                     # heading
        assert "Accumulated Depreciation - Vehicles" not in names  # contra
        assert "ABC Ltd" not in names                      # party sub-ledger
        assert "Old Machinery" not in names                # inactive
        assert "Accounts Receivable" not in names          # control

        heads = [h["name"] for h in cs.headings]
        assert "Property, Plant & Equipment" in heads and "Salaries" in heads


class TestPlannerAnswerRouting:
    """The contract question -> the answer-merge that routes BOTH legs."""

    RELATED_Q = _treatment_question(
        proposed_name="Motor Vehicles", proposed_code="1530",
        parent_name="Property, Plant & Equipment",
        related_name="Vehicles", related_code="1520",
    )
    NONE_Q = _treatment_question(
        proposed_name="Motor Vehicles", proposed_code="1530",
        parent_name="Property, Plant & Equipment",
    )

    def _merge(self, question, answer):
        from app.planner import _merge_clarification_answers

        return _merge_clarification_answers(
            {}, [{"question": question, "answer": answer}]
        )

    def test_yes_confirms_creation_under_the_heading(self):
        merged = self._merge(self.RELATED_Q, "Yes, create it")
        assert merged.get("create_account") == "Motor Vehicles"
        assert merged.get("create_parent_name") == "Property, Plant & Equipment"

    def test_use_related_pins_that_ledger_instead(self):
        merged = self._merge(self.RELATED_Q, "Use Vehicles")
        assert merged.get("account_name") == "vehicles"
        assert not merged.get("create_account")

    def test_bare_name_pins_that_ledger(self):
        merged = self._merge(self.RELATED_Q, "Vehicles")
        assert merged.get("account_name") == "vehicles"

    def test_refusing_the_related_leg_confirms_creation(self):
        for answer in ("No", "no, don't use it", "neither", "None of those"):
            merged = self._merge(self.RELATED_Q, answer)
            assert merged.get("create_account") == "Motor Vehicles", answer
            assert merged.get("create_parent_name") == "Property, Plant & Equipment"

    def test_refusal_without_a_related_leg_never_presses_create(self):
        merged = self._merge(self.NONE_Q, "No")
        assert not merged.get("create_account")

    def test_yes_without_an_under_clause_leaves_parent_unset(self):
        q = _treatment_question(
            proposed_name="Bonus", proposed_code=None, parent_name=None
        )
        merged = self._merge(q, "Yes, create it")
        assert merged.get("create_account") == "Bonus"
        assert not merged.get("create_parent_name")


class TestConfirmedCreateParent:
    @pytest.mark.asyncio
    async def test_under_clause_resolves_the_heading(self, monkeypatch):
        from app import classifier

        async def fake_exists(org, name):
            return PPE if name == "Property, Plant & Equipment" else None

        async def fake_code(org, nature, name):
            return "1530"

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)
        monkeypatch.setattr(classifier, "_confirmed_account_code", fake_code)

        c = await classifier.classify_transaction(
            organization_id=ORG,
            intent="record_purchase",
            entities={
                "create_account": "Motor Vehicles",
                "create_parent_name": "Property, Plant & Equipment",
                "transaction_nature": "FIXED_ASSET",
                "item_description": "car",
            },
        )
        assert c.create_account_confirmed is True
        assert c.proposed_account_name == "Motor Vehicles"
        assert c.proposed_account_code == "1530"
        assert c.proposed_parent_id == PPE["id"]
        assert c.proposed_parent_name == "Property, Plant & Equipment"

    @pytest.mark.asyncio
    async def test_wrong_section_parent_is_ignored(self, monkeypatch):
        from app import classifier

        async def fake_exists(org, name):
            return OPEX_HEAD if name == "Operating Expenses" else None

        async def fake_code(org, nature, name):
            return "6100"

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)
        monkeypatch.setattr(classifier, "_confirmed_account_code", fake_code)

        c = await classifier.classify_transaction(
            organization_id=ORG,
            intent="record_purchase",
            entities={
                "create_account": "Track Car",
                "create_parent_name": "Operating Expenses",  # EXPENSE head
                "transaction_nature": "FIXED_ASSET",
                "item_description": "car",
            },
        )
        assert c.create_account_confirmed is True
        assert c.proposed_parent_id is None  # a wrong-section parent is never used


class TestUserAgreedConsent:
    @pytest.mark.asyncio
    async def test_agreed_existing_account_is_pinned_as_user_answer(self, monkeypatch):
        from app import classifier

        async def fake_exists(org, name):
            return VEH if str(name).lower() == "vehicles" else None

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)

        c = await classifier.classify_transaction(
            organization_id=ORG,
            intent="record_purchase",
            entities={
                "account_name": "vehicles",
                "transaction_nature": "FIXED_ASSET",
                "item_description": "car",
            },
        )
        assert c.source == "USER_ANSWER"
        assert c.account_hint_id == VEH["id"]
        assert c.account_hint_name == "Vehicles"
        assert c.requires_clarification is False
        assert c.transaction_nature == "FIXED_ASSET"

    @pytest.mark.asyncio
    async def test_agreed_name_from_the_wrong_section_is_not_pinned(self, monkeypatch):
        from app import classifier

        async def fake_exists(org, name):
            return UTIL if str(name).lower() == "utilities expense" else None

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)

        c = await classifier.classify_transaction(
            organization_id=ORG,
            intent="record_purchase",
            entities={
                "account_name": "Utilities Expense",
                "transaction_nature": "FIXED_ASSET",
                "item_description": "car",
            },
            resolve_account_hints=False,
        )
        assert c.account_hint_id != UTIL["id"]


class TestConfirmedCreateArgs:
    @pytest.mark.asyncio
    async def test_validated_proposal_parent_wins(self, monkeypatch):
        from app.agent import _confirmed_create_args
        from app.models.schemas import TransactionClassification

        async def boom(*args, **kwargs):  # pragma: no cover
            raise AssertionError("no lookup expected for a validated parent")

        monkeypatch.setattr("app.account_resolution.account_exists", boom)
        monkeypatch.setattr("app.account_resolution.heading_account_id", boom)

        cls = TransactionClassification(
            transaction_nature="FIXED_ASSET",
            proposed_account_name="Motor Vehicles",
            proposed_account_code="1530",
            proposed_parent_id=PPE["id"],
            proposed_parent_name="Property, Plant & Equipment",
        )
        args = await _confirmed_create_args(
            cls, ORG, entities={}, name="Motor Vehicles"
        )
        assert args["name"] == "Motor Vehicles"
        assert args["account_type"] == "ASSET"
        assert args["normal_balance"] == "DEBIT"
        assert args["code"] == "1530"
        assert args["parent_account_id"] == PPE["id"]

    @pytest.mark.asyncio
    async def test_under_clause_parent_is_type_checked(self, monkeypatch):
        from app.agent import _confirmed_create_args
        from app.models.schemas import TransactionClassification

        async def fake_exists(org, name):
            return PPE if name == "Property, Plant & Equipment" else None

        async def fake_heading(org, *, nature):
            return None

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)
        monkeypatch.setattr("app.account_resolution.heading_account_id", fake_heading)

        cls = TransactionClassification(
            transaction_nature="FIXED_ASSET", proposed_account_name="Motor Vehicles"
        )
        args = await _confirmed_create_args(
            cls, ORG,
            entities={"create_parent_name": "Property, Plant & Equipment"},
            name=None,
        )
        assert args["parent_account_id"] == PPE["id"]

    @pytest.mark.asyncio
    async def test_asset_falls_back_to_the_ppe_heading(self, monkeypatch):
        from app.agent import _confirmed_create_args
        from app.models.schemas import TransactionClassification

        async def fake_exists(org, name):
            return None

        async def fake_heading(org, *, nature):
            return PPE["id"]

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)
        monkeypatch.setattr("app.account_resolution.heading_account_id", fake_heading)

        cls = TransactionClassification(
            transaction_nature="FIXED_ASSET", proposed_account_name="Motor Vehicles"
        )
        args = await _confirmed_create_args(cls, ORG, entities={}, name=None)
        assert args["parent_account_id"] == PPE["id"]

    @pytest.mark.asyncio
    async def test_expense_without_a_parent_stays_top_level(self, monkeypatch):
        from app.agent import _confirmed_create_args
        from app.models.schemas import TransactionClassification

        async def boom(*args, **kwargs):  # pragma: no cover
            raise AssertionError("EXPENSE must never get a fallback parent")

        monkeypatch.setattr("app.account_resolution.heading_account_id", boom)

        cls = TransactionClassification(
            transaction_nature="OPERATING_EXPENSE", proposed_account_name="Bonus"
        )
        args = await _confirmed_create_args(cls, ORG, entities={}, name=None)
        assert "parent_account_id" not in args


class TestPromptConsentGate:
    def _ctx(self, cls):
        from app.models.schemas import AgentContext

        return AgentContext(organization={}, user={}, classification=cls)

    def test_related_hint_is_not_an_approved_instruction(self):
        from app.models.schemas import TransactionClassification
        from app.prompts import build_user_content

        cls = TransactionClassification(
            transaction_nature="FIXED_ASSET",
            account_hint_id=VEH["id"], account_hint_code="1520",
            account_hint_name="Vehicles", requires_clarification=True,
        )
        text = build_user_content("bought a car", self._ctx(cls))
        assert "NOT yet approved" in text
        assert "Do NOT record to it yet" in text

    def test_approved_hint_keeps_the_recording_instruction(self):
        from app.models.schemas import TransactionClassification
        from app.prompts import build_user_content

        cls = TransactionClassification(
            transaction_nature="FIXED_ASSET",
            account_hint_id=VEH["id"], account_hint_code="1520",
            account_hint_name="Vehicles", requires_clarification=False,
        )
        text = build_user_content("bought a car", self._ctx(cls))
        assert "Account hint: 1520 Vehicles" in text
        assert "NOT yet approved" not in text
