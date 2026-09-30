"""The statement-SECTION invariant for category-ledger parents.

"Accounts Receivable" is an ASSET, so the old TYPE-only parent check happily
parented a newly created "Vehicles" ledger under it (production 2026-09-30:
the reasoning payload carried ``create_parent_name: Accounts Receivable``).
A parent must be in the same section as the nature's shape, so receivables,
cash/bank, inventory, tax and contra accounts are never acceptable parents
for a PPE-style category.

Covers the two enforcement points (the classifier's proposal and the agent's
confirmed-create helper) plus the shared predicate itself.
"""

from types import SimpleNamespace
import uuid

import pytest

from app.account_resolution import is_category_parent

AR = {
    "id": "55555555-5555-5555-5555-555555555555",
    "code": "1200",
    "name": "Accounts Receivable",
    "account_type": "ASSET",
    "normal_balance": "DEBIT",
}
PPE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "code": "1500",
    "name": "Property, Plant & Equipment",
    "account_type": "ASSET",
    "normal_balance": "DEBIT",
}
VEH = {
    "id": "22222222-2222-2222-2222-222222222222",
    "code": "1520",
    "name": "Vehicles",
    "account_type": "ASSET",
    "normal_balance": "DEBIT",
}
CASH = {
    "id": "66666666-6666-6666-6666-666666666666",
    "code": "1100",
    "name": "Cash on Hand",
    "account_type": "ASSET",
    "normal_balance": "DEBIT",
}
ACCUM = {
    "id": "77777777-7777-7777-7777-777777777777",
    "code": "1590",
    "name": "Accumulated Depreciation - Vehicles",
    "account_type": "ASSET",
    "normal_balance": "DEBIT",
}
OPEX_HEAD = {
    "id": "44444444-4444-4444-4444-444444444444",
    "code": "6000",
    "name": "Operating Expenses",
    "account_type": "EXPENSE",
    "normal_balance": "DEBIT",
}


class TestIsCategoryParent:
    def test_the_reported_defect_is_rejected(self):
        """Vehicles under Accounts Receivable — same type, wrong section."""
        assert is_category_parent(AR, nature="FIXED_ASSET") is False

    def test_real_pp_and_asset_headings_are_accepted(self):
        assert is_category_parent(PPE, nature="FIXED_ASSET") is True
        assert is_category_parent(VEH, nature="FIXED_ASSET") is True

    @pytest.mark.parametrize(
        "account",
        [CASH, ACCUM,
         {"code": "1150", "name": "Inventories", "account_type": "ASSET"},
         {"code": "1400", "name": "Prepaid Expenses", "account_type": "ASSET"},
         {"code": "2100", "name": "Trade Payables", "account_type": "LIABILITY"}],
    )
    def test_current_asset_settlement_and_contra_sections_are_rejected(
        self, account
    ):
        assert is_category_parent(account, nature="FIXED_ASSET") is False

    def test_a_type_mismatch_is_rejected(self):
        assert is_category_parent(OPEX_HEAD, nature="FIXED_ASSET") is False

    def test_expense_natures_may_parent_under_an_expense_head(self):
        assert is_category_parent(OPEX_HEAD, nature="OPERATING_EXPENSE") is True

    def test_no_account_and_unknown_nature_never_certify_a_section(self):
        assert is_category_parent(None, nature="FIXED_ASSET") is False
        assert is_category_parent(PPE, nature="NOT_A_NATURE") is False
        assert is_category_parent({}, nature="FIXED_ASSET") is False


class TestClassifierProposalParent:
    @pytest.mark.asyncio
    async def test_receivable_parent_is_dropped_for_a_fixed_asset(self, monkeypatch):
        from app import classifier

        async def fake_exists(org, name):
            return AR if "receivable" in str(name).lower() else None

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)

        c = await classifier.classify_transaction(
            organization_id=uuid.uuid4(),
            intent="record_purchase",
            entities={
                "create_account": "Vehicles",
                "create_parent_name": "Accounts Receivable",
                "transaction_nature": "FIXED_ASSET",
                "item_description": "car",
            },
        )
        assert c.create_account_confirmed is True
        # a wrong-SECTION parent is never asserted — top-level instead
        assert c.proposed_parent_id is None

    @pytest.mark.asyncio
    async def test_ppe_parent_is_still_accepted(self, monkeypatch):
        from app import classifier

        async def fake_exists(org, name):
            return PPE if "property" in str(name).lower() else None

        monkeypatch.setattr("app.account_resolution.account_exists", fake_exists)

        c = await classifier.classify_transaction(
            organization_id=uuid.uuid4(),
            intent="record_purchase",
            entities={
                "create_account": "Vehicles",
                "create_parent_name": "Property, Plant & Equipment",
                "transaction_nature": "FIXED_ASSET",
                "item_description": "car",
            },
        )
        assert c.proposed_parent_id == PPE["id"]
