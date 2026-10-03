"""Shared test policy for the app suite.

The LLM DECISION layer (app/llm_classification.py) is a network stage that
decides by default in production. Tests are deterministic by contract:
every existing test pins BEHAVIOUR (rules, guards, shapes) with no
provider, so the layer is DISABLED here unless a test explicitly opts in
(``monkeypatch.setattr(settings, "llm_classification_enabled", True)`` +
a stub client). The layer's own tests do exactly that.
"""

import os

os.environ["LLM_CLASSIFICATION_ENABLED"] = "0"

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402

# The settings object may already be cached by an import above — force the
# flag off for the whole session regardless of import order.
get_settings.cache_clear()
_settings = get_settings()
_settings.llm_classification_enabled = False


@pytest.fixture(autouse=True)
def _keep_llm_classification_off_by_default(monkeypatch):
    """Opt-in per test: set the flag True inside the test body/fixture."""
    monkeypatch.setattr(_settings, "llm_classification_enabled", False)


@pytest.fixture(autouse=True)
def _no_live_database(request, monkeypatch):
    """UNIT SUITE CONTRACT: no test may read or write the live database.

    Every process boundary in this suite is stubbed (the LLM decision layer is
    disabled above; fetch_one/fetch_many/execute_planned_tool_calls are patched
    per test).  A test whose logic ADDS a database hop is not a test any more:
    its outcome depends on network latency and on the state of the PRODUCTION
    project, and because the agent's helpers are deliberately fail-open
    (best-effort lookups that swallow errors) the difference is SILENT.

    Production 2026-10-03: test_approved_turn_rescues_the_poisoned_confirmation
    flaked exactly this way — the asset-ledger pin read the live chart; a
    successful read returned [] (→ create_account ran first) while a timeout
    returned "unresolved" (→ no gap → no create_account), and the assertion
    failed only on the slow runs.

    So real access FAILS LOUDLY here.  A test that genuinely needs a database
    must opt in with ``@pytest.mark.allows_db`` and point at a disposable
    project — never production.
    """
    if request.node.get_closest_marker("allows_db") is not None:
        return

    import app.database as _db

    def _blocked_table(table_name):
        raise AssertionError(
            "REAL_DB_ACCESS: this unit test reached the live database "
            f"(table {table_name!r}).  Stub the seam it uses "
            "(monkeypatch.setattr(<repository>, '<function>', ...)) instead of "
            "letting the test depend on the network — see "
            "app/tests/conftest.py::_no_live_database.  If it is a genuine "
            "integration test, mark it @pytest.mark.allows_db."
        )

    def _blocked_client(*args, **kwargs):
        raise AssertionError(
            "REAL_DB_ACCESS: this unit test built a database client "
            "(app.database.get_service_client()).  Stub the caller's seam "
            "instead — see app/tests/conftest.py::_no_live_database."
        )

    monkeypatch.setattr(_db, "_table", _blocked_table)
    monkeypatch.setattr(_db, "get_service_client", _blocked_client)


# ---------------------------------------------------------------------------
# Shared offline seams for the harnesses that used to reach the live database
# (measured: 63 real calls across 6 files).  Request these from a file-level
# autouse fixture — see the six test modules that use them.
# ---------------------------------------------------------------------------
@pytest.fixture
def offline_org_lookups(monkeypatch):
    """Stub the agent's organisation / fiscal-year reads.

    ``organization_repository.get_current_financial_year`` and
    ``get_organization`` were the two biggest live-DB seams (45 of 63 calls):
    agent/validation paths read them fail-open, so a slow or failing round-trip
    silently changed behaviour.
    """
    from app.repositories import organization_repository as org_repo

    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(org_repo, "get_current_financial_year", _none)
    monkeypatch.setattr(org_repo, "get_organization", _none)


@pytest.fixture
def offline_account_lookups(monkeypatch):
    """Stub the classifier's account lookups (chart search / code lookup)."""
    from app.repositories import account_repository as acct_repo

    async def _no_rows(*args, **kwargs):
        return []

    async def _no_row(*args, **kwargs):
        return None

    monkeypatch.setattr(acct_repo, "search_accounts", _no_rows)
    monkeypatch.setattr(acct_repo, "get_account_by_code", _no_row)
