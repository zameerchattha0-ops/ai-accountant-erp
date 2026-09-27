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
