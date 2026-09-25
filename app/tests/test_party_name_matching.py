"""Separator-insensitive party matching — production session ``8b2f14dd``.

The incident: the reasoning layer's ``parties`` evidence returned EMPTY for
"Alareesh Engineering" while customer ``Al-Areesh Engineering`` existed
(created the SAME afternoon as the session).  ILIKE '%alareesh%' never
matches 'Al-Areesh Engineering', and the old normaliser kept the hyphen as
a wall — so ``classify_party_match`` said NONE, the model asked a
clarification the books could already answer, and open_receivables was
EMPTY for the same reason (INV-000006 existed).

Fix under test (app/name_matching.py + repository fallbacks):
* ``name_key`` strips every separator, so hyphen/case/punctuation variants
  compare equal;
* ``search_customers``/``search_suppliers`` fall back to a bounded,
  name_key-ranked candidate read when the strict ILIKE search misses;
* ``classify_party_match`` and evidence ``_matches`` share the same key.
"""

import uuid

import pytest

import app.repositories.customer_repository as cust_repo
import app.repositories.supplier_repository as sup_repo
from app.books_evidence import _matches
from app.name_matching import name_key, normalized_matches
from app.reasoning import PartyMatchState, classify_party_match, normalize_entity_name

ORG = uuid.UUID("4f20f43c-bb3b-4747-abe1-02d9380884df")
ALAREESH = {
    "id": "237bed12-3ceb-4c2b-9cfb-bdcfad589da5",
    "name": "Al-Areesh Engineering",
    "customer_code": "C-0042",
    "email": None,
    "phone": None,
    "is_active": True,
}


class TestNameKey:
    def test_hyphen_variant_equal(self):
        assert name_key("Al-Areesh Engineering") == name_key("Alareesh Engineering")

    def test_case_space_punct_insensitive(self):
        assert name_key(" Al-Areesh, (Eng.) ") == name_key("alareesheng")

    def test_none_and_empty_are_empty_keys(self):
        assert name_key(None) == ""
        assert name_key("") == ""


class TestNormalizedMatches:
    def test_exact_key_ranks_first(self):
        other = {"name": "Areesh Engineering Services"}
        rows = normalized_matches([other, ALAREESH], "Alareesh Engineering")
        assert [r["name"] for r in rows] == ["Al-Areesh Engineering"]

    def test_query_with_extra_words_still_finds_name(self):
        # The merged extraction wording that reached evidence in the incident.
        rows = normalized_matches([ALAREESH], "alareesh engineering in cash")
        assert [r["name"] for r in rows] == ["Al-Areesh Engineering"]

    def test_non_matching_rows_excluded(self):
        assert normalized_matches([ALAREESH], "blue ridge trading") == []

    def test_too_short_query_never_fuzzy_matches(self):
        assert normalized_matches([ALAREESH], "al") == []


class TestClassifyPartyMatch:
    def test_hyphen_variant_is_exact(self):
        state, rows = classify_party_match([ALAREESH], "Alareesh Engineering")
        assert state is PartyMatchState.EXACT
        assert rows == [ALAREESH]

    def test_normalize_delegates_to_name_key(self):
        assert normalize_entity_name("Al-Areesh Engineering") == name_key(
            "Al-Areesh Engineering"
        )


class TestRepositoryFallback:
    @pytest.mark.asyncio
    async def test_strict_miss_falls_back_and_matches(self, monkeypatch):
        async def _empty(*a, **k):
            return []

        async def _candidates(*a, **k):
            return [ALAREESH]

        monkeypatch.setattr(cust_repo, "search_ilike", _empty)
        monkeypatch.setattr(cust_repo, "fetch_many", _candidates)
        rows = await cust_repo.search_customers(ORG, query="Alareesh Engineering")
        assert rows == [ALAREESH]

    @pytest.mark.asyncio
    async def test_strict_hit_short_circuits(self, monkeypatch):
        async def _hit(*a, **k):
            return [ALAREESH]

        async def _boom(*a, **k):
            raise AssertionError("fallback must not run when ILIKE hits")

        monkeypatch.setattr(cust_repo, "search_ilike", _hit)
        monkeypatch.setattr(cust_repo, "fetch_many", _boom)
        rows = await cust_repo.search_customers(ORG, query="areesh")
        assert rows == [ALAREESH]

    @pytest.mark.asyncio
    async def test_no_match_stays_empty(self, monkeypatch):
        async def _empty(*a, **k):
            return []

        async def _candidates(*a, **k):
            return [ALAREESH]

        monkeypatch.setattr(cust_repo, "search_ilike", _empty)
        monkeypatch.setattr(cust_repo, "fetch_many", _candidates)
        rows = await cust_repo.search_customers(ORG, query="blue ridge trading")
        assert rows == []

    @pytest.mark.asyncio
    async def test_supplier_fallback_symmetric(self, monkeypatch):
        supplier = {"id": "s" * 8, "name": "Al-Areesh Engineering", "is_active": True}

        async def _empty(*a, **k):
            return []

        async def _candidates(*a, **k):
            return [supplier]

        monkeypatch.setattr(sup_repo, "search_ilike", _empty)
        monkeypatch.setattr(sup_repo, "fetch_many", _candidates)
        rows = await sup_repo.search_suppliers(ORG, query="Alareesh Engineering")
        assert rows == [supplier]


class TestEvidenceMatches:
    def test_hyphen_term_matches_record(self):
        assert _matches({"name": "Al-Areesh Engineering"}, ["alareesh"]) is True

    def test_plain_term_still_matches(self):
        assert _matches({"name": "Al-Areesh Engineering"}, ["engineering"]) is True

    def test_non_match_is_false(self):
        assert _matches({"name": "Al-Areesh Engineering"}, ["blue ridge"]) is False

    def test_no_terms_matches_everything(self):
        assert _matches({"name": "anything"}, []) is True
