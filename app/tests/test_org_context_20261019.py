"""Per-business org context: freshness, tenant isolation, prompt wiring.

The three guarantees the design promised (2026-10-19):
* REAL-TIME — the profile is a fresh read each call: a product added
  after build A is present in build B;
* TENANT ISOLATION — org A's profile never contains org B rows even when
  names collide, and EVERY fetch carries the organization_id filter;
* PROMPT WIRING — the extractor, classifier decide and questionnaire
  authorizer actually receive the profile block (or its payload key).
"""
import uuid

import pytest

import app.org_context as org_context_mod
from app.org_context import business_profile, render_profile

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000000b")

_ROWS = {
    ("products", str(ORG_A)): [
        {"name": "chairs", "product_code": "PRD-A1",
         "is_stock_tracked": True, "cost_price": 9000},
    ],
    ("products", str(ORG_B)): [
        {"name": "chairs", "product_code": "PRD-B9",
         "is_stock_tracked": True, "cost_price": 1111},
    ],
    ("customers", str(ORG_A)): [{"name": "Ahmed Traders"}],
    ("customers", str(ORG_B)): [{"name": "Ahmed Traders"}],
    ("suppliers", str(ORG_A)): [],
    ("suppliers", str(ORG_B)): [],
    ("accounts", str(ORG_A)): [{"code": "1200", "name": "Inventory",
                                "account_type": "ASSET"}],
    ("accounts", str(ORG_B)): [{"code": "9999", "name": "OtherCo Ledger",
                                "account_type": "ASSET"}],
    ("invoices", str(ORG_A)): [{"invoice_number": "INV-000014",
                                "total": 24000}],
    ("invoices", str(ORG_B)): [{"invoice_number": "INV-999999",
                                "total": 1}],
    ("purchase_bills", str(ORG_A)): [{"bill_number": "PUR-000013",
                                      "total": 45000}],
    ("purchase_bills", str(ORG_B)): [],
}
_fetch_log = []


async def _spy_fetch(table, *, filters=None, **_kw):
    org = (filters or {}).get("organization_id")
    _fetch_log.append((table, org))
    return list(_ROWS.get((table, str(org)), []))


@pytest.fixture(autouse=True)
def _patch_fetch(monkeypatch):
    _fetch_log.clear()
    monkeypatch.setattr(org_context_mod, "fetch_many", _spy_fetch)


@pytest.mark.asyncio
async def test_every_fetch_carries_the_org_filter():
    await business_profile(ORG_A)
    assert _fetch_log, "no fetches ran"
    for table, org in _fetch_log:
        assert org == str(ORG_A), f"{table} fetched without organization_id"


@pytest.mark.asyncio
async def test_profile_is_fresh_on_the_next_call():
    first = await business_profile(ORG_A)
    assert not any(p.get("name") == "standing lamp"
                   for p in first["products"])
    _ROWS[("products", str(ORG_A))].append(
        {"name": "standing lamp", "product_code": "PRD-A2",
         "is_stock_tracked": True, "cost_price": 7000}
    )
    try:
        second = await business_profile(ORG_A)
        assert any(p.get("name") == "standing lamp"
                   for p in second["products"])
    finally:
        _ROWS[("products", str(ORG_A))].pop()


@pytest.mark.asyncio
async def test_org_a_profile_never_contains_org_b_rows():
    prof_a = await business_profile(ORG_A)
    text = render_profile(prof_a)
    assert "PRD-A1" in text
    assert "PRD-B9" not in text          # same product name, other tenant
    assert "INV-999999" not in text
    assert "OtherCo Ledger" not in text
    assert "INV-000014" in text and "PUR-000013" in text


def test_render_profile_is_compact_and_labelled():
    text = render_profile({
        "products": [{"name": "chairs", "product_code": "PRD-A1",
                      "is_stock_tracked": True, "cost_price": 9000}],
        "customers": ["abc technologies"],
        "suppliers": ["SHABBIR FURNITURES"],
        "accounts": [{"code": "1200", "name": "Inventory"}],
        "invoices": [], "bills": [],
    })
    assert text.startswith("\n\nYOUR BUSINESS")
    assert "chairs (PRD-A1, STOCK) cost=9000" in text
    assert "abc technologies" in text
    assert render_profile({}) == ""


# --- prompt wiring ---------------------------------------------------------
@pytest.mark.asyncio
async def test_stage2_extractor_prompt_carries_the_profile(monkeypatch):
    class _Flags:
        llm_preliminary_extraction_enabled = True
        llm_preliminary_extraction_timeout = 5.0

    monkeypatch.setattr("app.config.get_settings", lambda: _Flags())
    captured = {}

    class _Client:
        async def generate_text_light(self, *, prompt):
            captured["prompt"] = prompt
            return "{}"

    from app.llm_extraction import enrich_preliminary

    _prelim, audit = await enrich_preliminary(
        user_message="returned 1 chair against INV-000014",
        preliminary={"literals": {}},
        client=_Client(),
        org_context="\n\nYOUR BUSINESS (live, org-scoped, this turn):\n"
                     "- Recent documents: invoice INV-000014 (24000)",
    )
    assert "YOUR BUSINESS" in captured["prompt"]
    assert "INV-000014" in captured["prompt"]
    assert audit["llm"] != "skipped_disabled"


def test_classifier_prompt_carries_the_profile():
    from app.llm_classification import CandidateSet, build_prompt

    prompt = build_prompt(
        intent="create_credit_note",
        entities={"amount": 8000},
        message="returned 1 chair",
        nature_hint=None,
        candidates=CandidateSet(),
        org_context="YOUR BUSINESS: invoice INV-000014 (24000)",
    )
    assert "YOUR BUSINESS" in prompt


def test_questionnaire_author_prompt_carries_the_profile():
    from app.questionnaire import _authored_questionnaire_prompt

    prompt = _authored_questionnaire_prompt(
        user_request="returned 1 chair",
        intent="create_credit_note",
        missing_fields=["transaction_date"],
        org_context="YOUR BUSINESS: customers abc technologies",
    )
    assert "YOUR_BUSINESS" in prompt
    assert "abc technologies" in prompt

