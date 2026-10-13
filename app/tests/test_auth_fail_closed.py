"""Auth FAIL-CLOSED hardening — pinned offline, no database, no server.

Covers the audit's required matrix:
  * invalid JWT                -> 401
  * stale/expired JWT          -> 401
  * dev header disabled        -> 401 (header-only request is unauthenticated)
  * dev header only in development (flag True + production -> 401)
Plus the new per-deployment approval gate:
  * legacy HS256 blocked by DEFAULT even with a correctly signed token
  * legacy HS256 accepted only with allow_legacy_jwt_secret_auth + real secret
  * boot validator: non-local + legacy approved + placeholder secret -> raises
"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import auth
from app.config import Settings


def _settings(**overrides) -> Settings:
    """Explicit kwargs beat env/.env bleed — every security field pinned."""
    base = dict(
        app_env="development",
        jwt_secret="change-me",
        allow_dev_header_auth=False,
        allow_legacy_jwt_secret_auth=False,
    )
    base.update(overrides)
    return Settings(**base)


def _patch_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: settings)


def _hs256_token(secret: str, *, exp_offset: int = 3600, sub: str | None = None) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": sub or str(uuid.uuid4()),
            "iat": now,
            "exp": now + exp_offset,
        },
        secret,
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# _decode_jwt — invalid / stale / legacy-approval matrix
# ---------------------------------------------------------------------------

def test_invalid_jwt_is_rejected(monkeypatch):
    _patch_settings(monkeypatch, _settings())
    with pytest.raises(HTTPException) as exc:
        auth._decode_jwt("not.a.jwt")
    assert exc.value.status_code == 401


def test_expired_jwt_is_rejected_with_expiry_detail(monkeypatch):
    secret = "a-real-legacy-secret-value"
    _patch_settings(
        monkeypatch,
        _settings(
            allow_legacy_jwt_secret_auth=True,
            jwt_secret=secret,
        ),
    )
    stale = _hs256_token(secret, exp_offset=-3600)  # already expired
    with pytest.raises(HTTPException) as exc:
        auth._decode_jwt(stale)
    assert exc.value.status_code == 401
    assert "expired" in str(exc.value.detail).lower()


def test_wrong_signature_is_rejected(monkeypatch):
    _patch_settings(
        monkeypatch,
        _settings(allow_legacy_jwt_secret_auth=True, jwt_secret="correct-secret"),
    )
    forged = _hs256_token("attacker-secret")
    with pytest.raises(HTTPException) as exc:
        auth._decode_jwt(forged)
    assert exc.value.status_code == 401


def test_legacy_hs256_blocked_by_default_even_with_correct_secret(monkeypatch):
    """The audit's core fix: a set secret alone must NOT enable Path B."""
    secret = "a-real-legacy-secret-value"
    _patch_settings(
        monkeypatch,
        _settings(jwt_secret=secret),  # allow_legacy_jwt_secret_auth=False
    )
    valid = _hs256_token(secret)
    with pytest.raises(HTTPException) as exc:
        auth._decode_jwt(valid)
    assert exc.value.status_code == 401


def test_legacy_hs256_accepted_with_explicit_approval_and_real_secret(monkeypatch):
    secret = "a-real-legacy-secret-value"
    _patch_settings(
        monkeypatch,
        _settings(allow_legacy_jwt_secret_auth=True, jwt_secret=secret),
    )
    payload = auth._decode_jwt(_hs256_token(secret))
    assert payload.get("sub")


def test_legacy_hs256_still_refuses_placeholder_secret(monkeypatch):
    _patch_settings(
        monkeypatch,
        _settings(allow_legacy_jwt_secret_auth=True, jwt_secret="change-me"),
    )
    with pytest.raises(HTTPException) as exc:
        auth._decode_jwt(_hs256_token("change-me"))
    assert exc.value.status_code == 401

# ---------------------------------------------------------------------------
# X-User-Id dev header — disabled by default, development-only
# ---------------------------------------------------------------------------

def test_dev_header_disabled_treats_header_only_request_as_unauthenticated(monkeypatch):
    _patch_settings(monkeypatch, _settings(allow_dev_header_auth=False))

    async def _run():
        return await auth.authenticate_user(authorization=None, x_user_id=str(uuid.uuid4()))

    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_run())
    assert exc.value.status_code == 401


def test_dev_header_ignored_in_production_even_when_flag_true(monkeypatch):
    """The double gate: the flag alone can NEVER open production."""
    for env in ("production", "staging", "test"):
        _patch_settings(
            monkeypatch,
            _settings(app_env=env, allow_dev_header_auth=True),
        )

        async def _run():
            return await auth.authenticate_user(
                authorization=None, x_user_id=str(uuid.uuid4())
            )

        import asyncio
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_run())
        assert exc.value.status_code == 401, f"header auth leaked in {env}"


def test_dev_header_works_only_when_development_and_opted_in(monkeypatch):
    _patch_settings(
        monkeypatch,
        _settings(app_env="development", allow_dev_header_auth=True),
    )
    user_id = uuid.uuid4()

    async def _run():
        return await auth.authenticate_user(
            authorization=None, x_user_id=str(user_id)
        )

    import asyncio
    ctx = asyncio.run(_run())
    assert ctx.user_id == user_id


def test_dev_header_warning_fires_once_per_process(monkeypatch):
    _patch_settings(
        monkeypatch,
        _settings(app_env="development", allow_dev_header_auth=True),
    )
    auth._HEADER_AUTH_WARNED["done"] = False
    try:
        assert auth._dev_header_auth_enabled() is True
        assert auth._HEADER_AUTH_WARNED["done"] is True  # warned
        assert auth._dev_header_auth_enabled() is True  # still works
        # The one-shot latch means a second warning was NOT re-armed.
        assert auth._HEADER_AUTH_WARNED["done"] is True
    finally:
        auth._HEADER_AUTH_WARNED["done"] = False


# ---------------------------------------------------------------------------
# Boot validator — jwt_secret required wherever the legacy path is approved
# ---------------------------------------------------------------------------

def test_boot_refuses_placeholder_secret_when_legacy_approved_in_production():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            allow_legacy_jwt_secret_auth=True,
            jwt_secret="change-me",
        )


def test_boot_refuses_empty_secret_when_legacy_approved_in_production():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            allow_legacy_jwt_secret_auth=True,
            jwt_secret="",
        )


def test_boot_allows_jwks_only_production_without_real_secret():
    """Default deployments (legacy path OFF) stay bootable — ES256/JWKS only."""
    s = Settings(
        app_env="production",
        allow_legacy_jwt_secret_auth=False,
        jwt_secret="change-me",
    )
    assert s.allow_legacy_jwt_secret_auth is False


def test_boot_allows_development_to_run_the_legacy_path_placeholder():
    s = Settings(
        app_env="development",
        allow_legacy_jwt_secret_auth=True,
        jwt_secret="change-me",
    )
    assert s.allow_legacy_jwt_secret_auth is True


def test_boot_accepts_real_secret_in_production_with_legacy_approved():
    s = Settings(
        app_env="production",
        allow_legacy_jwt_secret_auth=True,
        jwt_secret="a-strong-rotated-secret",
    )
    assert s.jwt_secret == "a-strong-rotated-secret"

