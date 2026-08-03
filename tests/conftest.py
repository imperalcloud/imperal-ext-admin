"""Shared fixtures for admin-extension unit tests — no network, no DB.

The admin extension imports its gateway helper as ``_gw_request`` INTO each
handler module (``from app import ... _gw_request ...``). Tests therefore
monkeypatch the name on the HANDLER module (where it is called), never on
``app`` (where it is merely defined) — patching the wrong one lets the real
helper run and hit the live Auth GW during a test run.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from imperal_sdk.testing import MockContext  # noqa: E402


class GatewaySpy:
    """Records every ``_gw_request`` call and replays canned responses.

    Assertions can then be made about WHICH endpoint was hit, with WHICH
    method and body — not merely about the handler's return value. A test
    that only checks the return value passes even when the handler writes
    to the wrong store, which is exactly the class of bug this suite exists
    to catch.
    """

    def __init__(self, responses: dict | None = None, default: dict | None = None):
        # responses: {(METHOD, path_substring): response_dict}
        self.responses = responses or {}
        self.default = default if default is not None else {}
        self.calls: list[dict] = []

    async def __call__(self, method, path, data=None, acting=None):
        self.calls.append(
            {"method": method.upper(), "path": path, "data": data, "acting": acting}
        )
        for (m, frag), resp in self.responses.items():
            if m.upper() == method.upper() and frag in path:
                return resp
        return self.default

    # ── query helpers ────────────────────────────────────────────────── #

    def calls_to(self, fragment: str, method: str | None = None) -> list[dict]:
        return [
            c
            for c in self.calls
            if fragment in c["path"]
            and (method is None or c["method"] == method.upper())
        ]

    def hit(self, fragment: str, method: str | None = None) -> bool:
        return bool(self.calls_to(fragment, method))

    @property
    def summary(self) -> str:
        return " | ".join(f"{c['method']} {c['path']}" for c in self.calls) or "(no calls)"


@pytest.fixture
def ctx():
    """MockContext whose ``_tenant_id(ctx)`` resolves to 'default'."""
    return MockContext(user_id="imp_u_TESTUSER")


@pytest.fixture
def spy():
    return GatewaySpy
