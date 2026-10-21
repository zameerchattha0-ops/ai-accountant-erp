import uuid
import pytest
from app.services import accounting_service
from app.repositories import account_repository as a_repo

@pytest.mark.asyncio
async def test_resolve_account_strict_matching_flags(monkeypatch):
    org_id = uuid.uuid4()
    mock_accounts = [
        {"id": "1", "name": "Cash", "code": "1000", "account_type": "ASSET"},
        {"id": "2", "name": "Cash Advance Payables", "code": "2010", "account_type": "LIABILITY"},
        {"id": "3", "name": "Accounts Receivable", "code": "1100", "account_type": "ASSET"},
        {"id": "4", "name": "Accounts Payable", "code": "2000", "account_type": "LIABILITY"},
    ]

    async def fake_search(organization_id, *, query, limit=50):
        q = query.lower()
        return [a for a in mock_accounts if q in a["name"].lower() or q in a["code"].lower()]

    async def fake_by_code(organization_id, *, code):
        for a in mock_accounts:
            if a["code"] == code:
                return a
        return None

    monkeypatch.setattr(a_repo, "search_accounts", fake_search)
    monkeypatch.setattr(a_repo, "get_account_by_code", fake_by_code)

    # 1. Normal resolution: exact match preferred
    res = await accounting_service.resolve_account(org_id, account_name="Cash")
    assert res is not None
    assert res["name"] == "Cash"
    assert res["account_type"] == "ASSET"

    # 2. Fuzzy match without exact_only falls back to results[0]
    res_fuzzy = await accounting_service.resolve_account(org_id, account_name="Cash Advance")
    assert res_fuzzy is not None
    assert res_fuzzy["name"] == "Cash Advance Payables"

    # 3. exact_only=True returns None when no exact match exists
    res_none = await accounting_service.resolve_account(org_id, account_name="Cash Advance", exact_only=True)
    assert res_none is None

    # 4. required_type filter strictly filters out non-matching types
    # Searching "Cash" with required_type="LIABILITY" should only match "Cash Advance Payables"
    res_liab = await accounting_service.resolve_account(org_id, account_name="Cash", required_type="LIABILITY")
    assert res_liab is not None
    assert res_liab["name"] == "Cash Advance Payables"
    assert res_liab["account_type"] == "LIABILITY"

    # 5. required_type + exact_only=True fails if exact name has wrong type
    res_mismatch = await accounting_service.resolve_account(org_id, account_name="Cash", required_type="LIABILITY", exact_only=True)
    assert res_mismatch is None

    # 6. account_code with required_type
    res_code_ok = await accounting_service.resolve_account(org_id, account_code="1000", required_type="ASSET")
    assert res_code_ok is not None
    assert res_code_ok["code"] == "1000"

    res_code_bad = await accounting_service.resolve_account(org_id, account_code="1000", required_type="LIABILITY")
    assert res_code_bad is None

