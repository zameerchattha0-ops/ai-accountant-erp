"""Probe: an unentitled model (403 AccessDenied.Unpurchased) is NOT retried.

Production 2026-10-02: EVERY Qwen model answered 403 AccessDenied.Unpurchased,
so the shipped 2-model chain burned 6 HTTP calls + backoff on EVERY provider
round before Gemini was reached.  This counts the calls.

Usage: python scripts/probe_entitlement_failfast.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.qwen_client as qc
from app.qwen_client import (
    ProviderNotEntitled,
    ProviderRateLimited,
    QwenClient,
    is_entitlement_error,
)


class _Resp:
    status_code = 403
    text = '{"error":{"code":"AccessDenied.Unpurchased"}}'
    headers: dict = {}


_CALLS = {"n": 0}


class _Client:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *a, **kw):
        _CALLS["n"] += 1
        return _Resp()


async def main() -> int:
    print(
        "is_entitlement_error(403, AccessDenied.Unpurchased) =",
        is_entitlement_error(403, _Resp.text),
    )
    qc.httpx.AsyncClient = _Client
    qc.load_constitution = lambda: ""
    client = QwenClient(
        api_key="k", base_url="https://example.invalid/v1", model="qwen3.6-plus"
    )
    try:
        await client._chat_completion([{"role": "user", "content": "hi"}], None)
    except ProviderNotEntitled as exc:
        print(f"raised {type(exc).__name__} after {_CALLS['n']} HTTP call(s)")
    except ProviderRateLimited as exc:
        print(f"WRONG TYPE {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))